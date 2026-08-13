"""Anomaly detection thresholds — centralized for easy configuration.

All thresholds are business-safe defaults derived from FP&A best practices.
Change these values here only; never hardcode thresholds in tab or chart code.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Anomaly detection thresholds
# ---------------------------------------------------------------------------

ANOMALY_THRESHOLDS: dict[str, float] = {
    # Flag if absolute MoM revenue change exceeds this percentage
    "revenue_mom_pct": 20.0,

    # Flag if EBITDA margin swings by more than this many percentage points MoM
    "ebitda_margin_pp": 10.0,

    # Flag if COGS% or OpEx% of revenue swings by more than this many pp MoM
    "cost_ratio_pp": 8.0,

    # Flag if a top-5 client drops by more than this percentage MoM
    "client_disappearance_pct": 50.0,

    # Minimum absolute IDR value to qualify a movement as material
    # (prevents flagging noise on near-zero lines)
    "min_absolute_idr": 10_000_000,  # Rp10M

    # Minimum number of months required before anomaly detection is meaningful
    "min_months_required": 2,
}
