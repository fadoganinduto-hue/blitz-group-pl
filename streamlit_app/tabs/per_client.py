"""Per-Client revenue tab — KPIs, treemap, client search, new/churned clients."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.components.charts import (
    comparison_bar_chart,
    pareto_chart,
    render_plotly_chart,
    treemap_chart,
    trend_line_chart,
)
from streamlit_app.components.filters import (
    fmt_display,
    get_filtered_months,
    render_active_filter_bar,
    render_empty_state,
    validate_data_not_empty,
)
from streamlit_app.components.kpi_cards import render_single_kpi
from streamlit_app.components.ui import render_page_header, render_section_header, render_section_safe
from streamlit_app.constants import BLITZ_COLORS, ENTITY_COLORS, fmt_idr, fmt_idr_full
from streamlit_app.data.parsers import parse_master
from streamlit_app.data.analytics import compute_revenue_drivers
from streamlit_app.data.anomaly_config import ANOMALY_THRESHOLDS


def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the Per-Client revenue analysis tab."""
    render_page_header(
        "Client revenue",
        "Monitor client concentration, portfolio movement, and the commercial accounts driving growth or decline.",
        eyebrow="Commercial intelligence",
    )
    raw = sheets.get("MASTER")
    if raw is None:
        st.warning(":material/warning: 'MASTER' sheet not found in this workbook.")
        return

    master, missing = parse_master(raw)
    if missing:
        st.warning(f"MASTER sheet is missing expected columns: {missing}")
        return

    all_months: list[str] = master.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
    filtered_months = get_filtered_months(all_months)
    if not filtered_months:
        render_empty_state(
            title="No months in the selected date range.",
            suggestion="Adjust the month range slider in the sidebar to include at least one period.",
            icon="📅",
            show_reset=True,
            key_suffix="client",
        )
        return

    render_active_filter_bar(filtered_months)

    # ── Back to Entity View ─────────────────────────────────────────────
    if st.session_state.get("entity_filter"):
        if st.button("← Back to Entity Comparison", key="back_to_entity", help="Clear entity filter"):
            st.session_state["entity_filter"] = st.session_state.get("_all_entity_options", [])
            st.session_state["sidebar_entity_filter"] = st.session_state["entity_filter"]
            for k in ["sidebar_entity_filter_widget", "entity_filter_widget"]:
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()

    # ── Apply global filters ─────────────────────────────────────────────
    filtered = _apply_filters(master, filtered_months)

    if not validate_data_not_empty(
        filtered,
        context="the selected combination of Entity, Stream, and Industry",
        key_suffix="client_data"
    ):
        return

    # ── KPI row ──────────────────────────────────────────────────────────
    _render_kpis(filtered)

    # ── Tiered concentration + Driver analysis (side by side) ────────────
    col_conc, col_driver = st.columns([1, 1], gap="medium")
    with col_conc:
        _render_tiered_concentration(filtered)
    with col_driver:
        latest_m = filtered_months[-1] if filtered_months else None
        prior_m = filtered_months[-2] if len(filtered_months) >= 2 else None
        _render_driver_analysis(master, filtered_months, latest_m, prior_m)

    # ── Pareto chart — leads ─────────────────────────────────────────────
    _render_pareto(filtered)

    # ── Top-15 clients + Treemap (side by side) ──────────────────────────
    col_bar, col_tree = st.columns([1, 1], gap="medium")
    with col_bar:
        _render_top_clients(filtered)
    with col_tree:
        _render_treemap(filtered)

    # ── Industry & Rev Stream (side by side) ─────────────────────────────
    col_ind, col_stream = st.columns(2, gap="medium")
    with col_ind:
        _render_industry_breakdown(filtered)
    with col_stream:
        _render_stream_breakdown(filtered)

    # ── Client search + churn ────────────────────────────────────────────
    col_search, col_churn = st.columns([1, 1], gap="medium")
    with col_search:
        _render_client_search(master, filtered_months)
    with col_churn:
        _render_churn_analysis(master, all_months, filtered_months)

    # ── Raw data table ───────────────────────────────────────────────────
    raw_client_data = st.expander(
        ":material/table_chart: Raw client data",
        expanded=False,
        on_change="rerun",
    )
    if raw_client_data.open:
        with raw_client_data:
            st.dataframe(filtered, hide_index=True, width="stretch")


