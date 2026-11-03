"""Market-level empirical properties of a finished simulation (single source for diagnostics and experiments)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..evaluation.stats import autocorr, excess_kurtosis, hill_tail_index


def _series(sim: Any) -> tuple[np.ndarray, list[str]]:
    return np.array(sim.series, dtype=float), sim.series_columns()


def minute_returns(x: np.ndarray, step: int = 60) -> np.ndarray:
    idx = np.arange(step - 1, len(x), step)
    v = x[idx]
    v = v[v > 0]
    return np.diff(np.log(v)) * 1e4  # bps


def signed_flow_per_minute(sim: Any, venue: int | None = 0) -> np.ndarray:
    n = int(sim.cfg.duration_s // 60)
    out = np.zeros(n)
    for tr in sim.exchange.trades:
        if venue is not None and tr.venue != venue:
            continue
        m = tr.t // 60_000
        if m < n:
            out[m] += tr.aggressor_side * tr.qty / 1e4
    return out


def market_properties(sim: Any) -> dict[str, Any]:
    a, cols = _series(sim)
    mid = a[:, cols.index("mid_0")] / 100
    fund = a[:, cols.index("fundamental")]
    spread = a[:, cols.index("spread_bps")]
    vol_cum = a[:, cols.index("volume")] / 1e4
    r1, rf = minute_returns(mid), minute_returns(fund)
    n = min(len(r1), len(rf))
    vol_min = np.diff(np.r_[0.0, vol_cum[np.arange(59, len(vol_cum), 60)]])[1:]
    m = min(len(r1), len(vol_min))
    flow = signed_flow_per_minute(sim)[1:]
    k = min(len(r1), len(flow))
    impact = float(np.polyfit(flow[:k], r1[:k], 1)[0]) if k > 5 and np.std(flow[:k]) > 0 else float("nan")
    dt = np.diff(a[:, 0])
    out = {
        "mid_ret_std_bps": {
            "1m": float(np.std(r1)),
            "5m": float(np.std(minute_returns(mid, 300))),
            "15m": float(np.std(minute_returns(mid, 900))),
        },
        "fundamental_ret_std_bps": {"1m": float(np.std(rf)), "15m": float(np.std(minute_returns(fund, 900)))},
        "corr_mid_fundamental": {
            "1m": float(np.corrcoef(r1[:n], rf[:n])[0, 1]) if n > 5 else float("nan"),
            "15m": _corr(minute_returns(mid, 900), minute_returns(fund, 900)),
        },
        "excess_kurtosis_1m": excess_kurtosis(r1) if len(r1) > 10 else float("nan"),
        "hill_tail_1m": hill_tail_index(r1) if len(r1) > 30 else float("nan"),
        "acf_ret_lag1": autocorr(r1, 1),
        "acf_absret_lag1": autocorr(np.abs(r1), 1),
        "vol_volume_corr": _corr(np.abs(r1[:m]), vol_min[:m]),
        "volume_acf_lag1": autocorr(vol_min, 1),
        "spread_bps": {"median": float(np.nanmedian(spread)), "p95": float(np.nanpercentile(spread, 95))},
        "one_sided_or_empty_book_frac": float(np.mean(~np.isfinite(spread))),
        "signed_flow_acf_lag1": autocorr(flow, 1),
        "impact_bps_per_btc_signed_flow": impact,
        "volume_btc_per_min": float(np.mean(vol_min)) if len(vol_min) else float("nan"),
        "tracking_error_bps": float(np.mean(np.abs(mid / fund - 1)) * 1e4),
        "sampling_ms_unique": sorted({int(x) for x in np.unique(dt)})[:5],
        "trades": len(sim.exchange.trades),
        "liquidations": len(sim.liquidation_log),
    }
    return _clean(out)


def _corr(x: np.ndarray, y: np.ndarray) -> float:
    n = min(len(x), len(y))
    if n < 5 or np.std(x[:n]) == 0 or np.std(y[:n]) == 0:
        return float("nan")
    return float(np.corrcoef(x[:n], y[:n])[0, 1])


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, np.generic):
        return _clean(o.item())
    return o
