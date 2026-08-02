"""Group P&L BI Dashboard — entrypoint.

Responsibilities: page config, sidebar branding + data upload,
sidebar global filters, tab routing. Zero business logic here.
"""

from __future__ import annotations

import streamlit as st

from streamlit_app.components.filters import render_sidebar_filters
from streamlit_app.data.loader import load_all_sheets
from streamlit_app.data.parsers import parse_pl_sheet as _parse_pl
from streamlit_app.tabs import consolidated, data_health, margin_by_stream, overview, per_client, per_entity

st.set_page_config(
    page_title="Group P&L Dashboard",
    page_icon=":material/analytics:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar — branding
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        """
        <div style="display:flex;align-items:center;gap:10px;padding:4px 0 16px 0;">
            <span style="font-size:26px;">📊</span>
            <div>
                <div style="font-size:17px;font-weight:700;letter-spacing:-0.3px;">Group P&L</div>
                <div style="font-size:11px;color:#94A3B8;margin-top:1px;">BI Dashboard · 2026</div>
            </div>
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
    st.caption("Upload the workbook to load all tabs. Re-upload when the file updates.")

# ---------------------------------------------------------------------------
# Landing page (no file uploaded)
# ---------------------------------------------------------------------------
if uploaded_file is None:
    st.markdown(
        """
        <div style="
            max-width:640px;margin:80px auto 0 auto;text-align:center;
            padding:48px 40px;background:#1E293B;border-radius:16px;
            border:1px solid #334155;
        ">
            <div style="font-size:52px;margin-bottom:20px;">📊</div>
            <h2 style="font-size:26px;font-weight:700;margin:0 0 10px 0;color:#F1F5F9;">
                Group P&L BI Dashboard
            </h2>
            <p style="color:#94A3B8;font-size:14px;line-height:1.6;margin:0 0 28px 0;">
                Upload the <strong style="color:#F1F5F9;">Group_PL_2026_Upload…xlsx</strong>
                workbook in the sidebar to load the consolidated P&amp;L, per-entity,
                per-client, margin-by-stream, and data health views.
            </p>
            <div style="
                display:inline-flex;align-items:center;gap:8px;
                background:#0F172A;border:1px dashed #334155;border-radius:8px;
                padding:10px 20px;font-size:13px;color:#60A5FA;
            ">
                :material/arrow_back: Use the sidebar to upload your workbook
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

# ---------------------------------------------------------------------------
# Load workbook
# ---------------------------------------------------------------------------
sheets = load_all_sheets(uploaded_file)

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

with st.sidebar:
    render_sidebar_filters(_global_months)

# ---------------------------------------------------------------------------
# Tab routing
# ---------------------------------------------------------------------------
tab_overview, tab_cons, tab_entity, tab_client, tab_margin, tab_health = st.tabs(
    [
        ":material/home: Overview",
        ":material/bar_chart: Consolidated",
        ":material/compare: Per-Entity",
        ":material/group: Per-Client",
        ":material/donut_small: Margin by stream",
        ":material/health_and_safety: Data health",
    ]
)

with tab_overview:
    overview.render(sheets)

with tab_cons:
    consolidated.render(sheets)

with tab_entity:
    per_entity.render(sheets)

with tab_client:
    per_client.render(sheets)

with tab_margin:
    margin_by_stream.render(sheets)

with tab_health:
    data_health.render(sheets)