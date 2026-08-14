"""Financial Control Center — Data Health & Reconciliation Monitoring."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from streamlit_app.components.charts import render_plotly_chart
from streamlit_app.constants import (
    BLITZ_COLORS,
    ENTITY_SUMMARY_SHEETS,
    TIE_OUT_FLAG_THRESHOLD,
    fmt_idr,
    fmt_idr_full,
)
from streamlit_app.components.filters import (
    get_filtered_months,
    render_active_filter_bar,
    render_empty_state,
)
from streamlit_app.data.parsers import (
    KIND_DELTA,
    parse_master,
    parse_pl_sheet,
    parse_tie_out,
    tie_out_deltas,
)
from streamlit_app.data.periods import actual_months
from streamlit_app.data.reconciliation import (
    BRIDGE_MATERIALITY_IDR,
    coverage_gaps,
    master_vs_pl_bridge,
    unreconciled_summary,
)
from streamlit_app.components.ui import render_page_header

# ---------------------------------------------------------------------------
# Semantic colours — used throughout
# ---------------------------------------------------------------------------
_C_HEALTHY = "#1A7F37"
_C_ATTENTION = "#BF8700"
_C_CRITICAL = "#CF222E"
_C_HEALTHY_BG = "#DAFBE1"
_C_ATTENTION_BG = "#FFF8C5"
_C_CRITICAL_BG = "#FFEBE9"

# Severity thresholds (multiples of the base threshold)
_CRITICAL_MULT = 10   # > 10× threshold → Critical
_ATTENTION_MULT = 1   # > 1× threshold  → Attention


# ---------------------------------------------------------------------------
# Label classification helpers
# ---------------------------------------------------------------------------

_LABEL_MAP: dict[str, str] = {
    # Maps raw tie-out row labels → human-friendly reconciliation category
    "master": "Client Revenue vs Revenue Tracker",
    "tracker": "Revenue Tracker vs Group P&L",
    "pl feed": "Revenue Tracker vs Group P&L",
    "group p&l": "Revenue Tracker vs Group P&L",
    "consolidated": "Group P&L vs Consolidated Summary",
    "blitz": "Blitz Entity",
    "borzo": "Borzo Entity",
    "thelorry": "TheLorry Entity",
    "the lorry": "TheLorry Entity",
    "adjustment": "Manual Adjustment",
    "manual": "Manual Adjustment",
    "client map": "Client Mapping",
}

_ROOT_CAUSE_MAP: dict[str, str] = {
    "master": "Client Mapping Variance",
    "tracker": "Revenue Tracker Variance",
    "pl feed": "Revenue Tracker Variance",
    "group p&l": "Revenue Tracker Variance",
    "consolidated": "Consolidation Variance",
    "adjustment": "Manual Adjustment",
    "manual": "Manual Adjustment",
    "blitz": "Entity-Level Variance",
    "borzo": "Entity-Level Variance",
    "thelorry": "Entity-Level Variance",
    "the lorry": "Entity-Level Variance",
    "client map": "Client Mapping Variance",
}


def _classify_label(raw: str) -> str:
    """Return a human-readable reconciliation category for a raw label."""
    low = raw.lower()
    for key, label in _LABEL_MAP.items():
        if key in low:
            return label
    return "Other Reconciliation"


def _classify_root_cause(raw: str) -> str:
    """Return likely root cause for a raw label — only when clearly supported."""
    low = raw.lower()
    for key, cause in _ROOT_CAUSE_MAP.items():
        if key in low:
            return cause
    return "Other Reconciliation Issue"


def _severity(abs_delta: float, threshold: float) -> str:
    if abs_delta > threshold * _CRITICAL_MULT:
        return "Critical"
    if abs_delta > threshold:
        return "Attention"
    return "Healthy"


def _severity_color(sev: str) -> str:
    return {"Critical": _C_CRITICAL, "Attention": _C_ATTENTION, "Healthy": _C_HEALTHY}.get(sev, _C_HEALTHY)


def _severity_bg(sev: str) -> str:
    return {"Critical": _C_CRITICAL_BG, "Attention": _C_ATTENTION_BG, "Healthy": _C_HEALTHY_BG}.get(sev, _C_HEALTHY_BG)


def _severity_icon(sev: str) -> str:
    return {"Critical": "🔴", "Attention": "🟡", "Healthy": "🟢"}.get(sev, "⚪")


def get_overall_health_status(sheets: dict[str, pd.DataFrame]) -> str | None:
    """Return the existing reconciliation health classification for shared UI."""
    raw = sheets.get("TIE-OUT CHECK")
    if raw is None:
        return None

    df = tie_out_deltas(raw)
    if df.empty:
        return None

    # The header badge is deliberately NOT driven by the user's threshold
    # slider. Previously it read `health_threshold_slider`, so sliding the
    # Data Health control to Rp10M turned the global badge green on every tab.
    abs_deltas = df["Delta"].abs()
    if (abs_deltas > TIE_OUT_FLAG_THRESHOLD * _CRITICAL_MULT).any():
        return "Critical"
    if (abs_deltas > TIE_OUT_FLAG_THRESHOLD).any():
        return "Attention"
    return "Healthy"


# ---------------------------------------------------------------------------
# Main render entry point
# ---------------------------------------------------------------------------

def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the Financial Control Center tab."""
    render_page_header(
        "Data health",
        "Trust the reported numbers: monitor reconciliation exceptions, their likely causes, and data-quality risks.",
        eyebrow="Financial controls",
    )
    raw = sheets.get("TIE-OUT CHECK")
    if raw is None:
        st.warning(":material/warning: 'TIE-OUT CHECK' sheet not found in this workbook.")
        return

    tie_out_all = parse_tie_out(raw)
    if tie_out_all.empty:
        st.warning(
            "Could not parse reconciliation data from 'TIE-OUT CHECK'. "
            "Check that month headers appear in the first 10 rows."
        )
        return

    # Only Δ-marked rows are variances. Component rows (MASTER total, Tracker
    # total, Direct P&L total) and adjustment memos are context — reporting them
    # as exceptions made a Rp2.98B revenue TOTAL the month's largest "variance".
    df = tie_out_all[tie_out_all["Kind"] == KIND_DELTA].copy()
    if df.empty:
        st.warning(
            "No Δ reconciliation rows found on 'TIE-OUT CHECK'. "
            "Variances are identified by a leading Δ in the row label."
        )
        return

    # Enrich with derived columns — no changes to underlying values
    df = _enrich(df)

    all_months = df["Month"].dropna().unique().tolist()
    filtered_months = get_filtered_months(all_months)
    if not filtered_months:
        render_empty_state(
            title="No months in the selected date range.",
            suggestion="Adjust the month range slider in the sidebar to include at least one period.",
            icon="📅",
            show_reset=True,
            key_suffix="health",
        )
        return

    render_active_filter_bar(filtered_months)

    # Filter the tie-out data to only the selected months
    df = pd.DataFrame(df[df["Month"].isin(filtered_months)])

    # Threshold control (sidebar-style inline control)
    threshold = _render_threshold_control()

    # ── Section 0: Derived checks that cannot go stale ───────────────────
    _render_derived_checks(sheets, filtered_months)

    # ── Section 1: Data Trust Header ─────────────────────────────────────
    _render_trust_header(df, threshold)

    # ── Section 2: Reconciliation Scorecard ──────────────────────────────
    _render_scorecard(df, threshold)

    # ── Section 3: Top Exceptions ─────────────────────────────────────────
    _render_exceptions(df, threshold)

    # ── Section 4: Monthly Heatmap ────────────────────────────────────────
    _render_heatmap(df, threshold)

    # ── Section 5: Root-Cause Grouping ────────────────────────────────────
    _render_root_cause(df, threshold)

    # ── Section 6: Data Quality KPIs ──────────────────────────────────────
    _render_data_quality(sheets)

    # ── Section 7: Drill-Down ─────────────────────────────────────────────
    _render_drilldown(df, threshold)


