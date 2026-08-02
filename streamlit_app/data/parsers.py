"""Sheet-specific parsers — one function per sheet type, all returning tidy DataFrames."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.constants import (
    RATIO_LABELS,
    SKIP_LABELS,
    USD_BLOCK_MARKER,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

MONTH_FORMATS: list[str] = ["%b %Y", "%b-%y", "%B %Y", "%B-%y"]


def month_sort_key(month_label: str) -> pd.Timestamp:
    """Convert a month label string to a sortable Timestamp; returns NaT on failure."""
    for fmt in MONTH_FORMATS:
        try:
            return pd.to_datetime(str(month_label), format=fmt)
        except (ValueError, TypeError):
            continue
    return pd.NaT  # type: ignore[return-value]


def _detect_month_cols(
    raw: pd.DataFrame, header_row_idx: int
) -> list[int]:
    """Return column indices whose header-row value looks like a month string."""
    header = raw.iloc[header_row_idx]
    cols: list[int] = []
    for col_idx in range(2, len(raw.columns)):
        val = header.iloc[col_idx]
        if isinstance(val, str) and val.strip() and month_sort_key(val.strip()) is not pd.NaT:
            cols.append(col_idx)
        elif hasattr(val, "strftime"):  # datetime object from openpyxl
            cols.append(col_idx)
    return cols


def _header_label(raw: pd.DataFrame, header_row_idx: int, col_idx: int) -> str:
    """Return the month label for a given column, formatting datetime objects."""
    val = raw.iloc[header_row_idx, col_idx]
    if hasattr(val, "strftime"):
        return val.strftime("%b %Y")
    return str(val).strip()


# ---------------------------------------------------------------------------
# P&L summary / detail sheets
# ---------------------------------------------------------------------------

# Section headers that signal a cost block (used to disambiguate Depreciation rows)
_COGS_SECTION_KEYWORDS: frozenset[str] = frozenset(
    {"cogs", "cost of goods", "cost of revenue", "cost of sales", "direct cost"}
)
_OPEX_SECTION_KEYWORDS: frozenset[str] = frozenset(
    {"operating expense", "opex", "operating cost", "g&a", "selling", "overhead"}
)


def _disambiguate_depreciation(label: str, current_section: str) -> str:
    """Append (COGS) or (OpEx) to 'Depreciation' rows based on their section header."""
    if label.strip().lower() != "depreciation":
        return label
    sec_lower = current_section.lower()
    if any(k in sec_lower for k in _COGS_SECTION_KEYWORDS):
        return "Depreciation (COGS)"
    if any(k in sec_lower for k in _OPEX_SECTION_KEYWORDS):
        return "Depreciation (OpEx)"
    return label  # fallback if section is unclear


@st.cache_data(show_spinner=False)
def parse_pl_sheet(raw: pd.DataFrame, entity: str) -> pd.DataFrame:
    """Parse a wide P&L summary/detail sheet into tidy long format (Entity, Metric, Month, Value)."""
    # Locate the header row (must contain "In IDR" somewhere)
    header_row_idx: int | None = None
    for i in range(min(5, len(raw))):
        row = raw.iloc[i].astype(str)
        if row.str.contains("In IDR", na=False).any():
            header_row_idx = i
            break
    if header_row_idx is None:
        return pd.DataFrame(columns=["Entity", "Metric", "Month", "Value"])

    month_col_indices = _detect_month_cols(raw, header_row_idx)
    if not month_col_indices:
        return pd.DataFrame(columns=["Entity", "Metric", "Month", "Value"])

    records: list[dict] = []
    current_section: str = ""

    for row_idx in range(header_row_idx + 1, len(raw)):
        label_raw = raw.iloc[row_idx, 1]
        if not isinstance(label_raw, str) or not label_raw.strip():
            continue

        label_lower = label_raw.strip().lower()

        # Stop at the USD conversion block or any memo block
        if USD_BLOCK_MARKER in label_lower or "does not tie to main p&l" in label_lower:
            break

        # Track section headers (rows with no numeric values in month columns)
        row_has_numbers = any(
            isinstance(raw.iloc[row_idx, c], (int, float))
            for c in month_col_indices
        )
        if not row_has_numbers:
            current_section = label_raw.strip()
            continue

        # Skip ratio rows (they go to parse_ratios)
        if label_lower in SKIP_LABELS:
            continue

        label = _disambiguate_depreciation(label_raw.strip(), current_section)

        for col_idx in month_col_indices:
            val = raw.iloc[row_idx, col_idx]
            if isinstance(val, (int, float)):
                month_label = _header_label(raw, header_row_idx, col_idx)
                records.append(
                    {
                        "Entity": entity,
                        "Metric": label,
                        "Month": month_label,
                        "Value": float(val),
                    }
                )

    df = pd.DataFrame(records)
    if not df.empty:
        df["MonthDate"] = df["Month"].apply(month_sort_key)
        df = df.sort_values("MonthDate").reset_index(drop=True)
    return df


@st.cache_data(show_spinner=False)
def parse_ratios(raw: pd.DataFrame, entity: str) -> pd.DataFrame:
    """Parse ratio rows (Margin %, Growth %) from a P&L sheet into tidy long format."""
    header_row_idx: int | None = None
    for i in range(min(5, len(raw))):
        row = raw.iloc[i].astype(str)
        if row.str.contains("In IDR", na=False).any():
            header_row_idx = i
            break
    if header_row_idx is None:
        return pd.DataFrame(columns=["Entity", "Metric", "Month", "Value"])

    month_col_indices = _detect_month_cols(raw, header_row_idx)
    records: list[dict] = []

    for row_idx in range(header_row_idx + 1, len(raw)):
        label_raw = raw.iloc[row_idx, 1]
        if not isinstance(label_raw, str) or not label_raw.strip():
            continue
        label_lower = label_raw.strip().lower()
        if USD_BLOCK_MARKER in label_lower:
            break
        if label_lower not in RATIO_LABELS:
            continue

        for col_idx in month_col_indices:
            val = raw.iloc[row_idx, col_idx]
            if isinstance(val, (int, float)):
                month_label = _header_label(raw, header_row_idx, col_idx)
                records.append(
                    {
                        "Entity": entity,
                        "Metric": label_raw.strip(),
                        "Month": month_label,
                        "Value": float(val),
                    }
                )

    df = pd.DataFrame(records)
    if not df.empty:
        df["MonthDate"] = df["Month"].apply(month_sort_key)
        df = df.sort_values("MonthDate").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# MASTER sheet (already tidy/long format)
# ---------------------------------------------------------------------------

MASTER_NEEDED_COLS: list[str] = [
    "Entity",
    "Rev Stream",
    "Industry",
    "Client (clean)",
    "Month",
    "Amount (IDR)",
]


@st.cache_data(show_spinner=False)
def parse_master(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Parse the MASTER sheet (header on row 2) into a clean long DataFrame.

    Returns (dataframe, list_of_missing_columns).
    """
    master = raw.iloc[2:].copy()
    master.columns = raw.iloc[1]
    master = master.reset_index(drop=True)

    missing = [c for c in MASTER_NEEDED_COLS if c not in master.columns]
    if missing:
        return pd.DataFrame(), missing

    master = master[MASTER_NEEDED_COLS].dropna(subset=["Entity"])
    master["Amount (IDR)"] = pd.to_numeric(master["Amount (IDR)"], errors="coerce").fillna(0)
    master["MonthDate"] = master["Month"].apply(month_sort_key)
    master = master.sort_values("MonthDate").reset_index(drop=True)
    return master, []


