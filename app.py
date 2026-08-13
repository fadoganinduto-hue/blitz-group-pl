"""Group P&L BI Dashboard — entrypoint.

Responsibilities: page config, sidebar branding + data upload,
sidebar global filters, tab routing. Zero business logic here.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from streamlit_app.components.filters import (
    render_sidebar_filters,
    render_sidebar_global_filters,
)
from streamlit_app.components.ui import (
    apply_global_visual_system,
    render_app_footer,
    render_app_header,
)
from streamlit_app.data.loader import load_workbook, _file_hash
from streamlit_app.data.parsers import parse_master, parse_pl_sheet as _parse_pl
from streamlit_app.data.validator import validate_workbook
from streamlit_app.ai_service import is_api_configured
from streamlit_app.tabs import (
    ai_insights,
    consolidated,
    data_health,
    margin_by_stream,
    overview,
    per_client,
    per_entity,
)
from streamlit_app.constants import BLITZ_COLORS

st.set_page_config(
    page_title="Blitz Financial Intelligence",
    page_icon=":material/analytics:",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_global_visual_system()

# ---------------------------------------------------------------------------
# Sidebar — branding
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        f"""
        <div style="padding:6px 0 14px 0;
            border-bottom:1px solid {BLITZ_COLORS['border']};margin-bottom:4px;">
            <div style="font-size:15px;font-weight:800;letter-spacing:-0.3px;
                color:{BLITZ_COLORS['text_primary']};">Group P&amp;L</div>
            <div style="font-size:10px;color:{BLITZ_COLORS['text_secondary']};
                margin-top:2px;font-weight:600;">Financial Intelligence</div>
            <div style="font-size:10px;color:{BLITZ_COLORS['text_secondary']};margin-top:1px;">2026</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader(":material/upload_file: Data source")
    uploaded_file = st.file_uploader(
        "Upload the Group P&L workbook (.xlsx)",
        type=["xlsx"],
        label_visibility="collapsed",
    )
    st.caption("Upload your workbook to activate all views. Re-upload when updated.")

