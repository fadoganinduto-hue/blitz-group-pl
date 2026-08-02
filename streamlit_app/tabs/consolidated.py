"""Consolidated Group P&L tab — KPI cards, trend charts, waterfall, full P&L table."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.components.charts import (
    comparison_bar_chart,
    stacked_area_chart,
    trend_line_chart,
    waterfall_chart,
)
from streamlit_app.components.filters import get_compare_month, get_filtered_months
from streamlit_app.components.kpi_cards import render_kpi_row
from streamlit_app.constants import (
    CONSOLIDATED_KPI_METRICS,
    OPEX_LINE_ITEMS,
    PREFERRED_TREND_METRICS,
    WATERFALL_STEPS,
    fmt_idr_full,
)
from streamlit_app.data.parsers import parse_pl_sheet, parse_ratios


def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the Consolidated Group P&L tab."""
    raw = sheets.get("Consolidated Summary")
    if raw is None:
        st.warning(":material/warning: 'Consolidated Summary' sheet not found.", icon=":material/warning:")
        return

    cons_long = parse_pl_sheet(raw, "Consolidated")
    if cons_long.empty:
        st.warning("Could not parse the Consolidated Summary sheet.")
        return

    all_months: list[str] = cons_long.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
    filtered_months = get_filtered_months(all_months)

    if not filtered_months:
        st.info("No months in the selected range — adjust the sidebar slider.")
        return

    latest_month = filtered_months[-1]
    prior_month = get_compare_month(filtered_months, latest_month, all_months)

    # ---- KPI Row -------------------------------------------------------
    kpi_metrics = [m for m in CONSOLIDATED_KPI_METRICS if m in cons_long["Metric"].unique()]
    render_kpi_row(cons_long, kpi_metrics, latest_month, prior_month)

    vis = pd.DataFrame(cons_long[cons_long["Month"].isin(filtered_months)])
    cat_orders = {"Month": filtered_months}

    # ---- Metric trend & Revenue area (side by side) --------------------
    col_left, col_right = st.columns(2, gap="medium")
    with col_left:
        _render_metric_trend(vis, cat_orders)
    with col_right:
        _render_revenue_area(vis, cat_orders)

    # ---- Margin trend & Waterfall (side by side) -----------------------
    col_mg, col_wf = st.columns(2, gap="medium")
    with col_mg:
        _render_margin_trend(raw, filtered_months, cat_orders)
    with col_wf:
        _render_waterfall(cons_long, latest_month)

    # ---- OpEx breakdown & Cost-as-% trend (side by side) ---------------
    col_opex, col_cost = st.columns(2, gap="medium")
    with col_opex:
        _render_opex_breakdown(vis, latest_month)
    with col_cost:
        _render_cost_ratio_trend(cons_long, filtered_months, cat_orders)

    # ---- Full P&L table -----------------------------------------------
    with st.expander(":material/table_chart: Full P&L table", expanded=False):
        _render_pl_table(vis, filtered_months)


def _render_metric_trend(vis: pd.DataFrame, cat_orders: dict) -> None:
    """Render the interactive metric trend line chart."""
    st.markdown("##### :material/show_chart: Metric trend")
    all_metrics = sorted(vis["Metric"].unique())
    defaults = [m for m in PREFERRED_TREND_METRICS if m in all_metrics] or all_metrics[:3]
    selected = st.multiselect(
        "Metrics",
        all_metrics,
        default=defaults,
        key="cons_metric_select",
        label_visibility="collapsed",
    )
    chart_df = pd.DataFrame(vis[vis["Metric"].isin(selected)])
    if not chart_df.empty:
        fig = trend_line_chart(chart_df, "Month", "Value", "Metric", category_orders=cat_orders)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Select at least one metric.")


