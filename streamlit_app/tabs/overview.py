"""Executive overview tab — Power BI-inspired executive intelligence dashboard.

Information hierarchy:
    Header
    Active filter/context bar
    Primary KPI cards (8 metrics)
    Margin/growth KPI row (5 metrics)
    Entity KPIs & Business KPIs
    Revenue trend | P&L waterfall
    Executive insights
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from streamlit_app.data.parsers import parse_master, parse_pl_sheet, parse_ratios
from streamlit_app.data.loader import parse_all_entity_sheets
from streamlit_app.data.analytics import (
    compute_rolling_avg,
    detect_anomalies,
    find_chart_annotations,
)
from streamlit_app.components.charts import (
    annotated_trend_chart,
    entity_revenue_line_chart,
    pareto_chart,
    render_plotly_chart,
    variance_bar_chart,
    waterfall_chart,
    apply_blitz_chart_theme,
)
from streamlit_app.components.filters import (
    drill_to_entity,
    fmt_display,
    get_compare_month,
    get_filtered_months,
    render_active_filter_bar,
    render_empty_state,
    get_active_currency,
)
from streamlit_app.components.ui import (
    render_chart_card, 
    render_page_header, 
    render_section_safe,
    get_kpi_layout,
    render_insight_card,
    fmt_percent,
    fmt_variance,
)
from streamlit_app.components.kpi_cards import render_bi_kpi_card

from streamlit_app.constants import (
    BLITZ_COLORS,
    ENTITY_COLORS,
    ENTITY_SUMMARY_SHEETS,
    WATERFALL_STEPS,
    fmt_idr,
    fmt_idr_full,
)

# ─────────────────────────────────────────────────────────────────────────────
# Public render
# ─────────────────────────────────────────────────────────────────────────────

def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the executive overview — management decision landing page."""
    render_page_header(
        "Executive Summary",
        "Top-level financial performance, profitability, and growth drivers.",
        eyebrow="Management Cockpit",
    )
    raw_cons = sheets.get("Consolidated Summary")
    if raw_cons is None:
        st.warning(":material/warning: 'Consolidated Summary' sheet not found.")
        return

    cons_long = parse_pl_sheet(raw_cons, "Consolidated")
    if cons_long.empty:
        st.warning("Could not parse the Consolidated Summary sheet.")
        return

    all_months: list[str] = (
        cons_long.drop_duplicates("Month").sort_values(by="MonthDate")["Month"].tolist()
    )
    filtered_months = get_filtered_months(all_months)
    if not filtered_months:
        render_empty_state(
            title="NO DATA FOR CURRENT FILTERS",
            suggestion="Try expanding the reporting period or changing the selected filters.",
        )
        return

    latest_month = filtered_months[-1]
    prior_month = get_compare_month(filtered_months, latest_month, all_months)

    # ── Top Filter Bar ───────────────────────────────────────────────
    _render_top_filter_bar(all_months)

    # ── Active Context Bar ─────────────────────────────────────────
    _render_active_context(latest_month, prior_month, filtered_months)
    
    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # Pre-compute
    wb_hash = st.session_state.get("_wb_hash", "")
    entity_frames = parse_all_entity_sheets(wb_hash, sheets, granularity="Summary")
    kpis = _compute_kpis(cons_long, raw_cons, sheets, latest_month, prior_month, all_months, entity_frames)

    # A. Executive KPI Summary
    st.markdown("### Executive Summary")
    render_section_safe(_render_primary_kpis, kpis, cons_long, latest_month, prior_month, section_name="Executive Summary")

    # B. Margins & Growth
    st.markdown("### Margins & Growth")
    render_section_safe(_render_margin_growth_kpis, kpis, cons_long, latest_month, section_name="Margins & Growth")

    # C. Business Snapshot
    st.markdown("### Business Snapshot")
    render_section_safe(_render_entity_business_kpis, kpis, entity_frames, latest_month, section_name="Business Snapshot")

    # D. Revenue & Composition
    col_r1, col_r2 = st.columns([2, 1], gap="medium")
    with col_r1:
        st.markdown("### Revenue Performance")
        _render_gross_revenue_trend(cons_long, all_months, filtered_months)
    with col_r2:
        st.markdown("### Revenue Composition")
        _render_entity_donut(entity_frames, filtered_months)

    # E. Profitability & Mix
    col_p1, col_p2 = st.columns([2, 1], gap="medium")
    with col_p1:
        st.markdown("### Profitability Performance")
        _render_profitability_trend(cons_long, filtered_months)
    with col_p2:
        st.markdown("### Revenue Mix")
        raw_master = sheets.get("MASTER")
        from streamlit_app.data.parsers import parse_master
        master_df, _ = parse_master(raw_master) if raw_master is not None else (pd.DataFrame(), [])
        _render_stream_donut(master_df, filtered_months)

    # F. P&L Bridge
    st.markdown("### P&L Bridge")
    _render_waterfall()

