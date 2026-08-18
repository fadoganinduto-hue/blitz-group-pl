"""The sign-in gate.

The property that matters is ordering: an unauthenticated visitor must never
reach code that holds SharePoint credentials. A password box rendered after the
data has loaded protects the screen, not the workbook.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from streamlit_app import auth

ROOT = Path(__file__).resolve().parent.parent


class _FakeUser:
    def __init__(self, logged_in=False, email=None, name=None):
        self.is_logged_in = logged_in
        self.email = email
        self.name = name


@pytest.fixture
def stub(monkeypatch):
    """A recording stand-in for the Streamlit calls auth.py makes."""
    calls: dict = {"stopped": False, "errors": [], "buttons": []}

    class _Cols(list):
        pass

    monkeypatch.setattr(auth.st, "stop", lambda: calls.__setitem__("stopped", True))
    monkeypatch.setattr(auth.st, "error", lambda msg: calls["errors"].append(msg))
    monkeypatch.setattr(auth.st, "button", lambda label, **kw: calls["buttons"].append(label))
    monkeypatch.setattr(auth.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(auth.st, "caption", lambda *a, **k: None)

    class _Ctx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(auth.st, "columns", lambda spec, **k: [_Ctx(), _Ctx(), _Ctx()])
    return calls


def _configure(monkeypatch, **overrides):
    section = {
        "client_id": "0e6e2a05-275a-4367-9847-3f096d1c12ea",
        "client_secret": "x",
        "redirect_uri": "https://blitz-group-pl.streamlit.app/oauth2callback",
        "cookie_secret": "y",
    }
    section.update(overrides)
    monkeypatch.setattr(auth.st, "secrets", {"auth": section})


# ---------------------------------------------------------------------------
# Unconfigured — must change nothing
# ---------------------------------------------------------------------------

def test_no_auth_section_means_no_gate(monkeypatch, stub):
    """Local development stays one command, and an app already behind Azure's
    own authentication does not get a second, redundant login."""
    monkeypatch.setattr(auth.st, "secrets", {})
    monkeypatch.setattr(auth.st, "user", _FakeUser(logged_in=False))

    auth.require_login()

    assert stub["stopped"] is False
    assert stub["buttons"] == []


def test_a_half_written_auth_section_does_not_count_as_configured(monkeypatch):
    """A client_id with no redirect_uri cannot complete a login. Treating it as
    configured would lock everyone out of a dashboard that still works."""
    monkeypatch.setattr(auth.st, "secrets", {"auth": {"client_id": "abc"}})
    assert auth.is_configured() is False


def test_secrets_that_raise_do_not_take_the_app_down(monkeypatch):
    class _Explodes:
        def get(self, *a, **k):
            raise RuntimeError("no secrets backend")

    monkeypatch.setattr(auth.st, "secrets", _Explodes())
    assert auth.is_configured() is False


# ---------------------------------------------------------------------------
# Configured — the gate closes
# ---------------------------------------------------------------------------

def test_an_anonymous_visitor_is_stopped(monkeypatch, stub):
    _configure(monkeypatch)
    monkeypatch.setattr(auth.st, "user", _FakeUser(logged_in=False))

    auth.require_login()

    assert stub["stopped"] is True
    assert any("Sign in" in b for b in stub["buttons"])


def test_a_signed_in_blitz_account_passes(monkeypatch, stub):
    _configure(monkeypatch)
    monkeypatch.setattr(
        auth.st, "user", _FakeUser(True, "fado@rideblitz.com", "FG")
    )

    auth.require_login()

    assert stub["stopped"] is False


def test_the_login_screen_says_nothing_about_the_numbers(monkeypatch):
    """A login page that names the entities or the period has already told an
    outsider something."""
    source = (ROOT / "streamlit_app" / "auth.py").read_text()
    screen = source[source.index("def _render_login_screen"):source.index("def render_account_control")]
    for leak in ("Blitz Electric Mobility —", "Revenue", "EBITDA", "Borzo", "TheLorry", "2026"):
        if leak == "Blitz Electric Mobility —":
            continue  # the company name is on the door; the figures are not
        assert leak not in screen, f"login screen mentions {leak!r}"


# ---------------------------------------------------------------------------
# Domain allowlist — guests live in the tenant too
# ---------------------------------------------------------------------------

def test_no_allowlist_permits_the_whole_tenant(monkeypatch):
    _configure(monkeypatch)
    assert auth.is_permitted("anyone@rideblitz.com") == (True, "")


def test_an_allowlist_keeps_guest_accounts_out(monkeypatch):
    """Entra guests are members of the tenant and would otherwise pass."""
    _configure(monkeypatch, allowed_domains=["rideblitz.com"])
    allowed, reason = auth.is_permitted("consultant@othercompany.com")
    assert allowed is False
    assert "othercompany.com" in reason


def test_the_allowlist_admits_the_listed_domain(monkeypatch):
    _configure(monkeypatch, allowed_domains=["rideblitz.com"])
    assert auth.is_permitted("fado@rideblitz.com")[0] is True


@pytest.mark.parametrize(
    "raw", [["rideblitz.com"], "rideblitz.com", "@rideblitz.com", "rideblitz.com, borzo.id"]
)
def test_the_allowlist_accepts_the_shapes_people_actually_write(monkeypatch, raw):
    _configure(monkeypatch, allowed_domains=raw)
    assert auth.is_permitted("fado@rideblitz.com")[0] is True


def test_domain_matching_is_case_insensitive(monkeypatch):
    _configure(monkeypatch, allowed_domains=["RideBlitz.com"])
    assert auth.is_permitted("FADO@RIDEBLITZ.COM")[0] is True


def test_a_lookalike_domain_is_rejected(monkeypatch):
    """notrideblitz.com must not pass a check for rideblitz.com."""
    _configure(monkeypatch, allowed_domains=["rideblitz.com"])
    assert auth.is_permitted("attacker@notrideblitz.com")[0] is False
    assert auth.is_permitted("attacker@rideblitz.com.evil.net")[0] is False


def test_an_account_with_no_email_is_rejected_when_an_allowlist_is_set(monkeypatch):
    _configure(monkeypatch, allowed_domains=["rideblitz.com"])
    assert auth.is_permitted(None)[0] is False


def test_a_signed_in_outsider_is_stopped_not_shown_the_dashboard(monkeypatch, stub):
    _configure(monkeypatch, allowed_domains=["rideblitz.com"])
    monkeypatch.setattr(
        auth.st, "user", _FakeUser(True, "consultant@othercompany.com", "Guest")
    )

    auth.require_login()

    assert stub["stopped"] is True
    assert stub["errors"], "the visitor must be told why"


# ---------------------------------------------------------------------------
# Ordering — the property the whole module exists for
# ---------------------------------------------------------------------------

def test_the_gate_runs_before_any_data_source_is_built():
    """If build_source() ran first, an anonymous request would already have
    reached code holding tenant-wide SharePoint credentials."""
    source = (ROOT / "app.py").read_text()

    # Locate the CALL, not the first mention. "require_login()" also appears in
    # the comment above it, and anchoring on that made this test pass for the
    # wrong reason — it stayed green with the gate moved to the end of the file.
    gate_match = re.search(r"^require_login\(\)$", source, re.M)
    assert gate_match, "app.py has no top-level require_login() call"
    gate = gate_match.start()

    for name in ("build_source", "fetch_workbook", "load_sheets_from_bytes"):
        # Call sites only — a `def` above the gate is a definition, and an
        # import list is neither.
        for match in re.finditer(rf"(?<!def ){re.escape(name)}\(", source):
            start = match.start()
            preceding = source[:start].rstrip()
            if preceding.endswith(("import (", ",")):
                continue
            assert start > gate, f"{name}() is called before require_login()"


def test_the_gate_is_not_wrapped_in_a_conditional():
    """`if something: require_login()` is how a gate quietly stops gating."""
    source = (ROOT / "app.py").read_text()
    line = next(ln for ln in source.splitlines() if ln.strip() == "require_login()")
    assert not line.startswith((" ", "\t")), "require_login() must run unconditionally"


# ---------------------------------------------------------------------------
# The documented configuration must be the safe one
# ---------------------------------------------------------------------------

def test_the_documented_issuer_is_tenant_scoped_not_common():
    """`common` admits any Microsoft account on earth, personal ones included."""
    doc = (ROOT / "deploy" / "STREAMLIT_CLOUD.md").read_text()
    issuer = next(ln for ln in doc.splitlines() if "server_metadata_url =" in ln)
    assert "/common/" not in issuer
    assert "c13caea6-fef3-4328-bba6-4ff95ae9badc" in issuer


def test_the_documented_secrets_keep_bare_keys_above_every_section():
    """A bare TOML key belongs to the preceding section header. Below
    [workbook], AZURE_TENANT_ID silently becomes workbook.AZURE_TENANT_ID."""
    doc = (ROOT / "deploy" / "STREAMLIT_CLOUD.md").read_text()
    block = doc[doc.index("AZURE_TENANT_ID ="):doc.index("```", doc.index("AZURE_TENANT_ID ="))]
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    first_section = next(i for i, ln in enumerate(lines) if ln.startswith("["))
    bare_azure = [i for i, ln in enumerate(lines) if ln.startswith("AZURE_")]
    assert all(i < first_section for i in bare_azure)


def test_the_documented_redirect_uri_has_the_callback_path():
    """Without /oauth2callback, sign-in fails with a mismatch error that names
    no cause."""
    doc = (ROOT / "deploy" / "STREAMLIT_CLOUD.md").read_text()
    assert doc.count("/oauth2callback") >= 3


def test_no_real_client_secret_is_written_into_the_docs():
    """Tenant and client IDs are fine to document — they identify, they do not
    authenticate. A secret VALUE is the one thing that must stay a placeholder.
    """
    placeholders = ("the-secret", "the-64-character", "paste", "your-", "xxx", "<")

    for name in ("STREAMLIT_CLOUD.md", "README.md", ".env.azure.example"):
        text = (ROOT / "deploy" / name).read_text()
        for line in text.splitlines():
            stripped = line.strip()
            if not re.match(r"^(AZURE_CLIENT_SECRET|client_secret|cookie_secret)\s*=", stripped):
                continue
            value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
            assert any(p in value.lower() for p in placeholders), (
                f"{name} line {stripped!r} looks like a real secret"
            )
