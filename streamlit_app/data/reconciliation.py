"""Independent reconciliation checks computed from the workbook itself.

The TIE-OUT CHECK sheet is maintained by hand and can lag the P&L. These checks
are derived directly from the parsed data, so they cannot go stale:

* ``master_vs_pl_bridge`` — per-client MASTER revenue vs the Consolidated P&L
  Total Gross Revenue, per month. This is the number the team tracks manually
  and it did not previously appear anywhere in the dashboard.
* ``coverage_gaps`` — months the P&L has closed but MASTER or TIE-OUT has not
  caught up on. Silent coverage gaps are how an unreconciled month gets reported
  as "healthy".
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Absolute IDR variance that counts as material for the derived bridge.
BRIDGE_MATERIALITY_IDR: float = 1_000_000.0

PL_REVENUE_METRIC: str = "Total Gross Revenue"


def master_vs_pl_bridge(
    master: pd.DataFrame,
    cons_long: pd.DataFrame,
    *,
    months: list[str] | None = None,
) -> pd.DataFrame:
    """Return per-month MASTER vs Consolidated P&L revenue with the variance.

    Columns: Month, MonthDate, MasterRevenue, PLRevenue, Delta, AbsDelta, PctOfPL.
    Months present in only one source are still returned, with the missing side
    as NaN, so a coverage gap shows up rather than silently reconciling to zero.
    """
    empty = pd.DataFrame(
        columns=[
            "Month", "MonthDate", "MasterRevenue", "PLRevenue",
            "Delta", "AbsDelta", "PctOfPL",
        ]
    )
    if master is None or master.empty or cons_long is None or cons_long.empty:
        return empty
    if "Amount (IDR)" not in master.columns or "Month" not in master.columns:
        return empty

    m = (
        master.groupby(["Month", "MonthDate"], as_index=False)["Amount (IDR)"]
        .sum()
        .rename(columns={"Amount (IDR)": "MasterRevenue"})
    )
    p = (
        cons_long[cons_long["Metric"] == PL_REVENUE_METRIC]
        .groupby(["Month", "MonthDate"], as_index=False)["Value"]
        .sum()
        .rename(columns={"Value": "PLRevenue"})
    )
    if m.empty or p.empty:
        return empty

    bridge = m.merge(p, on=["Month", "MonthDate"], how="outer")

    if months is not None:
        bridge = bridge[bridge["Month"].isin(months)]

    bridge["Delta"] = bridge["MasterRevenue"].fillna(0) - bridge["PLRevenue"].fillna(0)
    bridge["AbsDelta"] = bridge["Delta"].abs()
    bridge["PctOfPL"] = bridge.apply(
        lambda r: (r["Delta"] / r["PLRevenue"]) if r.get("PLRevenue") else float("nan"),
        axis=1,
    )
    return bridge.sort_values("MonthDate").reset_index(drop=True)


@dataclass(frozen=True)
class CoverageGap:
    """A month the P&L has closed but a downstream source has not covered."""

    source: str
    months: tuple[str, ...]

    @property
    def detail(self) -> str:
        listed = ", ".join(self.months)
        return (
            f"{self.source} has no data for {listed}. Revenue for "
            f"{'those months is' if len(self.months) > 1 else 'that month is'} "
            f"unreconciled and unattributed to clients."
        )


def coverage_gaps(
    actual_pl_months: list[str],
    master: pd.DataFrame | None,
    tie_out: pd.DataFrame | None,
) -> list[CoverageGap]:
    """Return closed P&L months that MASTER or TIE-OUT does not cover."""
    gaps: list[CoverageGap] = []
    if not actual_pl_months:
        return gaps

    for source, df in (("Client breakdown (MASTER)", master), ("TIE-OUT CHECK", tie_out)):
        if df is None or df.empty or "Month" not in df.columns:
            continue
        covered = set(df["Month"].dropna().astype(str))
        missing = tuple(m for m in actual_pl_months if m not in covered)
        if missing:
            gaps.append(CoverageGap(source=source, months=missing))
    return gaps


def unreconciled_summary(
    deltas: pd.DataFrame,
    threshold: float,
) -> dict[str, float | int]:
    """Summarise variance activity so sub-threshold breaks are never hidden.

    ``flagged`` counts variances above the caller's threshold; ``below_threshold``
    counts variances that are non-zero but did not clear it. The Data Health tab
    must report both — reporting only ``flagged`` lets a raised threshold read as
    "everything ties out".
    """
    if deltas is None or deltas.empty or "Delta" not in deltas.columns:
        return {
            "total_rows": 0, "flagged": 0, "below_threshold": 0,
            "zero": 0, "gross_variance": 0.0, "net_variance": 0.0, "largest": 0.0,
        }

    abs_delta = deltas["Delta"].abs()
    non_zero = abs_delta > 0.5
    return {
        "total_rows": int(len(deltas)),
        "flagged": int((abs_delta > threshold).sum()),
        "below_threshold": int((non_zero & (abs_delta <= threshold)).sum()),
        "zero": int((~non_zero).sum()),
        "gross_variance": float(abs_delta.sum()),
        "net_variance": float(deltas["Delta"].sum()),
        "largest": float(abs_delta.max()),
    }