# ─────────────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get(df: pd.DataFrame, metric: str, month: str) -> float | None:
    rows = df[(df["Metric"] == metric) & (df["Month"] == month)]
    return float(rows["Value"].sum(skipna=True)) if not rows.empty else None

def _delta_pct(cur: float | None, prior: float | None) -> float | None:
    if cur is None or prior is None or prior == 0:
        return None
    return (cur - prior) / abs(prior)

def _sparkline(df: pd.DataFrame, metric: str) -> list[float] | None:
    rows = df[df["Metric"] == metric]
    if rows.empty:
        return None
    agg = rows.groupby("MonthDate", as_index=False).agg({"Value": "sum"}).sort_values(by="MonthDate")
    vals = [float(v) for v in agg["Value"].tail(12).tolist()]
    if len(vals) < 2:
        return None
    return vals

def _compute_kpis(
    cons_long: pd.DataFrame,
    raw_cons: pd.DataFrame,
    sheets: dict[str, pd.DataFrame],
    latest: str,
    prior: str | None,
    all_months: list[str],
    entity_frames: dict[str, pd.DataFrame] | None = None,
) -> dict:
    
    # 1. Base P&L Metrics
    metrics = [
        "Total Gross Revenue", "Net Revenue", "Total COGS", 
        "Gross Profit 1", "Gross Profit 2", "Total Operating Expenses", 
        "EBITDA", "NET PROFIT/LOSS (Before Tax)"
    ]
    
    kpi_dict = {}
    for m in metrics:
        cur_val = _get(cons_long, m, latest)
        pri_val = _get(cons_long, m, prior) if prior else None
        
        variance_abs = (cur_val - pri_val) if (cur_val is not None and pri_val is not None) else None
        variance_pct = _delta_pct(cur_val, pri_val)
        
        # Determine direction
        direction = "flat"
        if variance_abs and variance_abs > 0:
            direction = "up"
        elif variance_abs and variance_abs < 0:
            direction = "down"
            
        # Determine semantic status
        # For COGS and OPEX, down is positive. For Revenue/Profit, up is positive.
        status = "neutral"
        if variance_abs is not None:
            if m in ("Total COGS", "Total Operating Expenses"):
                status = "positive" if variance_abs <= 0 else "negative"
            else:
                status = "positive" if variance_abs >= 0 else "negative"
                
        kpi_dict[m] = {
            "cur": cur_val,
            "pri": pri_val,
            "var_abs": variance_abs,
            "var_pct": variance_pct,
            "direction": direction,
            "status": status,
            "sparkline_data": _sparkline(cons_long, m)
        }
        
    # 2. Margins
    ratios = parse_ratios(raw_cons, "Consolidated")
    margins = ["Gross Margin %", "Operating Margin %", "EBITDA Margin %"]
    for m in margins:
        val = None
        pri_val = None
        if not ratios.empty:
            m_rows = ratios[ratios["Metric"].str.lower() == m.lower()]
            if not m_rows.empty:
                cur_r = m_rows[m_rows["Month"] == latest]
                if not cur_r.empty:
                    val = float(cur_r["Value"].sum())
                if prior:
                    pri_r = m_rows[m_rows["Month"] == prior]
                    if not pri_r.empty:
                        pri_val = float(pri_r["Value"].sum())
                        
        if m == "Gross Margin %" and val is None:
            gp1_cur = kpi_dict.get("Gross Profit 1", {}).get("cur")
            rev_cur = kpi_dict.get("Net Revenue", {}).get("cur")
            if isinstance(gp1_cur, (int, float)) and isinstance(rev_cur, (int, float)) and rev_cur != 0:
                val = gp1_cur / rev_cur
                
            gp1_pri = kpi_dict.get("Gross Profit 1", {}).get("pri")
            rev_pri = kpi_dict.get("Net Revenue", {}).get("pri")
            if isinstance(gp1_pri, (int, float)) and isinstance(rev_pri, (int, float)) and rev_pri != 0:
                pri_val = gp1_pri / rev_pri
                        
        var_abs = (val - pri_val) if (val is not None and pri_val is not None) else None
        direction = "flat"
        if var_abs and var_abs > 0: direction = "up"
        elif var_abs and var_abs < 0: direction = "down"
        
        status = "neutral"
        if var_abs is not None:
            status = "positive" if var_abs >= 0 else "negative"
            
        kpi_dict[m] = {
            "cur": val,
            "pri": pri_val,
            "var_abs": var_abs, # For margins, this is pp difference
            "direction": direction,
            "status": status,
        }
        
    # 3. Growth (MoM and YoY)
    try:
        idx = all_months.index(latest)
    except ValueError:
        idx = len(all_months) - 1
        
    month_ly = all_months[idx - 12] if idx >= 12 else None
    month_lm = all_months[idx - 1] if idx >= 1 else None
    
    gr_cur = kpi_dict["Total Gross Revenue"]["cur"]
    gr_lm = _get(cons_long, "Total Gross Revenue", month_lm) if month_lm else None
    gr_ly = _get(cons_long, "Total Gross Revenue", month_ly) if month_ly else None
    
    mom = _delta_pct(gr_cur, gr_lm)
    yoy = _delta_pct(gr_cur, gr_ly)
    
    kpi_dict["growth"] = {
        "mom": mom,
        "yoy": yoy,
        "mom_status": "positive" if (mom and mom >= 0) else "negative",
        "yoy_status": "positive" if (yoy and yoy >= 0) else "negative",
        "month_lm": month_lm,
        "month_ly": month_ly,
    }
    
    # 4. Business KPIs (Active Client Count, Top Stream)
    active_clients = 0
    top_stream = "N/A"
    top_stream_pct = 0.0
    
    # Try to compute Active Clients from MASTER if it exists
    raw_master = sheets.get("MASTER")
    if raw_master is not None:
        from streamlit_app.data.parsers import parse_master
        master, missing = parse_master(raw_master)
        if not missing and not master.empty:
            lm_data = master[master["Month"] == latest]
            if not lm_data.empty:
                active_clients = lm_data[lm_data["Amount (IDR)"] > 0]["Client (clean)"].nunique()
                
    # Compute Top Revenue Stream reliably from cons_long
    streams = ["3PL", "Freight", "Mobile Selling", "EV Leasing", "COD", "Other"]
    stream_df = cons_long[(cons_long["Metric"].isin(streams)) & (cons_long["Month"] == latest)]
    if not stream_df.empty:
        stream_rev = stream_df.groupby("Metric")["Value"].sum().sort_values(ascending=False)
        total_stream_rev = stream_rev.sum()
        if total_stream_rev > 0:
            top_stream = stream_rev.index[0]
            top_stream_pct = stream_rev.iloc[0] / total_stream_rev
                    
    kpi_dict["business"] = {
        "active_clients": active_clients,
        "top_stream": top_stream,
        "top_stream_pct": top_stream_pct
    }

    return kpi_dict


