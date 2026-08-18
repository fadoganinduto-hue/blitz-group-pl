"""Smoke tests for the core P&L sheet parsers.

These tests use the synthetic fixtures from conftest.py — no real workbook required.
They verify:
  - parse_pl_sheet returns the correct long-format structure and values
  - parse_ratios returns ratio rows (not numeric P&L rows)
  - parse_master returns the correct tidy DataFrame
  - parse_tie_out returns the correct delta DataFrame
  - Parsing is idempotent (calling twice returns the same result)
  - Invalid / empty inputs return empty DataFrames gracefully
"""

from __future__ import annotations

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# parse_pl_sheet
# ---------------------------------------------------------------------------

class TestParsePlSheet:
    def test_returns_long_format_columns(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_pl_sheet

        df = parse_pl_sheet(consolidated_raw, "Consolidated")
        assert set(["Entity", "Metric", "Month", "Value", "MonthDate"]).issubset(df.columns), (
            "parse_pl_sheet must return columns: Entity, Metric, Month, Value, MonthDate"
        )

    def test_entity_column_matches_argument(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_pl_sheet

        df = parse_pl_sheet(consolidated_raw, "Consolidated")
        assert (df["Entity"] == "Consolidated").all(), (
            "Entity column must equal the entity argument passed in"
        )

    def test_expected_metrics_present(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_pl_sheet

        df = parse_pl_sheet(consolidated_raw, "Consolidated")
        expected = [
            "Total Gross Revenue",
            "Total COGS",
            "Gross Profit 2",
            "Total Operating Expenses",
            "EBITDA",
            "NET PROFIT/LOSS (Before Tax)",
        ]
        actual_metrics = df["Metric"].unique().tolist()
        for m in expected:
            assert m in actual_metrics, f"Expected metric '{m}' not found in parse_pl_sheet output"

    def test_ratio_rows_excluded(self, consolidated_raw):
        """Ratio rows (Gross Margin %, EBITDA Margin %) must NOT appear in parse_pl_sheet."""
        from streamlit_app.data.parsers import parse_pl_sheet

        df = parse_pl_sheet(consolidated_raw, "Consolidated")
        ratio_rows = df[df["Metric"].str.lower().str.contains("margin %")]
        assert ratio_rows.empty, (
            "parse_pl_sheet must exclude ratio rows (they belong in parse_ratios)"
        )

    def test_stop_at_usd_block(self, consolidated_raw):
        """Rows at or after 'In USD' marker must not appear in output."""
        from streamlit_app.data.parsers import parse_pl_sheet

        df = parse_pl_sheet(consolidated_raw, "Consolidated")
        assert "In USD" not in df["Metric"].values

    def test_correct_value_jan_2025(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_pl_sheet

        df = parse_pl_sheet(consolidated_raw, "Consolidated")
        val = df[(df["Metric"] == "Total Gross Revenue") & (df["Month"] == "Jan 2025")]["Value"]
        assert not val.empty, "Should have a row for Jan 2025 Total Gross Revenue"
        assert float(val.iloc[0]) == pytest.approx(1_000_000_000), (
            "Jan 2025 Total Gross Revenue value must be 1_000_000_000"
        )

    def test_correct_value_feb_2025(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_pl_sheet

        df = parse_pl_sheet(consolidated_raw, "Consolidated")
        val = df[(df["Metric"] == "EBITDA") & (df["Month"] == "Feb 2025")]["Value"]
        assert float(val.iloc[0]) == pytest.approx(500_000_000)

    def test_sorted_by_month_date(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_pl_sheet

        df = parse_pl_sheet(consolidated_raw, "Consolidated")
        months = df.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
        assert months == ["Jan 2025", "Feb 2025"], (
            "Months must be sorted chronologically"
        )

    def test_idempotent(self, consolidated_raw):
        """Calling parse_pl_sheet twice with the same input returns identical results."""
        from streamlit_app.data.parsers import parse_pl_sheet

        df1 = parse_pl_sheet(consolidated_raw, "Consolidated")
        df2 = parse_pl_sheet(consolidated_raw, "Consolidated")
        pd.testing.assert_frame_equal(df1.reset_index(drop=True), df2.reset_index(drop=True))

    def test_empty_raw_returns_empty_df(self):
        from streamlit_app.data.parsers import parse_pl_sheet

        empty = pd.DataFrame()
        result = parse_pl_sheet(empty, "Test")
        assert result.empty, "parse_pl_sheet on empty input must return empty DataFrame"

    def test_missing_header_row_returns_empty_df(self):
        """A raw sheet with no 'In IDR' row must return empty."""
        from streamlit_app.data.parsers import parse_pl_sheet

        bad = pd.DataFrame({0: ["No header here", "Row 2", "Row 3"]})
        result = parse_pl_sheet(bad, "Test")
        assert result.empty


# ---------------------------------------------------------------------------
# parse_ratios
# ---------------------------------------------------------------------------

class TestParseRatios:
    def test_returns_ratio_rows_only(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_ratios

        df = parse_ratios(consolidated_raw, "Consolidated")
        assert not df.empty, "parse_ratios should find at least one ratio row"
        for metric in df["Metric"].unique():
            assert metric.lower() in {
                "gross margin %", "ebitda margin %", "net margin %",
                "margin %", "operating margin %", "growth %",
            }, f"Unexpected non-ratio metric '{metric}' in parse_ratios output"

    def test_ebitda_margin_value_jan_2025(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_ratios

        df = parse_ratios(consolidated_raw, "Consolidated")
        row = df[(df["Metric"].str.lower() == "ebitda margin %") & (df["Month"] == "Jan 2025")]
        assert not row.empty, "EBITDA Margin % for Jan 2025 should be present"
        assert float(row["Value"].iloc[0]) == pytest.approx(0.40)

    def test_no_pl_metrics_in_ratios(self, consolidated_raw):
        from streamlit_app.data.parsers import parse_ratios

        df = parse_ratios(consolidated_raw, "Consolidated")
        pl_metrics = {"Total Gross Revenue", "Total COGS", "EBITDA"}
        for m in df["Metric"].unique():
            assert m not in pl_metrics, (
                f"P&L metric '{m}' should not appear in parse_ratios output"
            )


# ---------------------------------------------------------------------------
# parse_master
# ---------------------------------------------------------------------------

class TestParseMaster:
    def test_returns_correct_columns(self, master_raw):
        from streamlit_app.data.parsers import parse_master, MASTER_NEEDED_COLS

        df, missing = parse_master(master_raw)
        assert missing == [], f"parse_master reported missing columns: {missing}"
        for col in MASTER_NEEDED_COLS:
            assert col in df.columns, f"Expected column '{col}' not in parse_master output"

    def test_correct_row_count(self, master_raw):
        from streamlit_app.data.parsers import parse_master

        df, missing = parse_master(master_raw)
        assert len(df) == 8, f"Expected 8 data rows, got {len(df)}"

    def test_amount_is_numeric(self, master_raw):
        from streamlit_app.data.parsers import parse_master

        df, _ = parse_master(master_raw)
        assert pd.api.types.is_numeric_dtype(df["Amount (IDR)"]), (
            "Amount (IDR) column must be numeric"
        )

    def test_month_date_column_present_and_sorted(self, master_raw):
        from streamlit_app.data.parsers import parse_master

        df, _ = parse_master(master_raw)
        assert "MonthDate" in df.columns
        dates = df["MonthDate"].dropna()
        assert dates.is_monotonic_increasing, "Rows must be sorted chronologically by MonthDate"

    def test_jan_2025_total_revenue(self, master_raw):
        from streamlit_app.data.parsers import parse_master

        df, _ = parse_master(master_raw)
        jan_total = df[df["Month"] == "Jan 2025"]["Amount (IDR)"].sum()
        assert jan_total == pytest.approx(700_000_000), (
            "Jan 2025 total revenue should be 700M IDR (300+200+150+50)"
        )

    def test_missing_columns_returns_error(self):
        from streamlit_app.data.parsers import parse_master

        # Construct raw with wrong column names
        bad_header = ["WrongCol1", "WrongCol2", "WrongCol3", "WrongCol4", "WrongCol5", "WrongCol6"]
        raw = pd.DataFrame([
            [None] * 6,        # row 0 filler
            bad_header,        # row 1 headers
            ["a", "b", "c", "d", "e", 1],  # row 2 data
        ])
        df, missing = parse_master(raw)
        assert df.empty, "parse_master should return empty DataFrame when columns are missing"
        assert len(missing) > 0, "parse_master should report missing columns"

    def test_idempotent(self, master_raw):
        from streamlit_app.data.parsers import parse_master

        df1, _ = parse_master(master_raw)
        df2, _ = parse_master(master_raw)
        pd.testing.assert_frame_equal(df1.reset_index(drop=True), df2.reset_index(drop=True))


# ---------------------------------------------------------------------------
# parse_tie_out
# ---------------------------------------------------------------------------

class TestParseTieOut:
    def test_returns_expected_columns(self, tie_out_raw):
        from streamlit_app.data.parsers import parse_tie_out

        df = parse_tie_out(tie_out_raw)
        assert not df.empty
        for col in ["Label", "Month", "Delta", "MonthDate"]:
            assert col in df.columns, f"Expected column '{col}' in parse_tie_out output"

    def test_correct_row_count(self, tie_out_raw):
        from streamlit_app.data.parsers import parse_tie_out

        df = parse_tie_out(tie_out_raw)
        # 3 labels × 3 months = 9 rows
        assert len(df) == 9, f"Expected 9 rows, got {len(df)}"

    def test_delta_values_are_numeric(self, tie_out_raw):
        from streamlit_app.data.parsers import parse_tie_out

        df = parse_tie_out(tie_out_raw)
        assert pd.api.types.is_numeric_dtype(df["Delta"])

    def test_specific_delta_value(self, tie_out_raw):
        from streamlit_app.data.parsers import parse_tie_out

        df = parse_tie_out(tie_out_raw)
        # "Master vs Tracker" in "Feb 2025" should be 1_500_000
        row = df[(df["Label"] == "Master vs Tracker") & (df["Month"] == "Feb 2025")]
        assert not row.empty
        assert float(row["Delta"].iloc[0]) == pytest.approx(1_500_000)

    def test_empty_raw_returns_empty(self):
        from streamlit_app.data.parsers import parse_tie_out

        result = parse_tie_out(pd.DataFrame())
        assert result.empty


# ---------------------------------------------------------------------------
# Month-column detection — the P&L grid, and nothing pasted beside it
# ---------------------------------------------------------------------------

def _sheet_with(header: list, rows: list[tuple]) -> pd.DataFrame:
    """Build a raw sheet shaped like the real ones.

    Row 0 is the header: "In IDR" in column 1, month labels from column 2.
    Subsequent rows carry a label in column 1 and values from column 2.
    """
    grid = [[None, "In IDR"] + header]
    for label, values in rows:
        grid.append([None, label] + values)
    return pd.DataFrame(grid)


def test_month_grid_is_contiguous():
    """A side table to the right is separated by at least one blank column."""
    from streamlit_app.data.parsers import _detect_month_cols

    raw = _sheet_with(
        ["Jan 2026", "Feb 2026", None, "Top Clients", "Jan 2026", "Feb 2026"],
        [],
    )
    assert _detect_month_cols(raw, 0) == [2, 3]


def test_a_repeated_month_label_is_taken_once():
    """Belt and braces: uniqueness closes it even without the blank column."""
    from streamlit_app.data.parsers import _detect_month_cols

    raw = _sheet_with(
        ["Jan 2026", "Feb 2026", "Jan 2026", "Feb 2026"],
        [],
    )
    assert _detect_month_cols(raw, 0) == [2, 3]


def test_leading_blank_columns_before_the_grid_are_tolerated():
    from streamlit_app.data.parsers import _detect_month_cols

    raw = _sheet_with([None, "Jan 2026", "Feb 2026"], [])
    assert _detect_month_cols(raw, 0) == [3, 4]


def test_a_side_table_value_is_never_read_as_a_pl_figure():
    """End to end: the exact shape of the Blitz Summary defect, in miniature."""
    from streamlit_app.data.parsers import parse_pl_sheet

    raw = _sheet_with(
        ["Jan 2026", "Feb 2026", None, "Top Clients Monthly", "Jan 2026", "Feb 2026"],
        [
            ("Total Gross Revenue", [2_000_000_000, 2_400_000_000,
                                     None, None, 50_000_000, 693_396_500]),
        ],
    )
    parsed = parse_pl_sheet(raw, "Blitz")
    by_month = parsed.groupby("Month")["Value"].sum()
    assert by_month["Feb 2026"] == 2_400_000_000    # not 3,093,396,500
    assert len(parsed) == 2
