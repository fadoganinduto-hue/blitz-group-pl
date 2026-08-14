"""Actual-vs-placeholder month detection.

The Group P&L workbook carries a full 12-month column grid for the current year,
so months that have not been closed yet are present but empty (or hold rounding
artefacts such as a Net Profit of -1). Treating those as real months makes every
"latest month" KPI read Rp0 / -100% MoM and halves every period average.

Every tab MUST resolve its month list through this module rather than taking
``months[-1]`` or ``df["Month"].max()`` directly.
"""

from __future__ import annotations

import pandas as pd

# A month only counts as closed if gross revenue clears this floor. The workbook
# has been observed to carry values as small as -1 in unclosed months, so a bare
# `!= 0` test is not sufficient.
ACTUALS_REVENUE_FLOOR: float = 1_000_000.0  # Rp1M

# Metrics that indicate a month has real activity, in priority order.
_ACTUALS_PROBE_METRICS: tuple[str, ...] = (
    "Total Gross Revenue",
    "Gross Revenue",
    "Total COGS",
)


def actual_months(
    long_df: pd.DataFrame,
    *,
    floor: float = ACTUALS_REVENUE_FLOOR,
    value_col: str | None = None,
) -> list[str]:
    """Return the chronologically sorted month labels that hold closed actuals.

    Parameters
    ----------
    long_df:
        A tidy P&L frame with ``Metric``, ``Month``, ``MonthDate`` and ``Value``,
        or any frame with ``Month``/``MonthDate`` plus ``value_col``.
    floor:
        Absolute IDR floor a probe metric must clear for the month to count.
    value_col:
        Amount column to total when the frame has no ``Metric`` column — for
        example ``"Amount (IDR)"`` on the MASTER client detail.
    """
    if long_df is None or long_df.empty:
        return []

    if value_col is not None:
        if not {"Month", value_col}.issubset(long_df.columns):
            return []
        totals = (
            long_df.groupby(["Month", "MonthDate"], as_index=False)[value_col]
            .sum()
            .rename(columns={value_col: "Value"})
        )
        live = totals[totals["Value"].abs() >= floor]
        return live.sort_values("MonthDate")["Month"].tolist()

    if not {"Metric", "Month", "Value"}.issubset(long_df.columns):
        return []

    probe = next(
        (m for m in _ACTUALS_PROBE_METRICS if (long_df["Metric"] == m).any()),
        None,
    )
    if probe is None:
        # No probe metric present — fall back to "any month with material data".
        totals = long_df.groupby(["Month", "MonthDate"], as_index=False)["Value"].apply(
            lambda s: s.abs().sum()
        )
        totals.columns = ["Month", "MonthDate", "Value"]
    else:
        totals = (
            long_df[long_df["Metric"] == probe]
            .groupby(["Month", "MonthDate"], as_index=False)["Value"]
            .sum()
        )

    live = totals[totals["Value"].abs() >= floor]
    return live.sort_values("MonthDate")["Month"].tolist()


def latest_actual_month(
    long_df: pd.DataFrame,
    *,
    floor: float = ACTUALS_REVENUE_FLOOR,
) -> str | None:
    """Return the most recent closed month, or None when nothing has closed."""
    months = actual_months(long_df, floor=floor)
    return months[-1] if months else None


def restrict_to_actuals(
    months: list[str],
    long_df: pd.DataFrame,
    *,
    floor: float = ACTUALS_REVENUE_FLOOR,
    value_col: str | None = None,
) -> list[str]:
    """Filter a caller's month selection down to closed months, order preserved."""
    live = set(actual_months(long_df, floor=floor, value_col=value_col))
    return [m for m in months if m in live]


def placeholder_months(
    long_df: pd.DataFrame,
    *,
    floor: float = ACTUALS_REVENUE_FLOOR,
) -> list[str]:
    """Return month labels present in the workbook but not yet closed."""
    if long_df is None or long_df.empty or "Month" not in long_df.columns:
        return []
    live = set(actual_months(long_df, floor=floor))
    all_months = (
        long_df.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist()
    )
    return [m for m in all_months if m not in live]
