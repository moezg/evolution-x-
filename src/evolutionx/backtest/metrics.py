"""Performance metrics for backtests: gross/net, risk, turnover, exposure, holding, uncertainty."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .engine import BacktestResult

DAY_MS = 86_400_000


def daily_returns(equity: np.ndarray, open_time: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Close-to-close UTC daily returns from hourly equity (last bar of each day)."""
    day = open_time // DAY_MS
    last = np.r_[np.where(np.diff(day) != 0)[0], len(day) - 1]
    e = equity[last]
    r = e[1:] / e[:-1] - 1
    return day[last][1:], r


def sharpe(r: np.ndarray, periods: float = 365.0) -> float:
    r = np.asarray(r, dtype=float)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(periods))


def max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    return float(np.max(1 - equity / peak)) if len(equity) else 0.0


def summarize(res: BacktestResult, start: int = 0) -> dict[str, Any]:
    eq = res.equity[start:]
    t = res.open_time[start:]
    gross_eq = eq + res.cum_cost[start:] - (res.cum_cost[start - 1] if start > 0 else 0.0)
    _, r = daily_returns(eq, t)
    _, rg = daily_returns(gross_eq, t)
    pos = res.position[start:]
    years = max((t[-1] - t[0]) / (365 * DAY_MS), 1e-9)
    notional = np.abs(pos) * 1.0
    expo = np.mean(pos != 0) if len(pos) else 0.0
    # holding duration: average run length of non-zero same-sign position
    sgn = np.sign(pos)
    changes = np.flatnonzero(np.diff(sgn) != 0)
    runs = np.diff(np.r_[0, changes + 1, len(sgn)])
    run_signs = sgn[np.r_[0, changes + 1]]
    held = runs[run_signs != 0]
    cvar = float(np.mean(np.sort(r)[: max(1, len(r) // 20)])) if len(r) else 0.0
    _ = notional
    return {
        "net_total_return": float(eq[-1] / eq[0] - 1),
        "gross_total_return": float(gross_eq[-1] / gross_eq[0] - 1),
        "net_sharpe": sharpe(r),
        "gross_sharpe": sharpe(rg),
        "ann_return": float((eq[-1] / eq[0]) ** (1 / years) - 1) if eq[-1] > 0 else -1.0,
        "ann_vol": float(np.std(r, ddof=1) * math.sqrt(365)) if len(r) > 1 else 0.0,
        "max_drawdown": max_drawdown(eq),
        "cvar5_daily": cvar,
        "turnover_per_year": float(res.traded_notional / np.mean(eq) / years),
        "exposure_frac": float(expo),
        "avg_holding_bars": float(np.mean(held)) if len(held) else 0.0,
        "n_fills": res.n_fills,
        "n_position_changes": int(len(changes)),
        "n_liquidations": res.n_liquidations,
        "costs": {k: float(v) for k, v in res.costs.items()},
        "unfilled_qty": float(res.unfilled_qty),
        "days": int(len(r)),
    }
