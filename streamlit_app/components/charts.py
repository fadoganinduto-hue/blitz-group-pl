"""Reusable Plotly chart builders — pure functions that return go.Figure objects.

All chart functions call _apply_base_layout() (consistent margins/fonts/legend)
and _apply_xaxis_months() (adaptive tick angle/density for month-labeled axes).
Neither the public API nor any business/data logic is changed.
"""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import hashlib

from streamlit_app.constants import (
    BLITZ_COLORS,
    ENTITY_COLORS,
    METRIC_COLORS,
    PLOTLY_COLOR_SEQUENCE,
    fmt_idr,
)
from streamlit_app.components.filters import fmt_display

# ---------------------------------------------------------------------------
# Module-level shared helpers
# ---------------------------------------------------------------------------

_PCT_HOVER = "<b>%{fullData.name}</b><br>Period: %{x}<br>%{y:.2%}<extra></extra>"
_PLOTLY_CONFIG = {"displayModeBar": True, "scrollZoom": False, "responsive": True}


def render_plotly_chart(fig: go.Figure, *, key: str | None = None) -> None:
    """Render charts with the same focused interaction model everywhere."""
    import streamlit as st

    st.plotly_chart(
        fig,
        width="stretch",
        theme=None,
        config=_PLOTLY_CONFIG,
        key=key,
    )


def _resolved_color_map(
    df: pd.DataFrame,
    color: str | None,
    explicit_map: dict | None,
) -> dict:
    """Return a deterministic map for known measures and any dynamic categories."""
    mapping = dict(METRIC_COLORS)
    if explicit_map:
        mapping.update(explicit_map)
    if color is None or color not in df.columns:
        return mapping

    for value in df[color].dropna().unique():
        if value in mapping:
            continue
        digest = hashlib.sha256(str(value).encode("utf-8")).digest()[0]
        mapping[value] = PLOTLY_COLOR_SEQUENCE[digest % len(PLOTLY_COLOR_SEQUENCE)]
    return mapping


def _get_prefix() -> str:
    from streamlit_app.components.filters import get_active_currency
    return "$" if get_active_currency() == "USD" else "Rp"


def _fmt_converted(value: float) -> str:
    """Format a value that is ALREADY in the active currency (no FX conversion).

    Use this inside chart builders that receive pre-converted data from callers.
    Never call convert_value() here — the caller has already done it.
    """
    from streamlit_app.constants import IDR_SUFFIX_THRESHOLDS
    from streamlit_app.components.filters import get_active_currency
    currency = get_active_currency()
    prefix = "$" if currency == "USD" else "Rp"
    thresholds = IDR_SUFFIX_THRESHOLDS if currency == "IDR" else [
        (1_000_000_000, "B", 1_000_000_000),
        (1_000_000, "M", 1_000_000),
        (1_000, "K", 1_000),
    ]
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    for threshold, suffix, divisor in thresholds:
        if abs_val >= threshold:
            return f"{sign}{prefix}{abs_val / divisor:,.1f}{suffix}"
    return f"{sign}{prefix}{abs_val:,.0f}"

# ---------------------------------------------------------------------------
# Financial value axis
#
# Plotly's tickformat="~s" is D3's SI notation, which labels 10^9 as "G" (giga).
# Every other number in this dashboard — KPI cards, tables, waterfall labels,
# hover text — comes from fmt_idr and says "B". An axis reading "Rp2.5G" beside
# a card reading "Rp2.5B" is the same figure in two dialects, and a reader who
# does not know SI prefixes has no way to tell that "G" means billion at all.
#
# D3 has no billion format, so the ticks are placed and labelled here instead:
# nice round steps, one shared unit for the whole axis, text from the same
# thresholds fmt_idr uses. Hover still carries the exact rupiah.
# ---------------------------------------------------------------------------

_TICK_TARGET = 6  # aim for roughly this many gridlines


def _nice_step(rough: float) -> float:
    """Round a raw step up to the nearest 1 / 2 / 2.5 / 5 × 10^k."""
    import math

    if not rough or rough <= 0 or not math.isfinite(rough):
        return 0.0
    exponent = math.floor(math.log10(rough))
    magnitude = 10.0**exponent
    base = rough / magnitude
    for candidate in (1.0, 2.0, 2.5, 5.0, 10.0):
        if base <= candidate * 1.0000001:
            return candidate * magnitude
    return 10.0 * magnitude


