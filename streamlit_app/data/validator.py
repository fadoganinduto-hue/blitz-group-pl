"""Workbook validation — validates an uploaded Excel workbook before rendering.

Checks file size, required sheets, and minimal structural correctness.
Returns a list of ValidationIssue objects; the caller decides how to render them.
No business logic here — only structural/schema checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from streamlit_app.data.parsers import parse_pl_sheet, parse_master, MASTER_NEEDED_COLS

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    """A single validation finding."""
    level: str          # "error" | "warning"
    title: str          # Short headline
    detail: str         # Expanded explanation shown in the UI
    sheet: str = ""     # Relevant sheet name, if applicable


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_MAX_SIZE_WARN_MB: float = 50.0
_MAX_SIZE_BLOCK_MB: float = 200.0
_BYTES_PER_MB: int = 1_048_576

# Required sheets — missing any of these is a hard error
_REQUIRED_SHEETS: list[str] = [
    "Consolidated Summary",
    "MASTER",
]

# Optional sheets — missing these is only a warning
_OPTIONAL_SHEETS: list[str] = [
    "Blitz Summary",
    "Borzo Summary",
    "TheLorry Summary",
    "Settings",
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_workbook(
    file: Any,  # streamlit.runtime.uploaded_file_manager.UploadedFile
    sheets: dict[str, pd.DataFrame],
) -> list[ValidationIssue]:
    """Validate an uploaded workbook and return all issues found.

    Checks are run in order of severity. Critical errors (level="error") should
    cause the caller to halt rendering; warnings are advisory only.

    Parameters
    ----------
    file:
        The Streamlit UploadedFile object (has .name and .size attributes).
    sheets:
        The dict[sheet_name → DataFrame] returned by load_all_sheets().

    Returns
    -------
    List of ValidationIssue objects, ordered errors-first.
    """
    issues: list[ValidationIssue] = []

    # 1. File size check
    issues.extend(_check_file_size(file))
    # Stop immediately if the file is too large to safely process
    if any(i.level == "error" and "file size" in i.title.lower() for i in issues):
        return issues

    # 2. Required sheets present
    issues.extend(_check_required_sheets(sheets))
    # Stop structural checks if critical sheets are absent
    critical_missing = {
        i.sheet for i in issues
        if i.level == "error" and "missing" in i.title.lower()
    }
    if critical_missing:
        return issues

    # 3. Optional sheets (warnings only)
    issues.extend(_check_optional_sheets(sheets))

    # 4. Consolidated Summary structure
    issues.extend(_check_consolidated_summary(sheets))

    # 5. MASTER sheet column completeness
    issues.extend(_check_master_sheet(sheets))

    return issues


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_file_size(file: Any) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        size_mb = file.size / _BYTES_PER_MB
    except AttributeError:
        return issues  # Can't determine size — skip check

    if size_mb > _MAX_SIZE_BLOCK_MB:
        issues.append(ValidationIssue(
            level="error",
            title="File size exceeds limit",
            detail=(
                f"The uploaded file is {size_mb:.0f} MB. "
                f"The maximum allowed size is {_MAX_SIZE_BLOCK_MB:.0f} MB. "
                "Please reduce the workbook size (remove unused sheets or data) and re-upload."
            ),
        ))
    elif size_mb > _MAX_SIZE_WARN_MB:
        issues.append(ValidationIssue(
            level="warning",
            title="Large file detected",
            detail=(
                f"The workbook is {size_mb:.0f} MB. "
                f"Files over {_MAX_SIZE_WARN_MB:.0f} MB may load slowly. "
                "Consider archiving historical data or splitting into smaller workbooks."
            ),
        ))
    return issues


def _check_required_sheets(sheets: dict[str, pd.DataFrame]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for sheet_name in _REQUIRED_SHEETS:
        if sheet_name not in sheets:
            issues.append(ValidationIssue(
                level="error",
                title=f"Required sheet missing: '{sheet_name}'",
                detail=(
                    f"The workbook must contain a sheet named exactly '{sheet_name}'. "
                    "Check that the sheet exists and is not hidden or renamed. "
                    "This sheet is essential for the dashboard to function."
                ),
                sheet=sheet_name,
            ))
    return issues


def _check_optional_sheets(sheets: dict[str, pd.DataFrame]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for sheet_name in _OPTIONAL_SHEETS:
        if sheet_name not in sheets:
            issues.append(ValidationIssue(
                level="warning",
                title=f"Optional sheet not found: '{sheet_name}'",
                detail=(
                    f"'{sheet_name}' was not found. "
                    "Some dashboard views may be limited or unavailable. "
                    "This is not an error if this sheet is intentionally excluded."
                ),
                sheet=sheet_name,
            ))
    return issues


def _check_consolidated_summary(sheets: dict[str, pd.DataFrame]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    raw = sheets.get("Consolidated Summary")
    if raw is None:
        return issues  # Already caught by _check_required_sheets

    try:
        parsed = parse_pl_sheet(raw, "Consolidated")
    except Exception as exc:  # noqa: BLE001
        issues.append(ValidationIssue(
            level="error",
            title="Consolidated Summary could not be parsed",
            detail=(
                "The 'Consolidated Summary' sheet was found but could not be read. "
                "Ensure it contains an 'In IDR' header row and at least one month column. "
                f"Technical detail: {type(exc).__name__}."
            ),
            sheet="Consolidated Summary",
        ))
        return issues

    if parsed.empty:
        issues.append(ValidationIssue(
            level="error",
            title="Consolidated Summary contains no parseable data",
            detail=(
                "The 'Consolidated Summary' sheet was found but returned no rows after parsing. "
                "Verify that:\n"
                "  • The sheet has an 'In IDR' row in the first 5 rows\n"
                "  • Month headers (e.g. 'Jan 2025') are present in row 1–5\n"
                "  • Financial rows have numeric values in the month columns"
            ),
            sheet="Consolidated Summary",
        ))
    return issues


def _check_master_sheet(sheets: dict[str, pd.DataFrame]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    raw = sheets.get("MASTER")
    if raw is None:
        return issues  # Already caught by _check_required_sheets

    try:
        _, missing_cols = parse_master(raw)
    except Exception as exc:  # noqa: BLE001
        issues.append(ValidationIssue(
            level="error",
            title="MASTER sheet could not be parsed",
            detail=(
                "The 'MASTER' sheet was found but could not be read. "
                f"Technical detail: {type(exc).__name__}."
            ),
            sheet="MASTER",
        ))
        return issues

    if missing_cols:
        issues.append(ValidationIssue(
            level="error",
            title="MASTER sheet is missing required columns",
            detail=(
                f"The following columns were not found in 'MASTER': {missing_cols}. "
                f"Expected columns: {MASTER_NEEDED_COLS}. "
                "Check that row 2 of the MASTER sheet contains the correct column headers."
            ),
            sheet="MASTER",
        ))
    return issues
