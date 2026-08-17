"""Tests for the derived reconciliation checks."""
from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.data.reconciliation import (
    BRIDGE_MATERIALITY_IDR,
    coverage_gaps,
    master_vs_pl_bridge,
)


def _master(rows):
    return pd.DataFrame([
        {"Month": m, "MonthDate": pd.Timestamp(d), "Amount (IDR)": v}
        for m, d, v in rows
    ])


def _cons(rows):
    return pd.DataFrame([
        {"Metric": "Total Gross Revenue", "Month": m,
         "MonthDate": pd.Timestamp(d), "Value": v}
        for m, d, v in rows
    ])


# ---------------------------------------------------------------------------
# Comparability — the distinction between a variance and a coverage gap
# ---------------------------------------------------------------------------

def test_month_covered_by_both_sources_is_comparable():
    b = master_vs_pl_bridge(
        _master([("Jan 2026", "2026-01-01", 105.0)]),
        _cons([("Jan 2026", "2026-01-01", 100.0)]),
    )
    row = b.iloc[0]
    assert row["Comparable"] is True or row["Comparable"] == True  # noqa: E712
    assert row["Delta"] == pytest.approx(5.0)


def test_month_missing_from_master_is_not_a_variance():
    """MASTER not reaching a month is a COVERAGE gap, not a billion-rupiah break.

    Counting these as variances reported Rp32B gross unreconciled against a
    true Rp348M, because MASTER simply does not cover 2024 at all.
    """
    b = master_vs_pl_bridge(
        _master([("Jan 2026", "2026-01-01", 100.0)]),
        _cons([("Jan 2024", "2024-01-01", 4_000.0),
               ("Jan 2026", "2026-01-01", 100.0)]),
    )
    gap = b[b["Month"] == "Jan 2024"].iloc[0]
    assert not gap["Comparable"]
    assert pd.isna(gap["Delta"]), "an uncovered month has no meaningful variance"
    comparable = b[b["Comparable"]]
    assert len(comparable) == 1
    assert float(comparable["AbsDelta"].sum()) == pytest.approx(0.0)


def test_unclosed_month_is_not_comparable():
    """A P&L month with zero revenue has not closed; nothing to reconcile."""
    b = master_vs_pl_bridge(
        _master([("Jan 2026", "2026-01-01", 100.0)]),
        _cons([("Jan 2026", "2026-01-01", 100.0),
               ("Dec 2026", "2026-12-01", 0.0)]),
    )
    assert not b[b["Month"] == "Dec 2026"].iloc[0]["Comparable"]


def test_variance_totals_use_comparable_months_only():
    b = master_vs_pl_bridge(
        _master([("Feb 2026", "2026-02-01", 90.0)]),
        _cons([("Jan 2026", "2026-01-01", 5_000.0),
               ("Feb 2026", "2026-02-01", 100.0)]),
    )
    comparable = b[b["Comparable"]]
    assert float(comparable["AbsDelta"].sum()) == pytest.approx(10.0)
    assert float(comparable["AbsDelta"].max()) < BRIDGE_MATERIALITY_IDR


# ---------------------------------------------------------------------------
# Coverage gaps
# ---------------------------------------------------------------------------

def test_coverage_gap_lists_uncovered_closed_months():
    gaps = coverage_gaps(
        ["May 2026", "Jun 2026", "Jul 2026"],
        _master([("May 2026", "2026-05-01", 1.0), ("Jun 2026", "2026-06-01", 1.0)]),
    )
    assert len(gaps) == 1
    assert gaps[0].months == ("Jul 2026",)
    assert "Jul 2026" in gaps[0].detail
    assert "unattributed" in gaps[0].detail


def test_no_gap_when_every_closed_month_is_covered():
    assert coverage_gaps(
        ["May 2026"], _master([("May 2026", "2026-05-01", 1.0)])
    ) == []


def test_tie_out_source_is_optional():
    """The retired sheet is simply not passed; the call must still work."""
    gaps = coverage_gaps(["Jul 2026"], _master([("Jun 2026", "2026-06-01", 1.0)]))
    assert [g.source for g in gaps] == ["Client breakdown (MASTER)"]


# ---------------------------------------------------------------------------
# Summary vs Detail — the granularity toggle must not change a number silently
# ---------------------------------------------------------------------------

def _pl(entity, rows):
    return pd.DataFrame([
        {"Entity": entity, "Metric": "Total Gross Revenue", "Month": m,
         "MonthDate": pd.Timestamp(d), "Value": v}
        for m, d, v in rows
    ])


def test_summary_and_detail_disagreement_is_reported():
    from streamlit_app.data.reconciliation import summary_vs_detail

    out = summary_vs_detail(
        {"Blitz": _pl("Blitz", [("Jun 2026", "2026-06-01", 3_661_974_619)])},
        {"Blitz": _pl("Blitz", [("Jun 2026", "2026-06-01", 2_968_578_119)])},
    )
    assert len(out) == 1
    assert out.iloc[0]["Delta"] == pytest.approx(693_396_500)
    assert out.iloc[0]["Entity"] == "Blitz"


def test_agreeing_months_are_not_reported():
    from streamlit_app.data.reconciliation import summary_vs_detail

    out = summary_vs_detail(
        {"Borzo": _pl("Borzo", [("Jun 2026", "2026-06-01", 1_143_733_236)])},
        {"Borzo": _pl("Borzo", [("Jun 2026", "2026-06-01", 1_143_733_236)])},
    )
    assert out.empty


def test_rounding_is_not_a_disagreement():
    from streamlit_app.data.reconciliation import summary_vs_detail

    out = summary_vs_detail(
        {"Blitz": _pl("Blitz", [("Jun 2026", "2026-06-01", 1_000_000_000)])},
        {"Blitz": _pl("Blitz", [("Jun 2026", "2026-06-01", 1_000_000_500)])},
    )
    assert out.empty, "sub-materiality differences are not disagreements"


def test_month_absent_from_one_granularity_is_skipped():
    """An inner join: a month only one sheet covers is not a disagreement."""
    from streamlit_app.data.reconciliation import summary_vs_detail

    out = summary_vs_detail(
        {"Blitz": _pl("Blitz", [("Jul 2026", "2026-07-01", 5_000_000_000)])},
        {"Blitz": _pl("Blitz", [("Jun 2026", "2026-06-01", 1_000_000_000)])},
    )
    assert out.empty
