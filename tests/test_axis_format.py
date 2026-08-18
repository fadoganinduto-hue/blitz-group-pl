"""The currency axis must speak the same dialect as the rest of the dashboard.

Plotly's tickformat="~s" is D3 SI notation: 10^9 is labelled "G" (giga). Every
other figure on screen comes from fmt_idr and says "B". The axis read "Rp2.5G"
next to a KPI card reading "Rp2.5B" — the same number, twice, in two languages,
and nothing on screen told the reader that "G" meant billion.

These tests pin the replacement: explicit tick values, one unit for the whole
axis, text built from the same thresholds fmt_idr uses.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from streamlit_app.components import charts
from streamlit_app.components.charts import (
    _financial_ticks,
    _nice_step,
    _value_axis_extent,
    comparison_bar_chart,
    entity_revenue_line_chart,
    pareto_chart,
    trend_line_chart,
    variance_bar_chart,
    waterfall_chart,
)

BN = 1_000_000_000.0
MN = 1_000_000.0


@pytest.fixture(autouse=True)
def _idr(monkeypatch):
    """Charts read the active currency from Streamlit session state."""
    monkeypatch.setattr(charts, "_get_prefix", lambda: "Rp")


def _axis(fig: go.Figure, axis: str = "y") -> dict:
    return (fig.layout.yaxis if axis == "y" else fig.layout.xaxis).to_plotly_json()


def _ticktext(fig: go.Figure, axis: str = "y") -> tuple[str, ...]:
    return tuple(_axis(fig, axis).get("ticktext") or ())


# ---------------------------------------------------------------------------
# Tick arithmetic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rough, expected",
    [
        (1.0, 1.0),
        (1.1, 2.0),
        (2.4, 2.5),
        (3.0, 5.0),
        (6.0, 10.0),
        (7.3e8, 1e9),
        (0.0, 0.0),
        (-5.0, 0.0),
    ],
)
def test_nice_step_rounds_up_to_a_readable_interval(rough, expected):
    assert _nice_step(rough) == pytest.approx(expected)


def test_ticks_are_labelled_in_billions_not_giga():
    vals, text, _ = _financial_ticks(0, 3.2 * BN, "Rp")
    assert vals[0] == 0
    assert text[0] == "Rp0"
    assert all("G" not in t for t in text)
    assert any(t.endswith("B") for t in text)


def test_ticks_use_one_unit_across_the_whole_axis():
    """Mixing 'Rp500M' and 'Rp1B' on one axis makes the gridlines unreadable."""
    _, text, _rng = _financial_ticks(0, 2 * BN, "Rp")
    suffixes = {t[-1] for t in text if t != "Rp0"}
    assert suffixes == {"B"}


def test_step_widens_rather_than_labelling_quarter_billions():
    """A 250M step under a 1.5B ceiling would read "Rp0.25B" — widen instead."""
    _, text, _rng = _financial_ticks(0, 1.4 * BN, "Rp")
    assert text == ("Rp0", "Rp0.5B", "Rp1.0B", "Rp1.5B") or list(text) == [
        "Rp0", "Rp0.5B", "Rp1.0B", "Rp1.5B",
    ]


def test_decimals_are_uniform_down_the_axis():
    """Ragged "Rp0.5B / Rp1B / Rp1.5B" is harder to scan than fixed places."""
    _, text, _rng = _financial_ticks(0, 1.4 * BN, "Rp")
    decimals = {len(t.split(".")[1]) - 1 for t in text if "." in t}
    assert len(decimals) == 1


def test_millions_scale_axis_uses_M():
    _, text, _rng = _financial_ticks(0, 600 * MN, "Rp")
    assert all("G" not in t and "B" not in t for t in text)
    assert any(t.endswith("M") for t in text)


def test_negative_span_keeps_zero_and_signs_the_losses():
    vals, text, _ = _financial_ticks(-2 * BN, 3 * BN, "Rp")
    assert 0.0 in vals
    assert any(t.startswith("-Rp") for t in text)
    assert text[vals.index(0.0)] == "Rp0"


def test_ticks_span_the_data():
    lo, hi = -1.4 * BN, 4.6 * BN
    vals, _t, _rng = _financial_ticks(lo, hi, "Rp")
    assert min(vals) <= lo and max(vals) >= hi


def test_a_bar_axis_keeps_the_baseline_on_screen():
    """Truncating a bar axis makes a 4% move look like a doubling."""
    _, _t, rng = _financial_ticks(2.4 * BN, 2.5 * BN, "Rp", include_zero=True)
    assert rng is not None and rng[0] == 0


def test_a_line_axis_is_not_pinned_to_zero():
    """A revenue trend held against zero flattens into a straight edge."""
    _, _t, rng = _financial_ticks(2.4 * BN, 3.8 * BN, "Rp", include_zero=False)
    assert rng is not None and rng[0] > 0


def test_the_range_matches_the_ticks():
    """A tick outside the rendered range is a gridline that never appears.

    Without this the MoM bars dipped below zero while the axis showed no
    negative label at all: the -Rp0.5B tick sat outside Plotly's autorange.
    """
    vals, _t, rng = _financial_ticks(-0.25 * BN, 1.15 * BN, "Rp")
    assert rng == (vals[0], vals[-1])
    assert rng[0] < 0, "a negative tick must be reachable when bars go negative"


def test_usd_prefix_is_honoured():
    _, text, _rng = _financial_ticks(0, 2 * BN, "$")
    assert text[-1].startswith("$")


# ---------------------------------------------------------------------------
# Extent detection
# ---------------------------------------------------------------------------

def test_waterfall_extent_follows_the_running_total_not_the_deltas():
    """A waterfall's y values are steps; the axis measures where they land."""
    fig = waterfall_chart(
        ["Revenue", "COGS", "Gross Profit"],
        [5 * BN, -3 * BN, 2 * BN],
        measures=["absolute", "relative", "total"],
    )
    lo, hi = _value_axis_extent(fig, "y")
    assert hi == pytest.approx(5 * BN)   # the peak, not the 5B step alone
    assert lo == pytest.approx(2 * BN)


