"""Per-Entity comparison tab — KPI cards, normalised view, small-multiples, ranking."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.components.charts import comparison_bar_chart, mini_line_chart, trend_line_chart
from streamlit_app.components.filters import get_filtered_months
from streamlit_app.components.kpi_cards import render_single_kpi
from streamlit_app.constants import ENTITY_COLORS, ENTITY_SUMMARY_SHEETS, PREFERRED_TREND_METRICS, fmt_idr
from streamlit_app.data.parsers import parse_pl_sheet

# Metrics shown in the ranking table
_RANKING_METRICS: list[str] = [
    "Total Gross Revenue",
    "EBITDA",
    "Gross Profit 2",
]


def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the Per-Entity comparison tab."""
    entity_frames: dict[str, pd.DataFrame] = {}
    for entity, sheet_name in ENTITY_SUMMARY_SHEETS.items():
        raw = sheets.get(sheet_name)
        if raw is not None:
            df = parse_pl_sheet(raw, entity)
            if not df.empty:
                entity_frames[entity] = df

    if not entity_frames:
        st.warning(":material/warning: No per-entity sheets found in this workbook.")
        return

    entity_long = pd.concat(entity_frames.values(), ignore_index=True)
    all_months: list[str] = (
        entity_long.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
    )
    filtered_months = get_filtered_months(all_months)

    if not filtered_months:
        st.info("No months in the selected range.")
        return

    latest_month = filtered_months[-1]
    prior_month = filtered_months[-2] if len(filtered_months) >= 2 else None

    # ---- Per-entity KPI cards -----------------------------------------
    _render_entity_kpis(entity_frames, latest_month, prior_month)

    vis = pd.DataFrame(entity_long[entity_long["Month"].isin(filtered_months)])
    cat_orders = {"Month": filtered_months}

    # ---- View mode + metric selector -----------------------------------
    col_mode, col_metric = st.columns([1, 2], gap="medium")
    with col_mode:
        view_mode = st.segmented_control(
            "View",
            options=["IDR", "% of Group"],
            default="IDR",
            key="entity_view_mode",
        )
    with col_metric:
        all_metrics = sorted(vis["Metric"].unique())
        defaults = [m for m in PREFERRED_TREND_METRICS if m in all_metrics] or all_metrics[:1]
        metric = st.selectbox(
            "Metric",
            all_metrics,
            index=all_metrics.index(defaults[0]) if defaults else 0,
            key="entity_metric_select",
            label_visibility="collapsed",
        )

    # ---- Trend + bar side by side -------------------------------------
    col_trend, col_bar = st.columns(2, gap="medium")
    with col_trend:
        _render_entity_trend(vis, metric, view_mode, cat_orders, filtered_months, latest_month)
    with col_bar:
        _render_entity_bar(vis, metric, view_mode, latest_month)

    # ---- Small-multiples grid -----------------------------------------
    _render_small_multiples(vis, cat_orders)

    # ---- Ranking table ------------------------------------------------
    with st.expander(":material/leaderboard: Entity ranking table", expanded=False):
        _render_ranking_table(entity_long, latest_month, prior_month)


def _render_entity_kpis(
    entity_frames: dict[str, pd.DataFrame],
    latest_month: str,
    prior_month: str | None,
) -> None:
    """Render one KPI card per entity showing Total Gross Revenue."""
    kpi_metric = "Total Gross Revenue"
    with st.container(horizontal=True):
        for entity, df in entity_frames.items():
            latest_row = df[(df["Metric"] == kpi_metric) & (df["Month"] == latest_month)]
            val = float(latest_row["Value"].sum(skipna=True)) if not latest_row.empty else None

            delta_str = None
            if prior_month and val is not None:
                prior_row = df[(df["Metric"] == kpi_metric) & (df["Month"] == prior_month)]
                if not prior_row.empty:
                    pv = float(prior_row["Value"].sum(skipna=True))
                    if pv != 0:
                        delta_str = f"{(val - pv) / abs(pv) * 100:+.1f}%"

            sparkline = (
                df[df["Metric"] == kpi_metric]["Value"].sort_index().tail(12).tolist()
            )
            render_single_kpi(entity, val, delta_str=delta_str, sparkline=sparkline)


