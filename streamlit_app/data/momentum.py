"""Month-on-month movement, computed once and honestly.

The dashboard already reports MoM for a single month, on the KPI cards. Reading
a *series* of MoM figures meant moving the context month one step at a time and
writing the answers down. This module produces the whole series at once.

Four things it refuses to do, because each produces a number that looks like
growth and is not:

* **Compare against a month that has not closed.** The workbook carries a full
  12-month grid, so an unclosed month reads as zero. Comparing May against an
  empty June is a −100% that never happened.
* **Compare against a month that is not the previous one.** If the workbook
  skips a period, ``shift(1)`` silently produces a two-month change labelled
  "MoM". Adjacency is checked on the calendar, not on row order.
* **Divide by a base too small to carry a percentage.** A month that closed at
  Rp2M followed by one at Rp200M is not "+9,900% growth"; it is a base effect.
  Below the floor the delta is reported and the percentage is withheld.
* **Divide by a signed base.** Blitz runs a net loss. Moving from −Rp2.4B to
  −Rp2.0B is a Rp400M *improvement*, but dividing by −2.4 renders it −16.7%,
  which reads as deterioration. The denominator is always ``abs(prior)``, so
  the sign of the percentage always matches the sign of the delta.

Every excluded row is kept in the frame with a ``Basis`` explaining why, so the
caller can say what is missing rather than drawing a shorter chart.
"""

from __future__ import annotations

import pandas as pd

from streamlit_app.data.periods import restrict_to_actuals

# Smallest prior-month magnitude that can carry a percentage. Below this a
# percentage is arithmetically valid and financially meaningless.
MOM_PCT_BASE_FLOOR: float = 50_000_000.0  # Rp50M

# Reasons a month carries no comparable MoM figure.
BASIS_OK = "ok"
BASIS_NO_PRIOR = "no prior month"
BASIS_GAP = "prior month missing"
BASIS_SMALL_BASE = "prior month too small to percentage"

_COLUMNS = [
    "Entity", "Month", "MonthDate", "Value", "Prior",
    "Delta", "Pct", "Basis", "Comparable",
]


def month_on_month(
    long_df: pd.DataFrame,
    metric: str,
    *,
    months: list[str] | None = None,
    group_col: str = "Entity",
    base_floor: float = MOM_PCT_BASE_FLOOR,
) -> pd.DataFrame:
    """Return per-group month-on-month movement for one metric.

    Columns: Entity (or ``group_col``), Month, MonthDate, Value, Prior, Delta,
    Pct, Basis, Comparable.

    The comparison always reaches across the full closed history, then the
    result is restricted to ``months``. That way the first month on screen still
    carries a real MoM instead of an empty bar just because the range slider
    starts there.
    """
    if long_df is None or long_df.empty:
        return pd.DataFrame(columns=_COLUMNS)
    required = {"Metric", "Month", "MonthDate", "Value", group_col}
    if not required.issubset(long_df.columns):
        return pd.DataFrame(columns=_COLUMNS)

    # Closed months only — an unclosed month is a zero, not a collapse.
    closed = restrict_to_actuals(
        long_df.drop_duplicates("Month").sort_values("MonthDate")["Month"].tolist(),
        long_df,
    )
    if not closed:
        return pd.DataFrame(columns=_COLUMNS)

    frame = long_df[
        (long_df["Metric"] == metric) & (long_df["Month"].isin(closed))
    ]
    if frame.empty:
        return pd.DataFrame(columns=_COLUMNS)

    frame = (
        frame.groupby([group_col, "Month", "MonthDate"], as_index=False)["Value"]
        .sum()
        .sort_values([group_col, "MonthDate"])
        .reset_index(drop=True)
    )

    frame["Prior"] = frame.groupby(group_col)["Value"].shift(1)
    prior_date = frame.groupby(group_col)["MonthDate"].shift(1)

    # Adjacency on the calendar, not on row order: a workbook that skips a month
    # would otherwise hand back a two-month change wearing a "MoM" label.
    this_period = pd.PeriodIndex(pd.to_datetime(frame["MonthDate"]), freq="M")
    prev_period = pd.PeriodIndex(pd.to_datetime(prior_date), freq="M")
    step = pd.Series(
        [
            (a - b).n if pd.notna(p) else None
            for a, b, p in zip(this_period, prev_period, prior_date)
        ],
        index=frame.index,
        dtype="object",
    )

    frame["Delta"] = frame["Value"] - frame["Prior"]
    frame["Basis"] = BASIS_OK
    frame.loc[frame["Prior"].isna(), "Basis"] = BASIS_NO_PRIOR
    frame.loc[frame["Prior"].notna() & (step != 1), "Basis"] = BASIS_GAP
    # A non-adjacent comparison is not a MoM delta either.
    frame.loc[frame["Basis"] == BASIS_GAP, "Delta"] = float("nan")

    base = frame["Prior"].abs()
    too_small = (frame["Basis"] == BASIS_OK) & (base < base_floor)
    frame.loc[too_small, "Basis"] = BASIS_SMALL_BASE

    # abs(prior) as the denominator — see the module docstring on loss-making
    # entities. The sign of Pct then always matches the sign of Delta.
    frame["Pct"] = frame["Delta"] / base
    frame.loc[frame["Basis"] != BASIS_OK, "Pct"] = float("nan")
    frame["Comparable"] = frame["Basis"] == BASIS_OK

    if months is not None:
        frame = frame[frame["Month"].isin(months)]

    return frame.sort_values(["MonthDate", group_col]).reset_index(drop=True)[_COLUMNS]


def momentum_caveats(mom: pd.DataFrame) -> list[str]:
    """Return one plain sentence per reason a month carries no MoM figure.

    A chart with a missing bar and no explanation reads as a zero.
    """
    if mom is None or mom.empty or "Basis" not in mom.columns:
        return []

    notes: list[str] = []
    excluded = mom[mom["Basis"] != BASIS_OK]
    for basis, wording in (
        (BASIS_GAP, "the workbook has no figure for the month before"),
        (BASIS_SMALL_BASE, "the prior month is too small for a percentage to mean anything — the change in rupiah is shown"),
        (BASIS_NO_PRIOR, "no closed month precedes it in the workbook"),
    ):
        rows = excluded[excluded["Basis"] == basis]
        if rows.empty:
            continue
        labels = sorted(
            {f"{r.Entity} {r.Month}" for r in rows.itertuples()},
            key=str,
        )
        shown = ", ".join(labels[:4]) + (f" (+{len(labels) - 4} more)" if len(labels) > 4 else "")
        notes.append(f"No month-on-month figure for {shown}: {wording}.")
    return notes
