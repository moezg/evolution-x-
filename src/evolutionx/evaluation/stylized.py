"""Stylized facts of returns: the realism yardstick for simulated markets.

Compares simulated statistics with reference statistics computed from real
historical data (if a dataset is available locally) or, failing that, with
broad literature ranges (Cont 2001, "Empirical properties of asset returns").
Literature ranges are explicitly labelled as uncalibrated.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .stats import autocorr, excess_kurtosis, hill_tail_index

# Broad literature bands for intraday (1-minute) crypto/asset returns. Uncalibrated.
LITERATURE_BANDS: dict[str, tuple[float, float]] = {
    "excess_kurtosis": (1.0, 50.0),  # fat tails
    "acf_ret_lag1": (-0.15, 0.10),  # near-zero linear autocorrelation (small negative from bid-ask bounce)
    "acf_absret_lag1": (0.05, 0.6),  # volatility clustering
    "acf_absret_lag5": (0.02, 0.5),
    "hill_tail_index": (1.5, 6.0),
    "vol_volume_corr": (0.1, 0.9),
}


def facts_from_series(prices: np.ndarray, volumes: np.ndarray | None = None) -> dict[str, float]:
    p = np.asarray(prices, dtype=float)
    p = p[p > 0]
    if len(p) < 20:
        return {}
    r = np.diff(np.log(p))
    ar = np.abs(r)
    out = {
        "n_returns": float(len(r)),
        "ret_std_bps": float(r.std() * 1e4),
        "excess_kurtosis": excess_kurtosis(r),
        "acf_ret_lag1": autocorr(r, 1),
        "acf_absret_lag1": autocorr(ar, 1),
        "acf_absret_lag5": autocorr(ar, 5),
        "hill_tail_index": hill_tail_index(r),
    }
    if volumes is not None and len(volumes) == len(p):
        v = np.asarray(volumes, dtype=float)[1:]
        out["vol_volume_corr"] = float(np.corrcoef(ar, v)[0, 1]) if v.std() > 0 and ar.std() > 0 else float("nan")
    return out


def realism_score(facts: dict[str, float], bands: dict[str, tuple[float, float]] | None = None) -> dict[str, Any]:
    """Fraction of facts inside reference bands plus a soft distance (lower is better)."""
    bands = bands or LITERATURE_BANDS
    detail = {}
    inside = 0
    dist = 0.0
    n = 0
    for k, (lo, hi) in bands.items():
        v = facts.get(k)
        if v is None or not math.isfinite(v):
            detail[k] = {"value": None, "band": [lo, hi], "inside": False}
            n += 1
            dist += 1.0
            continue
        ok = lo <= v <= hi
        width = max(hi - lo, 1e-9)
        d = 0.0 if ok else min(1.0, (lo - v if v < lo else v - hi) / width)
        detail[k] = {"value": v, "band": [lo, hi], "inside": ok}
        inside += ok
        dist += d
        n += 1
    return {"score": inside / n if n else 0.0, "distance": dist / n if n else 1.0, "detail": detail}


def bands_from_reference(
    ref_facts: list[dict[str, float]], lo_q: float = 0.05, hi_q: float = 0.95
) -> dict[str, tuple[float, float]]:
    """Empirical bands from historical reference windows: the [lo_q, hi_q] quantile range of each fact."""
    bands = {}
    for k in LITERATURE_BANDS:
        vals = [f[k] for f in ref_facts if k in f and math.isfinite(f[k])]
        if len(vals) >= 10:
            bands[k] = (float(np.quantile(vals, lo_q)), float(np.quantile(vals, hi_q)))
    return bands