def _apply_filters(master: pd.DataFrame, filtered_months: list[str]) -> pd.DataFrame:
    """Apply global entity / stream / industry filters."""
    entity_f = st.session_state.get("entity_filter") or st.session_state.get("sidebar_entity_filter", [])
    stream_f = st.session_state.get("stream_filter") or st.session_state.get("sidebar_stream_filter", [])
    industry_f = st.session_state.get("industry_filter") or st.session_state.get("sidebar_industry_filter", [])

    mask = master["Month"].isin(filtered_months)
    if entity_f:
        mask &= master["Entity"].isin(entity_f)
    if stream_f:
        mask &= master["Rev Stream"].isin(stream_f)
    if industry_f:
        mask &= master["Industry"].isin(industry_f)

    return pd.DataFrame(master[mask])


def _render_kpis(filtered: pd.DataFrame) -> None:
    """Render KPI cards: total revenue, active clients, top client share, top-5 concentration."""
    total_rev = filtered["Amount (IDR)"].sum()
    active_clients = filtered.loc[filtered["Amount (IDR)"] > 0, "Client (clean)"].nunique()

    client_rev = filtered.groupby("Client (clean)")["Amount (IDR)"].sum().sort_values(ascending=False)
    top_share = (client_rev.iloc[0] / total_rev * 100) if total_rev > 0 and not client_rev.empty else 0
    top5_share = (client_rev.head(5).sum() / total_rev * 100) if total_rev > 0 else 0
    top_client_name = client_rev.index[0] if not client_rev.empty else "—"

    with st.container(horizontal=True):
        render_single_kpi("Total Revenue (filtered)", total_rev, help_text=fmt_idr_full(total_rev))
        st.metric(
            "Active clients",
            value=str(active_clients),
            border=True,
            help="Clients with Amount (IDR) > 0 in selected period",
        )
        st.metric(
            f"Top client share ({top_client_name})",
            value=f"{top_share:.1f}%",
            border=True,
            help="Top client's revenue as % of total filtered revenue",
        )
        st.metric(
            "Top-5 concentration",
            value=f"{top5_share:.1f}%",
            border=True,
            help="Top 5 clients' combined revenue as % of total — higher = more concentrated risk",
        )


def _render_top_clients(filtered: pd.DataFrame) -> None:
    """Decision: Which clients are driving the most revenue?"""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f":material/bar_chart: Top Clients Driving Revenue</div>",
        unsafe_allow_html=True,
    )
    top15 = pd.DataFrame(
        filtered.groupby("Client (clean)", as_index=False)["Amount (IDR)"]
        .sum()
        .sort_values("Amount (IDR)", ascending=False)
        .head(15)
    )
    if not validate_data_not_empty(top15, context="top clients", key_suffix="top15"):
        return
    fig = comparison_bar_chart(top15, x="Client (clean)", y="Amount (IDR)")
    render_plotly_chart(fig)


def _render_treemap(filtered: pd.DataFrame) -> None:
    """Decision: Which entity/stream/client combination owns the most revenue?"""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f":material/account_tree: Revenue Composition — Entity → Stream → Client</div>",
        unsafe_allow_html=True,
    )
    treemap_df = pd.DataFrame(
        filtered.groupby(["Entity", "Rev Stream", "Client (clean)"], as_index=False)[
            "Amount (IDR)"
        ].sum()
    )
    treemap_df = pd.DataFrame(treemap_df[treemap_df["Amount (IDR)"] > 0])
    if not validate_data_not_empty(treemap_df, context="treemap", key_suffix="tree"):
        return
    fig = treemap_chart(
        treemap_df,
        path=["Entity", "Rev Stream", "Client (clean)"],
        values="Amount (IDR)",
        color_map=ENTITY_COLORS,
    )
    render_plotly_chart(fig)


