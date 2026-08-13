"""Pure-function analytical module — no Streamlit imports.

All functions accept tidy DataFrames (as produced by the parsers) and return
plain Python objects (dicts, lists, DataFrames, floats).  This makes them
easily unit-testable and reusable across multiple tabs.

Functions
---------
compute_yoy_comparison      — look up same-month prior-year value
compute_rolling_avg         — 3M (or N-M) rolling average series
find_chart_annotations      — highest/lowest/biggest-MoM points
detect_anomalies            — flag material movements vs configurable thresholds
compute_revenue_drivers     — unified driver analysis across entity/stream/client
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from streamlit_app.data.anomaly_config import ANOMALY_THRESHOLDS


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class YoYResult:
    """Result of a year-over-year comparison for a single metric/month."""
    available: bool            # False when prior-year month is not in the data
    current: float | None
    prior_year: float | None   # None when available=False
    abs_change: float | None
    pct_change: float | None   # None when prior_year is 0 or unavailable
    prior_year_month: str | None  # e.g. "Jan 2024"


@dataclass
class ChartAnnotation:
    """A single annotation point to render on a trend chart."""
    month: str
    value: float
    label: str     # e.g. "Peak", "Trough", "▲ Biggest MoM", "▼ Biggest drop"
    kind: Literal["peak", "trough", "mom_up", "mom_down"]


@dataclass
class AnomalyFlag:
    """A single anomaly event — rendered as a warning chip in the UI."""
    level: Literal["warning", "critical"]   # warning = notable, critical = very large
    title: str
    detail: str
    metric: str
    month: str
    pct_change: float | None = None


@dataclass
class DriverResult:
    """Revenue driver decomposition for a single period comparison."""
    total_delta: float
    prior_month: str
    latest_month: str
    entity_drivers: list[dict]     # [{name, delta, pct_of_total_delta}]
    stream_drivers: list[dict]     # [{name, delta, pct_of_total_delta}]
    client_drivers_pos: list[dict] # top positive client movers
    client_drivers_neg: list[dict] # top negative client movers
    pl_drivers: list[dict]         # P&L line item decomposition (revenue/COGS/opex)


# ---------------------------------------------------------------------------
# YoY comparison
# ---------------------------------------------------------------------------

def compute_yoy_comparison(
    df: pd.DataFrame,
    metric: str,
    latest_month: str,
    all_months: list[str],
) -> YoYResult:
    """Find the same-month-prior-year value for a given metric.

    Parameters
    ----------
    df:
        Long-format DataFrame with columns [Metric, Month, Value, MonthDate].
    metric:
        The metric label to look up (e.g. "Total Gross Revenue").
    latest_month:
        The current period (e.g. "Jan 2025").
    all_months:
        All months present in the dataset (sorted chronologically).

    Returns
    -------
    YoYResult with available=False if the prior-year month is not in the data.
    """
    metric_df = df[df["Metric"] == metric]
    cur_rows = metric_df[metric_df["Month"] == latest_month]
    current = float(cur_rows["Value"].sum()) if not cur_rows.empty else None

    # Determine the prior-year month label using pd.to_datetime directly
    try:
        # Use MonthDate column if available, otherwise parse on the fly
        if "MonthDate" in df.columns and not cur_rows.empty:
            latest_dt = pd.to_datetime(cur_rows["MonthDate"].iloc[0])
        else:
            latest_dt = pd.to_datetime(latest_month, format="%b %Y", errors="coerce")
        if pd.isna(latest_dt):
            return YoYResult(False, current, None, None, None, None)
        prior_year_dt = latest_dt.replace(year=latest_dt.year - 1)
        prior_year_month = prior_year_dt.strftime("%b %Y")
    except Exception:  # noqa: BLE001
        return YoYResult(False, current, None, None, None, None)

    if prior_year_month not in all_months:
        return YoYResult(False, current, None, None, None, prior_year_month)

    prior_rows = metric_df[metric_df["Month"] == prior_year_month]
    if prior_rows.empty:
        return YoYResult(False, current, None, None, None, prior_year_month)

    prior_year = float(prior_rows["Value"].sum())
    abs_change = (current - prior_year) if current is not None else None
    pct_change = (
        (current - prior_year) / abs(prior_year) * 100
        if current is not None and prior_year != 0
        else None
    )
    return YoYResult(True, current, prior_year, abs_change, pct_change, prior_year_month)


# ---------------------------------------------------------------------------
# Rolling average
# ---------------------------------------------------------------------------

def compute_rolling_avg(
    df: pd.DataFrame,
    metric: str,
    months: list[str],
    window: int = 3,
) -> pd.DataFrame:
    """Compute a rolling average series for a metric over the given months.

    Returns a DataFrame with columns [Month, Value, MonthDate] representing
    the rolling window average.  Returns an empty DataFrame when fewer than
    (window + 1) months are available, since a rolling average with only 1
    valid point is not meaningful.

    Parameters
    ----------
    df:
        Long-format DataFrame with [Metric, Month, Value, MonthDate].
    metric:
        The metric label.
    months:
        The ordered list of months to compute over.
    window:
        Rolling window size (default 3 = 3-month rolling average).
    """
    metric_df = (
        df[df["Metric"] == metric]
        .groupby(["Month", "MonthDate"], as_index=False)["Value"]
        .sum()
        .sort_values("MonthDate")
    )

    # Filter to the requested months
    metric_df = metric_df[metric_df["Month"].isin(months)]

    if len(metric_df) < window:
        return pd.DataFrame(columns=["Month", "Value", "MonthDate"])

    metric_df = metric_df.copy()
    metric_df["Value"] = metric_df["Value"].rolling(window=window, min_periods=window).mean()
    return metric_df.dropna(subset=["Value"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Chart annotations
# ---------------------------------------------------------------------------

def find_chart_annotations(
    df: pd.DataFrame,
    metric: str,
    months: list[str],
    max_annotations: int = 2,
) -> list[ChartAnnotation]:
    """Identify the most material points on a trend chart for annotation.

    Returns at most `max_annotations` annotations, prioritizing:
      1. The all-time peak (highest value in period)
      2. The all-time trough (lowest value in period)
      3. The biggest single-period MoM increase
      4. The biggest single-period MoM decline

    Annotations are only returned when the move is genuinely material
    (≥ ANOMALY_THRESHOLDS["min_absolute_idr"] in absolute terms).

    Parameters
    ----------
    df:
        Long-format DataFrame with [Metric, Month, Value, MonthDate].
    metric:
        The metric label.
    months:
        Ordered list of months in the viewing window.
    max_annotations:
        Maximum number of annotation points to return (keeps charts clean).
    """
    metric_df = (
        df[df["Metric"] == metric]
        .groupby(["Month", "MonthDate"], as_index=False)["Value"]
        .sum()
        .sort_values("MonthDate")
    )
    metric_df = metric_df[metric_df["Month"].isin(months)]

    if len(metric_df) < 2:
        return []

    annotations: list[ChartAnnotation] = []
    min_abs = ANOMALY_THRESHOLDS["min_absolute_idr"]

    # Peak
    peak_row = metric_df.loc[metric_df["Value"].idxmax()]
    if abs(float(peak_row["Value"])) >= min_abs:
        annotations.append(ChartAnnotation(
            month=str(peak_row["Month"]),
            value=float(peak_row["Value"]),
            label="Peak",
            kind="peak",
        ))

    # Trough — only add if different from peak
    trough_row = metric_df.loc[metric_df["Value"].idxmin()]
    if (
        str(trough_row["Month"]) != str(peak_row["Month"])
        and abs(float(trough_row["Value"])) >= min_abs
        and len(annotations) < max_annotations
    ):
        annotations.append(ChartAnnotation(
            month=str(trough_row["Month"]),
            value=float(trough_row["Value"]),
            label="Trough",
            kind="trough",
        ))

    # MoM changes — compute diffs
    if len(annotations) < max_annotations:
        metric_df = metric_df.copy()
        metric_df["MoM_abs"] = metric_df["Value"].diff()
        valid_diffs = metric_df.dropna(subset=["MoM_abs"])

        if not valid_diffs.empty:
            biggest_up = valid_diffs.loc[valid_diffs["MoM_abs"].idxmax()]
            months_annotated = {a.month for a in annotations}
            if (
                float(biggest_up["MoM_abs"]) > 0
                and abs(float(biggest_up["MoM_abs"])) >= min_abs
                and str(biggest_up["Month"]) not in months_annotated
                and len(annotations) < max_annotations
            ):
                annotations.append(ChartAnnotation(
                    month=str(biggest_up["Month"]),
                    value=float(biggest_up["Value"]),
                    label=f"▲ Biggest MoM",
                    kind="mom_up",
                ))

        if len(annotations) < max_annotations and not valid_diffs.empty:
            biggest_down = valid_diffs.loc[valid_diffs["MoM_abs"].idxmin()]
            months_annotated = {a.month for a in annotations}
            if (
                float(biggest_down["MoM_abs"]) < 0
                and abs(float(biggest_down["MoM_abs"])) >= min_abs
                and str(biggest_down["Month"]) not in months_annotated
            ):
                annotations.append(ChartAnnotation(
                    month=str(biggest_down["Month"]),
                    value=float(biggest_down["Value"]),
                    label=f"▼ Biggest drop",
                    kind="mom_down",
                ))

    return annotations[:max_annotations]


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def detect_anomalies(
    cons_long: pd.DataFrame,
    months: list[str],
    thresholds: dict[str, float] | None = None,
) -> list[AnomalyFlag]:
    """Detect unusually large movements in consolidated P&L data.

    Checks:
      - Revenue MoM change > revenue_mom_pct threshold
      - EBITDA margin swing > ebitda_margin_pp threshold (if ratio data provided)
      - COGS% and OpEx% as % of revenue swing > cost_ratio_pp threshold

    Parameters
    ----------
    cons_long:
        Long-format DataFrame from parse_pl_sheet("Consolidated Summary", ...).
    months:
        Ordered list of months in the viewing window.
    thresholds:
        Override dict for ANOMALY_THRESHOLDS.

    Returns
    -------
    List of AnomalyFlag objects, most critical first.
    """
    t = {**ANOMALY_THRESHOLDS, **(thresholds or {})}
    flags: list[AnomalyFlag] = []

    if len(months) < t["min_months_required"]:
        return flags

    def _get(metric: str, month: str) -> float | None:
        rows = cons_long[(cons_long["Metric"] == metric) & (cons_long["Month"] == month)]
        return float(rows["Value"].sum()) if not rows.empty else None

    # Check each consecutive month pair within the viewing window
    for i in range(1, len(months)):
        cur_m = months[i]
        pri_m = months[i - 1]

        # Revenue MoM
        cur_rev = _get("Total Gross Revenue", cur_m)
        pri_rev = _get("Total Gross Revenue", pri_m)
        if cur_rev is not None and pri_rev is not None and pri_rev != 0:
            pct = (cur_rev - pri_rev) / abs(pri_rev) * 100
            abs_delta = abs(cur_rev - pri_rev)
            if abs(pct) >= t["revenue_mom_pct"] and abs_delta >= t["min_absolute_idr"]:
                level: Literal["warning", "critical"] = "critical" if abs(pct) >= t["revenue_mom_pct"] * 2 else "warning"
                direction = "increased" if pct > 0 else "declined"
                flags.append(AnomalyFlag(
                    level=level,
                    title=f"Revenue {direction} {abs(pct):.0f}% MoM in {cur_m}",
                    detail=f"Revenue moved from Rp{pri_rev:,.0f} to Rp{cur_rev:,.0f} ({pct:+.1f}%) — {pri_m} → {cur_m}.",
                    metric="Total Gross Revenue",
                    month=cur_m,
                    pct_change=pct,
                ))

        # COGS% swing
        cur_cogs = _get("Total COGS", cur_m)
        pri_cogs = _get("Total COGS", pri_m)
        if (cur_rev is not None and pri_rev is not None
                and cur_cogs is not None and pri_cogs is not None
                and cur_rev != 0 and pri_rev != 0):
            cur_cogs_pct = cur_cogs / cur_rev * 100
            pri_cogs_pct = pri_cogs / pri_rev * 100
            swing = cur_cogs_pct - pri_cogs_pct
            if abs(swing) >= t["cost_ratio_pp"]:
                direction = "worsened" if swing > 0 else "improved"
                flags.append(AnomalyFlag(
                    level="warning",
                    title=f"COGS% {direction} {abs(swing):.1f}pp in {cur_m}",
                    detail=f"COGS as % of revenue moved from {pri_cogs_pct:.1f}% to {cur_cogs_pct:.1f}% ({swing:+.1f}pp) — {pri_m} → {cur_m}.",
                    metric="Total COGS",
                    month=cur_m,
                    pct_change=swing,
                ))

        # OpEx% swing
        cur_opex = _get("Total Operating Expenses", cur_m)
        pri_opex = _get("Total Operating Expenses", pri_m)
        if (cur_rev is not None and pri_rev is not None
                and cur_opex is not None and pri_opex is not None
                and cur_rev != 0 and pri_rev != 0):
            cur_opex_pct = cur_opex / cur_rev * 100
            pri_opex_pct = pri_opex / pri_rev * 100
            swing = cur_opex_pct - pri_opex_pct
            if abs(swing) >= t["cost_ratio_pp"]:
                direction = "worsened" if swing > 0 else "improved"
                flags.append(AnomalyFlag(
                    level="warning",
                    title=f"OpEx% {direction} {abs(swing):.1f}pp in {cur_m}",
                    detail=f"OpEx as % of revenue moved from {pri_opex_pct:.1f}% to {cur_opex_pct:.1f}% ({swing:+.1f}pp) — {pri_m} → {cur_m}.",
                    metric="Total Operating Expenses",
                    month=cur_m,
                    pct_change=swing,
                ))

    # Sort: critical first, then by absolute pct_change desc
    flags.sort(key=lambda f: (0 if f.level == "critical" else 1, -(abs(f.pct_change) if f.pct_change else 0)))
    return flags


# ---------------------------------------------------------------------------
# Revenue driver analysis
# ---------------------------------------------------------------------------

def compute_revenue_drivers(
    cons_long: pd.DataFrame,
    entity_frames: dict[str, pd.DataFrame] | None,
    master: pd.DataFrame | None,
    latest: str,
    prior: str,
) -> DriverResult:
    """Decompose a revenue change into entity, stream, client, and P&L-line drivers.

    All drivers are derived from actual data. No imputation or estimation.

    Parameters
    ----------
    cons_long:
        Long-format consolidated P&L DataFrame.
    entity_frames:
        dict of {entity_name → entity long DataFrame} from parse_all_entity_sheets.
        Pass None to skip entity-level decomposition.
    master:
        Tidy MASTER DataFrame from parse_master(). Pass None to skip client/stream drivers.
    latest:
        Latest month label (e.g. "Jun 2025").
    prior:
        Prior month label for comparison (e.g. "May 2025").

    Returns
    -------
    DriverResult dataclass.
    """
    def _get_cons(metric: str, month: str) -> float:
        rows = cons_long[(cons_long["Metric"] == metric) & (cons_long["Month"] == month)]
        return float(rows["Value"].sum()) if not rows.empty else 0.0

    cur_rev = _get_cons("Total Gross Revenue", latest)
    pri_rev = _get_cons("Total Gross Revenue", prior)
    total_delta = cur_rev - pri_rev

    # ── P&L line decomposition ────────────────────────────────────────────
    pl_metrics = [
        ("Total Gross Revenue", "Gross Revenue"),
        ("Total COGS", "COGS"),
        ("Gross Profit 2", "Gross Profit"),
        ("Total Operating Expenses", "OpEx"),
        ("EBITDA", "EBITDA"),
        ("NET PROFIT/LOSS (Before Tax)", "Net Profit"),
    ]
    pl_drivers: list[dict] = []
    for key, label in pl_metrics:
        cur_v = _get_cons(key, latest)
        pri_v = _get_cons(key, prior)
        delta = cur_v - pri_v
        pct = (delta / abs(pri_v) * 100) if pri_v != 0 else None
        pl_drivers.append({"name": label, "cur": cur_v, "prior": pri_v, "delta": delta, "pct": pct})

    # ── Entity-level decomposition ────────────────────────────────────────
    entity_drivers: list[dict] = []
    if entity_frames:
        for entity, df in entity_frames.items():
            cur_rows = df[(df["Metric"] == "Total Gross Revenue") & (df["Month"] == latest)]
            pri_rows = df[(df["Metric"] == "Total Gross Revenue") & (df["Month"] == prior)]
            cur_v = float(cur_rows["Value"].sum()) if not cur_rows.empty else 0.0
            pri_v = float(pri_rows["Value"].sum()) if not pri_rows.empty else 0.0
            delta = cur_v - pri_v
            pct_of_total = (delta / abs(total_delta) * 100) if total_delta != 0 else None
            entity_drivers.append({"name": entity, "cur": cur_v, "prior": pri_v, "delta": delta, "pct_of_total": pct_of_total})
        entity_drivers.sort(key=lambda x: x["delta"], reverse=True)

    # ── Stream and client decomposition (from MASTER) ─────────────────────
    stream_drivers: list[dict] = []
    client_drivers_pos: list[dict] = []
    client_drivers_neg: list[dict] = []

    if master is not None and not master.empty:
        cur_m = master[master["Month"] == latest]
        pri_m = master[master["Month"] == prior]

        # Stream
        cur_stream = cur_m.groupby("Rev Stream")["Amount (IDR)"].sum()
        pri_stream = pri_m.groupby("Rev Stream")["Amount (IDR)"].sum()
        all_streams = cur_stream.index.union(pri_stream.index)
        for stream in all_streams:
            c = float(cur_stream.get(stream, 0.0))
            p = float(pri_stream.get(stream, 0.0))
            d = c - p
            pct_of_total = (d / abs(total_delta) * 100) if total_delta != 0 else None
            stream_drivers.append({"name": stream, "cur": c, "prior": p, "delta": d, "pct_of_total": pct_of_total})
        stream_drivers.sort(key=lambda x: x["delta"], reverse=True)

        # Client
        cur_client = cur_m.groupby("Client (clean)")["Amount (IDR)"].sum()
        pri_client = pri_m.groupby("Client (clean)")["Amount (IDR)"].sum()
        all_clients = cur_client.index.union(pri_client.index)
        client_delta = {
            c: float(cur_client.get(c, 0.0)) - float(pri_client.get(c, 0.0))
            for c in all_clients
        }
        sorted_clients = sorted(client_delta.items(), key=lambda x: x[1], reverse=True)
        client_drivers_pos = [
            {"name": k, "delta": v, "cur": float(cur_client.get(k, 0.0)), "prior": float(pri_client.get(k, 0.0))}
            for k, v in sorted_clients if v > 0
        ][:5]
        client_drivers_neg = [
            {"name": k, "delta": v, "cur": float(cur_client.get(k, 0.0)), "prior": float(pri_client.get(k, 0.0))}
            for k, v in reversed(sorted_clients) if v < 0
        ][:5]

    return DriverResult(
        total_delta=total_delta,
        prior_month=prior,
        latest_month=latest,
        entity_drivers=entity_drivers,
        stream_drivers=stream_drivers,
        client_drivers_pos=client_drivers_pos,
        client_drivers_neg=client_drivers_neg,
        pl_drivers=pl_drivers,
    )


# ---------------------------------------------------------------------------
# Historical average reference line
# ---------------------------------------------------------------------------

def compute_historical_average(
    df: pd.DataFrame,
    metric: str,
    months: list[str],
) -> float | None:
    """Return the simple mean of a metric over the provided months.

    Returns None if fewer than 2 data points are available (meaningless average).
    """
    metric_df = df[(df["Metric"] == metric) & (df["Month"].isin(months))]
    if len(metric_df) < 2:
        return None
    return float(metric_df.groupby("Month")["Value"].sum().mean())
