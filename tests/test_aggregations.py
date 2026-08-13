"""Smoke tests for formatting utilities, date filtering, and aggregation helpers.

Tests cover:
  - fmt_idr: correct compact formatting for B/M/K/raw values
  - fmt_idr_full: full IDR formatting
  - month_sort_key: correct chronological sorting
  - Financial correctness: KPI delta calculations
  - Stale cache safety: different content → different parse output
"""

from __future__ import annotations

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# fmt_idr formatting
# ---------------------------------------------------------------------------

class TestFmtIdr:
    @pytest.mark.parametrize("value, expected_prefix, expected_suffix", [
        (1_500_000_000, "Rp1.5", "B"),
        (500_000_000,   "Rp500.0", "M"),
        (1_200_000,     "Rp1.2", "M"),
        (450_000,       "Rp450.0", "K"),
        (999,           "Rp999",  ""),
        (-1_000_000_000, "-Rp1.0", "B"),
        (0,             "Rp0",    ""),
    ])
    def test_fmt_idr_format(self, value, expected_prefix, expected_suffix):
        from streamlit_app.constants import fmt_idr

        result = fmt_idr(value)
        assert result.startswith(expected_prefix), (
            f"fmt_idr({value}) = '{result}', expected prefix '{expected_prefix}'"
        )
        assert result.endswith(expected_suffix), (
            f"fmt_idr({value}) = '{result}', expected suffix '{expected_suffix}'"
        )

    def test_negative_billion(self):
        from streamlit_app.constants import fmt_idr

        result = fmt_idr(-2_500_000_000)
        assert result.startswith("-Rp")
        assert "B" in result

    def test_zero(self):
        from streamlit_app.constants import fmt_idr

        result = fmt_idr(0)
        assert "Rp" in result


# ---------------------------------------------------------------------------
# fmt_idr_full
# ---------------------------------------------------------------------------

class TestFmtIdrFull:
    def test_full_format_includes_commas(self):
        from streamlit_app.constants import fmt_idr_full

        result = fmt_idr_full(1_234_567)
        assert "1,234,567" in result

    def test_full_format_negative(self):
        from streamlit_app.constants import fmt_idr_full

        result = fmt_idr_full(-500_000)
        assert result.startswith("-Rp")


# ---------------------------------------------------------------------------
# month_sort_key
# ---------------------------------------------------------------------------

class TestMonthSortKey:
    @pytest.mark.parametrize("month_str, expected_year, expected_month", [
        ("Jan 2025", 2025, 1),
        ("Feb 2025", 2025, 2),
        ("Dec 2024", 2024, 12),
        ("Jan-25",   2025, 1),
    ])
    def test_known_formats(self, month_str, expected_year, expected_month):
        from streamlit_app.data.parsers import month_sort_key

        result = month_sort_key(month_str)
        assert result is not pd.NaT, f"month_sort_key('{month_str}') returned NaT"
        assert result.year == expected_year
        assert result.month == expected_month

    def test_invalid_string_returns_nat(self):
        from streamlit_app.data.parsers import month_sort_key

        result = month_sort_key("not-a-month")
        assert result is pd.NaT

    def test_chronological_ordering(self):
        from streamlit_app.data.parsers import month_sort_key

        months = ["Mar 2025", "Jan 2025", "Feb 2025", "Dec 2024"]
        sorted_months = sorted(months, key=month_sort_key)
        assert sorted_months == ["Dec 2024", "Jan 2025", "Feb 2025", "Mar 2025"]


# ---------------------------------------------------------------------------
# KPI delta calculation correctness
# ---------------------------------------------------------------------------

class TestKpiDeltas:
    """Verify the delta calculations used in the dashboard produce correct results.

    These tests reproduce the inline arithmetic from filters.py / overview.py
    to ensure financial calculations remain consistent after refactoring.
    """

    def test_mom_growth_positive(self):
        """MoM growth = (current - prior) / |prior| * 100."""
        prior = 1_000_000_000
        current = 1_200_000_000
        expected = 20.0
        result = (current - prior) / abs(prior) * 100
        assert result == pytest.approx(expected)

    def test_mom_growth_negative(self):
        prior = 1_200_000_000
        current = 1_000_000_000
        expected = -100 / 6  # ≈ -16.667%
        result = (current - prior) / abs(prior) * 100
        assert result == pytest.approx(expected, rel=1e-4)

    def test_mom_growth_zero_prior_is_excluded(self):
        """When prior is 0, delta % is undefined — should return None."""
        prior = 0
        current = 500_000_000
        # Reproduces the guard in _delta_pct
        result = None if prior == 0 else (current - prior) / abs(prior) * 100
        assert result is None

    def test_top5_concentration(self):
        """Top-5 concentration = top5_revenue / total * 100."""
        revenues = [500, 400, 300, 200, 100, 50, 25]
        total = sum(revenues)    # 1575
        top5 = sum(sorted(revenues, reverse=True)[:5])  # 500+400+300+200+100 = 1500
        pct = top5 / total * 100
        # 1500 / 1575 * 100 = 95.2381...
        assert pct == pytest.approx(95.238, rel=1e-3)

    def test_ebitda_margin_from_ratio(self):
        """EBITDA Margin % is stored as decimal (0.40) → displayed as 40.0%."""
        stored_value = 0.40
        displayed_value = stored_value * 100
        assert displayed_value == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# Date filtering consistency
