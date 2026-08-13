"""Executive overview tab — full executive intelligence dashboard.

Information hierarchy:
    Row 0 → Period context header
    Row 1 → 8-KPI hero band (Gross Rev, Net Rev, Gross Profit, EBITDA, Net P/L,
              EBITDA Margin %, MoM Growth %, Top-5 Concentration)
    Row 2 → Auto-generated insight chips (data-driven, no LLM)
    Row 3 → Entity performance table | Revenue stream ranking | Client concentration
    Row 4 → Revenue by entity (multi-line) | P&L waterfall
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

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
    render_plotly_chart,
    waterfall_chart,
)
from streamlit_app.components.filters import (
    drill_to_entity,
    fmt_display,
    get_compare_month,
    get_filtered_months,
    render_active_filter_bar,
    render_empty_state,
)
from streamlit_app.components.ui import render_page_header, render_section_safe
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
        "Executive overview",
        "Understand revenue, profitability, growth drivers, concentration risk, and reporting quality at a glance.",
        eyebrow="Management cockpit",
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
        cons_long.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
    )
    filtered_months = get_filtered_months(all_months)
    if not filtered_months:
        render_empty_state(
            title="No months in the selected date range.",
            suggestion="Adjust the month range slider in the sidebar to include at least one period.",
            icon="📅",
            show_reset=True,
            key_suffix="overview",
        )
        return

    # ── Active filter context bar ─────────────────────────────────────────
    render_active_filter_bar(filtered_months)

    latest_month = filtered_months[-1]
    prior_month = get_compare_month(filtered_months, latest_month, all_months)

    # Pre-compute all entity frames ONCE — shared by insight chips, entity
    # performance table, and revenue trend chart.  Eliminates 6+ redundant
    # parse_pl_sheet cache lookups per render cycle.
    wb_hash = st.session_state.get("_wb_hash", "")
    entity_frames = parse_all_entity_sheets(wb_hash, sheets, granularity="Summary")

    # Pre-compute all values once
    kpis = _compute_kpis(cons_long, raw_cons, sheets, latest_month, prior_month, entity_frames)

    # ── Row 0: Section header ────────────────────────────────────────────
    render_section_safe(_render_header, latest_month, prior_month, filtered_months,
                        section_name="Period Header")

    # ── Row 1: 8-KPI hero band ───────────────────────────────────────────
    render_section_safe(_render_kpi_band, kpis, cons_long, filtered_months,
                        section_name="KPI Band")

    # ── Row 2: Executive insight chips ──────────────────────────────────
    render_section_safe(_render_insight_chips, kpis, sheets, filtered_months, latest_month, prior_month,
                        entity_frames=entity_frames,
                        section_name="Insight Chips")

    # ── Drill-down navigation strip ──────────────────────────────────────
    render_section_safe(_render_drill_strip, sheets, latest_month,
                        section_name="Drill-Down Strip")

    # ── Row 3: Entity perf | Stream ranking | Client concentration ───────
    col_entity, col_stream, col_conc = st.columns([4, 3, 3], gap="medium")
    with col_entity:
        render_section_safe(_render_entity_performance, entity_frames, sheets, latest_month, prior_month,
                            section_name="Entity Performance")
    with col_stream:
        render_section_safe(_render_stream_ranking, sheets, latest_month, prior_month,
                            section_name="Stream Ranking")
    with col_conc:
        render_section_safe(_render_concentration, sheets, filtered_months,
                            section_name="Client Concentration")

    # ── Row 4: Revenue trend | Waterfall ─────────────────────────────────
    col_trend, col_wf = st.columns([3, 2], gap="medium")
    with col_trend:
        render_section_safe(_render_entity_revenue_trend, entity_frames, filtered_months,
                            section_name="Revenue by Entity")
    with col_wf:
        render_section_safe(_render_waterfall, cons_long, latest_month,
                            section_name="P&L Waterfall")


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get(df: pd.DataFrame, metric: str, month: str) -> float | None:
    rows = df[(df["Metric"] == metric) & (df["Month"] == month)]
    return float(rows["Value"].sum(skipna=True)) if not rows.empty else None


def _delta_pct(cur: float | None, prior: float | None) -> float | None:
    if cur is None or prior is None or prior == 0:
        return None
    return (cur - prior) / abs(prior) * 100


def _delta_str(cur: float | None, prior: float | None) -> str | None:
    d = _delta_pct(cur, prior)
    return f"{d:+.1f}%" if d is not None else None


def _sparkline(df: pd.DataFrame, metric: str) -> list[float]:
    rows = df[df["Metric"] == metric]
    agg = rows.groupby("MonthDate", as_index=False)["Value"].sum().sort_values("MonthDate")
    return [float(v) for v in agg["Value"].tail(12).tolist()]


def _compute_kpis(
    cons_long: pd.DataFrame,
    raw_cons: pd.DataFrame,
    sheets: dict[str, pd.DataFrame],
    latest: str,
    prior: str | None,
    entity_frames: dict[str, pd.DataFrame] | None = None,
) -> dict:
    gross_rev = _get(cons_long, "Total Gross Revenue", latest)
    net_rev = _get(cons_long, "Net Revenue", latest)
    gross_profit = _get(cons_long, "Gross Profit 2", latest)
    ebitda = _get(cons_long, "EBITDA", latest)
    net_pl = _get(cons_long, "NET PROFIT/LOSS (Before Tax)", latest)

    prior_gross_rev = _get(cons_long, "Total Gross Revenue", prior) if prior else None
    prior_net_rev = _get(cons_long, "Net Revenue", prior) if prior else None
    prior_gross_profit = _get(cons_long, "Gross Profit 2", prior) if prior else None
    prior_ebitda = _get(cons_long, "EBITDA", prior) if prior else None
    prior_net_pl = _get(cons_long, "NET PROFIT/LOSS (Before Tax)", prior) if prior else None

    ratios = parse_ratios(raw_cons, "Consolidated")
    ebitda_margin: float | None = None
    prior_ebitda_margin: float | None = None
    if not ratios.empty:
        m_rows = ratios[ratios["Metric"].str.lower().str.contains("ebitda margin")]
        if not m_rows.empty:
            cur_r = m_rows[m_rows["Month"] == latest]
            ebitda_margin = float(cur_r["Value"].sum()) * 100 if not cur_r.empty else None
            if prior:
                pri_r = m_rows[m_rows["Month"] == prior]
                prior_ebitda_margin = float(pri_r["Value"].sum()) * 100 if not pri_r.empty else None

    mom_growth = _delta_pct(gross_rev, prior_gross_rev)

    top5_pct: float | None = None
    top5_clients: list[dict] = []
    raw_master = sheets.get("MASTER")
    if raw_master is not None:
        master, missing = parse_master(raw_master)
        if not missing and not master.empty:
            total = master["Amount (IDR)"].sum()
            if total > 0:
                by_client = master.groupby("Client (clean)")["Amount (IDR)"].sum().sort_values(ascending=False)
                top5_rev = by_client.head(5).sum()
                top5_pct = top5_rev / total * 100
                for name, rev in by_client.head(5).items():
                    top5_clients.append({"name": name, "rev": float(rev), "pct": float(rev / total * 100)})

    return {
        "gross_rev": gross_rev, "prior_gross_rev": prior_gross_rev,
        "net_rev": net_rev, "prior_net_rev": prior_net_rev,
        "gross_profit": gross_profit, "prior_gross_profit": prior_gross_profit,
        "ebitda": ebitda, "prior_ebitda": prior_ebitda,
        "net_pl": net_pl, "prior_net_pl": prior_net_pl,
        "ebitda_margin": ebitda_margin, "prior_ebitda_margin": prior_ebitda_margin,
        "mom_growth": mom_growth,
        "top5_pct": top5_pct,
        "top5_clients": top5_clients,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Row 0: Header
# ─────────────────────────────────────────────────────────────────────────────

def _render_header(latest: str, prior: str | None, months: list[str]) -> None:
    compare_label = f" vs {prior}" if prior else ""
    n_months = len(months)
    period_label = f"{months[0]} – {latest}" if n_months > 1 else latest
    st.caption(
        f"Latest reporting period: **{latest}**{compare_label} · "
        f"Selected period: {period_label} ({n_months} month{'s' if n_months != 1 else ''})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Row 1: 8-KPI hero band
# ─────────────────────────────────────────────────────────────────────────────

def _render_kpi_band(kpis: dict, cons_long: pd.DataFrame, filtered_months: list[str]) -> None:
    c1, c2, c3, c4 = st.columns(4, gap="small")
    with c1:
        _kpi_card("Gross Revenue", kpis["gross_rev"], kpis["prior_gross_rev"],
                  sparkline=_sparkline(cons_long, "Total Gross Revenue"),
                  help_text="Total Gross Revenue from Consolidated Summary")
    with c2:
        _kpi_card("Net Revenue", kpis["net_rev"], kpis["prior_net_rev"],
                  sparkline=_sparkline(cons_long, "Net Revenue"))
    with c3:
        _kpi_card("Gross Profit", kpis["gross_profit"], kpis["prior_gross_profit"],
                  sparkline=_sparkline(cons_long, "Gross Profit 2"))
    with c4:
        growth = kpis["mom_growth"]
        st.metric(
            label="Revenue Growth MoM",
            value=f"{growth:+.1f}%" if growth is not None else "N/A",
            border=True,
            help="Month-on-month change in Total Gross Revenue",
        )

    c5, c6, c7, c8 = st.columns(4, gap="small")
    with c5:
        _kpi_card("EBITDA", kpis["ebitda"], kpis["prior_ebitda"],
                  sparkline=_sparkline(cons_long, "EBITDA"),
                  help_text="Earnings before interest, tax, depreciation & amortisation")
    with c6:
        _kpi_card("Net Profit / Loss", kpis["net_pl"], kpis["prior_net_pl"],
                  sparkline=_sparkline(cons_long, "NET PROFIT/LOSS (Before Tax)"))
    with c7:
        margin = kpis["ebitda_margin"]
        prior_m = kpis["prior_ebitda_margin"]
        st.metric(
            label="EBITDA Margin %",
            value=f"{margin:.1f}%" if margin is not None else "N/A",
            delta=_delta_str(margin, prior_m),
            border=True,
            help="EBITDA as % of Gross Revenue",
        )
    with c8:
        top5 = kpis["top5_pct"]
        high_risk = top5 is not None and top5 > 60
        st.metric(
            label="Top-5 Client Concentration",
            value=f"{top5:.1f}%" if top5 is not None else "N/A",
            border=True,
            help="Top 5 clients' combined share of all-time total revenue. Above 60% = high risk.",
            delta=":material/warning: High risk" if high_risk else None,
            delta_color="inverse" if high_risk else "normal",
        )


def _kpi_card(
    label: str,
    value: float | None,
    prior: float | None,
    sparkline: list[float] | None = None,
    help_text: str | None = None,
) -> None:
    delta = _delta_str(value, prior)
    st.metric(
        label=label,
        value=fmt_display(value) if value is not None else "N/A",
        delta=delta,
        border=True,
        chart_data=sparkline if sparkline and len(sparkline) > 1 else None,
        chart_type="line",
        help=help_text or (f"Prior period: {fmt_display(prior)}" if prior is not None else None),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Row 2: Executive insight chips
# ─────────────────────────────────────────────────────────────────────────────

def _render_insight_chips(
    kpis: dict,
    sheets: dict[str, pd.DataFrame],
    filtered_months: list[str],
    latest: str,
    prior: str | None,
    entity_frames: dict[str, pd.DataFrame] | None = None,
) -> None:
    insights: list[tuple[str, str, str]] = []

    # Revenue direction
    growth = kpis["mom_growth"]
    if growth is not None and prior:
        if growth > 0:
            insights.append((":material/trending_up:", BLITZ_COLORS["primary"],
                f"Revenue grew **{growth:+.1f}%** MoM ({prior} → {latest})"))
        else:
            insights.append((":material/trending_down:", "#CF222E",
                f"Revenue declined **{growth:+.1f}%** MoM ({prior} → {latest})"))

    # EBITDA margin signal
    margin = kpis["ebitda_margin"]
    prior_margin = kpis["prior_ebitda_margin"]
    if margin is not None:
        if margin < 0:
            label = "EBITDA margin remains negative"
            if prior_margin is not None:
                diff = margin - prior_margin
                direction = "improved" if diff > 0 else "worsened"
                label += f" ({direction} {abs(diff):.1f}pp vs prior)"
            insights.append((":material/warning:", "#BF8700", label + "."))
        else:
            label = f"EBITDA margin positive at **{margin:.1f}%**"
            if prior_margin is not None:
                label += f" ({margin - prior_margin:+.1f}pp vs prior)"
            insights.append((":material/check_circle:", BLITZ_COLORS["primary_hover"], label + "."))

    # Leading entity — use pre-computed entity_frames if available
    top_entity: str | None = None
    top_entity_rev: float = 0
    frames_to_check = entity_frames or {}
    for entity, df in frames_to_check.items():
        row = df[(df["Metric"] == "Total Gross Revenue") & (df["Month"] == latest)]
        rev = float(row["Value"].sum()) if not row.empty else 0
        if rev > top_entity_rev:
            top_entity_rev = rev
            top_entity = entity
    if top_entity:
        insights.append((":material/apartment:", BLITZ_COLORS["primary"],
            f"**{top_entity}** leads group revenue at **{fmt_idr(top_entity_rev)}** in {latest}."))

    # Top revenue stream from MASTER
    raw_master = sheets.get("MASTER")
    if raw_master is not None:
        master, missing = parse_master(raw_master)
        if not missing and not master.empty:
            vis = master[master["Month"].isin(filtered_months)]
            if not vis.empty:
                stream_rev = vis.groupby("Rev Stream")["Amount (IDR)"].sum().sort_values(ascending=False)
                if not stream_rev.empty:
                    top_stream = stream_rev.index[0]
                    top_pct = stream_rev.iloc[0] / stream_rev.sum() * 100
                    insights.append((":material/donut_small:", BLITZ_COLORS["deep_blue"],
                        f"**{top_stream}** is the dominant revenue stream "
                        f"(**{top_pct:.0f}%** of group revenue in period)."))

    # Concentration risk
    top5 = kpis["top5_pct"]
    if top5 is not None:
        if top5 > 60:
            insights.append((":material/groups:", "#CF222E",
                f"Concentration at **{top5:.1f}%** — top 5 clients account for over 60% of revenue."))
        elif top5 > 40:
            insights.append((":material/groups:", "#BF8700",
                f"Concentration at **{top5:.1f}%** — monitor client dependency risk."))

    # Data health flags
    raw_tie = sheets.get("TIE-OUT CHECK")
    if raw_tie is not None:
        from streamlit_app.data.parsers import parse_tie_out
        tie = parse_tie_out(raw_tie)
        if not tie.empty:
            flagged = tie[tie["Delta"].abs() > 1_000_000]
            if not flagged.empty:
                insights.append((":material/report:", "#CF222E",
                    f"**{len(flagged)} reconciliation flag{'s' if len(flagged) != 1 else ''}** "
                    f"detected — review Data Health tab."))

    # Anomaly signals from the selected period
    if filtered_months and len(filtered_months) >= 2:
        raw_cons_local = sheets.get("Consolidated Summary")
        if raw_cons_local is not None:
            from streamlit_app.data.parsers import parse_pl_sheet as _pps  # noqa: PLC0415
            _cl = _pps(raw_cons_local, "Consolidated")
            anomaly_flags = detect_anomalies(_cl, filtered_months)
            for flag in anomaly_flags[:2]:  # cap at 2 anomaly chips
                flag_color = "#CF222E" if flag.level == "critical" else "#BF8700"
                icon = ":material/error:" if flag.level == "critical" else ":material/warning:"
                insights.append((
                    icon,
                    flag_color,
                    f"{flag.title}" + (f": {flag.detail[:80]}…" if len(flag.detail) > 80 else f": {flag.detail}"),
                ))

    if not insights:
        return

    st.markdown(
        f"<div style='font-size:11px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;margin-top:4px;'>"
        f"Executive Insights</div>",
        unsafe_allow_html=True,
    )

    n = len(insights)
    cols = st.columns(n, gap="small")
    for col, (icon, color, text) in zip(cols, insights):
        with col:
            st.markdown(
                f"""<div style="background:#FFFFFF;border:1px solid {BLITZ_COLORS['border']};
                    border-left:3px solid {color};border-radius:8px;padding:10px 12px;
                    font-size:12.5px;line-height:1.5;color:{BLITZ_COLORS['text_primary']};
                    min-height:54px;">{icon} {text}</div>""",
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Row 3a: Entity performance comparison table
# ─────────────────────────────────────────────────────────────────────────────

