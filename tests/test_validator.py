"""Smoke tests for the workbook validator.

Tests validate_workbook() behaviour for:
  - Missing required sheets → error issues
  - File size limits
  - Valid workbook → no errors
  - Missing MASTER columns → error
  - Optional sheet absence → warning only (not error)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file_mock(name: str = "workbook.xlsx", size_bytes: int = 1_000) -> SimpleNamespace:
    """Return a minimal file-like object with .name and .size as plain attributes.

    Using SimpleNamespace instead of MagicMock ensures .size is always an int
    with no descriptor magic, so `file.size / _BYTES_PER_MB` works correctly.
    """
    return SimpleNamespace(name=name, size=size_bytes)


# ---------------------------------------------------------------------------
# Required sheets
# ---------------------------------------------------------------------------

class TestRequiredSheets:
    def test_valid_workbook_has_no_errors(self, valid_sheets):
        from streamlit_app.data.validator import validate_workbook

        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, valid_sheets)
        errors = [i for i in issues if i.level == "error"]
        assert errors == [], f"Valid workbook should have no errors; got: {errors}"

    def test_missing_consolidated_summary_is_error(self, master_raw):
        from streamlit_app.data.validator import validate_workbook

        sheets = {"MASTER": master_raw}  # No Consolidated Summary
        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, sheets)
        errors = [i for i in issues if i.level == "error"]
        assert any("Consolidated Summary" in i.title for i in errors), (
            "Missing 'Consolidated Summary' must produce an error issue"
        )

    def test_missing_master_is_error(self, consolidated_raw):
        from streamlit_app.data.validator import validate_workbook

        sheets = {"Consolidated Summary": consolidated_raw}  # No MASTER
        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, sheets)
        errors = [i for i in issues if i.level == "error"]
        assert any("MASTER" in i.title for i in errors), (
            "Missing 'MASTER' must produce an error issue"
        )

    def test_missing_both_required_sheets(self):
        from streamlit_app.data.validator import validate_workbook

        sheets: dict[str, pd.DataFrame] = {}
        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, sheets)
        errors = [i for i in issues if i.level == "error"]
        assert len(errors) >= 2, (
            "Missing both required sheets must produce at least 2 error issues"
        )


# ---------------------------------------------------------------------------
# Optional sheets
# ---------------------------------------------------------------------------

class TestOptionalSheets:
    def test_missing_optional_sheet_is_warning_not_error(self, valid_sheets):
        from streamlit_app.data.validator import validate_workbook

        # Remove TIE-OUT CHECK (optional) from the valid sheets
        sheets = {k: v for k, v in valid_sheets.items() if k != "TIE-OUT CHECK"}
        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, sheets)

        errors = [i for i in issues if i.level == "error"]
        warnings = [i for i in issues if i.level == "warning" and "TIE-OUT CHECK" in i.title]

        assert errors == [], "Missing optional sheet must NOT produce an error"
        assert warnings, "Missing optional sheet must produce a warning"

    def test_all_optional_sheets_absent_produces_warnings_only(self, consolidated_raw, master_raw):
        from streamlit_app.data.validator import validate_workbook

        sheets = {
            "Consolidated Summary": consolidated_raw,
            "MASTER": master_raw,
            # All optional sheets absent
        }
        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, sheets)
        errors = [i for i in issues if i.level == "error"]
        assert errors == [], "Absent optional sheets must not produce errors"


# ---------------------------------------------------------------------------
# File size
# ---------------------------------------------------------------------------

class TestFileSize:
    def test_large_file_produces_warning(self, valid_sheets):
        from streamlit_app.data.validator import validate_workbook

        # 60 MB — above warn threshold (50 MB), below block threshold (200 MB)
        file_mock = _make_file_mock(size_bytes=60 * 1_048_576)
        issues = validate_workbook(file_mock, valid_sheets)
        warnings = [
            i for i in issues
            if i.level == "warning" and (
                "large file" in i.title.lower() or "size" in i.title.lower()
            )
        ]
        assert warnings, "A 60 MB file should produce a size warning"

    def test_huge_file_produces_error(self, valid_sheets):
        from streamlit_app.data.validator import validate_workbook

        # 210 MB — above block threshold (200 MB)
        file_mock = _make_file_mock(size_bytes=210 * 1_048_576)
        issues = validate_workbook(file_mock, valid_sheets)
        errors = [i for i in issues if i.level == "error" and "size" in i.title.lower()]
        assert errors, "A 210 MB file should produce a blocking size error"

    def test_normal_file_no_size_issue(self, valid_sheets):
        from streamlit_app.data.validator import validate_workbook

        file_mock = _make_file_mock(size_bytes=5 * 1_048_576)  # 5 MB — fine
        issues = validate_workbook(file_mock, valid_sheets)
        size_issues = [i for i in issues if "size" in i.title.lower()]
        assert size_issues == [], "A 5 MB file should not produce any size issue"


# ---------------------------------------------------------------------------
# MASTER column completeness
# ---------------------------------------------------------------------------

class TestMasterColumns:
    def test_valid_master_no_column_error(self, valid_sheets):
        from streamlit_app.data.validator import validate_workbook

        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, valid_sheets)
        col_errors = [
            i for i in issues
            if i.level == "error" and "missing" in i.title.lower() and i.sheet == "MASTER"
        ]
        assert col_errors == [], "Valid MASTER sheet must not produce missing-column errors"

    def test_missing_master_columns_produces_error(self, consolidated_raw):
        from streamlit_app.data.validator import validate_workbook

        # MASTER with wrong headers
        bad_master = pd.DataFrame([
            [None, None, None, None, None, None],    # filler
            ["Bad1", "Bad2", "Bad3", "Bad4", "Bad5", "Bad6"],  # wrong headers
            ["Blitz", "X", "Y", "Z", "Jan 2025", 100],
        ])
        sheets = {"Consolidated Summary": consolidated_raw, "MASTER": bad_master}
        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, sheets)
        col_errors = [
            i for i in issues
            if i.level == "error" and i.sheet == "MASTER"
        ]
        assert col_errors, "MASTER with wrong column names must produce an error"


# ---------------------------------------------------------------------------
# Consolidated Summary structure
# ---------------------------------------------------------------------------

class TestConsolidatedSummaryStructure:
    def test_valid_consolidated_no_structure_error(self, valid_sheets):
        from streamlit_app.data.validator import validate_workbook

        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, valid_sheets)
        struct_errors = [
            i for i in issues
            if i.level == "error" and i.sheet == "Consolidated Summary"
        ]
        assert struct_errors == [], "Valid Consolidated Summary must not produce structure errors"

    def test_empty_consolidated_produces_error(self, master_raw):
        from streamlit_app.data.validator import validate_workbook

        sheets = {
            "Consolidated Summary": pd.DataFrame(),  # Empty
            "MASTER": master_raw,
        }
        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, sheets)
        errors = [
            i for i in issues
            if i.level == "error" and i.sheet == "Consolidated Summary"
        ]
        assert errors, "Empty Consolidated Summary must produce an error"


# ---------------------------------------------------------------------------
# Issue format integrity
# ---------------------------------------------------------------------------

class TestIssueFormat:
    def test_all_issues_have_required_fields(self, valid_sheets):
        from streamlit_app.data.validator import validate_workbook, ValidationIssue

        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, valid_sheets)

        for issue in issues:
            assert isinstance(issue, ValidationIssue), "All issues must be ValidationIssue instances"
            assert issue.level in {"error", "warning"}, f"Unexpected level: {issue.level}"
            assert issue.title, "Issue must have a non-empty title"
            assert issue.detail, "Issue must have non-empty detail"

    def test_no_python_traceback_in_messages(self, valid_sheets):
        from streamlit_app.data.validator import validate_workbook

        file_mock = _make_file_mock()
        issues = validate_workbook(file_mock, valid_sheets)
        for issue in issues:
            # Tracebacks contain "Traceback (most recent call last)" — must never appear
            assert "Traceback" not in issue.detail, (
                f"Issue detail must not expose Python tracebacks: {issue.detail[:80]}"
            )