# ─────────────────────────────────────────────────────────────────────────────
# Render Sections
# ─────────────────────────────────────────────────────────────────────────────

def _render_top_filter_bar(all_months: list[str]) -> None:
    from streamlit_app.components.filters import _PRESETS, _DEFAULT_PRESET, _apply_preset
    from streamlit_app.components.filters import multiselect_with_all
    
    if "overview_period_preset" not in st.session_state:
        st.session_state["overview_period_preset"] = st.session_state.get("period_preset", _DEFAULT_PRESET)
    if "overview_currency" not in st.session_state:
        st.session_state["overview_currency"] = st.session_state.get("currency", "IDR")
        
    with st.container(border=True):
        col1, col2 = st.columns([2.5, 1])
        
        with col1:
            st.markdown("<div style='font-size:11px;font-weight:700;margin-bottom:4px;color:#4D4D4D;text-transform:uppercase;'>Reporting Period</div>", unsafe_allow_html=True)
            preset = st.pills("Reporting Period", options=_PRESETS, key="overview_period_preset", label_visibility="collapsed")
            if not preset:
                preset = _DEFAULT_PRESET
            
            # Sync to global state
            if preset != st.session_state.get("period_preset"):
                st.session_state["period_preset"] = preset
                start_idx, end_idx = _apply_preset(preset, all_months)
                st.session_state["month_start_idx"] = start_idx
                st.session_state["month_end_idx"] = end_idx
                st.rerun()
                
            if preset == "Custom":
                c1, c2 = st.columns(2)
                cur_start = int(st.session_state.get("month_start_idx", 0))
                cur_end = int(st.session_state.get("month_end_idx", len(all_months)-1))
                
                with c1:
                    s_month = st.selectbox("Start month", options=all_months, index=cur_start, key="overview_start_month")
                with c2:
                    s_idx = all_months.index(s_month)
                    valid_ends = all_months[s_idx:]
                    e_idx_rel = max(0, min(cur_end - s_idx, len(valid_ends)-1))
                    e_month = st.selectbox("End month", options=valid_ends, index=e_idx_rel, key="overview_end_month")
                    
                new_start = all_months.index(s_month)
                new_end = all_months.index(e_month)
                if new_start != cur_start or new_end != cur_end:
                    st.session_state["month_start_idx"] = new_start
                    st.session_state["month_end_idx"] = new_end
                    st.rerun()
                    
        with col2:
            st.markdown("<div style='font-size:11px;font-weight:700;margin-bottom:4px;color:#4D4D4D;text-transform:uppercase;'>Currency</div>", unsafe_allow_html=True)
            curr = st.segmented_control("Currency", options=["IDR", "USD"], key="overview_currency", label_visibility="collapsed")
            if curr and curr != st.session_state.get("currency"):
                st.session_state["currency"] = curr
                st.rerun()
                
        # Row 2: Business Filters
        st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)
        bc1, bc2, bc3 = st.columns(3)
        with bc1:
            multiselect_with_all("Entity", st.session_state.get("_all_entity_options", []), "entity_filter")
        with bc2:
            multiselect_with_all("Revenue Stream", st.session_state.get("_all_stream_options", []), "stream_filter")
        with bc3:
            multiselect_with_all("Industry", st.session_state.get("_all_industry_options", []), "industry_filter")

