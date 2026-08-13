"""Reusable filter widget builders — premium FP&A filter UX for the Group P&L dashboard.

Public API (unchanged):
  multiselect_with_all()
  render_sidebar_filters()
  render_sidebar_global_filters()
  get_filtered_months()
  get_compare_month()
  get_active_currency()
  get_fx_rate()
  convert_value()
  fmt_display()
  render_active_filter_bar()
  render_empty_state()
  validate_data_not_empty()
  drill_to_entity()

Session state keys written here (tabs must NOT be touched to consume them):
  month_start_idx, month_end_idx   → consumed by get_filtered_months()
  compare_mode                     → consumed by get_compare_month() and render_active_filter_bar()
  entity_filter / sidebar_entity_filter
  stream_filter / sidebar_stream_filter
  industry_filter / sidebar_industry_filter

New UI-only keys (zero impact on calculations):
  period_preset    → which preset pill is active
  compare_label    → display label for comparison control
"""

from __future__ import annotations

from datetime import datetime
from html import escape

import streamlit as st


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PRESETS: list[str] = [
    "Current month",
    "Previous month",
    "QTD",
    "YTD",
    "Last 3 months",
    "Last 6 months",
    "Last 12 months",
    "Previous year",
    "Custom",
]

_DEFAULT_PRESET: str = "Last 12 months"

# Comparison display labels ↔ internal compare_mode values
_COMPARE_LABELS: list[str] = ["Prior period", "Same period LY", "None"]
_LABEL_TO_MODE: dict[str, str] = {
    "Prior period": "Prior Month",
    "Same period LY": "Same Month LY",
    "None": "None",
}
_MODE_TO_LABEL: dict[str, str] = {v: k for k, v in _LABEL_TO_MODE.items()}


# ---------------------------------------------------------------------------
# Multiselect with All / None buttons  (public API — used by per_entity tab)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Internal — month parsing + preset resolver
# ---------------------------------------------------------------------------

def _parse_month(m: str) -> datetime:
    """Parse 'Jan 2025' → datetime(2025, 1, 1)."""
    return datetime.strptime(m, "%b %Y")


def _current_month_idx(month_options: list[str]) -> int:
    """Return the index of the current calendar month in month_options.

    Scans the list and returns the index whose year+month matches today.
    If today's month is not present (e.g. the workbook hasn't been updated
    yet), returns the index of the most recent *past* month available.
    Falls back to the last index if every month in the list is in the future.
    """
    now = datetime.now()
    current_ym = (now.year, now.month)
    best_idx = len(month_options) - 1  # fallback: last available
    for i, m in enumerate(month_options):
        try:
            dt = _parse_month(m)
            ym = (dt.year, dt.month)
            if ym == current_ym:
                return i          # exact match
            if ym < current_ym:
                best_idx = i      # track latest past month seen so far
        except (ValueError, AttributeError):
            continue
    return best_idx


