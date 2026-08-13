"""AI service layer — Gemini client, data context builder, and prompt functions."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

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
    """Check whether a valid Gemini API key is present."""
    return _get_api_key() is not None


@st.cache_resource(show_spinner=False)
def _get_client(api_key: str) -> genai.Client:
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
) -> str:
    """Convert parsed P&L DataFrames into a concise text summary for the LLM.

    The output is a structured, token-efficient summary of the financial data
    that fits comfortably within the model's context window.
    """
    sections: list[str] = []

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
            lines = ["## Consolidated P&L (IDR)"]
            lines.append(f"Months in dataset: {', '.join(all_months)}")
            lines.append(f"Filtered months: {', '.join(months)}")
            lines.append("")

            for metric in key_metrics:
                vals = []
                for m in months:
                    v = _safe_metric_val(cons, metric, m)
                    vals.append(f"{m}: {fmt_idr(v)}" if v is not None else f"{m}: N/A")
                lines.append(f"**{metric}**: {' | '.join(vals)}")

            # MoM changes for the latest two months
            if len(months) >= 2:
                latest, prior = months[-1], months[-2]
                lines.append(f"\n### MoM changes ({prior} → {latest}):")
                for metric in key_metrics:
                    cur = _safe_metric_val(cons, metric, latest)
                    prev = _safe_metric_val(cons, metric, prior)
                    if cur is not None and prev is not None and prev != 0:
                        pct = (cur - prev) / abs(prev) * 100
                        lines.append(f"- {metric}: {pct:+.1f}% ({fmt_idr(prev)} → {fmt_idr(cur)})")

            sections.append("\n".join(lines))

            # Ratios
            ratios = parse_ratios(raw_cons, "Consolidated")
            if not ratios.empty:
                ratio_lines = ["\n## Margin Ratios"]
                for ratio_name in ratios["Metric"].unique():
                    r_vals = []
                    for m in months:
                        r = ratios[(ratios["Metric"] == ratio_name) & (ratios["Month"] == m)]
                        if not r.empty:
                            r_vals.append(f"{m}: {float(r['Value'].iloc[0]) * 100:.1f}%")
                    if r_vals:
                        ratio_lines.append(f"**{ratio_name}**: {' | '.join(r_vals)}")
                sections.append("\n".join(ratio_lines))

    # ── 2. Per-entity summaries ──────────────────────────────────────────
    from streamlit_app.constants import ENTITY_SUMMARY_SHEETS
    entity_lines = ["\n## Per-Entity Revenue & EBITDA"]
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

        rev_vals = []
        ebitda_vals = []
        for m in months[-6:]:  # Last 6 months to keep context tight
            rv = _safe_metric_val(df, "Total Gross Revenue", m)
            ev = _safe_metric_val(df, "EBITDA", m)
            rev_vals.append(f"{m}: {fmt_idr(rv)}" if rv is not None else f"{m}: N/A")
            ebitda_vals.append(f"{m}: {fmt_idr(ev)}" if ev is not None else f"{m}: N/A")

        entity_lines.append(f"\n### {entity}")
        entity_lines.append(f"Revenue: {' | '.join(rev_vals)}")
        entity_lines.append(f"EBITDA: {' | '.join(ebitda_vals)}")

    if len(entity_lines) > 1:
        sections.append("\n".join(entity_lines))

    # ── 3. Client concentration from MASTER ──────────────────────────────
    raw_master = sheets.get("MASTER")
    if raw_master is not None:
        master, missing = parse_master(raw_master)
        if not missing and not master.empty:
            client_lines = ["\n## Client Concentration"]
            total = master["Amount (IDR)"].sum()
            top10 = master.groupby("Client (clean)")["Amount (IDR)"].sum().nlargest(10)
            if total > 0:
                client_lines.append(f"Total revenue (all-time): {fmt_idr(total)}")
                client_lines.append(f"Top-10 clients ({top10.sum() / total * 100:.1f}% of total):")
                for client_name, client_rev in top10.items():
                    pct = client_rev / total * 100
                    client_lines.append(f"  - {client_name}: {fmt_idr(client_rev)} ({pct:.1f}%)")

            # Industry breakdown
            ind_rev = master.groupby("Industry")["Amount (IDR)"].sum().sort_values(ascending=False)
            if not ind_rev.empty:
                client_lines.append("\nRevenue by Industry:")
                for ind, val in ind_rev.head(8).items():
                    client_lines.append(f"  - {ind}: {fmt_idr(val)}")

            # Revenue stream breakdown
            stream_rev = master.groupby("Rev Stream")["Amount (IDR)"].sum().sort_values(ascending=False)
            if not stream_rev.empty:
                client_lines.append("\nRevenue by Stream:")
                for stream, val in stream_rev.head(8).items():
                    client_lines.append(f"  - {stream}: {fmt_idr(val)}")

            sections.append("\n".join(client_lines))

    # ── 4. Data quality (TIE-OUT CHECK) ──────────────────────────────────
    raw_tie = sheets.get("TIE-OUT CHECK")
    if raw_tie is not None:
        tie = parse_tie_out(raw_tie)
        if not tie.empty:
            flagged = tie[tie["Delta"].abs() > 1_000_000]
            quality_lines = ["\n## Data Quality (TIE-OUT CHECK)"]
            quality_lines.append(f"Total reconciliation rows: {len(tie)}")
            quality_lines.append(f"Flagged rows (|delta| > Rp1M): {len(flagged)}")
            if not flagged.empty:
                quality_lines.append("Largest discrepancies:")
                for _, row in flagged.nlargest(5, "Delta").iterrows():
                    quality_lines.append(
                        f"  - {row['Label']} ({row['Month']}): {fmt_idr(row['Delta'])}"
                    )
            sections.append("\n".join(quality_lines))

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# AI prompt functions
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTION = (
    "You are a senior financial analyst reviewing a Group P&L (Profit & Loss) dashboard "
    "for a holding company with three subsidiaries: Blitz, Borzo, and TheLorry. "
    "All monetary values are in Indonesian Rupiah (IDR) unless stated otherwise. "
    "Provide insightful, data-driven analysis. Be specific — reference actual numbers, "
    "months, and entities. Use bullet points for clarity. "
    "If the data is insufficient to answer a question, say so clearly."
)


def generate_executive_summary(
    data_context: str,
    latest_month: str,
) -> str:
    """Generate an AI executive summary for the latest month."""
    prompt = f"""Based on the following financial data, write a concise executive summary 
for the month of **{latest_month}**. Structure it as:

1. **Headline** — One sentence capturing the key takeaway
2. **Revenue Performance** — Consolidated and per-entity revenue trends
3. **Profitability** — EBITDA and net profit analysis, margin movements
4. **Cost Analysis** — Key cost drivers (COGS, OpEx) and any notable changes
5. **Risk Flags** — Client concentration, data quality issues, any concerns
6. **Recommendation** — 2-3 actionable items for management

Keep it to ~300 words. Be direct and specific.

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


def detect_anomalies(data_context: str) -> str:
    """Detect anomalies and unusual patterns in the financial data."""
    prompt = f"""Analyze the following financial data and identify anomalies, unusual patterns, 
or items that need management attention. For each finding:

- **What**: Describe the anomaly clearly
- **Where**: Which entity, metric, or time period
- **Severity**: 🔴 High / 🟡 Medium / 🟢 Low
- **Impact**: Estimated financial impact or risk
- **Suggested Action**: What should management do

Look for:
- Revenue spikes or drops > 15% MoM
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