def _numeric(values) -> list[float]:
    import math

    if values is None:
        return []
    out: list[float] = []
    # Plotly hands back numpy arrays; `values or []` would raise on those.
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def _value_axis_extent(fig: go.Figure, axis: str) -> tuple[float, float] | None:
    """Return (min, max) of everything plotted against the given value axis.

    Waterfall traces are handled specially: their ``y`` entries are deltas, so
    the axis extent is the running total, not the raw values.
    """
    anchor = "y" if axis == "y" else "x"
    seen: list[float] = []

    for trace in fig.data:
        if getattr(trace, "type", "") == "waterfall":
            ys = _numeric(getattr(trace, "y", None))
            measures = list(getattr(trace, "measure", None) or [])
            running = 0.0
            for i, y in enumerate(ys):
                measure = measures[i] if i < len(measures) else "relative"
                if measure == "absolute":
                    running = y
                elif measure != "total":
                    running += y
                seen.append(running)
            continue

        # Ignore anything riding a secondary axis (e.g. the Pareto cumulative
        # % line on y2) — it is not measured in currency.
        if getattr(trace, anchor + "axis", None) not in (None, anchor):
            continue
        seen.extend(_numeric(getattr(trace, anchor, None)))

    if not seen:
        return None
    return min(seen), max(seen)


def _tick_unit(largest: float) -> tuple[float, str]:
    """Pick one divisor/suffix for the whole axis, matching fmt_idr."""
    from streamlit_app.constants import IDR_SUFFIX_THRESHOLDS

    for threshold, suffix, divisor in IDR_SUFFIX_THRESHOLDS:
        if largest >= threshold:
            return divisor, suffix
    return 1.0, ""


def _coarser_step(step: float) -> float:
    """Return the next nice step up (…1 → 2 → 2.5 → 5 → 10…)."""
    import math

    if step <= 0:
        return 0.0
    exponent = math.floor(math.log10(step))
    magnitude = 10.0**exponent
    base = round(step / magnitude, 6)
    ladder = (1.0, 2.0, 2.5, 5.0)
    for candidate in ladder:
        if base < candidate - 1e-9:
            return candidate * magnitude
    return 10.0 * magnitude


def _decimals_for(step: float, divisor: float) -> int:
    """Fewest decimals (0–2) that render the step exactly in its unit."""
    scaled = step / divisor
    for places in (0, 1, 2):
        shifted = scaled * (10**places)
        if abs(shifted - round(shifted)) < 1e-9:
            return places
    return 2


def _financial_ticks(lo: float, hi: float, prefix: str) -> tuple[list[float], list[str]]:
    """Return (tickvals, ticktext) for a currency axis spanning lo..hi."""
    import math

    # Charts here are baselined at zero (bars literally, lines by convention),
    # so the tick lattice must include it.
    lo, hi = min(0.0, lo), max(0.0, hi)
    span = hi - lo
    if span <= 0:
        return [0.0], [f"{prefix}0"]

    step = _nice_step(span / _TICK_TARGET)
    if step <= 0:
        return [], []

    # A 250M step under a 1.5B ceiling would label the gridlines "Rp0.25B".
    # Widening the step to 500M costs two gridlines and buys "Rp0.5B / Rp1.0B".
    divisor, suffix = 1.0, ""
    decimals = 0
    for _ in range(3):
        largest = max(abs(math.floor(lo / step)), abs(math.ceil(hi / step))) * step
        divisor, suffix = _tick_unit(largest or step)
        decimals = _decimals_for(step, divisor)
        if decimals <= 1:
            break
        step = _coarser_step(step)

    first = math.floor(lo / step)
    last = math.ceil(hi / step)
    if last - first > 40:  # pathological range; let Plotly cope
        return [], []

    vals = [round(i * step, 6) for i in range(first, last + 1)]
    text: list[str] = []
    for v in vals:
        if v == 0:
            text.append(f"{prefix}0")
            continue
        # Fixed decimals across the axis — a ragged "Rp0.5B / Rp1B / Rp1.5B"
        # column is harder to scan than "Rp0.5B / Rp1.0B / Rp1.5B".
        body = f"{abs(v) / divisor:,.{decimals}f}"
        text.append(f"{'-' if v < 0 else ''}{prefix}{body}{suffix}")
    return vals, text


def _apply_financial_axis(fig: go.Figure, axis: str = "y") -> None:
    """Label the value axis in the dashboard's own units (B / M / K, not G).

    Falls back to Plotly's SI ticks only when the figure carries no numeric
    data to measure — an empty chart, where no label is rendered anyway.
    """
    prefix = _get_prefix()
    update = fig.update_yaxes if axis == "y" else fig.update_xaxes

    extent = _value_axis_extent(fig, axis)
    if extent is None:
        update(tickprefix=prefix, tickformat="~s")
        return

    vals, text = _financial_ticks(extent[0], extent[1], prefix)
    if not vals:
        update(tickprefix=prefix, tickformat="~s")
        return

    # tickprefix is carried in the text, so it must not be applied twice.
    update(tickprefix="", tickmode="array", tickvals=vals, ticktext=text)