def _render_client_search(master: pd.DataFrame, filtered_months: list[str]) -> None:
    """Render individual client monthly revenue trend with a search input."""
    render_section_header(
        "Client lookup",
        "search",
        "Inspect an individual account without changing the global portfolio view.",
    )
    search = st.text_input(
        "Search client",
        placeholder="Type part of a client name…",
        key="client_search",
        label_visibility="collapsed",
    )
    all_clients = sorted(master["Client (clean)"].dropna().unique())
    if search:
        matches = [c for c in all_clients if search.lower() in c.lower()]
        if not matches:
            st.caption(f"No clients matching '{search}'.")
            return
        selected_client = st.selectbox(
            "Select client",
            matches,
            key="client_search_select",
            label_visibility="collapsed",
        )
    else:
        selected_client = None

    if selected_client:
        client_df = (
            master[
                (master["Client (clean)"] == selected_client)
                & master["Month"].isin(filtered_months)
            ]
            .groupby(["Month", "MonthDate"], as_index=False)["Amount (IDR)"]
            .sum()
            .sort_values("MonthDate")
        )
        if client_df.empty:
            st.caption(f"No data for '{selected_client}' in the selected date range.")
            return
        fig = trend_line_chart(
            client_df, "Month", "Amount (IDR)", None,
            title=f"{selected_client}",
            category_orders={"Month": client_df["Month"].tolist()},
        )
        render_plotly_chart(fig)


def _render_churn_analysis(
    master: pd.DataFrame,
    all_months: list[str],
    filtered_months: list[str],
) -> None:
    """Show clients who are new or churned vs 3 months prior to the latest selected month."""
    st.markdown("##### :material/compare_arrows: Movement (vs 3 months prior)")
    if not filtered_months:
        return
    latest = filtered_months[-1]
    lookback_idx = all_months.index(latest) - 3 if all_months.index(latest) >= 3 else None
    if lookback_idx is None:
        st.caption("Need at least 3 months of history to compute churn.")
        return

    prior_month_3 = all_months[lookback_idx]
    latest_clients = set(
        master[(master["Month"] == latest) & (master["Amount (IDR)"] > 0)]["Client (clean)"]
    )
    prior_clients = set(
        master[(master["Month"] == prior_month_3) & (master["Amount (IDR)"] > 0)]["Client (clean)"]
    )

    new_clients = sorted(latest_clients - prior_clients)
    churned_clients = sorted(prior_clients - latest_clients)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**🟢 New clients ({len(new_clients)})**")
        if new_clients:
            st.dataframe(pd.DataFrame({"Client": new_clients}), hide_index=True, width="stretch")
        else:
            st.caption("No new clients detected.")

    with col2:
        st.markdown(f"**🔴 Churned ({len(churned_clients)})**")
        if churned_clients:
            st.dataframe(pd.DataFrame({"Client": churned_clients}), hide_index=True, width="stretch")
        else:
            st.caption("No churned clients detected.")


def _render_pareto(filtered: pd.DataFrame) -> None:
    """Render an 80/20 Pareto chart: client bars + cumulative revenue % line."""
    st.markdown("##### :material/bar_chart: Pareto — Client revenue (80/20)")
    client_rev = (
        filtered.groupby("Client (clean)")["Amount (IDR)"]
        .sum()
        .sort_values(ascending=False)
    )
    if client_rev.empty:
        st.caption("No data in the selected filters.")
        return
    n_clients = len(client_rev)
    slider_max = max(10, min(50, n_clients))
    slider_default = min(20, slider_max)
    top_n = st.slider("Top N clients in Pareto", 10, slider_max, slider_default, key="pareto_top_n") if n_clients > 10 else n_clients
    fig = pareto_chart(
        labels=client_rev.index.tolist(),
        values=client_rev.values.tolist(),
        title="",
        top_n=top_n,
    )
    render_plotly_chart(fig)


def _render_industry_breakdown(filtered: pd.DataFrame) -> None:
    """Decision: Which industry is the biggest revenue contributor?"""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f":material/category: Revenue by Industry</div>",
        unsafe_allow_html=True,
    )
    ind_rev = pd.DataFrame(
        filtered.groupby("Industry", as_index=False)["Amount (IDR)"].sum()
        .sort_values("Amount (IDR)", ascending=False)
    )
    if ind_rev.empty:
        st.caption("No industry data in the selected filters.")
        return
    fig = comparison_bar_chart(ind_rev, x="Industry", y="Amount (IDR)", title="")
    render_plotly_chart(fig)


