"""Tests for the workbook source layer."""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest

from streamlit_app.data.graph_client import SharePointConfig
from streamlit_app.data.sources import (
    MODE_LOCAL, MODE_SHAREPOINT, MODE_UPLOAD,
    LocalWorkbook, UploadedWorkbook, WorkbookRef, WorkbookUnavailable,
    build_source, configured_mode,
)


class FakeSecrets(dict):
    """Mimics st.secrets' .get() over nested sections."""


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

def test_defaults_to_upload_when_unconfigured():
    assert configured_mode(FakeSecrets()) == MODE_UPLOAD
    source, warning = build_source(FakeSecrets())
    assert source is None and warning is None


def test_unknown_mode_falls_back_to_upload():
    assert configured_mode(FakeSecrets({"workbook": {"mode": "ftp"}})) == MODE_UPLOAD


def test_incomplete_sharepoint_config_warns_rather_than_silently_downgrading():
    secrets = FakeSecrets({
        "workbook": {"mode": MODE_SHAREPOINT},
        "sharepoint": {"tenant_id": "t", "client_id": "c"},
    })
    source, warning = build_source(secrets)
    assert source is None
    assert warning and "incomplete" in warning.lower()


def test_local_mode_without_path_warns():
    source, warning = build_source(FakeSecrets({"workbook": {"mode": MODE_LOCAL}}))
    assert source is None
    assert warning and "workbook.path" in warning


def test_placeholder_secrets_are_rejected():
    """A half-filled template must not be treated as configured."""
    assert SharePointConfig.from_mapping({
        "tenant_id": "your-directory-id", "client_id": "c", "client_secret": "s",
        "hostname": "h", "site_path": "/sites/Finance", "file_path": "f.xlsx",
    }) is None


def test_config_normalises_paths():
    cfg = SharePointConfig.from_mapping({
        "tenant_id": "t", "client_id": "c", "client_secret": "s",
        "hostname": "example.sharepoint.com",
        "site_path": "sites/Finance/", "file_path": "/Shared Documents/Group PL/x.xlsx",
    })
    assert cfg is not None
    assert cfg.site_path == "/sites/Finance"
    assert cfg.file_path == "Shared Documents/Group PL/x.xlsx"


# ---------------------------------------------------------------------------
# Local source
# ---------------------------------------------------------------------------

def test_local_source_reports_provenance(tmp_path):
    wb = tmp_path / "Group_PL.xlsx"
    wb.write_bytes(b"fake-workbook-bytes")
    ref = LocalWorkbook(wb).describe()
    assert ref.name == "Group_PL.xlsx"
    assert ref.origin == "Synced folder"
    assert ref.is_live is True
    assert ref.size == len(b"fake-workbook-bytes")
    assert LocalWorkbook(wb).read_bytes() == b"fake-workbook-bytes"


def test_local_fingerprint_changes_when_file_changes(tmp_path):
    """The cache key must move when the file does, or Refresh is a lie."""
    wb = tmp_path / "Group_PL.xlsx"
    wb.write_bytes(b"v1")
    first = LocalWorkbook(wb).describe().fingerprint
    wb.write_bytes(b"v2-longer")
    assert LocalWorkbook(wb).describe().fingerprint != first


def test_missing_local_file_explains_onedrive_sync(tmp_path):
    with pytest.raises(WorkbookUnavailable, match="sync"):
        LocalWorkbook(tmp_path / "nope.xlsx").describe()


# ---------------------------------------------------------------------------
# Upload source
# ---------------------------------------------------------------------------

class _FakeUpload(io.BytesIO):
    name = "manual.xlsx"


def test_upload_source_has_no_modification_time():
    """An upload cannot claim freshness it does not have."""
    ref = UploadedWorkbook(_FakeUpload(b"abc")).describe()
    assert ref.last_modified is None
    assert ref.is_live is False
    assert ref.origin == "Manual upload"
    assert ref.modified_label == "unknown"


def test_upload_fingerprint_is_content_addressed():
    a = UploadedWorkbook(_FakeUpload(b"same")).describe().fingerprint
    b = UploadedWorkbook(_FakeUpload(b"same")).describe().fingerprint
    c = UploadedWorkbook(_FakeUpload(b"different")).describe().fingerprint
    assert a == b and a != c


# ---------------------------------------------------------------------------
# Freshness reporting
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hours,expected", [
    (0.2, "updated in the last hour"),
    (5, "updated 5h ago"),
    (30, "updated 1 day ago"),
    (80, "updated 3 days ago"),
])
def test_age_hint(hours, expected):
    ref = WorkbookRef(
        name="x", origin="SharePoint", detail="", fingerprint="f",
        last_modified=datetime.now(timezone.utc) - timedelta(hours=hours),
    )
    assert ref.age_hint == expected


def test_age_hint_empty_without_timestamp():
    assert WorkbookRef("x", "Manual upload", "", "f").age_hint == ""


# ---------------------------------------------------------------------------
# Atomicity — the banner must never describe a different file than the data
# ---------------------------------------------------------------------------

