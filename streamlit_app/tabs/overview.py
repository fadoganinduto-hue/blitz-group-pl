"""Executive overview tab — headline KPIs, mini entity trend, client concentration."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.components.charts import mini_line_chart, stacked_area_chart
from streamlit_app.components.filters import get_compare_month, get_filtered_months
from streamlit_app.constants import (
    ENTITY_COLORS,
    ENTITY_SUMMARY_SHEETS,
    fmt_idr,
    fmt_idr_full,
)
from streamlit_app.data.parsers import parse_master, parse_pl_sheet, parse_ratios


def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the executive overview landing page."""
    raw_cons = sheets.get("Consolidated Summary")
    if raw_cons is None:
        st.warning(":material/warning: 'Consolidated Summary' sheet not found.")
        return

    cons_long = parse_pl_sheet(raw_cons, "Consolidated")
    if cons_long.empty:
        st.warning("Could not parse the Consolidated Summary sheet.")
        return

    all_months: list[str] = (
        cons_long.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
    )
    filtered_months = get_filtered_months(all_months)
    if not filtered_months:
        st.info("No months in the selected range — adjust the sidebar slider.")
        return

    latest_month = filtered_months[-1]
    prior_month = get_compare_month(filtered_months, latest_month, all_months)

    # ── Headline KPI row ─────────────────────────────────────────────────
    _render_headline_kpis(cons_long, raw_cons, sheets, latest_month, prior_month)

    st.divider()

    # ── Mini trends + concentration metric ───────────────────────────────
    col_trend, col_conc = st.columns([2, 1], gap="medium")
    with col_trend:
        _render_entity_mini_trend(sheets, filtered_months)
    with col_conc:
        _render_concentration(sheets, filtered_months)


def _get_metric_val(df: pd.DataFrame, metric: str, month: str) -> float | None:
    """Return the summed value for a metric in a given month, or None if absent."""
    rows = df[(df["Metric"] == metric) & (df["Month"] == month)]
    return float(rows["Value"].sum(skipna=True)) if not rows.empty else None


def _delta_str(current: float | None, prior: float | None) -> str | None:
    """Return a formatted MoM delta percentage string, or None."""
    if current is None or prior is None or prior == 0:
        return None
    return f"{(current - prior) / abs(prior) * 100:+.1f}%"


def _render_headline_kpis(
    cons_long: pd.DataFrame,
    raw_cons: pd.DataFrame,
    sheets: dict[str, pd.DataFrame],
    latest_month: str,
    prior_month: str | None,
) -> None:
    """Render the top KPI row: Revenue, EBITDA, Net Profit, EBITDA Margin %."""
    st.markdown(f"#### Executive Summary — **{latest_month}**")

    rev = _get_metric_val(cons_long, "Total Gross Revenue", latest_month)
    ebitda = _get_metric_val(cons_long, "EBITDA", latest_month)
    net = _get_metric_val(cons_long, "NET PROFIT/LOSS (Before Tax)", latest_month)

    prior_rev = _get_metric_val(cons_long, "Total Gross Revenue", prior_month) if prior_month else None
    prior_ebitda = _get_metric_val(cons_long, "EBITDA", prior_month) if prior_month else None
    prior_net = _get_metric_val(cons_long, "NET PROFIT/LOSS (Before Tax)", prior_month) if prior_month else None

    # EBITDA Margin % from ratios
    ratios = parse_ratios(raw_cons, "Consolidated")
    margin_val: float | None = None
    prior_margin: float | None = None
    if not ratios.empty:
        margin_rows = ratios[ratios["Metric"].str.lower().str.contains("ebitda margin")]
        if not margin_rows.empty:
            m_row = margin_rows[margin_rows["Month"] == latest_month]
            margin_val = float(m_row["Value"].sum(skipna=True)) * 100 if not m_row.empty else None
            if prior_month:
                pm_row = margin_rows[margin_rows["Month"] == prior_month]
                prior_margin = float(pm_row["Value"].sum(skipna=True)) * 100 if not pm_row.empty else None

    # Client concentration (top-5 % of total)
    top5_pct: float | None = None
    raw_master = sheets.get("MASTER")
    if raw_master is not None:
        master, missing = parse_master(raw_master)
        if not missing and not master.empty:
            total_rev_master = master["Amount (IDR)"].sum()
            if total_rev_master > 0:
                top5_rev = (
                    master.groupby("Client (clean)")["Amount (IDR)"]
                    .sum()
                    .nlargest(5)
                    .sum()
                )
                top5_pct = top5_rev / total_rev_master * 100

    with st.container(horizontal=True):
        st.metric(
            "Total Gross Revenue",
            value=fmt_idr(rev) if rev is not None else "N/A",
            delta=_delta_str(rev, prior_rev),
            help=f"Full value: {fmt_idr_full(rev)}" if rev is not None else "",
            border=True,
        )
        st.metric(
            "EBITDA",
            value=fmt_idr(ebitda) if ebitda is not None else "N/A",
            delta=_delta_str(ebitda, prior_ebitda),
            border=True,
        )
        st.metric(
            "Net Profit / Loss",
            value=fmt_idr(net) if net is not None else "N/A",
            delta=_delta_str(net, prior_net),
            border=True,
        )
        if margin_val is not None:
            st.metric(
                "EBITDA Margin %",
                value=f"{margin_val:.1f}%",
                delta=_delta_str(margin_val, prior_margin),
                border=True,
            )
        if top5_pct is not None:
            st.metric(
                "Top-5 Client Concentration",
                value=f"{top5_pct:.1f}%",
                border=True,
                help="Top 5 clients' combined revenue as % of all-time total. Higher = more concentration risk.",
            )