def _apply_preset(preset: str, month_options: list[str]) -> tuple[int, int]:
    """Map a preset name to (start_idx, end_idx) for the given month list.

    Time-relative presets (Current month, YTD, Last N months, QTD, …) are
    anchored to the **current calendar month**, not the last row of the
    workbook.  This means selecting 'Current month' in August 2026 shows
    Aug 2026 even if the workbook contains forecast rows through Dec 2026.

    'Custom' preserves the current session state indices unchanged.
    """
    n = len(month_options)
    if n == 0:
        return 0, 0

    # Calendar anchor: the current real-world month (or closest past month).
    cal_idx = _current_month_idx(month_options)

    if preset == "Current month":
        return cal_idx, cal_idx

    if preset == "Previous month":
        idx = max(0, cal_idx - 1)
        return idx, idx

    if preset in ("Last 3 months", "Last 6 months", "Last 12 months"):
        back = {"Last 3 months": 3, "Last 6 months": 6, "Last 12 months": 12}[preset]
        return max(0, cal_idx - back + 1), cal_idx

    if preset == "YTD":
        try:
            current_year = _parse_month(month_options[cal_idx]).year
            for i, m in enumerate(month_options):
                if _parse_month(m).year == current_year:
                    return i, cal_idx
        except (ValueError, AttributeError):
            pass
        return 0, cal_idx

    if preset == "QTD":
        try:
            last_dt = _parse_month(month_options[cal_idx])
            q_start_month = ((last_dt.month - 1) // 3) * 3 + 1  # 1, 4, 7, or 10
            target_year = last_dt.year
            for i, m in enumerate(month_options):
                dt = _parse_month(m)
                if dt.year == target_year and dt.month == q_start_month:
                    return i, cal_idx
        except (ValueError, AttributeError):
            pass
        return max(0, cal_idx - 2), cal_idx  # ~3-month fallback

    if preset == "Previous year":
        try:
            cal_year = _parse_month(month_options[cal_idx]).year
            prev_year = cal_year - 1
            start: int | None = None
            py_end: int | None = None
            for i, m in enumerate(month_options):
                if _parse_month(m).year == prev_year:
                    if start is None:
                        start = i
                    py_end = i
            if start is not None and py_end is not None:
                return start, py_end
        except (ValueError, AttributeError):
            pass
        return 0, n - 1  # fallback: full range

    # Custom → preserve current state unchanged
    cur_start = max(0, min(int(st.session_state.get("month_start_idx", 0)), n - 1))
    cur_end = max(cur_start, min(int(st.session_state.get("month_end_idx", end_idx)), n - 1))
    return cur_start, cur_end


def _sidebar_section_header(label: str) -> None:
    """Render a compact uppercase section label in the sidebar."""
    from streamlit_app.constants import BLITZ_COLORS

    st.sidebar.markdown(
        f"<p style='font-size:10px;font-weight:700;letter-spacing:0.08em;"
        f"text-transform:uppercase;color:{BLITZ_COLORS['primary_hover']};"
        f"margin:0 0 4px 0;padding:10px 0 0 0;'>{label}</p>",
        unsafe_allow_html=True,
    )


def _resolve_compare_label(
    month_options: list[str], end_idx: int, mode: str
) -> str | None:
    """Return the human-readable name of the comparison month for a given mode."""
    if not month_options:
        return None

    if mode == "Prior Month":
        return month_options[end_idx - 1] if end_idx > 0 else None

    if mode == "Same Month LY":
        # Prefer a direct year-offset lookup so we get the right label
        try:
            end_dt = _parse_month(month_options[end_idx])
            target_str = end_dt.replace(year=end_dt.year - 1).strftime("%b %Y")
            if target_str in month_options:
                return target_str
        except (ValueError, AttributeError):
            pass
        # Fallback: 12 positions back in the list
        if end_idx >= 12:
            return month_options[end_idx - 12]

    return None


# ---------------------------------------------------------------------------
# Sidebar — Reporting period + Comparison
# ---------------------------------------------------------------------------

def render_sidebar_filters(month_options: list[str]) -> None:
    """Render global sidebar filters: period presets, custom range, and comparison control.

    Writes to:  month_start_idx, month_end_idx, compare_mode
    (UI-only):  period_preset, compare_label
    """
    if not month_options:
        return

    n = len(month_options)

    # ── REPORTING PERIOD ─────────────────────────────────────────────────
    st.sidebar.divider()
    _sidebar_section_header("Reporting period")

    # Initialise period_preset on first run
    st.session_state.setdefault("period_preset", _DEFAULT_PRESET)
    # Ensure period_preset is a valid option (guard against stale state after file re-upload)
    if st.session_state["period_preset"] not in _PRESETS:
        st.session_state["period_preset"] = _DEFAULT_PRESET

    preset: str = st.sidebar.pills(
        "Quick period select",
        options=_PRESETS,
        key="period_preset",
        label_visibility="collapsed",
    ) or _DEFAULT_PRESET  # type: ignore[assignment]

    # pills returns None if user deselects; restore gracefully
    if st.session_state.get("period_preset") is None:
        st.session_state["period_preset"] = _DEFAULT_PRESET
        preset = _DEFAULT_PRESET

    if preset == "Custom":
        # Initialise custom indices from the calendar-anchored current month
        # (not from n-1, which would default to the last forecast month)
        cal_default = _current_month_idx(month_options)
        st.session_state.setdefault("month_start_idx", cal_default)
        st.session_state.setdefault("month_end_idx", cal_default)
        cur_start = max(0, min(int(st.session_state["month_start_idx"]), n - 1))
        cur_end = max(cur_start, min(int(st.session_state["month_end_idx"]), n - 1))

        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_choice: str = st.selectbox(
                "Start month",
                options=month_options,
                index=cur_start,
                key="custom_start_month",
            )
        with col2:
            # End options are limited to months ≥ start (prevents invalid ranges)
            start_pos = month_options.index(start_choice)
            valid_ends = month_options[start_pos:]
            clamped_end_pos = max(0, min(cur_end - start_pos, len(valid_ends) - 1))
            end_choice: str = st.selectbox(
                "End month",
                options=valid_ends,
                index=clamped_end_pos,
                key="custom_end_month",
            )

        new_start = month_options.index(start_choice)
        new_end = month_options.index(end_choice)
        st.session_state["month_start_idx"] = new_start
        st.session_state["month_end_idx"] = new_end
        start_idx, end_idx = new_start, new_end

    else:
        # Non-custom preset: always compute fresh indices from the calendar anchor.
        # Also clear any stale custom widget keys so they don't bleed back in.
        for _k in ("custom_start_month", "custom_end_month"):
            st.session_state.pop(_k, None)
        start_idx, end_idx = _apply_preset(preset, month_options)
        st.session_state["month_start_idx"] = start_idx
        st.session_state["month_end_idx"] = end_idx

    # Period display card
    from streamlit_app.constants import BLITZ_COLORS

    start_label = month_options[start_idx]
    end_label = month_options[end_idx]
    n_months = end_idx - start_idx + 1
    range_str = f"{start_label} → {end_label}" if start_label != end_label else start_label
    months_str = f"{n_months} month{'s' if n_months != 1 else ''}"

    st.sidebar.markdown(
        f"<div style='background:{BLITZ_COLORS['pale_blue']};"
        f"border:1px solid {BLITZ_COLORS['light_blue']};border-radius:8px;"
        f"padding:8px 12px;margin:6px 0 0 0;'>"
        f"<div style='font-size:13px;font-weight:700;color:{BLITZ_COLORS['deep_blue']};'>"
        f"{escape(range_str)}</div>"
        f"<div style='font-size:10px;color:{BLITZ_COLORS['text_secondary']};margin-top:2px;'>"
        f"{escape(months_str)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── COMPARISON ───────────────────────────────────────────────────────
    _sidebar_section_header("Comparison")

    # Migrate existing compare_mode → compare_label on first run
    if "compare_label" not in st.session_state:
        existing_mode = st.session_state.get("compare_mode", "Prior Month")
        st.session_state["compare_label"] = _MODE_TO_LABEL.get(existing_mode, "Prior period")

    # Ensure compare_label is a valid option
    if st.session_state.get("compare_label") not in _COMPARE_LABELS:
        st.session_state["compare_label"] = "Prior period"

    compare_display: str = st.sidebar.segmented_control(
        "Compare to",
        options=_COMPARE_LABELS,
        key="compare_label",
    ) or "None"

    # Write the canonical compare_mode key consumed by all tab calculations
    st.session_state["compare_mode"] = _LABEL_TO_MODE.get(compare_display, "None")

    # Show the resolved comparison month below the control
    if compare_display != "None":
        cmp_label = _resolve_compare_label(
            month_options, end_idx, st.session_state["compare_mode"]
        )
        if cmp_label:
            st.sidebar.caption(f"vs **{cmp_label}**")


# ---------------------------------------------------------------------------
# Sidebar — Global entity / stream / industry filters
# ---------------------------------------------------------------------------

def render_sidebar_global_filters(
    entity_options: list[str],
    stream_options: list[str],
    industry_options: list[str],
    month_options: list[str],
) -> None:
    """Render global Entity / Stream / Industry filters in the sidebar.

    These write to the same session state keys the per-entity and per-client
    tabs already read, so selections here propagate automatically.
    """
    if not entity_options and not stream_options and not industry_options:
        return

    st.sidebar.divider()
    _sidebar_section_header("Business filters")

    # ── Entity filter ────────────────────────────────────────────────────
    if entity_options:
        _key = "sidebar_entity_filter"
        st.session_state.setdefault(_key, list(entity_options))
        current = [v for v in st.session_state[_key] if v in entity_options]
        if not current:
            current = list(entity_options)

        c1, c2, _ = st.sidebar.columns([1, 1, 2])
        with c1:
            if st.button("All", key="sidebar_entity_all", help="Select all entities"):
                st.session_state[_key] = list(entity_options)
                st.rerun()
        with c2:
            if st.button("None", key="sidebar_entity_none", help="Clear entities"):
                st.session_state[_key] = []
                st.rerun()

        widget_key = f"{_key}_widget"
        st.session_state.setdefault(widget_key, current)
        selected_entities = st.sidebar.multiselect(
            "Entity",
            options=entity_options,
            key=widget_key,
            help="Filter all tabs by entity",
        )
        st.session_state[_key] = selected_entities
        # Mirror to entity_filter used by per_entity and per_client tabs
        st.session_state["entity_filter"] = selected_entities

    # ── Revenue stream filter ────────────────────────────────────────────
    if stream_options:
        _key = "sidebar_stream_filter"
        st.session_state.setdefault(_key, list(stream_options))
        current_s = [v for v in st.session_state[_key] if v in stream_options]
        if not current_s:
            current_s = list(stream_options)

        widget_key_s = f"{_key}_widget"
        st.session_state.setdefault(widget_key_s, current_s)
        selected_streams = st.sidebar.multiselect(
            "Revenue stream",
            options=stream_options,
            key=widget_key_s,
            help="Filter all tabs by revenue stream",
        )
        st.session_state[_key] = selected_streams
        # Mirror to stream_filter used by per_client tab
        st.session_state["stream_filter"] = selected_streams

    # ── Industry filter ──────────────────────────────────────────────────
    if industry_options:
        _key = "sidebar_industry_filter"
        st.session_state.setdefault(_key, list(industry_options))
        current_i = [v for v in st.session_state[_key] if v in industry_options]
        if not current_i:
            current_i = list(industry_options)

        widget_key_i = f"{_key}_widget"
        st.session_state.setdefault(widget_key_i, current_i)
        selected_industries = st.sidebar.multiselect(
            "Industry",
            options=industry_options,
            key=widget_key_i,
            help="Filter all tabs by industry",
        )
        st.session_state[_key] = selected_industries
        st.session_state["industry_filter"] = selected_industries

    # ── Reset all filters ────────────────────────────────────────────────
    st.sidebar.divider()
    if st.sidebar.button(
        ":material/restart_alt: Reset all filters",
        key="reset_filters_btn",
    ):
        _reset_all_filters(month_options, entity_options, stream_options, industry_options)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

def _reset_all_filters(
    month_options: list[str],
    entity_options: list[str] | None = None,
    stream_options: list[str] | None = None,
    industry_options: list[str] | None = None,
) -> None:
    """Reset all session state filter keys to their defaults and rerun.

    Widget-backed keys (period_preset, compare_label, *_widget) must be
    **deleted** (not written-to) so Streamlit re-renders them fresh on the
    next run.  Pure computation keys (month_start_idx, month_end_idx,
    compare_mode) are safe to set directly.
    """
    # Compute default period indices from calendar anchor
    s, e = _apply_preset(_DEFAULT_PRESET, month_options)
    st.session_state["month_start_idx"] = s
    st.session_state["month_end_idx"] = e

    # Canonical comparison key (not widget-backed)
    st.session_state["compare_mode"] = "Prior Month"

    # Delete ALL widget-backed keys so their widgets re-initialise from the
    # setdefault() calls at the top of render_sidebar_filters on the next run.
    widget_backed_keys = [
        k for k in list(st.session_state.keys())
        if (
            k in ("period_preset", "compare_label")
            or k.endswith("_widget")
            or k.endswith("_all")
            or k.endswith("_none")
            or k in (
                "compare_mode_ctrl",
                "compare_mode_radio",
                "custom_start_month",
                "custom_end_month",
            )
        )
    ]
    for k in widget_backed_keys:
        st.session_state.pop(k, None)

    # Remove canonical filter keys (they re-initialise on next run)
    for key in (
        "entity_filter", "stream_filter", "industry_filter",
        "sidebar_entity_filter", "sidebar_stream_filter", "sidebar_industry_filter",
    ):
        st.session_state.pop(key, None)

    st.rerun()


# ---------------------------------------------------------------------------
# Date / month filter helpers  (public API — unchanged signatures)
# ---------------------------------------------------------------------------

def get_filtered_months(month_options: list[str]) -> list[str]:
    """Return the slice of months selected by the global period control."""
    if not month_options:
        return []
    start = int(st.session_state.get("month_start_idx", 0))
    end = int(st.session_state.get("month_end_idx", len(month_options) - 1))
    start = max(0, min(start, len(month_options) - 1))
    end = max(start, min(end, len(month_options) - 1))
    return month_options[start: end + 1]


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


# ---------------------------------------------------------------------------
# Currency helpers  (public API — unchanged)
# ---------------------------------------------------------------------------

def get_active_currency() -> str:
    """Return the currently selected currency: 'IDR' or 'USD'."""
    return str(st.session_state.get("currency", "IDR"))


def get_fx_rate() -> float:
    """Return the IDR→USD FX rate stored in session state (default 15000)."""
    return float(st.session_state.get("fx_rate", 15_000.0))


def convert_value(value: float) -> float:
    """Convert a value from IDR to the active currency."""
    if get_active_currency() == "USD":
        return value / get_fx_rate()
    return value


def fmt_display(value: float) -> str:
    """Format a value using compact notation for the active currency."""
    from streamlit_app.constants import IDR_SUFFIX_THRESHOLDS

    currency = get_active_currency()
    display_val = convert_value(value)
    prefix = "$" if currency == "USD" else "Rp"
    abs_val = abs(display_val)
    thresholds = IDR_SUFFIX_THRESHOLDS if currency == "IDR" else [
        (1_000_000_000, "B", 1_000_000_000),
        (1_000_000, "M", 1_000_000),
        (1_000, "K", 1_000),
    ]
    sign = "-" if display_val < 0 else ""
    for threshold, suffix, divisor in thresholds:
        if abs_val >= threshold:
            return f"{sign}{prefix}{abs_val / divisor:,.1f}{suffix}"
    return f"{sign}{prefix}{abs_val:,.0f}"


# ---------------------------------------------------------------------------
# Active filter summary bar  (public API — signature unchanged)
# ---------------------------------------------------------------------------

def render_active_filter_bar(
    filtered_months: list[str],
    tab_name: str = "",
    extra_chips: list[str] | None = None,
) -> None:
    """Render a one-line contextual bar showing exactly what is being analyzed.

    Primary chip (Blitz blue): the reporting period.
    Secondary chips (neutral): comparison, entity/stream/industry subsets, currency.
    """
    from streamlit_app.constants import BLITZ_COLORS

    if not filtered_months:
        return

    # ── Build chip list ──────────────────────────────────────────────────
    # Each chip is (text, is_primary)
    chips: list[tuple[str, bool]] = []

    # Reporting period — primary blue chip
    if len(filtered_months) == 1:
        date_text = filtered_months[0]
    else:
        date_text = f"{filtered_months[0]} → {filtered_months[-1]}"
    chips.append((date_text, True))

    # Comparison mode
    mode = st.session_state.get("compare_mode", "Prior Month")
    if mode != "None":
        mode_label = _MODE_TO_LABEL.get(mode, mode)
        chips.append((f"vs {mode_label}", False))

    # Entity filter — only if a subset is selected
    entities = st.session_state.get("entity_filter") or st.session_state.get("sidebar_entity_filter")
    all_entities = st.session_state.get("_all_entity_options", [])
    if entities is not None and all_entities and set(entities) != set(all_entities):
        if entities:
            ent_label = ", ".join(entities[:2]) + (f" +{len(entities) - 2}" if len(entities) > 2 else "")
            chips.append((f"Entity: {ent_label}", False))
        else:
            chips.append(("No entities", False))

    # Revenue stream filter
    streams = st.session_state.get("stream_filter") or st.session_state.get("sidebar_stream_filter")
    all_streams = st.session_state.get("_all_stream_options", [])
    if streams is not None and all_streams and set(streams) != set(all_streams):
        if streams:
            str_label = ", ".join(streams[:2]) + (f" +{len(streams) - 2}" if len(streams) > 2 else "")
            chips.append((f"Stream: {str_label}", False))

    # Industry filter
    industries = st.session_state.get("industry_filter") or st.session_state.get("sidebar_industry_filter")
    all_industries = st.session_state.get("_all_industry_options", [])
    if industries is not None and all_industries and set(industries) != set(all_industries):
        if industries:
            ind_label = ", ".join(industries[:2]) + (f" +{len(industries) - 2}" if len(industries) > 2 else "")
            chips.append((f"Industry: {ind_label}", False))

    # Currency — only mention if USD (IDR is the default expectation)
    currency = get_active_currency()
    if currency == "USD":
        fx = get_fx_rate()
        chips.append((f"USD @ Rp{int(fx):,}", False))

    # Extra caller-supplied chips
    if extra_chips:
        for c in extra_chips:
            chips.append((c, False))

    # ── Build HTML ───────────────────────────────────────────────────────
    _primary = (
        f"display:inline-flex;align-items:center;"
        f"background:{BLITZ_COLORS['pale_blue']};"
        f"border:1px solid {BLITZ_COLORS['light_blue']};"
        f"border-radius:20px;padding:3px 11px;"
        f"font-size:11.5px;font-weight:700;"
        f"color:{BLITZ_COLORS['deep_blue']};white-space:nowrap;"
    )
    _secondary = (
        f"display:inline-flex;align-items:center;"
        f"background:{BLITZ_COLORS['white']};"
        f"border:1px solid {BLITZ_COLORS['border']};"
        f"border-radius:20px;padding:3px 10px;"
        f"font-size:11px;font-weight:500;"
        f"color:{BLITZ_COLORS['text_secondary']};white-space:nowrap;"
    )

    chip_html = "".join(
        f"<span style='{_primary if primary else _secondary}'>{escape(text)}</span>"
        for text, primary in chips
    )

    viewing_label = (
        f"<span style='font-size:11px;color:{BLITZ_COLORS['text_secondary']};"
        f"font-weight:500;flex-shrink:0;'>Viewing:</span>"
    )

    st.markdown(
        f"<div style='display:flex;align-items:center;flex-wrap:wrap;gap:6px;"
        f"padding:8px 0 12px;border-bottom:1px solid {BLITZ_COLORS['border']};"
        f"margin-bottom:14px;'>"
        f"{viewing_label} {chip_html}</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Empty state renderer  (public API — signature unchanged)
# ---------------------------------------------------------------------------

def render_empty_state(
    title: str = "No data available for the selected period.",
    suggestion: str = "Try expanding the date range or adjusting the filters.",
    icon: str = "📭",
    show_reset: bool = True,
    key_suffix: str = "",
) -> None:
    """Render a premium empty state with icon, message, and optional reset button."""
    from streamlit_app.constants import BLITZ_COLORS

    st.markdown(
        f"""
        <div style='text-align:center;padding:40px 24px;background:{BLITZ_COLORS["background"]};
            border:1.5px dashed {BLITZ_COLORS["border"]};border-radius:12px;margin:12px 0;'>
          <div style='font-size:36px;margin-bottom:12px;'>{icon}</div>
          <div style='font-size:15px;font-weight:700;color:{BLITZ_COLORS["text_primary"]};
              margin-bottom:6px;'>{title}</div>
          <div style='font-size:12px;color:{BLITZ_COLORS["text_secondary"]};
              max-width:380px;margin:0 auto;line-height:1.6;'>{suggestion}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if show_reset:
        col_reset = st.columns([1, 1, 1])[1]
        with col_reset:
            if st.button(
                ":material/restart_alt: Reset filters",
                key=f"empty_reset_{key_suffix}",
                width="stretch",
            ):
                # Clear all period / filter / preset keys so they reinitialise
                for k in list(st.session_state.keys()):
                    if any(
                        k.startswith(p)
                        for p in [
                            "month_", "compare_", "entity_", "stream_",
                            "industry_", "sidebar_", "period_",
                            "custom_start", "custom_end",
                        ]
                    ):
                        st.session_state.pop(k, None)
                st.rerun()


# ---------------------------------------------------------------------------
# Filter validation  (public API — signature unchanged)
# ---------------------------------------------------------------------------

def validate_data_not_empty(
    df_or_list: "pd.DataFrame | list",  # type: ignore[name-defined]
    context: str = "the selected filters",
    suggestion: str = "Try expanding the date range or adjusting the filters in the sidebar.",
    key_suffix: str = "",
) -> bool:
    """Return True if data is non-empty. If empty, render a validation message and return False.

    Usage::

        if not validate_data_not_empty(df, context="the selected entity + stream"):
            return

    """
    import pandas as pd

    is_empty = (
        df_or_list.empty if isinstance(df_or_list, pd.DataFrame)
        else len(df_or_list) == 0
    )
    if is_empty:
        render_empty_state(
            title=f"No data found for {context}.",
            suggestion=suggestion,
            icon="🔍",
            show_reset=True,
            key_suffix=key_suffix,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Cross-filter drill helpers  (public API — unchanged)
# ---------------------------------------------------------------------------

def drill_to_entity(entity: str) -> None:
    """Write entity to session state so Per-Entity tab pre-filters to it."""
    from streamlit_app.constants import ENTITY_SUMMARY_SHEETS
    all_entities = list(ENTITY_SUMMARY_SHEETS.keys())
    st.session_state["entity_filter"] = [entity] if entity in all_entities else all_entities
    st.session_state["sidebar_entity_filter"] = st.session_state["entity_filter"]
    # Also clear widget keys so they re-initialise cleanly
    for k in ["sidebar_entity_filter_widget", "entity_filter_widget", "entity_selector_widget"]:
        st.session_state.pop(k, None)