def _guard_category_labels(fig: go.Figure, n_categories: int, axis: str = "x") -> None:
    """Stop long category names being cropped by a fixed plot height.

    Client and industry names run long, and the category band was being squeezed
    until labels rendered as "ce" / "als" / "ics". Let the axis claim the room
    it needs, and angle the labels once there are enough of them to collide.
    """
    if axis == "x":
        fig.update_xaxes(automargin=True, tickangle=-35 if n_categories > 6 else 0)
        fig.update_yaxes(automargin=True)
        fig.update_layout(margin=dict(b=90 if n_categories > 6 else 60))
    else:
        # Horizontal bars: names sit on y and need width, not rotation.
        fig.update_yaxes(automargin=True, tickangle=0)
        fig.update_xaxes(automargin=True)
        fig.update_layout(margin=dict(l=150, b=60))


def _apply_base_layout(fig: go.Figure, title: str = "") -> go.Figure:
    """Apply consistent responsive layout to any Plotly figure.

    Margin rationale vs. original (l=12, r=12, b=12):
      l=52  — room for "Rp123.4B" y-axis tick labels (~50 px at size 11)
      b=60  — tick labels (~16 px) + gap + axis title (~16 px) + breathing room
      r=20  — small right pad for legend/toolbar clearance
      t=52/36 — titled charts get extra top space for the title + floating legend
    """
    base_legend = dict(
        orientation="h",
        yanchor="bottom",
        y=1.03,          # Reduced spacing to keep chart compact but clear title
        xanchor="right",
        x=1,
        font=dict(size=11, color=BLITZ_COLORS["text_secondary"]),
        bgcolor="rgba(0,0,0,0)",
    )

    base_axes = dict(
        gridcolor="rgba(226, 226, 226, 0.8)",
        gridwidth=1,
        zeroline=False,
        automargin=True,
        tickfont=dict(size=11, color=BLITZ_COLORS["text_secondary"]),
        title_font=dict(size=12, color=BLITZ_COLORS["text_secondary"]),
        showgrid=False,
    )

    fig.update_layout(
        font=dict(family="Inter, sans-serif", color=BLITZ_COLORS["text_primary"], size=12),
        title=dict(
            text=f"<b>{title}</b>" if title else "",
            font=dict(size=15, color=BLITZ_COLORS["text_primary"], family="Inter, sans-serif"),
            x=0,
            xanchor="left",
            pad=dict(l=4),
        ),
        legend=base_legend,
        margin=dict(l=10, r=10, t=40 if title else 20, b=20),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=BLITZ_COLORS["white"],
            bordercolor=BLITZ_COLORS["border"],
            font=dict(size=12, color=BLITZ_COLORS["text_primary"], family="Inter, sans-serif"),
        ),
        xaxis=base_axes,
        yaxis=base_axes,
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, automargin=True)
    return fig


def _apply_xaxis_months(
    fig: go.Figure,
    n_months: int = 12,
    month_labels: list[str] | None = None,
) -> None:
    """Apply adaptive x-axis tick settings for month-based time series.

    Chooses rotation angle and tick density based on how many months are
    displayed so labels never overlap regardless of the container width.

    ≤ 6 months   → horizontal (0°),   every month shown
    7–12 months  → light tilt (−30°), every month shown
    13–18 months → moderate tilt (−45°), every 2nd month shown
    > 18 months  → moderate tilt (−45°), every 3rd month shown

    When thinning is needed and month_labels is provided, explicit tickvals /
    ticktext are set so Plotly shows exactly the right subset of labels.
    """
    if n_months <= 6:
        tick_angle = 0
        step = 1
    elif n_months <= 12:
        tick_angle = -30
        step = 1
    elif n_months <= 18:
        tick_angle = -45
        step = 2
    else:
        tick_angle = -45
        step = 3

    xaxis_updates: dict = dict(
        type="category",
        tickangle=tick_angle,
        automargin=True,
        tickfont=dict(size=10, color=BLITZ_COLORS["text_secondary"]),
    )

    # For crowded ranges use explicit tickvals so only every N-th label renders
    if step > 1 and month_labels:
        selected = month_labels[::step]
        xaxis_updates["tickmode"] = "array"
        xaxis_updates["tickvals"] = selected
        xaxis_updates["ticktext"] = selected

    fig.update_xaxes(**xaxis_updates)


# ---------------------------------------------------------------------------
# Trend line chart
# ---------------------------------------------------------------------------

