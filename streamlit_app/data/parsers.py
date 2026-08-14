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

# Explicit section-start labels.
#
# The original implementation inferred section headers from "rows with no numeric
# values". That heuristic never fires on the real workbook, because the section
# header rows ("COGS", "Operating Expenses") carry values of their own — so
# ``current_section`` stayed empty and BOTH Depreciation rows kept the ambiguous
# label "Depreciation". Downstream that summed Rp48.4M of COGS depreciation into
# the OpEx breakdown. Sections are now driven by an explicit label map, with the
# no-numbers heuristic retained only as a fallback for layouts we haven't seen.
_SECTION_STARTS: dict[str, str] = {
    "gross revenue": "Revenue",
    "revenue": "Revenue",
    "cogs": "COGS",
    "cost of goods sold": "COGS",
    "operating expenses": "Operating Expenses",
    "opex": "Operating Expenses",
    "other income and expenses": "Other Income and Expenses",
}


def _section_for_label(label: str, current_section: str) -> str:
    """Return the section this row starts, or the unchanged current section."""
    return _SECTION_STARTS.get(label.strip().lower(), current_section)


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


@st.cache_data(show_spinner=False, max_entries=12)
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

        # Track sections. Section-start rows carry values of their own on this
        # workbook, so the section is updated BEFORE the no-numbers fallback and
        # the row is still recorded.
        current_section = _section_for_label(label_raw, current_section)

        row_has_numbers = any(
            isinstance(raw.iloc[row_idx, c], (int, float))
            for c in month_col_indices
        )
        if not row_has_numbers:
            # Fallback for layouts where headers genuinely have no values.
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


