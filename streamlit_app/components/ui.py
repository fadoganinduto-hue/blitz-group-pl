"""Shared presentation primitives for the executive financial dashboard."""

from __future__ import annotations

import base64
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Callable, Generator

import pandas as pd
import streamlit as st


from streamlit_app.constants import BLITZ_COLORS


_HEALTH_COLORS = {
    "Healthy": "#1A7F37",
    "Attention": "#BF8700",
    "Critical": "#CF222E",
}

ENTITY_COLORS_BI = {
    "Blitz": BLITZ_COLORS["primary"],
    "Borzo": "#E85D04",    # distinct orange
    "TheLorry": "#2D6A4F", # distinct green
    "Consolidated": BLITZ_COLORS["text_primary"],
}

STREAM_COLORS_BI = {
    "3PL": BLITZ_COLORS["primary"],
    "Freight": BLITZ_COLORS["primary_hover"],
    "Mobile Selling": BLITZ_COLORS["deep_blue"],
    "EV Leasing": BLITZ_COLORS["light_blue"],
    "COD": BLITZ_COLORS["text_secondary"],
    "Other": BLITZ_COLORS["border"],
}


def apply_global_visual_system() -> None:
    """Apply the restrained interaction and component treatment used across the app."""
    st.html(
        f"""
        <style>
          @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

          html, body, [class*="css"] {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          }}

          .stApp {{ background: {BLITZ_COLORS["background"]}; }}

          /* ── Sidebar ── */
          [data-testid="stSidebar"] {{ background: {BLITZ_COLORS["white"]}; }}
          [data-testid="stSidebar"] > div:first-child {{
            border-right: 1px solid {BLITZ_COLORS["border"]};
          }}

          /* ── KPI metric cards — premium card surface ── */
          [data-testid="stMetric"] {{
            background: {BLITZ_COLORS["white"]};
            border-radius: 10px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.06), 0 0 0 1px {BLITZ_COLORS["border"]};
            transition: box-shadow 160ms ease, transform 160ms ease;
          }}
          [data-testid="stMetric"]:hover {{
            box-shadow: 0 4px 14px rgba(0,185,242,0.12), 0 0 0 1px {BLITZ_COLORS["primary"]}44;
            transform: translateY(-1px);
          }}
          [data-testid="stMetricLabel"] {{
            color: {BLITZ_COLORS["text_secondary"]};
            font-size: 11px !important;
            font-weight: 600 !important;
            letter-spacing: 0.04em;
            text-transform: uppercase;
          }}
          [data-testid="stMetricValue"] {{
            font-size: 22px !important;
            font-weight: 700 !important;
            letter-spacing: -0.02em;
            color: {BLITZ_COLORS["text_primary"]} !important;
          }}
          [data-testid="stMetricDelta"] {{
            font-size: 12px !important;
            font-weight: 600 !important;
          }}

          /* ── Chart card container class ── */
          .bi-card {{
            background: {BLITZ_COLORS["white"]};
            border: 1px solid {BLITZ_COLORS["border"]};
            border-radius: 12px;
            padding: 16px 18px 12px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.05);
          }}

          /* ── Buttons ── */
          .stButton > button,
          [data-testid="stFileUploaderDropzone"],
          [data-baseweb="select"] > div {{
            transition: border-color 140ms ease, box-shadow 140ms ease, background-color 140ms ease;
          }}
          .stButton > button:hover {{
            border-color: {BLITZ_COLORS["primary_hover"]};
            box-shadow: 0 2px 8px rgba(0, 185, 242, 0.16);
          }}
          .stButton > button:focus-visible,
          button[role="tab"]:focus-visible,
          input:focus-visible {{
            outline: 2px solid {BLITZ_COLORS["primary"]};
            outline-offset: 2px;
          }}

          /* ── Navigation tabs ── */
          [data-baseweb="tab-list"] {{
            gap: 4px;
            padding: 4px;
            background: {BLITZ_COLORS["white"]};
            border: 1px solid {BLITZ_COLORS["border"]};
            border-radius: 10px;
          }}
          button[role="tab"] {{
            border-radius: 7px;
            color: {BLITZ_COLORS["text_secondary"]};
            font-weight: 600;
            padding: 7px 12px;
            transition: color 140ms ease, background-color 140ms ease;
          }}
          button[role="tab"]:hover {{
            color: {BLITZ_COLORS["deep_blue"]};
            background: {BLITZ_COLORS["pale_blue"]};
          }}
          button[role="tab"][aria-selected="true"] {{
            color: {BLITZ_COLORS["deep_blue"]};
            background: {BLITZ_COLORS["pale_blue"]};
            font-weight: 700;
          }}
          [data-baseweb="tab-highlight"] {{ background: {BLITZ_COLORS["primary_hover"]}; }}

          /* ── Data frames ── */
          [data-testid="stDataFrame"],
          [data-testid="stFileUploaderDropzone"],
          [data-testid="stExpander"] {{
            border-radius: 10px;
            overflow: hidden;
          }}
          [data-testid="stDataFrame"] {{
            border: 1px solid {BLITZ_COLORS["border"]};
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
          }}
          [data-testid="stExpander"] {{ background: {BLITZ_COLORS["white"]}; }}

          /* ── Plotly modebar hidden for clean presentation ── */
          .js-plotly-plot .modebar {{ display: none !important; }}

          /* ── Section dividers ── */
          .bi-section-rule {{
            height: 1px;
            background: linear-gradient(90deg, {BLITZ_COLORS["primary"]}44 0%, {BLITZ_COLORS["border"]} 40%, transparent 100%);
            margin: 6px 0 10px;
            border: none;
          }}
        </style>
        """
    )