def trend_line_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str | None,
    title: str = "",
    category_orders: dict | None = None,
    color_map: dict | None = None,
    y_format: str = "idr",
    hover_data: list[str] | None = None,
) -> go.Figure:
    """Return a multi-series line chart with markers and rich hover tooltips."""
    fig = px.line(
        df,
        x=x,
        y=y,
        color=color,
        markers=True,
        hover_data=hover_data,
        category_orders=category_orders or {},
        color_discrete_map=_resolved_color_map(df, color, color_map),
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    if y_format == "pct":
        hover = (
            "<b>%{fullData.name}</b><br>Period: %{x}<br>%{y:.1%}<extra></extra>"
            if color else
            "<b>%{x}</b><br>%{y:.1%}<extra></extra>"
        )
    else:
        # If custom hover data is provided, use custom template
        if hover_data and not color:
            custom_parts = [f"<b>%{{x}}</b><br>Total Gross Revenue: {_get_prefix()}%{{y:,.0f}}"]
            for i, col in enumerate(hover_data):
                custom_parts.append(f"{col}: %{{customdata[{i}]}}")
            custom_parts.append("<extra></extra>")
            hover = "<br>".join(custom_parts)
        else:
            hover = (
                f"<b>%{{fullData.name}}</b><br>Period: %{{x}}<br>Value: {_get_prefix()}%{{y:,.0f}}<extra></extra>"
                if color else
                f"<b>%{{x}}</b><br>Value: {_get_prefix()}%{{y:,.0f}}<extra></extra>"
            )
    fig.update_traces(
        hovertemplate=hover,
        line=dict(width=2.5),
        marker=dict(size=6, line=dict(width=1.5, color="rgba(0,0,0,0)")),
    )
    _apply_base_layout(fig, title)
    if y_format == "pct":
        fig.update_yaxes(tickformat=".0%")
    else:
        _apply_financial_axis(fig)
    fig.update_layout(showlegend=bool(color))

    # Adaptive month x-axis
    month_labels = (category_orders or {}).get(x)
    n_months = len(month_labels) if month_labels else df[x].nunique()
    _apply_xaxis_months(fig, n_months, month_labels)
    return fig


# ---------------------------------------------------------------------------
# Donut chart
# ---------------------------------------------------------------------------

def donut_chart(
    df: pd.DataFrame,
    names: str,
    values: str,
    title: str = "",
    color_map: dict | None = None,
) -> go.Figure:
    """Return a donut chart for revenue composition."""
    fig = px.pie(
        df,
        names=names,
        values=values,
        hole=0.65,
        color=names,
        color_discrete_map=_resolved_color_map(df, names, color_map),
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    
    hover = f"<b>%{{label}}</b><br>Revenue: {_get_prefix()}%{{value:,.0f}}<br>Share: %{{percent}}<extra></extra>"
    fig.update_traces(
        hovertemplate=hover,
        textinfo="percent",
        textposition="inside",
        insidetextorientation="horizontal",
        marker=dict(line=dict(color=BLITZ_COLORS["white"], width=1))
    )
    
    _apply_base_layout(fig, title)
    
    # Override legend for donut
    fig.update_layout(
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.1,
            xanchor="center",
            x=0.5,
        ),
        margin=dict(t=40 if title else 20, b=40, l=20, r=20)
    )
    return fig


# ---------------------------------------------------------------------------
# Comparison bar chart
# ---------------------------------------------------------------------------

def comparison_bar_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str | None = None,
    title: str = "",
    color_map: dict | None = None,
    barmode: str = "group",
    y_format: str = "idr",
) -> go.Figure:
    """Return a grouped or stacked bar chart with rich tooltips.

    Orientation follows the data: a numeric ``y`` puts values on the vertical
    axis, a numeric ``x`` (with categorical ``y``) gives horizontal bars. The
    currency axis and the label-crowding guard follow the same detection, so a
    horizontal chart does not end up with "Rp" stamped on its client names.
    """
    horizontal = (
        pd.api.types.is_numeric_dtype(df[x])
        and not pd.api.types.is_numeric_dtype(df[y])
    )
    value_axis = "x" if horizontal else "y"
    cat_axis = "y" if horizontal else "x"

    fig = px.bar(
        df,
        x=x,
        y=y,
        color=color,
        barmode=barmode,
        orientation="h" if horizontal else "v",
        color_discrete_map=_resolved_color_map(df, color, color_map),
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    cat_token = f"%{{{cat_axis}}}"
    val_token = f"%{{{value_axis}}}"
    if y_format == "pct":
        value_part = f"Value: {val_token[:-1]}:.1%}}"
    else:
        value_part = f"Value: {_get_prefix()}{val_token[:-1]}:,.0f}}"
    hover = (
        f"<b>%{{fullData.name}}</b><br>{cat_token}<br>{value_part}<extra></extra>"
        if color else
        f"<b>{cat_token}</b><br>{value_part}<extra></extra>"
    )
    fig.update_traces(hovertemplate=hover, marker_line_width=0, opacity=0.92)
    _apply_base_layout(fig, title)
    if y_format == "pct":
        (fig.update_xaxes if horizontal else fig.update_yaxes)(tickformat=".0%")
    else:
        _apply_financial_axis(fig, axis=value_axis)
    fig.update_layout(showlegend=bool(color))

    n_categories = df[y].nunique() if horizontal else df[x].nunique()
    if not horizontal:
        # Adaptive month x-axis (no category_orders on this builder)
        _apply_xaxis_months(fig, n_categories)
    # Client, industry and stream names are long; without this the label band is
    # squeezed until labels render as "ce" / "als" / "ics".
    _guard_category_labels(fig, n_categories, axis=cat_axis)
    return fig


# ---------------------------------------------------------------------------
# Stacked area chart  (revenue composition — margin_by_stream tab)
# ---------------------------------------------------------------------------

def stacked_area_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str,
    title: str = "",
    category_orders: dict | None = None,
    color_map: dict | None = None,
) -> go.Figure:
    """Return a stacked area chart for revenue composition over time.

    Use this when you want to show how multiple streams/entities contribute
    to a total (stacked), not for entity-vs-entity comparison.
    For entity comparison use entity_revenue_line_chart() instead.
    """
    fig = px.area(
        df,
        x=x,
        y=y,
        color=color,
        category_orders=category_orders or {},
        color_discrete_map=_resolved_color_map(df, color, color_map),
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    fig.update_traces(
        hovertemplate=f"<b>%{{fullData.name}}</b><br>Period: %{{x}}<br>Revenue: {_get_prefix()}%{{y:,.0f}}<extra></extra>",
        line=dict(width=1.5),
        connectgaps=False,   # honest gaps where data is missing
    )
    _apply_base_layout(fig, title)
    _apply_financial_axis(fig)

    # Adaptive month x-axis
    month_labels = (category_orders or {}).get(x)
    n_months = len(month_labels) if month_labels else df[x].nunique()
    _apply_xaxis_months(fig, n_months, month_labels)
    return fig


# ---------------------------------------------------------------------------
# Entity revenue line chart  (replaces stacked area in overview)
# ---------------------------------------------------------------------------

def entity_revenue_line_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str,
    title: str = "",
    category_orders: dict | None = None,
    color_map: dict | None = None,
) -> go.Figure:
    """Multi-series line chart for comparing entity revenue trends over time.

    Unlike stacked_area_chart this renders one clear line per entity so the
    reader can directly compare Blitz / Borzo / TheLorry on the same axis.

    Key properties:
    - connectgaps=False  → honest gap where a month has no data
    - hovermode="x unified"  → hover shows all entities at once per month
    - ENTITY_COLORS mapping used by default
    """
    fig = px.line(
        df,
        x=x,
        y=y,
        color=color,
        markers=True,
        category_orders=category_orders or {},
        color_discrete_map=_resolved_color_map(df, color, color_map or ENTITY_COLORS),
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    fig.update_traces(
        # With hovermode="x unified" the month is shown once at the top;
        # each trace only needs to show entity name + value.
        hovertemplate=f"<b>%{{fullData.name}}</b>: {_get_prefix()}%{{y:,.0f}}<extra></extra>",
        line=dict(width=2.5),
        marker=dict(size=7, line=dict(width=1.5, color="rgba(0,0,0,0)")),
        connectgaps=False,
    )
    _apply_base_layout(fig, title)
    _apply_financial_axis(fig)

    # Adaptive month x-axis
    month_labels = (category_orders or {}).get(x)
    n_months = len(month_labels) if month_labels else df[x].nunique()
    _apply_xaxis_months(fig, n_months, month_labels)

    fig.update_layout(
        showlegend=True,
        hovermode="x unified",
    )
    return fig


# ---------------------------------------------------------------------------
# Waterfall chart
# ---------------------------------------------------------------------------

def waterfall_chart(
    labels: list[str],
    values: list[float],
    title: str = "P&L Waterfall",
    measures: list[str] | None = None,
) -> go.Figure:
    """Return a Plotly waterfall chart showing P&L decomposition."""
    if measures is None:
        measures = []
        for i in range(len(labels)):
            if i == 0:
                measures.append("absolute")
            elif i == len(labels) - 1:
                measures.append("total")
            else:
                measures.append("relative")

    fig = go.Figure(
        go.Waterfall(
            name="P&L",
            orientation="v",
            measure=measures,
            x=labels,
            y=values,
            text=[_fmt_converted(v) for v in values],
            textposition="outside",
            textfont=dict(size=11),
            cliponaxis=False,
            connector=dict(line=dict(color="rgba(226,226,226,0.8)", width=1, dash="dot")),
            increasing=dict(marker=dict(color=BLITZ_COLORS["primary"], line=dict(width=0))),
            decreasing=dict(marker=dict(color=BLITZ_COLORS["deep_blue"], line=dict(width=0))),
            totals=dict(marker=dict(color=BLITZ_COLORS["primary_hover"], line=dict(width=0))),
        )
    )
    _apply_base_layout(fig, title)
    fig.update_layout(
        showlegend=False,
        hovermode="x",
    )
    # Waterfall has P&L line-item labels, not months.
    # A modest rotation helps when there are many items.
    fig.update_xaxes(
        showgrid=False,
        tickangle=-30,
        automargin=True,
        tickfont=dict(size=10, color=BLITZ_COLORS["text_secondary"]),
    )
    _apply_financial_axis(fig)
    return fig


# ---------------------------------------------------------------------------
# Treemap chart
# ---------------------------------------------------------------------------

def treemap_chart(
    df: pd.DataFrame,
    path: list[str],
    values: str,
    title: str = "",
    color_map: dict | None = None,
) -> go.Figure:
    """Return a hierarchical treemap for revenue composition."""
    fig = px.treemap(
        df,
        path=[px.Constant("All")] + path,
        values=values,
        color=path[0] if path else values,
        color_discrete_map=_resolved_color_map(df, path[0] if path else None, color_map),
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    fig.update_traces(
        texttemplate="<b>%{label}</b>",
        hovertemplate=f"<b>%{{label}}</b><br>Value: {_get_prefix()}%{{value:,.0f}}<extra></extra>",
        textfont=dict(size=12, family="Inter, sans-serif"),
        marker=dict(pad=dict(t=18, l=4, r=4, b=4)),
    )
    _apply_base_layout(fig, title)
    fig.update_layout(
        margin=dict(l=0, r=0, t=40, b=0),
    )
    return fig


# ---------------------------------------------------------------------------
# Small-multiples mini line chart
# ---------------------------------------------------------------------------

def mini_line_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str,
    title: str = "",
    category_orders: dict | None = None,
) -> go.Figure:
    """Return a compact multi-entity line chart for small-multiples grids."""
    fig = px.line(
        df,
        x=x,
        y=y,
        color=color,
        markers=False,
        category_orders=category_orders or {},
        color_discrete_map=ENTITY_COLORS,
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    fig.update_traces(hovertemplate=f"<b>%{{fullData.name}}</b><br>Period: %{{x}}<br>%{{fullData.name}}: {_get_prefix()}%{{y:,.0f}}<extra></extra>", line=dict(width=2))
    _apply_base_layout(fig, title)
    fig.update_layout(
        showlegend=False,
        margin=dict(l=8, r=8, t=30, b=8),
        height=210,
    )
    # Mini charts hide their x-axis labels (they're identified by their containing card)
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(tickfont=dict(size=10))
    _apply_financial_axis(fig)
    return fig


# ---------------------------------------------------------------------------
# Pareto chart (bar + cumulative % line)
# ---------------------------------------------------------------------------

def pareto_chart(
    labels: list[str],
    values: list[float],
    title: str = "Pareto — Client Revenue",
    top_n: int = 30,
) -> go.Figure:
    """Return a combined bar + cumulative % line chart for 80/20 analysis."""
    sorted_pairs = sorted(zip(values, labels), reverse=True)[:top_n]
    sorted_vals = [v for v, _ in sorted_pairs]
    sorted_labels = [label for _, label in sorted_pairs]

    total = sum(sorted_vals)
    cumulative_pct = []
    running = 0.0
    for v in sorted_vals:
        running += v
        cumulative_pct.append(round(running / total * 100, 1) if total else 0)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=sorted_labels,
            y=sorted_vals,
            name="Revenue",
            marker_color=BLITZ_COLORS["primary"],
            marker_line_width=0,
            opacity=0.85,
            hovertemplate=f"<b>%{{x}}</b><br>{_get_prefix()}%{{y:,.0f}}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=sorted_labels,
            y=cumulative_pct,
            name="Cumulative %",
            yaxis="y2",
            line=dict(color=BLITZ_COLORS["deep_blue"], width=2),
            mode="lines+markers",
            marker=dict(size=4),
            hovertemplate="<b>%{x}</b><br>Cumulative: %{y:.1f}%<extra></extra>",
        )
    )
    _apply_base_layout(fig, title)
    fig.update_layout(
        yaxis2=dict(
            title="Cumulative %",
            overlaying="y",
            side="right",
            range=[0, 105],
            showgrid=False,
            ticksuffix="%",
        ),
        bargap=0.15,
        showlegend=True,
    )
    # Client names — always rotate; names can be long
    fig.update_xaxes(
        tickangle=-45,
        automargin=True,
        tickfont=dict(size=10, color=BLITZ_COLORS["text_secondary"]),
    )
    _apply_financial_axis(fig)
    return fig


