"""Consolidated Group P&L tab — variance analysis, waterfall, margin intelligence, OpEx."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.components.charts import (
    annotated_trend_chart,
    comparison_bar_chart,
    donut_chart,
    margin_multi_line,
    render_plotly_chart,
    waterfall_chart,
)
from streamlit_app.components.filters import (
    convert_value,
    fmt_display,
    get_active_currency,
    get_compare_month,
    get_filtered_months,
    render_active_filter_bar,
    render_empty_state,
)
from streamlit_app.components.kpi_cards import render_kpi_row
from streamlit_app.components.ui import render_page_header, render_section_safe
from streamlit_app.constants import (
    BLITZ_COLORS,
    CONSOLIDATED_KPI_METRICS,
    OPEX_LINE_ITEMS,
    WATERFALL_STEPS,
    fmt_idr,
    fmt_idr_full,
)
from streamlit_app.data.analytics import (
    compute_historical_average,
    compute_revenue_drivers,
    compute_rolling_avg,
    compute_yoy_comparison,
    detect_anomalies,
    find_chart_annotations,
)
from streamlit_app.data.parsers import parse_master, parse_pl_sheet, parse_ratios


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_val(cons_long: pd.DataFrame, metric: str, month: str) -> float | None:
    """Return the summed value for a metric/month, or None if not found."""
    rows = cons_long[(cons_long["Metric"] == metric) & (cons_long["Month"] == month)]
    return float(rows["Value"].sum()) if not rows.empty else None


def _find_latest_actual_month(cons_long: pd.DataFrame, all_months: list[str]) -> str | None:
    """Return the last month in all_months that has a non-zero Total Gross Revenue.

    This prevents the dashboard from defaulting to a future/unpopulated month
    that has zero revenue, which would produce misleading KPI cards and alerts.
    """
    rev_metric = "Total Gross Revenue"
    for month in reversed(all_months):
        val = _get_val(cons_long, rev_metric, month)
        if val is not None and val != 0:
            return month
    return None


def _build_actual_months(cons_long: pd.DataFrame, months: list[str]) -> list[str]:
    """Return only those months from `months` where Total Gross Revenue is non-zero.

    Used to guard anomaly detection and comparisons against unpopulated
    future periods that would produce false 100% decline alerts.
    """
    rev_metric = "Total Gross Revenue"
    return [
        m for m in months
        if _get_val(cons_long, rev_metric, m) not in (None, 0)
    ]


# ---------------------------------------------------------------------------
# Tab entry point
# ---------------------------------------------------------------------------

def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the Consolidated Group P&L tab."""
    render_page_header(
        "Consolidated P&L",
        "Review the group profit bridge, material variances, margin trajectory, and operating-cost pressure.",
        eyebrow="Group performance",
    )
    raw = sheets.get("Consolidated Summary")
    if raw is None:
        st.warning(":material/warning: 'Consolidated Summary' sheet not found.")
        return

    cons_long = parse_pl_sheet(raw, "Consolidated")
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
            key_suffix="cons",
        )
        return

    render_active_filter_bar(filtered_months)

    # ── Determine "latest actual" month ──────────────────────────────────
    # Use the last month with actual non-zero revenue as the reference point
    # for KPI cards, variance table, waterfall, and driver analysis.
    # This prevents defaulting to a future/unpopulated month in the workbook.
    latest_actual_month = _find_latest_actual_month(cons_long, all_months)
    if latest_actual_month is None:
        # All months are empty — fall back gracefully
        latest_actual_month = filtered_months[-1]

    # ── Build actual-only month list for anomaly detection ────────────────
    # This prevents "Revenue declined 100% MoM" when a populated month is
    # compared against an unpopulated future placeholder.
    actual_filtered_months = _build_actual_months(cons_long, filtered_months)

    prior_month = get_compare_month(
        # Use all months so prior-period can reach outside the filter window
        all_months, latest_actual_month, all_months
    )

    # Resolve YoY month (same month, prior calendar year) if data exists
    _yoy_result = compute_yoy_comparison(cons_long, "Total Gross Revenue", latest_actual_month, all_months)
    yoy_month: str | None = _yoy_result.prior_year_month if _yoy_result.available else None

    # Determine whether comparison mode is MoM or YoY for labeling
    compare_mode: str = st.session_state.get("compare_mode", "Prior Month")
    is_yoy_mode = compare_mode == "Same Month LY"
    comparison_label = f"YoY vs {prior_month}" if is_yoy_mode and prior_month else (
        f"MoM vs {prior_month}" if prior_month else "No comparison"
    )

    # ── Anomaly Banner ─────────────────────────────────────────────────
    # Only pass months with actual data to avoid false 100% decline alerts
    if actual_filtered_months:
        render_section_safe(
            _render_anomaly_banner, cons_long, actual_filtered_months,
            section_name="Anomaly Detection",
        )

    # ── Row 0: KPI cards ─────────────────────────────────────────────────
    kpi_metrics = [m for m in CONSOLIDATED_KPI_METRICS if m in cons_long["Metric"].unique()]
    render_kpi_row(cons_long, kpi_metrics, latest_actual_month, prior_month, yoy_month=yoy_month)

    vis = pd.DataFrame(cons_long[cons_long["Month"].isin(filtered_months)])
    cat_orders = {"Month": filtered_months}

    # ── Row 1: Variance table | P&L waterfall ────────────────────────────
    col_var, col_wf = st.columns([3, 2], gap="medium")
    with col_var:
        render_section_safe(
            _render_variance_table, cons_long, latest_actual_month, prior_month,
            comparison_label=comparison_label,
            section_name="Variance Table",
        )
    with col_wf:
        render_section_safe(_render_waterfall, cons_long, latest_actual_month,
                            section_name="P&L Waterfall")

    # ── Row 1b: Driver Analysis ───────────────────────────────────────────
    if prior_month:
        master_raw = sheets.get("MASTER")
        master_df: pd.DataFrame | None = None
        if master_raw is not None:
            _m, _missing = parse_master(master_raw)
            if not _missing:
                master_df = _m
        render_section_safe(
            _render_driver_analysis, cons_long, None, master_df, latest_actual_month, prior_month,
            section_name="Revenue Driver Analysis",
        )

    # ── Row 2: Revenue trend w/ rolling avg | Margin intelligence ─────────
    col_rev, col_mg = st.columns(2, gap="medium")
    with col_rev:
        render_section_safe(_render_revenue_trend, cons_long, filtered_months, cat_orders,
                            section_name="Revenue Trend")
    with col_mg:
        render_section_safe(_render_margin_intelligence, raw, filtered_months, cat_orders,
                            section_name="Margin Intelligence")

    # ── Row 3: Cost ratio trend | OpEx ranked ────────────────────────────
    col_cost, col_opex = st.columns(2, gap="medium")
    with col_cost:
        render_section_safe(_render_cost_ratio_trend, cons_long, filtered_months, cat_orders,
                            section_name="Cost Efficiency")
    with col_opex:
        render_section_safe(_render_opex_breakdown, vis, latest_actual_month, prior_month, cons_long,
                            section_name="Operating Costs")

    # ── Row 4 (optional): Revenue / Margin combo | OpEx donut ─────────────
    # Only rendered when sufficient data exists — avoids empty chart clutter.
    _combo_data = _build_combo_data(cons_long, filtered_months)
    _donut_data = _build_opex_donut_data(vis, latest_actual_month)
    if _combo_data is not None or _donut_data is not None:
        col_combo, col_donut = st.columns(2, gap="medium")
        with col_combo:
            if _combo_data is not None:
                render_section_safe(
                    _render_revenue_margin_combo, _combo_data, cat_orders,
                    section_name="Revenue vs Margin",
                )
        with col_donut:
            if _donut_data is not None:
                render_section_safe(
                    _render_opex_donut, _donut_data, latest_actual_month,
                    section_name="OpEx Composition",
                )

    # ── Full P&L table ───────────────────────────────────────────────────
    full_pl = st.expander(
        "Full P&L table (all months)",
        expanded=False,
        on_change="rerun",
    )
    if full_pl.open:
        with full_pl:
            _render_pl_table(vis, filtered_months)


