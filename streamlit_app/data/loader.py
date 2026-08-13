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
from typing import Any

import pandas as pd
import streamlit as st

from streamlit_app.constants import ENTITY_DETAIL_SHEETS, ENTITY_SUMMARY_SHEETS


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
        MD5 digest of the file content — used as the primary cache key so
        that different content always produces a fresh parse (the leading
        underscore tells Streamlit to hash this argument directly, not the
        object itself).
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