# ---------------------------------------------------------------------------
# Variance bar chart  (horizontal — period delta analysis)
# ---------------------------------------------------------------------------

def variance_bar_chart(
    labels: list[str],
    actuals: list[float],
    priors: list[float],
    title: str = "",
) -> go.Figure:
    """Return a horizontal grouped bar showing actual vs prior with Δ overlay.

    Positive Δ markers use brand blue; negative use semantic red.
    """
    deltas = [a - p for a, p in zip(actuals, priors)]
    delta_colors = [
        BLITZ_COLORS["primary"] if d >= 0 else "#CF222E" for d in deltas
    ]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Prior Period",
            y=labels,
            x=priors,
            orientation="h",
            marker_color=BLITZ_COLORS["border"],
            marker_line_width=0,
            opacity=0.6,
            hovertemplate=f"<b>%{{y}}</b><br>Prior: {_get_prefix()}%{{x:,.0f}}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Current Period",
            y=labels,
            x=actuals,
            orientation="h",
            marker_color=BLITZ_COLORS["primary_hover"],
            marker_line_width=0,
            opacity=0.9,
            hovertemplate=f"<b>%{{y}}</b><br>Current: {_get_prefix()}%{{x:,.0f}}<extra></extra>",
        )
    )
    _apply_base_layout(fig, title)
    fig.update_layout(
        barmode="overlay",
        legend=dict(orientation="h", y=1.08),
        margin=dict(l=140, r=60, t=48, b=20),
        height=max(200, len(labels) * 50),
    )
    fig.update_yaxes(tickfont=dict(size=11))
    _apply_financial_axis(fig, axis="x")
    return fig