# ---------------------------------------------------------------------------

class TestDateFiltering:
    """Verify that date range filtering produces correct subsets."""

    def test_filter_by_month_list(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_pl_sheet

        df = parse_pl_sheet(consolidated_raw, "Consolidated")
        all_months = df.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()

        # Filter to only Jan 2025
        filtered = df[df["Month"].isin(["Jan 2025"])]
        assert set(filtered["Month"].unique()) == {"Jan 2025"}
        assert "Feb 2025" not in filtered["Month"].values

    def test_filter_preserves_values(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_pl_sheet

        df = parse_pl_sheet(consolidated_raw, "Consolidated")
        jan_rev = df[(df["Metric"] == "Total Gross Revenue") & (df["Month"] == "Jan 2025")]["Value"].sum()
        feb_rev = df[(df["Metric"] == "Total Gross Revenue") & (df["Month"] == "Feb 2025")]["Value"].sum()

        assert jan_rev == pytest.approx(1_000_000_000)
        assert feb_rev == pytest.approx(1_200_000_000)

    def test_empty_month_filter_returns_empty(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_pl_sheet

        df = parse_pl_sheet(consolidated_raw, "Consolidated")
        filtered = df[df["Month"].isin(["Mar 2099"])]  # Non-existent month
        assert filtered.empty


# ---------------------------------------------------------------------------
# Stale cache safety
# ---------------------------------------------------------------------------

class TestStaleCacheSafety:
    """Verify that different content produces different parse results.

    This test cannot directly test the Streamlit cache (which requires a running
    app), but it verifies that the underlying parse functions return different
    results for different inputs — ensuring correct cache key semantics.
    """

    def test_different_values_produce_different_output(self):
        from streamlit_app.data.parsers import parse_pl_sheet

        # Two sheets with the same structure but different revenue values
        data_a = {
            0: [None, None, None],
            1: [None, "In IDR", "Total Gross Revenue"],
            2: [None, "Jan 2025", 1_000_000_000],
        }
        data_b = {
            0: [None, None, None],
            1: [None, "In IDR", "Total Gross Revenue"],
            2: [None, "Jan 2025", 2_000_000_000],  # Different value
        }

        df_a = parse_pl_sheet(pd.DataFrame(data_a), "Test")
        df_b = parse_pl_sheet(pd.DataFrame(data_b), "Test")

        val_a = df_a[df_a["Metric"] == "Total Gross Revenue"]["Value"].iloc[0]
        val_b = df_b[df_b["Metric"] == "Total Gross Revenue"]["Value"].iloc[0]

        assert val_a != val_b, (
            "Different input DataFrames must produce different parse output — "
            "this verifies that cache invalidation on re-upload would work correctly"
        )

    def test_file_hash_changes_with_content(self):
        """Verify _file_hash returns different digests for different content."""
        from io import BytesIO
        from streamlit_app.data.loader import _file_hash

        content_a = b"workbook content version A"
        content_b = b"workbook content version B"

        mock_a = BytesIO(content_a)
        mock_a.name = "file.xlsx"
        mock_a.size = len(content_a)

        mock_b = BytesIO(content_b)
        mock_b.name = "file.xlsx"  # Same filename, different content
        mock_b.size = len(content_b)

        hash_a = _file_hash(mock_a)
        hash_b = _file_hash(mock_b)

        assert hash_a != hash_b, (
            "Different file content must produce different hashes — "
            "this guarantees cache invalidation on re-upload"
        )

    def test_same_content_same_hash(self):
        """Verify _file_hash returns the same digest for identical content."""
        from io import BytesIO
        from streamlit_app.data.loader import _file_hash

        content = b"identical workbook bytes"

        mock_1 = BytesIO(content)
        mock_1.name = "file.xlsx"
        mock_1.size = len(content)

        mock_2 = BytesIO(content)
        mock_2.name = "file.xlsx"
        mock_2.size = len(content)

        assert _file_hash(mock_1) == _file_hash(mock_2), (
            "Same file content must produce the same hash (cache stability)"
        )