def test_secondary_axis_series_is_excluded_from_the_currency_extent():
    """Pareto's cumulative % rides y2 — 0-100 must not shrink the money axis."""
    fig = pareto_chart(["A", "B", "C"], [3 * BN, 2 * BN, 1 * BN])
    lo, hi = _value_axis_extent(fig, "y")
    assert hi == pytest.approx(3 * BN)
    assert all("G" not in t for t in _ticktext(fig))


# ---------------------------------------------------------------------------
# Every builder that draws money
# ---------------------------------------------------------------------------

def _months() -> pd.DataFrame:
    return pd.DataFrame({
        "Month": ["Apr 2026", "May 2026", "Jun 2026"] * 2,
        "Value": [2.1 * BN, 2.4 * BN, 2.9 * BN, 1.1 * BN, 1.3 * BN, 1.2 * BN],
        "Entity": ["Blitz"] * 3 + ["Borzo"] * 3,
    })


def test_trend_line_chart_axis_reads_in_billions():
    fig = trend_line_chart(_months(), "Month", "Value", "Entity")
    text = _ticktext(fig)
    assert text and all("G" not in t for t in text)
    assert _axis(fig).get("tickformat") != "~s"


def test_entity_revenue_line_chart_axis_reads_in_billions():
    fig = entity_revenue_line_chart(_months(), "Month", "Value", "Entity")
    assert all("G" not in t for t in _ticktext(fig))


def test_vertical_bar_chart_axis_reads_in_billions():
    df = _months()[["Month", "Value"]].groupby("Month", as_index=False).sum()
    fig = comparison_bar_chart(df, "Month", "Value")
    assert all("G" not in t for t in _ticktext(fig))


def test_waterfall_axis_reads_in_billions():
    fig = waterfall_chart(
        ["Revenue", "COGS", "Net"], [5 * BN, -3 * BN, 2 * BN],
        measures=["absolute", "relative", "total"],
    )
    assert all("G" not in t for t in _ticktext(fig))


