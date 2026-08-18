"""Month-on-month movement — the four ways a growth number lies.

Each test here corresponds to a figure that is arithmetically correct and
financially false. The module exists to refuse to produce them.
"""
from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.data.momentum import (
    BASIS_GAP,
    BASIS_NO_PRIOR,
    BASIS_OK,
    BASIS_SMALL_BASE,
    MOM_PCT_BASE_FLOOR,
    month_on_month,
    momentum_caveats,
)

BN = 1_000_000_000.0
MN = 1_000_000.0


def _long(rows: list[tuple[str, str, float]], metric: str = "Total Gross Revenue") -> pd.DataFrame:
    """rows: (entity, "Jan 2026", value). Revenue is the actual-month probe."""
    return pd.DataFrame([
        {
            "Entity": e,
            "Metric": metric,
            "Month": m,
            "MonthDate": pd.Timestamp(m),
            "Value": v,
        }
        for e, m, v in rows
    ])


# ---------------------------------------------------------------------------
# The plain case
# ---------------------------------------------------------------------------

def test_delta_and_pct_for_consecutive_closed_months():
    df = _long([
        ("Blitz", "Jan 2026", 2 * BN),
        ("Blitz", "Feb 2026", 2.5 * BN),
    ])
    mom = month_on_month(df, "Total Gross Revenue")
    feb = mom[mom["Month"] == "Feb 2026"].iloc[0]
    assert feb["Delta"] == pytest.approx(0.5 * BN)
    assert feb["Pct"] == pytest.approx(0.25)
    assert feb["Basis"] == BASIS_OK and bool(feb["Comparable"])


def test_the_first_month_has_no_prior_and_says_so():
    df = _long([("Blitz", "Jan 2026", 2 * BN), ("Blitz", "Feb 2026", 2.5 * BN)])
    jan = month_on_month(df, "Total Gross Revenue").iloc[0]
    assert pd.isna(jan["Delta"]) and jan["Basis"] == BASIS_NO_PRIOR


def test_entities_are_compared_against_themselves_not_each_other():
    df = _long([
        ("Blitz", "Jan 2026", 2 * BN), ("Borzo", "Jan 2026", 1 * BN),
        ("Blitz", "Feb 2026", 3 * BN), ("Borzo", "Feb 2026", 1.5 * BN),
    ])
    mom = month_on_month(df, "Total Gross Revenue")
    feb = mom[mom["Month"] == "Feb 2026"].set_index("Entity")
    assert feb.loc["Blitz", "Delta"] == pytest.approx(1 * BN)
    assert feb.loc["Borzo", "Delta"] == pytest.approx(0.5 * BN)


# ---------------------------------------------------------------------------
# Lie 1 — comparing against a month that has not closed
# ---------------------------------------------------------------------------

def test_an_unclosed_month_is_not_a_minus_100_percent_collapse():
    """The workbook carries a 12-month grid; unclosed months read as zero."""
    df = _long([
        ("Blitz", "Jan 2026", 2 * BN),
        ("Blitz", "Feb 2026", 2.4 * BN),
        ("Blitz", "Mar 2026", 0.0),      # not closed yet
    ])
    mom = month_on_month(df, "Total Gross Revenue")
    assert "Mar 2026" not in set(mom["Month"])
    assert mom["Pct"].min() > -1.0


def test_a_rounding_artefact_month_does_not_become_the_base():
    """Unclosed months have been observed carrying values as small as -1."""
    df = _long([
        ("Blitz", "Jan 2026", 2 * BN),
        ("Blitz", "Feb 2026", -1.0),
        ("Blitz", "Mar 2026", 2.2 * BN),
    ])
    mom = month_on_month(df, "Total Gross Revenue")
    assert "Feb 2026" not in set(mom["Month"])
    # Mar's prior is Jan, which is not adjacent — so no MoM is claimed.
    mar = mom[mom["Month"] == "Mar 2026"].iloc[0]
    assert mar["Basis"] == BASIS_GAP and pd.isna(mar["Delta"])


# ---------------------------------------------------------------------------
# Lie 2 — a gap in the calendar wearing a "MoM" label
# ---------------------------------------------------------------------------

