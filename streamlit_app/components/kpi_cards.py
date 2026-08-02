"""Reusable KPI card row renderer using st.metric with sparklines."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.constants import fmt_idr, fmt_idr_full


def render_kpi_row(
    df: pd.DataFrame,
    metrics: list[str],
    latest_month: str,
    prior_month: str | None,
    entity: str = "Consolidated",
) -> None:
    """Render a horizontal row of st.metric cards, one per metric, with MoM delta and sparkline."""
    with st.container(horizontal=True):
        for metric in metrics:
            metric_df = df[df["Metric"] == metric].sort_values("MonthDate")
            latest_row = metric_df[metric_df["Month"] == latest_month]

            if latest_row.empty:
                st.metric(metric, "N/A", border=True)
                continue

            current_val = float(latest_row["Value"].sum())

            # Delta vs prior month
            delta_str: str | None = None
            if prior_month:
                prior_row = metric_df[metric_df["Month"] == prior_month]
                if not prior_row.empty:
                    prior_val = float(prior_row["Value"].sum())
                    if prior_val != 0:
                        delta_pct = (current_val - prior_val) / abs(prior_val) * 100
                        delta_str = f"{delta_pct:+.1f}%"

            # Sparkline: aggregate by MonthDate to ensure 1 point per month, then take last 12
            agg_df = metric_df.groupby("MonthDate", as_index=False)["Value"].sum().sort_values("MonthDate")
            sparkline_vals: list[float] = [float(v) for v in agg_df["Value"].tail(12).tolist()]

            st.metric(
                label=metric,
                value=fmt_idr(current_val),
                delta=delta_str,
                help=f"{fmt_idr_full(current_val)} as of {latest_month}",
                border=True,
                chart_data=sparkline_vals if len(sparkline_vals) > 1 else None,
                chart_type="line",
            )


def render_single_kpi(
    label: str,
    value: float | None,
    delta_str: str | None = None,
    help_text: str | None = None,
    sparkline: list[float] | None = None,
) -> None:
    """Render a single bordered st.metric card with optional sparkline."""
    st.metric(
        label=label,
        value=fmt_idr(value) if value is not None else "N/A",
        delta=delta_str,
        help=help_text,
        border=True,
        chart_data=sparkline if sparkline and len(sparkline) > 1 else None,
        chart_type="line",
    )
