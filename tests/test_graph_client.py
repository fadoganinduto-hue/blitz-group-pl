"""Tests for the Microsoft Graph client — request shape and error translation.

Real Azure credentials are never used here. What matters is that the URLs are
built correctly and that failures produce messages a finance user can act on,
rather than a bare HTTP status.
"""
from __future__ import annotations

import pytest

from streamlit_app.data import graph_client as gc
from streamlit_app.data.graph_client import GraphError, SharePointConfig

CONFIG = SharePointConfig(
    tenant_id="tid", client_id="cid", client_secret="secret",
    hostname="blitz.sharepoint.com", site_path="/sites/Finance",
    file_path="Shared Documents/Group PL/Group_PL_2026_Upload.xlsx",
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", content=b""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture(autouse=True)
def _clear_token_cache():
    gc._token_cache.clear()
    yield
    gc._token_cache.clear()


@pytest.fixture
def fake_token(monkeypatch):
    monkeypatch.setattr(gc, "_acquire_token", lambda config: "fake-token")


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def test_locate_file_builds_correct_urls_and_strips_library_prefix(monkeypatch, fake_token):
    """Graph's drive root is already inside 'Shared Documents' — don't repeat it."""
    seen: list[str] = []

    def fake_get(url, token, **kwargs):
        seen.append(url)
        if "/drive/root:" in url:
            return FakeResponse(payload={
                "name": "Group_PL_2026_Upload.xlsx",
                "id": "ITEM1", "size": 609772, "eTag": 'W/"tag-1"',
                "lastModifiedDateTime": "2026-08-14T10:02:08Z",
                "webUrl": "https://blitz.sharepoint.com/sites/Finance/x.xlsx",
                "parentReference": {"driveId": "DRIVE1"},
                "lastModifiedBy": {"user": {"displayName": "Fado Ganinduto"}},
            })
        return FakeResponse(payload={"id": "SITE1"})

    monkeypatch.setattr(gc, "_get", fake_get)
    remote = gc.locate_file(CONFIG)

    assert seen[0] == "https://graph.microsoft.com/v1.0/sites/blitz.sharepoint.com:/sites/Finance"
    assert "Shared%20Documents" not in seen[1], "library prefix must be stripped"
    assert seen[1].endswith("/sites/SITE1/drive/root:/Group%20PL/Group_PL_2026_Upload.xlsx")

    assert remote.drive_id == "DRIVE1"
    assert remote.item_id == "ITEM1"
    assert remote.etag == 'W/"tag-1"'
    assert remote.modified_by == "Fado Ganinduto"
    assert remote.last_modified is not None
    assert remote.last_modified.year == 2026


def test_download_uses_drive_item_content_endpoint(monkeypatch, fake_token):
    captured: list[str] = []

    def fake_get(url, token, **kwargs):
        captured.append(url)
        return FakeResponse(content=b"PK\x03\x04workbook")

    monkeypatch.setattr(gc, "_get", fake_get)
    remote = gc.RemoteFile("w.xlsx", "DRIVE1", "ITEM1", None, None, "", "")
    assert gc.download_file(CONFIG, remote) == b"PK\x03\x04workbook"
    assert captured[0].endswith("/drives/DRIVE1/items/ITEM1/content")


# ---------------------------------------------------------------------------
# Error translation — the part a finance user actually reads
# ---------------------------------------------------------------------------

def test_403_names_the_admin_consent_problem(monkeypatch, fake_token):
    monkeypatch.setattr(gc, "_get", lambda *a, **k: FakeResponse(status_code=403, text="denied"))
    with pytest.raises(GraphError, match="ADMIN CONSENT"):
        gc.locate_file(CONFIG)


def test_404_points_at_the_path_settings(monkeypatch, fake_token):
    monkeypatch.setattr(gc, "_get", lambda *a, **k: FakeResponse(status_code=404, text="nope"))
    with pytest.raises(GraphError, match="file_path"):
        gc.locate_file(CONFIG)


def test_bad_secret_explains_the_value_vs_id_trap(monkeypatch):
    monkeypatch.setattr(gc.requests, "post", lambda *a, **k: FakeResponse(
        status_code=401,
        payload={"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret provided."},
    ))
    with pytest.raises(GraphError, match="Secret ID is not the value"):
        gc._acquire_token(CONFIG)


def test_wrong_tenant_is_named(monkeypatch):
    monkeypatch.setattr(gc.requests, "post", lambda *a, **k: FakeResponse(
        status_code=400,
        payload={"error": "invalid_request", "error_description": "AADSTS90002: Tenant not found."},
    ))
    with pytest.raises(GraphError, match="tenant_id"):
        gc._acquire_token(CONFIG)


# ---------------------------------------------------------------------------
# Token caching
# ---------------------------------------------------------------------------

def test_token_is_cached_between_calls(monkeypatch):
    calls = {"n": 0}

    def fake_post(*args, **kwargs):
        calls["n"] += 1
        return FakeResponse(payload={"access_token": "tok", "expires_in": 3600})

    monkeypatch.setattr(gc.requests, "post", fake_post)
    assert gc._acquire_token(CONFIG) == "tok"
    assert gc._acquire_token(CONFIG) == "tok"
    assert calls["n"] == 1, "token should be reused, not re-fetched on every call"


def test_expiring_token_is_refetched(monkeypatch):
    calls = {"n": 0}

    def fake_post(*args, **kwargs):
        calls["n"] += 1
        return FakeResponse(payload={"access_token": f"tok{calls['n']}", "expires_in": 30})

    monkeypatch.setattr(gc.requests, "post", fake_post)
    assert gc._acquire_token(CONFIG) == "tok1"
    # expires_in 30s is inside the 120s skew window, so it must not be reused
    assert gc._acquire_token(CONFIG) == "tok2"


def test_secret_never_appears_in_error_messages(monkeypatch):
    monkeypatch.setattr(gc.requests, "post", lambda *a, **k: FakeResponse(
        status_code=400, payload={"error": "bad", "error_description": "generic failure"},
    ))
    with pytest.raises(GraphError) as excinfo:
        gc._acquire_token(CONFIG)
    assert CONFIG.client_secret not in str(excinfo.value)


# ---------------------------------------------------------------------------
# URL addressing (the /shares endpoint used by the existing dashboards)
# ---------------------------------------------------------------------------

URL_CONFIG = SharePointConfig.from_mapping({
    "AZURE_TENANT_ID": "tid", "AZURE_CLIENT_ID": "cid", "AZURE_CLIENT_SECRET": "sec",
    "GROUP_PL": "https://blitz.sharepoint.com/sites/Finance/Shared Documents/Group PL/Group_PL_2026_Upload.xlsx",
})


def test_url_mode_fetches_metadata_not_just_content(monkeypatch, fake_token):
    """/driveItem, not /driveItem/content — the banner needs the eTag."""
    seen: list[str] = []

    def fake_get(url, token, **kwargs):
        seen.append(url)
        return FakeResponse(payload={
            "name": "Group_PL_2026_Upload.xlsx", "id": "ITEM9", "size": 609772,
            "eTag": 'W/"tag-9"', "lastModifiedDateTime": "2026-08-14T10:02:08Z",
            "webUrl": "https://blitz.sharepoint.com/sites/Finance/x.xlsx",
            "parentReference": {"driveId": "DRIVE9"},
            "lastModifiedBy": {"user": {"displayName": "Fado Ganinduto"}},
        })

    monkeypatch.setattr(gc, "_get", fake_get)
    remote = gc.locate_file(URL_CONFIG)

    assert seen[0].startswith("https://graph.microsoft.com/v1.0/shares/u!")
    assert seen[0].endswith("/driveItem"), "must not go straight to /content"
    assert remote.etag == 'W/"tag-9"'
    assert remote.modified_by == "Fado Ganinduto"
    assert remote.drive_id == "DRIVE9"


def test_url_mode_download_prefers_resolved_item_ids(monkeypatch, fake_token):
    captured: list[str] = []
    monkeypatch.setattr(gc, "_get", lambda url, t, **k: (captured.append(url), FakeResponse(content=b"xlsx"))[1])
    remote = gc.RemoteFile("w.xlsx", "DRIVE9", "ITEM9", None, None, "e", "")
    assert gc.download_file(URL_CONFIG, remote) == b"xlsx"
    assert captured[0].endswith("/drives/DRIVE9/items/ITEM9/content")


def test_url_mode_download_falls_back_to_shares_when_ids_missing(monkeypatch, fake_token):
    captured: list[str] = []
    monkeypatch.setattr(gc, "_get", lambda url, t, **k: (captured.append(url), FakeResponse(content=b"xlsx"))[1])
    remote = gc.RemoteFile("w.xlsx", "", "", None, None, "e", "")
    assert gc.download_file(URL_CONFIG, remote) == b"xlsx"
    assert "/shares/u!" in captured[0] and captured[0].endswith("/driveItem/content")