def test_a_missing_month_is_not_silently_bridged():
    """shift(1) over a gap yields a two-month change called "MoM"."""
    df = _long([
        ("Blitz", "Jan 2026", 2 * BN),
        ("Blitz", "Apr 2026", 3 * BN),
    ])
    apr = month_on_month(df, "Total Gross Revenue")
    apr = apr[apr["Month"] == "Apr 2026"].iloc[0]
    assert apr["Basis"] == BASIS_GAP
    assert pd.isna(apr["Delta"]) and pd.isna(apr["Pct"])


def test_a_december_to_january_step_is_adjacent():
    df = _long([
        ("Blitz", "Dec 2025", 2 * BN),
        ("Blitz", "Jan 2026", 2.4 * BN),
    ])
    jan = month_on_month(df, "Total Gross Revenue")
    jan = jan[jan["Month"] == "Jan 2026"].iloc[0]
    assert jan["Basis"] == BASIS_OK
    assert jan["Delta"] == pytest.approx(0.4 * BN)


# ---------------------------------------------------------------------------
# Lie 3 — a base too small to carry a percentage
# ---------------------------------------------------------------------------

def test_a_tiny_base_yields_a_delta_but_no_percentage():
    """Rp2M then Rp200M is a base effect, not +9,900% growth."""
    df = _long([
        ("TheLorry", "Jan 2026", 2 * MN),
        ("TheLorry", "Feb 2026", 200 * MN),
    ])
    feb = month_on_month(df, "Total Gross Revenue")
    feb = feb[feb["Month"] == "Feb 2026"].iloc[0]
    assert feb["Delta"] == pytest.approx(198 * MN)   # the rupiah is still reported
    assert pd.isna(feb["Pct"])
    assert feb["Basis"] == BASIS_SMALL_BASE


def test_the_base_floor_is_configurable():
    df = _long([
        ("TheLorry", "Jan 2026", 2 * MN),
        ("TheLorry", "Feb 2026", 4 * MN),
    ])
    feb = month_on_month(df, "Total Gross Revenue", base_floor=1 * MN)
    feb = feb[feb["Month"] == "Feb 2026"].iloc[0]
    assert feb["Pct"] == pytest.approx(1.0)


def test_default_floor_is_documented_where_it_is_used():
    assert MOM_PCT_BASE_FLOOR == 50_000_000.0


# ---------------------------------------------------------------------------
# Lie 4 — dividing by a signed base
# ---------------------------------------------------------------------------

def test_an_improving_loss_reads_positive():
    """Blitz runs a net loss. -2.4B to -2.0B is a Rp400M improvement.

    Dividing by -2.4 renders +16.7% as -16.7%, which reads as deterioration.
    """
    df = pd.concat([
        _long([("Blitz", "Jan 2026", 3 * BN), ("Blitz", "Feb 2026", 3 * BN)]),
        _long(
            [("Blitz", "Jan 2026", -2.4 * BN), ("Blitz", "Feb 2026", -2.0 * BN)],
            metric="NET PROFIT/LOSS (Before Tax)",
        ),
    ], ignore_index=True)
    feb = month_on_month(df, "NET PROFIT/LOSS (Before Tax)")
    feb = feb[feb["Month"] == "Feb 2026"].iloc[0]
    assert feb["Delta"] > 0
    assert feb["Pct"] > 0
    assert feb["Pct"] == pytest.approx(0.4 / 2.4)


def test_a_deepening_loss_reads_negative():
    df = pd.concat([
        _long([("Blitz", "Jan 2026", 3 * BN), ("Blitz", "Feb 2026", 3 * BN)]),
        _long(
            [("Blitz", "Jan 2026", -2.0 * BN), ("Blitz", "Feb 2026", -2.4 * BN)],
            metric="NET PROFIT/LOSS (Before Tax)",
        ),
    ], ignore_index=True)
    feb = month_on_month(df, "NET PROFIT/LOSS (Before Tax)")
    feb = feb[feb["Month"] == "Feb 2026"].iloc[0]
    assert feb["Delta"] < 0 and feb["Pct"] < 0


def test_sign_of_pct_always_matches_sign_of_delta():
    df = pd.concat([
        _long([("Blitz", m, 3 * BN) for m in ("Jan 2026", "Feb 2026", "Mar 2026")]),
        _long(
            [("Blitz", "Jan 2026", -2.0 * BN), ("Blitz", "Feb 2026", 1.0 * BN),
             ("Blitz", "Mar 2026", -0.5 * BN)],
            metric="EBITDA",
        ),
    ], ignore_index=True)
    mom = month_on_month(df, "EBITDA")
    paired = mom[mom["Pct"].notna()]
    assert not paired.empty
    assert ((paired["Delta"] > 0) == (paired["Pct"] > 0)).all()