def _render_stream_breakdown(filtered: pd.DataFrame) -> None:
    """Decision: Which revenue stream is strongest — and weakest?"""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f":material/donut_small: Revenue by Stream</div>",
        unsafe_allow_html=True,
    )
    stream_rev = pd.DataFrame(
        filtered.groupby("Rev Stream", as_index=False)["Amount (IDR)"].sum()
        .sort_values("Amount (IDR)", ascending=False)
    )
    if stream_rev.empty:
        st.caption("No stream data in the selected filters.")
        return
    fig = comparison_bar_chart(stream_rev, x="Rev Stream", y="Amount (IDR)", title="")
    render_plotly_chart(fig)


def _render_tiered_concentration(filtered: pd.DataFrame) -> None:
    """Decision: How dependent are we on a small number of clients?"""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:10px;'>"
        f":material/groups: Client Concentration by Tier</div>",
        unsafe_allow_html=True,
    )
    if filtered.empty:
        st.caption("No data in selected filters.")
        return

    total = filtered["Amount (IDR)"].sum()
    if total <= 0:
        st.caption("No revenue in selected period.")
        return

    client_rev = filtered.groupby("Client (clean)")["Amount (IDR)"].sum().sort_values(ascending=False)
    tiers = [("Top-1", 1), ("Top-5", 5), ("Top-10", 10), ("Top-20", 20)]

    border = BLITZ_COLORS["border"]
    items_html = ""
    for label, n in tiers:
        if n > len(client_rev):
            continue
        tier_rev = client_rev.head(n).sum()
        pct = tier_rev / total * 100
        risk_color = "#CF222E" if pct > 60 else ("#BF8700" if pct > 40 else BLITZ_COLORS["primary"])
        bar_w = int(min(100, pct))
        top_names = ", ".join(client_rev.head(min(n, 3)).index.tolist())
        suffix = "..." if n > 3 else ""
        items_html += (
            f"<div style='padding:8px 0;border-bottom:1px solid {border};'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
            f"<span style='font-size:12px;font-weight:700;color:{BLITZ_COLORS['text_primary']};'>{label}</span>"
            f"<span style='font-size:14px;font-weight:800;color:{risk_color};'>{pct:.1f}%</span>"
            f"</div>"
            f"<div style='height:5px;background:{border};border-radius:3px;margin:4px 0;'>"
            f"<div style='height:5px;width:{bar_w}%;background:{risk_color};border-radius:3px;'></div></div>"
            f"<div style='font-size:10px;color:{BLITZ_COLORS['text_secondary']};'>"
            f"Revenue: {fmt_idr(tier_rev)} &nbsp;·&nbsp; {top_names}{suffix}</div>"
            f"</div>"
        )

    rest_rev = total - client_rev.head(20).sum()
    if rest_rev > 0:
        rest_pct = rest_rev / total * 100
        n_rest = max(0, len(client_rev) - 20)
        items_html += (
            f"<div style='padding:8px 0;'>"
            f"<div style='display:flex;justify-content:space-between;'>"
            f"<span style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};'>Rest ({n_rest} clients)</span>"
            f"<span style='font-size:13px;font-weight:700;color:{BLITZ_COLORS['text_secondary']};'>{rest_pct:.1f}%</span>"
            f"</div></div>"
        )

    st.markdown(
        f"<div style='background:#FFFFFF;border:1px solid {border};border-radius:8px;"
        f"padding:10px 16px;'>{items_html}</div>",
        unsafe_allow_html=True,
    )


