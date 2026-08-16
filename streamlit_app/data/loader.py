"""File-upload handling and cached raw-sheet loading.

Design notes
------------
* ``load_all_sheets`` is keyed by the *bytes* of the uploaded file — not by the
  UploadedFile object or its name — so re-uploading a file with different content
  **always** invalidates the cache immediately, regardless of the 300-second TTL.
* ``parse_all_entity_sheets`` pre-computes every per-entity P&L DataFrame in a
  single cached call.  Tabs that need entity data (overview, per_entity, ai_service)
  call this once rather than each issuing their own ``parse_pl_sheet`` loop.
"""

from __future__ import annotations

import hashlib
import io
from typing import Any

import pandas as pd
import streamlit as st

from streamlit_app.constants import ENTITY_DETAIL_SHEETS, ENTITY_SUMMARY_SHEETS


class WorkbookBytes:
    """An in-memory workbook that quacks like a Streamlit UploadedFile.

    Lets the validator and every existing caller work unchanged whether the
    bytes arrived from a browser upload, a synced folder, or SharePoint.
    """

    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data
        self._buffer = io.BytesIO(data)

    @property
    def size(self) -> int:
        return len(self._data)

    def read(self, *args: Any) -> bytes:
        return self._buffer.read(*args)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._buffer.seek(offset, whence)

    def getvalue(self) -> bytes:
        return self._data


@st.cache_data(ttl=None, max_entries=3, show_spinner="Loading workbook…")
def load_sheets_from_bytes(fingerprint: str, _data: bytes) -> dict[str, pd.DataFrame]:
    """Load every sheet from workbook bytes, cached on the source's fingerprint.

    The fingerprint is the SharePoint eTag, the file mtime+size, or a content
    hash — so the cache invalidates exactly when the underlying file changes.
    There is deliberately no TTL: a time-based cache would either serve a stale
    P&L or re-download the workbook on a timer, and neither is wanted.

    ``_data`` is underscore-prefixed so Streamlit EXCLUDES it from the cache key
    — digesting 600KB of workbook on every rerun is pure waste when the
    fingerprint already identifies the file exactly.
    """
    return pd.read_excel(io.BytesIO(_data), sheet_name=None, header=None)


# ---------------------------------------------------------------------------
# Raw sheet loading
# ---------------------------------------------------------------------------

def _file_hash(file: Any) -> str:
    """Return an MD5 hex digest of the uploaded file's bytes.

    Using the raw bytes (not the filename or size) as the cache key ensures
    that uploading a new workbook always invalidates stale cached data, even
    within the TTL window.
    """
    try:
        data = file.read()
        file.seek(0)  # Reset so pd.read_excel can read from the start
        return hashlib.md5(data, usedforsecurity=False).hexdigest()
    except Exception:  # noqa: BLE001
        # Fallback: use name + size; better than nothing
        return f"{getattr(file, 'name', '')}_{getattr(file, 'size', 0)}"


@st.cache_data(ttl=300, max_entries=3, show_spinner="Loading workbook…")
def load_all_sheets(_file_bytes_hash: str, file: Any) -> dict[str, pd.DataFrame]:
    """Load every sheet from the uploaded Excel workbook as raw DataFrames.

    Parameters
    ----------
    _file_bytes_hash:
        Digest of the file content — used as the primary cache key so that
        different content always produces a fresh parse. (The leading
        underscore EXCLUDES an argument from Streamlit's cache key; the digest
        is what identifies the workbook here.)
    file:
        The Streamlit UploadedFile object (already seeked to position 0).
    """
    return pd.read_excel(file, sheet_name=None, header=None)


def load_workbook(file: Any) -> dict[str, pd.DataFrame]:
    """Public entry point: hash the file bytes then delegate to the cached loader.

    Always call this function rather than ``load_all_sheets`` directly so that
    the byte-hash cache key is always computed and passed correctly.
    """
    file_hash = _file_hash(file)
    return load_all_sheets(file_hash, file)


# ---------------------------------------------------------------------------
# Pre-computed entity sheet parsing
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=6)
def parse_all_entity_sheets(
    _file_bytes_hash: str,
    sheets: dict[str, pd.DataFrame],
    granularity: str = "Summary",
) -> dict[str, pd.DataFrame]:
    """Parse all per-entity P&L sheets and return a dict of {entity → long DataFrame}.

    This eliminates the repeated ``parse_pl_sheet`` loops that previously ran
    independently across overview, per_entity, and ai_service on every render.

    Parameters
    ----------
    _file_bytes_hash:
        Propagated from the workbook load so the entity cache also invalidates
        when a new file is uploaded.
    sheets:
        The full dict returned by ``load_workbook``.
    granularity:
        ``"Summary"`` (default) or ``"Detail"`` — selects which sheet map to use.
    """
    # Import here to avoid circular imports at module level
    from streamlit_app.data.parsers import parse_pl_sheet  # noqa: PLC0415

    sheet_map = ENTITY_DETAIL_SHEETS if granularity == "Detail" else ENTITY_SUMMARY_SHEETS
    result: dict[str, pd.DataFrame] = {}
    for entity, sheet_name in sheet_map.items():
        raw = sheets.get(sheet_name)
        if raw is not None:
            try:
                df = parse_pl_sheet(raw, entity)
                if not df.empty:
                    result[entity] = df
            except Exception:  # noqa: BLE001
                pass  # Individual entity parse failure should not abort the whole batch
    return result
