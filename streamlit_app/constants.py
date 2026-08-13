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

# Metric sections for the consolidated tab section filter
METRIC_SECTIONS: dict[str, list[str]] = {
    "Revenue": [
        "Total Gross Revenue",
        "Net Revenue",
        "Deliveries",
        "Mobile Commerce",
        "EV Leasing",
        "COD & Others",
        "Others",
    ],
    "COGS": [
        "Total COGS",
        "Gross Profit 1",
        "Gross Profit 2",
        "Courier Fees",
        "Fulfillment Costs",
        "Cost of Goods Sold",
        "Depreciation (COGS)",
    ],
    "Operating Expenses": [
        "Total Operating Expenses",
        "Salaries",
        "Office and Hub Rentals",
        "Overheads",
        "IT Software and Services",
        "Marketing",
        "Travel",
        "Depreciation (OpEx)",
        "Depreciation",
        "Outsourced Services",
    ],
    "Profitability": [
        "EBITDA",
        "NET PROFIT/LOSS (Before Tax)",
        "Net Profit/Loss",
        "Operating Profit",
    ],
}

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
# Blitz brand colour palette (centralized)
# ---------------------------------------------------------------------------
BLITZ_COLORS: dict[str, str] = {
    "primary": "#00B9F2",
    "primary_hover": "#018EDD",
    "deep_blue": "#004EA9",
    "light_blue": "#B2EDFF",
    "pale_blue": "#D6F6FF",
    "text_primary": "#1A1A1A",
    "text_secondary": "#4D4D4D",
    "black": "#000000",
    "white": "#FFFFFF",
    "off_white": "#FCFCFC",
    "background": "#F8F8F8",
    "border": "#E2E2E2",
}

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
ENTITY_COLORS: dict[str, str] = {
    "Blitz": "#00B9F2",       # primary Blitz blue
    "Borzo": "#018EDD",       # secondary blue
    "TheLorry": "#004EA9",    # deep blue
    "Consolidated": "#1A1A1A", # dark text
}

METRIC_COLOR_FAMILIES: dict[str, str] = {
    "revenue": "#00B9F2",
    "cost": "#004EA9",
    "profit": "#018EDD",
    "margin": "#B2EDFF",
    "ebitda": "#1A1A1A",
}

# Fixed metric colours prevent the same financial measure from changing identity
# between executive, entity, and consolidated views.
METRIC_COLORS: dict[str, str] = {
    "Total Gross Revenue": "#00B9F2",
    "Gross Revenue": "#00B9F2",
    "Net Revenue": "#018EDD",
    "Total COGS": "#004EA9",
    "COGS": "#004EA9",
    "Gross Profit 1": "#018EDD",
    "Gross Profit 2": "#018EDD",
    "Gross Profit": "#018EDD",
    "Total Operating Expenses": "#4D4D4D",
    "Operating Expenses": "#4D4D4D",
    "OpEx": "#4D4D4D",
    "EBITDA": "#1A1A1A",
    "NET PROFIT/LOSS (Before Tax)": "#004EA9",
    "Net Profit": "#004EA9",
    "Net Profit / Loss": "#004EA9",
    "Gross Margin": "#00B9F2",
    "EBITDA Margin": "#018EDD",
    "Net Margin": "#004EA9",
    "COGS %": "#004EA9",
    "OpEx %": "#4D4D4D",
}

# Matches chartCategoricalColors in config.toml. Light tones remain reserved for
# surfaces, so every plotted category remains legible on a white background.
PLOTLY_COLOR_SEQUENCE: list[str] = [
    "#00B9F2",  # primary Blitz blue
    "#018EDD",  # secondary blue
    "#004EA9",  # deep blue
    "#1A1A1A",  # primary text
    "#4D4D4D",  # secondary text
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
            return f"{'-' if value < 0 else ''}Rp{abs_val / divisor:,.1f}{suffix}"
    return f"{'-' if value < 0 else ''}Rp{abs_val:,.0f}"


def fmt_idr_full(value: float) -> str:
    """Return a full IDR string like 'Rp1,234,567,890'."""
    return f"{'-' if value < 0 else ''}Rp{abs(value):,.0f}"


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------
TIE_OUT_FLAG_THRESHOLD: float = 1_000_000  # IDR — flag deltas above this
