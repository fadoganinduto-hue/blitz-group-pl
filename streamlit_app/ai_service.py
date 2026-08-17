"""AI service layer — Gemini client, data context builder, and prompt functions."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

# The AI tab is optional. Importing google-genai at module scope made a missing
# or broken install crash the ENTIRE dashboard at startup (app.py imports this
# module for its sidebar status line), taking the P&L views down with it.
try:  # pragma: no cover - exercised by environments without the extra
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
    GENAI_IMPORT_ERROR: str | None = None
except Exception as _exc:  # noqa: BLE001
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]
    GENAI_AVAILABLE = False
    GENAI_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

from streamlit_app.constants import fmt_idr
from streamlit_app.data.parsers import (
    parse_master,
    parse_pl_sheet,
    parse_ratios,
    parse_tie_out,
)

# ---------------------------------------------------------------------------
# Gemini client
# ---------------------------------------------------------------------------

_MODEL = "gemini-2.5-flash"
ANOMALY_THRESHOLD_PCT = 15.0


def _get_api_key() -> str | None:
    """Return the Gemini API key from Streamlit secrets, or None."""
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
        if key and key != "your-api-key-here":
            return str(key)
    except Exception:  # noqa: BLE001
        pass
    return None


def is_api_configured() -> bool:
    """Check whether the AI tab can run: package installed AND key present."""
    return GENAI_AVAILABLE and _get_api_key() is not None


@st.cache_resource(show_spinner=False)
def _get_client(api_key: str) -> Any:
    """Return a cached Gemini client instance."""
    return genai.Client(api_key=api_key)


def _client() -> genai.Client:
    """Convenience accessor for the Gemini client."""
    key = _get_api_key()
    if not key:
        raise ValueError("Gemini API key is not configured.")
    return _get_client(key)


# ---------------------------------------------------------------------------
# Data context builder
# ---------------------------------------------------------------------------

def _safe_metric_val(df: pd.DataFrame, metric: str, month: str) -> float | None:
    """Return summed value for a metric in a month, or None."""
    rows = df[(df["Metric"] == metric) & (df["Month"] == month)]
    return float(rows["Value"].sum(skipna=True)) if not rows.empty else None


def prepare_data_context(
    sheets: dict[str, pd.DataFrame],
    filtered_months: list[str] | None = None,
    comparison_period: str | None = None,
    wb_hash: str | None = None,
) -> str:
    """Convert parsed P&L DataFrames into a structured JSON payload for the LLM.

    The output is a strict JSON summary of the financial data
    that fits comfortably within the model's context window.
    """
    context_data = {
        "period": filtered_months,
        "comparison_period": comparison_period,
        "workbook_hash": wb_hash,
        "group_kpis": {},
        "entities": {},
        "client_concentration": {},
        "data_health": {}
    }

    # ── 1. Consolidated P&L ──────────────────────────────────────────────
    raw_cons = sheets.get("Consolidated Summary")
    if raw_cons is not None:
        cons = parse_pl_sheet(raw_cons, "Consolidated")
        if not cons.empty:
            all_months = cons.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
            months = filtered_months or all_months
            months = [m for m in months if m in all_months]

            key_metrics = [
                "Total Gross Revenue", "Total COGS", "Gross Profit 2",
                "Total Operating Expenses", "EBITDA", "NET PROFIT/LOSS (Before Tax)",
            ]
            
            for metric in key_metrics:
                context_data["group_kpis"][metric] = {}
                for m in months:
                    v = _safe_metric_val(cons, metric, m)
                    if v is not None:
                        context_data["group_kpis"][metric][m] = v
            
            # Ratios
            ratios = parse_ratios(raw_cons, "Consolidated")
            if not ratios.empty:
                context_data["group_kpis"]["Ratios"] = {}
                for ratio_name in ratios["Metric"].unique():
                    context_data["group_kpis"]["Ratios"][ratio_name] = {}
                    for m in months:
                        r = ratios[(ratios["Metric"] == ratio_name) & (ratios["Month"] == m)]
                        if not r.empty:
                            context_data["group_kpis"]["Ratios"][ratio_name][m] = float(r['Value'].iloc[0])

    # ── 2. Per-entity summaries ──────────────────────────────────────────
    from streamlit_app.constants import ENTITY_SUMMARY_SHEETS
    for entity, sheet_name in ENTITY_SUMMARY_SHEETS.items():
        raw = sheets.get(sheet_name)
        if raw is None:
            continue
        df = parse_pl_sheet(raw, entity)
        if df.empty:
            continue
        all_m = df.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
        months = filtered_months or all_m
        months = [m for m in months if m in all_m]
        if not months:
            continue

        context_data["entities"][entity] = {"Revenue": {}, "EBITDA": {}}
        for m in months[-6:]:  # Last 6 months
            rv = _safe_metric_val(df, "Total Gross Revenue", m)
            ev = _safe_metric_val(df, "EBITDA", m)
            if rv is not None:
                context_data["entities"][entity]["Revenue"][m] = rv
            if ev is not None:
                context_data["entities"][entity]["EBITDA"][m] = ev

    # ── 3. Client concentration from MASTER ──────────────────────────────
    raw_master = sheets.get("MASTER")
    if raw_master is not None:
        master, missing = parse_master(raw_master)
        if not missing and not master.empty:
            total = master["Amount (IDR)"].sum()
            top10 = master.groupby("Client (clean)")["Amount (IDR)"].sum().nlargest(10)
            
            context_data["client_concentration"]["total_revenue_all_time"] = float(total)
            context_data["client_concentration"]["top_10"] = {}
            for client_name, client_rev in top10.items():
                context_data["client_concentration"]["top_10"][client_name] = float(client_rev)
                
            ind_rev = master.groupby("Industry")["Amount (IDR)"].sum().sort_values(ascending=False)
            context_data["client_concentration"]["by_industry"] = {ind: float(val) for ind, val in ind_rev.head(8).items()}
            
            stream_rev = master.groupby("Rev Stream")["Amount (IDR)"].sum().sort_values(ascending=False)
            context_data["client_concentration"]["by_stream"] = {st: float(val) for st, val in stream_rev.head(8).items()}

    # Section 4 previously summarised the TIE-OUT CHECK sheet. That sheet is
    # being retired, and reconciliation context now comes from the derived
    # MASTER-vs-P&L bridge instead of a hand-maintained worksheet.


    return json.dumps(context_data, indent=2)


# ---------------------------------------------------------------------------
# AI prompt functions
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTION = (
    "You are a senior financial analyst reviewing a Group P&L (Profit & Loss) dashboard "
    "for a holding company with three subsidiaries: Blitz, Borzo, and TheLorry. "
    "All monetary values are in Indonesian Rupiah (IDR) unless stated otherwise. "
    "Provide insightful, data-driven analysis. Be specific — reference actual numbers, "
    "months, and entities. Use bullet points for clarity.\n\n"
    "STRICT FACTUAL HIERARCHY:\n"
    "1. OBSERVED FACT: Directly computed from data.\n"
    "2. DERIVED FACT: Mathematically derived from available data.\n"
    "3. INTERPRETATION: Cautious interpretation supported by evidence.\n"
    "4. HYPOTHESIS: Clearly labeled as a possibility.\n"
    "Never present Level 3/4 as Level 1. Do not invent budgets, forecasts, market events, "
    "management actions, or causes if they aren't explicitly in the data. "
    "If the data is insufficient to answer a question, say so clearly."
)


@st.cache_data(show_spinner=False)
def generate_executive_summary(
    data_context: str,
    latest_month: str,
) -> str:
    """Generate an AI executive summary for the latest month."""
    prompt = f"""Based on the following JSON financial data, write a concise executive summary 
