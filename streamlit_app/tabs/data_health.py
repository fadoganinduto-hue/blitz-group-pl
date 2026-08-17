"""Data health — reconciliation checks derived from the workbook itself.

Scope note
----------
This tab deliberately does NOT read the ``TIE-OUT CHECK`` worksheet. That sheet
is maintained by hand and is being retired, and a dashboard that reports from a
sheet nobody is updating is worse than one that reports nothing.

What remains is computed from ``MASTER`` and ``Consolidated Summary`` on every
load:

* **MASTER vs P&L revenue bridge** — the per-client detail totalled against
  Total Gross Revenue, month by month.
* **Coverage gaps** — months the P&L has closed that the client detail has not
  reached, so revenue with no client attribution is visible rather than
  implied.
* **Data quality indicators** — record counts, missing and placeholder client
  names, and clients spanning multiple entities.

Neither check can go stale, because neither is stored.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from streamlit_app.constants import (
    BLITZ_COLORS,
    ENTITY_SUMMARY_SHEETS,
    fmt_idr,
    fmt_idr_full,
)
from streamlit_app.components.filters import (
    get_filtered_months,
    render_active_filter_bar,
    render_empty_state,
)
from streamlit_app.components.ui import render_page_header
from streamlit_app.data.parsers import parse_master, parse_pl_sheet
from streamlit_app.data.periods import actual_months
from streamlit_app.data.reconciliation import (
    BRIDGE_MATERIALITY_IDR,
    coverage_gaps,
    master_vs_pl_bridge,
)

# ---------------------------------------------------------------------------
# Semantic colours
# ---------------------------------------------------------------------------
_C_HEALTHY = "#1A7F37"
_C_ATTENTION = "#BF8700"
_C_CRITICAL = "#CF222E"
_C_HEALTHY_BG = "#DAFBE1"
_C_ATTENTION_BG = "#FFF8C5"
_C_CRITICAL_BG = "#FFEBE9"

# A variance above 10x materiality is Critical rather than Attention.
_CRITICAL_MULT = 10


# ---------------------------------------------------------------------------
# Shared health status (drives the badge in the global header)
# ---------------------------------------------------------------------------

def _bridge_for(sheets: dict[str, pd.DataFrame]):
    """Return (bridge, coverage_gaps, cons_long) or (None, [], None)."""
    cons_raw = sheets.get("Consolidated Summary")
    master_raw = sheets.get("MASTER")
    if cons_raw is None or master_raw is None:
        return None, [], None

    cons_long = parse_pl_sheet(cons_raw, "Consolidated")
    master_df, missing = parse_master(master_raw)
    if cons_long.empty or missing or master_df.empty:
        return None, [], None

    bridge = master_vs_pl_bridge(master_df, cons_long)
    gaps = coverage_gaps(actual_months(cons_long), master_df, None)
    return bridge, gaps, cons_long


def get_overall_health_status(sheets: dict[str, pd.DataFrame]) -> str | None:
    """Classify reconciliation health for the shared application header.

    Driven by the derived bridge, and deliberately NOT by any user-adjustable
    threshold — an earlier version read the tab's slider, so widening the
    tolerance turned the badge green on every other tab too.
    """
    bridge, gaps, _ = _bridge_for(sheets)
    if bridge is None or bridge.empty:
        return None

    comparable = bridge[bridge["Comparable"]] if "Comparable" in bridge else bridge
    if comparable.empty:
        return "Critical" if gaps else None
    largest = float(comparable["AbsDelta"].max())
    if gaps or largest > BRIDGE_MATERIALITY_IDR * _CRITICAL_MULT:
        return "Critical"
    if largest > BRIDGE_MATERIALITY_IDR:
        return "Attention"
    return "Healthy"


# ---------------------------------------------------------------------------
# Main render entry point
# ---------------------------------------------------------------------------

def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the Data Health tab."""
    render_page_header(
        "Data health",
        "Reconcile the client detail against the reported P&L, and see where "
        "the two sources do not yet cover the same periods.",
        eyebrow="Financial controls",
    )

    bridge, gaps, cons_long = _bridge_for(sheets)
    if bridge is None:
        st.warning(
            ":material/warning: Data health needs both the 'MASTER' and "
            "'Consolidated Summary' sheets, and at least one must be missing "
            "or unreadable in this workbook."
        )
        return

    all_months = actual_months(cons_long)
    filtered_months = get_filtered_months(all_months) if all_months else all_months
    if not filtered_months:
        render_empty_state(
            title="No months in the selected date range.",
            suggestion="Adjust the month range slider to include at least one closed period.",
            icon="📅",
            show_reset=True,
            key_suffix="health",
        )
        return

    render_active_filter_bar(filtered_months)

    _render_trust_header(bridge, gaps, filtered_months)
    _render_derived_checks(sheets, filtered_months)
    _render_data_quality(sheets)