def _render_entity_mini_trend(
    sheets: dict[str, pd.DataFrame], filtered_months: list[str]
) -> None:
    """Render a compact 3-entity revenue trend as a stacked area chart."""
    st.markdown("##### :material/show_chart: Revenue trend by entity")
    frames: list[pd.DataFrame] = []
    for entity, sheet_name in ENTITY_SUMMARY_SHEETS.items():
        raw = sheets.get(sheet_name)
        if raw is None:
            continue
        df = parse_pl_sheet(raw, entity)
        if df.empty:
            continue
        rev = pd.DataFrame(df[df["Metric"] == "Total Gross Revenue"])
        if not rev.empty:
            frames.append(rev)

    if not frames:
        st.caption("No per-entity data found.")
        return

    entity_long = pd.concat(frames, ignore_index=True)
    vis = pd.DataFrame(entity_long[entity_long["Month"].isin(filtered_months)])
    if vis.empty:
        st.caption("No data in the selected date range.")
        return

    fig = stacked_area_chart(
        vis, "Month", "Value", "Entity",
        category_orders={"Month": filtered_months},
        color_map=ENTITY_COLORS,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_concentration(
    sheets: dict[str, pd.DataFrame], filtered_months: list[str]
) -> None:
    """Render top-5 client concentration trend over time."""
    st.markdown("##### :material/group: Client concentration risk")
    raw_master = sheets.get("MASTER")
    if raw_master is None:
        st.caption("MASTER sheet not found.")
        return

    master, missing = parse_master(raw_master)
    if missing or master.empty:
        st.caption("Could not parse MASTER sheet.")
        return

    vis = pd.DataFrame(master[master["Month"].isin(filtered_months)])
    if vis.empty:
        st.caption("No data in the selected date range.")
        return

    # Build monthly top-5 concentration series
    records = []
    for month in filtered_months:
        m_data = vis[vis["Month"] == month]
        total = m_data["Amount (IDR)"].sum()
        if total <= 0:
            continue
        top5 = m_data.groupby("Client (clean)")["Amount (IDR)"].sum().nlargest(5).sum()
        records.append({"Month": month, "Top-5 %": round(top5 / total * 100, 1)})

    if not records:
        st.caption("Insufficient data.")
        return

    conc_df = pd.DataFrame(records)
    latest_pct = conc_df["Top-5 %"].iloc[-1]
    st.metric(
        "Top-5 concentration (latest)",
        value=f"{latest_pct:.1f}%",
        help="What % of revenue is driven by just 5 clients. Above 60% is typically high risk.",
        border=True,
    )
    st.caption("Monthly trend:")
    st.line_chart(conc_df.set_index("Month")["Top-5 %"], height=160)
