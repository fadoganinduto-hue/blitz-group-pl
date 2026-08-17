"""Reconciliation checks computed from the workbook itself.

These replace the hand-maintained TIE-OUT CHECK sheet, which is being retired.
Both are derived from the parsed data on every load, so neither can go stale:

* ``master_vs_pl_bridge`` — per-client MASTER revenue against Consolidated
  Total Gross Revenue, month by month. The number the team tracks by hand.
* ``coverage_gaps`` — months the P&L has closed that a downstream source has
  not reached. Silent coverage gaps are how an unreconciled month gets reported
  as healthy.

The two are deliberately separate. A month covered by only one source cannot be
reconciled at all, and treating that as a variance produces figures that are
both enormous and meaningless.
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

    Columns: Month, MonthDate, MasterRevenue, PLRevenue, Delta, AbsDelta,
    PctOfPL, Comparable.

    Months present in only one source are still returned, with the missing side
    as NaN, so a coverage gap shows up rather than silently reconciling to zero
    — but they are marked ``Comparable = False`` and carry a NaN Delta. Callers
    reporting variance totals must filter on ``Comparable``.
    """
    empty = pd.DataFrame(
        columns=[
            "Month", "MonthDate", "MasterRevenue", "PLRevenue",
            "Delta", "AbsDelta", "PctOfPL", "Comparable",
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

    # A month can only be reconciled when BOTH sources cover it and the P&L has
    # closed it. Months present in one source alone are COVERAGE gaps, not
    # variances — scoring them as variances turned 18 months that MASTER simply
    # does not reach into billion-rupiah breaks and reported Rp32B "gross
    # unreconciled" against a true Rp348M. They are reported by coverage_gaps().
    bridge["Comparable"] = (
        bridge["MasterRevenue"].notna()
        & bridge["PLRevenue"].notna()
        & (bridge["PLRevenue"] != 0)
    )
    bridge["Delta"] = bridge["MasterRevenue"].fillna(0) - bridge["PLRevenue"].fillna(0)
    bridge.loc[~bridge["Comparable"], "Delta"] = float("nan")
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
    tie_out: pd.DataFrame | None = None,
) -> list[CoverageGap]:
    """Return closed P&L months that a downstream source does not cover.

    ``tie_out`` is retained so an alternative reconciliation source can be
    passed later; the retired TIE-OUT CHECK sheet is no longer supplied.
    """
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


def summary_vs_detail(
    summary_frames: dict[str, pd.DataFrame],
    detail_frames: dict[str, pd.DataFrame],
    metric: str = PL_REVENUE_METRIC,
    *,
    materiality: float = BRIDGE_MATERIALITY_IDR,
) -> pd.DataFrame:
    """Where the Summary and Detail sheets disagree on the same figure.

    The Entity tab lets the reader toggle granularity, and the two sheets are
    meant to be two views of one truth. They are not always: on the current
    workbook Blitz Jun 2026 revenue is Rp3,661,974,619 on Summary and
    Rp2,968,578,119 on Detail — a Rp693M swing that follows a toggle nobody
    would expect to change a number.

    Returns Entity, Month, MonthDate, Summary, Detail, Delta for every
    disagreement above materiality.
    """
    rows: list[dict] = []
    for entity, summary in (summary_frames or {}).items():
        detail = (detail_frames or {}).get(entity)
        if summary is None or detail is None or summary.empty or detail.empty:
            continue
        s_vals = (
            summary[summary["Metric"] == metric]
            .groupby(["Month", "MonthDate"], as_index=False)["Value"].sum()
        )
        d_vals = (
            detail[detail["Metric"] == metric]
            .groupby(["Month", "MonthDate"], as_index=False)["Value"].sum()
        )
        merged = s_vals.merge(
            d_vals, on=["Month", "MonthDate"], how="inner",
            suffixes=("_summary", "_detail"),
        )
        for _, r in merged.iterrows():
            delta = float(r["Value_summary"]) - float(r["Value_detail"])
            if abs(delta) > materiality:
                rows.append({
                    "Entity": entity, "Month": r["Month"], "MonthDate": r["MonthDate"],
                    "Summary": float(r["Value_summary"]),
                    "Detail": float(r["Value_detail"]), "Delta": delta,
                })
    if not rows:
        return pd.DataFrame(columns=["Entity","Month","MonthDate","Summary","Detail","Delta"])
    return pd.DataFrame(rows).sort_values(
        ["MonthDate", "Entity"]).reset_index(drop=True)


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
