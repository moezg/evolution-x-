"""Run-level metrics extracted from a finished (or live) simulation."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .stats import max_drawdown
from .stylized import facts_from_series, realism_score


def minute_bars(sim) -> tuple[np.ndarray, np.ndarray]:  # noqa: ANN001
    """1-minute close mid (venue 0) and volume from the per-second public series."""
    s = sim.series
    if not s:
        return np.array([]), np.array([])
    mids = np.array([r[1] for r in s], dtype=float) / 100
    vol = np.array([r[-2] for r in s], dtype=float) / 1e4
    idx = np.arange(59, len(s), 60)
    closes = mids[idx]
    cumv = vol[idx]
    v = np.diff(np.concatenate([[0.0], cumv]))
    return closes, v


def run_metrics(sim, shock_at_s: int | None = None, window_s: int = 300) -> dict[str, Any]:  # noqa: ANN001
    s = sim.series
    mids = np.array([r[1] for r in s], dtype=float) / 100
    spreads = np.array([r[1 + sim.cfg.n_venues] for r in s], dtype=float)
    depth = np.array([r[2 + sim.cfg.n_venues] for r in s], dtype=float) / 1e4
    closes, vols = minute_bars(sim)
    facts = facts_from_series(closes, vols)
    out: dict[str, Any] = {
        "final_mid": float(mids[-1]) if len(mids) else float("nan"),
        "return_pct": float((mids[-1] / mids[0] - 1) * 100) if len(mids) else float("nan"),
        "max_drawdown_pct": max_drawdown(mids) * 100 if len(mids) else float("nan"),
        "spread_bps_median": float(np.nanmedian(spreads)) if len(spreads) else float("nan"),
        "spread_bps_p95": float(np.nanpercentile(spreads, 95)) if np.isfinite(spreads).any() else float("nan"),
        "depth_btc_median": float(np.median(depth)) if len(depth) else float("nan"),
        "volume_btc": float(sum(t.qty for t in sim.exchange.trades) / 1e4),
        "n_trades": len(sim.exchange.trades),
        "liquidations": len(sim.liquidation_log),
        "influence_events": len(sim.influence_events),
        "circuit_breakers": sum(1 for e in sim.exchange.events if e.type == "circuit_breaker"),
        "tracking_error_bps": float(np.mean(np.abs(mids / np.array([r[4 + sim.cfg.n_venues] for r in s]) - 1)) * 1e4),
        "cross_venue_gap_bps": float(
            np.mean(np.abs(np.array([r[2] for r in s]) / np.array([r[1] for r in s]) - 1)) * 1e4
        )
        if sim.cfg.n_venues > 1
        else 0.0,
        "facts": facts,
        "realism": realism_score(facts),
        "events_per_s": sim.events_processed / max(sim.wall_time_s, 1e-9),
        "wall_time_s": sim.wall_time_s,
    }
    if shock_at_s is not None and len(mids) > shock_at_s:
        pre = mids[max(0, shock_at_s - 1)]
        win = mids[shock_at_s : shock_at_s + window_s]
        out["shock"] = {
            "pre_price": float(pre),
            "min_after_pct": float((win.min() / pre - 1) * 100),
            "max_after_pct": float((win.max() / pre - 1) * 100),
            "ret_window_pct": float((win[-1] / pre - 1) * 100),
            "ret_end_pct": float((mids[-1] / pre - 1) * 100),
            "realized_vol_bps": float(np.std(np.diff(np.log(win))) * 1e4) if len(win) > 2 else float("nan"),
            "spread_bps_window": float(np.nanmedian(spreads[shock_at_s : shock_at_s + window_s])),
            "liquidations_window": sum(
                1 for x in sim.liquidation_log if shock_at_s * 1000 <= x["t"] < (shock_at_s + window_s) * 1000
            ),
        }
    out["by_kind"] = performance_by_kind(sim)
    return _finite(out)


def performance_by_kind(sim) -> dict[str, dict[str, float]]:  # noqa: ANN001
    marks = sim.exchange.marks()
    res: dict[str, list[float]] = {}
    dds: dict[str, list[float]] = {}
    for a in sim.agents:
        eq = sim.clearing.accounts[a.id].equity(marks) / 1e6
        res.setdefault(a.kind, []).append(eq / a.capital_usd - 1)
        dds.setdefault(a.kind, []).append(a.max_drawdown)
    return {
        k: {
            "mean_return_pct": float(np.mean(v) * 100),
            "median_return_pct": float(np.median(v) * 100),
            "cvar5_return_pct": float(np.mean(sorted(v)[: max(1, len(v) // 20)]) * 100),
            "mean_max_dd_pct": float(np.mean(dds[k]) * 100),
            "n": len(v),
        }
        for k, v in res.items()
    }


def gini(x: list[float]) -> float:
    a = np.sort(np.maximum(np.asarray(x, dtype=float), 0))
    if a.sum() == 0:
        return 0.0
    n = len(a)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(a) / (n * a.sum()))


def _finite(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_finite(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, np.floating | np.integer):
        return _finite(o.item())
    return o
