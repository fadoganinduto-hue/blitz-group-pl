"""AI Insights tab — executive summary, anomaly detection, and data Q&A chat."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.ai_service import (
    chat_with_data_stream,
    detect_anomalies,
    generate_executive_summary,
    is_api_configured,
    prepare_data_context,
)
from streamlit_app.components.filters import (
    get_filtered_months,
    render_active_filter_bar,
    render_empty_state,
)
from streamlit_app.components.ui import render_page_header, render_section_header
from streamlit_app.data.parsers import parse_pl_sheet


# Suggested questions shown as pills before the first chat message
_SUGGESTIONS: dict[str, str] = {
    ":blue[:material/trending_up:] What drove revenue changes this month?": (
        "What drove the revenue changes this month? Which entities contributed most?"
    ),
    ":red[:material/warning:] Which entity is underperforming?": (
        "Which entity is underperforming relative to the others? Provide specific numbers."
    ),
    ":green[:material/group:] Summarize client concentration risks": (
        "Summarize the top client concentration risks. Are we too dependent on any single client?"
    ),
    ":violet[:material/percent:] How are margins trending?": (
        "How are the EBITDA and gross margins trending over the last few months? Any concerns?"
    ),
}


def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the AI Insights tab."""
    render_page_header(
        "AI insights",
        "Generate grounded narrative analysis and investigate anomalies using the uploaded financial data.",
        eyebrow="Assisted analysis",
    )
    # ── API key gate ─────────────────────────────────────────────────────
    if not is_api_configured():
        st.markdown(
            """
            <div style="
                max-width:600px;margin:60px auto;text-align:center;
                padding:40px 36px;border-radius:16px;
                border:1px dashed #E2E2E2;
                background:#FFFFFF;
            ">
                <div style="font-size:48px;margin-bottom:16px;">🔑</div>
                <h3 style="margin:0 0 12px 0;color:#1A1A1A;">API key required</h3>
                <p style="color:#4D4D4D;font-size:14px;line-height:1.6;margin:0 0 20px 0;">
                    To use AI Insights, add your Gemini API key to
                    <code>.streamlit/secrets.toml</code>:
                </p>
                <code style="
                    display:block;text-align:left;padding:12px 16px;
                    border-radius:8px;font-size:13px;
                    background:#F8F8F8;color:#1A1A1A;
                ">GEMINI_API_KEY = "your-key-here"</code>
                <p style="color:#4D4D4D;font-size:12px;margin-top:16px;">
                    Get a free key at
                    <a href="https://aistudio.google.com/apikey" target="_blank"
                       style="color:#00B9F2;">Google AI Studio</a>
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # ── Resolve filtered months ──────────────────────────────────────────
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
            key_suffix="ai",
        )
        return

    latest_month = filtered_months[-1]
    render_active_filter_bar(filtered_months)

    # ── Build data context (cached in session state) ─────────────────────
    wb_hash = st.session_state.get("_wb_hash", "unknown")
    cmp_label = st.session_state.get("_resolved_compare_label") or "None"
    ctx_cache_key = f"ai_data_ctx_{wb_hash}_{hash(tuple(filtered_months))}_{hash(cmp_label)}"
    
    if ctx_cache_key not in st.session_state:
        with st.spinner("Preparing data context…"):
            st.session_state[ctx_cache_key] = prepare_data_context(
                sheets, filtered_months, cmp_label, wb_hash
            )
    data_context: str = st.session_state[ctx_cache_key]

    # ── Executive summary & Anomaly detection (side by side) ─────────────
    col_summary, col_anomaly = st.columns(2, gap="medium")

    with col_summary:
        _render_executive_summary(data_context, latest_month)

    with col_anomaly:
        _render_anomaly_detection(data_context)

    # ── Chat with your data ──────────────────────────────────────────────
    _render_chat(data_context)


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_executive_summary(data_context: str, latest_month: str) -> None:
    """Render the executive summary section."""
    render_section_header("Executive summary", "summarize")
    st.caption(f"AI-generated overview for **{latest_month}**")

    summary_key = f"ai_exec_summary_{hash(data_context)}"
    
    if st.button(
        ":material/auto_awesome: Generate summary",
        key="gen_summary_btn",
        type="primary",
    ):
        with st.spinner("Generating executive summary…"):
            try:
                summary = generate_executive_summary(data_context, latest_month)
                st.session_state[summary_key] = summary
            except Exception:  # noqa: BLE001
                st.error("AI insights temporarily unavailable.")
                return

    summary = st.session_state.get(summary_key)
    if summary:
        st.markdown(summary)
    else:
        st.caption("Click the button above to generate an AI executive summary.")


def _render_anomaly_detection(data_context: str) -> None:
    """Render the anomaly detection section."""
    render_section_header("Anomaly detection", "report")
    st.caption("AI-flagged unusual patterns in your data")

    anomaly_key = f"ai_anomalies_{hash(data_context)}"
    
    if st.button(
        ":material/search: Scan for anomalies",
        key="scan_anomaly_btn",
        type="secondary",
    ):
        with st.spinner("Scanning for anomalies…"):
            try:
                anomalies = detect_anomalies(data_context)
                st.session_state[anomaly_key] = anomalies
            except Exception:  # noqa: BLE001
                st.error("AI insights temporarily unavailable.")
                return

    anomalies = st.session_state.get(anomaly_key)
    if anomalies:
        st.markdown(anomalies)
    else:
        st.caption("Click the button above to scan for anomalies in the data.")


def _render_chat(data_context: str) -> None:
    """Render the chat-with-your-data section."""
    render_section_header("Ask about your data", "chat")
    st.caption(
        "Ask any question about the P&L, revenue, margins, clients, or trends. "
        "The AI grounds its answers in your actual uploaded data."
    )

    # Initialize chat history
    if "ai_chat_history" not in st.session_state:
        st.session_state["ai_chat_history"] = []

    chat_history: list[dict[str, str]] = st.session_state["ai_chat_history"]

    # Suggestion pills — only shown before first message
    if not chat_history:
        selected = st.pills(
            "Try asking:",
            list(_SUGGESTIONS.keys()),
            label_visibility="collapsed",
            key="ai_suggestion_pills",
        )
        if selected:
            prompt = _SUGGESTIONS[selected]
            # Add user message to history
            chat_history.append({"role": "user", "content": prompt})
            # Show user bubble immediately
            with st.chat_message("user"):
                st.write(prompt)
            # Generate AI response inline (same path as chat_input)
            with st.chat_message("assistant"):
                try:
                    response = st.write_stream(
                        chat_with_data_stream(data_context, prompt, chat_history)
                    )
                except Exception:  # noqa: BLE001
                    response = "AI insights temporarily unavailable."
                    st.error(response)
            chat_history.append({"role": "assistant", "content": response})
            # Clear the pills widget key so it resets if chat is cleared later
            st.session_state.pop("ai_suggestion_pills", None)
            st.rerun()

    # Display chat history
    for msg in chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # Chat input
    if prompt := st.chat_input(
        "Ask a question about your P&L data…",
        key="ai_chat_input",
    ):
        # Add user message
        chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        # Generate streamed response
        with st.chat_message("assistant"):
            try:
                response = st.write_stream(
                    chat_with_data_stream(data_context, prompt, chat_history)
                )
            except Exception:  # noqa: BLE001
                response = "AI insights temporarily unavailable."
                st.error(response)

        chat_history.append({"role": "assistant", "content": response})

    # Clear chat button (only show if there's history)
    if chat_history:
        if st.button(
            ":material/delete: Clear chat",
            key="clear_chat_btn",
        ):
            st.session_state["ai_chat_history"] = []
            # Also clear the suggestion pills key to reset them
            st.session_state.pop("ai_suggestion_pills", None)
            st.rerun()