def _render_active_context(latest: str, prior: str | None, months: list[str]) -> None:
    from html import escape
    n_months = len(months)
    period_label = f"{months[0]} – {latest}" if n_months > 1 else latest
    currency = get_active_currency()
    
    context_str = f"Period: {period_label}"
    if prior:
        context_str += f" · vs {prior}"
    context_str += f" · {currency}"
    
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};'>"
        f"{escape(context_str)}</div>",
        unsafe_allow_html=True
    )

def _kpi_helper(kpis: dict, metric_key: str, label: str) -> None:
    from streamlit_app.components.charts import render_sparkline
    data = kpis.get(metric_key, {})
    
    spark_data = data.get("sparkline_data")
    fig = None
    if spark_data:
        # Use red for expenses, blue for revenue
        color = "#CF222E" if metric_key in ("Total COGS", "Total Operating Expenses") else BLITZ_COLORS["primary"]
        fig = render_sparkline(spark_data, color=color)
        
    render_bi_kpi_card(
        title=label,
        current_value=fmt_display(data.get("cur")),
        comparison_value=fmt_display(data.get("pri")) if data.get("pri") is not None else None,
        variance_abs=fmt_variance(data.get("var_abs")),
        variance_pct=fmt_percent(data.get("var_pct")),
        direction=data.get("direction", "flat"),
        semantic_status=data.get("status", "neutral"),
        sparkline_fig=fig
    )

def _render_primary_kpis(kpis: dict, cons_long: pd.DataFrame, latest: str, prior: str | None) -> None:
    with get_kpi_layout(4) as cols:
        with cols[0]: _kpi_helper(kpis, "Total Gross Revenue", "Total Gross Revenue")
        with cols[1]: _kpi_helper(kpis, "Total COGS", "Total COGS")
        with cols[2]: _kpi_helper(kpis, "Gross Profit 1", "Gross Profit 1")
        with cols[3]: _kpi_helper(kpis, "Gross Profit 2", "Gross Profit 2")
        
    st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)
    
    with get_kpi_layout(4) as cols:
        with cols[0]: _kpi_helper(kpis, "Total Operating Expenses", "Total Opex")
        with cols[1]: _kpi_helper(kpis, "Net Revenue", "Net Revenue")
        with cols[2]: _kpi_helper(kpis, "EBITDA", "EBITDA")
        with cols[3]: _kpi_helper(kpis, "NET PROFIT/LOSS (Before Tax)", "Net Profit/Loss")


