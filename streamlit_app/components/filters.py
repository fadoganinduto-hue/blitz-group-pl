"""Reusable filter widget builders with Select All / Clear All support."""

from __future__ import annotations

import streamlit as st


def multiselect_with_all(
    label: str,
    options: list[str],
    key: str,
    default: list[str] | None = None,
) -> list[str]:
    """Render a multiselect with Select All and Clear All buttons; persists via session state.

    Returns the currently selected list of values.
    """
    if key not in st.session_state:
        st.session_state[key] = default if default is not None else list(options)

    # Keep selected values that are still valid options (options may change with filters)
    current = [v for v in st.session_state[key] if v in options]
    if not current and options:
        current = list(options)
        st.session_state[key] = current

    btn_col1, btn_col2, _ = st.columns([1, 1, 4])
    with btn_col1:
        if st.button("All", key=f"{key}_all", help=f"Select all {label}"):
            st.session_state[key] = list(options)
            st.session_state[f"{key}_widget"] = list(options)
            st.rerun()
    with btn_col2:
        if st.button("None", key=f"{key}_none", help=f"Clear all {label}"):
            st.session_state[key] = []
            st.session_state[f"{key}_widget"] = []
            st.rerun()

    # Pre-initialise the widget key only when absent (avoids 'conflicting sources' warning)
    widget_key = f"{key}_widget"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = current

    selected: list[str] = st.multiselect(label, options=options, key=widget_key)
    # Sync widget value back to the canonical session state key
    st.session_state[key] = selected
    return selected


def render_sidebar_filters(month_options: list[str]) -> None:
    """Render global sidebar filters: date range slider and comparison mode toggle."""
    st.sidebar.divider()
    st.sidebar.subheader(":material/tune: Filters")

    if not month_options:
        return

    n = len(month_options)
    # Initialize session state defaults
    st.session_state.setdefault("month_start_idx", 0)
    st.session_state.setdefault("month_end_idx", n - 1)
    st.session_state.setdefault("compare_mode", "Prior Month")

    start_idx, end_idx = st.sidebar.select_slider(
        "Month range",
        options=list(range(n)),
        value=(
            st.session_state["month_start_idx"],
            st.session_state["month_end_idx"],
        ),
        format_func=lambda i: month_options[i],
        key="month_range_slider",
    )
    start_idx = int(start_idx)
    end_idx = int(end_idx)
    st.session_state["month_start_idx"] = start_idx
    st.session_state["month_end_idx"] = end_idx

    compare_mode = st.sidebar.segmented_control(
        "Compare to",
        options=["Prior Month", "Same Month LY", "None"],
        default=st.session_state["compare_mode"],
        key="compare_mode_ctrl",
    )
    st.session_state["compare_mode"] = compare_mode or "None"

    if st.sidebar.button(":material/restart_alt: Reset all filters", key="reset_filters_btn"):
        _reset_all_filters(month_options)


def _reset_all_filters(month_options: list[str]) -> None:
    """Reset all session state filter keys to their defaults."""
    n = len(month_options)
    st.session_state["month_start_idx"] = 0
    st.session_state["month_end_idx"] = n - 1
    st.session_state["compare_mode"] = "Prior Month"
    # Reset multiselect canonical keys
    for key in ["entity_filter", "stream_filter", "industry_filter"]:
        if key in st.session_state:
            del st.session_state[key]
    # Remove all derived widget keys so widgets re-initialise on next render
    widget_keys_to_clear = [
        k for k in list(st.session_state.keys())
        if k.endswith("_widget") or k.endswith("_all") or k.endswith("_none")
        or k in ("month_range_slider", "compare_mode_ctrl")
    ]
    for k in widget_keys_to_clear:
        del st.session_state[k]


def get_filtered_months(month_options: list[str]) -> list[str]:
    """Return the slice of months selected by the global date range slider."""
    start = st.session_state.get("month_start_idx", 0)
    end = st.session_state.get("month_end_idx", len(month_options) - 1)
    return month_options[start : end + 1]


def get_compare_month(
    month_options: list[str],
    current_month: str,
    all_months_sorted: list[str],
) -> str | None:
    """Return the comparison month based on the active compare_mode setting."""
    mode = st.session_state.get("compare_mode", "Prior Month")
    if mode == "None" or not current_month:
        return None

    try:
        idx = all_months_sorted.index(current_month)
    except ValueError:
        return None

    if mode == "Prior Month":
        return all_months_sorted[idx - 1] if idx > 0 else None

    if mode == "Same Month LY":
        return all_months_sorted[idx - 12] if idx >= 12 else None

    return None