def test_variance_bar_chart_labels_its_horizontal_value_axis():
    fig = variance_bar_chart(["Revenue", "COGS"], [3 * BN, 2 * BN], [2.5 * BN, 1.8 * BN])
    text = _ticktext(fig, "x")
    assert text and all("G" not in t for t in text)


# ---------------------------------------------------------------------------
# Horizontal bars — client-by-entity panels
# ---------------------------------------------------------------------------

def _clients() -> pd.DataFrame:
    return pd.DataFrame({
        "Client (clean)": ["Grab", "JNE", "Halodoc", "Other (12)"],
        "Amount (IDR)": [1.4 * BN, 900 * MN, 400 * MN, 250 * MN],
    })


def test_numeric_x_with_categorical_y_puts_currency_on_x():
    fig = comparison_bar_chart(_clients(), x="Amount (IDR)", y="Client (clean)")
    assert fig.data[0].orientation == "h"
    text = _ticktext(fig, "x")
    assert text and all("G" not in t for t in text)


def test_client_names_never_get_a_currency_prefix():
    """The value axis moved to x; stamping 'Rp' on y would label 'RpGrab'."""
    fig = comparison_bar_chart(_clients(), x="Amount (IDR)", y="Client (clean)")
    assert not _axis(fig, "y").get("tickprefix")
    assert not _ticktext(fig, "y")


def test_horizontal_bars_do_not_rotate_their_category_labels():
    fig = comparison_bar_chart(_clients(), x="Amount (IDR)", y="Client (clean)")
    assert _axis(fig, "y").get("tickangle") in (0, None)


def test_horizontal_hover_reads_the_value_off_the_right_axis():
    fig = comparison_bar_chart(_clients(), x="Amount (IDR)", y="Client (clean)")
    template = fig.data[0].hovertemplate
    assert "%{y}" in template and "Rp%{x:,.0f}" in template


# ---------------------------------------------------------------------------
# Month-on-month bars
# ---------------------------------------------------------------------------

def _mom_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Entity": ["Blitz", "Borzo", "Blitz", "Borzo"],
        "Month": ["May 2026", "May 2026", "Jun 2026", "Jun 2026"],
        "MonthDate": pd.to_datetime(
            ["2026-05-01", "2026-05-01", "2026-06-01", "2026-06-01"]
        ),
        "Value": [2.98 * BN, 1.15 * BN, 3.66 * BN, 1.14 * BN],
        "Prior": [2.61 * BN, 1.23 * BN, 2.98 * BN, 1.15 * BN],
        "Delta": [0.37 * BN, -0.08 * BN, 0.68 * BN, -0.01 * BN],
        "Pct": [0.141, -0.066, 0.228, -0.003],
    })


def test_mom_bars_carry_a_zero_line():
    """Signed bars are unreadable without the baseline they are signed about."""
    fig = charts.mom_bar_chart(_mom_frame())
    assert fig.layout.yaxis.zeroline is True


def test_mom_bars_are_coloured_by_entity_not_direction():
    from streamlit_app.constants import ENTITY_COLORS

    fig = charts.mom_bar_chart(_mom_frame())
    by_name = {t.name: t.marker.color for t in fig.data}
    assert by_name["Blitz"] == ENTITY_COLORS["Blitz"]
    assert by_name["Borzo"] == ENTITY_COLORS["Borzo"]


def test_mom_axis_is_labelled_in_billions():
    fig = charts.mom_bar_chart(_mom_frame())
    assert all("G" not in t for t in _ticktext(fig))


def test_mom_axis_labels_the_negative_side_it_draws_bars_on():
    fig = charts.mom_bar_chart(_mom_frame())
    text = _ticktext(fig)
    assert any(t.startswith("-Rp") for t in text)
    assert _axis(fig)["range"][0] < 0


def test_mom_y_axis_says_what_it_measures():
    """px names the axis after the column — "Delta" tells the reader nothing."""
    fig = charts.mom_bar_chart(_mom_frame())
    assert _axis(fig)["title"]["text"] == "Change vs prior month"