def _render_margin_growth_kpis(kpis: dict, cons_long: pd.DataFrame, latest: str) -> None:
    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)
    
    with get_kpi_layout(5) as cols:
        margins = [("EBITDA Margin %", "EBITDA Margin"), ("Gross Margin %", "Gross Margin"), ("Operating Margin %", "Operating Margin")]
        for i, (m_key, m_label) in enumerate(margins):
            data = kpis.get(m_key, {})
            with cols[i]:
                render_bi_kpi_card(
                    title=m_label,
                    current_value=fmt_percent(data.get("cur")),
                    variance_abs=f"{data.get('var_abs') * 100:+.1f}pp" if data.get("var_abs") is not None else None,
                    direction=data.get("direction", "flat"),
                    semantic_status=data.get("status", "neutral"),
                    comparison_value=fmt_percent(data.get("pri")) if data.get("pri") is not None else None,
                    size="medium"
                )
                
        # Growth
        growth = kpis.get("growth", {})
        with cols[3]:
            render_bi_kpi_card(
                title="YoY Growth %",
                current_value=fmt_percent(growth.get("yoy")),
                semantic_status=growth.get("yoy_status", "neutral"),
                direction="up" if growth.get("yoy") and growth.get("yoy") > 0 else "down",
                subtitle=f"vs {growth.get('month_ly')}" if growth.get("month_ly") else None,
                size="medium"
            )
        with cols[4]:
            render_bi_kpi_card(
                title="MoM Growth %",
                current_value=fmt_percent(growth.get("mom")),
                semantic_status=growth.get("mom_status", "neutral"),
                direction="up" if growth.get("mom") and growth.get("mom") > 0 else "down",
                subtitle=f"vs {growth.get('month_lm')}" if growth.get("month_lm") else None,
                size="medium"
            )


def _render_entity_business_kpis(kpis: dict, entity_frames: dict[str, pd.DataFrame], latest: str) -> None:
    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)
    
    with get_kpi_layout(5) as cols:
        # Entities
        for i, entity in enumerate(["Blitz", "Borzo", "TheLorry"]):
            df = entity_frames.get(entity)
            rev = _get(df, "Total Gross Revenue", latest) if df is not None else None
            with cols[i]:
                render_bi_kpi_card(
                    title=f"{entity} Revenue",
                    current_value=fmt_display(rev),
                    semantic_status="neutral",
                    size="medium"
                )
                
        # Business
        bus = kpis.get("business", {})
        
        # Determine reliable Active Client display
        act_clients = bus.get("active_clients", 0)
        client_val = str(act_clients) if act_clients > 0 else "N/A"
        client_sub = "Clients with revenue in period" if act_clients > 0 else "Active Clients cannot currently be computed reliably from the parsed data."
        
        with cols[3]:
            render_bi_kpi_card(
                title="Active Clients",
                current_value=client_val,
                subtitle=client_sub,
                size="medium"
            )
        with cols[4]:
            render_bi_kpi_card(
                title="Top Revenue Stream",
                current_value=bus.get("top_stream", "N/A"),
                subtitle=f"{fmt_percent(bus.get('top_stream_pct', 0))} of Total Revenue" if bus.get("top_stream") != "N/A" else "Data unavailable for period",
                size="medium"
            )


def _render_gross_revenue_trend(cons_long: pd.DataFrame, all_months: list[str], filtered_months: list[str]) -> None:
    from streamlit_app.components.charts import trend_line_chart
    
    df = cons_long[cons_long["Metric"] == "Total Gross Revenue"].copy()
    df = df.dropna(subset=["Value"])
    df = df.sort_values(by="MonthDate")
    
    # Calculate MoM and YoY safely across all available history
    df["MoM %"] = df["Value"].pct_change(1)
    df["YoY %"] = df["Value"].pct_change(12)
    
    df["MoM %"] = df["MoM %"].apply(lambda x: f"{x:+.1%}" if pd.notna(x) else "N/A")
    df["YoY %"] = df["YoY %"].apply(lambda x: f"{x:+.1%}" if pd.notna(x) else "N/A")
    
    # Filter to only the selected reporting period context
    df = df[df["Month"].isin(filtered_months)]
    
    with render_chart_card("Revenue Trend", subtitle="Monthly Total Gross Revenue"):
        if df.empty:
            st.caption("No data available for the selected period.")
        else:
            fig = trend_line_chart(
                df, x="Month", y="Value", color=None,
                category_orders={"Month": filtered_months},
                hover_data=["MoM %", "YoY %"]
            )
            fig.update_layout(height=360)
            apply_blitz_chart_theme(fig)
            render_plotly_chart(fig)

