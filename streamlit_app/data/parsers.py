"""Sheet-specific parsers — one function per sheet type, all returning tidy DataFrames."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from streamlit_app.constants import (
    DETAIL_METRIC_ALIASES,
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
    """Return the columns of the P&L's own month grid — and nothing else.

    Scanning the whole header row for anything month-shaped is not safe. Blitz
    Summary carries a "Top Clients Monthly" side table pasted to the right of
    the P&L, at columns 41-46, under its own ``Jan 2026 … Jun 2026`` header. A
    naive scan returned 42 columns for 36 months, so six months of 2026 were
    read twice: once from the P&L, and once from whatever client figure happened
    to sit on the same spreadsheet row.

    The cost of that was not small. Row 8 is "Total Gross Revenue" in the P&L
    and TikTok's monthly revenue in the side table, so Blitz Jun 2026 revenue
    was reported as Rp3,661,974,619 against a true Rp2,968,578,119 — the
    Rp693,396,500 gap being TikTok's June revenue, read as if it were P&L.

    Two independent rules, either of which alone closes it:

    * **Contiguity.** The P&L grid is an unbroken run of month columns. Stop at
      the first non-month column once the run has started; a side table is
      always separated from it by at least one blank or titled column.
    * **Uniqueness.** A month may appear once. The leftmost band wins, because
      the P&L is authored first and side tables are appended to its right.
    """
    header = raw.iloc[header_row_idx]
    cols: list[int] = []
    seen: set[str] = set()
    started = False

    for col_idx in range(2, len(raw.columns)):
        val = header.iloc[col_idx]
        if hasattr(val, "strftime"):  # datetime object from openpyxl
            label = val.strftime("%b %Y")
        elif isinstance(val, str) and val.strip() and month_sort_key(val.strip()) is not pd.NaT:
            label = val.strip()
        else:
            # A break in the run ends the grid. Leading blanks before the first
            # month column are tolerated.
            if started:
                break
            continue

        started = True
        if label in seen:
            continue
        seen.add(label)
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
        # Detail sheets use their own names for the shared subtotals.
        label = DETAIL_METRIC_ALIASES.get(label, label)

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

# Section headers on the sheet are lettered: "A.  REVENUE BY STREAM",
# "B.  COST OF REVENUE BY STREAM", "C.  GROSS MARGIN BY STREAM",
# "D.  CHECK vs GROUP TOTALS". Keying on the letter is exact; the previous
# implementation guessed from keywords and mis-filed rows — "3PL Deliveries
# Margin" matched "cogs" before it matched "margin", so a margin line was
# reported as a cost.
_WIP_SECTIONS: dict[str, str] = {
    "a": "revenue",
    "b": "cogs",
    "c": "margin",
    "d": "check",
}

_WIP_TOTAL_LABELS: frozenset[str] = frozenset(
    {"total revenue", "total cost of revenue", "total gross margin"}
)


@dataclass(frozen=True)
class WipMarginQuality:
    """Whether the WIP Margin sheet is fit to report from.

    The sheet is named WIP for a reason. Both conditions below are true of the
    workbook as it stands, and either one makes every margin on it meaningless:
    rendering them anyway would put "3PL Deliveries margin: 100%" on screen with
    the authority of a dashboard behind it.
    """

    costs_allocated: bool
    unallocated_cost: float
    period_mismatch: dict[str, tuple[float, float]]  # month -> (sheet, expected)

    @property
    def usable(self) -> bool:
        return self.costs_allocated and not self.period_mismatch


@st.cache_data(show_spinner=False, max_entries=12)
def parse_wip_margin(raw: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Parse the WIP Margin by Stream sheet into section DataFrames.

    Keys: 'revenue', 'cogs', 'margin', 'check'. Ratio rows ("margin %") are
    excluded — they are derived, and on this sheet they are derived from an
    empty cost section.
    """
    try:
        header_row_idx = None
        month_col_indices: list[int] = []
        month_labels: list[str] = []
        for candidate in range(min(8, len(raw))):
            cols, labels = [], []
            for col_idx in range(1, len(raw.columns)):
                val = raw.iloc[candidate, col_idx]
                if hasattr(val, "strftime"):
                    cols.append(col_idx)
                    labels.append(val.strftime("%b %Y"))
                elif isinstance(val, str) and month_sort_key(val.strip()) is not pd.NaT:
                    cols.append(col_idx)
                    # Canonicalise to "%b %Y". This sheet writes "Jan-26" while
                    # the P&L sheets write "Jan 2026"; leaving them raw makes
                    # every cross-check join match zero rows and pass
                    # vacuously — the same trap the MASTER sheet sprang.
                    labels.append(month_sort_key(val.strip()).strftime("%b %Y"))
            if len(cols) >= 3:
                header_row_idx, month_col_indices, month_labels = candidate, cols, labels
                break

        if header_row_idx is None:
            return {}

        sections: dict[str, list[dict]] = {}
        current: str | None = None

        for row_idx in range(header_row_idx + 1, len(raw)):
            label_raw = raw.iloc[row_idx, 1]
            if not isinstance(label_raw, str):
                label_raw = raw.iloc[row_idx, 0] if len(raw.columns) else ""
            if not isinstance(label_raw, str) or not label_raw.strip():
                continue
            label = label_raw.strip()

            # "A.  REVENUE BY STREAM (from entity Detail sheets)"
            marker = re.match(r"^([A-Da-d])\s*\.", label)
            if marker:
                current = _WIP_SECTIONS.get(marker.group(1).lower())
                continue
            if current is None:
                continue

            lowered = label.lower()
            if lowered.startswith("margin %") or lowered.startswith("total margin %"):
                continue  # derived ratio, not a figure

            for col_idx, month_label in zip(month_col_indices, month_labels):
                val = raw.iloc[row_idx, col_idx]
                if isinstance(val, (int, float)) and not pd.isna(val):
                    sections.setdefault(current, []).append(
                        {
                            "Stream": label,
                            "Month": month_label,
                            "Value": float(val),
                            "MonthDate": month_sort_key(month_label),
                            "IsTotal": lowered in _WIP_TOTAL_LABELS,
                        }
                    )

        return {
            key: pd.DataFrame(rows).sort_values("MonthDate")
            for key, rows in sections.items()
            if rows
        }

    except Exception:  # noqa: BLE001
        return {}


