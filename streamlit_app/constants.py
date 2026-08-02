"""Central constants for the Group P&L dashboard — colours, sheet names, labels."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Sheet names
# ---------------------------------------------------------------------------
SHEET_CONSOLIDATED = "Consolidated Summary"
SHEET_BLITZ_SUMMARY = "Blitz Summary"
SHEET_BORZO_SUMMARY = "Borzo Summary"
SHEET_THELORRY_SUMMARY = "TheLorry Summary"
SHEET_BLITZ_DETAIL = "Blitz Detail"
SHEET_BORZO_DETAIL = "Borzo Detail"
SHEET_THELORRY_DETAIL = "TheLorry Detail"
SHEET_WIP_MARGIN = "WIP Margin by Stream"
SHEET_MASTER = "MASTER"
SHEET_PL_FEED = "PL FEED"
SHEET_TIE_OUT = "TIE-OUT CHECK"
SHEET_SETTINGS = "Settings"

ENTITY_SUMMARY_SHEETS: dict[str, str] = {
    "Blitz": SHEET_BLITZ_SUMMARY,
    "Borzo": SHEET_BORZO_SUMMARY,
    "TheLorry": SHEET_THELORRY_SUMMARY,
}

ENTITY_DETAIL_SHEETS: dict[str, str] = {
    "Blitz": SHEET_BLITZ_DETAIL,
    "Borzo": SHEET_BORZO_DETAIL,
    "TheLorry": SHEET_THELORRY_DETAIL,
}

# ---------------------------------------------------------------------------
# Parsing — labels to skip or treat as ratio rows
# ---------------------------------------------------------------------------
SKIP_LABELS: frozenset[str] = frozenset(
    {
        "growth %",
        "margin %",
        "operating margin %",
        "ebitda margin %",
        "gross margin %",
        "net margin %",
    }
)

RATIO_LABELS: frozenset[str] = frozenset(
    {
        "growth %",
        "margin %",
        "gross margin %",
        "operating margin %",
        "ebitda margin %",
        "net margin %",
    }
)

# Substring that marks the start of a USD conversion block → stop parsing the IDR table
USD_BLOCK_MARKER: str = "in usd"

# ---------------------------------------------------------------------------
# KPI metrics — ordered for display
# ---------------------------------------------------------------------------
CONSOLIDATED_KPI_METRICS: list[str] = [
    "Total Gross Revenue",
    "Total COGS",
    "Gross Profit 2",
    "EBITDA",
    "NET PROFIT/LOSS (Before Tax)",
]

PREFERRED_TREND_METRICS: list[str] = [
    "Total Gross Revenue",
    "Total COGS",
    "Gross Profit 2",
    "Total Operating Expenses",
    "EBITDA",
    "NET PROFIT/LOSS (Before Tax)",
]

# Metrics used for the waterfall chart (in order, sign convention: positive = value as-is)
WATERFALL_STEPS: list[tuple[str, str]] = [
    # (metric_label_in_data, display_name)
    ("Total Gross Revenue", "Gross Revenue"),
    ("Total COGS", "COGS"),
    ("Gross Profit 2", "Gross Profit"),
    ("Total Operating Expenses", "OpEx"),
    ("EBITDA", "EBITDA"),
    ("NET PROFIT/LOSS (Before Tax)", "Net Profit"),
]

# Individual OpEx line items for the breakdown bar chart
OPEX_LINE_ITEMS: list[str] = [
    "Salaries",
    "Office and Hub Rentals",
    "Overheads",
    "IT Software and Services",
    "Marketing",
    "Travel",
    "Depreciation (OpEx)",
    "Depreciation",         # fallback if not disambiguated
    "Courier Fees",
    "Others",
]

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
ENTITY_COLORS: dict[str, str] = {
    "Blitz": "#60A5FA",       # electric blue
    "Borzo": "#F87171",       # coral red
    "TheLorry": "#34D399",    # emerald green
    "Consolidated": "#A78BFA", # violet
}

METRIC_COLOR_FAMILIES: dict[str, str] = {
    "revenue": "#60A5FA",
    "cost": "#F87171",
    "profit": "#34D399",
    "margin": "#FBBF24",
    "ebitda": "#A78BFA",
}

# Matches chartCategoricalColors in config.toml
PLOTLY_COLOR_SEQUENCE: list[str] = [
    "#60A5FA",  # blue
    "#34D399",  # green
    "#A78BFA",  # violet
    "#F87171",  # red
    "#FBBF24",  # yellow
    "#38BDF8",  # sky
    "#FB923C",  # orange
    "#94A3B8",  # slate
]

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
IDR_SUFFIX_THRESHOLDS: list[tuple[float, str, float]] = [
    (1_000_000_000, "B", 1_000_000_000),
    (1_000_000, "M", 1_000_000),
    (1_000, "K", 1_000),
]


def fmt_idr(value: float) -> str:
    """Return a compact IDR string like 'Rp1.2B', 'Rp450M', 'Rp12K'."""
    abs_val = abs(value)
    for threshold, suffix, divisor in IDR_SUFFIX_THRESHOLDS:
        if abs_val >= threshold:
            return f"Rp{value / divisor:,.1f}{suffix}"
    return f"Rp{value:,.0f}"


def fmt_idr_full(value: float) -> str:
    """Return a full IDR string like 'Rp1,234,567,890'."""
    return f"Rp{value:,.0f}"


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------
TIE_OUT_FLAG_THRESHOLD: float = 1_000_000  # IDR — flag deltas above this
