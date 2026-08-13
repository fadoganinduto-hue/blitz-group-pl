"""Shared presentation primitives for the executive financial dashboard."""

from __future__ import annotations

import base64
import sys
import traceback
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Callable

import streamlit as st


from streamlit_app.constants import BLITZ_COLORS


_HEALTH_COLORS = {
    "Healthy": "#1A7F37",
    "Attention": "#BF8700",
    "Critical": "#CF222E",
}


def apply_global_visual_system() -> None:
    """Apply the restrained interaction and component treatment used across the app."""
    st.html(
        f"""
        <style>
          .stApp {{ background: {BLITZ_COLORS["background"]}; }}
          [data-testid="stSidebar"] {{ background: {BLITZ_COLORS["white"]}; }}
          [data-testid="stSidebar"] > div:first-child {{ border-right: 1px solid {BLITZ_COLORS["border"]}; }}

          [data-testid="stMetric"] {{
            background: {BLITZ_COLORS["white"]};
            border-radius: 10px;
          }}
          [data-testid="stMetricLabel"] {{ color: {BLITZ_COLORS["text_secondary"]}; }}

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
            padding: 7px 10px;
            transition: color 140ms ease, background-color 140ms ease;
          }}
          button[role="tab"]:hover {{
            color: {BLITZ_COLORS["deep_blue"]};
            background: {BLITZ_COLORS["pale_blue"]};
          }}
          button[role="tab"][aria-selected="true"] {{
            color: {BLITZ_COLORS["deep_blue"]};
            background: {BLITZ_COLORS["pale_blue"]};
          }}
          [data-baseweb="tab-highlight"] {{ background: {BLITZ_COLORS["primary_hover"]}; }}

          [data-testid="stDataFrame"],
          [data-testid="stFileUploaderDropzone"],
          [data-testid="stExpander"] {{
            border-radius: 10px;
            overflow: hidden;
          }}
          [data-testid="stDataFrame"] {{ border: 1px solid {BLITZ_COLORS["border"]}; }}
          [data-testid="stExpander"] {{ background: {BLITZ_COLORS["white"]}; }}
          .js-plotly-plot .modebar {{ display: none !important; }}
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
    """Render a compact, consistent section heading without adding visual weight."""
    st.markdown(f"##### :material/{icon}: {title}")
    if summary:
        st.caption(summary)


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