# ---------------------------------------------------------------------------
# The window reaches outside itself
# ---------------------------------------------------------------------------

def test_the_first_month_on_screen_compares_against_the_month_before_it():
    """A range starting at Feb should still show Feb's change against Jan."""
    df = _long([
        ("Blitz", "Jan 2026", 2 * BN),
        ("Blitz", "Feb 2026", 2.5 * BN),
        ("Blitz", "Mar 2026", 2.8 * BN),
    ])
    mom = month_on_month(df, "Total Gross Revenue", months=["Feb 2026", "Mar 2026"])
    assert set(mom["Month"]) == {"Feb 2026", "Mar 2026"}
    feb = mom[mom["Month"] == "Feb 2026"].iloc[0]
    assert feb["Delta"] == pytest.approx(0.5 * BN)   # not blank


# ---------------------------------------------------------------------------
# Caveats
# ---------------------------------------------------------------------------

def test_every_withheld_month_is_explained():
    df = _long([
        ("TheLorry", "Jan 2026", 2 * MN),
        ("TheLorry", "Feb 2026", 200 * MN),
    ])
    notes = momentum_caveats(month_on_month(df, "Total Gross Revenue"))
    assert any("Feb 2026" in n for n in notes)
    assert any("Jan 2026" in n for n in notes)


def test_a_clean_series_produces_no_noise():
    df = _long([
        ("Blitz", "Jan 2026", 2 * BN),
        ("Blitz", "Feb 2026", 2.5 * BN),
    ])
    mom = month_on_month(df, "Total Gross Revenue", months=["Feb 2026"])
    assert momentum_caveats(mom) == []


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("df", [None, pd.DataFrame(), pd.DataFrame({"Month": []})])
def test_empty_input_returns_an_empty_frame_not_an_exception(df):
    out = month_on_month(df, "Total Gross Revenue")
    assert out.empty and "Delta" in out.columns


def test_unknown_metric_returns_empty():
    df = _long([("Blitz", "Jan 2026", 2 * BN), ("Blitz", "Feb 2026", 3 * BN)])
    assert month_on_month(df, "Nonexistent Metric").empty


# ---------------------------------------------------------------------------
# The table form
# ---------------------------------------------------------------------------

def _fmt(value: float) -> str:
    """Stand-in for the tab's currency formatter (positive magnitudes only)."""
    if value >= 1_000_000_000:
        return f"Rp{value / 1_000_000_000:,.1f}B"
    if value >= 1_000_000:
        return f"Rp{value / 1_000_000:,.0f}M"
    return f"Rp{value:,.0f}"


def test_matrix_is_one_row_per_entity_and_one_column_per_month():
    from streamlit_app.data.momentum import mom_matrix

    df = _long([
        ("Blitz", "Jan 2026", 2 * BN), ("Borzo", "Jan 2026", 1 * BN),
        ("Blitz", "Feb 2026", 2.5 * BN), ("Borzo", "Feb 2026", 1.1 * BN),
        ("Blitz", "Mar 2026", 2.4 * BN), ("Borzo", "Mar 2026", 1.3 * BN),
    ])
    table = mom_matrix(month_on_month(df, "Total Gross Revenue"), _fmt)

    assert list(table.columns) == ["Entity", "Jan 2026", "Feb 2026", "Mar 2026"]
    assert set(table["Entity"]) == {"Blitz", "Borzo"}


def test_a_cell_carries_the_rupiah_and_the_percentage():
    """A bar height is not a number anyone can quote in a meeting."""
    from streamlit_app.data.momentum import mom_matrix

    df = _long([("Blitz", "Jan 2026", 2 * BN), ("Blitz", "Feb 2026", 2.5 * BN)])
    table = mom_matrix(month_on_month(df, "Total Gross Revenue"), _fmt)
    assert table.loc[0, "Feb 2026"] == "+Rp500M (+25.0%)"