@st.cache_data(show_spinner=False)
def _logo_data_uri(logo_path: str) -> str:
    """Return the supplied logo as an embeddable PNG without altering it."""
    encoded_logo = base64.b64encode(Path(logo_path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded_logo}"


# Background tints for the health status pill
_HEALTH_BG: dict[str, str] = {
    "Healthy": "#DAFBE1",
    "Attention": "#FFF8C5",
    "Critical": "#FFEBE9",
}


def render_app_header(
    logo_path: str | Path,
    health_status: str | None,
    refreshed_at: datetime | None,
) -> None:
    """Render the shared Blitz application header above the dashboard navigation.

    Layout (left → right):
      [blue accent] | [logo] | [product title + sub-title] ... [health pill + timestamp]
    """
    logo_uri = _logo_data_uri(str(logo_path))
    status = health_status if health_status in _HEALTH_COLORS else "Unavailable"
    status_dot_color = _HEALTH_COLORS.get(status, BLITZ_COLORS["text_secondary"])
    status_bg_color = _HEALTH_BG.get(status, BLITZ_COLORS["background"])
    refreshed_label = (
        refreshed_at.strftime("%d %b %Y, %H:%M") if refreshed_at else "Not yet loaded"
    )

    st.html(
        f"""
        <div style="
            display: flex;
            align-items: center;
            gap: 0;
            margin: 0 0 14px 0;
            padding: 0;
            background: {BLITZ_COLORS['white']};
            border: 1px solid {BLITZ_COLORS['border']};
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        ">

          <!-- left accent bar -->
          <div style="
              flex: 0 0 4px;
              align-self: stretch;
              background: {BLITZ_COLORS['primary']};
              border-radius: 10px 0 0 10px;
          "></div>

          <!-- logo -->
          <div style="
              flex: 0 0 auto;
              display: flex;
              align-items: center;
              padding: 10px 8px 10px 16px;
          ">
            <img
              src="{logo_uri}"
              alt="Blitz"
              style="
                  height: 36px;
                  width: auto;
                  display: block;
                  object-fit: contain;
              "
            />
          </div>

          <!-- divider -->
          <div style="
              flex: 0 0 1px;
              align-self: stretch;
              margin: 10px 12px;
              background: {BLITZ_COLORS['border']};
          "></div>

          <!-- product title -->
          <div style="
              flex: 1 1 auto;
              min-width: 0;
              padding: 10px 0;
          ">
            <div style="
                font-size: 15px;
                line-height: 1.2;
                font-weight: 700;
                letter-spacing: -0.2px;
                color: {BLITZ_COLORS['text_primary']};
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            ">Group P&amp;L Intelligence</div>
            <div style="
                margin-top: 2px;
                font-size: 11px;
                line-height: 1.3;
                color: {BLITZ_COLORS['text_secondary']};
                font-weight: 500;
                white-space: nowrap;
            ">Financial Performance Dashboard</div>
          </div>

          <!-- right-side status block -->
          <div style="
              flex: 0 0 auto;
              display: flex;
              flex-direction: column;
              align-items: flex-end;
              gap: 4px;
              padding: 10px 16px;
          ">

            <!-- data health pill -->
            <div style="
                display: inline-flex;
                align-items: center;
                gap: 5px;
                background: {status_bg_color};
                border: 1px solid {status_dot_color}22;
                border-radius: 20px;
                padding: 3px 10px;
            ">
              <span style="
                  display: inline-block;
                  width: 6px;
                  height: 6px;
                  border-radius: 50%;
                  background: {status_dot_color};
                  flex-shrink: 0;
              "></span>
              <span style="
                  font-size: 11px;
                  font-weight: 600;
                  color: {status_dot_color};
                  white-space: nowrap;
              ">Data health: {escape(status)}</span>
            </div>

            <!-- timestamp -->
            <div style="
                font-size: 10px;
                line-height: 1.3;
                color: {BLITZ_COLORS['text_secondary']};
                white-space: nowrap;
            ">Updated: {escape(refreshed_label)}</div>

          </div>
        </div>
        """
    )


def render_app_footer(refreshed_at: datetime | None) -> None:
    """Render a quiet internal-application footer after the active dashboard view."""
    refreshed_label = (
        refreshed_at.strftime("%d %b %Y, %H:%M") if refreshed_at else "Not yet loaded"
    )
    st.html(
        f"""
        <div style="
            margin-top: 32px;
            padding: 10px 0 6px;
            border-top: 1px solid {BLITZ_COLORS['border']};
            font-size: 11px;
            line-height: 1.4;
            color: {BLITZ_COLORS['text_secondary']};
            text-align: center;
        ">
          Blitz Group P&amp;L Intelligence
          <span style="padding: 0 6px; color: {BLITZ_COLORS['border']};">|</span>
          Financial Performance Dashboard
          <span style="padding: 0 6px; color: {BLITZ_COLORS['border']};">|</span>
          Last refreshed: {escape(refreshed_label)}
        </div>
        """
    )


def render_page_header(title: str, summary: str, eyebrow: str = "Financial intelligence") -> None:
    """Render a consistent executive page title and decision-focused summary."""
    st.markdown(
        f"""
        <div style="margin:4px 0 14px;">
          <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;
              color:{BLITZ_COLORS['primary_hover']};margin-bottom:4px;">{escape(eyebrow)}</div>
          <div style="font-size:27px;line-height:1.15;font-weight:700;letter-spacing:-0.03em;
              color:{BLITZ_COLORS['text_primary']};">{escape(title)}</div>
          <div style="font-size:13px;line-height:1.55;color:{BLITZ_COLORS['text_secondary']};
              margin-top:5px;max-width:760px;">{escape(summary)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_header(title: str, icon: str, summary: str | None = None) -> None:
    """Render a compact section heading with a left-accent-bar rule for BI-style sections."""
    st.markdown(
        f"""
        <div style="margin: 4px 0 2px;">
          <div style="
              font-size: 13px;
              font-weight: 700;
              color: {BLITZ_COLORS['text_primary']};
              letter-spacing: -0.01em;
              display: flex;
              align-items: center;
              gap: 6px;
          ">
            <span style="
                display: inline-block;
                width: 3px;
                height: 14px;
                background: {BLITZ_COLORS['primary']};
                border-radius: 2px;
                flex-shrink: 0;
            "></span>
            :material/{icon}: {escape(title)}
          </div>
          {f'<div style="font-size:11px;color:{BLITZ_COLORS["text_secondary"]};margin-top:2px;margin-left:9px;">{escape(summary)}</div>' if summary else ''}
        </div>
        <hr class="bi-section-rule">
        """,
        unsafe_allow_html=True,
    )


def render_section_safe(
    fn: Callable[..., Any],
    *args: Any,
    section_name: str = "Section",
    **kwargs: Any,
) -> None:
    """Call fn(*args, **kwargs) inside an error boundary.

    If fn raises, a compact styled error card is shown for that section only.
    The rest of the dashboard remains unaffected. The full traceback is always
    written to stderr so developers can diagnose the root cause.

    Parameters
    ----------
    fn:
        The rendering function to call.
    *args:
        Positional arguments forwarded to fn.
    section_name:
        Human-readable label shown in the error card (e.g. "Revenue Trend").
    **kwargs:
        Keyword arguments forwarded to fn.
    """
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        # Always log the full traceback for developer visibility
        print(
            f"[Dashboard] Section '{section_name}' raised an exception:\n"
            + traceback.format_exc(),
            file=sys.stderr,
        )
        # Show a compact, friendly error card — no raw traceback shown to users
        err_type = type(exc).__name__
        st.html(
            f"""
            <div style="
                background:#FFEBE9;
                border:1.5px solid #CF222E;
                border-radius:8px;
                padding:12px 16px;
                margin:4px 0 8px 0;
                display:flex;
                align-items:flex-start;
                gap:10px;
            ">
              <span style="font-size:16px;flex-shrink:0;">⚠️</span>
              <div>
                <div style="font-size:12px;font-weight:700;color:#CF222E;margin-bottom:2px;">
                  {escape(section_name)} could not be rendered
                </div>
                <div style="font-size:11px;color:#6E3B3B;line-height:1.5;">
                  An unexpected error occurred in this section ({escape(err_type)}).
                  Other sections are unaffected.
                  Please check that the workbook format is correct, or contact support.
                </div>
              </div>
            </div>
            """
        )


@contextmanager
def render_chart_card(
    title: str,
    subtitle: str | None = None,
    icon: str | None = None,
) -> "Generator[None, None, None]":
    """Context manager that wraps a chart section in a consistent BI-style card.

    Usage::

        with render_chart_card("Revenue trend and growth by entity", icon="show_chart"):
            render_plotly_chart(fig)

    The card renders:
      - Uppercase label (with optional material icon prefix)
      - Optional subtitle / contextual caption
      - The chart / content placed inside the `with` block

    The card uses `.bi-card` CSS injected by `apply_global_visual_system`.
    """
    from streamlit_app.constants import BLITZ_COLORS  # local import keeps module lean

    icon_prefix = f":material/{icon}: " if icon else ""
    title_html = (
        f"<div style='"
        f"font-size:12px;font-weight:700;color:{BLITZ_COLORS['text_secondary']};"
        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:2px;'>"
        f"{icon_prefix}{escape(title)}</div>"
    )
    sub_html = ""
    if subtitle:
        sub_html = (
            f"<div style='font-size:11px;color:{BLITZ_COLORS['text_secondary']};"
            f"margin-bottom:6px;'>{escape(subtitle)}</div>"
        )

    with st.container():
        st.markdown(
            f"<div style='"
            f"background:{BLITZ_COLORS['white']};"
            f"border:1px solid {BLITZ_COLORS['border']};"
            f"border-radius:12px;padding:14px 16px 8px;"
            f"box-shadow:0 1px 4px rgba(0,0,0,0.05);margin-bottom:2px;'>"
            f"{title_html}{sub_html}</div>",
            unsafe_allow_html=True,
        )
        yield


# ---------------------------------------------------------------------------
# Formatting Helpers (UI Only)
# ---------------------------------------------------------------------------

def fmt_percent(val: float | None) -> str:
    """Format a decimal as a percentage (e.g. 0.126 -> +12.6%). Never modifies underlying data."""
    if val is None:
        return "N/A"
    return f"{val * 100:+.1f}%"

def fmt_variance(val: float | None) -> str:
    """Format an absolute variance with a sign prefix (e.g. +Rp420M, -Rp180M)."""
    if val is None:
        return "N/A"
    from streamlit_app.constants import fmt_idr
    formatted = fmt_idr(abs(val))
    return f"+{formatted}" if val >= 0 else f"-{formatted}"


# ---------------------------------------------------------------------------
# Empty State & Data Health
# ---------------------------------------------------------------------------

def render_empty_state(message: str = "NO DATA AVAILABLE", subtext: str = "No records match the current filters. Try expanding the reporting period.") -> None:
    """Render a reusable no-data component."""
    st.markdown(
        f"""
        <div style="
            background: {BLITZ_COLORS['white']};
            border: 1px dashed {BLITZ_COLORS['border']};
            border-radius: 12px;
            padding: 32px 20px;
            text-align: center;
            color: {BLITZ_COLORS['text_secondary']};
        ">
          <div style="font-size: 24px; margin-bottom: 8px;">📊</div>
          <div style="font-size: 13px; font-weight: 700; letter-spacing: 0.05em; color: {BLITZ_COLORS['text_primary']}; margin-bottom: 4px;">
            {escape(message)}
          </div>
          <div style="font-size: 12px; line-height: 1.5;">{escape(subtext)}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_data_health_badge(status: str | None) -> None:
    """Render a reusable data health status pill."""
    status_clean = status if status in _HEALTH_COLORS else "Unavailable"
    dot_color = _HEALTH_COLORS.get(status_clean, BLITZ_COLORS["text_secondary"])
    bg_color = _HEALTH_BG.get(status_clean, BLITZ_COLORS["background"])
    st.markdown(
        f"""
        <div style="
            display: inline-flex;
            align-items: center;
            gap: 5px;
            background: {bg_color};
            border: 1px solid {dot_color}22;
            border-radius: 20px;
            padding: 4px 12px;
        ">
          <span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: {dot_color};"></span>
          <span style="font-size: 11px; font-weight: 600; color: {dot_color}; white-space: nowrap;">
            Data health: {escape(status_clean)}
          </span>
        </div>
        """,
        unsafe_allow_html=True
    )


# ---------------------------------------------------------------------------
# Responsive Layout Helpers
# ---------------------------------------------------------------------------

@contextmanager
def get_kpi_layout(count: int) -> "Generator[list, None, None]":
    """Return responsive columns for KPI cards (typically 3 or 4 per row)."""
    if count == 4:
        cols = st.columns([1, 1, 1, 1], gap="small")
    elif count == 3:
        cols = st.columns([1, 1, 1], gap="small")
    elif count == 2:
        cols = st.columns([1, 1], gap="small")
    else:
        cols = st.columns(count, gap="small")
    yield cols

@contextmanager
def get_chart_layout(mode: str = "full") -> "Generator[list, None, None]":
    """Return responsive columns for charts. mode in ('full', 'split_even', 'split_wide_main')."""
    if mode == "split_even":
        cols = st.columns([1, 1], gap="medium")
    elif mode == "split_wide_main":
        cols = st.columns([3, 2], gap="medium")
    else:
        cols = [st.container()]
    yield cols


# ---------------------------------------------------------------------------
# Additional BI Components (Filter Chips, Insights, Badges, Tables)
# ---------------------------------------------------------------------------

def render_status_badge(label: str, semantic_status: str = "neutral") -> str:
    """Return HTML for a small colored status badge."""
    bg_colors = {
        "positive": "#DAFBE1",
        "negative": "#FFEBE9",
        "warning": "#FFF8C5",
        "neutral": BLITZ_COLORS["background"]
    }
    text_colors = {
        "positive": "#1A7F37",
        "negative": "#CF222E",
        "warning": "#BF8700",
        "neutral": BLITZ_COLORS["text_secondary"]
    }
    
    bg = bg_colors.get(semantic_status, bg_colors["neutral"])
    color = text_colors.get(semantic_status, text_colors["neutral"])
    
    return f"""
        <span style="
            background: {bg};
            color: {color};
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
        ">{escape(label)}</span>
    """


def render_filter_chip(label: str, value: str, on_remove: str | None = None) -> str:
    """Return HTML for a UI filter chip."""
    return f"""
        <div style="
            display: inline-flex;
            align-items: center;
            background: {BLITZ_COLORS['white']};
            border: 1px solid {BLITZ_COLORS['border']};
            border-radius: 16px;
            padding: 4px 10px;
            font-size: 12px;
            color: {BLITZ_COLORS['text_primary']};
            margin-right: 6px;
            margin-bottom: 6px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        ">
            <span style="color: {BLITZ_COLORS['text_secondary']}; margin-right: 4px;">{escape(label)}:</span>
            <span style="font-weight: 600;">{escape(value)}</span>
        </div>
    """


def render_filter_control(title: str, widget_func: Callable, *args, **kwargs) -> Any:
    """Wrap a Streamlit widget with a consistent BI-style label."""
    st.markdown(
        f"<div style='font-size:11px;font-weight:600;color:{BLITZ_COLORS['text_secondary']};"
        f"text-transform:uppercase;margin-bottom:-10px;margin-top:6px;'>{escape(title)}</div>",
        unsafe_allow_html=True
    )
    return widget_func(*args, **kwargs)


@contextmanager
def render_insight_card(title: str, icon: str = "lightbulb") -> "Generator[None, None, None]":
    """Context manager for rendering an insight/summary card."""
    st.markdown(
        f"""
        <div style="
            background: {BLITZ_COLORS['pale_blue']};
            border-left: 4px solid {BLITZ_COLORS['primary']};
            border-radius: 0 8px 8px 0;
            padding: 12px 16px;
            margin-bottom: 16px;
        ">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                <span style="font-size: 16px; color: {BLITZ_COLORS['primary']};">:material/{icon}:</span>
                <span style="font-size: 13px; font-weight: 700; color: {BLITZ_COLORS['deep_blue']};">{escape(title)}</span>
            </div>
            <div style="font-size: 13px; color: {BLITZ_COLORS['text_primary']}; line-height: 1.5;">
        """,
        unsafe_allow_html=True
    )
    yield
    st.markdown("</div></div>", unsafe_allow_html=True)


def render_metric_table(df: pd.DataFrame, height: int | None = None) -> None:
    """Render a clean dataframe using Streamlit's native dataframe but optimized for BI."""
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=height,
    )


# ---------------------------------------------------------------------------
# Data-source provenance
# ---------------------------------------------------------------------------

def render_source_banner(ref: object) -> None:
    """State exactly which workbook is on screen, and how fresh it is.

    A dashboard that cannot name its own source is not a control. The Finance
    folder holds a dozen `Group_PL_*` variants, and a board pack was once built
    from a stale one — this strip exists so that can never happen silently.
    """
    import streamlit as st  # noqa: PLC0415

    name = getattr(ref, "name", "unknown")
    origin = getattr(ref, "origin", "unknown")
    detail = getattr(ref, "detail", "")
    is_live = bool(getattr(ref, "is_live", False))
    modified = getattr(ref, "modified_label", "unknown")
    age = getattr(ref, "age_hint", "")
    modified_by = getattr(ref, "modified_by", None)

    if is_live:
        accent, chip_bg, icon, chip = "#1A7F37", "#DAFBE1", "🟢", "LIVE"
    else:
        accent, chip_bg, icon, chip = "#BF8700", "#FFF8C5", "🟡", "MANUAL"

    by = f" by {escape(str(modified_by))}" if modified_by else ""
    age_txt = f" · {escape(age)}" if age else ""
    detail_txt = escape(str(detail))
    if len(detail_txt) > 110:
        detail_txt = detail_txt[:107] + "…"

    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;
            background:{BLITZ_COLORS['off_white']};border:1px solid {BLITZ_COLORS['border']};
            border-left:4px solid {accent};border-radius:8px;
            padding:9px 16px;margin:0 0 14px 0;">
          <span style="background:{chip_bg};color:{accent};font-size:10px;font-weight:800;
            letter-spacing:0.08em;padding:2px 8px;border-radius:4px;white-space:nowrap;">
            {icon} {chip}</span>
          <span style="font-size:13px;font-weight:700;color:{BLITZ_COLORS['text_primary']};">
            {escape(str(name))}</span>
          <span style="font-size:11px;color:{BLITZ_COLORS['text_secondary']};">
            {escape(str(origin))} · modified {escape(str(modified))}{by}{age_txt}</span>
          <span style="font-size:10px;color:{BLITZ_COLORS['text_secondary']};
            margin-left:auto;font-family:ui-monospace,monospace;opacity:0.75;">
            {detail_txt}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