# ---------------------------------------------------------------------------
# Section 0 — Derived checks (computed from the workbook, cannot go stale)
# ---------------------------------------------------------------------------

def _render_derived_checks(
    sheets: dict[str, pd.DataFrame],
    filtered_months: list[str],
) -> None:
    """MASTER-vs-P&L revenue bridge and source coverage gaps.

    The TIE-OUT CHECK sheet is maintained by hand and lags the P&L. These two
    checks are derived from the parsed workbook, so they always reflect the file
    that is actually loaded.
    """
    cons_raw = sheets.get("Consolidated Summary")
    master_raw = sheets.get("MASTER")
    if cons_raw is None or master_raw is None:
        return

    cons_long = parse_pl_sheet(cons_raw, "Consolidated")
    master_df, missing = parse_master(master_raw)
    if cons_long.empty or missing or master_df.empty:
        return

    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.07em;text-transform:uppercase;margin:6px 0 10px;'>"
        f":material/rule: Client detail vs Group P&amp;L</div>",
        unsafe_allow_html=True,
    )

    # ── Coverage: months the P&L has closed that a source has not ────────
    closed = actual_months(cons_long)
    tie_out_df = parse_tie_out(sheets.get("TIE-OUT CHECK", pd.DataFrame()))
    for gap in coverage_gaps(closed, master_df, tie_out_df):
        st.markdown(
            f"<div style='background:{_C_ATTENTION_BG};border:1.5px solid {_C_ATTENTION};"
            f"border-radius:8px;padding:12px 18px;margin-bottom:8px;font-size:12px;"
            f"color:#735C00;'><strong>⚠️ Coverage gap — {gap.source}</strong><br>{gap.detail}</div>",
            unsafe_allow_html=True,
        )

    # ── Bridge: MASTER client revenue vs Consolidated Total Gross Revenue ─
    months = [m for m in filtered_months if m in closed] or closed
    bridge = master_vs_pl_bridge(master_df, cons_long, months=months)
    if bridge.empty:
        return

    border = BLITZ_COLORS["border"]
    head = (
        "<tr>"
        + "".join(
            f"<th style='padding:6px 12px;text-align:{a};font-size:11px;font-weight:700;"
            f"color:{BLITZ_COLORS['text_secondary']};white-space:nowrap;'>{h}</th>"
            for h, a in [
                ("Month", "left"), ("Client breakdown (MASTER)", "right"),
                ("Group P&L revenue", "right"), ("Variance", "right"), ("% of P&L", "right"),
            ]
        )
        + "</tr>"
    )
    body = ""
    for i, (_, row) in enumerate(bridge.iterrows()):
        material = bool(row["AbsDelta"] >= BRIDGE_MATERIALITY_IDR)
        colour = _C_CRITICAL if material else _C_HEALTHY
        stripe = "#FFFFFF" if i % 2 == 0 else BLITZ_COLORS["off_white"]
        pct = row["PctOfPL"]
        pct_txt = "—" if pd.isna(pct) else f"{pct * 100:+.2f}%"
        body += (
            f"<tr style='background:{stripe};'>"
            f"<td style='padding:6px 12px;font-size:12px;font-weight:600;border-bottom:1px solid {border};'>{row['Month']}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-size:12px;border-bottom:1px solid {border};'>{fmt_idr_full(row['MasterRevenue'] or 0)}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-size:12px;border-bottom:1px solid {border};'>{fmt_idr_full(row['PLRevenue'] or 0)}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-size:12px;font-weight:700;color:{colour};border-bottom:1px solid {border};'>{fmt_idr_full(row['Delta'])}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-size:12px;color:{colour};border-bottom:1px solid {border};'>{pct_txt}</td>"
            f"</tr>"
        )

    st.markdown(
        f"<table style='width:100%;border-collapse:collapse;margin-bottom:6px;'>"
        f"<thead>{head}</thead><tbody>{body}</tbody></table>",
        unsafe_allow_html=True,
    )
    gross = float(bridge["AbsDelta"].sum())
    net = float(bridge["Delta"].sum())
    st.caption(
        f"Gross unreconciled {fmt_idr(gross)} across {len(bridge)} month(s); "
        f"net {fmt_idr(net)}. Computed from the loaded workbook — independent of "
        f"the TIE-OUT CHECK sheet."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add Category, RootCause, AbsDelta, Severity columns to the tie-out df."""
    df = df.copy()
    df["Category"] = df["Label"].apply(_classify_label)
    df["RootCause"] = df["Label"].apply(_classify_root_cause)
    df["AbsDelta"] = df["Delta"].abs()
    return df


def _render_threshold_control() -> float:
    """Render the variance threshold slider and return the chosen value."""
    col_thresh, col_note = st.columns([2, 3], gap="medium")
    with col_thresh:
        threshold = st.slider(
            "Variance threshold (IDR)",
            min_value=0,
            max_value=10_000_000,
            value=int(TIE_OUT_FLAG_THRESHOLD),
            step=100_000,
            format="Rp%d",
            key="health_threshold_slider",
            help="Variances above this amount are flagged. Critical = 10× threshold.",
        )
    with col_note:
        st.markdown(
            f"<div style='padding-top:28px;font-size:11px;color:{BLITZ_COLORS['text_secondary']};'>"
            f"🟢 Healthy = below Rp{threshold:,.0f} &nbsp;&nbsp; "
            f"🟡 Attention = above Rp{threshold:,.0f} &nbsp;&nbsp; "
            f"🔴 Critical = above Rp{threshold * 10:,.0f}</div>",
            unsafe_allow_html=True,
        )
    return float(threshold)


# ---------------------------------------------------------------------------
# Section 1 — Data Trust Header
# ---------------------------------------------------------------------------

def _render_trust_header(df: pd.DataFrame, threshold: float) -> None:
    """Prominent health summary — CFO's first read."""
    summary = unreconciled_summary(df, threshold)
    total = int(summary["total_rows"])
    flagged = int(summary["flagged"])
    below = int(summary["below_threshold"])
    critical = int((df["AbsDelta"] > threshold * _CRITICAL_MULT).sum())
    passing = int(summary["zero"])
    largest = float(summary["largest"])

    # Overall status. "All Checks Passing" is only claimed when every variance
    # is genuinely zero — not merely below the user's threshold. The previous
    # wording let a raised slider report unreconciled books as clean.
    if critical > 0:
        status_label = "Critical — Immediate Attention Required"
        status_color = _C_CRITICAL
        status_bg = _C_CRITICAL_BG
        status_icon = "⛔"
    elif flagged > 0:
        status_label = "Attention Required"
        status_color = _C_ATTENTION
        status_bg = _C_ATTENTION_BG
        status_icon = "⚠️"
    elif below > 0:
        status_label = f"Ties out within tolerance — {below} variance(s) below threshold"
        status_color = _C_ATTENTION
        status_bg = _C_ATTENTION_BG
        status_icon = "⚠️"
    else:
        status_label = "Healthy — All Checks Passing"
        status_color = _C_HEALTHY
        status_bg = _C_HEALTHY_BG
        status_icon = "✅"

    pct_pass = (passing / total * 100) if total > 0 else 100.0
    bar_w = int(min(100, pct_pass))
    bar_color = _C_HEALTHY if critical == 0 and flagged == 0 and below == 0 else (
        _C_CRITICAL if critical > 0 else _C_ATTENTION
    )

    st.markdown(
        f"""
        <div style='background:{status_bg};border:2px solid {status_color};
            border-radius:12px;padding:20px 28px;margin-bottom:20px;'>
          <div style='display:flex;align-items:center;gap:12px;margin-bottom:12px;'>
            <span style='font-size:28px;'>{status_icon}</span>
            <div>
              <div style='font-size:11px;font-weight:700;letter-spacing:0.1em;
                text-transform:uppercase;color:{status_color};margin-bottom:2px;'>
                FINANCIAL DATA HEALTH</div>
              <div style='font-size:20px;font-weight:800;color:{status_color};'>
                {status_label}</div>
            </div>
          </div>
          <div style='display:flex;gap:32px;flex-wrap:wrap;margin-bottom:14px;'>
            <div>
              <div style='font-size:26px;font-weight:800;color:{BLITZ_COLORS["text_primary"]};'>{total:,}</div>
              <div style='font-size:11px;color:{BLITZ_COLORS["text_secondary"]};'>Reconciliation checks</div>
            </div>
            <div>
              <div style='font-size:26px;font-weight:800;color:{_C_HEALTHY};'>{passing:,}</div>
              <div style='font-size:11px;color:{BLITZ_COLORS["text_secondary"]};'>Passing</div>
            </div>
            <div>
              <div style='font-size:26px;font-weight:800;color:{_C_ATTENTION};'>{flagged - critical:,}</div>
              <div style='font-size:11px;color:{BLITZ_COLORS["text_secondary"]};'>Attention</div>
            </div>
            <div>
              <div style='font-size:26px;font-weight:800;color:{_C_CRITICAL};'>{critical:,}</div>
              <div style='font-size:11px;color:{BLITZ_COLORS["text_secondary"]};'>Critical</div>
            </div>
            <div>
              <div style='font-size:26px;font-weight:800;color:{bar_color};'>{fmt_idr(largest)}</div>
              <div style='font-size:11px;color:{BLITZ_COLORS["text_secondary"]};'>Largest variance</div>
            </div>
          </div>
          <div style='font-size:10px;color:{BLITZ_COLORS["text_secondary"]};margin-bottom:4px;'>
            {pct_pass:.1f}% of checks passing &nbsp;|&nbsp; Threshold: {fmt_idr_full(threshold)}</div>
          <div style='height:8px;background:rgba(0,0,0,0.1);border-radius:4px;'>
            <div style='height:8px;width:{bar_w}%;background:{_C_HEALTHY};border-radius:4px;
              transition:width 0.4s ease;'></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Section 2 — Reconciliation Scorecard
# ---------------------------------------------------------------------------

# Map of (category_substring → card_label) for the scorecard lanes
_SCORECARD_LANES = [
    ("Client Revenue vs Revenue Tracker", "Client Revenue → Revenue Tracker",
     "Checks that MASTER client revenue totals match the Revenue Tracker"),
    ("Revenue Tracker vs Group P&L", "Revenue Tracker → Group P&L",
     "Checks that the Revenue Tracker aligns to the Group P&L feed"),
    ("Group P&L vs Consolidated Summary", "Group P&L → Consolidated Summary",
     "Checks that entity P&Ls consolidate correctly into the Group summary"),
    ("Blitz Entity", "Blitz Entity",
     "Entity-level reconciliation for Blitz"),
    ("Borzo Entity", "Borzo Entity",
     "Entity-level reconciliation for Borzo"),
    ("TheLorry Entity", "TheLorry Entity",
     "Entity-level reconciliation for TheLorry"),
]


def _render_scorecard(df: pd.DataFrame, threshold: float) -> None:
    """Compact reconciliation scorecard — one card per reconciliation lane."""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.07em;text-transform:uppercase;margin:18px 0 10px;'>"
        f":material/fact_check: Reconciliation Scorecard</div>",
        unsafe_allow_html=True,
    )

    # Determine which lanes have data
    present_lanes = []
    for cat, label, help_txt in _SCORECARD_LANES:
        lane_df = df[df["Category"] == cat]
        if not lane_df.empty:
            present_lanes.append((cat, label, help_txt, lane_df))

    if not present_lanes:
        st.caption("No reconciliation lanes detected from the workbook labels.")
        return

    n_cols = min(3, len(present_lanes))
    rows = [present_lanes[i:i + n_cols] for i in range(0, len(present_lanes), n_cols)]
    for row_items in rows:
        cols = st.columns(n_cols, gap="medium")
        for col, (cat, label, help_txt, lane_df) in zip(cols, row_items):
            with col:
                _render_scorecard_card(label, help_txt, lane_df, threshold)


def _render_scorecard_card(
    label: str, help_txt: str, lane_df: pd.DataFrame, threshold: float
) -> None:
    total = len(lane_df)
    flagged = int((lane_df["AbsDelta"] > threshold).sum())
    critical = int((lane_df["AbsDelta"] > threshold * _CRITICAL_MULT).sum())
    valid_deltas = lane_df["AbsDelta"].dropna()
    largest = float(valid_deltas.max()) if not valid_deltas.empty else None
    worst_month = ""
    if not valid_deltas.empty:
        worst_row = lane_df.loc[valid_deltas.idxmax()]
        worst_month = str(worst_row.get("Month", ""))

    if critical > 0:
        sev = "Critical"
    elif flagged > 0:
        sev = "Attention"
    else:
        sev = "Healthy"

    sc = _severity_color(sev)
    sb = _severity_bg(sev)
    icon = _severity_icon(sev)

    st.markdown(
        f"""
        <div style='background:{sb};border:1.5px solid {sc};border-radius:10px;
            padding:14px 16px;margin-bottom:8px;' title='{help_txt}'>
          <div style='display:flex;justify-content:space-between;align-items:flex-start;'>
            <div style='font-size:11.5px;font-weight:700;color:{BLITZ_COLORS["text_primary"]};
                max-width:160px;line-height:1.3;'>{label}</div>
            <div style='font-size:16px;'>{icon}</div>
          </div>
          <div style='font-size:18px;font-weight:800;color:{sc};margin:6px 0 2px;'>{sev}</div>
          <div style='font-size:11px;color:{BLITZ_COLORS["text_secondary"]};line-height:1.7;'>
            {total} checks &nbsp;·&nbsp; {flagged} with variance<br>
            Largest: <b>{fmt_idr(largest) if largest is not None else "N/A"}</b><br>
            Worst period: <b>{worst_month or "—"}</b>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Section 3 — Exception-First: Top Exceptions Table
# ---------------------------------------------------------------------------

def _render_exceptions(df: pd.DataFrame, threshold: float) -> None:
    """Surface the 5 largest reconciliation exceptions at the top."""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.07em;text-transform:uppercase;margin:22px 0 10px;'>"
        f":material/priority_high: Top Reconciliation Exceptions</div>",
        unsafe_allow_html=True,
    )

    summary = unreconciled_summary(df, threshold)
    below = int(summary["below_threshold"])
    exceptions = df[df["AbsDelta"] > threshold].sort_values("AbsDelta", ascending=False).head(10)

    # Always state what the threshold is hiding. "No variances above threshold"
    # is not the same claim as "everything ties out", and conflating the two is
    # how an unreconciled month gets signed off.
    if below > 0:
        st.caption(
            f":material/filter_alt: {below} further non-zero variance(s) totalling "
            f"{fmt_idr(float(summary['gross_variance']) - float(df.loc[df['AbsDelta'] > threshold, 'AbsDelta'].sum()))} "
            f"fall below the Rp{threshold:,.0f} threshold and are not listed below."
        )

    if exceptions.empty:
        banner_bg = _C_HEALTHY_BG if below == 0 else _C_ATTENTION_BG
        banner_fg = _C_HEALTHY if below == 0 else _C_ATTENTION
        message = (
            "✅ Every reconciliation check is exactly zero for the selected months."
            if below == 0
            else f"⚠️ No variance exceeds Rp{threshold:,.0f}, but {below} non-zero "
                 f"variance(s) remain. This is within tolerance, not reconciled."
        )
        st.markdown(
            f"<div style='background:{banner_bg};border:1.5px solid {banner_fg};"
            f"border-radius:8px;padding:14px 20px;font-weight:600;color:{banner_fg};'>"
            f"{message}</div>",
            unsafe_allow_html=True,
        )
        return

    border = BLITZ_COLORS["border"]
    thead = (
        f"<tr>"
        + "".join(
            f"<th style='padding:6px 12px;text-align:{a};font-size:11px;font-weight:700;"
            f"color:{BLITZ_COLORS['text_secondary']};white-space:nowrap;'>{h}</th>"
            for h, a in [
                ("Category", "left"), ("Month", "left"), ("Check", "left"),
                ("Variance", "right"), ("|Variance|", "right"), ("Severity", "center")
            ]
        ) + "</tr>"
    )

    tbody = ""
    for i, (_, row) in enumerate(exceptions.iterrows()):
        sev = _severity(row["AbsDelta"], threshold)
        sc = _severity_color(sev)
        sb = "#FFFFFF" if i % 2 == 0 else BLITZ_COLORS["off_white"]
        sev_badge = (
            f"<span style='background:{sc};color:#FFFFFF;padding:2px 7px;"
            f"border-radius:4px;font-size:10px;font-weight:700;'>{sev}</span>"
        )
        delta_color = _C_CRITICAL if row["Delta"] < 0 else _C_ATTENTION
        tbody += (
            f"<tr style='background:{sb};'>"
            f"<td style='padding:6px 12px;font-size:12px;font-weight:600;"
            f"color:{BLITZ_COLORS['text_primary']};border-bottom:1px solid {border};'>{row['Category']}</td>"
            f"<td style='padding:6px 12px;font-size:12px;color:{BLITZ_COLORS['text_secondary']};border-bottom:1px solid {border};'>"
            f"{row['Month']}</td>"
            f"<td style='padding:6px 12px;font-size:11px;color:{BLITZ_COLORS['text_secondary']};border-bottom:1px solid {border};'>"
            f"{row['Label']}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-size:12px;font-weight:600;"
            f"color:{delta_color};border-bottom:1px solid {border};'>{fmt_idr(row['Delta'])}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-size:12px;font-weight:700;"
            f"color:{sc};border-bottom:1px solid {border};'>{fmt_idr(row['AbsDelta'])}</td>"
            f"<td style='padding:6px 12px;text-align:center;border-bottom:1px solid {border};'>{sev_badge}</td>"
            f"</tr>"
        )

    st.markdown(
        f"<div style='border:1px solid {border};border-radius:10px;overflow:hidden;'>"
        f"<table style='width:100%;border-collapse:collapse;'>"
        f"<thead style='background:{BLITZ_COLORS['pale_blue']};border-bottom:2px solid {border};'>"
        f"{thead}</thead><tbody>{tbody}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section 4 — Monthly Heatmap
# ---------------------------------------------------------------------------

def _render_heatmap(df: pd.DataFrame, threshold: float) -> None:
    """Interactive plotly heatmap: Category × Month, colored by max severity."""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.07em;text-transform:uppercase;margin:22px 0 10px;'>"
        f":material/grid_on: Monthly Reconciliation Heatmap</div>",
        unsafe_allow_html=True,
    )

    if df.empty:
        st.caption("No data available for heatmap.")
        return

    month_order = df.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
    categories = sorted(df["Category"].unique())

    # Build z-matrix: 0=Healthy, 1=Attention, 2=Critical
    z: list[list[float]] = []
    hover: list[list[str]] = []

    for cat in categories:
        row_z: list[float] = []
        row_hover: list[str] = []
        for month in month_order:
            cell = df[(df["Category"] == cat) & (df["Month"] == month)]
            if cell.empty:
                row_z.append(float("nan"))
                row_hover.append("No data")
            else:
                max_abs = float(cell["AbsDelta"].max())
                if max_abs > threshold * _CRITICAL_MULT:
                    row_z.append(2.0)
                elif max_abs > threshold:
                    row_z.append(1.0)
                else:
                    row_z.append(0.0)
                n = len(cell)
                row_hover.append(
                    f"<b>{cat}</b><br>Period: {month}<br>Checks: {n}"
                    f"<br>Largest variance: {fmt_idr(max_abs)}"
                )
        z.append(row_z)
        hover.append(row_hover)

    colorscale = [
        [0.0, _C_HEALTHY_BG],
        [0.35, _C_HEALTHY_BG],
        [0.35, _C_ATTENTION_BG],
        [0.65, _C_ATTENTION_BG],
        [0.65, _C_CRITICAL_BG],
        [1.0, _C_CRITICAL_BG],
    ]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=month_order,
            y=categories,
            colorscale=colorscale,
            zmin=0,
            zmax=2,
            showscale=False,
            hovertemplate="%{customdata}<extra></extra>",
            customdata=hover,
            xgap=3,
            ygap=3,
        )
    )

    # Add text annotations for severity level
    sev_text = [["", "!", "✕"][int(v)] if not math.isnan(v) else "" for row in z for v in row]
    annotations = []
    for ri, row_z in enumerate(z):
        for ci, val in enumerate(row_z):
            if not math.isnan(val) and val > 0:
                annotations.append(
                    dict(
                        x=month_order[ci],
                        y=categories[ri],
                        text=["", "!", "✕"][int(val)],
                        showarrow=False,
                        font=dict(
                            size=12,
                            color=_C_ATTENTION if val == 1.0 else _C_CRITICAL,
                            family="Arial",
                        ),
                    )
                )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color=BLITZ_COLORS["text_primary"]),
        margin=dict(l=10, r=10, t=30, b=10),
        height=max(200, len(categories) * 52),
        xaxis=dict(
            tickfont=dict(size=10),
            side="top",
            showgrid=False,
            tickangle=-30,
        ),
        yaxis=dict(
            tickfont=dict(size=11),
            showgrid=False,
            autorange="reversed",
        ),
        annotations=annotations,
        title=dict(
            text="🟢 Healthy &nbsp;&nbsp; 🟡 Attention (!) &nbsp;&nbsp; 🔴 Critical (✕)",
            font=dict(size=10, color=BLITZ_COLORS["text_secondary"]),
            x=0,
            y=1.0,
            xref="paper",
            yref="paper",
        ),
    )

    render_plotly_chart(fig)