def _render_driver_analysis(
    master: pd.DataFrame,
    filtered_months: list[str],
    latest: str | None,
    prior: str | None,
) -> None:
    """Decision: Who and what caused the revenue change between periods?

    Shows:
    - Total revenue delta with direction
    - Anomaly flag if a top-5 client dropped >50% MoM
    - Client gainers / decliners (top 5 each)
    - Stream-level breakdown
    - Industry-level breakdown
    """
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:10px;'>"
        f":material/trending_up: Revenue Driver Analysis</div>",
        unsafe_allow_html=True,
    )
    if latest is None or prior is None:
        st.caption("Need at least 2 months selected to compute drivers.")
        return

    # Use unified compute_revenue_drivers (MASTER only, no cons_long needed)
    # We build a dummy cons_long from master sums so we can use the standard driver function
    # without a P&L sheet here (master only has Amount (IDR))
    cur_data = master[master["Month"] == latest]
    pri_data = master[master["Month"] == prior]

    cur_total = float(cur_data["Amount (IDR)"].sum())
    pri_total = float(pri_data["Amount (IDR)"].sum())
    total_delta = cur_total - pri_total

    border = BLITZ_COLORS["border"]
    delta_color = BLITZ_COLORS["primary"] if total_delta >= 0 else "#CF222E"
    arrow = "▲" if total_delta >= 0 else "▼"

    st.markdown(
        f"<div style='background:#FFFFFF;border:1px solid {border};border-radius:8px;"
        f"padding:10px 14px;margin-bottom:8px;'>"
        f"<div style='font-size:11px;color:{BLITZ_COLORS['text_secondary']};'>Total Revenue Change ({prior} → {latest})</div>"
        f"<div style='font-size:22px;font-weight:800;color:{delta_color};'>{arrow} {fmt_idr(total_delta)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Anomaly: top-5 client disappearance ──────────────────────────────────────
    threshold_pct = ANOMALY_THRESHOLDS["client_disappearance_pct"]
    if pri_total > 0:
        top5_prior = (
            pri_data.groupby("Client (clean)")["Amount (IDR)"]
            .sum()
            .sort_values(ascending=False)
            .head(5)
        )
        anomaly_clients = []
        for client, pri_rev in top5_prior.items():
            cur_rev = float(cur_data[cur_data["Client (clean)"] == client]["Amount (IDR)"].sum())
            if pri_rev > 0 and (pri_rev - cur_rev) / pri_rev * 100 >= threshold_pct:
                drop_pct = (pri_rev - cur_rev) / pri_rev * 100
                anomaly_clients.append((client, drop_pct))
        if anomaly_clients:
            anom_html = " | ".join(
                f"<b>{c}</b> −{p:.0f}%" for c, p in anomaly_clients
            )
            st.markdown(
                f"<div style='padding:6px 10px;background:#FFEBE9;border:1px solid #CF222E;"
                f"border-radius:6px;font-size:11px;color:#CF222E;margin-bottom:8px;'>"
                f"⚠️ Top-5 client significant decline: {anom_html}</div>",
                unsafe_allow_html=True,
            )

    # ── Client movers ────────────────────────────────────────────────────────
    cur_client = cur_data.groupby("Client (clean)")["Amount (IDR)"].sum()
    pri_client = pri_data.groupby("Client (clean)")["Amount (IDR)"].sum()
    all_clients = cur_client.index.union(pri_client.index)
    delta = pd.Series(
        {c: float(cur_client.get(c, 0.0)) - float(pri_client.get(c, 0.0)) for c in all_clients},
        name="Delta",
    ).sort_values(ascending=False)

    top_positive = delta[delta > 0].head(5)
    top_negative = delta[delta < 0].tail(5)

    col_pos, col_neg = st.columns(2, gap="small")
    with col_pos:
        pos_html = ""
        for client, dv in top_positive.items():
            pos_html += (
                f"<div style='display:flex;justify-content:space-between;padding:5px 0;"
                f"border-bottom:1px solid {border};font-size:11.5px;'>"
                f"<span style='color:{BLITZ_COLORS['text_primary']};font-weight:500;"
                f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:110px;'>{client}</span>"
                f"<span style='color:{BLITZ_COLORS['primary']};font-weight:700;'>+{fmt_idr(dv)}</span>"
                f"</div>"
            )
        if pos_html:
            st.markdown(
                f"<div style='font-size:11px;font-weight:600;color:{BLITZ_COLORS['primary']};"
                f"margin-bottom:6px;'>▲ Gainers</div>"
                f"<div style='background:#FFFFFF;border:1px solid {border};border-radius:8px;"
                f"padding:6px 12px;'>{pos_html}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("No positive movers.")

    with col_neg:
        neg_html = ""
        for client, dv in top_negative.items():
            neg_html += (
                f"<div style='display:flex;justify-content:space-between;padding:5px 0;"
                f"border-bottom:1px solid {border};font-size:11.5px;'>"
                f"<span style='color:{BLITZ_COLORS['text_primary']};font-weight:500;"
                f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:110px;'>{client}</span>"
                f"<span style='color:#CF222E;font-weight:700;'>{fmt_idr(dv)}</span>"
                f"</div>"
            )
        if neg_html:
            st.markdown(
                f"<div style='font-size:11px;font-weight:600;color:#CF222E;"
                f"margin-bottom:6px;'>▼ Decliners</div>"
                f"<div style='background:#FFFFFF;border:1px solid {border};border-radius:8px;"
                f"padding:6px 12px;'>{neg_html}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("No negative movers.")

    # ── Stream breakdown ─────────────────────────────────────────────────────
    cur_stream = cur_data.groupby("Rev Stream")["Amount (IDR)"].sum()
    pri_stream = pri_data.groupby("Rev Stream")["Amount (IDR)"].sum()
    stream_delta = {
        s: float(cur_stream.get(s, 0.0)) - float(pri_stream.get(s, 0.0))
        for s in cur_stream.index.union(pri_stream.index)
    }
    sorted_streams = sorted(stream_delta.items(), key=lambda x: abs(x[1]), reverse=True)

    if sorted_streams:
        st.markdown(
            f"<div style='font-size:11px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
            f"margin-top:10px;margin-bottom:4px;'>By Revenue Stream</div>",
            unsafe_allow_html=True,
        )
        s_html = ""
        for stream, dv in sorted_streams[:5]:
            dcolor = BLITZ_COLORS["primary"] if dv >= 0 else "#CF222E"
            s_html += (
                f"<div style='display:flex;justify-content:space-between;padding:4px 0;"
                f"border-bottom:1px solid {border};font-size:11px;'>"
                f"<span style='color:{BLITZ_COLORS['text_primary']};font-weight:500;"
                f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:130px;'>{stream}</span>"
                f"<span style='color:{dcolor};font-weight:700;'>{fmt_idr(dv)}</span>"
                f"</div>"
            )
        st.markdown(
            f"<div style='background:#FFFFFF;border:1px solid {border};border-radius:8px;"
            f"padding:6px 10px;margin-bottom:6px;'>{s_html}</div>",
            unsafe_allow_html=True,
        )

    # ── Industry breakdown ──────────────────────────────────────────────────
    cur_ind = cur_data.groupby("Industry")["Amount (IDR)"].sum()
    pri_ind = pri_data.groupby("Industry")["Amount (IDR)"].sum()
    ind_delta = {
        ind: float(cur_ind.get(ind, 0.0)) - float(pri_ind.get(ind, 0.0))
        for ind in cur_ind.index.union(pri_ind.index)
    }
    sorted_inds = sorted(ind_delta.items(), key=lambda x: abs(x[1]), reverse=True)

    if sorted_inds:
        st.markdown(
            f"<div style='font-size:11px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
            f"margin-bottom:4px;'>By Industry</div>",
            unsafe_allow_html=True,
        )
        i_html = ""
        for ind, dv in sorted_inds[:4]:
            dcolor = BLITZ_COLORS["primary"] if dv >= 0 else "#CF222E"
            i_html += (
                f"<div style='display:flex;justify-content:space-between;padding:4px 0;"
                f"border-bottom:1px solid {border};font-size:11px;'>"
                f"<span style='color:{BLITZ_COLORS['text_primary']};font-weight:500;"
                f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:130px;'>{ind}</span>"
                f"<span style='color:{dcolor};font-weight:700;'>{fmt_idr(dv)}</span>"
                f"</div>"
            )
        st.markdown(
            f"<div style='background:#FFFFFF;border:1px solid {border};border-radius:8px;"
            f"padding:6px 10px;'>{i_html}</div>",
            unsafe_allow_html=True,
        )