def test_a_negative_change_is_signed_in_the_cell():
    from streamlit_app.data.momentum import mom_matrix

    df = _long([("Blitz", "Jan 2026", 2.5 * BN), ("Blitz", "Feb 2026", 2 * BN)])
    table = mom_matrix(month_on_month(df, "Total Gross Revenue"), _fmt)
    cell = table.loc[0, "Feb 2026"]
    assert cell.startswith("−") and "(-20.0%)" in cell


def test_a_withheld_percentage_reads_n_a_not_blank():
    """Blank reads as zero. The rupiah is still real and still shown."""
    from streamlit_app.data.momentum import mom_matrix

    df = _long([
        ("TheLorry", "Jan 2026", 2 * MN),
        ("TheLorry", "Feb 2026", 200 * MN),
    ])
    table = mom_matrix(month_on_month(df, "Total Gross Revenue"), _fmt)
    assert table.loc[0, "Feb 2026"] == "+Rp198M (n/a)"


def test_a_month_with_no_comparable_prior_reads_as_a_dash():
    from streamlit_app.data.momentum import mom_matrix

    df = _long([("Blitz", "Jan 2026", 2 * BN), ("Blitz", "Feb 2026", 2.5 * BN)])
    table = mom_matrix(month_on_month(df, "Total Gross Revenue"), _fmt)
    assert table.loc[0, "Jan 2026"] == "—"


def test_matrix_columns_follow_the_caller_s_month_order():
    """Alphabetical column order would put Apr before Jan."""
    from streamlit_app.data.momentum import mom_matrix

    df = _long([
        ("Blitz", "Jan 2026", 2 * BN), ("Blitz", "Feb 2026", 2.2 * BN),
        ("Blitz", "Mar 2026", 2.4 * BN), ("Blitz", "Apr 2026", 2.6 * BN),
    ])
    mom = month_on_month(df, "Total Gross Revenue")
    months = ["Feb 2026", "Mar 2026", "Apr 2026"]
    table = mom_matrix(mom, _fmt, months=months)
    assert list(table.columns) == ["Entity"] + months


def test_an_entity_absent_from_a_month_gets_a_dash_not_a_gap():
    from streamlit_app.data.momentum import mom_matrix

    df = _long([
        ("Blitz", "Jan 2026", 2 * BN), ("Blitz", "Feb 2026", 2.5 * BN),
        ("Blitz", "Mar 2026", 2.6 * BN),
        ("Borzo", "Mar 2026", 1 * BN),
    ])
    table = mom_matrix(month_on_month(df, "Total Gross Revenue"), _fmt)
    borzo = table[table["Entity"] == "Borzo"].iloc[0]
    assert borzo["Feb 2026"] == "—"


def test_matrix_of_nothing_is_empty_not_an_exception():
    from streamlit_app.data.momentum import mom_matrix

    assert mom_matrix(pd.DataFrame(), _fmt).empty
    assert mom_matrix(None, _fmt).empty


def test_a_dormant_month_reads_as_a_dash_not_plus_zero():
    """TheLorry's pre-launch quarter: three "+Rp0 (n/a)" cells crowd out the
    months that actually moved."""
    from streamlit_app.data.momentum import mom_matrix

    df = _long([
        ("TheLorry", "Jan 2026", 0.0), ("TheLorry", "Feb 2026", 0.0),
        ("TheLorry", "Mar 2026", 150 * MN), ("TheLorry", "Apr 2026", 180 * MN),
        # Something has to be trading for the months to count as closed.
        ("Blitz", "Jan 2026", 2 * BN), ("Blitz", "Feb 2026", 2 * BN),
        ("Blitz", "Mar 2026", 2 * BN), ("Blitz", "Apr 2026", 2 * BN),
    ])
    table = mom_matrix(month_on_month(df, "Total Gross Revenue"), _fmt)
    lorry = table[table["Entity"] == "TheLorry"].iloc[0]
    assert lorry["Feb 2026"] == "—"
    assert lorry["Mar 2026"].startswith("+Rp150M")


def test_a_real_flat_month_is_not_hidden():
    """Rp2B then Rp2B is a genuine zero change and must be reported as one."""
    from streamlit_app.data.momentum import mom_matrix

    df = _long([("Blitz", "Jan 2026", 2 * BN), ("Blitz", "Feb 2026", 2 * BN)])
    table = mom_matrix(month_on_month(df, "Total Gross Revenue"), _fmt)
    assert table.loc[0, "Feb 2026"] == "+Rp0 (+0.0%)"