# ---------------------------------------------------------------------------
# Landing page (no file uploaded)
# ---------------------------------------------------------------------------
if uploaded_file is None:
    st.markdown(
        f"""
        <div style="
            max-width:620px;margin:80px auto 0 auto;text-align:center;
            padding:52px 44px;background:#FFFFFF;border-radius:16px;
            border:1px solid {BLITZ_COLORS['border']};
            box-shadow:0 4px 24px rgba(0,185,242,0.08);
        ">
            <div style="width:64px;height:64px;border-radius:16px;margin:0 auto 20px;
                background:linear-gradient(135deg,{BLITZ_COLORS['primary']},{BLITZ_COLORS['deep_blue']});
                display:flex;align-items:center;justify-content:center;font-size:28px;">📊</div>
            <h2 style="font-size:24px;font-weight:800;margin:0 0 10px 0;
                color:{BLITZ_COLORS['text_primary']};">
                Group P&amp;L Intelligence Dashboard
            </h2>
            <p style="color:{BLITZ_COLORS['text_secondary']};font-size:13px;
                line-height:1.7;margin:0 0 28px 0;">
                Upload the <strong style="color:{BLITZ_COLORS['text_primary']};">
                Group_PL_2026_Upload…xlsx</strong> workbook in the sidebar to load
                consolidated P&amp;L, per-entity, per-client, margin, and data health views.
            </p>
            <div style="
                display:inline-flex;align-items:center;gap:8px;
                background:{BLITZ_COLORS['pale_blue']};border:1px dashed {BLITZ_COLORS['light_blue']};
                border-radius:8px;padding:10px 20px;font-size:13px;
                color:{BLITZ_COLORS['deep_blue']};font-weight:600;">
                ← Use the sidebar to upload your workbook
            </div>
            <div style="margin-top:28px;display:flex;justify-content:center;gap:20px;flex-wrap:wrap;">
                <div style="font-size:11px;color:{BLITZ_COLORS['text_secondary']};text-align:center;">
                    <div style="font-size:20px;">📈</div>Executive Overview
                </div>
                <div style="font-size:11px;color:{BLITZ_COLORS['text_secondary']};text-align:center;">
                    <div style="font-size:20px;">🏢</div>Per-Entity Analysis
                </div>
                <div style="font-size:11px;color:{BLITZ_COLORS['text_secondary']};text-align:center;">
                    <div style="font-size:20px;">👥</div>Per-Client Revenue
                </div>
                <div style="font-size:11px;color:{BLITZ_COLORS['text_secondary']};text-align:center;">
                    <div style="font-size:20px;">🛡️</div>Data Health
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

# ---------------------------------------------------------------------------
# Load workbook
# ---------------------------------------------------------------------------
# Compute and store the file hash so downstream cached calls share the same key
_wb_hash = _file_hash(uploaded_file)
st.session_state["_wb_hash"] = _wb_hash
sheets = load_workbook(uploaded_file)

# ---------------------------------------------------------------------------
# Workbook validation
# ---------------------------------------------------------------------------
_wb_issues = validate_workbook(uploaded_file, sheets)
_wb_errors = [i for i in _wb_issues if i.level == "error"]
_wb_warnings = [i for i in _wb_issues if i.level == "warning"]

if _wb_errors:
    st.error(":material/error: **This workbook cannot be loaded — please fix the following issues:**")
    for _issue in _wb_errors:
        sheet_tag = f" `{_issue.sheet}`" if _issue.sheet else ""
        st.markdown(
            f"""
            <div style="
                background:#FFEBE9;border:1.5px solid #CF222E;border-radius:8px;
                padding:14px 18px;margin-bottom:8px;
            ">
              <div style="font-weight:700;font-size:13px;color:#CF222E;margin-bottom:4px;">
                ⛔ {_issue.title}{sheet_tag}
              </div>
              <div style="font-size:12px;color:#6E3B3B;line-height:1.6;white-space:pre-wrap;">{_issue.detail}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.stop()

if _wb_warnings:
    with st.expander(
        f":material/warning: {len(_wb_warnings)} workbook notice(s) — click to review",
        expanded=False,
    ):
        for _issue in _wb_warnings:
            sheet_tag = f" `{_issue.sheet}`" if _issue.sheet else ""
            st.markdown(
                f"""
                <div style="
                    background:#FFF8C5;border:1px solid #BF8700;border-radius:6px;
                    padding:10px 14px;margin-bottom:6px;
                ">
                  <div style="font-weight:600;font-size:12px;color:#BF8700;margin-bottom:2px;">
                    ⚠️ {_issue.title}{sheet_tag}
                  </div>
                  <div style="font-size:11px;color:#735C00;line-height:1.5;">{_issue.detail}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

_upload_identity = (uploaded_file.name, uploaded_file.size)
if st.session_state.get("_loaded_workbook_identity") != _upload_identity:
    st.session_state["_loaded_workbook_identity"] = _upload_identity
    st.session_state["_data_loaded_at"] = datetime.now().astimezone()
_data_loaded_at = st.session_state.get("_data_loaded_at")

# Shared application header — intentionally above, and separate from, tab navigation.
_logo_path = Path(__file__).parent / "streamlit_app" / "assets" / "rideblitzlogo.png"
render_app_header(
    logo_path=_logo_path,
    health_status=data_health.get_overall_health_status(sheets),
    refreshed_at=_data_loaded_at,
)

# ---------------------------------------------------------------------------
# Build global month list from Consolidated Summary for sidebar filters
# ---------------------------------------------------------------------------
_global_months: list[str] = []
_cons_raw = sheets.get("Consolidated Summary")
if _cons_raw is not None:
    _cons_long = _parse_pl(_cons_raw, "Consolidated")
    if not _cons_long.empty:
        _global_months = (
            _cons_long.drop_duplicates("Month")
            .sort_values("MonthDate")["Month"]
            .tolist()
        )

# ---------------------------------------------------------------------------
# Build global entity / stream / industry option lists from MASTER
# ---------------------------------------------------------------------------
_entity_options: list[str] = []
_stream_options: list[str] = []
_industry_options: list[str] = []

_master_raw = sheets.get("MASTER")
if _master_raw is not None:
    _master_df, _missing = parse_master(_master_raw)
    if not _missing and not _master_df.empty:
        _entity_options = sorted(_master_df["Entity"].dropna().unique().tolist())
        _stream_options = sorted(_master_df["Rev Stream"].dropna().unique().tolist())
        _industry_options = sorted(_master_df["Industry"].dropna().unique().tolist())

# Store option lists in session state so filter bar can compare against "all"
st.session_state["_all_entity_options"] = _entity_options
st.session_state["_all_stream_options"] = _stream_options
st.session_state["_all_industry_options"] = _industry_options

# ---------------------------------------------------------------------------
# Read FX rate from Settings sheet
# ---------------------------------------------------------------------------
_settings_raw = sheets.get("Settings")
if _settings_raw is not None:
    try:
        fx_val = _settings_raw.iloc[1, 1]
        if isinstance(fx_val, (int, float)) and float(fx_val) > 0:
            st.session_state["fx_rate"] = float(fx_val)
        else:
            st.session_state.setdefault("fx_rate", 15_000.0)
    except Exception:
        st.session_state.setdefault("fx_rate", 15_000.0)
else:
    st.session_state.setdefault("fx_rate", 15_000.0)

# ---------------------------------------------------------------------------
# Sidebar — filters
# ---------------------------------------------------------------------------
with st.sidebar:
    render_sidebar_filters(_global_months)
    render_sidebar_global_filters(
        entity_options=_entity_options,
        stream_options=_stream_options,
        industry_options=_industry_options,
        month_options=_global_months,
    )

    st.sidebar.divider()
    st.sidebar.markdown(
        f"<p style='font-size:10px;font-weight:700;letter-spacing:0.08em;"
        f"text-transform:uppercase;color:{BLITZ_COLORS['primary_hover']};"
        f"margin:0 0 4px 0;padding:10px 0 0 0;'>Display</p>",
        unsafe_allow_html=True,
    )
    fx_display = f"USD (1 USD = Rp{int(st.session_state.get('fx_rate', 15_000)):,})"
    currency = st.sidebar.segmented_control(
        "Display currency",
        options=["IDR", "USD"],
        default=st.session_state.get("currency", "IDR"),
        key="currency_ctrl",
        help=f"IDR values are converted at the FX rate from the Settings sheet: {fx_display}",
    )
    st.session_state["currency"] = currency or "IDR"

    # AI status indicator
    st.sidebar.divider()
    if is_api_configured():
        st.sidebar.caption(":material/check_circle: AI Insights ready")
    else:
        st.sidebar.caption(":material/key_off: AI key not set — see AI Insights tab")

    # Data context footer
    if _global_months:
        st.sidebar.markdown(
            f"<div style='font-size:10px;color:{BLITZ_COLORS['text_secondary']};margin-top:8px;"
            f"padding:8px;background:{BLITZ_COLORS['background']};border-radius:6px;'>"
            f"📁 {len(_global_months)} months loaded<br>"
            f"🏢 {len(_entity_options)} entities<br>"
            f"👥 {len(_stream_options)} revenue streams</div>",
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------------------
# Tab routing — logical order with intentional labels
# ---------------------------------------------------------------------------
tab_overview, tab_cons, tab_entity, tab_client, tab_margin, tab_health, tab_ai = st.tabs(
    [
        ":material/home: Overview",
        ":material/bar_chart: Consolidated P&L",
        ":material/compare: Entity Analysis",
        ":material/group: Client Revenue",
        ":material/donut_small: Margin by Stream",
        ":material/shield_with_heart: Data Health",
        ":material/auto_awesome: AI Insights",
    ],
    key="dashboard_navigation",
    on_change="rerun",
)

if tab_overview.open:
    with tab_overview:
        overview.render(sheets)

if tab_cons.open:
    with tab_cons:
        consolidated.render(sheets)

if tab_entity.open:
    with tab_entity:
        per_entity.render(sheets)

if tab_client.open:
    with tab_client:
        per_client.render(sheets)

if tab_margin.open:
    with tab_margin:
        margin_by_stream.render(sheets)

if tab_health.open:
    with tab_health:
        data_health.render(sheets)

if tab_ai.open:
    with tab_ai:
        ai_insights.render(sheets)

render_app_footer(_data_loaded_at)