def _render_entity_trend(
    vis: pd.DataFrame,
    metric: str,
    view_mode: str | None,
    cat_orders: dict,
    filtered_months: list[str],
    latest_month: str,
) -> None:
    """Render trend line for selected metric, absolute or % of group."""
    st.markdown("##### :material/show_chart: Trend by entity")
    metric_df = vis[vis["Metric"] == metric].copy()

    if view_mode == "% of Group":
        group_total = metric_df.groupby("Month")["Value"].transform("sum")
        metric_df["Value"] = (metric_df["Value"] / group_total * 100).fillna(0)

    chart_df = pd.DataFrame(metric_df[metric_df["Month"].isin(filtered_months)])
    if chart_df.empty:
        st.caption("No data for the selected metric and month range.")
        return

    fig = trend_line_chart(
        chart_df, "Month", "Value", "Entity",
        category_orders=cat_orders,
        color_map=ENTITY_COLORS,
        y_format="pct" if view_mode == "% of Group" else "idr",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_entity_bar(
    vis: pd.DataFrame,
    metric: str,
    view_mode: str | None,
    latest_month: str,
) -> None:
    """Render bar chart of the selected metric for the latest month."""
    st.markdown(f"##### :material/bar_chart: {latest_month} snapshot")
    bar_df = pd.DataFrame(vis[(vis["Metric"] == metric) & (vis["Month"] == latest_month)])
    if view_mode == "% of Group":
        total = bar_df["Value"].sum()
        bar_df["Value"] = (bar_df["Value"] / total * 100).fillna(0) if total else bar_df["Value"]
    if not bar_df.empty:
        fig = comparison_bar_chart(bar_df, "Entity", "Value", color_map=ENTITY_COLORS)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No data for this metric in the latest month.")


def _render_small_multiples(vis: pd.DataFrame, cat_orders: dict) -> None:
    """Render a 3-column small-multiples grid of top shared metrics."""
    st.markdown("##### :material/grid_view: Small multiples")
    candidates = [m for m in PREFERRED_TREND_METRICS if m in vis["Metric"].unique()][:6]
    if not candidates:
        st.caption("No matching metrics for small multiples.")
        return
    n_cols = 3
    rows = [candidates[i : i + n_cols] for i in range(0, len(candidates), n_cols)]
    for row in rows:
        cols = st.columns(n_cols, gap="small")
        for col, metric in zip(cols, row):
            with col:
                m_df = pd.DataFrame(vis[vis["Metric"] == metric])
                fig = mini_line_chart(
                    m_df, "Month", "Value", "Entity",
                    title=metric,
                    category_orders=cat_orders,
                )
                st.plotly_chart(fig, use_container_width=True)


def _render_ranking_table(
    entity_long: pd.DataFrame,
    latest_month: str,
    prior_month: str | None,
) -> None:
    """Render entity ranking table with rank-change arrows."""
    rows: list[dict] = []

    for metric in _RANKING_METRICS:
        metric_df = entity_long[entity_long["Metric"] == metric]
        latest_vals = (
            metric_df[metric_df["Month"] == latest_month]
            .set_index("Entity")["Value"]
            .sort_values(ascending=False)
        )
        prior_vals = (
            metric_df[metric_df["Month"] == prior_month]
            .set_index("Entity")["Value"]
            .sort_values(ascending=False)
            if prior_month
            else pd.Series(dtype=float)
        )

        for rank, (entity, val) in enumerate(latest_vals.items(), start=1):
            prior_rank = list(prior_vals.index).index(entity) + 1 if entity in prior_vals.index else None
            arrow = "—" if prior_rank is None else ("▲" if rank < prior_rank else ("▼" if rank > prior_rank else "="))
            rows.append({"Metric": metric, "Rank": rank, "Trend": arrow, "Entity": entity, "Value": fmt_idr(val)})

    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
