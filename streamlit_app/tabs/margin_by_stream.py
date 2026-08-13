"""Margin by Revenue Stream tab — parses WIP Margin by Stream sheet."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.components.charts import (
    comparison_bar_chart,
    render_plotly_chart,
    stacked_area_chart,
    trend_line_chart,
)
from streamlit_app.components.filters import (
    get_filtered_months,
    render_active_filter_bar,
    render_empty_state,
    validate_data_not_empty,
)
from streamlit_app.components.kpi_cards import render_single_kpi
from streamlit_app.components.ui import render_page_header, render_section_header, render_section_safe
from streamlit_app.constants import fmt_idr
from streamlit_app.data.parsers import parse_wip_margin


def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the Margin by Revenue Stream tab."""
    render_page_header(
        "Margin by stream",
        "See which revenue streams are scaling profitably and where cost intensity needs attention.",
        eyebrow="Profitability analysis",
    )
    raw = sheets.get("WIP Margin by Stream")
    if raw is None:
        st.warning(":material/warning: 'WIP Margin by Stream' sheet not found in this workbook.")
        return

    sections = parse_wip_margin(raw)
    if not sections:
        st.warning("Could not parse any data from the 'WIP Margin by Stream' sheet.")
        return

    revenue_df = sections.get("revenue", pd.DataFrame())
    cogs_df = sections.get("cogs", pd.DataFrame())
    margin_df = sections.get("margin", pd.DataFrame())

    all_months: list[str] = []
    if not revenue_df.empty:
        all_months = revenue_df.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()

    filtered_months = get_filtered_months(all_months) if all_months else all_months
    if not filtered_months:
        render_empty_state(
            title="No months in the selected date range.",
            suggestion="Adjust the month range slider in the sidebar to include at least one period.",
            icon="📅",
            show_reset=True,
            key_suffix="margin",
        )
        return

    render_active_filter_bar(filtered_months)
    cat_orders = {"Month": filtered_months}

    # ---- Apply Global Stream Filter ------------------------------------
    stream_f = st.session_state.get("stream_filter") or st.session_state.get("sidebar_stream_filter", [])
    if stream_f and not revenue_df.empty:
        revenue_df = pd.DataFrame(revenue_df[revenue_df["Stream"].isin(stream_f)])
        if not cogs_df.empty:
            cogs_df = pd.DataFrame(cogs_df[cogs_df["Stream"].isin(stream_f)])
        if not margin_df.empty:
            margin_df = pd.DataFrame(margin_df[margin_df["Stream"].isin(stream_f)])

    # ---- KPI cards — latest month per stream --------------------------
    _render_stream_kpis(revenue_df, filtered_months)

    # ──── Stacked area / bar: revenue by stream ────────────────────────────
    col_area, col_bar = st.columns(2, gap="medium")
    with col_area:
        render_section_safe(_render_revenue_area, revenue_df, filtered_months, cat_orders,
                            section_name="Revenue Composition")
    with col_bar:
        render_section_safe(_render_revenue_bar, revenue_df, filtered_months, cat_orders,
                            section_name="Revenue Comparison")

    # ──── COGS & Margin (if available) ───────────────────────────────────
    if not cogs_df.empty or not margin_df.empty:
        col_cogs, col_margin = st.columns(2, gap="medium")
        with col_cogs:
            if not cogs_df.empty:
                render_section_safe(_render_cogs_charts, cogs_df, filtered_months, cat_orders,
                                    section_name="COGS by Stream")
            else:
                st.caption("No COGS data found in sheet.")
        with col_margin:
            if not margin_df.empty:
                render_section_safe(_render_margin_charts, margin_df, filtered_months, cat_orders,
                                    section_name="Margin Trend")
            else:
                st.info(
                    "No margin % rows found below the revenue section of this sheet. "
                    "If the sheet has COGS/margin data beyond the rows currently parsed, "
                    "check the raw sheet structure.", icon=":material/info:"
                )


def _render_stream_kpis(revenue_df: pd.DataFrame, filtered_months: list[str]) -> None:
    """Render one KPI card per revenue stream showing the latest month's value."""
    if revenue_df.empty or not filtered_months:
        return
    latest_month = filtered_months[-1]
    prior_month = filtered_months[-2] if len(filtered_months) >= 2 else None
    latest_data = pd.DataFrame(revenue_df[revenue_df["Month"] == latest_month])

    with st.container(horizontal=True):
        for stream in latest_data["Stream"].unique():
            row = pd.DataFrame(latest_data[latest_data["Stream"] == stream])
            val = float(row["Value"].iloc[0]) if not row.empty else None

            delta_str = None
            if prior_month and val is not None:
                prior_row = pd.DataFrame(
                    revenue_df[(revenue_df["Stream"] == stream) & (revenue_df["Month"] == prior_month)]
                )
                if not prior_row.empty:
                    pv = float(prior_row["Value"].iloc[0])
                    if pv != 0:
                        delta_str = f"{(val - pv) / abs(pv) * 100:+.1f}%"

            sparkline = (
                revenue_df[revenue_df["Stream"] == stream]["Value"].tail(12).tolist()
            )
            render_single_kpi(stream, val, delta_str=delta_str, sparkline=sparkline)


def _render_revenue_area(
    revenue_df: pd.DataFrame, filtered_months: list[str], cat_orders: dict
) -> None:
    """Render stacked area for revenue by stream."""
    render_section_header("Revenue composition", "stacked_area_chart")
    vis = pd.DataFrame(revenue_df[revenue_df["Month"].isin(filtered_months)])
    if not validate_data_not_empty(vis, context="revenue composition", key_suffix="rev_area"):
        return

    fig_area = stacked_area_chart(
        vis, "Month", "Value", "Stream",
        category_orders=cat_orders,
    )
    render_plotly_chart(fig_area)


def _render_revenue_bar(
    revenue_df: pd.DataFrame, filtered_months: list[str], cat_orders: dict
) -> None:
    """Render grouped bar for revenue by stream."""
    render_section_header("Revenue comparison", "bar_chart")
    vis = pd.DataFrame(revenue_df[revenue_df["Month"].isin(filtered_months)])
    if not validate_data_not_empty(vis, context="revenue comparison", key_suffix="rev_bar"):
        return

    fig_bar = comparison_bar_chart(
        vis, "Month", "Value", color="Stream",
        barmode="group",
        color_map={},
    )
    render_plotly_chart(fig_bar)


def _render_cogs_charts(
    cogs_df: pd.DataFrame, filtered_months: list[str], cat_orders: dict
) -> None:
    """Render COGS by stream chart."""
    render_section_header("COGS by stream", "money_off")
    vis = pd.DataFrame(cogs_df[cogs_df["Month"].isin(filtered_months)])
    if not validate_data_not_empty(vis, context="COGS", key_suffix="cogs_bar"):
        return
    fig = comparison_bar_chart(
        vis, "Month", "Value", color="Stream",
        barmode="group",
    )
    render_plotly_chart(fig)


def _render_margin_charts(
    margin_df: pd.DataFrame, filtered_months: list[str], cat_orders: dict
) -> None:
    """Render margin % trend per stream."""
    render_section_header("Margin trend", "show_chart")
    vis = pd.DataFrame(margin_df[margin_df["Month"].isin(filtered_months)])
    if not validate_data_not_empty(vis, context="margin %", key_suffix="margin_trend"):
        return
    fig = trend_line_chart(
        vis, "Month", "Value", "Stream",
        category_orders=cat_orders,
        y_format="pct",
    )
    render_plotly_chart(fig)
