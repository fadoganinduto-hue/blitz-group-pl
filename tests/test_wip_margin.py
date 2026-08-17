"""Tests for the WIP Margin by Stream sheet — parsing and fitness-to-report."""
from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.data.parsers import assess_wip_margin, parse_wip_margin

MONTHS = ["Jan-26", "Feb-26", "Mar-26"]


def _sheet(cost_rows, revenue_total=(100.0, 100.0, 100.0)):
    """Build a WIP-shaped sheet: lettered sections, months on row 3."""
    rows = [[None] * 5 for _ in range(4)]
    rows[0][1] = "MARGIN BY REVENUE STREAM — 2026"
    for i, m in enumerate(MONTHS):
        rows[3][2 + i] = m
    def add(label, values=None):
        row = [None] * 5
        row[1] = label
        if values:
            for i, v in enumerate(values):
                row[2 + i] = v
        rows.append(row)
    add("A.  REVENUE BY STREAM (from entity Detail sheets)")
    add("3PL Deliveries", [60.0, 60.0, 60.0])
    add("EV Leasing", [40.0, 40.0, 40.0])
    add("Total Revenue", list(revenue_total))
    add("B.  COST OF REVENUE BY STREAM (allocated)")
    add("3PL Deliveries", cost_rows[0])
    add("EV Leasing", cost_rows[1])
    add("Total Cost of Revenue", [a + b for a, b in zip(*cost_rows)])
    add("C.  GROSS MARGIN BY STREAM")
    add("3PL Deliveries Margin", [10.0, 10.0, 10.0])
    add("   margin %", [0.16, 0.16, 0.16])
    add("Total Gross Margin", [20.0, 20.0, 20.0])
    add("D.  CHECK vs GROUP TOTALS")
    add("Revenue: streams − Σ entity Total REVENUE", [0.0, 0.0, 0.0])
    return pd.DataFrame(rows)


def _cons(values):
    return pd.DataFrame([
        {"Entity": "Consolidated", "Metric": "Total Gross Revenue",
         "Month": m, "Value": v, "MonthDate": pd.Timestamp(f"2026-{i+1:02d}-01")}
        for i, (m, v) in enumerate(zip(["Jan 2026", "Feb 2026", "Mar 2026"], values))
    ])


# ---------------------------------------------------------------------------
# Section routing
# ---------------------------------------------------------------------------

def test_sections_are_keyed_on_the_letter_not_keywords():
    """'3PL Deliveries Margin' must land in margin, never in cogs."""
    s = parse_wip_margin(_sheet(([5.0] * 3, [5.0] * 3)))
    assert set(s) == {"revenue", "cogs", "margin", "check"}
    assert "3PL Deliveries Margin" in set(s["margin"]["Stream"])
    assert "3PL Deliveries Margin" not in set(s["cogs"]["Stream"])
    assert "3PL Deliveries" in set(s["revenue"]["Stream"])


def test_derived_ratio_rows_are_excluded():
    s = parse_wip_margin(_sheet(([5.0] * 3, [5.0] * 3)))
    assert not any("margin %" in x.lower() for x in s["margin"]["Stream"])


def test_month_labels_are_canonicalised():
    """The sheet writes 'Jan-26'; every cross-check joins on 'Jan 2026'."""
    s = parse_wip_margin(_sheet(([5.0] * 3, [5.0] * 3)))
    assert set(s["revenue"]["Month"]) == {"Jan 2026", "Feb 2026", "Mar 2026"}


def test_totals_are_flagged():
    s = parse_wip_margin(_sheet(([5.0] * 3, [5.0] * 3)))
    totals = s["revenue"][s["revenue"]["IsTotal"]]
    assert set(totals["Stream"]) == {"Total Revenue"}


# ---------------------------------------------------------------------------
# Fitness to report
# ---------------------------------------------------------------------------

def test_zero_cost_allocation_makes_the_sheet_unusable():
    """All-zero costs mean every margin is 100% — must not be rendered."""
    q = assess_wip_margin(parse_wip_margin(_sheet(([0.0] * 3, [0.0] * 3))), _cons([100.0] * 3))
    assert q.costs_allocated is False
    assert q.usable is False


def test_allocated_costs_and_matching_periods_are_usable():
    q = assess_wip_margin(
        parse_wip_margin(_sheet(([25.0] * 3, [15.0] * 3))), _cons([100.0] * 3)
    )
    assert q.costs_allocated is True
    assert q.period_mismatch == {}
    assert q.usable is True


def test_period_offset_is_detected():
    """Columns labelled 2026 holding 2024 figures must be caught."""
    q = assess_wip_margin(
        parse_wip_margin(_sheet(([25.0] * 3, [15.0] * 3), revenue_total=(100.0, 100.0, 100.0))),
        _cons([400.0, 400.0, 400.0]),
    )
    assert len(q.period_mismatch) == 3
    assert q.usable is False
    sheet_value, expected = q.period_mismatch["Jan 2026"]
    assert sheet_value == 100.0 and expected == 400.0


def test_assessment_without_a_pl_still_checks_costs():
    """No Consolidated sheet: the cost check must still apply."""
    q = assess_wip_margin(parse_wip_margin(_sheet(([0.0] * 3, [0.0] * 3))), None)
    assert q.costs_allocated is False
    assert q.usable is False


def test_rounding_noise_is_not_a_period_mismatch():
    q = assess_wip_margin(
        parse_wip_margin(_sheet(([25.0] * 3, [15.0] * 3), revenue_total=(100.0, 100.0, 100.0))),
        _cons([100.4, 100.0, 99.7]),
    )
    assert q.period_mismatch == {}, "sub-rupiah differences are not misstatements"
