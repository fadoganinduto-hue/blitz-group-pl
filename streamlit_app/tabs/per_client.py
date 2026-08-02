"""Per-Client revenue tab — KPIs, treemap, client search, new/churned clients."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.components.charts import (
    comparison_bar_chart,
    pareto_chart,
    treemap_chart,
    trend_line_chart,
)
from streamlit_app.components.filters import get_filtered_months, multiselect_with_all
from streamlit_app.components.kpi_cards import render_single_kpi
from streamlit_app.constants import ENTITY_COLORS, fmt_idr_full
from streamlit_app.data.parsers import parse_master


def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the Per-Client revenue analysis tab."""
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

    # ---- Hierarchical filters -----------------------------------------
    filtered = _apply_filters(master, filtered_months)

    # ---- KPI row -------------------------------------------------------
    _render_kpis(filtered)

    # ---- Top-15 clients & Treemap (side by side) ----------------------
    col_bar, col_tree = st.columns([1, 1], gap="medium")
    with col_bar:
        _render_top_clients(filtered)
    with col_tree:
        _render_treemap(filtered)

    # ---- Pareto chart --------------------------------------------------
    _render_pareto(filtered)

    # ---- Industry & Rev Stream breakdown (side by side) ---------------
    col_ind, col_stream = st.columns(2, gap="medium")
    with col_ind:
        _render_industry_breakdown(filtered)
    with col_stream:
        _render_stream_breakdown(filtered)

    # ---- Client search + churn (side by side) ------------------------
    col_search, col_churn = st.columns([1, 1], gap="medium")
    with col_search:
        _render_client_search(master, filtered_months)
    with col_churn:
        _render_churn_analysis(master, all_months, filtered_months)

    # ---- Raw data table -----------------------------------------------
    with st.expander(":material/table_chart: Raw client data", expanded=False):
        st.dataframe(filtered, hide_index=True, use_container_width=True)


def _apply_filters(master: pd.DataFrame, filtered_months: list[str]) -> pd.DataFrame:
    """Apply hierarchically-dependent entity / stream / industry filters."""
    with st.container():
        st.markdown("##### :material/filter_list: Master Filters")
        col1, col2, col3 = st.columns(3, gap="medium")
        
        with col1:
            entity_opts = sorted(master["Entity"].dropna().unique())
            entity_f = multiselect_with_all("Entity", entity_opts, key="entity_filter")

        with col2:
            stream_source = pd.DataFrame(master[master["Entity"].isin(entity_f)]) if entity_f else master
            stream_opts = sorted(stream_source["Rev Stream"].dropna().unique())
            stream_f = multiselect_with_all("Rev Stream", stream_opts, key="stream_filter")

        with col3:
            industry_source = pd.DataFrame(stream_source[stream_source["Rev Stream"].isin(stream_f)]) if stream_f else stream_source
            industry_opts = sorted(industry_source["Industry"].dropna().unique())
            industry_f = multiselect_with_all("Industry", industry_opts, key="industry_filter")

    filtered = pd.DataFrame(master[
        master["Entity"].isin(entity_f)
        & master["Rev Stream"].isin(stream_f)
        & master["Industry"].isin(industry_f)
        & master["Month"].isin(filtered_months)
    ])
    st.write("") # small spacing
    return filtered


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
    st.write("")


def _render_top_clients(filtered: pd.DataFrame) -> None:
    """Render a horizontal bar chart of the top 15 clients by revenue."""
    st.markdown("##### :material/bar_chart: Top 15 clients")
    top15 = pd.DataFrame(
        filtered.groupby("Client (clean)", as_index=False)["Amount (IDR)"]
        .sum()
        .sort_values("Amount (IDR)", ascending=False)
        .head(15)
    )
    if top15.empty:
        st.caption("No client data in the selected filters.")
        return
    fig = comparison_bar_chart(top15, x="Client (clean)", y="Amount (IDR)")
    st.plotly_chart(fig, use_container_width=True)


def _render_treemap(filtered: pd.DataFrame) -> None:
    """Render a hierarchical treemap: Entity → Rev Stream → Client."""
    st.markdown("##### :material/account_tree: Entity → Stream → Client")
    treemap_df = pd.DataFrame(
        filtered.groupby(["Entity", "Rev Stream", "Client (clean)"], as_index=False)[
            "Amount (IDR)"
        ].sum()
    )
    treemap_df = pd.DataFrame(treemap_df[treemap_df["Amount (IDR)"] > 0])
    if treemap_df.empty:
        st.caption("No revenue data for treemap in selected filters.")
        return
    fig = treemap_chart(
        treemap_df,
        path=["Entity", "Rev Stream", "Client (clean)"],
        values="Amount (IDR)",
        color_map=ENTITY_COLORS,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_client_search(master: pd.DataFrame, filtered_months: list[str]) -> None:
    """Render individual client monthly revenue trend with a search input."""
    st.markdown("##### :material/search: Client lookup")
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
            client_df, "Month", "Amount (IDR)", "Month",
            title=f"{selected_client}",
            category_orders={"Month": client_df["Month"].tolist()},
        )
        st.plotly_chart(fig, use_container_width=True)


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
            st.dataframe(pd.DataFrame({"Client": new_clients}), hide_index=True, use_container_width=True)
        else:
            st.caption("No new clients detected.")

    with col2:
        st.markdown(f"**🔴 Churned ({len(churned_clients)})**")
        if churned_clients:
            st.dataframe(pd.DataFrame({"Client": churned_clients}), hide_index=True, use_container_width=True)
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
    st.plotly_chart(fig, use_container_width=True)


def _render_industry_breakdown(filtered: pd.DataFrame) -> None:
    """Render a bar chart of revenue by Industry."""
    st.markdown("##### :material/category: Revenue by Industry")
    ind_rev = pd.DataFrame(
        filtered.groupby("Industry", as_index=False)["Amount (IDR)"].sum()
        .sort_values("Amount (IDR)", ascending=False)
    )
    if ind_rev.empty:
        st.caption("No industry data in the selected filters.")
        return
    fig = comparison_bar_chart(ind_rev, x="Industry", y="Amount (IDR)", title="")
    st.plotly_chart(fig, use_container_width=True)


def _render_stream_breakdown(filtered: pd.DataFrame) -> None:
    """Render a bar chart of revenue by Revenue Stream."""
    st.markdown("##### :material/donut_small: Revenue by Stream")
    stream_rev = pd.DataFrame(
        filtered.groupby("Rev Stream", as_index=False)["Amount (IDR)"].sum()
        .sort_values("Amount (IDR)", ascending=False)
    )
    if stream_rev.empty:
        st.caption("No stream data in the selected filters.")
        return
    fig = comparison_bar_chart(stream_rev, x="Rev Stream", y="Amount (IDR)", title="")
    st.plotly_chart(fig, use_container_width=True)

