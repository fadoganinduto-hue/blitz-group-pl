"""Reusable Plotly chart builders — pure functions that return go.Figure objects."""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from streamlit_app.constants import (
    ENTITY_COLORS,
    PLOTLY_COLOR_SEQUENCE,
    fmt_idr,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_IDR_HOVER = "<b>%{y:,.0f}</b> IDR<extra></extra>"
_IDR_HOVER_X = "<b>%{x}</b><br>%{y:,.0f} IDR<extra></extra>"


def _apply_base_layout(fig: go.Figure, title: str = "") -> go.Figure:
    """Apply consistent responsive layout to any Plotly figure."""
    import streamlit as st
    
    is_dark = True
    try:
        if st.context.theme:
            is_dark = st.context.theme.type == "dark"
    except Exception:
        pass
        
    font_color = "#F1F5F9" if is_dark else "#0F172A"
    grid_color = "rgba(51, 65, 85, 0.6)" if is_dark else "rgba(226, 232, 240, 0.8)"
    hover_bg = "#1E293B" if is_dark else "#F8FAFC"
    hover_border = "#334155" if is_dark else "#E2E8F0"
    
    base_legend = dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
        font=dict(size=12, color=font_color),
        bgcolor="rgba(0,0,0,0)",
    )
    
    base_axes = dict(
        gridcolor=grid_color,
        gridwidth=1,
        zeroline=False,
        tickfont=dict(size=11, color="#94A3B8"),
        title_font=dict(size=12, color="#94A3B8"),
        showgrid=True,
    )

    fig.update_layout(
        font=dict(family="Inter, sans-serif", color=font_color, size=12),
        title=dict(
            text=f"<b>{title}</b>" if title else "",
            font=dict(size=15, color=font_color, family="Inter, sans-serif"),
            x=0,
            xanchor="left",
            pad=dict(l=4),
        ),
        legend=base_legend,
        margin=dict(l=12, r=12, t=48 if title else 24, b=12),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=hover_bg,
            bordercolor=hover_border,
            font=dict(size=12, color=font_color, family="Inter, sans-serif"),
        ),
        xaxis=base_axes,
        yaxis=base_axes,
    )
    return fig


# ---------------------------------------------------------------------------
# Trend line chart
# ---------------------------------------------------------------------------

def trend_line_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str,
    title: str = "",
    category_orders: dict | None = None,
    color_map: dict | None = None,
    y_format: str = "idr",
) -> go.Figure:
    """Return a multi-series line chart with markers and IDR hover formatting."""
    fig = px.line(
        df,
        x=x,
        y=y,
        color=color,
        markers=True,
        category_orders=category_orders or {},
        color_discrete_map=color_map or {},
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    hover = _IDR_HOVER if y_format == "idr" else "<b>%{y:.2f}%</b><extra></extra>"
    fig.update_traces(
        hovertemplate=hover,
        line=dict(width=2.5),
        marker=dict(size=6, line=dict(width=1.5, color="rgba(0,0,0,0)")),
    )
    return _apply_base_layout(fig, title)


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
) -> go.Figure:
    """Return a grouped or stacked bar chart with rounded bars."""
    fig = px.bar(
        df,
        x=x,
        y=y,
        color=color,
        barmode=barmode,
        color_discrete_map=color_map or {},
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    fig.update_traces(
        hovertemplate=_IDR_HOVER_X,
        marker_line_width=0,
        opacity=0.92,
    )
    return _apply_base_layout(fig, title)


# ---------------------------------------------------------------------------
# Stacked area chart
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
    """Return a stacked area chart for revenue composition over time."""
    fig = px.area(
        df,
        x=x,
        y=y,
        color=color,
        category_orders=category_orders or {},
        color_discrete_map=color_map or {},
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    fig.update_traces(
        hovertemplate=_IDR_HOVER,
        line=dict(width=1.5),
    )
    return _apply_base_layout(fig, title)


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
            connector=dict(line=dict(color="rgba(51,65,85,0.8)", width=1, dash="dot")),
            increasing=dict(marker=dict(color="#34D399", line=dict(width=0))),
            decreasing=dict(marker=dict(color="#F87171", line=dict(width=0))),
            totals=dict(marker=dict(color="#60A5FA", line=dict(width=0))),
        )
    )
    _apply_base_layout(fig, title)
    fig.update_layout(
        showlegend=False,
        hovermode="x",
    )
    fig.update_xaxes(showgrid=False)
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
        color_discrete_map=color_map or {},
        color_discrete_sequence=PLOTLY_COLOR_SEQUENCE,
    )
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{value:,.0f}",
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} IDR<extra></extra>",
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
        height=180,
    )
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(tickfont=dict(size=10))
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
    sorted_labels = [l for _, l in sorted_pairs]

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
            marker_color="#60A5FA",
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
            line=dict(color="#FBBF24", width=2),
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
    return fig

