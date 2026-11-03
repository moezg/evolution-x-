"""Chronological walk-forward: inner selection on a trailing train window, embargo, outer test window."""

from __future__ import annotations

from typing import Any

import numpy as np

from .engine import CostModel, run_backtest
from .metrics import daily_returns, sharpe

MONTH_MS = 30 * 86_400_000


def windows(
    open_time: np.ndarray, train_months: int, test_months: int, step_months: int, embargo_bars: int
) -> list[dict[str, tuple[int, int]]]:
    t0 = open_time[0]
    out = []
    k = 0
    while True:
        tr_end_t = t0 + (train_months + k * step_months) * MONTH_MS
        te_end_t = tr_end_t + test_months * MONTH_MS
        tr_start = int(np.searchsorted(open_time, tr_end_t - train_months * MONTH_MS))
        tr_end = int(np.searchsorted(open_time, tr_end_t))
        te_start = tr_end + embargo_bars
        te_end = int(np.searchsorted(open_time, te_end_t))
        if te_end <= te_start or te_end > len(open_time) or te_end_t > open_time[-1] + 3_600_000:
            break
        out.append({"train": (tr_start, tr_end), "test": (te_start, te_end)})
        k += 1
    return out


def _slice(d: dict[str, np.ndarray], a: int, b: int) -> dict[str, np.ndarray]:
    return {k: v[a:b] for k, v in d.items()}


def segment_daily(data: dict[str, np.ndarray], dec: np.ndarray, a: int, b: int, cost: CostModel) -> np.ndarray:
    return segment_daily_with_days(data, dec, a, b, cost)[1]


def segment_daily_with_days(
    data: dict[str, np.ndarray], dec: np.ndarray, a: int, b: int, cost: CostModel
) -> tuple[np.ndarray, np.ndarray]:
    res = run_backtest(_slice(data, a, b), dec[a:b], cost)
    return daily_returns(res.equity, res.open_time)


def walk_forward(
    data: dict[str, np.ndarray], decisions_by_param: dict[str, np.ndarray], cost: CostModel, wf: dict[str, int]
) -> dict[str, Any]:
    """decisions_by_param: param-set key -> full-series causal decisions (computed once per param set)."""
    ws = windows(data["open_time"], wf["train_months"], wf["test_months"], wf["step_months"], wf["embargo_bars"])
    oos: list[np.ndarray] = []
    oos_days: list[np.ndarray] = []
    per_window = []
    for w in ws:
        a, b = w["train"]
        scores = {k: sharpe(segment_daily(data, d, a, b, cost)) for k, d in decisions_by_param.items()}
        best = max(sorted(scores), key=lambda k: scores[k])
        ta, tb = w["test"]
        dd, r = segment_daily_with_days(data, decisions_by_param[best], ta, tb, cost)
        oos.append(r)
        oos_days.append(dd)
        per_window.append(
            {
                "train": [int(data["open_time"][a]), int(data["open_time"][b - 1])],
                "test": [int(data["open_time"][ta]), int(data["open_time"][tb - 1])],
                "selected": best,
                "train_sharpe": scores[best],
                "test_sharpe": sharpe(r),
                "test_return": float(np.prod(1 + r) - 1),
            }
        )
    allr = np.concatenate(oos) if oos else np.array([])
    alld = np.concatenate(oos_days) if oos_days else np.array([], dtype=np.int64)
    return {
        "oos_days": alld,
        "n_windows": len(ws),
        "n_trials": len(ws) * len(decisions_by_param),
        "oos_daily": allr,
        "oos_sharpe": sharpe(allr),
        "per_window": per_window,
    }