def test_mom_hover_names_the_prior_month_it_measured_against():
    fig = charts.mom_bar_chart(_mom_frame())
    assert "Prior month" in fig.data[0].hovertemplate
    assert "Change %" in fig.data[0].hovertemplate


def test_a_withheld_percentage_says_so_rather_than_showing_blank():
    """A blank in a hover reads as zero. It has to name itself."""
    df = _mom_frame()
    df.loc[0, "Pct"] = float("nan")
    fig = charts.mom_bar_chart(df)
    rows = [row for t in fig.data for row in (t.customdata or [])]
    assert any("withheld" in row[0] for row in rows)


def test_base_effect_bars_are_hatched_and_real_growth_is_not():
    """Borzo's +Rp1.26B January is entry into the P&L, not the best month anyone
    had. Solid, it dominates a chart of genuine single-digit-percent moves."""
    df = _mom_frame()
    df.loc[0, "Pct"] = float("nan")     # Blitz May — base too small
    fig = charts.mom_bar_chart(df)
    blitz = [t for t in fig.data if t.name == "Blitz"]
    borzo = [t for t in fig.data if t.name == "Borzo"]

    hatched = [t for t in blitz if t.marker.pattern and t.marker.pattern.shape]
    solid = [t for t in blitz if not (t.marker.pattern and t.marker.pattern.shape)]
    assert len(hatched) == 1 and list(hatched[0].x) == ["May 2026"]
    assert len(solid) == 1 and list(solid[0].x) == ["Jun 2026"]
    assert all(not (t.marker.pattern and t.marker.pattern.shape) for t in borzo)


def test_the_legend_swatch_is_never_the_hatched_one():
    """A hatched legend key reads as "this entity is a base effect"."""
    df = _mom_frame()
    df.loc[0, "Pct"] = float("nan")
    fig = charts.mom_bar_chart(df)
    for trace in fig.data:
        if trace.showlegend:
            assert not (trace.marker.pattern and trace.marker.pattern.shape)
    assert {t.name for t in fig.data if t.showlegend} == {"Blitz", "Borzo"}


def test_an_entity_that_is_only_base_effects_still_appears_in_the_legend():
    df = _mom_frame()
    df.loc[df["Entity"] == "Borzo", "Pct"] = float("nan")
    fig = charts.mom_bar_chart(df)
    assert "Borzo" in {t.name for t in fig.data if t.showlegend}


def test_split_traces_share_one_slot_per_entity():
    """Without a shared offsetgroup the hatched bar gets its own column."""
    df = _mom_frame()
    df.loc[0, "Pct"] = float("nan")
    fig = charts.mom_bar_chart(df)
    for trace in fig.data:
        assert trace.offsetgroup == trace.name


def test_rows_without_a_delta_are_not_drawn_as_zero_bars():
    df = _mom_frame()
    df.loc[0, "Delta"] = float("nan")
    fig = charts.mom_bar_chart(df)
    blitz = next(t for t in fig.data if t.name == "Blitz")
    assert len(blitz.x) == 1 and blitz.x[0] == "Jun 2026"


def test_customdata_stays_aligned_with_its_bars():
    """Misaligned customdata attaches one month's percentage to another's bar."""
    fig = charts.mom_bar_chart(_mom_frame())
    for trace in fig.data:
        assert len(trace.customdata) == len(trace.y)
    borzo = next(t for t in fig.data if t.name == "Borzo")
    order = list(borzo.x)
    assert borzo.customdata[order.index("May 2026")][0] == "-6.6%"
    assert borzo.customdata[order.index("Jun 2026")][0] == "-0.3%"


# ---------------------------------------------------------------------------
# Nothing anywhere still asks Plotly for SI ticks on a money axis
# ---------------------------------------------------------------------------

def test_no_module_hardcodes_si_tickformat():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "streamlit_app"
    offenders = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if 'tickformat="~s"' in p.read_text()
        and p.name != "charts.py"  # charts.py keeps it as an empty-figure fallback
    ]
    assert not offenders, f'tickformat="~s" still present in: {offenders}'