def assess_wip_margin(
    sections: dict[str, pd.DataFrame],
    cons_long: pd.DataFrame | None = None,
) -> WipMarginQuality:
    """Decide whether the parsed sheet can honestly be reported from.

    Two independent checks, both of which the current workbook fails:

    1. **Costs allocated?** Section B is entirely zero, so every "margin" in
       section C is just revenue again and every margin % is 100%.
    2. **Do the periods line up?** The sheet's own Total Revenue row is compared
       against Consolidated Total Gross Revenue for the same month. The columns
       are labelled Jan-26..Jun-26 but hold Jan-2024..Jun-2024 figures, so this
       catches a 24-month formula offset that no amount of correct parsing
       would fix.
    """
    cogs = sections.get("cogs", pd.DataFrame())
    if cogs.empty:
        unallocated, allocated = 0.0, False
    else:
        detail = cogs[~cogs.get("IsTotal", False)] if "IsTotal" in cogs else cogs
        unallocated = float(detail["Value"].abs().sum())
        allocated = unallocated > 0

    mismatch: dict[str, tuple[float, float]] = {}
    revenue = sections.get("revenue", pd.DataFrame())
    if cons_long is not None and not cons_long.empty and not revenue.empty:
        totals = revenue[revenue.get("IsTotal", False)] if "IsTotal" in revenue else revenue
        for _, row in totals.iterrows():
            expected = cons_long[
                (cons_long["Metric"] == "Total Gross Revenue")
                & (cons_long["Month"] == row["Month"])
            ]["Value"].sum()
            if expected and abs(expected - row["Value"]) > 1.0:
                mismatch[str(row["Month"])] = (float(row["Value"]), float(expected))

    return WipMarginQuality(
        costs_allocated=allocated,
        unallocated_cost=unallocated,
        period_mismatch=mismatch,
    )


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