# ─────────────────────────────────────────────────────────────────────────────
# Anomaly detection banner
# ─────────────────────────────────────────────────────────────────────────────

def _render_anomaly_banner(cons_long: pd.DataFrame, months: list[str]) -> None:
    """Render a compact banner of anomaly chips above the KPI row.

    Only shown when material movements are detected in actual (populated) months.
    """
    flags = detect_anomalies(cons_long, months)
    if not flags:
        return  # nothing to show — keep the UI clean

    # Cap at 3 chips to avoid cluttering the page
    shown = flags[:3]
    chips_html = ""
    for f in shown:
        bg = "#FFEBE9" if f.level == "critical" else "#FFF8C5"
        border = "#CF222E" if f.level == "critical" else "#BF8700"
        icon = "⛔" if f.level == "critical" else "⚠️"
        text_color = "#CF222E" if f.level == "critical" else "#735C00"
        chips_html += (
            f"<span title='{f.detail}' style='"
            f"display:inline-block;padding:4px 10px;margin:0 6px 6px 0;"
            f"background:{bg};border:1px solid {border};border-radius:16px;"
            f"font-size:11px;font-weight:600;color:{text_color};"
            f"cursor:help;white-space:nowrap;'>{icon} {f.title}</span>"
        )
    extra = len(flags) - len(shown)
    if extra > 0:
        chips_html += (
            f"<span style='font-size:10px;color:{BLITZ_COLORS['text_secondary']};'"
            f"> +{extra} more</span>"
        )
    st.markdown(
        f"<div style='margin-bottom:10px;'>{chips_html}</div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Revenue trend with rolling average + annotations + reference line
# ─────────────────────────────────────────────────────────────────────────────

def _render_revenue_trend(
    cons_long: pd.DataFrame,
    filtered_months: list[str],
    cat_orders: dict,
) -> None:
    """Revenue trend chart: Actual + optional 3M rolling avg + historical avg reference + annotations."""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:4px;'>"
        f"Revenue Trend — Actuals &amp; Context</div>",
        unsafe_allow_html=True,
    )
    metric = "Total Gross Revenue"
    rev_df = (
        cons_long[cons_long["Metric"] == metric]
        .groupby(["Month", "MonthDate"], as_index=False)["Value"]
        .sum()
        .sort_values("MonthDate")
    )
    rev_df = rev_df[rev_df["Month"].isin(filtered_months)]
    if rev_df.empty:
        st.caption("No revenue data in selected range.")
        return

    rev_df = rev_df.copy()
    rev_df["Value"] = rev_df["Value"].apply(convert_value)

    # Rolling average (only if enough months)
    show_rolling = (
        len(filtered_months) >= 4
        and st.checkbox("Show 3M rolling avg", value=False, key="cons_rolling_avg")
    )
    rolling_df = None
    if show_rolling:
        rolling_df = compute_rolling_avg(cons_long, metric, filtered_months, window=3)
        if rolling_df is not None:
            rolling_df["Value"] = rolling_df["Value"].apply(convert_value)

    # Historical average reference line
    hist_avg = compute_historical_average(cons_long, metric, filtered_months)
    if hist_avg is not None:
        hist_avg = convert_value(hist_avg)

    # Annotations (peak / trough / biggest MoM)
    annotations = find_chart_annotations(cons_long, metric, filtered_months, max_annotations=2)
    if annotations:
        for ann in annotations:
            ann.value = convert_value(ann.value)

    fig = annotated_trend_chart(
        rev_df, "Month", "Value", None,
        rolling_avg_df=rolling_df,
        rolling_avg_label="3M Rolling Avg",
        annotations=annotations if annotations else None,
        reference_value=hist_avg if hist_avg is not None else None,
        reference_label="Period Avg",
        category_orders=cat_orders,
    )
    render_plotly_chart(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Unified driver analysis (P&L lines + entity + stream + client)
# ─────────────────────────────────────────────────────────────────────────────

def _render_driver_analysis(
    cons_long: pd.DataFrame,
    entity_frames: dict | None,
    master: pd.DataFrame | None,
    latest: str,
    prior: str,
) -> None:
    """Decision: What drove the revenue change and where did it come from?"""
    result = compute_revenue_drivers(cons_long, entity_frames, master, latest, prior)

    currency = get_active_currency()
    delta_color = BLITZ_COLORS["primary"] if result.total_delta >= 0 else "#CF222E"
    arrow = "▲" if result.total_delta >= 0 else "▼"
    border = BLITZ_COLORS["border"]

    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;'>"
        f"Revenue Driver Analysis — {prior} → {latest}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='font-size:13px;font-weight:700;color:{delta_color};margin-bottom:10px;'>"
        f"{arrow} Net Revenue Change: {fmt_display(result.total_delta)}</div>",
        unsafe_allow_html=True,
    )

    col_pl, col_drv = st.columns(2, gap="medium")

    # P&L line decomposition (left)
    with col_pl:
        st.markdown(
            f"<div style='font-size:11px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
            f"margin-bottom:6px;'>P&L Waterfall</div>",
            unsafe_allow_html=True,
        )
        cur_label = f"{latest} ({currency})"
        rows_html = ""
        for i, d in enumerate(result.pl_drivers):
            bg = "#FFFFFF" if i % 2 == 0 else BLITZ_COLORS["off_white"]
            delta = d["delta"]
            dcolor = BLITZ_COLORS["primary"] if delta >= 0 else "#CF222E"
            pct_str = f"{d['pct']:+.1f}%" if d["pct"] is not None else "—"
            cur_disp = fmt_display(d["cur"])
            delta_disp = fmt_display(delta)
            rows_html += (
                f"<tr style='background:{bg};'>"
                f"<td style='padding:5px 8px;font-size:11.5px;color:{BLITZ_COLORS['text_primary']};font-weight:500;'>{d['name']}</td>"
                f"<td style='padding:5px 8px;text-align:right;font-size:11.5px;font-weight:700;"
                f"color:{BLITZ_COLORS['text_primary']};'>{cur_disp}</td>"
                f"<td style='padding:5px 8px;text-align:right;font-size:11.5px;font-weight:600;"
                f"color:{dcolor};'>{delta_disp}</td>"
                f"<td style='padding:5px 8px;text-align:right;font-size:11px;color:{dcolor};'>{pct_str}</td>"
                f"</tr>"
            )
        st.markdown(
            f"<table style='width:100%;border-collapse:collapse;border:1px solid {border};"
            f"border-radius:8px;overflow:hidden;font-size:11px;'>"
            f"<thead><tr style='background:{BLITZ_COLORS['pale_blue']};'>"
            f"<th style='padding:5px 8px;text-align:left;font-size:10px;color:{BLITZ_COLORS['text_secondary']};'>Line</th>"
            f"<th style='padding:5px 8px;text-align:right;font-size:10px;color:{BLITZ_COLORS['text_secondary']};'>{cur_label}</th>"
            f"<th style='padding:5px 8px;text-align:right;font-size:10px;color:{BLITZ_COLORS['text_secondary']};'>Δ</th>"
            f"<th style='padding:5px 8px;text-align:right;font-size:10px;color:{BLITZ_COLORS['text_secondary']};'>Δ%</th>"
            f"</tr></thead><tbody>{rows_html}</tbody></table>",
            unsafe_allow_html=True,
        )

    # Top movers by stream + client (right)
    with col_drv:
        # Stream drivers
        if result.stream_drivers:
            st.markdown(
                f"<div style='font-size:11px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
                f"margin-bottom:4px;'>By Revenue Stream</div>",
                unsafe_allow_html=True,
            )
            top_streams = result.stream_drivers[:3] + list(reversed(result.stream_drivers[-2:]))
            seen: set[str] = set()
            unique_streams = []
            for d in top_streams:
                if d["name"] not in seen:
                    unique_streams.append(d)
                    seen.add(d["name"])
            s_html = ""
            for d in unique_streams[:5]:
                dcolor = BLITZ_COLORS["primary"] if d["delta"] >= 0 else "#CF222E"
                delta_disp = fmt_display(d["delta"])
                s_html += (
                    f"<div style='display:flex;justify-content:space-between;padding:4px 0;"
                    f"border-bottom:1px solid {border};font-size:11px;'>"
                    f"<span style='color:{BLITZ_COLORS['text_primary']};font-weight:500;"
                    f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:120px;'>{d['name']}</span>"
                    f"<span style='color:{dcolor};font-weight:700;'>{delta_disp:>12}</span>"
                    f"</div>"
                )
            st.markdown(
                f"<div style='background:#FFFFFF;border:1px solid {border};border-radius:8px;"
                f"padding:6px 10px;margin-bottom:10px;'>{s_html}</div>",
                unsafe_allow_html=True,
            )

        # Client movers
        pos = result.client_drivers_pos[:3]
        neg = result.client_drivers_neg[:3]
        if pos or neg:
            st.markdown(
                f"<div style='font-size:11px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
                f"margin-bottom:4px;'>Top Client Movers</div>",
                unsafe_allow_html=True,
            )
            c_html = ""
            for d in pos:
                delta_disp = fmt_display(d["delta"])
                c_html += (
                    f"<div style='display:flex;justify-content:space-between;padding:3px 0;"
                    f"border-bottom:1px solid {border};font-size:11px;'>"
                    f"<span style='color:{BLITZ_COLORS['text_primary']};white-space:nowrap;"
                    f"overflow:hidden;text-overflow:ellipsis;max-width:120px;'>{d['name']}</span>"
                    f"<span style='color:{BLITZ_COLORS['primary']};font-weight:700;'>+{delta_disp}</span>"
                    f"</div>"
                )
            for d in neg:
                delta_disp = fmt_display(d["delta"])
                c_html += (
                    f"<div style='display:flex;justify-content:space-between;padding:3px 0;"
                    f"border-bottom:1px solid {border};font-size:11px;'>"
                    f"<span style='color:{BLITZ_COLORS['text_primary']};white-space:nowrap;"
                    f"overflow:hidden;text-overflow:ellipsis;max-width:120px;'>{d['name']}</span>"
                    f"<span style='color:#CF222E;font-weight:700;'>{delta_disp}</span>"
                    f"</div>"
                )
            st.markdown(
                f"<div style='background:#FFFFFF;border:1px solid {border};border-radius:8px;"
                f"padding:6px 10px;'>{c_html}</div>",
                unsafe_allow_html=True,
            )
        elif not result.stream_drivers:
            st.markdown(
                f"<div style='padding:16px 12px;background:{BLITZ_COLORS['background']};"
                f"border:1px dashed {BLITZ_COLORS['border']};border-radius:8px;"
                f"font-size:12px;color:{BLITZ_COLORS['text_secondary']};'>"
                f"<b>Revenue Driver Analysis</b><br>"
                f"Client and stream-level driver data is not available from the current parsed workbook."
                f"</div>",
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Variance analysis table
# ─────────────────────────────────────────────────────────────────────────────

def _render_variance_table(
    cons_long: pd.DataFrame,
    latest: str,
    prior: str | None,
    comparison_label: str = "",
) -> None:
    """Decision: What changed and how material is it?"""
    currency = get_active_currency()
    compare_label = f" — {comparison_label}" if comparison_label else (f" vs {prior}" if prior else "")
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;'>"
        f"Variance Analysis — {latest}{compare_label}</div>",
        unsafe_allow_html=True,
    )
    if prior is None:
        st.caption("Select a prior period in the sidebar to enable variance analysis.")
        return

    _METRICS = [
        ("Total Gross Revenue", "Gross Revenue"),
        ("Net Revenue", "Net Revenue"),
        ("Gross Profit 2", "Gross Profit"),
        ("Total Operating Expenses", "Operating Expenses"),
        ("EBITDA", "EBITDA"),
        ("NET PROFIT/LOSS (Before Tax)", "Net Profit / Loss"),
    ]

    def _val(metric: str, month: str) -> float | None:
        rows = cons_long[(cons_long["Metric"] == metric) & (cons_long["Month"] == month)]
        return float(rows["Value"].sum()) if not rows.empty else None

    border = BLITZ_COLORS["border"]
    header_bg = BLITZ_COLORS["pale_blue"]

    thead = (
        f"<tr>"
        f"<th style='padding:6px 12px;text-align:left;font-size:11px;font-weight:600;"
        f"color:{BLITZ_COLORS['text_secondary']};width:28%;'>Metric</th>"
        f"<th style='padding:6px 12px;text-align:right;font-size:11px;font-weight:600;"
        f"color:{BLITZ_COLORS['text_secondary']};width:18%;'>{latest} ({currency})</th>"
        f"<th style='padding:6px 12px;text-align:right;font-size:11px;font-weight:600;"
        f"color:{BLITZ_COLORS['text_secondary']};width:18%;'>{prior} ({currency})</th>"
        f"<th style='padding:6px 12px;text-align:right;font-size:11px;font-weight:600;"
        f"color:{BLITZ_COLORS['text_secondary']};width:18%;'>Δ Abs</th>"
        f"<th style='padding:6px 12px;text-align:right;font-size:11px;font-weight:600;"
        f"color:{BLITZ_COLORS['text_secondary']};width:10%;'>Δ %</th>"
        f"<th style='padding:6px 12px;text-align:center;font-size:11px;font-weight:600;"
        f"color:{BLITZ_COLORS['text_secondary']};width:8%;'>Dir</th>"
        f"</tr>"
    )

    tbody = ""
    for i, (metric_key, display) in enumerate(_METRICS):
        cur_raw = _val(metric_key, latest)
        pri_raw = _val(metric_key, prior)
        bg = "#FFFFFF" if i % 2 == 0 else BLITZ_COLORS["off_white"]

        if cur_raw is None:
            tbody += (
                f"<tr style='background:{bg};'>"
                f"<td style='padding:6px 12px;font-size:12px;font-weight:500;"
                f"color:{BLITZ_COLORS['text_primary']};border-bottom:1px solid {border};'>{display}</td>"
                f"<td colspan='5' style='padding:6px 12px;text-align:center;font-size:11px;"
                f"color:{BLITZ_COLORS['text_secondary']};border-bottom:1px solid {border};'>N/A</td></tr>"
            )
            continue

        # Apply currency conversion for display
        cur_disp = fmt_display(cur_raw)
        pri_disp = fmt_display(pri_raw) if pri_raw is not None else "—"

        # Compute delta in raw IDR, then convert for display
        delta_abs_raw = (cur_raw - pri_raw) if pri_raw is not None else None
        delta_pct = ((cur_raw - pri_raw) / abs(pri_raw) * 100) if pri_raw is not None and pri_raw != 0 else None

        if delta_abs_raw is not None:
            is_cost = "expense" in display.lower() or "cogs" in display.lower()
            is_good = (delta_abs_raw >= 0) if not is_cost else (delta_abs_raw <= 0)
            delta_color = BLITZ_COLORS["primary"] if is_good else "#CF222E"
            arrow = "▲" if delta_abs_raw >= 0 else "▼"
            delta_abs_disp = fmt_display(delta_abs_raw)
            delta_pct_str = f"{delta_pct:+.1f}%" if delta_pct is not None else "—"
            dir_badge = (
                f"<span style='background:{delta_color};color:#FFFFFF;padding:1px 5px;"
                f"border-radius:4px;font-size:10px;font-weight:700;'>{arrow}</span>"
            )
        else:
            delta_color = BLITZ_COLORS["text_secondary"]
            delta_abs_disp = "—"
            delta_pct_str = "—"
            dir_badge = "—"

        tbody += (
            f"<tr style='background:{bg};'>"
            f"<td style='padding:6px 12px;font-size:12px;font-weight:600;"
            f"color:{BLITZ_COLORS['text_primary']};border-bottom:1px solid {border};'>{display}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-size:12px;font-weight:700;"
            f"color:{BLITZ_COLORS['text_primary']};border-bottom:1px solid {border};'>{cur_disp}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-size:12px;"
            f"color:{BLITZ_COLORS['text_secondary']};border-bottom:1px solid {border};'>{pri_disp}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-size:12px;font-weight:600;"
            f"color:{delta_color};border-bottom:1px solid {border};'>{delta_abs_disp}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-size:12px;font-weight:600;"
            f"color:{delta_color};border-bottom:1px solid {border};'>{delta_pct_str}</td>"
            f"<td style='padding:6px 12px;text-align:center;border-bottom:1px solid {border};'>{dir_badge}</td>"
            f"</tr>"
        )

    st.markdown(
        f"<div style='border:1px solid {border};border-radius:8px;overflow:hidden;'>"
        f"<table style='width:100%;border-collapse:collapse;'>"
        f"<thead style='background:{header_bg};border-bottom:2px solid {border};'>"
        f"{thead}</thead><tbody>{tbody}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # Budget vs Actual placeholder
    st.markdown(
        f"<div style='margin-top:6px;padding:7px 12px;"
        f"background:{BLITZ_COLORS['background']};border:1px dashed {BLITZ_COLORS['border']};"
        f"border-radius:6px;font-size:11px;color:{BLITZ_COLORS['text_secondary']};'>"
        f"📋 <b>Budget vs Actual:</b> Budget data not available in the current workbook. "
        f"Upload a workbook containing a Budget sheet to enable this comparison."
        f"</div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# P&L Waterfall
# ─────────────────────────────────────────────────────────────────────────────

def _render_waterfall(cons_long: pd.DataFrame, latest_month: str) -> None:
    """Decision: What caused the final profit/loss result?"""
    currency = get_active_currency()
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f"P&amp;L Bridge — {latest_month} ({currency})</div>",
        unsafe_allow_html=True,
    )
    latest_data = pd.DataFrame(cons_long[cons_long["Month"] == latest_month])

    labels: list[str] = []
    raw_values: list[float] = []
    for metric_key, display_name in WATERFALL_STEPS:
        rows = pd.DataFrame(latest_data[latest_data["Metric"] == metric_key])
        if not rows.empty:
            labels.append(display_name)
            raw_values.append(float(rows["Value"].sum(skipna=True)))

    if len(labels) < 2:
        st.caption("Insufficient waterfall metrics for this month.")
        return

    # Apply currency conversion to all values before computing steps
    converted_values = [convert_value(v) for v in raw_values]

    subtotal_names = {"Gross Profit", "EBITDA", "Net Profit"}
    measures: list[str] = []
    waterfall_values: list[float] = []
    cumulative = 0.0
    for i, (lbl, val) in enumerate(zip(labels, converted_values)):
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

    # Build the waterfall with currency-aware bar labels
    fig = waterfall_chart(labels, waterfall_values, measures=measures)
    render_plotly_chart(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Margin intelligence
# ─────────────────────────────────────────────────────────────────────────────

def _render_margin_intelligence(
    raw: pd.DataFrame,
    filtered_months: list[str],
    cat_orders: dict,
) -> None:
    """Decision: Is profitability improving or deteriorating, and how fast?"""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f"Margin Trend — Improving or Deteriorating?</div>",
        unsafe_allow_html=True,
    )
    ratios = parse_ratios(raw, "Consolidated")
    if ratios.empty:
        st.caption("No margin rows found in sheet.")
        return

    keep = {"gross margin %", "ebitda margin %", "net margin %", "margin %"}
    margin_df = pd.DataFrame(
        ratios[ratios["Metric"].str.lower().isin(keep)]
    )
    margin_df = pd.DataFrame(margin_df[margin_df["Month"].isin(filtered_months)])
    if margin_df.empty:
        st.caption("No margin data in selected range.")
        return

    label_map = {
        "Gross Margin %": "Gross Margin", "gross margin %": "Gross Margin",
        "EBITDA Margin %": "EBITDA Margin", "ebitda margin %": "EBITDA Margin",
        "Net Margin %": "Net Margin", "net margin %": "Net Margin",
        "Margin %": "Margin", "margin %": "Margin",
    }
    margin_df = margin_df.copy()
    margin_df["Metric"] = margin_df["Metric"].map(label_map).fillna(margin_df["Metric"])

    fig = margin_multi_line(
        margin_df, "Month", "Value", "Metric",
        category_orders=cat_orders,
    )
    render_plotly_chart(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Cost efficiency trend
# ─────────────────────────────────────────────────────────────────────────────

def _render_cost_ratio_trend(
    cons_long: pd.DataFrame,
    filtered_months: list[str],
    cat_orders: dict,
) -> None:
    """Decision: Are costs eating into revenue more or less over time?"""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f"Cost Efficiency — COGS &amp; OpEx as % of Revenue</div>",
        unsafe_allow_html=True,
    )
    rev_df = cons_long[cons_long["Metric"] == "Total Gross Revenue"][["Month", "Value"]].rename(
        columns={"Value": "Revenue"}
    )
    cogs_df = cons_long[cons_long["Metric"] == "Total COGS"][["Month", "Value"]].rename(
        columns={"Value": "COGS"}
    )
    opex_df = cons_long[cons_long["Metric"] == "Total Operating Expenses"][["Month", "Value"]].rename(
        columns={"Value": "OpEx"}
    )

    merged = rev_df.merge(cogs_df, on="Month", how="inner").merge(opex_df, on="Month", how="inner")
    merged = pd.DataFrame(merged[merged["Month"].isin(filtered_months)])
    if merged.empty or (merged["Revenue"] == 0).all():
        st.caption("Insufficient data to compute cost ratios.")
        return

    ratio_records = []
    for _, row in merged.iterrows():
        rev = row["Revenue"]
        if rev == 0:
            continue
        ratio_records.append({"Month": row["Month"], "Metric": "COGS %", "Value": row["COGS"] / rev})
        ratio_records.append({"Month": row["Month"], "Metric": "OpEx %", "Value": row["OpEx"] / rev})

    ratio_df = pd.DataFrame(ratio_records)
    if ratio_df.empty:
        st.caption("No ratio data available.")
        return

    fig = margin_multi_line(
        ratio_df, "Month", "Value", "Metric",
        category_orders=cat_orders,
    )
    render_plotly_chart(fig)


# ─────────────────────────────────────────────────────────────────────────────
# OpEx breakdown — comparison table with prior period
# ─────────────────────────────────────────────────────────────────────────────

def _render_opex_breakdown(
    vis: pd.DataFrame,
    latest_month: str,
    prior_month: str | None,
    cons_long: pd.DataFrame,
) -> None:
    """Decision: What is eating our operating budget?"""
    currency = get_active_currency()
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f"Operating Costs — What is eating our budget? ({latest_month})</div>",
        unsafe_allow_html=True,
    )
    month_data = pd.DataFrame(vis[vis["Month"] == latest_month])
    opex_data = (
        month_data[month_data["Metric"].isin(OPEX_LINE_ITEMS)]
        .groupby("Metric", as_index=False)["Value"]
        .sum()
        .sort_values("Value", ascending=False)
    )
    if opex_data.empty:
        # ── TEMPORARY DIAGNOSTIC (remove after investigation) ──────────────────
        with st.expander("🔍 DIAGNOSTIC: All metrics in parsed data for this month", expanded=True):
            all_metrics = sorted(month_data["Metric"].unique().tolist())
            st.caption(f"Total metrics found in cons_long for **{latest_month}**: {len(all_metrics)}")
            st.write("**All metric names (exact strings from workbook):**")
            for m in all_metrics:
                match = "✅ IN OPEX_LINE_ITEMS" if m in OPEX_LINE_ITEMS else ""
                st.text(f"  • {m!r}  {match}")
            st.write("**OPEX_LINE_ITEMS we are looking for:**")
            for m in OPEX_LINE_ITEMS:
                st.text(f"  • {m!r}")
        # ── END DIAGNOSTIC ─────────────────────────────────────────────────────
        st.caption("No OpEx line items found.")
        return

    if prior_month:
        prior_data = pd.DataFrame(cons_long[cons_long["Month"] == prior_month])
        prior_opex = (
            prior_data[prior_data["Metric"].isin(OPEX_LINE_ITEMS)]
            .groupby("Metric", as_index=False)["Value"]
            .sum()
            .rename(columns={"Value": "Prior"})
        )
        merged = opex_data.merge(prior_opex, on="Metric", how="left").fillna(0)

        border = BLITZ_COLORS["border"]
        thead = (
            f"<tr style='background:{BLITZ_COLORS['pale_blue']};'>"
            f"<th style='padding:7px 10px;text-align:left;font-size:11px;font-weight:600;"
            f"color:{BLITZ_COLORS['text_secondary']};width:35%;'>Cost Item</th>"
            f"<th style='padding:7px 8px;text-align:right;font-size:11px;font-weight:600;"
            f"color:{BLITZ_COLORS['text_secondary']};width:20%;'>{latest_month} ({currency})</th>"
            f"<th style='padding:7px 8px;text-align:right;font-size:11px;font-weight:600;"
            f"color:{BLITZ_COLORS['text_secondary']};width:20%;'>{prior_month} ({currency})</th>"
            f"<th style='padding:7px 8px;text-align:right;font-size:11px;font-weight:600;"
            f"color:{BLITZ_COLORS['text_secondary']};width:15%;'>Δ</th>"
            f"<th style='padding:7px 8px;text-align:right;font-size:11px;font-weight:600;"
            f"color:{BLITZ_COLORS['text_secondary']};width:10%;'>Δ %</th>"
            f"</tr>"
        )
        tbody = ""
        total_cur = merged["Value"].sum()
        for i, (_, row) in enumerate(merged.iterrows()):
            bg = "#FFFFFF" if i % 2 == 0 else BLITZ_COLORS["off_white"]
            delta_raw = row["Value"] - row["Prior"]
            pct = (delta_raw / abs(row["Prior"]) * 100) if row["Prior"] != 0 else None
            delta_color = "#CF222E" if delta_raw > 0 else BLITZ_COLORS["primary"]
            pct_str = f"{pct:+.1f}%" if pct is not None else "—"
            share = row["Value"] / total_cur * 100 if total_cur > 0 else 0
            cur_disp = fmt_display(row["Value"])
            pri_disp = fmt_display(row["Prior"])
            delta_disp = fmt_display(delta_raw)
            tbody += (
                f"<tr style='background:{bg};'>"
                f"<td style='padding:7px 10px;font-size:12px;font-weight:500;"
                f"color:{BLITZ_COLORS['text_primary']};'>{row['Metric']}"
                f"<span style='font-size:10px;color:{BLITZ_COLORS['text_secondary']};margin-left:4px;'>"
                f"({share:.0f}%)</span></td>"
                f"<td style='padding:7px 8px;text-align:right;font-size:12px;font-weight:700;"
                f"color:{BLITZ_COLORS['text_primary']};'>{cur_disp}</td>"
                f"<td style='padding:7px 8px;text-align:right;font-size:12px;"
                f"color:{BLITZ_COLORS['text_secondary']};'>{pri_disp}</td>"
                f"<td style='padding:7px 8px;text-align:right;font-size:12px;font-weight:600;"
                f"color:{delta_color};'>{delta_disp}</td>"
                f"<td style='padding:7px 8px;text-align:right;font-size:12px;font-weight:600;"
                f"color:{delta_color};'>{pct_str}</td>"
                f"</tr>"
            )
        st.markdown(
            f"<table style='width:100%;border-collapse:collapse;border:1px solid {border};"
            f"border-radius:8px;overflow:hidden;'>"
            f"<thead>{thead}</thead><tbody>{tbody}</tbody></table>",
            unsafe_allow_html=True,
        )
    else:
        display_opex = opex_data.copy()
        display_opex["Value"] = display_opex["Value"].apply(convert_value)
        fig = comparison_bar_chart(display_opex, x="Metric", y="Value", title="")
        render_plotly_chart(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Revenue vs Margin combo chart (optional enhancement)
# ─────────────────────────────────────────────────────────────────────────────

def _build_combo_data(
    cons_long: pd.DataFrame,
    filtered_months: list[str],
) -> pd.DataFrame | None:
    """Build a merged DataFrame with Revenue and Margin% columns per month.

    Returns None if fewer than 3 actual data points exist (chart not meaningful).
    """
    rev = (
        cons_long[cons_long["Metric"] == "Total Gross Revenue"]
        .groupby(["Month", "MonthDate"], as_index=False)["Value"]
        .sum()
        .rename(columns={"Value": "Revenue"})
    )
    gp = (
        cons_long[cons_long["Metric"].isin(["Gross Profit 2", "Gross Profit 1"])]
        .groupby(["Month", "MonthDate"], as_index=False)["Value"]
        .sum()
        .rename(columns={"Value": "GrossProfit"})
    )
    merged = rev.merge(gp, on=["Month", "MonthDate"], how="inner")
    merged = merged[merged["Month"].isin(filtered_months)].copy()
    merged = merged[merged["Revenue"] != 0].copy()
    if len(merged) < 3:
        return None
    merged["MarginPct"] = merged["GrossProfit"] / merged["Revenue"]
    merged = merged.sort_values("MonthDate")
    return merged


def _render_revenue_margin_combo(
    combo_df: pd.DataFrame,
    cat_orders: dict,
) -> None:
    """Dual-axis combo: Revenue bars (left) + Gross Margin % line (right)."""
    import plotly.graph_objects as go
    from streamlit_app.components.charts import _apply_base_layout, _apply_xaxis_months

    currency = get_active_currency()
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f"Revenue vs Margin — Monthly Overview ({currency})</div>",
        unsafe_allow_html=True,
    )

    months = combo_df["Month"].tolist()
    rev_converted = [convert_value(v) for v in combo_df["Revenue"].tolist()]
    margin_pct = combo_df["MarginPct"].tolist()

    fig = go.Figure()

    # Revenue bars
    fig.add_trace(go.Bar(
        x=months,
        y=rev_converted,
        name=f"Revenue ({currency})",
        marker_color=BLITZ_COLORS["primary"],
        marker_line_width=0,
        opacity=0.80,
        yaxis="y",
        hovertemplate="<b>%{x}</b><br>Revenue: %{y:,.1f}<extra></extra>",
    ))

    # Gross Margin % line on secondary axis
    fig.add_trace(go.Scatter(
        x=months,
        y=margin_pct,
        name="Gross Margin %",
        mode="lines+markers",
        line=dict(color=BLITZ_COLORS["deep_blue"], width=2.5),
        marker=dict(size=7, color=BLITZ_COLORS["deep_blue"]),
        yaxis="y2",
        hovertemplate="<b>%{x}</b><br>Gross Margin: %{y:.1%}<extra></extra>",
    ))

    _apply_base_layout(fig)
    fig.update_layout(
        yaxis=dict(
            title=f"Revenue ({currency})",
            tickprefix="" if currency == "USD" else "Rp",
            tickformat="~s",
            showgrid=True,
            gridcolor="rgba(226,226,226,0.5)",
        ),
        yaxis2=dict(
            title="Gross Margin %",
            overlaying="y",
            side="right",
            tickformat=".0%",
            showgrid=False,
            range=[0, max(margin_pct) * 1.4] if margin_pct else [0, 1],
        ),
        bargap=0.3,
        showlegend=True,
        hovermode="x unified",
    )
    month_labels = cat_orders.get("Month", months)
    _apply_xaxis_months(fig, len(month_labels), month_labels)
    render_plotly_chart(fig)