def _render_profitability_trend(cons_long: pd.DataFrame, filtered_months: list[str]) -> None:
    from streamlit_app.components.charts import trend_line_chart
    
    metrics = ["Gross Profit 1", "EBITDA", "NET PROFIT/LOSS (Before Tax)"]
    df = cons_long[cons_long["Metric"].isin(metrics)].copy()
    df = df.dropna(subset=["Value"])
    df = df[df["Month"].isin(filtered_months)]
    
    rename_map = {
        "NET PROFIT/LOSS (Before Tax)": "Net Profit/Loss"
    }
    df["Metric"] = df["Metric"].replace(rename_map)
    
    color_map = {
        "Gross Profit 1": BLITZ_COLORS["primary"],
        "EBITDA": BLITZ_COLORS["primary_hover"],
        "Net Profit/Loss": BLITZ_COLORS["deep_blue"]
    }
    
    with render_chart_card("Profitability Trend", subtitle="Gross Profit 1 vs EBITDA vs Net Profit"):
        if df.empty:
            st.caption("No data available for the selected period.")
        else:
            fig = trend_line_chart(
                df, x="Month", y="Value", color="Metric",
                category_orders={"Month": filtered_months},
                color_map=color_map
            )
            fig.update_layout(height=360)
            apply_blitz_chart_theme(fig)
            render_plotly_chart(fig)

def _render_entity_donut(entity_frames: dict[str, pd.DataFrame], filtered_months: list[str]) -> None:
    from streamlit_app.components.charts import donut_chart
    
    data = []
    for ent, df in entity_frames.items():
        if df is not None:
            mask = (df["Metric"] == "Total Gross Revenue") & (df["Month"].isin(filtered_months))
            val = df.loc[mask, "Value"].sum()
            if pd.notna(val) and val != 0:
                data.append({"Entity": ent, "Value": val})
                
    df_donut = pd.DataFrame(data)
    
    with render_chart_card("Revenue by Entity", subtitle="Revenue Share by Entity"):
        if df_donut.empty:
            st.caption("No data available for the selected period.")
        else:
            custom_entity_colors = {
                "Blitz": BLITZ_COLORS.get("primary", "#00B9F2"),
                "Borzo": "#F47920",     # established orange
                "TheLorry": "#009944"   # established green
            }
            fig = donut_chart(df_donut, names="Entity", values="Value", color_map=custom_entity_colors)
            fig.update_layout(height=360)
            apply_blitz_chart_theme(fig)
            render_plotly_chart(fig)

def _render_stream_donut(master: pd.DataFrame, filtered_months: list[str]) -> None:
    from streamlit_app.components.charts import donut_chart
    
    if master.empty:
        df = pd.DataFrame()
    else:
        from streamlit_app.data.parsers import month_sort_key
        entity_f = st.session_state.get("entity_filter", [])
        stream_f = st.session_state.get("stream_filter", [])
        industry_f = st.session_state.get("industry_filter", [])

        # Match using MonthDate (Timestamp) because MASTER's Month column might be raw datetime objects
        filtered_dts = [month_sort_key(m) for m in filtered_months]
        mask = master["MonthDate"].isin(filtered_dts)
        
        if entity_f:
            mask &= master["Entity"].isin(entity_f)
        if stream_f:
            mask &= master["Rev Stream"].isin(stream_f)
        if industry_f:
            mask &= master["Industry"].isin(industry_f)
            
        df = master[mask]
        
    if df.empty:
        agg = pd.DataFrame()
    else:
        agg = df.groupby("Rev Stream", as_index=False)["Amount (IDR)"].sum()
        agg = agg.rename(columns={"Rev Stream": "Metric", "Amount (IDR)": "Value"})
        agg = agg[(agg["Value"].notna()) & (agg["Value"] > 0)]
        
        # Apply currency conversion if needed
        currency = st.session_state.get("currency", "IDR")
        if currency == "USD":
            fx = st.session_state.get("fx_rate", 15000.0)
            agg["Value"] = agg["Value"] / fx
    
    with render_chart_card("Revenue by Revenue Stream", subtitle="Revenue Share by Stream"):
        if agg.empty:
            st.caption("No data available for the selected period.")
        else:
            # We map streams to distinct colors using Blitz color tokens if possible
            fig = donut_chart(agg, names="Metric", values="Value")
            fig.update_layout(height=360)
            apply_blitz_chart_theme(fig)
            render_plotly_chart(fig)

def _render_waterfall() -> None:
    from streamlit_app.components.filters import render_empty_state
    render_empty_state(
        title="P&L BRIDGE UNAVAILABLE",
        suggestion="P&L bridge unavailable for the current parsed data.",
        show_reset=False
    )