for the month of **{latest_month}**. Structure it as:

1. **What changed?** — One sentence capturing the key takeaway.
2. **How material was it?** — Quantify the main changes in revenue and profit.
3. **What were the main drivers?** — Which entities, streams, or clients drove this?
4. **What is the largest risk?** — Client concentration, margins, or data quality concerns.
5. **What deserves management attention?** — 2 actionable recommendations.

Keep it to ~300 words. Be direct and specific.
At the very end, generate 2-3 specific follow-up questions based on this exact data state 
that the user could ask to dig deeper (e.g. 'Which clients drove the decline in Blitz?').

---
DATA:
{data_context}
"""
    response = _client().models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            temperature=0.3,
        ),
    )
    return response.text or "No summary generated."


@st.cache_data(show_spinner=False)
def detect_anomalies(data_context: str) -> str:
    """Detect anomalies and unusual patterns in the financial data."""
    prompt = f"""Analyze the following JSON financial data and identify anomalies, unusual patterns, 
or items that need management attention. For each finding:

- **What**: Describe the anomaly clearly
- **Where**: Which entity, metric, or time period
- **Severity**: 🔴 High / 🟡 Medium / 🟢 Low
- **Impact**: Estimated financial impact or risk
- **Suggested Action**: What should management do

Look for:
- Revenue spikes or drops > {ANOMALY_THRESHOLD_PCT}% MoM
- Margin compression or expansion
- Cost items growing faster than revenue
- Client concentration changes
- Data quality / reconciliation issues
- Entity-level divergence from group trends

Be specific with numbers. Only flag real issues visible in the data.

---
DATA:
{data_context}
"""
    response = _client().models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            temperature=0.2,
        ),
    )
    return response.text or "No anomalies detected."


def chat_with_data_stream(
    data_context: str,
    user_question: str,
    chat_history: list[dict[str, str]],
):
    """Stream a response to a user question about the financial data.

    Yields text chunks for use with st.write_stream.
    """
    # Build conversation messages
    history_text = ""
    if chat_history:
        history_text = "\n\nPrevious conversation:\n"
        for msg in chat_history[-10:]:  # Keep last 10 messages for context
            role = "User" if msg["role"] == "user" else "Assistant"
            history_text += f"{role}: {msg['content']}\n"

    prompt = f"""Answer the user's question about the financial data below. 
Be specific and reference actual numbers. If the data doesn't contain enough 
information to answer fully, say so.
{history_text}
---
FINANCIAL DATA:
{data_context}

---
USER QUESTION: {user_question}
"""
    response_stream = _client().models.generate_content_stream(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            temperature=0.4,
        ),
    )
    for chunk in response_stream:
        if chunk.text:
            yield chunk.text
