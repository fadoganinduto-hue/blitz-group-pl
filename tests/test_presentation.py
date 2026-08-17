"""Tests for chart presentation defects that reached the screen."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from streamlit_app.constants import (
    DETAIL_METRIC_ALIASES,
    ENTITY_COLORS,
    PLOTLY_COLOR_SEQUENCE,
)

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Material icon tokens inside raw HTML
# ---------------------------------------------------------------------------

def test_no_material_tokens_inside_raw_html_blocks():
    """Streamlit only translates :material/x: in its own text elements.

    Inside unsafe_allow_html they render literally, and the uppercase CSS on
    section headings turned them into ":MATERIAL_BAR_CHART:" on screen.
    """
    offenders: list[str] = []
    for path in (ROOT / "streamlit_app").rglob("*.py"):
        source = path.read_text()
        for block in re.findall(r"st\.markdown\(.*?unsafe_allow_html=True", source, re.S):
            if ":material/" in block:
                offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders, f":material/ inside raw HTML in: {sorted(set(offenders))}"


# ---------------------------------------------------------------------------
# Palette — validated with scripts/validate_palette.js, pinned here
# ---------------------------------------------------------------------------

def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _relative_luminance(hex_colour: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _hex_to_rgb(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("colour", sorted(set(ENTITY_COLORS.values())))
def test_entity_colours_have_usable_contrast_on_white(colour):
    """The old Blitz cyan sat at 2.22:1 on a white chart surface."""
    assert _contrast(colour, "#FFFFFF") >= 3.0, (
        f"{colour} is below 3:1 against the chart surface"
    )


def test_entity_colours_are_not_all_one_hue():
    """Three shades of the same blue is why the charts were hard to read."""
    hues = {tuple(round(c, 1) for c in _hex_to_rgb(v)) for v in ENTITY_COLORS.values()}
    assert len(hues) == len(ENTITY_COLORS), "entity colours collapsed to the same hue"
    assert ENTITY_COLORS["Blitz"] != ENTITY_COLORS["Borzo"]


def test_categorical_sequence_contains_no_greys():
    """Text tokens were being used as series fills; they fail the chroma floor."""
    for colour in PLOTLY_COLOR_SEQUENCE:
        r, g, b = _hex_to_rgb(colour)
        assert max(r, g, b) - min(r, g, b) > 0.08, f"{colour} reads as grey"


def test_categorical_sequence_has_no_duplicates():
    assert len(PLOTLY_COLOR_SEQUENCE) == len(set(PLOTLY_COLOR_SEQUENCE))


# ---------------------------------------------------------------------------
# Detail-sheet metric aliasing
# ---------------------------------------------------------------------------

def test_detail_revenue_alias_exists():
    """Without this the Entity tab's Detail view shows N/A for every revenue."""
    assert DETAIL_METRIC_ALIASES["Total REVENUE"] == "Total Gross Revenue"
    assert DETAIL_METRIC_ALIASES["Total NET REVENUE"] == "Net Revenue"


def test_aliases_do_not_collide():
    """Two Detail labels must never both map onto one canonical metric."""
    targets = list(DETAIL_METRIC_ALIASES.values())
    assert len(targets) == len(set(targets))
