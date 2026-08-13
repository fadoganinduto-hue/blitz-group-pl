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

# ---------------------------------------------------------------------------
# Module-level shared helpers
# ---------------------------------------------------------------------------

_IDR_HOVER = "<b>%{fullData.name}</b><br>Period: %{x}<br>Value: Rp%{y:,.0f}<extra></extra>"
_IDR_HOVER_X = "<b>%{x}</b><br>%{fullData.name}: Rp%{y:,.0f}<extra></extra>"
_PCT_HOVER = "<b>%{fullData.name}</b><br>Period: %{x}<br>%{y:.2%}<extra></extra>"
_PLOTLY_CONFIG = {"displayModeBar": False, "scrollZoom": False, "responsive": True}


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


def _apply_financial_axis(fig: go.Figure) -> None:
    """Use compact IDR ticks while retaining exact values in hover details."""
    fig.update_yaxes(tickprefix="Rp", tickformat="~s")


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
        y=1.06,          # ↑ from 1.04; clears chart title on titled charts
        xanchor="right",
        x=1,
        font=dict(size=11, color=BLITZ_COLORS["text_secondary"]),
        bgcolor="rgba(0,0,0,0)",
    )

    base_axes = dict(
        gridcolor="rgba(226, 226, 226, 0.8)",
        gridwidth=1,
        zeroline=False,
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
        margin=dict(l=52, r=20, t=52 if title else 36, b=60),
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
    fig.update_yaxes(showgrid=True)
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
) -> go.Figure:
    """Return a multi-series line chart with markers and rich hover tooltips."""
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
    if y_format == "pct":
        hover = (
            "<b>%{fullData.name}</b><br>Period: %{x}<br>%{y:.1%}<extra></extra>"
            if color else
            "<b>%{x}</b><br>%{y:.1%}<extra></extra>"
        )
    else:
        hover = (
            "<b>%{fullData.name}</b><br>Period: %{x}<br>Value: Rp%{y:,.0f}<extra></extra>"
            if color else
            "<b>%{x}</b><br>Value: Rp%{y:,.0f}<extra></extra>"
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
    """Return a grouped or stacked bar chart with rich tooltips."""
    fig = px.bar(
        df,
        x=x,
        y=y,
        color=color,
        barmode=barmode,
        color_discrete_map=_resolved_color_map(df, color, color_map),
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    hover = (
        "<b>%{fullData.name}</b><br>%{x}<br>Value: %{y:.1%}<extra></extra>"
        if y_format == "pct" and color else
        "<b>%{x}</b><br>Value: %{y:.1%}<extra></extra>"
        if y_format == "pct" else
        "<b>%{fullData.name}</b><br>%{x}<br>Value: Rp%{y:,.0f}<extra></extra>"
        if color else
        "<b>%{x}</b><br>Value: Rp%{y:,.0f}<extra></extra>"
    )
    fig.update_traces(hovertemplate=hover, marker_line_width=0, opacity=0.92)
    _apply_base_layout(fig, title)
    if y_format == "pct":
        fig.update_yaxes(tickformat=".0%")
    else:
        _apply_financial_axis(fig)
    fig.update_layout(showlegend=bool(color))

    # Adaptive month x-axis (no category_orders on this builder; count from data)
    n_months = df[x].nunique()
    _apply_xaxis_months(fig, n_months)
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
        hovertemplate="<b>%{fullData.name}</b><br>Period: %{x}<br>Revenue: Rp%{y:,.0f}<extra></extra>",
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
        hovertemplate="<b>%{fullData.name}</b>: Rp%{y:,.0f}<extra></extra>",
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
            text=[fmt_idr(v) for v in values],
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
        hovertemplate="<b>%{label}</b><br>Value: Rp%{value:,.0f}<extra></extra>",
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
    fig.update_traces(hovertemplate=_IDR_HOVER, line=dict(width=2))
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
            hovertemplate="<b>%{x}</b><br>%{y:,.0f} IDR<extra></extra>",
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
            hovertemplate="<b>%{y}</b><br>Prior: %{x:,.0f} IDR<extra></extra>",
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
            hovertemplate="<b>%{y}</b><br>Current: %{x:,.0f} IDR<extra></extra>",
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
    fig.update_xaxes(tickprefix="Rp", tickformat="~s")
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
        xs = list(trace.x) if trace.x is not None else []
        ys = list(trace.y) if trace.y is not None else []
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
                    hovertemplate=f"<b>{cat_val} {rolling_avg_label}</b><br>%{{x}}<br>Rp%{{y:,.0f}}<extra></extra>",
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
                hovertemplate=f"<b>{rolling_avg_label}</b><br>%{{x}}<br>Rp%{{y:,.0f}}<extra></extra>",
                showlegend=True,
            ))

    # ── Reference line (horizontal) ──────────────────────────────────────
    if reference_value is not None:
        add_reference_line(fig, reference_value, reference_label)

    # ── Chart annotations (peak/trough/MoM markers) ─────────────────────
    if annotations:
        from streamlit_app.constants import fmt_idr  # noqa: PLC0415

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
                text=f"<b>{symbol} {ann.label}</b><br>{fmt_idr(ann.value)}",
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
    from streamlit_app.constants import fmt_idr  # noqa: PLC0415

    line_color = color or BLITZ_COLORS["text_secondary"]
    fig.add_hline(
        y=value,
        line_dash=dash,
        line_color=line_color,
        line_width=1.2,
        opacity=0.6,
        annotation_text=f" {label}: {fmt_idr(value)}",
        annotation_position="right",
        annotation_font=dict(size=9, color=line_color, family="Inter, sans-serif"),
    )