def _render_entity_performance(
    entity_frames: dict[str, pd.DataFrame],
    sheets: dict[str, pd.DataFrame],
    latest: str,
    prior: str | None,
) -> None:
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:10px;'>"
        f":material/compare: Entity Performance — {latest}</div>",
        unsafe_allow_html=True,
    )

    _METRICS = [
        ("Revenue", "Total Gross Revenue"),
        ("Gross Profit", "Gross Profit 2"),
        ("EBITDA", "EBITDA"),
        ("Net P/L", "NET PROFIT/LOSS (Before Tax)"),
    ]

    rows: list[dict] = []
    for entity, df in entity_frames.items():
        if df.empty:
            continue
        row: dict = {"Entity": entity}
        for col_label, metric in _METRICS:
            cur = _get(df, metric, latest)
            pri = _get(df, metric, prior) if prior else None
            val_str = fmt_display(cur) if cur is not None else "—"
            if pri is not None and cur is not None and pri != 0:
                pct = (cur - pri) / abs(pri) * 100
                arrow = "▲" if pct > 0 else "▼"
                row[col_label] = f"{val_str} {arrow}{abs(pct):.0f}%"
            else:
                row[col_label] = val_str
        rows.append(row)

    if not rows:
        st.caption("No per-entity data available.")
        return

    border = BLITZ_COLORS["border"]
    header_bg = BLITZ_COLORS["pale_blue"]
    header_cols = ["Entity"] + [c for c, _ in _METRICS]
    col_widths = ["22%", "20%", "20%", "20%", "18%"]

    thead = "".join(
        f"<th style='padding:7px 8px;text-align:left;font-size:11px;font-weight:600;"
        f"color:{BLITZ_COLORS['text_secondary']};width:{col_widths[i]};'>{h}</th>"
        for i, h in enumerate(header_cols)
    )
    tbody = ""
    for i, row in enumerate(rows):
        bg = "#FFFFFF" if i % 2 == 0 else BLITZ_COLORS["off_white"]
        entity = row["Entity"]
        dot = (
            f"<span style='display:inline-block;width:8px;height:8px;border-radius:50%;"
            f"background:{ENTITY_COLORS.get(entity, BLITZ_COLORS['primary'])};margin-right:6px;'></span>"
        )
        entity_cell = (
            f"<td style='padding:8px;font-size:12px;font-weight:600;"
            f"color:{BLITZ_COLORS['text_primary']};'>{dot}{entity}</td>"
        )
        data_cells = "".join(
            f"<td style='padding:8px;font-size:11.5px;color:{BLITZ_COLORS['text_primary']};'>{row.get(c, '—')}</td>"
            for c, _ in _METRICS
        )
        tbody += f"<tr style='background:{bg};'>{entity_cell}{data_cells}</tr>"

    st.markdown(
        f"<table style='width:100%;border-collapse:collapse;border:1px solid {border};"
        f"border-radius:8px;overflow:hidden;'>"
        f"<thead style='background:{header_bg};'><tr>{thead}</tr></thead>"
        f"<tbody>{tbody}</tbody></table>",
        unsafe_allow_html=True,
    )

    # EBITDA margin per entity (inline below table)
    margin_parts = []
    for entity, _df in entity_frames.items():
        raw_entity = sheets.get(ENTITY_SUMMARY_SHEETS.get(entity, ""))
        if raw_entity is None:
            continue
        try:
            ratios = parse_ratios(raw_entity, entity)
            if not ratios.empty:
                m_rows = ratios[ratios["Metric"].str.lower().str.contains("ebitda margin")]
                cur_r = m_rows[m_rows["Month"] == latest] if not m_rows.empty else pd.DataFrame()
                if not cur_r.empty:
                    mv = float(cur_r["Value"].sum()) * 100
                    color = ENTITY_COLORS.get(entity, BLITZ_COLORS["primary"])
                    margin_parts.append(
                        f"<strong style='color:{color};'>{entity}</strong> {mv:.1f}%"
                    )
        except Exception:
            pass
    if margin_parts:
        st.markdown(
            f"<div style='margin-top:6px;font-size:11px;color:{BLITZ_COLORS['text_secondary']};'>"
            f"EBITDA Margin %: {' &nbsp;·&nbsp; '.join(margin_parts)}</div>",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Row 3b: Revenue stream ranking
# ─────────────────────────────────────────────────────────────────────────────

def _render_stream_ranking(
    sheets: dict[str, pd.DataFrame],
    latest: str,
    prior: str | None,
) -> None:
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:10px;'>"
        f":material/donut_small: Revenue Streams — {latest}</div>",
        unsafe_allow_html=True,
    )
    raw_master = sheets.get("MASTER")
    if raw_master is None:
        st.caption("MASTER sheet not found.")
        return
    master, missing = parse_master(raw_master)
    if missing or master.empty:
        st.caption("Could not parse MASTER sheet.")
        return

    latest_data = master[master["Month"] == latest]
    prior_data = master[master["Month"] == prior] if prior else pd.DataFrame()
    stream_cur = latest_data.groupby("Rev Stream")["Amount (IDR)"].sum().sort_values(ascending=False)
    stream_pri = prior_data.groupby("Rev Stream")["Amount (IDR)"].sum() if not prior_data.empty else pd.Series(dtype=float)

    total = stream_cur.sum()
    if total == 0:
        st.caption("No stream revenue data for selected month.")
        return

    border = BLITZ_COLORS["border"]
    items_html = ""
    for rank, (stream, rev) in enumerate(stream_cur.items(), 1):
        pct = rev / total * 100
        prior_rev = float(stream_pri.get(stream, 0))
        mom_pct = ((rev - prior_rev) / abs(prior_rev) * 100) if prior_rev != 0 else None
        mom_str = f"{mom_pct:+.1f}%" if mom_pct is not None else "—"
        mom_color = BLITZ_COLORS["primary"] if mom_pct is not None and mom_pct >= 0 else "#CF222E"
        bar_w = max(3, int(pct))
        items_html += (
            f"<div style='padding:8px 4px;border-bottom:1px solid {border};'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;'>"
            f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_primary']};'>"
            f"<span style='color:{BLITZ_COLORS['text_secondary']};margin-right:6px;'>{rank}.</span>{stream}</div>"
            f"<div style='text-align:right;'>"
            f"<span style='font-size:12px;font-weight:700;color:{BLITZ_COLORS['text_primary']};'>{fmt_display(rev)}</span>"
            f"<span style='font-size:10px;color:{mom_color};margin-left:6px;'>{mom_str}</span>"
            f"</div></div>"
            f"<div style='height:4px;background:{BLITZ_COLORS['border']};border-radius:2px;'>"
            f"<div style='height:4px;width:{bar_w}%;background:{BLITZ_COLORS['primary']};border-radius:2px;'></div></div>"
            f"<div style='font-size:10px;color:{BLITZ_COLORS['text_secondary']};margin-top:2px;'>{pct:.1f}% of total</div>"
            f"</div>"
        )

    st.markdown(
        f"<div style='background:#FFFFFF;border:1px solid {border};border-radius:8px;"
        f"padding:4px 12px;'>{items_html}</div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Row 3c: Client concentration risk
# ─────────────────────────────────────────────────────────────────────────────

def _render_concentration(
    sheets: dict[str, pd.DataFrame],
    filtered_months: list[str],
) -> None:
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:10px;'>"
        f":material/groups: Concentration Risk</div>",
        unsafe_allow_html=True,
    )
    raw_master = sheets.get("MASTER")
    if raw_master is None:
        st.caption("MASTER sheet not found.")
        return
    master, missing = parse_master(raw_master)
    if missing or master.empty:
        st.caption("Could not parse MASTER sheet.")
        return

    vis = master[master["Month"].isin(filtered_months)]
    if vis.empty:
        st.caption("No data in the selected range.")
        return

    total = vis["Amount (IDR)"].sum()
    if total == 0:
        st.caption("No revenue in selected period.")
        return

    by_client = vis.groupby("Client (clean)")["Amount (IDR)"].sum().sort_values(ascending=False)
    top5_pct = by_client.head(5).sum() / total * 100

    risk_color = "#CF222E" if top5_pct > 60 else "#BF8700" if top5_pct > 40 else BLITZ_COLORS["primary"]
    risk_label = "HIGH" if top5_pct > 60 else "MODERATE" if top5_pct > 40 else "LOW"
    border = BLITZ_COLORS["border"]

    st.markdown(
        f"<div style='background:#FFFFFF;border:1px solid {border};border-radius:8px;"
        f"padding:14px 16px;margin-bottom:10px;'>"
        f"<div style='font-size:28px;font-weight:800;color:{risk_color};'>{top5_pct:.1f}%</div>"
        f"<div style='font-size:11px;color:{BLITZ_COLORS['text_secondary']};margin-top:2px;'>"
        f"Top-5 client share &nbsp;"
        f"<span style='background:{risk_color};color:#FFFFFF;padding:1px 6px;border-radius:4px;"
        f"font-size:10px;font-weight:700;'>{risk_label}</span></div>"
        f"<div style='height:6px;background:{BLITZ_COLORS['border']};border-radius:3px;margin-top:10px;'>"
        f"<div style='height:6px;width:{min(100, top5_pct):.0f}%;background:{risk_color};border-radius:3px;'>"
        f"</div></div></div>",
        unsafe_allow_html=True,
    )

    items_html = ""
    for rank, (name, rev) in enumerate(by_client.head(5).items(), 1):
        pct = rev / total * 100
        items_html += (
            f"<div style='display:flex;justify-content:space-between;padding:6px 0;"
            f"border-bottom:1px solid {border};font-size:11.5px;'>"
            f"<div style='color:{BLITZ_COLORS['text_secondary']};margin-right:4px;width:16px;'>{rank}.</div>"
            f"<div style='flex:1;color:{BLITZ_COLORS['text_primary']};font-weight:500;"
            f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:120px;'>{name}</div>"
            f"<div style='text-align:right;'>"
            f"<span style='color:{BLITZ_COLORS['text_primary']};font-weight:600;'>{fmt_display(rev)}</span>"
            f"<span style='color:{BLITZ_COLORS['text_secondary']};margin-left:4px;font-size:10px;'>{pct:.1f}%</span>"
            f"</div></div>"
        )
    st.markdown(
        f"<div style='background:#FFFFFF;border:1px solid {border};border-radius:8px;"
        f"padding:8px 12px;'>{items_html}</div>",
        unsafe_allow_html=True,
    )

    records = []
    for month in filtered_months:
        m_data = master[master["Month"] == month]
        m_total = m_data["Amount (IDR)"].sum()
        if m_total <= 0:
            continue
        top5_m = m_data.groupby("Client (clean)")["Amount (IDR)"].sum().nlargest(5).sum()
        records.append({"Month": month, "Top-5 %": round(top5_m / m_total * 100, 1)})
    if len(records) > 1:
        st.caption("Monthly trend:")
        st.line_chart(pd.DataFrame(records).set_index("Month")["Top-5 %"], height=110)