@st.cache_data(show_spinner=False, max_entries=12)
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
    last_basis: str = ""

    for row_idx in range(header_row_idx + 1, len(raw)):
        label_raw = raw.iloc[row_idx, 1]
        if not isinstance(label_raw, str) or not label_raw.strip():
            continue
        label_lower = label_raw.strip().lower()
        if USD_BLOCK_MARKER in label_lower:
            break
        if label_lower not in RATIO_LABELS:
            # Remember the subtotal this ratio row will refer to. The sheet has
            # TWO rows literally labelled "Margin %" (one under Gross Profit 1,
            # one under Gross Profit 2). Keying purely on the label collapsed
            # them into a single zig-zagging series.
            last_basis = label_raw.strip()
            continue

        basis = last_basis
        metric = label_raw.strip()
        if metric.lower() == "margin %" and basis:
            metric = f"Margin % ({basis})"

        for col_idx in month_col_indices:
            val = raw.iloc[row_idx, col_idx]
            if isinstance(val, (int, float)):
                month_label = _header_label(raw, header_row_idx, col_idx)
                records.append(
                    {
                        "Entity": entity,
                        "Metric": metric,
                        "RatioLabel": label_raw.strip(),
                        "Basis": basis,
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


@st.cache_data(show_spinner=False, max_entries=12)
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

    # MASTER stores months as "Jan-25"; the P&L sheets store them as "Jan 2026".
    # Every downstream join did `master["Month"] == "<P&L label>"`, which matched
    # zero rows on every month — so the per-client cards were permanently blank.
    # Keep the sheet's own text in MonthRaw and normalise Month to the canonical
    # "%b %Y" label used everywhere else in the app.
    master["MonthRaw"] = master["Month"]
    canonical = master["MonthDate"].dt.strftime("%b %Y")
    master["Month"] = canonical.where(
        master["MonthDate"].notna(), master["MonthRaw"].astype(str)
    )

    # Trailing/leading whitespace in client names silently creates duplicate
    # clients in every groupby. Full alias consolidation lands in Phase 2.
    master["Client (clean)"] = master["Client (clean)"].astype("object")
    _names = master["Client (clean)"]
    master["Client (clean)"] = _names.where(_names.isna(), _names.astype(str).str.strip())

    master = master.sort_values("MonthDate").reset_index(drop=True)
    return master, []


# ---------------------------------------------------------------------------
# WIP Margin by Stream sheet
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=12)
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

# The sheet marks true reconciliation deltas with a leading Δ. Everything else on
# the sheet is either a component being reconciled (MASTER total, Tracker total,
# Direct P&L total) or a free-text adjustment memo.
_DELTA_MARKER: str = "Δ"  # Δ

KIND_DELTA: str = "delta"
KIND_COMPONENT: str = "component"
KIND_ADJUSTMENT: str = "adjustment"

TIE_OUT_COLUMNS: list[str] = [
    "Scope", "Label", "Kind", "Month", "Delta", "MonthDate", "Category",
]


def _tie_out_label(raw: pd.DataFrame, row_idx: int) -> tuple[str, bool]:
    """Return (label_text, is_indented) for a TIE-OUT row.

    Indentation is the sheet's own structure: scope headers sit flush left,
    the components and deltas belonging to them are indented.
    """
    for col_idx in (0, 1):
        if col_idx >= raw.shape[1]:
            continue
        val = raw.iloc[row_idx, col_idx]
        if isinstance(val, str) and val.strip():
            return val.strip(), val != val.lstrip()
    return "", False


@st.cache_data(show_spinner=False, max_entries=12)
def parse_tie_out(raw: pd.DataFrame) -> pd.DataFrame:
    """Parse the TIE-OUT CHECK sheet into tidy reconciliation rows.

    The previous implementation treated **every numeric cell on the sheet** as a
    variance. That made the Data Health tab report the MASTER revenue total
    (~Rp3.0B) as the month's single largest "discrepancy", while the actual
    reconciliation deltas — the handful of Δ rows, typically Rp5M–Rp300M — were
    buried below it.

    This parser preserves the sheet's structure instead:

    * ``Kind == "delta"``      → a real variance (row label starts with Δ).
      **These, and only these, may be reported as reconciliation exceptions.**
    * ``Kind == "component"``  → an input to a reconciliation (MASTER total,
      Revenue Tracker total, Direct P&L total). Context, never a variance.
    * ``Kind == "adjustment"`` → a named manual adjustment memo.

    ``Scope`` carries the block the row belongs to (Blitz, Borzo, TheLorry,
    "BLITZ — 2025 (historical)", …).
    """
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
        return pd.DataFrame(columns=TIE_OUT_COLUMNS)

    # Pre-scan labels so a flush-left row can be classified as a scope header
    # (followed by indented children) rather than a standalone adjustment memo.
    labels: dict[int, tuple[str, bool]] = {}
    for row_idx in range(header_row_idx + 1, len(raw)):
        text, indented = _tie_out_label(raw, row_idx)
        if text:
            labels[row_idx] = (text, indented)

    ordered_rows = sorted(labels)

    def _starts_block(row_idx: int) -> bool:
        """True when the next labelled row is indented under this one."""
        position = ordered_rows.index(row_idx)
        for following in ordered_rows[position + 1: position + 3]:
            if labels[following][1]:
                return True
        return False

    records: list[dict] = []
    current_scope: str = ""

    for row_idx in ordered_rows:
        row_label, indented = labels[row_idx]

        if not indented:
            if _starts_block(row_idx):
                current_scope = row_label
                # Scope headers are structural; they carry no values of their own.
                continue
            kind = KIND_ADJUSTMENT
        elif _DELTA_MARKER in row_label:
            kind = KIND_DELTA
        else:
            kind = KIND_COMPONENT

        for col_idx, month_label in zip(month_col_indices, month_labels):
            val = raw.iloc[row_idx, col_idx]
            if isinstance(val, (int, float)) and not pd.isna(val):
                records.append(
                    {
                        "Scope": current_scope,
                        "Label": row_label,
                        "Kind": kind,
                        "Month": month_label,
                        "Delta": float(val),
                        "MonthDate": month_sort_key(month_label),
                        "Category": current_scope or "Unscoped",
                    }
                )

    if not records:
        return pd.DataFrame(columns=TIE_OUT_COLUMNS)

    return pd.DataFrame(records).sort_values("MonthDate").reset_index(drop=True)


def tie_out_deltas(raw: pd.DataFrame) -> pd.DataFrame:
    """Return ONLY the true reconciliation variances from the TIE-OUT sheet."""
    df = parse_tie_out(raw)
    if df.empty or "Kind" not in df.columns:
        return df
    return df[df["Kind"] == KIND_DELTA].reset_index(drop=True)