# ---------------------------------------------------------------------------
# Phase 1: Reusable Power BI-Style Components
# ---------------------------------------------------------------------------

def apply_blitz_chart_theme(fig: go.Figure, title: str = "") -> go.Figure:
    """Public API to apply centralized Plotly defaults for the BI dashboard.
    
    Configures background, font, axes, gridlines, margins, hover mode, 
    legend, and title styling. Future charts outside this module can use this.
    """
    return _apply_base_layout(fig, title)


def render_sparkline(
    values: list[float], 
    color: str | None = None,
    height: int = 50,
) -> go.Figure:
    """Return a minimal-noise mini-trend chart without axes.
    
    Designed specifically to be embedded within a KPI card.
    """
    if color is None:
        color = BLITZ_COLORS["text_secondary"]
        
    df = pd.DataFrame({"y": values, "x": range(len(values))})
    
    fig = px.line(
        df, x="x", y="y", 
        color_discrete_sequence=[color]
    )
    fig.update_traces(
        line=dict(width=2),
        hoverinfo="skip",
        hovertemplate=None
    )
    
    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=5, b=5),
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        hovermode=False,
    )
    fig.update_xaxes(visible=False, showgrid=False, zeroline=False)
    fig.update_yaxes(visible=False, showgrid=False, zeroline=False)
    
    return fig