def test_local_load_returns_matching_ref_and_bytes(tmp_path):
    wb = tmp_path / "Group_PL.xlsx"
    wb.write_bytes(b"version-one")
    ref, data = LocalWorkbook(wb).load()
    assert data == b"version-one"
    assert ref.fingerprint == LocalWorkbook(wb).describe().fingerprint


def test_sharepoint_load_retries_when_file_changes_mid_read(monkeypatch):
    """A save between metadata and download must not produce a lying banner."""
    from streamlit_app.data import sources as S
    from streamlit_app.data.graph_client import RemoteFile

    cfg = SharePointConfig.from_mapping({
        "tenant_id": "t", "client_id": "c", "client_secret": "s",
        "hostname": "blitz.sharepoint.com", "site_path": "/sites/Finance",
        "file_path": "Shared Documents/x.xlsx",
    })

    def remote(tag):
        return RemoteFile("x.xlsx", "D", "I", None, None, tag, "https://x")

    # etags seen by successive locate_file calls:
    #   attempt 1: before=v1, after=v2  -> changed, retry
    #   attempt 2: before=v2, after=v2  -> stable, accept
    sequence = iter(["v1", "v2", "v2", "v2"])
    monkeypatch.setattr(S, "locate_file", lambda c: remote(next(sequence)))
    monkeypatch.setattr(S, "download_file", lambda c, r: f"bytes-for-{r.etag}".encode())

    ref, data = S.SharePointWorkbook(cfg).load()
    assert ref.fingerprint == "v2"
    assert data == b"bytes-for-v2", "bytes and banner must come from the same version"


def test_sharepoint_load_gives_up_loudly_if_file_never_settles(monkeypatch):
    from streamlit_app.data import sources as S
    from streamlit_app.data.graph_client import RemoteFile

    cfg = SharePointConfig.from_mapping({
        "tenant_id": "t", "client_id": "c", "client_secret": "s",
        "hostname": "blitz.sharepoint.com", "site_path": "/sites/Finance",
        "file_path": "Shared Documents/x.xlsx",
    })
    counter = iter(range(100))
    monkeypatch.setattr(
        S, "locate_file",
        lambda c: RemoteFile("x.xlsx", "D", "I", None, None, f"v{next(counter)}", ""),
    )
    monkeypatch.setattr(S, "download_file", lambda c, r: b"data")
    with pytest.raises(WorkbookUnavailable, match="saving it right now"):
        S.SharePointWorkbook(cfg).load()


def test_fingerprint_is_not_md5():
    """The fingerprint keys a process-global cache shared across sessions."""
    ref = UploadedWorkbook(_FakeUpload(b"abc")).describe()
    assert len(ref.fingerprint) == 64, "expected SHA-256, not MD5"


# ---------------------------------------------------------------------------
# Compatibility with the existing Blitz dashboards' secrets convention
# ---------------------------------------------------------------------------

def test_house_azure_naming_and_pasted_url_are_accepted():
    """Same three secrets as the 3PL dashboard, plus a pasted SharePoint URL."""
    secrets = FakeSecrets({
        "workbook": {"mode": MODE_SHAREPOINT},
        "AZURE_TENANT_ID": "tid",
        "AZURE_CLIENT_ID": "cid",
        "AZURE_CLIENT_SECRET": "sec",
        "files": {
            "GROUP_PL": "https://blitz.sharepoint.com/sites/Finance/Shared Documents/Group PL/Group_PL_2026_Upload.xlsx",
        },
    })
    source, warning = build_source(secrets)
    assert warning is None
    assert source is not None
    assert source.origin == "SharePoint"


def test_share_token_matches_graph_shares_encoding():
    """Graph expects 'u!' + base64url(url) with padding stripped."""
    import base64
    url = "https://blitz.sharepoint.com/sites/Finance/x.xlsx"
    cfg = SharePointConfig.from_mapping({
        "AZURE_TENANT_ID": "t", "AZURE_CLIENT_ID": "c",
        "AZURE_CLIENT_SECRET": "s", "GROUP_PL": url,
    })
    assert cfg is not None and cfg.addresses_by_url
    expected = "u!" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    assert cfg.share_token == expected
    assert "=" not in cfg.share_token


def test_url_must_be_https():
    assert SharePointConfig.from_mapping({
        "AZURE_TENANT_ID": "t", "AZURE_CLIENT_ID": "c",
        "AZURE_CLIENT_SECRET": "s", "file_url": "ftp://blitz/x.xlsx",
    }) is None


def test_explicit_path_config_still_works_alongside_url_support():
    cfg = SharePointConfig.from_mapping({
        "tenant_id": "t", "client_id": "c", "client_secret": "s",
        "hostname": "blitz.sharepoint.com", "site_path": "sites/Finance/",
        "file_path": "/Shared Documents/Group PL/x.xlsx",
    })
    assert cfg is not None
    assert not cfg.addresses_by_url
    assert cfg.site_path == "/sites/Finance"