# ─────────────────────────────────────────────────────────────────────────────
# Row 4a: Revenue trend by entity (stacked area)
# ─────────────────────────────────────────────────────────────────────────────

def _render_entity_revenue_trend(
    entity_frames: dict[str, pd.DataFrame],
    filtered_months: list[str],
) -> None:
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f":material/show_chart: Revenue by Entity</div>",
        unsafe_allow_html=True,
    )
    frames: list[pd.DataFrame] = []
    for entity, df in entity_frames.items():
        rev = df[df["Metric"] == "Total Gross Revenue"]
        if not rev.empty:
            frames.append(pd.DataFrame(rev))

    if not frames:
        st.caption("No per-entity data found.")
        return

    entity_long = pd.concat(frames, ignore_index=True)
    vis = pd.DataFrame(entity_long[entity_long["Month"].isin(filtered_months)])
    if vis.empty:
        st.caption("No data in the selected range.")
        return

    # Optional 3M rolling average (only when enough months available)
    show_rolling = (
        len(filtered_months) >= 4
        and st.checkbox("Show 3M rolling avg", value=False, key="overview_rolling_avg")
    )
    rolling_df = None
    if show_rolling:
        # Build rolling avg per entity
        rolling_frames = []
        for entity, df in entity_frames.items():
            r = compute_rolling_avg(df, "Total Gross Revenue", filtered_months, window=3)
            if not r.empty:
                r = r.copy()
                r["Entity"] = entity
                rolling_frames.append(r)
        if rolling_frames:
            rolling_df = pd.concat(rolling_frames, ignore_index=True)

    # Annotations on the group leader entity (peak/trough)
    top_entity: str | None = None
    top_rev = 0.0
    for entity, df in entity_frames.items():
        rows = df[(df["Metric"] == "Total Gross Revenue") & (df["Month"].isin(filtered_months))]
        rev = float(rows["Value"].sum()) if not rows.empty else 0.0
        if rev > top_rev:
            top_rev = rev
            top_entity = entity

    annotations = None
    if top_entity and top_entity in entity_frames:
        annotations = find_chart_annotations(
            entity_frames[top_entity], "Total Gross Revenue", filtered_months, max_annotations=2
        )

    if show_rolling and rolling_df is not None:
        fig = annotated_trend_chart(
            vis, "Month", "Value", "Entity",
            rolling_avg_df=rolling_df,
            rolling_avg_label="3M Avg",
            annotations=annotations,
            category_orders={"Month": filtered_months},
            color_map=ENTITY_COLORS,
        )
    else:
        fig = entity_revenue_line_chart(
            vis, "Month", "Value", "Entity",
            category_orders={"Month": filtered_months},
            color_map=ENTITY_COLORS,
        )
        # Add annotations to the plain chart too
        if annotations:
            from streamlit_app.components.charts import add_reference_line  # noqa: PLC0415
            from streamlit_app.constants import fmt_idr as _fmt  # noqa: PLC0415
            _ACOLORS = {"peak": BLITZ_COLORS["primary"], "trough": "#CF222E",
                        "mom_up": BLITZ_COLORS["primary_hover"], "mom_down": "#BF8700"}
            for ann in annotations:
                fig.add_annotation(
                    x=ann.month, y=ann.value,
                    text=f"<b>{'▲' if ann.kind in ('peak','mom_up') else '▼'} {ann.label}</b><br>{_fmt(ann.value)}",
                    showarrow=True, arrowhead=2, arrowsize=0.8, arrowwidth=1.2,
                    arrowcolor=_ACOLORS.get(ann.kind, BLITZ_COLORS["text_secondary"]),
                    ax=0, ay=-36,
                    font=dict(size=9, color=_ACOLORS.get(ann.kind, BLITZ_COLORS["text_secondary"]),
                              family="Inter, sans-serif"),
                    bgcolor="rgba(255,255,255,0.88)",
                    bordercolor=_ACOLORS.get(ann.kind, BLITZ_COLORS["text_secondary"]),
                    borderwidth=1, borderpad=3,
                )

    render_plotly_chart(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Row 4b: P&L waterfall for latest month
# ─────────────────────────────────────────────────────────────────────────────

def _render_waterfall(cons_long: pd.DataFrame, latest: str) -> None:
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f":material/waterfall_chart: P&L Bridge — {latest}</div>",
        unsafe_allow_html=True,
    )
    labels, values, measure = [], [], []
    for metric_key, display_name in WATERFALL_STEPS:
        val = _get(cons_long, metric_key, latest)
        if val is None:
            continue
        labels.append(display_name)
        values.append(val)
        measure.append(
            "total" if display_name in ("Gross Revenue", "Gross Profit", "EBITDA", "Net Profit")
            else "relative"
        )
    if not labels:
        st.caption("No waterfall data available.")
        return
    fig = waterfall_chart(labels, values, title="", measures=measure)
    render_plotly_chart(fig)


def _render_drill_strip(sheets: dict[str, pd.DataFrame], latest: str) -> None:
    """Render a row of action chips to drill down to specific entities."""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin:24px 0 8px;'>"
        f":material/manage_search: Investigate by Entity</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns(4, gap="small")
    for i, entity in enumerate(ENTITY_SUMMARY_SHEETS.keys()):
        if i >= 4:
            break
        with cols[i]:
            if st.button(
                f"Drill to {entity} →",
                key=f"drill_{entity}",
                width="stretch",
                help=f"Filter entire dashboard to {entity} and investigate."
            ):
                drill_to_entity(entity)