# ---------------------------------------------------------------------------
# Section 1 — headline
# ---------------------------------------------------------------------------

def _render_trust_header(bridge: pd.DataFrame, gaps: list, months: list[str]) -> None:
    """State the reconciliation position in one line, without softening it."""
    scoped = bridge[bridge["Comparable"]] if "Comparable" in bridge else bridge
    in_range = scoped[scoped["Month"].isin(months)]
    if not in_range.empty:
        scoped = in_range

    largest = float(scoped["AbsDelta"].max()) if not scoped.empty else 0.0
    gross = float(scoped["AbsDelta"].sum())
    net = float(scoped["Delta"].sum())
    material = int((scoped["AbsDelta"] > BRIDGE_MATERIALITY_IDR).sum())
    exact = int((scoped["AbsDelta"] <= 0.5).sum())

    if gaps or largest > BRIDGE_MATERIALITY_IDR * _CRITICAL_MULT:
        label, colour, bg, icon = (
            "Attention required — material variances outstanding",
            _C_CRITICAL, _C_CRITICAL_BG, "⛔",
        )
    elif material:
        label, colour, bg, icon = (
            f"{material} month(s) above materiality",
            _C_ATTENTION, _C_ATTENTION_BG, "⚠️",
        )
    elif exact == len(scoped):
        label, colour, bg, icon = (
            "Client detail ties to the P&L exactly", _C_HEALTHY, _C_HEALTHY_BG, "✅",
        )
    else:
        label, colour, bg, icon = (
            "Ties out within materiality", _C_HEALTHY, _C_HEALTHY_BG, "✅",
        )

    st.markdown(
        f"""
        <div style='background:{bg};border:2px solid {colour};border-radius:12px;
            padding:18px 26px;margin-bottom:18px;'>
          <div style='display:flex;align-items:center;gap:12px;'>
            <span style='font-size:26px;'>{icon}</span>
            <div>
              <div style='font-size:11px;font-weight:700;letter-spacing:0.1em;
                text-transform:uppercase;color:{colour};'>
                CLIENT DETAIL vs REPORTED P&amp;L</div>
              <div style='font-size:19px;font-weight:800;color:{colour};'>{label}</div>
            </div>
          </div>
          <div style='font-size:12px;color:{BLITZ_COLORS['text_secondary']};margin-top:10px;'>
            Largest single month <b>{fmt_idr(largest)}</b> &nbsp;·&nbsp;
            gross <b>{fmt_idr(gross)}</b> across {len(scoped)} month(s) &nbsp;·&nbsp;
            net <b>{fmt_idr(net)}</b>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_derived_checks(
    sheets: dict[str, pd.DataFrame],
    filtered_months: list[str],
) -> None:
    """MASTER-vs-P&L revenue bridge and source coverage gaps.

    Both are derived from the parsed workbook rather than read from a
    maintained reconciliation sheet, so they always describe the file actually
    on screen and cannot fall behind it.
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
    for gap in coverage_gaps(closed, master_df, None):
        st.markdown(
            f"<div style='background:{_C_ATTENTION_BG};border:1.5px solid {_C_ATTENTION};"
            f"border-radius:8px;padding:12px 18px;margin-bottom:8px;font-size:12px;"
            f"color:#735C00;'><strong>⚠️ Coverage gap — {gap.source}</strong><br>{gap.detail}</div>",
            unsafe_allow_html=True,
        )

    # ── Bridge: MASTER client revenue vs Consolidated Total Gross Revenue ─
    months = [m for m in filtered_months if m in closed] or closed
    bridge = master_vs_pl_bridge(master_df, cons_long, months=months)
    if "Comparable" in bridge:
        bridge = bridge[bridge["Comparable"]]
    if bridge.empty:
        st.caption(
            "No month is covered by both the client detail and the P&L in this "
            "range, so there is nothing to reconcile — see the coverage gaps above."
        )
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
        f"net {fmt_idr(net)}. Computed from the loaded workbook on every refresh, "
        f"so it cannot lag the P&L."
    )


# ---------------------------------------------------------------------------
# Helpers
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
