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

# The Detail sheets name the same lines differently from the Summary sheets.
# Left unmapped, the Entity tab's Detail view finds no revenue at all and every
# revenue cell renders "N/A" while the profit lines populate normally.
DETAIL_METRIC_ALIASES: dict[str, str] = {
    "Total REVENUE": "Total Gross Revenue",
    "Total NET REVENUE": "Net Revenue",
    "Total COGS ": "Total COGS",
}

# ---------------------------------------------------------------------------
# P&L bridge (waterfall)
# ---------------------------------------------------------------------------
# Each step declares its ROLE so the bridge arithmetic is explicit:
#   "start"    — opening bar, taken at face value
#   "cost"     — subtracted from the running total (costs are stored POSITIVE
#                in this workbook, so the step is -value)
#   "subtotal" — a figure the workbook already computed. The running total must
#                land exactly on it; any gap is emitted as a visible residual
#                bar rather than silently absorbed.
#
# The previous list had no roles, and the renderer computed every step as
# `current_line - previous_line`. On Jun 2026 that drew the COGS bar as
# +Rp489M (actual -Rp4.73B) and EBITDA as -Rp5.21B (actual -Rp2.85B), while the
# bar labels still printed the correct figures.
WATERFALL_STEPS: list[tuple[str, str, str]] = [
    # (metric_label_in_data, display_name, role)
    ("Total Gross Revenue", "Gross Revenue", "start"),
    ("Total COGS", "COGS", "cost"),
    ("Gross Profit 1", "Gross Profit 1", "subtotal"),
    ("Depreciation (COGS)", "D&A (COGS)", "cost"),
    ("Gross Profit 2", "Gross Profit", "subtotal"),
    ("Total Operating Expenses", "OpEx", "cost"),
    ("EBITDA", "EBITDA", "subtotal"),
    ("NET PROFIT/LOSS (Before Tax)", "Net Profit", "subtotal"),
]

# Bridge residuals below this are rounding; above it they get their own bar.
WATERFALL_RESIDUAL_FLOOR: float = 500_000.0  # IDR

# The single subtotal used for gross margin. Never sum or average margin rows,
# and never combine Gross Profit 1 and Gross Profit 2 — the sheet reports both,
# and adding them reported Jun 2026 gross margin as -24.2% against a true -12.7%.
GROSS_PROFIT_METRIC: str = "Gross Profit 2"

# Individual OpEx line items for the breakdown bar chart.
#
# Must contain ONLY rows that roll up into "Total Operating Expenses". The
# original list also carried "Courier Fees" (a COGS line, Rp3.70B), "Others"
# (a REVENUE line) and a bare "Depreciation" that double-counted the COGS
# depreciation — so the breakdown summed to Rp6.03B against a true OpEx of
# Rp2.36B and ranked Courier Fees as the largest operating expense.
OPEX_LINE_ITEMS: list[str] = [
    "Salaries",
    "Office and Hub Rentals",
    "Overheads",
    "Outsourced Services",
    "IT Software and Services",
    "Marketing",
    "Travel",
    "Depreciation (OpEx)",
]

# Roll-up subtotal the OpEx line items must reconcile to.
OPEX_TOTAL_METRIC: str = "Total Operating Expenses"

# Unallocated OpEx above this is surfaced to the user rather than ignored.
OPEX_RECONCILIATION_FLOOR: float = 1_000_000.0  # IDR

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
# Entity series colours — validated, not chosen by eye.
#
# The previous three (#00B9F2 / #018EDD / #004EA9) were three shades of the same
# blue: Blitz and Borzo sat ΔE 11.8 apart in NORMAL vision, below the 15 floor,
# so they were hard to tell apart even without a colour-vision deficiency, and
# #00B9F2 had only 2.22:1 contrast against a white chart surface. That is a large
# part of why the charts were hard to read.
#
# These pass all six checks in light AND dark mode (lightness band, chroma floor,
# CVD separation, normal-vision floor, contrast). Borzo orange and TheLorry teal
# are the values the team's own Power BI guide already specified.
#
#   node scripts/validate_palette.js "#0284C7,#E0592B,#0F9D8F" --mode light
#
# NB: #00B9F2 remains the brand colour for UI chrome (buttons, accent bars). It
# is simply not usable as a data-series fill.
ENTITY_COLORS: dict[str, str] = {
    "Blitz": "#0284C7",        # blue — brand family, with real contrast
    "Borzo": "#E0592B",        # orange
    "TheLorry": "#0F9D8F",     # teal
    "Consolidated": "#334155",  # slate — a total, deliberately not a hue
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
# Categorical sequence, assigned in this fixed order and never cycled.
#
# The previous sequence put two greys (#1A1A1A, #4D4D4D) in slots 4 and 5 — text
# tokens used as series fills, which read as gray and failed the chroma floor —
# behind three near-identical blues. Validated:
#
#   node scripts/validate_palette.js \
#     "#0284C7,#E0592B,#0F9D8F,#7C3AED,#65A30D,#DB2777" --mode light
#   → all six checks PASS, light and dark
#
# A seventh category is NOT a generated hue: fold the tail into "Other" or facet.
PLOTLY_COLOR_SEQUENCE: list[str] = [
    "#0284C7",  # blue
    "#E0592B",  # orange
    "#0F9D8F",  # teal
    "#7C3AED",  # violet
    "#65A30D",  # olive
    "#DB2777",  # magenta
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
            formatted = f"{abs_val / divisor:,.1f}"
            if formatted.endswith(".0"):
                formatted = formatted[:-2]
            return f"{'-' if value < 0 else ''}Rp{formatted}{suffix}"
    return f"{'-' if value < 0 else ''}Rp{abs_val:,.0f}"


def fmt_idr_full(value: float) -> str:
    """Return a full IDR string like 'Rp1,234,567,890'."""
    return f"{'-' if value < 0 else ''}Rp{abs(value):,.0f}"


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------
TIE_OUT_FLAG_THRESHOLD: float = 1_000_000  # IDR — flag deltas above this
