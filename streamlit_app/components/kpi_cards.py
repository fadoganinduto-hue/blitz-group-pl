"""Reusable KPI card row renderer using st.metric with sparklines."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.components.filters import convert_value, fmt_display, get_active_currency
from streamlit_app.constants import fmt_idr, fmt_idr_full


def render_kpi_row(
    df: pd.DataFrame,
    metrics: list[str],
    latest_month: str,
    prior_month: str | None,
    entity: str = "Consolidated",
    yoy_month: str | None = None,
) -> None:
    """Render a horizontal row of st.metric cards, one per metric, with MoM delta and sparkline.

    Parameters
    ----------
    yoy_month:
        When provided, a YoY secondary delta is computed and displayed below the
        MoM delta as small HTML text.  Pass None to suppress (e.g. when prior-year
        data is unavailable or the comparison mode is not "Same Month LY").
    """
    with st.container(horizontal=True):
        for metric in metrics:
            metric_df = df[df["Metric"] == metric].sort_values("MonthDate")
            latest_row = metric_df[metric_df["Month"] == latest_month]

            if latest_row.empty:
                st.metric(metric, "N/A", border=True)
                continue

            current_val = float(latest_row["Value"].sum())

            # Delta vs prior month (MoM)
            delta_str: str | None = None
            if prior_month:
                prior_row = metric_df[metric_df["Month"] == prior_month]
                if not prior_row.empty:
                    prior_val = float(prior_row["Value"].sum())
                    if prior_val != 0:
                        delta_pct = (current_val - prior_val) / abs(prior_val) * 100
                        delta_str = f"{delta_pct:+.1f}%"

            # YoY secondary delta (rendered as help-text suffix)
            yoy_help_suffix = ""
            if yoy_month:
                yoy_row = metric_df[metric_df["Month"] == yoy_month]
                if not yoy_row.empty:
                    yoy_val = float(yoy_row["Value"].sum())
                    if yoy_val != 0:
                        yoy_pct = (current_val - yoy_val) / abs(yoy_val) * 100
                        yoy_sign = "▲" if yoy_pct >= 0 else "▼"
                        yoy_help_suffix = f"  |  YoY: {yoy_sign} {abs(yoy_pct):.1f}%  (vs {yoy_month})"

            # Sparkline: aggregate by MonthDate to ensure 1 point per month, then take last 12.
            # Trim to the headline month first — the workbook carries unclosed
            # future columns, and including them drew every card falling to zero
            # to the right of a value labelled "as of <latest_month>".
            agg_df = metric_df.groupby("MonthDate", as_index=False)["Value"].sum().sort_values("MonthDate")
            _latest_dates = metric_df.loc[metric_df["Month"] == latest_month, "MonthDate"]
            if not _latest_dates.empty:
                agg_df = agg_df[agg_df["MonthDate"] <= _latest_dates.max()]
            sparkline_vals: list[float] = [float(v) for v in agg_df["Value"].tail(12).tolist()]

            current_display = convert_value(current_val)

            base_help = (
                f"{fmt_idr_full(current_val)} as of {latest_month}"
                if get_active_currency() == "IDR"
                else f"${current_display:,.0f} as of {latest_month}"
            )

            # Cost metrics (COGS, OpEx): an increase is unfavorable → inverse color semantics
            _COST_METRICS = {"Total COGS", "Total Operating Expenses"}
            delta_color = "inverse" if metric in _COST_METRICS else "normal"

            st.metric(
                label=metric,
                value=fmt_display(current_val),
                delta=delta_str,
                delta_color=delta_color,
                help=base_help + yoy_help_suffix,
                border=True,
                chart_data=sparkline_vals if len(sparkline_vals) > 1 else None,
                chart_type="line",
            )


def render_single_kpi(
    label: str,
    value: float | None,
    delta_str: str | None = None,
    help_text: str | None = None,
    sparkline: list[float] | None = None,
) -> None:
    """Render a single bordered st.metric card with optional sparkline."""
    st.metric(
        label=label,
        value=fmt_display(value) if value is not None else "N/A",
        delta=delta_str,
        help=help_text,
        border=True,
        chart_data=sparkline if sparkline and len(sparkline) > 1 else None,
        chart_type="line",
    )


# ---------------------------------------------------------------------------
# Phase 1: Reusable Power BI-Style Components
# ---------------------------------------------------------------------------

def render_variance_badge(value_str: str, semantic_status: str = "neutral") -> str:
    """Return HTML for a small colored variance/status badge.
    
    semantic_status must be one of: 'positive', 'negative', 'warning', 'neutral'.
    """
    from streamlit_app.constants import BLITZ_COLORS
    from html import escape

    bg_colors = {
        "positive": "#DAFBE1",
        "negative": "#FFEBE9",
        "warning": "#FFF8C5",
        "neutral": BLITZ_COLORS["background"]
    }
    text_colors = {
        "positive": "#1A7F37",
        "negative": "#CF222E",
        "warning": "#BF8700",
        "neutral": BLITZ_COLORS["text_secondary"]
    }
    
    bg = bg_colors.get(semantic_status, bg_colors["neutral"])
    color = text_colors.get(semantic_status, text_colors["neutral"])
    
    # Do not use leading whitespace or newlines, otherwise Streamlit parses it as a Markdown code block
    return f'<span style="background: {bg}; color: {color}; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 700;">{escape(value_str)}</span>'


def render_bi_kpi_card(
    title: str,
    current_value: str,
    comparison_value: str | None = None,
    variance_abs: str | None = None,
    variance_pct: str | None = None,
    direction: str | None = None,
    semantic_status: str = "neutral",
    subtitle: str | None = None,
    sparkline_fig: "plotly.graph_objects.Figure | None" = None,
    size: str = "large",
) -> None:
    """Render a comprehensive BI-style KPI card.
    
    Supports title, current value, absolute variance, percentage variance, 
    comparison baseline, semantic direction/status, and an optional sparkline.
    """
    from streamlit_app.constants import BLITZ_COLORS
    from html import escape
    from streamlit_app.components.charts import render_plotly_chart
    
    parts = []
    if direction == "up":
        parts.append("▲")
    elif direction == "down":
        parts.append("▼")
    elif direction == "flat":
        parts.append("▶")
        
    if variance_pct:
        parts.append(variance_pct)
    if variance_abs:
        parts.append(f"({variance_abs})")
        
    badge_html = ""
    if parts:
        badge_html = render_variance_badge(" ".join(parts), semantic_status)
        
    comp_html = ""
    if comparison_value:
        comp_html = f"<span style='font-size: 11px; color: {BLITZ_COLORS['text_secondary']}; margin-left: 6px;'>vs {escape(comparison_value)}</span>"

    title_size = "11px" if size == "large" else "10px"
    val_size = "24px" if size == "large" else "20px"
    title_html = f"<div style='font-size: {title_size}; font-weight: 700; color: {BLITZ_COLORS['text_secondary']}; letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 8px;'>{escape(title)}</div>"
    val_html = f"<div style='font-size: {val_size}; font-weight: 800; color: {BLITZ_COLORS['text_primary']}; line-height: 1.1; margin-bottom: 6px;'>{escape(current_value)}</div>"
    metrics_row_html = f"<div style='display: flex; align-items: center; margin-bottom: 8px; min-height: 20px;'>{badge_html} {comp_html}</div>"
    
    footer_html = ""
    if subtitle:
        footer_html = f"<div style='font-size: 11px; color: {BLITZ_COLORS['text_secondary']}; margin-top: 8px; padding-top: 8px; border-top: 1px solid {BLITZ_COLORS['border']}44;'>{escape(subtitle)}</div>"
        
    with st.container(border=True):
        st.markdown(title_html + val_html + metrics_row_html, unsafe_allow_html=True)
        
        if sparkline_fig:
            safe_key = f"sparkline_{title.replace(' ', '_').lower()}"
            render_plotly_chart(sparkline_fig, key=safe_key)
            
        if footer_html:
            st.markdown(footer_html, unsafe_allow_html=True)
