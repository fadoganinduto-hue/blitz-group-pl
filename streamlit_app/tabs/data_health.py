"""Data Health tab — reconciliation deltas from TIE-OUT CHECK sheet."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.constants import TIE_OUT_FLAG_THRESHOLD, fmt_idr, fmt_idr_full
from streamlit_app.data.parsers import parse_tie_out


def render(sheets: dict[str, pd.DataFrame]) -> None:
    """Render the Data Health (TIE-OUT CHECK) tab."""
    st.caption(
        "This tab surfaces the TIE-OUT CHECK sheet: reconciliation deltas between MASTER totals, "
        "Revenue Tracker, and Group P&L by entity and month. "
        f"Cells where |delta| > {fmt_idr_full(TIE_OUT_FLAG_THRESHOLD)} are flagged in red."
    )
    st.write("")

    raw = sheets.get("TIE-OUT CHECK")
    if raw is None:
        st.warning(":material/warning: 'TIE-OUT CHECK' sheet not found in this workbook.")
        return

    df = parse_tie_out(raw)
    if df.empty:
        st.warning(
            "Could not parse reconciliation data from 'TIE-OUT CHECK'. "
            "The sheet may have an unexpected layout — check that month headers appear in one of "
            "the first 10 rows with at least 3 consecutive month columns."
        )
        return

    # ---- Filters -------------------------------------------------------
    col_ent, col_thresh = st.columns([1, 2], gap="medium")
    with col_ent:
        all_labels = sorted(df["Label"].dropna().unique())
        selected_labels = st.multiselect(
            "Filter rows",
            all_labels,
            default=all_labels,
            key="health_label_filter",
            help="Filter to specific reconciliation rows",
        )
        if selected_labels:
            df = pd.DataFrame(df[df["Label"].isin(selected_labels)])
    with col_thresh:
        threshold = st.slider(
            "Flag threshold (IDR)",
            min_value=0,
            max_value=10_000_000,
            value=int(TIE_OUT_FLAG_THRESHOLD),
            step=100_000,
            format="Rp%d",
            key="health_threshold_slider",
            help="Flag reconciliation gaps above this amount",
        )
    st.write("")

    # ---- Summary metrics -----------------------------------------------
    _render_summary(df, threshold)

    # ---- Flagged rows --------------------------------------------------
    _render_flagged(df, threshold)

    # ---- Full table ----------------------------------------------------
    st.write("")
    with st.expander(":material/table_chart: Full reconciliation table", expanded=False):
        _render_full_table(df)


def _render_summary(df: pd.DataFrame, threshold: float) -> None:
    """Render KPI-style summary: total rows, flagged rows, largest delta."""
    flagged = df[df["Delta"].abs() > threshold]
    largest_delta = df["Delta"].abs().max() if not df.empty else 0

    with st.container(horizontal=True):
        st.metric("Total reconciliation rows", value=str(len(df)), border=True)
        st.metric(
            "Flagged rows (|delta| > threshold)",
            value=str(len(flagged)),
            delta=None,
            border=True,
            help=f"Threshold: {fmt_idr_full(threshold)}",
        )
        st.metric(
            "Largest |delta|",
            value=fmt_idr_full(largest_delta) if largest_delta else "0",
            border=True,
        )
    st.write("")


def _render_flagged(df: pd.DataFrame, threshold: float) -> None:
    """Render a table of only the flagged (above-threshold) rows."""
    st.markdown(f"##### :material/flag: Flagged months (|delta| > {fmt_idr_full(threshold)})")
    
    flagged = df[df["Delta"].abs() > threshold].copy()
    if flagged.empty:
        st.success("No reconciliation gaps above the threshold — all months tie out!", icon=":material/check_circle:")
        return

    flagged["Delta (IDR)"] = flagged["Delta"].apply(fmt_idr_full)
    flagged["|Delta|"] = flagged["Delta"].abs()
    display = flagged[["Label", "Month", "Delta (IDR)", "|Delta|"]].sort_values("|Delta|", ascending=False)

    def _style_row(row: pd.Series) -> list[str]:
        style = "background-color: rgba(248, 113, 113, 0.15); color: #F87171; font-weight: 500;" if row["|Delta|"] > threshold else ""
        return [style] * len(row)

    # Apply style before hiding the helper column so _style_row can reference it
    styled = display.style.apply(_style_row, axis=1)
    st.dataframe(
        styled,
        hide_index=True,
        column_config={"|Delta|": None},  # hide the helper column from the UI
        use_container_width=True
    )


def _render_full_table(df: pd.DataFrame) -> None:
    """Render the complete reconciliation table as a pivot (Label × Month)."""
    if df.empty:
        return

    try:
        month_order = df.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
        pivot = df.pivot_table(index="Label", columns="Month", values="Delta", aggfunc="sum")
        pivot = pivot[[m for m in month_order if m in pivot.columns]]

        def _color_cell(v: object) -> str:
            try:
                fv = float(v)  # type: ignore[arg-type]
                if abs(fv) > TIE_OUT_FLAG_THRESHOLD:
                    return "background-color: rgba(248, 113, 113, 0.15); color: #F87171; font-weight: 500;"
            except (TypeError, ValueError):
                pass
            return ""

        styled = pivot.style.map(_color_cell).format(
            lambda v: fmt_idr_full(v) if isinstance(v, (int, float)) else ""
        )
        st.dataframe(styled, use_container_width=True)
    except Exception:  # noqa: BLE001
        st.dataframe(df[["Label", "Month", "Delta"]], hide_index=True, use_container_width=True)