# ---------------------------------------------------------------------------
# WIP Margin by Stream sheet
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def parse_wip_margin(raw: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Parse the WIP Margin by Stream sheet into section DataFrames keyed by section name.

    Returns a dict with keys like 'revenue', 'cogs', 'margin' depending on what's found.
    """
    # Months are on row 4 (index 3), data starts at row 7 (index 6)
    try:
        header_row_idx = 3  # row 4, 0-indexed
        header = raw.iloc[header_row_idx]

        # Collect month column indices
        month_col_indices: list[int] = []
        month_labels: list[str] = []
        for col_idx in range(1, len(raw.columns)):
            val = header.iloc[col_idx]
            ts = month_sort_key(str(val).strip()) if isinstance(val, str) else (
                pd.Timestamp(val) if hasattr(val, "strftime") else pd.NaT
            )
            if ts is not pd.NaT:
                month_col_indices.append(col_idx)
                month_labels.append(
                    val.strftime("%b %Y") if hasattr(val, "strftime") else str(val).strip()
                )

        if not month_col_indices:
            return {}

        # Scan all rows from row 5 onward (index 4) to discover sections
        sections: dict[str, list[dict]] = {}
        current_section = "revenue"

        for row_idx in range(4, len(raw)):
            label_raw = raw.iloc[row_idx, 0]
            if not isinstance(label_raw, str):
                label_raw = raw.iloc[row_idx, 1] if len(raw.columns) > 1 else ""
            if not isinstance(label_raw, str) or not label_raw.strip():
                continue

            label_lower = label_raw.strip().lower()

            # Detect section headers
            if "revenue" in label_lower and "total" not in label_lower:
                current_section = "revenue"
                continue
            if "cogs" in label_lower or "cost of" in label_lower:
                current_section = "cogs"
                continue
            if "margin" in label_lower and "%" in label_lower:
                current_section = "margin"
                continue
            if "gross profit" in label_lower:
                current_section = "gross_profit"
                continue

            row_has_numbers = any(
                isinstance(raw.iloc[row_idx, c], (int, float))
                for c in month_col_indices
            )
            if not row_has_numbers:
                continue

            for col_idx, month_label in zip(month_col_indices, month_labels):
                val = raw.iloc[row_idx, col_idx]
                if isinstance(val, (int, float)):
                    sections.setdefault(current_section, []).append(
                        {
                            "Stream": label_raw.strip(),
                            "Month": month_label,
                            "Value": float(val),
                            "MonthDate": month_sort_key(month_label),
                        }
                    )

        return {k: pd.DataFrame(v).sort_values("MonthDate") for k, v in sections.items() if v}

    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# TIE-OUT CHECK sheet
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def parse_tie_out(raw: pd.DataFrame) -> pd.DataFrame:
    """Parse the TIE-OUT CHECK sheet into a tidy DataFrame of reconciliation deltas."""
    records: list[dict] = []

    # Find the first row that has recognisable month column headers
    header_row_idx: int | None = None
    month_col_indices: list[int] = []
    month_labels: list[str] = []

    for row_idx in range(min(10, len(raw))):
        row = raw.iloc[row_idx]
        tentative_months: list[tuple[int, str]] = []
        for col_idx in range(1, len(raw.columns)):
            val = row.iloc[col_idx]
            label = ""
            if hasattr(val, "strftime"):
                label = val.strftime("%b %Y")
            elif isinstance(val, str):
                label = val.strip()
            if label and month_sort_key(label) is not pd.NaT:
                tentative_months.append((col_idx, label))
        if len(tentative_months) >= 3:  # at least 3 month columns
            header_row_idx = row_idx
            month_col_indices = [t[0] for t in tentative_months]
            month_labels = [t[1] for t in tentative_months]
            break

    if header_row_idx is None:
        return pd.DataFrame()

    # Scan data rows
    for row_idx in range(header_row_idx + 1, len(raw)):
        label_raw = raw.iloc[row_idx, 0]
        if not isinstance(label_raw, str):
            label_raw = ""
        label2 = raw.iloc[row_idx, 1] if len(raw.columns) > 1 else ""
        row_label = label_raw.strip() or (str(label2).strip() if isinstance(label2, str) else "")
        if not row_label:
            continue

        for col_idx, month_label in zip(month_col_indices, month_labels):
            val = raw.iloc[row_idx, col_idx]
            if isinstance(val, (int, float)):
                records.append(
                    {
                        "Label": row_label,
                        "Month": month_label,
                        "Delta": float(val),
                        "MonthDate": month_sort_key(month_label),
                    }
                )

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).sort_values("MonthDate").reset_index(drop=True)
    return df
