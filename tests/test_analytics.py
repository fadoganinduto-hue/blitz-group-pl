"""Unit tests for streamlit_app.data.analytics pure functions.

Run with: pytest tests/test_analytics.py -v
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.data.analytics import (
    AnomalyFlag,
    ChartAnnotation,
    YoYResult,
    compute_historical_average,
    compute_rolling_avg,
    compute_yoy_comparison,
    detect_anomalies,
    find_chart_annotations,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_long(records: list[dict]) -> pd.DataFrame:
    """Build a minimal long-format P&L DataFrame from raw records."""
    df = pd.DataFrame(records)
    if "MonthDate" not in df.columns:
        df["MonthDate"] = pd.to_datetime(df["Month"], format="%b %Y", errors="coerce")
    return df


@pytest.fixture()
def single_metric_6m() -> pd.DataFrame:
    """6 months of a single metric — Total Gross Revenue."""
    data = [
        {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "Jan 2025", "Value": 100_000_000},
        {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "Feb 2025", "Value": 120_000_000},
        {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "Mar 2025", "Value": 110_000_000},
        {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "Apr 2025", "Value": 140_000_000},
        {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "May 2025", "Value": 90_000_000},
        {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "Jun 2025", "Value": 130_000_000},
    ]
    df = pd.DataFrame(data)
    df["MonthDate"] = pd.to_datetime(df["Month"], format="%b %Y", errors="coerce")
    return df


@pytest.fixture()
def with_prior_year() -> pd.DataFrame:
    """13 months of data — includes prior-year month Jan 2024."""
    records = [
        {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "Jan 2024", "Value": 100_000_000},
        {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "Jan 2025", "Value": 100_000_000},
    ]
    df = pd.DataFrame(records)
    df["MonthDate"] = pd.to_datetime(df["Month"], format="%b %Y", errors="coerce")
    return df


@pytest.fixture()
def anomaly_df() -> pd.DataFrame:
    """Consolidated data with a large revenue drop + COGS spike."""
    return _make_long([
        {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "Jan 2025", "Value": 200_000_000},
        {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "Feb 2025", "Value": 80_000_000},
        {"Entity": "Cons", "Metric": "Total COGS",          "Month": "Jan 2025", "Value": 60_000_000},
        {"Entity": "Cons", "Metric": "Total COGS",          "Month": "Feb 2025", "Value": 55_000_000},
        {"Entity": "Cons", "Metric": "Total Operating Expenses", "Month": "Jan 2025", "Value": 20_000_000},
        {"Entity": "Cons", "Metric": "Total Operating Expenses", "Month": "Feb 2025", "Value": 18_000_000},
    ])


# ---------------------------------------------------------------------------
# compute_yoy_comparison
# ---------------------------------------------------------------------------

class TestComputeYoyComparison:
    def test_returns_unavailable_when_prior_year_missing(self, single_metric_6m):
        all_months = single_metric_6m["Month"].unique().tolist()
        result = compute_yoy_comparison(single_metric_6m, "Total Gross Revenue", "Jan 2025", all_months)
        assert isinstance(result, YoYResult)
        assert result.available is False
        assert result.prior_year_month == "Jan 2024"

    def test_returns_available_when_prior_year_present(self, with_prior_year):
        all_months = ["Jan 2024", "Jan 2025"]
        result = compute_yoy_comparison(with_prior_year, "Total Gross Revenue", "Jan 2025", all_months)
        assert result.available is True
        assert result.prior_year_month == "Jan 2024"
        assert result.current == pytest.approx(100_000_000)
        assert result.prior_year == pytest.approx(100_000_000)

    def test_pct_change_computed_correctly(self, with_prior_year):
        all_months = ["Jan 2024", "Jan 2025"]
        result = compute_yoy_comparison(with_prior_year, "Total Gross Revenue", "Jan 2025", all_months)
        # Jan 2024 = 100M, Jan 2025 = 100M → pct = 0%
        assert result.pct_change == pytest.approx(0.0)

    def test_returns_none_for_unknown_metric(self, single_metric_6m):
        result = compute_yoy_comparison(single_metric_6m, "Does Not Exist", "Jan 2025", ["Jan 2025"])
        assert result.available is False


# ---------------------------------------------------------------------------
# compute_rolling_avg
# ---------------------------------------------------------------------------

class TestComputeRollingAvg:
    def test_empty_when_insufficient_months(self, single_metric_6m):
        # Need at least window=3 months; 2 months is too few
        result = compute_rolling_avg(single_metric_6m, "Total Gross Revenue", ["Jan 2025", "Feb 2025"], window=3)
        assert result.empty

    def test_correct_length_when_enough_months(self, single_metric_6m):
        months = ["Jan 2025", "Feb 2025", "Mar 2025", "Apr 2025"]
        result = compute_rolling_avg(single_metric_6m, "Total Gross Revenue", months, window=3)
        # With window=3 and 4 months, we get 2 valid rolling avg points (months 3 & 4)
        assert len(result) == 2

    def test_correct_average_value(self, single_metric_6m):
        months = ["Jan 2025", "Feb 2025", "Mar 2025"]
        result = compute_rolling_avg(single_metric_6m, "Total Gross Revenue", months, window=3)
        # 3 months with window=3 → exactly 1 point
        assert len(result) == 1
        # 3M avg of Jan=100M, Feb=120M, Mar=110M = 110M
        assert result.iloc[0]["Value"] == pytest.approx(110_000_000)


# ---------------------------------------------------------------------------
# find_chart_annotations
# ---------------------------------------------------------------------------

class TestFindChartAnnotations:
    def test_finds_peak(self, single_metric_6m):
        months = ["Jan 2025", "Feb 2025", "Mar 2025", "Apr 2025", "May 2025", "Jun 2025"]
        anns = find_chart_annotations(single_metric_6m, "Total Gross Revenue", months)
        peaks = [a for a in anns if a.kind == "peak"]
        assert len(peaks) == 1
        assert peaks[0].month == "Apr 2025"  # 140M is highest

    def test_finds_trough(self, single_metric_6m):
        months = ["Jan 2025", "Feb 2025", "Mar 2025", "Apr 2025", "May 2025", "Jun 2025"]
        anns = find_chart_annotations(single_metric_6m, "Total Gross Revenue", months, max_annotations=2)
        troughs = [a for a in anns if a.kind == "trough"]
        assert len(troughs) == 1
        assert troughs[0].month == "May 2025"  # 90M is lowest

    def test_empty_for_single_month(self, single_metric_6m):
        anns = find_chart_annotations(single_metric_6m, "Total Gross Revenue", ["Jan 2025"])
        assert anns == []

    def test_returns_at_most_max_annotations(self, single_metric_6m):
        months = ["Jan 2025", "Feb 2025", "Mar 2025", "Apr 2025", "May 2025", "Jun 2025"]
        anns = find_chart_annotations(single_metric_6m, "Total Gross Revenue", months, max_annotations=1)
        assert len(anns) <= 1


# ---------------------------------------------------------------------------
# detect_anomalies
# ---------------------------------------------------------------------------

class TestDetectAnomalies:
    def test_flags_large_revenue_drop(self, anomaly_df):
        months = ["Jan 2025", "Feb 2025"]
        flags = detect_anomalies(anomaly_df, months)
        rev_flags = [f for f in flags if "Revenue" in f.title]
        assert len(rev_flags) >= 1
        assert rev_flags[0].level == "critical"  # 60% drop → critical

    def test_no_flags_for_single_month(self, anomaly_df):
        flags = detect_anomalies(anomaly_df, ["Jan 2025"])
        assert flags == []

    def test_flag_sorted_critical_first(self, anomaly_df):
        months = ["Jan 2025", "Feb 2025"]
        flags = detect_anomalies(anomaly_df, months)
        if len(flags) > 1:
            assert flags[0].level == "critical" or all(f.level == "warning" for f in flags)

    def test_no_false_positive_on_small_change(self):
        df = _make_long([
            {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "Jan 2025", "Value": 100_000_000},
            {"Entity": "Cons", "Metric": "Total Gross Revenue", "Month": "Feb 2025", "Value": 105_000_000},
            {"Entity": "Cons", "Metric": "Total COGS",          "Month": "Jan 2025", "Value": 30_000_000},
            {"Entity": "Cons", "Metric": "Total COGS",          "Month": "Feb 2025", "Value": 31_000_000},
            {"Entity": "Cons", "Metric": "Total Operating Expenses", "Month": "Jan 2025", "Value": 20_000_000},
            {"Entity": "Cons", "Metric": "Total Operating Expenses", "Month": "Feb 2025", "Value": 20_500_000},
        ])
        flags = detect_anomalies(df, ["Jan 2025", "Feb 2025"])
        assert flags == []


# ---------------------------------------------------------------------------
# compute_historical_average
# ---------------------------------------------------------------------------

class TestComputeHistoricalAverage:
    def test_average_of_6_months(self, single_metric_6m):
        months = ["Jan 2025", "Feb 2025", "Mar 2025", "Apr 2025", "May 2025", "Jun 2025"]
        avg = compute_historical_average(single_metric_6m, "Total Gross Revenue", months)
        expected = (100 + 120 + 110 + 140 + 90 + 130) / 6 * 1_000_000
        assert avg == pytest.approx(expected)

    def test_returns_none_for_single_month(self, single_metric_6m):
        avg = compute_historical_average(single_metric_6m, "Total Gross Revenue", ["Jan 2025"])
        assert avg is None

    def test_returns_none_for_unknown_metric(self, single_metric_6m):
        months = ["Jan 2025", "Feb 2025"]
        avg = compute_historical_average(single_metric_6m, "Nonexistent Metric", months)
        assert avg is None