# ─────────────────────────────────────────────────────────────────────────────
# OpEx composition donut (optional enhancement)
# ─────────────────────────────────────────────────────────────────────────────

def _build_opex_donut_data(
    vis: pd.DataFrame,
    latest_month: str,
) -> pd.DataFrame | None:
    """Build OpEx category data for the donut. Returns None if all zero or empty."""
    month_data = vis[vis["Month"] == latest_month]
    opex = (
        month_data[month_data["Metric"].isin(OPEX_LINE_ITEMS)]
        .groupby("Metric", as_index=False)["Value"]
        .sum()
    )
    opex = opex[opex["Value"] > 0].copy()
    if opex.empty or opex["Value"].sum() == 0:
        return None
    return opex


def _render_opex_donut(
    opex_df: pd.DataFrame,
    latest_month: str,
) -> None:
    """Donut chart showing OpEx category composition for the latest actual month."""
    currency = get_active_currency()
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px;'>"
        f"OpEx Composition — {latest_month} ({currency})</div>",
        unsafe_allow_html=True,
    )
    # Apply currency conversion to values for display
    display_df = opex_df.copy()
    display_df["DisplayValue"] = display_df["Value"].apply(convert_value)
    fig = donut_chart(
        display_df,
        names="Metric",
        values="DisplayValue",
    )
    # Currency-aware hover
    prefix = "$" if currency == "USD" else "Rp"
    fig.update_traces(
        hovertemplate=(
            f"<b>%{{label}}</b><br>"
            f"Amount: {prefix}%{{value:,.1f}}<br>"
            f"Share: %{{percent}}<extra></extra>"
        )
    )
    render_plotly_chart(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Full P&L table
# ─────────────────────────────────────────────────────────────────────────────

def _render_pl_table(vis: pd.DataFrame, filtered_months: list[str]) -> None:
    """Render the full P&L pivot table with conditional formatting."""
    pivot = vis.pivot_table(index="Metric", columns="Month", values="Value", aggfunc="sum")
    pivot = pivot[[m for m in filtered_months if m in pivot.columns]]

    def _style_negatives(v: object) -> str:
        try:
            return "color: #CF222E; font-weight: 600;" if float(v) < 0 else ""  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return ""

    styled = pivot.style.map(_style_negatives).format(
        lambda v: fmt_idr_full(v) if isinstance(v, (int, float)) else v
    )
    st.dataframe(styled, width="stretch")
