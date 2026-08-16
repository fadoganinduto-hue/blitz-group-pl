"""Where the workbook comes from.

One dashboard, three possible origins:

* ``sharepoint`` — read live from SharePoint via Microsoft Graph. Nobody has to
  remember to export anything, and a Refresh button picks up the newest save.
* ``local`` — a path on disk. Intended for a OneDrive/SharePoint **synced**
  folder, where Microsoft keeps the file current and this app just re-reads it.
* ``upload`` — the original manual file-upload, kept for what-if analysis.

Why this exists
---------------
The manual-upload model let anyone point the dashboard at any workbook. The
Finance folder holds a dozen `Group_PL_*` variants, and a board pack was once
built from a stale one — Jun EBITDA read -Rp1,995M against a true -Rp2,850M.
A dashboard whose header cannot state *which file it is showing* is not a
control; it is a second place to be wrong. Every source below therefore carries
its provenance, and the UI is expected to display it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from streamlit_app.data.graph_client import (
    GraphError,
    SharePointConfig,
    download_file,
    locate_file,
)

# A workbook being saved while we read it is retried this many times.
MAX_RESOLVE_ATTEMPTS = 3

MODE_SHAREPOINT = "sharepoint"
MODE_LOCAL = "local"
MODE_UPLOAD = "upload"


@dataclass(frozen=True)
class WorkbookRef:
    """Provenance for the workbook currently loaded. Always show this."""

    name: str
    origin: str                      # "SharePoint" / "Synced folder" / "Manual upload"
    detail: str                      # URL or path — where it actually came from
    fingerprint: str                 # etag / mtime+size / content hash — the cache key
    last_modified: datetime | None = None
    size: int | None = None
    modified_by: str | None = None
    is_live: bool = False            # True when re-reading picks up edits automatically

    @property
    def modified_label(self) -> str:
        if self.last_modified is None:
            return "unknown"
        stamp = self.last_modified
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone().strftime("%d %b %Y, %H:%M")

    @property
    def age_hint(self) -> str:
        """A short 'how fresh is this' phrase for the header."""
        if self.last_modified is None:
            return ""
        stamp = self.last_modified
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - stamp
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return "updated in the last hour"
        if hours < 24:
            return f"updated {int(hours)}h ago"
        days = int(hours // 24)
        return f"updated {days} day{'s' if days != 1 else ''} ago"


class WorkbookUnavailable(RuntimeError):
    """The configured source could not supply a workbook."""


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class SharePointWorkbook:
    """Reads the workbook live from SharePoint."""

    origin = "SharePoint"

    def __init__(self, config: SharePointConfig) -> None:
        self._config = config

    def describe(self) -> WorkbookRef:
        """Cheap metadata probe. The eTag changes on every save, so it is the
        natural cache key — no polling interval to tune, no stale window."""
        try:
            return self._ref(locate_file(self._config))
        except GraphError as exc:
            raise WorkbookUnavailable(str(exc)) from exc

    def _ref(self, remote) -> WorkbookRef:
        return WorkbookRef(
            name=remote.name,
            origin=self.origin,
            detail=remote.web_url,
            fingerprint=remote.etag or f"{remote.item_id}:{remote.last_modified}",
            last_modified=remote.last_modified,
            size=remote.size,
            modified_by=remote.modified_by,
            is_live=True,
        )

    def load(self) -> tuple[WorkbookRef, bytes]:
        """Return metadata and bytes from a SINGLE resolution of the file.

        Resolving twice — once for the banner, once for the download — allows a
        save between the two calls to produce a banner describing version A
        while the figures on screen come from version B. That is precisely the
        silent-staleness failure this module exists to prevent, so the eTag is
        re-checked after the download and the read is retried if the file moved.
        """
        try:
            for _ in range(MAX_RESOLVE_ATTEMPTS):
                remote = locate_file(self._config)
                data = download_file(self._config, remote)
                confirmed = locate_file(self._config)
                if confirmed.etag == remote.etag:
                    return self._ref(remote), data
        except GraphError as exc:
            raise WorkbookUnavailable(str(exc)) from exc
        raise WorkbookUnavailable(
            "The workbook changed while it was being read, repeatedly. Someone is "
            "saving it right now — try Refresh again in a moment."
        )

    def read_bytes(self) -> bytes:
        return self.load()[1]


class LocalWorkbook:
    """Reads the workbook from disk — typically a OneDrive-synced folder."""

    origin = "Synced folder"

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()

    def describe(self) -> WorkbookRef:
        path = self._path
        if not path.is_file():
            raise WorkbookUnavailable(
                f"No workbook at {path}. Check the path in secrets.toml, and that "
                "the OneDrive folder has finished syncing (a cloud icon next to "
                "the file means it has not downloaded yet)."
            )
        stat = path.stat()
        return WorkbookRef(
            name=path.name,
            origin=self.origin,
            detail=str(path),
            fingerprint=f"{stat.st_mtime_ns}:{stat.st_size}",
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            size=stat.st_size,
            is_live=True,
        )

    def load(self) -> tuple[WorkbookRef, bytes]:
        """Read metadata and bytes together, re-checking that the file is stable."""
        for _ in range(MAX_RESOLVE_ATTEMPTS):
            ref = self.describe()
            data = self.read_bytes()
            if self.describe().fingerprint == ref.fingerprint:
                return ref, data
        raise WorkbookUnavailable(
            f"{self._path.name} kept changing while being read — OneDrive may "
            "still be syncing it. Try Refresh in a moment."
        )

    def read_bytes(self) -> bytes:
        try:
            return self._path.read_bytes()
        except OSError as exc:
            raise WorkbookUnavailable(f"Could not read {self._path}: {exc}") from exc


class UploadedWorkbook:
    """Wraps a Streamlit file-upload. No provenance beyond what the user chose."""

    origin = "Manual upload"

    def __init__(self, uploaded_file: Any) -> None:
        self._file = uploaded_file
        self._bytes: bytes | None = None

    def _content(self) -> bytes:
        if self._bytes is None:
            self._file.seek(0)
            self._bytes = self._file.read()
            self._file.seek(0)
        return self._bytes

    def describe(self) -> WorkbookRef:
        content = self._content()
        return WorkbookRef(
            name=getattr(self._file, "name", "uploaded.xlsx"),
            origin=self.origin,
            detail="Uploaded in this browser session",
            # SHA-256, not MD5: this value is a cache key in a process-global
            # cache shared across sessions, so a collision would serve one
            # user's parsed P&L under another user's file name.
            fingerprint=hashlib.sha256(content).hexdigest(),
            # An upload carries no modification time — say so rather than
            # implying the file is current.
            last_modified=None,
            size=len(content),
            is_live=False,
        )

    def load(self) -> tuple[WorkbookRef, bytes]:
        return self.describe(), self._content()

    def read_bytes(self) -> bytes:
        return self._content()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def configured_mode(secrets: Any) -> str:
    """Return the configured source mode, defaulting to manual upload."""
    try:
        workbook_cfg = secrets.get("workbook", {}) or {}
        mode = str(workbook_cfg.get("mode", "")).strip().lower()
    except Exception:  # noqa: BLE001 - secrets access varies by host
        return MODE_UPLOAD
    return mode if mode in {MODE_SHAREPOINT, MODE_LOCAL, MODE_UPLOAD} else MODE_UPLOAD


def build_source(secrets: Any) -> tuple[Any | None, str | None]:
    """Build the configured source.

    Returns ``(source, warning)``. A None source means the caller should fall
    back to manual upload; ``warning`` explains why, so a misconfiguration is
    visible instead of silently degrading to the old behaviour.
    """
    mode = configured_mode(secrets)

    if mode == MODE_SHAREPOINT:
        # Credentials may live in a [sharepoint] section or flat at the top
        # level as AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET —
        # the convention the other Blitz dashboards already use. Merge both so
        # one set of secrets can serve every app.
        merged: dict = {}
        for key in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"):
            try:
                if secrets.get(key):
                    merged[key] = secrets[key]
            except Exception:  # noqa: BLE001
                pass
        merged.update(_section(secrets, "files"))
        merged.update(_section(secrets, "sharepoint"))
        config = SharePointConfig.from_mapping(merged)
        if config is None:
            return None, (
                "workbook.mode is 'sharepoint' but the credentials in secrets.toml "
                "are missing or incomplete. Needs a tenant/client/secret (either "
                "[sharepoint] keys or AZURE_TENANT_ID / AZURE_CLIENT_ID / "
                "AZURE_CLIENT_SECRET) plus either file_url or "
                "hostname+site_path+file_path. Falling back to manual upload."
            )
        return SharePointWorkbook(config), None

    if mode == MODE_LOCAL:
        path = str(_section(secrets, "workbook").get("path", "")).strip()
        if not path:
            return None, (
                "workbook.mode is 'local' but workbook.path is not set in "
                "secrets.toml. Falling back to manual upload."
            )
        return LocalWorkbook(path), None

    return None, None


def _section(secrets: Any, key: str) -> dict:
    try:
        value = secrets.get(key, {})
        return dict(value) if value else {}
    except Exception:  # noqa: BLE001
        return {}
