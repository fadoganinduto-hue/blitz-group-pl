"""Shared pytest fixtures — synthetic DataFrames that match the workbook structure.

No real workbook is required to run these tests.  Every fixture is built from
scratch using pandas so the test suite works in CI without the proprietary file.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Consolidated Summary fixture
# ---------------------------------------------------------------------------

def _make_consolidated_raw() -> pd.DataFrame:
    """Build a minimal raw Consolidated Summary sheet.

    Layout mirrors the real workbook:
      row 0 : filler
      row 1 : header row — col[1]="In IDR", col[2]="Jan 2025", col[3]="Feb 2025"
      row 2+ : P&L rows — col[1]=label, col[2..]=values
    """
    data = {
        0: [None, None, None, None, None, None, None, None, None, None, None],
        1: [
            None,
            "In IDR",
            "Total Gross Revenue",
            "Total COGS",
            "Gross Profit 2",
            "Total Operating Expenses",
            "EBITDA",
            "NET PROFIT/LOSS (Before Tax)",
            "Gross Margin %",   # ratio row — should go to parse_ratios not parse_pl_sheet
            "EBITDA Margin %",  # ratio row
            "In USD",           # stop marker
        ],
        2: [
            None,
            "Jan 2025",
            1_000_000_000,   # Total Gross Revenue
            400_000_000,     # Total COGS
            600_000_000,     # Gross Profit 2
            200_000_000,     # Total Operating Expenses
            400_000_000,     # EBITDA
            350_000_000,     # NET PROFIT/LOSS (Before Tax)
            0.60,            # Gross Margin %
            0.40,            # EBITDA Margin %
            None,
        ],
        3: [
            None,
            "Feb 2025",
            1_200_000_000,
            480_000_000,
            720_000_000,
            220_000_000,
            500_000_000,
            440_000_000,
            0.60,
            0.4167,
            None,
        ],
    }
    return pd.DataFrame(data)


@pytest.fixture
def consolidated_raw() -> pd.DataFrame:
    """Raw Consolidated Summary sheet as returned by pd.read_excel(header=None)."""
    return _make_consolidated_raw()


# ---------------------------------------------------------------------------
# MASTER sheet fixture
# ---------------------------------------------------------------------------

def _make_master_raw() -> pd.DataFrame:
    """Build a minimal raw MASTER sheet.

    Layout mirrors the real workbook:
      row 0 : filler
      row 1 : column headers
      row 2+: data rows
    """
    headers = ["Entity", "Rev Stream", "Industry", "Client (clean)", "Month", "Amount (IDR)"]
    rows = [
        ["Blitz", "Delivery", "E-commerce", "Client A", "Jan 2025", 300_000_000],
        ["Blitz", "Delivery", "E-commerce", "Client B", "Jan 2025", 200_000_000],
        ["Borzo", "On-demand", "Retail",     "Client C", "Jan 2025", 150_000_000],
        ["TheLorry", "Trucking", "Logistics","Client D", "Jan 2025",  50_000_000],
        ["Blitz", "Delivery", "E-commerce", "Client A", "Feb 2025", 400_000_000],
        ["Blitz", "Delivery", "E-commerce", "Client B", "Feb 2025", 250_000_000],
        ["Borzo", "On-demand", "Retail",     "Client C", "Feb 2025", 180_000_000],
        ["TheLorry", "Trucking", "Logistics","Client D", "Feb 2025",  70_000_000],
    ]

    # Row 0: all None (filler)
    filler = pd.DataFrame([[None] * len(headers)], columns=range(len(headers)))
    # Row 1: column headers
    header_row = pd.DataFrame([headers], columns=range(len(headers)))
    # Rows 2+: data
    data_df = pd.DataFrame(rows, columns=range(len(headers)))

    raw = pd.concat([filler, header_row, data_df], ignore_index=True)
    raw.columns = range(len(headers))
    return raw


@pytest.fixture
def master_raw() -> pd.DataFrame:
    """Raw MASTER sheet as returned by pd.read_excel(header=None)."""
    return _make_master_raw()


# ---------------------------------------------------------------------------
# TIE-OUT CHECK fixture
# ---------------------------------------------------------------------------

def _make_tie_out_raw() -> pd.DataFrame:
    """Build a minimal raw TIE-OUT CHECK sheet.

    parse_tie_out requires at least 3 month columns in the header row.
    Row labels are read from column 0 (not column 1).
    """
    # Header: col 0 empty, cols 1-3 are month labels
    header = [None, "Jan 2025", "Feb 2025", "Mar 2025"]
    data_rows = [
        ["Master vs Tracker", 500_000, 1_500_000, 200_000],
        ["Tracker vs P&L",    200_000, -300_000,  100_000],
        ["Entity Blitz",     -100_000, 800_000,  -50_000],
    ]
    all_rows = [header] + data_rows
    return pd.DataFrame(all_rows)


@pytest.fixture
def tie_out_raw() -> pd.DataFrame:
    """Raw TIE-OUT CHECK sheet as returned by pd.read_excel(header=None)."""
    return _make_tie_out_raw()


# ---------------------------------------------------------------------------
# Minimal valid sheets dict
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_sheets(consolidated_raw, master_raw, tie_out_raw) -> dict[str, pd.DataFrame]:
    """A minimal valid workbook sheets dict that passes validation."""
    return {
        "Consolidated Summary": consolidated_raw,
        "MASTER": master_raw,
        "TIE-OUT CHECK": tie_out_raw,
    }