def _render_revenue_area(vis: pd.DataFrame, cat_orders: dict) -> None:
    """Render stacked area chart of revenue line items."""
    st.markdown("##### :material/stacked_bar_chart: Revenue composition")
    is_positive = (
        vis.groupby("Metric")["Value"]
        .apply(lambda s: bool((s >= 0).all() and s.sum() > 0))
    )
    exclude_prefixes = ("total", "gross profit", "ebitda", "net profit", "net loss")
    revenue_line_items = [
        m for m, ok in is_positive.items()
        if ok and not any(str(m).lower().startswith(p) for p in exclude_prefixes)
    ]
    if revenue_line_items:
        area_df = pd.DataFrame(vis[vis["Metric"].isin(revenue_line_items)])
        fig = stacked_area_chart(
            area_df, "Month", "Value", "Metric",
            title="",
            category_orders=cat_orders,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No revenue line items detected.")


def _render_margin_trend(
    raw: pd.DataFrame,
    filtered_months: list[str],
    cat_orders: dict,
) -> None:
    """Render margin % trend from the ratios DataFrame."""
    st.markdown("##### :material/percent: Margin trend")
    ratios = parse_ratios(raw, "Consolidated")
    if ratios.empty:
        st.caption("No margin/ratio rows found.")
        return

    ratios_vis = pd.DataFrame(ratios[ratios["Month"].isin(filtered_months)])
    if ratios_vis.empty:
        st.caption("No ratio data in the selected month range.")
        return

    fig = trend_line_chart(
        ratios_vis, "Month", "Value", "Metric",
        category_orders=cat_orders,
        y_format="pct",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_waterfall(cons_long: pd.DataFrame, latest_month: str) -> None:
    """Render the P&L waterfall for the latest selected month."""
    st.markdown(f"##### :material/waterfall_chart: P&L bridge — {latest_month}")
    latest_data = pd.DataFrame(cons_long[cons_long["Month"] == latest_month])

    labels: list[str] = []
    raw_values: list[float] = []
    for metric_key, display_name in WATERFALL_STEPS:
        rows = pd.DataFrame(latest_data[latest_data["Metric"] == metric_key])
        if not rows.empty:
            labels.append(display_name)
            raw_values.append(float(rows["Value"].sum(skipna=True)))

    if len(labels) < 2:
        st.caption("Insufficient waterfall metrics found for this month.")
        return

    # Build waterfall values: first bar is absolute (Gross Revenue).
    # Each subsequent bar is the *delta* from the previous cumulative total.
    # Subtotal/total bars (Gross Profit, EBITDA, Net Profit) are "absolute" in value.
    # Cost bars (COGS, OpEx) are relative — their delta = their value minus the prior cumulative.
    subtotal_names = {"Gross Profit", "EBITDA", "Net Profit"}
    measures: list[str] = []
    waterfall_values: list[float] = []
    cumulative = 0.0
    for i, (lbl, val) in enumerate(zip(labels, raw_values)):
        if i == 0:
            waterfall_values.append(val)
            measures.append("absolute")
            cumulative = val
        elif lbl in subtotal_names:
            waterfall_values.append(val)
            measures.append("total")
            cumulative = val
        else:
            waterfall_values.append(val - cumulative)
            measures.append("relative")
            cumulative = val

    fig = waterfall_chart(labels, waterfall_values, measures=measures)
    st.plotly_chart(fig, use_container_width=True)


def _render_pl_table(vis: pd.DataFrame, filtered_months: list[str]) -> None:
    """Render the full P&L pivot table with conditional formatting."""
    pivot = vis.pivot_table(index="Metric", columns="Month", values="Value", aggfunc="sum")
    pivot = pivot[[m for m in filtered_months if m in pivot.columns]]

    def _style_negatives(v: object) -> str:
        try:
            return "color: #F87171; font-weight: 600;" if float(v) < 0 else ""  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return ""

    styled = pivot.style.map(_style_negatives).format(
        lambda v: fmt_idr_full(v) if isinstance(v, (int, float)) else v
    )
    st.dataframe(styled, use_container_width=True)


def _render_opex_breakdown(vis: pd.DataFrame, latest_month: str) -> None:
    """Render a bar chart of OpEx line items for the latest selected month."""
    st.markdown(f"##### :material/payments: OpEx breakdown — {latest_month}")
    month_data = pd.DataFrame(vis[vis["Month"] == latest_month])
    opex_data = pd.DataFrame(
        month_data[month_data["Metric"].isin(OPEX_LINE_ITEMS)]
        .groupby("Metric", as_index=False)["Value"]
        .sum()
        .sort_values("Value", ascending=False)
    )
    if opex_data.empty:
        st.caption("No OpEx line items found in the selected month.")
        return
    fig = comparison_bar_chart(opex_data, x="Metric", y="Value", title="")
    st.plotly_chart(fig, use_container_width=True)


def _render_cost_ratio_trend(
    cons_long: pd.DataFrame, filtered_months: list[str], cat_orders: dict
) -> None:
    """Render COGS and OpEx as % of gross revenue over time (efficiency trend)."""
    st.markdown("##### :material/percent: Cost ratios (% of Revenue)")
    revenue_df = cons_long[cons_long["Metric"] == "Total Gross Revenue"][["Month", "Value"]].rename(
        columns={"Value": "Revenue"}
    )
    cogs_df = cons_long[cons_long["Metric"] == "Total COGS"][["Month", "Value"]].rename(
        columns={"Value": "COGS"}
    )
    opex_df = cons_long[cons_long["Metric"] == "Total Operating Expenses"][["Month", "Value"]].rename(
        columns={"Value": "OpEx"}
    )

    merged = revenue_df.merge(cogs_df, on="Month", how="inner").merge(opex_df, on="Month", how="inner")
    merged = pd.DataFrame(merged[merged["Month"].isin(filtered_months)])

    if merged.empty or (merged["Revenue"] == 0).all():
        st.caption("Insufficient data to compute cost ratios.")
        return

    ratio_records = []
    for _, row in merged.iterrows():
        rev = row["Revenue"]
        if rev == 0:
            continue
        ratio_records.append({"Month": row["Month"], "Metric": "COGS %", "Value": row["COGS"] / rev * 100})
        ratio_records.append({"Month": row["Month"], "Metric": "OpEx %", "Value": row["OpEx"] / rev * 100})

    ratio_df = pd.DataFrame(ratio_records)
    if ratio_df.empty:
        st.caption("No ratio data available.")
        return

    fig = trend_line_chart(ratio_df, "Month", "Value", "Metric", category_orders=cat_orders, y_format="pct")
    st.plotly_chart(fig, use_container_width=True)