# ---------------------------------------------------------------------------
# Multi-margin trend with ΔPP annotations
# ---------------------------------------------------------------------------

def margin_multi_line(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str,
    title: str = "",
    category_orders: dict | None = None,
    color_map: dict | None = None,
) -> go.Figure:
    """Margin trend line chart with per-period ΔPP text annotations.

    df must have columns [x, y, color]; y values are fractions (0–1 scale).
    Displayed as percentages with ΔPP labels on each step.
    """
    fig = px.line(
        df,
        x=x,
        y=y,
        color=color,
        markers=True,
        category_orders=category_orders or {},
        color_discrete_map=_resolved_color_map(df, color, color_map),
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    fig.update_traces(
        hovertemplate="<b>%{x}</b><br>%{y:.1%}<extra></extra>",
        line=dict(width=2.5),
        marker=dict(size=7),
    )
    # ΔPP annotations for each series
    for trace in fig.data:
        xs = list(getattr(trace, "x", []))
        ys = list(getattr(trace, "y", []))
        for i in range(1, len(ys)):
            try:
                delta_pp = (float(ys[i]) - float(ys[i - 1])) * 100
                if abs(delta_pp) >= 0.5:
                    ann_color = BLITZ_COLORS["primary"] if delta_pp >= 0 else "#CF222E"
                    fig.add_annotation(
                        x=xs[i],
                        y=float(ys[i]),
                        text=f"{delta_pp:+.1f}pp",
                        showarrow=False,
                        font=dict(size=9, color=ann_color),
                        yshift=12,
                    )
            except (TypeError, ValueError):
                pass

    _apply_base_layout(fig, title)
    fig.update_layout(yaxis=dict(tickformat=".1%"))

    # Adaptive month x-axis
    month_labels = (category_orders or {}).get(x)
    n_months = len(month_labels) if month_labels else df[x].nunique()
    _apply_xaxis_months(fig, n_months, month_labels)
    return fig


# ---------------------------------------------------------------------------
# Annotated trend chart (rolling average + peak/trough annotations)
# ---------------------------------------------------------------------------

def annotated_trend_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str | None,
    rolling_avg_df: "pd.DataFrame | None" = None,
    rolling_avg_label: str = "3M Rolling Avg",
    annotations: "list | None" = None,
    reference_value: float | None = None,
    reference_label: str = "Avg",
    title: str = "",
    category_orders: dict | None = None,
    color_map: dict | None = None,
) -> go.Figure:
    """Trend line chart with optional rolling average overlay, annotation markers, and reference line.

    Parameters
    ----------
    df:
        Main data (same signature as trend_line_chart).
    rolling_avg_df:
        DataFrame with [x, y] columns for the rolling average trace.
        Each unique value in the `color` column of `df` should have its own
        rolling avg series, OR pass a single-series DataFrame if color=None.
    rolling_avg_label:
        Legend label for the rolling average trace.
    annotations:
        List of ChartAnnotation objects from find_chart_annotations().
    reference_value:
        Y-value for a horizontal dashed reference line (historical average).
    reference_label:
        Label for the reference line.
    """
    # Build the base figure using the existing trend_line_chart
    fig = trend_line_chart(
        df, x, y, color,
        title=title,
        category_orders=category_orders,
        color_map=color_map,
    )

    # ── Rolling average overlay ──────────────────────────────────────────
    if rolling_avg_df is not None and not rolling_avg_df.empty:
        if color and color in rolling_avg_df.columns:
            # Multi-series: one dashed trace per entity/category
            for cat_val, grp in rolling_avg_df.groupby(color):
                grp_sorted = grp.sort_values(x)
                fig.add_trace(go.Scatter(
                    x=grp_sorted[x],
                    y=grp_sorted[y],
                    mode="lines",
                    name=f"{cat_val} {rolling_avg_label}",
                    line=dict(
                        dash="dash",
                        width=1.5,
                        color=_resolved_color_map(df, color, color_map).get(str(cat_val), BLITZ_COLORS["text_secondary"]),
                    ),
                    opacity=0.65,
                    hovertemplate=f"<b>{cat_val} {rolling_avg_label}</b><br>%{{x}}<br>{_get_prefix()}%{{y:,.0f}}<extra></extra>",
                    showlegend=True,
                ))
        else:
            # Single-series
            sorted_avg = rolling_avg_df.sort_values(x) if x in rolling_avg_df.columns else rolling_avg_df
            fig.add_trace(go.Scatter(
                x=sorted_avg[x],
                y=sorted_avg[y],
                mode="lines",
                name=rolling_avg_label,
                line=dict(dash="dash", width=1.5, color=BLITZ_COLORS["text_secondary"]),
                opacity=0.7,
                hovertemplate=f"<b>{rolling_avg_label}</b><br>%{{x}}<br>{_get_prefix()}%{{y:,.0f}}<extra></extra>",
                showlegend=True,
            ))

    # ── Reference line (horizontal) ──────────────────────────────────────
    if reference_value is not None:
        add_reference_line(fig, reference_value, reference_label)

    # ── Chart annotations (peak/trough/MoM markers) ─────────────────────
    if annotations:
        _ANNOTATION_COLORS = {
            "peak":     BLITZ_COLORS["primary"],
            "trough":   "#CF222E",
            "mom_up":   BLITZ_COLORS["primary_hover"],
            "mom_down": "#BF8700",
        }
        _ANNOTATION_SYMBOLS = {
            "peak": "▲", "trough": "▼", "mom_up": "▲", "mom_down": "▼",
        }

        for ann in annotations:
            color_ann = _ANNOTATION_COLORS.get(ann.kind, BLITZ_COLORS["text_secondary"])
            symbol = _ANNOTATION_SYMBOLS.get(ann.kind, "•")
            fig.add_annotation(
                x=ann.month,
                y=ann.value,
                text=f"<b>{symbol} {ann.label}</b><br>{_fmt_converted(ann.value)}",
                showarrow=True,
                arrowhead=2,
                arrowsize=0.8,
                arrowwidth=1.2,
                arrowcolor=color_ann,
                ax=0,
                ay=-36,
                font=dict(size=9, color=color_ann, family="Inter, sans-serif"),
                bgcolor="rgba(255,255,255,0.88)",
                bordercolor=color_ann,
                borderwidth=1,
                borderpad=3,
            )

    return fig


def add_reference_line(
    fig: go.Figure,
    value: float,
    label: str = "Avg",
    color: str | None = None,
    dash: str = "dot",
) -> None:
    """Add a dashed horizontal reference line to an existing figure (in-place).

    Parameters
    ----------
    fig:
        The Plotly figure to annotate.
    value:
        Y-position of the reference line.
    label:
        Short text label shown at the right end of the line.
    color:
        Line color (defaults to text_secondary).
    dash:
        Plotly dash style: "dot", "dash", "dashdot".
    """
    from streamlit_app.components.filters import fmt_display

    line_color = color or BLITZ_COLORS["text_secondary"]
    fig.add_hline(
        y=value,
        line_dash=dash,
        line_color=line_color,
        line_width=1.2,
        opacity=0.6,
        annotation_text=f" {label}: {_fmt_converted(value)}",
        annotation_position="right",
        annotation_font=dict(size=9, color=line_color, family="Inter, sans-serif"),
    )
