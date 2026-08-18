"""Blitz sign-in, via Streamlit's own OIDC support.

The alternative that keeps coming up is a shared password checked inside the
app. It is worse than it looks, for three reasons that have nothing to do with
how strong the password is:

* **It gates the screen, not the data.** By the time a password box renders,
  the Python process is already running and already holds a client secret with
  tenant-wide read access to SharePoint. The password is one bug — a stray
  ``st.write``, an unhandled exception page, a mis-ordered ``st.stop()`` — away
  from the workbook. Sign-in here runs before any source is built, so an
  unauthenticated visitor never reaches code that can touch Graph.
* **It cannot be revoked for one person.** Someone leaves and the only remedy
  is to change the password and re-tell everyone who is left. With Entra,
  disabling their Microsoft 365 account is the remedy, and it is a step
  offboarding already performs.
* **It answers "who saw the group P&L in July?" with "someone".** ``st.user``
  carries a real identity, so the question has an answer.

Configuration lives under ``[auth]`` in secrets. When it is absent this module
does nothing at all — local development stays a single command, and a
deployment already sitting behind Azure App Service's built-in authentication
does not get a second, redundant login.
"""

from __future__ import annotations

import streamlit as st

# Only these email domains may sign in, when set. Entra's single-tenant issuer
# is the real boundary; this is a second, readable one for guest accounts,
# which DO live in the tenant and would otherwise pass.
ALLOWED_DOMAINS_KEY = "allowed_domains"


def is_configured() -> bool:
    """True when an ``[auth]`` section is present in secrets."""
    try:
        section = st.secrets.get("auth", {}) or {}
        return bool(section.get("client_id") and section.get("redirect_uri"))
    except Exception:  # noqa: BLE001 - secrets access varies by host
        return False


def _allowed_domains() -> list[str]:
    try:
        raw = (st.secrets.get("auth", {}) or {}).get(ALLOWED_DOMAINS_KEY, [])
    except Exception:  # noqa: BLE001
        return []
    if isinstance(raw, str):
        raw = [part for part in raw.replace(",", " ").split() if part]
    return [str(d).strip().lower().lstrip("@") for d in raw if str(d).strip()]


def is_permitted(email: str | None) -> tuple[bool, str]:
    """Return (allowed, reason). An empty allowlist permits the whole tenant."""
    domains = _allowed_domains()
    if not domains:
        return True, ""
    if not email:
        return False, "Your account did not return an email address."
    domain = email.rsplit("@", 1)[-1].lower()
    if domain in domains:
        return True, ""
    return False, (
        f"{email} is outside the domains allowed for this dashboard "
        f"({', '.join(domains)})."
    )


def require_login() -> None:
    """Block the page until the visitor has signed in with a Blitz account.

    A no-op when ``[auth]`` is not configured. Call this BEFORE building any
    data source: everything after it runs only for a signed-in user, and
    ``st.stop()`` guarantees there is no "after it" for anyone else.
    """
    if not is_configured():
        return

    if not getattr(st.user, "is_logged_in", False):
        _render_login_screen()
        st.stop()

    allowed, reason = is_permitted(getattr(st.user, "email", None))
    if not allowed:
        st.error(reason)
        st.button("Sign in as someone else", on_click=st.logout)
        st.stop()


def _render_login_screen() -> None:
    """The whole page, for someone who has not signed in yet.

    Deliberately says nothing about the numbers behind it — not the entities,
    not the period, not the figures. A login screen that reports what it is
    protecting has already told an outsider something.
    """
    st.markdown(
        """
        <div style="max-width:420px;margin:12vh auto 0 auto;text-align:center;">
          <div style="font-size:26px;font-weight:800;letter-spacing:-0.5px;">
            Group P&amp;L
          </div>
          <div style="font-size:13px;color:#4D4D4D;margin-top:6px;">
            Blitz Electric Mobility — internal
          </div>
          <div style="font-size:13px;color:#4D4D4D;margin-top:22px;">
            Sign in with your Blitz Microsoft account to continue.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    left, middle, right = st.columns([1, 1, 1])
    with middle:
        st.button(
            "Sign in with Microsoft",
            on_click=st.login,
            type="primary",
            width="stretch",
        )


def render_account_control() -> None:
    """Show who is signed in, and offer a way out. Safe to call unconditionally."""
    if not is_configured() or not getattr(st.user, "is_logged_in", False):
        return

    name = getattr(st.user, "name", None) or getattr(st.user, "email", "Signed in")
    st.caption(f":material/account_circle: {name}")
    st.button("Sign out", on_click=st.logout, width="stretch")
