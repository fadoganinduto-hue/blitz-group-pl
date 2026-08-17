"""Golden-file regression tests against the REAL Group P&L workbook.

Why this file exists
--------------------
The rest of the suite tests synthetic fixtures (Rp1,000M revenue, 60% margin).
Every fixture passed while the live workbook produced a P&L bridge whose EBITDA
bar read -Rp5.21B against a KPI card reading -Rp2.85B. Fixtures cannot catch
that; only the real file can.

Running these tests
-------------------
The workbook is NOT committed (it holds live financials and .gitignore excludes
*.xlsx). Point the suite at your local copy:

    export GROUP_PL_WORKBOOK="/path/to/Group_PL_2026_Upload 6.xlsx"
    pytest tests/test_golden_workbook.py -v

or drop the file at ``tests/fixtures/`` under any ``Group_PL*.xlsx`` name.
Without it these tests SKIP rather than fail, so CI stays green for
contributors who do not hold the finance file.

Updating the expected figures
-----------------------------
When a genuinely newer workbook lands, update EXPECTED below **from the
workbook**, and say so in the commit message. Never edit an expectation to make
a failing test pass — a failure here means a parser change moved a reported
number, which is exactly the event this file exists to catch.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from streamlit_app.constants import (
    GROSS_PROFIT_METRIC,
    OPEX_LINE_ITEMS,
    OPEX_TOTAL_METRIC,
    WATERFALL_RESIDUAL_FLOOR,
    WATERFALL_STEPS,
)
from streamlit_app.data.parsers import (
    KIND_COMPONENT,
    KIND_DELTA,
    parse_master,
    parse_pl_sheet,
    parse_tie_out,
    tie_out_deltas,
)
from streamlit_app.data.periods import actual_months, latest_actual_month
from streamlit_app.data.reconciliation import master_vs_pl_bridge

# Rupiah tolerance. The workbook stores cached formula values, so the parsed
# figures should match to the rupiah; 1.0 absorbs float representation only.
TOL = 1.0

# Source of truth: "Group_PL_2026_Upload 6.xlsx", Consolidated Summary.
GOLDEN_MONTH = "Jul 2026"
EXPECTED: dict[str, float] = {
    "Total Gross Revenue": 4_843_172_634,
    "Total COGS": 4_899_158_251,
    "Gross Profit 1": -55_985_617,
    "Depreciation (COGS)": 46_338_444,
    "Gross Profit 2": -102_324_061,
    "Total Operating Expenses": 2_248_125_179,
    "Depreciation (OpEx)": 20_722_808,
    "EBITDA": -2_304_110_796,
    "NET PROFIT/LOSS (Before Tax)": -2_520_505_465,
}

EXPECTED_LAST_ACTUAL_MONTH = "Jul 2026"
EXPECTED_PLACEHOLDERS = {"Aug 2026", "Sep 2026", "Oct 2026", "Nov 2026", "Dec 2026"}


def _locate_workbook() -> Path | None:
    env = os.environ.get("GROUP_PL_WORKBOOK")
    if env and Path(env).is_file():
        return Path(env)
    fixtures = Path(__file__).parent / "fixtures"
    if fixtures.is_dir():
        matches = sorted(fixtures.glob("Group_PL*.xlsx"))
        if matches:
            return matches[-1]
    return None


@pytest.fixture(scope="module")
def sheets() -> dict[str, pd.DataFrame]:
    path = _locate_workbook()
    if path is None:
        pytest.skip(
            "Real workbook not available. Set GROUP_PL_WORKBOOK=/path/to/"
            "Group_PL_2026_Upload*.xlsx or place it in tests/fixtures/."
        )
    return pd.read_excel(path, sheet_name=None, header=None)


@pytest.fixture(scope="module")
def cons(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return parse_pl_sheet(sheets["Consolidated Summary"], "Consolidated")


def _value(cons: pd.DataFrame, metric: str, month: str = GOLDEN_MONTH) -> float:
    rows = cons[(cons["Metric"] == metric) & (cons["Month"] == month)]
    return float(rows["Value"].sum())


# ---------------------------------------------------------------------------
# Headline figures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metric,expected", sorted(EXPECTED.items()))
def test_headline_metric_matches_workbook(cons, metric: str, expected: float) -> None:
    assert _value(cons, metric) == pytest.approx(expected, abs=TOL), (
        f"{metric} for {GOLDEN_MONTH} drifted from the workbook."
    )


def test_depreciation_is_split_by_section(cons) -> None:
    """Both Depreciation rows must be disambiguated, not left ambiguous."""
    metrics = set(cons["Metric"].unique())
    assert "Depreciation (COGS)" in metrics
    assert "Depreciation (OpEx)" in metrics
    assert "Depreciation" not in metrics, (
        "An ambiguous 'Depreciation' row survived — section detection regressed, "
        "and COGS depreciation will be double-counted into OpEx."
    )


# ---------------------------------------------------------------------------
# Period handling
# ---------------------------------------------------------------------------

def test_unclosed_months_are_excluded(cons) -> None:
    live = actual_months(cons)
    assert latest_actual_month(cons) == EXPECTED_LAST_ACTUAL_MONTH
    assert not EXPECTED_PLACEHOLDERS & set(live), (
        "An unclosed month was treated as an actual — KPI cards will read Rp0."
    )


def test_placeholder_month_with_rounding_artefact_is_not_actual(cons) -> None:
    """Aug 2026 carries a Net Profit of -1 but no revenue; it is not closed."""
    assert _value(cons, "Total Gross Revenue", "Aug 2026") == 0
    assert "Aug 2026" not in actual_months(cons)


# ---------------------------------------------------------------------------
# Derived views
# ---------------------------------------------------------------------------

def test_opex_line_items_reconcile_to_total(cons) -> None:
    parts = sum(_value(cons, item) for item in OPEX_LINE_ITEMS)
    total = _value(cons, OPEX_TOTAL_METRIC)
    assert parts == pytest.approx(total, abs=TOL), (
        f"OpEx breakdown sums to {parts:,.0f} against a reported total of "
        f"{total:,.0f}. A non-OpEx line (Courier Fees is COGS, Others is "
        f"revenue) has been added back to OPEX_LINE_ITEMS."
    )


def test_gross_margin_uses_a_single_subtotal(cons) -> None:
    revenue = _value(cons, "Total Gross Revenue")
    margin = _value(cons, GROSS_PROFIT_METRIC) / revenue
    assert margin == pytest.approx(-0.0211, abs=0.0005)
    both = (_value(cons, "Gross Profit 1") + _value(cons, "Gross Profit 2")) / revenue
    assert both != pytest.approx(margin, abs=0.0005), (
        "Gross margin is summing Gross Profit 1 and Gross Profit 2 again."
    )


def test_waterfall_bridge_lands_on_every_subtotal(cons) -> None:
    """The running total must equal each subtotal the workbook reports."""
    running = 0.0
    for metric, _display, role in WATERFALL_STEPS:
        if not (cons["Metric"] == metric).any():
            continue
        value = _value(cons, metric)
        if role == "start":
            running = value
        elif role == "cost":
            running -= value
        else:
            residual = value - running
            if abs(residual) >= WATERFALL_RESIDUAL_FLOOR:
                running += residual  # drawn as an explicit "Other" bar
            assert running == pytest.approx(value, abs=TOL)
            running = value
    assert running == pytest.approx(EXPECTED["NET PROFIT/LOSS (Before Tax)"], abs=TOL)


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def test_tie_out_separates_deltas_from_components(sheets) -> None:
    parsed = parse_tie_out(sheets["TIE-OUT CHECK"])
    assert not parsed.empty
    assert {"Kind", "Scope"}.issubset(parsed.columns)

    deltas = tie_out_deltas(sheets["TIE-OUT CHECK"])
    assert not deltas.empty
    assert (deltas["Kind"] == KIND_DELTA).all()
    assert deltas["Label"].str.contains("Δ").all(), (
        "A non-Δ row leaked into the variance set."
    )

    # Component totals must never be reported as variances.
    components = parsed[parsed["Kind"] == KIND_COMPONENT]
    assert not components.empty
    assert components["Delta"].abs().max() > deltas["Delta"].abs().max(), (
        "Sanity check: component totals are larger than any true variance, "
        "which is exactly why they must not be classified as exceptions."
    )


def test_tie_out_scopes_are_populated(sheets) -> None:
    deltas = tie_out_deltas(sheets["TIE-OUT CHECK"])
    assert deltas["Scope"].str.len().gt(0).all()
    assert {"Blitz", "Borzo", "TheLorry"}.issubset(set(deltas["Scope"]))


def test_master_months_join_against_pl_labels(sheets, cons) -> None:
    master, missing = parse_master(sheets["MASTER"])
    assert not missing
    pl_months = set(cons["Month"])
    master_months = set(master["Month"])
    assert master_months & pl_months, (
        "MASTER month labels do not intersect the P&L labels — the per-client "
        "views will render blank on every month."
    )
    assert "MonthRaw" in master.columns


def test_master_vs_pl_bridge_is_computed(sheets, cons) -> None:
    master, _ = parse_master(sheets["MASTER"])
    bridge = master_vs_pl_bridge(master, cons)
    assert not bridge.empty
    assert {"MasterRevenue", "PLRevenue", "Delta"}.issubset(bridge.columns)
    # Jun 2026 is the last month MASTER covers; the variance is real and must
    # not silently reconcile to zero.
    jun = bridge[bridge["Month"] == "Jun 2026"]
    assert not jun.empty
    assert abs(float(jun["Delta"].iloc[0])) > 1_000_000


def test_client_names_are_stripped(sheets) -> None:
    master, _ = parse_master(sheets["MASTER"])
    names = master["Client (clean)"].dropna().astype(str)
    assert (names == names.str.strip()).all()


# ---------------------------------------------------------------------------
# WIP Margin by Stream — the live sheet is not fit to report from
# ---------------------------------------------------------------------------

def test_wip_margin_sheet_is_flagged_unusable(sheets, cons) -> None:
    """Two faults in the workbook, either of which invalidates every margin.

    If this test ever fails, the sheet has been fixed in Excel — check both
    conditions, then let the tab render.
    """
    from streamlit_app.data.parsers import assess_wip_margin, parse_wip_margin

    parsed = parse_wip_margin(sheets["WIP Margin by Stream"])
    assert set(parsed) == {"revenue", "cogs", "margin", "check"}

    quality = assess_wip_margin(parsed, cons)
    assert quality.costs_allocated is False, (
        "Section B now has cost allocated — good. Re-check the margins and "
        "update this test."
    )
    assert len(quality.period_mismatch) == 6, (
        "Column periods no longer disagree with the P&L — the 24-month formula "
        "offset may have been fixed."
    )
    assert quality.usable is False


def test_wip_margin_columns_hold_data_two_years_older_than_their_label(sheets, cons) -> None:
    """Jan-26 column carries Jan 2024 figures. Documents the defect precisely."""
    from streamlit_app.data.parsers import assess_wip_margin, parse_wip_margin

    quality = assess_wip_margin(parse_wip_margin(sheets["WIP Margin by Stream"]), cons)
    sheet_value, expected = quality.period_mismatch["Jan 2026"]
    assert expected == pytest.approx(4_010_178_131, abs=TOL)   # Jan 2026, correct
    assert sheet_value == pytest.approx(1_196_856_516, abs=TOL)  # Jan 2024, what's there


def test_margin_rows_are_not_filed_as_costs(sheets) -> None:
    from streamlit_app.data.parsers import parse_wip_margin

    parsed = parse_wip_margin(sheets["WIP Margin by Stream"])
    assert "3PL Deliveries Margin" in set(parsed["margin"]["Stream"])
    assert "3PL Deliveries Margin" not in set(parsed["cogs"]["Stream"])