# ---------------------------------------------------------------------------
# Section 5 — Root-Cause Grouping
# ---------------------------------------------------------------------------

def _render_root_cause(df: pd.DataFrame, threshold: float) -> None:
    """Group variances by likely root cause, without inventing causes."""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.07em;text-transform:uppercase;margin:22px 0 10px;'>"
        f":material/analytics: Variance by Root Cause</div>",
        unsafe_allow_html=True,
    )

    flagged = df[df["AbsDelta"] > threshold]
    if flagged.empty:
        st.caption("No variances above threshold — root cause analysis not required.")
        return

    by_cause = (
        flagged.groupby("RootCause")
        .agg(
            total_checks=("Delta", "count"),
            total_abs_variance=("AbsDelta", "sum"),
            largest_variance=("AbsDelta", "max"),
        )
        .sort_values("total_abs_variance", ascending=False)
        .reset_index()
    )

    border = BLITZ_COLORS["border"]
    grand_total = by_cause["total_abs_variance"].sum()

    cols = st.columns(min(3, len(by_cause)), gap="medium")
    for i, row in by_cause.iterrows():
        col = cols[int(i) % len(cols)]
        share = row["total_abs_variance"] / grand_total * 100 if grand_total > 0 else 0
        bar_w = int(min(100, share))
        # Classify urgency by share
        urg_color = _C_CRITICAL if share > 50 else (_C_ATTENTION if share > 20 else _C_HEALTHY)
        with col:
            st.markdown(
                f"<div style='background:#FFFFFF;border:1px solid {border};"
                f"border-radius:8px;padding:14px 16px;margin-bottom:8px;'>"
                f"<div style='font-size:12px;font-weight:700;color:{BLITZ_COLORS['text_primary']};"
                f"margin-bottom:6px;'>{row['RootCause']}</div>"
                f"<div style='font-size:20px;font-weight:800;color:{urg_color};'>"
                f"{fmt_idr(row['largest_variance'])}</div>"
                f"<div style='font-size:10px;color:{BLITZ_COLORS['text_secondary']};margin-top:2px;'>"
                f"Largest single variance</div>"
                f"<div style='height:4px;background:{BLITZ_COLORS['border']};border-radius:2px;margin:8px 0;'>"
                f"<div style='height:4px;width:{bar_w}%;background:{urg_color};border-radius:2px;'></div></div>"
                f"<div style='font-size:11px;color:{BLITZ_COLORS['text_secondary']};'>"
                f"{int(row['total_checks'])} exceptions &nbsp;·&nbsp; "
                f"{share:.0f}% of total variance<br>"
                f"Cumulative: {fmt_idr(row['total_abs_variance'])}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Section 6 — Data Quality KPIs
# ---------------------------------------------------------------------------

def _render_data_quality(sheets: dict[str, pd.DataFrame]) -> None:
    """Compute and display data quality metrics directly from the workbook data."""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.07em;text-transform:uppercase;margin:22px 0 10px;'>"
        f":material/health_metrics: Data Quality Indicators</div>",
        unsafe_allow_html=True,
    )

    raw_master = sheets.get("MASTER")
    if raw_master is None:
        st.caption("MASTER sheet not available — data quality indicators require it.")
        return

    master, missing = parse_master(raw_master)
    if missing or master.empty:
        st.caption("Could not parse MASTER sheet for data quality analysis.")
        return

    metrics: list[tuple[str, Any, str, str]] = []  # (label, value, unit, note)

    # 1. Total records
    total_records = len(master)
    metrics.append(("Total Records", f"{total_records:,}", "", "All rows in MASTER"))

    # 2. Missing client names
    missing_clients = int(master["Client (clean)"].isna().sum()) + int(
        (master["Client (clean)"] == "").sum()
    )
    metrics.append((
        "Missing Client Names",
        str(missing_clients),
        "",
        "Rows with no client assigned",
    ))

    # 3. Unmapped / placeholder clients
    placeholder_tokens = {"unknown", "n/a", "tbc", "to be confirmed", "pending", "n.a.", "none", "-"}
    unmapped = int(
        master["Client (clean)"]
        .str.strip()
        .str.lower()
        .isin(placeholder_tokens)
        .sum()
    )
    metrics.append(("Unmapped / Placeholder Clients", str(unmapped), "", "e.g. 'Unknown', 'N/A', 'TBC'"))

    # 4. Duplicate client aliases (same name, different entity — potential double-count risk)
    client_entity_pairs = master.groupby("Client (clean)")["Entity"].nunique()
    multi_entity_clients = int((client_entity_pairs > 1).sum())
    metrics.append((
        "Clients Across Multiple Entities",
        str(multi_entity_clients),
        "",
        "Same client name appears under > 1 entity — review for double counting",
    ))

    # 5. Unexpected entity values
    known_entities = set(ENTITY_SUMMARY_SHEETS.keys())
    unexpected_entities_mask = ~master["Entity"].isin(known_entities)
    unexpected_entities = master.loc[unexpected_entities_mask, "Entity"].nunique()
    metrics.append((
        "Unexpected Entity Values",
        str(unexpected_entities),
        "",
        f"Entities not in {', '.join(sorted(known_entities))}",
    ))

    # 6. Unclassified revenue streams (blank / placeholder)
    blank_streams = int(
        master["Rev Stream"].isna().sum()
        + (master["Rev Stream"].str.strip() == "").sum()
    )
    metrics.append(("Unclassified Revenue Streams", str(blank_streams), "", "Rows with no stream assigned"))

    # 7. Unusual negative revenue values
    negative_rev = int((master["Amount (IDR)"] < -1_000_000).sum())
    metrics.append((
        "Unusual Negative Revenue Rows",
        str(negative_rev),
        "",
        "Rows where Amount (IDR) < −1M (may be valid adjustments)",
    ))

    # 8. Zero revenue rows
    zero_rev = int((master["Amount (IDR)"] == 0).sum())
    metrics.append(("Zero-Value Revenue Rows", str(zero_rev), "", "Rows with zero amount"))

    # Render as a grid of metric cards
    border = BLITZ_COLORS["border"]
    n_cols = 4
    rows = [metrics[i:i + n_cols] for i in range(0, len(metrics), n_cols)]
    for row_items in rows:
        cols = st.columns(n_cols, gap="small")
        for col, (label, value, unit, note) in zip(cols, row_items):
            # Determine if this is a warning metric
            try:
                num_val = int(str(value).replace(",", ""))
                is_warn = num_val > 0 and label not in ("Total Records",)
            except ValueError:
                is_warn = False
            warn_color = _C_ATTENTION if is_warn else _C_HEALTHY
            with col:
                st.markdown(
                    f"<div style='background:#FFFFFF;border:1px solid {border};"
                    f"border-radius:8px;padding:12px 14px;margin-bottom:6px;"
                    f"border-left:3px solid {warn_color};'>"
                    f"<div style='font-size:11px;font-weight:600;"
                    f"color:{BLITZ_COLORS['text_secondary']};margin-bottom:4px;'>{label}</div>"
                    f"<div style='font-size:22px;font-weight:800;color:{warn_color};'>{value}{unit}</div>"
                    f"<div style='font-size:10px;color:{BLITZ_COLORS['text_secondary']};margin-top:4px;"
                    f"line-height:1.3;'>{note}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------------------
# Section 7 — Drill-Down
# ---------------------------------------------------------------------------

def _render_drilldown(df: pd.DataFrame, threshold: float) -> None:
    """Layered drill-down: Category → Month → Entity → Source → Records."""
    st.markdown(
        f"<div style='font-size:12px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.07em;text-transform:uppercase;margin:22px 0 10px;'>"
        f":material/manage_search: Drill-Down Explorer</div>",
        unsafe_allow_html=True,
    )

    with st.expander(
        ":material/keyboard_arrow_down: Open Drill-Down — Navigate from Category → Period → Source",
        expanded=False,
    ):
        col_cat, col_month = st.columns(2, gap="medium")
        with col_cat:
            cats = sorted(df["Category"].unique())
            selected_cat = st.selectbox(
                "Reconciliation Check",
                cats,
                key="dd_category",
            )
        filtered = pd.DataFrame(df[df["Category"] == selected_cat])
        month_order = filtered.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
        with col_month:
            selected_month = st.selectbox(
                "Period",
                ["All periods"] + month_order,
                key="dd_month",
            )
        if selected_month != "All periods":
            filtered = pd.DataFrame(filtered[filtered["Month"] == selected_month])

        if filtered.empty:
            st.caption("No data for the selected filters.")
            return

        # Show aggregated view + underlying records
        col_agg, col_detail = st.columns([1, 2], gap="medium")
        with col_agg:
            total = len(filtered)
            flagged = int((filtered["AbsDelta"] > threshold).sum())
            valid_deltas = filtered["AbsDelta"].dropna()
            largest = float(valid_deltas.max()) if not valid_deltas.empty else 0.0
            sev = _severity(largest, threshold)
            sc = _severity_color(sev)
            border = BLITZ_COLORS["border"]
            st.markdown(
                f"<div style='background:{_severity_bg(sev)};border:1.5px solid {sc};"
                f"border-radius:8px;padding:14px;'>"
                f"<div style='font-size:11px;color:{BLITZ_COLORS['text_secondary']};'>"
                f"{selected_cat}</div>"
                f"<div style='font-size:24px;font-weight:800;color:{sc};'>{sev}</div>"
                f"<div style='font-size:11px;color:{BLITZ_COLORS['text_secondary']};margin-top:6px;'>"
                f"{total} checks<br>{flagged} with variance<br>"
                f"Largest: <b>{fmt_idr(largest)}</b></div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        with col_detail:
            display_df = filtered[["Label", "Month", "Delta", "AbsDelta", "RootCause"]].copy()
            display_df = display_df.rename(columns={
                "Label": "Source Row",
                "Month": "Period",
                "Delta": "Variance (IDR)",
                "AbsDelta": "Absolute Variance",
                "RootCause": "Likely Cause",
            })
            # Sort on the NUMERIC value before formatting. Sorting the
            # formatted strings ranked "Rp999K" above "Rp1.2B" lexicographically
            # and buried the largest exception mid-table.
            display_df = display_df.sort_values("Absolute Variance", ascending=False)
            display_df["Variance (IDR)"] = display_df["Variance (IDR)"].apply(fmt_idr_full)
            display_df["Absolute Variance"] = display_df["Absolute Variance"].apply(fmt_idr)

            def _style_dd(row: pd.Series) -> list[str]:
                raw_abs = filtered.loc[row.name, "AbsDelta"] if row.name in filtered.index else 0
                if raw_abs > threshold * _CRITICAL_MULT:
                    style = f"background-color:{_C_CRITICAL_BG};color:{_C_CRITICAL};"
                elif raw_abs > threshold:
                    style = f"background-color:{_C_ATTENTION_BG};color:{_C_ATTENTION};"
                else:
                    style = ""
                return [style] * len(row)

            styled = display_df.style.apply(_style_dd, axis=1)
            st.dataframe(styled, hide_index=True, width="stretch")

    # Full reconciliation pivot is deferred until requested.
    full_pivot = st.expander(
        ":material/table_chart: Full Reconciliation Pivot Table (all periods)",
        expanded=False,
        on_change="rerun",
    )
    if full_pivot.open:
        with full_pivot:
            _render_full_pivot(df, threshold)


def _render_full_pivot(df: pd.DataFrame, threshold: float | None = None) -> None:
    """Full reconciliation pivot with conditional formatting."""
    # Honour the user's threshold. Previously this used the module constant, so
    # dropping the slider to Rp0 to surface everything still hid sub-Rp1M cells.
    limit = float(threshold) if threshold is not None else float(TIE_OUT_FLAG_THRESHOLD)
    if df.empty:
        return
    try:
        month_order = df.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
        pivot = df.pivot_table(index="Label", columns="Month", values="Delta", aggfunc="sum")
        pivot = pivot[[m for m in month_order if m in pivot.columns]]

        def _color_cell(v: object) -> str:
            try:
                fv = float(v)  # type: ignore[arg-type]
                abs_fv = abs(fv)
                if abs_fv > limit * _CRITICAL_MULT:
                    return f"background-color:{_C_CRITICAL_BG};color:{_C_CRITICAL};font-weight:600;"
                if abs_fv > limit:
                    return f"background-color:{_C_ATTENTION_BG};color:{_C_ATTENTION};"
            except (TypeError, ValueError):
                pass
            return ""

        styled = pivot.style.map(_color_cell).format(
            lambda v: fmt_idr_full(v) if isinstance(v, (int, float)) else ""
        )
        st.dataframe(styled, width="stretch")
    except Exception:  # noqa: BLE001
        st.dataframe(df[["Label", "Month", "Delta"]], hide_index=True, width="stretch")
