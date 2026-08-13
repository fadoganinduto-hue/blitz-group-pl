"""Per-Entity comparison tab — KPI cards, normalised view, small-multiples, ranking."""

from __future__ import annotations

import sys
import traceback

import pandas as pd
import streamlit as st

from streamlit_app.components.charts import (
    comparison_bar_chart,
    mini_line_chart,
    render_plotly_chart,
    trend_line_chart,
)
from streamlit_app.components.filters import drill_to_entity, fmt_display, get_compare_month, get_filtered_months, multiselect_with_all, render_active_filter_bar, render_empty_state
from streamlit_app.components.kpi_cards import render_single_kpi
from streamlit_app.components.ui import render_page_header
from streamlit_app.constants import (
    BLITZ_COLORS,
    ENTITY_COLORS,
    ENTITY_DETAIL_SHEETS,
    ENTITY_SUMMARY_SHEETS,
    PREFERRED_TREND_METRICS,
    fmt_idr,
)
from streamlit_app.data.parsers import parse_pl_sheet, parse_ratios
from streamlit_app.data.analytics import compute_yoy_comparison

# Metrics shown in the ranking table
_RANKING_METRICS: list[str] = [
    "Total Gross Revenue",
    "EBITDA",
    "Gross Profit 2",
]


def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the Per-Entity comparison tab."""
    render_page_header(
        "Entity analysis",
        "Compare each operating entity’s revenue, profit contribution, momentum, and margin profile.",
        eyebrow="Performance drivers",
    )
    # ── Granularity toggle (Summary / Detail) ─────────────────────────
    col_gran, _ = st.columns([1, 3])
    with col_gran:
        granularity = st.segmented_control(
            "Granularity",
            options=["Summary", "Detail"],
            default="Summary",
            key="entity_granularity",
            help="Detail sheets contain finer line items (Direct Delivery, COD & Others, EV Bike Rental, etc.)",
        )
    sheet_map = ENTITY_DETAIL_SHEETS if granularity == "Detail" else ENTITY_SUMMARY_SHEETS

    # ── Load all available entities ───────────────────────────────────
    all_entity_frames: dict[str, pd.DataFrame] = {}
    for entity, sheet_name in sheet_map.items():
        raw = sheets.get(sheet_name)
        if raw is not None:
            df = parse_pl_sheet(raw, entity)
            if not df.empty:
                all_entity_frames[entity] = df

    if not all_entity_frames:
        st.warning(":material/warning: No per-entity sheets found in this workbook.")
        return

    # ── Entity selector ───────────────────────────────────────────────
    entity_opts = list(all_entity_frames.keys())
    selected_entities = multiselect_with_all("Entities", entity_opts, key="entity_selector")
    entity_frames = {e: all_entity_frames[e] for e in selected_entities if e in all_entity_frames}

    if not entity_frames:
        render_empty_state(
            title="No entities selected.",
            suggestion="Select at least one entity from the filter above.",
            icon="🏢",
            show_reset=False,
            key_suffix="entity_sel",
        )
        return

    entity_long = pd.concat(entity_frames.values(), ignore_index=True)
    all_months: list[str] = (
        entity_long.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
    )
    filtered_months = get_filtered_months(all_months)

    if not filtered_months:
        render_empty_state(
            title="No months in the selected date range.",
            suggestion="Adjust the month range slider in the sidebar to include at least one period.",
            icon="📅",
            show_reset=True,
            key_suffix="entity",
        )
        return

    render_active_filter_bar(filtered_months)

    latest_month = filtered_months[-1]
    prior_month = get_compare_month(filtered_months, latest_month, all_months)

    # ── KPI cards ────────────────────────────────────────────────────────
    _render_entity_kpis(entity_frames, latest_month, prior_month)

    vis = pd.DataFrame(entity_long[entity_long["Month"].isin(filtered_months)])
    cat_orders = {"Month": filtered_months}

    # ── Entity comparison panel ──────────────────────────────────────────
    _render_entity_comparison(entity_frames, sheets, filtered_months, latest_month, prior_month)

    # ── Cross-filter to Per-Client ───────────────────────────────────────
    if len(entity_frames) == 1:
        ent_name = list(entity_frames.keys())[0]
        if st.button(f"Drill to {ent_name} Client Analysis →", key=f"drill_client_{ent_name}"):
            drill_to_entity(ent_name)

    # ── View mode + metric selector ──────────────────────────────────────
    col_mode, col_metric = st.columns([1, 2], gap="medium")
    with col_mode:
        view_mode = st.segmented_control(
            "View",
            options=["IDR", "% of Group"],
            default="IDR",
            key="entity_view_mode",
        )
    with col_metric:
        per_entity_metrics = [set(df["Metric"].unique()) for df in entity_frames.values()]
        common_metrics = sorted(per_entity_metrics[0].intersection(*per_entity_metrics[1:]))
        if not common_metrics:
            common_metrics = sorted(vis["Metric"].unique())
        defaults = [m for m in PREFERRED_TREND_METRICS if m in common_metrics] or common_metrics[:1]
        metric = st.selectbox(
            "Metric",
            common_metrics,
            index=common_metrics.index(defaults[0]) if defaults else 0,
            key="entity_metric_select",
            label_visibility="collapsed",
        )

    # ── Trend + bar side by side ─────────────────────────────────────────
    col_trend, col_bar = st.columns(2, gap="medium")
    with col_trend:
        _render_entity_trend(vis, metric, view_mode, cat_orders, filtered_months, latest_month)
    with col_bar:
        _render_entity_bar(vis, metric, view_mode, latest_month)

    # ── Small-multiples grid ─────────────────────────────────────────────
    _render_small_multiples(vis, cat_orders)

    # ── Ranking table — always visible ───────────────────────────────────
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin:12px 0 8px;'>"
        f":material/leaderboard: Entity Ranking — {latest_month}</div>",
        unsafe_allow_html=True,
    )
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
    """Decision: Which entity is driving group performance over time?"""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f":material/show_chart: Which entity drives performance?</div>",
        unsafe_allow_html=True,
    )
    metric_df = vis[vis["Metric"] == metric].copy()

    if view_mode == "% of Group":
        group_total = metric_df.groupby("Month")["Value"].transform("sum")
        metric_df["Value"] = (metric_df["Value"] / group_total).fillna(0)

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
    render_plotly_chart(fig)


def _render_entity_bar(
    vis: pd.DataFrame,
    metric: str,
    view_mode: str | None,
    latest_month: str,
) -> None:
    """Decision: Which entity leads for this metric right now?"""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f":material/bar_chart: Entity Snapshot — {latest_month}</div>",
        unsafe_allow_html=True,
    )
    bar_df = pd.DataFrame(vis[(vis["Metric"] == metric) & (vis["Month"] == latest_month)])
    if view_mode == "% of Group":
        total = bar_df["Value"].sum()
        bar_df["Value"] = (bar_df["Value"] / total).fillna(0) if total else bar_df["Value"]
    if not bar_df.empty:
        fig = comparison_bar_chart(
            bar_df,
            "Entity",
            "Value",
            color_map=ENTITY_COLORS,
            y_format="pct" if view_mode == "% of Group" else "idr",
        )
        render_plotly_chart(fig)
    else:
        st.caption("No data for this metric in the latest month.")


def _render_small_multiples(vis: pd.DataFrame, cat_orders: dict) -> None:
    """Decision: Is each entity's KPIs improving across 6 key metrics?"""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f":material/grid_view: Multi-KPI Trend — 6 Key Metrics</div>",
        unsafe_allow_html=True,
    )
    candidates = [m for m in PREFERRED_TREND_METRICS if m in vis["Metric"].unique()][:4]
    if not candidates:
        st.caption("No matching metrics for small multiples.")
        return
    n_cols = 2
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
                render_plotly_chart(fig)


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
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _render_entity_comparison(
    entity_frames: dict[str, pd.DataFrame],
    sheets: dict[str, pd.DataFrame],
    filtered_months: list[str],
    latest_month: str,
    prior_month: str | None,
) -> None:
    """Decision: Which entity is responsible for group financial performance?"""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:10px;'>"
        f":material/compare: Entity Performance Summary — {latest_month}</div>",
        unsafe_allow_html=True,
    )

    _METRICS = [
        ("Total Gross Revenue", "Revenue"),
        ("Gross Profit 2", "Gross Profit"),
        ("EBITDA", "EBITDA"),
        ("NET PROFIT/LOSS (Before Tax)", "Net P/L"),
    ]

    def _val(df: pd.DataFrame, metric_key: str, month: str) -> float | None:
        rows = df[(df["Metric"] == metric_key) & (df["Month"] == month)]
        return float(rows["Value"].sum()) if not rows.empty else None

    # Determine all months for YoY lookup
    all_months_set: list[str] = []
    for df in entity_frames.values():
        if not df.empty:
            all_months_set = df.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
            break
    yoy_col_available = any(
        compute_yoy_comparison(df, "Total Gross Revenue", latest_month, all_months_set).available
        for df in entity_frames.values()
    ) if all_months_set else False

    # Total group revenue for contribution %
    group_rev = 0.0
    for df in entity_frames.values():
        r = _val(df, "Total Gross Revenue", latest_month)
        if r is not None:
            group_rev += r

    border = BLITZ_COLORS["border"]
    header_bg = BLITZ_COLORS["pale_blue"]
    col_headers = ["Entity"] + [disp for _, disp in _METRICS] + ["Margin", "Contrib %", "MoM Rev"]
    if yoy_col_available:
        col_headers.append("YoY Rev")
    col_widths_base = ["16%", "14%", "13%", "11%", "11%", "9%", "9%", "9%"]
    col_widths_yoy  = ["14%", "12%", "12%", "10%", "10%", "8%", "8%", "8%", "8%"]
    col_widths = col_widths_yoy if yoy_col_available else col_widths_base

    thead = "".join(
        f"<th style='padding:7px 8px;text-align:{'left' if i == 0 else 'right'};font-size:11px;"
        f"font-weight:600;color:{BLITZ_COLORS['text_secondary']};width:{col_widths[i]};'>{h}</th>"
        for i, h in enumerate(col_headers)
    )

    tbody = ""
    for i, (entity, df) in enumerate(entity_frames.items()):
        bg = "#FFFFFF" if i % 2 == 0 else BLITZ_COLORS["off_white"]
        dot = (
            f"<span style='display:inline-block;width:8px;height:8px;border-radius:50%;"
            f"background:{ENTITY_COLORS.get(entity, BLITZ_COLORS['primary'])};margin-right:6px;'></span>"
        )
        cells = f"<td style='padding:8px;font-size:12px;font-weight:700;color:{BLITZ_COLORS['text_primary']};'>{dot}{entity}</td>"

        rev = _val(df, "Total Gross Revenue", latest_month)
        prior_rev = _val(df, "Total Gross Revenue", prior_month) if prior_month else None

        for metric_key, _ in _METRICS:
            cur = _val(df, metric_key, latest_month)
            val_str = fmt_display(cur) if cur is not None else "—"
            color = BLITZ_COLORS["text_primary"] if cur is None or cur >= 0 else "#CF222E"
            cells += (
                f"<td style='padding:8px;text-align:right;font-size:12px;font-weight:600;"
                f"color:{color};'>{val_str}</td>"
            )

        # EBITDA margin from ratios
        try:
            from streamlit_app.constants import ENTITY_SUMMARY_SHEETS
            raw_entity = sheets.get(ENTITY_SUMMARY_SHEETS.get(entity, ""))
            ebitda_m_str = "—"
            if raw_entity is not None:
                ratios = parse_ratios(raw_entity, entity)
                if not ratios.empty:
                    m = ratios[ratios["Metric"].str.lower().str.contains("ebitda margin")]
                    cur_m = m[m["Month"] == latest_month]
                    if not cur_m.empty:
                        mv = float(cur_m["Value"].sum()) * 100
                        ebitda_m_str = f"{mv:.1f}%"
        except Exception as exc:  # noqa: BLE001
            print(
                f"[Dashboard] EBITDA margin for '{entity}' could not be computed:\n"
                + traceback.format_exc(),
                file=sys.stderr,
            )
            ebitda_m_str = "—"

        # Contribution %
        contrib_str = "—"
        if rev is not None and group_rev > 0:
            contrib = rev / group_rev * 100
            contrib_str = f"{contrib:.1f}%"

        # MoM Revenue Δ
        mom_str = "—"
        mom_color = BLITZ_COLORS["text_secondary"]
        if rev is not None and prior_rev is not None and prior_rev != 0:
            mom = (rev - prior_rev) / abs(prior_rev) * 100
            mom_str = f"{mom:+.1f}%"
            mom_color = BLITZ_COLORS["primary"] if mom >= 0 else "#CF222E"

        # YoY Revenue Δ (only rendered when column is available)
        yoy_str = "—"
        yoy_color = BLITZ_COLORS["text_secondary"]
        if yoy_col_available:
            yoy_result = compute_yoy_comparison(df, "Total Gross Revenue", latest_month, all_months_set)
            if yoy_result.available and yoy_result.pct_change is not None:
                yoy_str = f"{yoy_result.pct_change:+.1f}%"
                yoy_color = BLITZ_COLORS["primary"] if yoy_result.pct_change >= 0 else "#CF222E"
            elif yoy_result.prior_year_month:
                yoy_str = "N/A"

        cells += (
            f"<td style='padding:8px;text-align:right;font-size:12px;color:{BLITZ_COLORS['text_secondary']};'>{ebitda_m_str}</td>"
            f"<td style='padding:8px;text-align:right;font-size:12px;color:{BLITZ_COLORS['text_secondary']};'>{contrib_str}</td>"
            f"<td style='padding:8px;text-align:right;font-size:12px;font-weight:600;color:{mom_color};'>{mom_str}</td>"
        )
        if yoy_col_available:
            cells += (
                f"<td style='padding:8px;text-align:right;font-size:12px;font-weight:600;color:{yoy_color};'>{yoy_str}</td>"
            )
        tbody += f"<tr style='background:{bg};'>{cells}</tr>"

    st.markdown(
        f"<table style='width:100%;border-collapse:collapse;border:1px solid {border};"
        f"border-radius:8px;overflow:hidden;'>"
        f"<thead style='background:{header_bg};'><tr>{thead}</tr></thead>"
        f"<tbody>{tbody}</tbody></table>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
