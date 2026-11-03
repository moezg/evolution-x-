"""Adversarial falsification battery (role E3) on DEVELOPMENT data only (2020-2023, free exploration).

Hard failures (candidate rejected): look-ahead (truncation probe), invalid decisions.
Soft weaknesses (recorded, they shape the next step): cost fragility, delay fragility, parameter instability,
regime dependence, edge not distinguishable from a block-shuffled placebo.
"""

from __future__ import annotations

import math
import types
from typing import Any

import numpy as np

from ..backtest.engine import CostModel, InvalidDecisions, run_backtest
from ..backtest.interface import decisions_for, load_module_strategy
from ..backtest.metrics import daily_returns, sharpe
from ..data.datasets import load_split, protocol


def load_module(source: str, name: str = "candidate") -> types.ModuleType:
    """Only for sources that already passed the lab's static contract check (no imports beyond math/numpy)."""
    mod = types.ModuleType(name)
    exec(compile(source, name, "exec"), mod.__dict__)  # noqa: S102  # nosec B102 - static-checked template output
    return mod


def _sharpe(data: dict[str, np.ndarray], dec: np.ndarray, mult: float = 1.0) -> float:
    base = CostModel.from_protocol(protocol(), "BTCUSDT")
    cost = CostModel(**{**base.__dict__, "cost_multiplier": mult})
    res = run_backtest(data, dec, cost)
    _, r = daily_returns(res.equity, res.open_time)
    return float(sharpe(r))


def _placebo(data: dict[str, np.ndarray], seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    c = data["close"]
    lr = np.diff(np.log(c))
    n = len(lr) // 24 * 24
    blocks = lr[:n].reshape(-1, 24)[rng.permutation(n // 24)].ravel()
    close = c[0] * np.exp(np.r_[0.0, np.cumsum(blocks)])
    m = len(close)
    out = {k: v[:m].copy() for k, v in data.items()}
    out["close"] = close
    out["open"] = np.r_[close[0], close[:-1]]
    out["high"] = np.maximum(out["open"], close) * 1.0005
    out["low"] = np.minimum(out["open"], close) * 0.9995
    return out


def battery(source: str, params: dict[str, float], n_placebo: int = 8, years: int = 4) -> dict[str, Any]:
    full = load_split("BTCUSDT", "development")
    n = min(len(full["close"]), years * 8760)
    data = {k: v[-n:] for k, v in full.items()}
    mod = load_module(source)
    strat = load_module_strategy(mod, params)
    tests: dict[str, Any] = {}
    try:
        dec = decisions_for(strat, data)
        if not np.all(np.isfinite(dec)) or np.max(np.abs(dec)) > 1 + 1e-9:
            raise InvalidDecisions("decisions outside [-1, 1] or non-finite")
        tests["valid_decisions"] = {"ok": True, "hard_failure": False}
    except Exception as e:  # noqa: BLE001 - any failure here is a hard rejection of the candidate
        return {
            "tests": {"valid_decisions": {"ok": False, "hard_failure": True, "error": str(e)[:300]}},
            "verdict": "rejected",
        }

    rng = np.random.default_rng(0)
    probe_t = sorted(rng.integers(1000, n - 1, 25).tolist())
    mism = [
        int(t)
        for t in probe_t
        if abs(load_module_strategy(mod, params).decide(_view({k: v[: t + 1] for k, v in data.items()}, t)) - dec[t])
        > 1e-12
    ]
    tests["causality_truncation_probe"] = {
        "ok": not mism,
        "hard_failure": bool(mism),
        "mismatched_bars": mism[:10],
        "probes": len(probe_t),
    }

    s1, s2, s3 = (_sharpe(data, dec, m) for m in (1.0, 2.0, 3.0))
    tests["cost_stress"] = {
        "sharpe_1x": s1,
        "sharpe_2x": s2,
        "sharpe_3x": s3,
        "ok": bool(not (s1 > 0 >= s2)),
        "hard_failure": False,
    }
    sd = _sharpe(data, np.r_[0.0, dec[:-1]])
    tests["one_bar_delay"] = {"sharpe": sd, "ok": bool(not (s1 > 0 and sd < 0.5 * s1)), "hard_failure": False}

    neigh = {}
    for k, v in params.items():
        for f in (0.5, 2.0):
            p2 = {**params, k: v * f}
            neigh[f"{k}x{f}"] = _sharpe(data, decisions_for(load_module_strategy(mod, p2), data))
    signs = {np.sign(x) for x in [s1, *neigh.values()] if abs(x) > 1e-9}
    tests["parameter_neighbourhood"] = {"sharpe": neigh, "ok": len(signs) <= 1, "hard_failure": False}

    lr = np.r_[0.0, np.diff(np.log(data["close"]))]
    vol = np.array([np.std(lr[max(0, i - 720) : i + 1]) for i in range(0, n, 24)]).repeat(24)[:n]
    hi = vol > np.median(vol)
    reg = {}
    for name, mask in (("high_vol", hi), ("low_vol", ~hi)):
        d2 = np.where(mask, dec, 0.0)
        reg[name] = _sharpe(data, d2)
    tests["regime_split"] = {
        "sharpe": reg,
        "ok": bool(np.sign(reg["high_vol"]) == np.sign(reg["low_vol"])),
        "hard_failure": False,
    }

    plac = []
    for s in range(n_placebo):
        pd_ = _placebo(data, s)
        plac.append(_sharpe(pd_, decisions_for(load_module_strategy(mod, params), pd_)))
    q90 = float(np.quantile(plac, 0.9)) if plac else math.nan
    tests["block_shuffle_placebo"] = {
        "placebo_sharpes": plac,
        "q90": q90,
        "candidate": s1,
        "ok": bool(s1 > q90),
        "hard_failure": False,
    }

    bh = _sharpe(data, np.full(n, 0.5))
    tests["exposure"] = {
        "mean_abs_exposure_x_engine_max": float(np.mean(np.abs(dec))),
        "max_abs": float(np.max(np.abs(dec))),
        "buy_and_hold_1x_sharpe_same_period": bh,
        "ok": True,
        "hard_failure": False,
    }
    hard = [k for k, v in tests.items() if v.get("hard_failure")]
    soft = [k for k, v in tests.items() if not v.get("ok") and not v.get("hard_failure")]
    return {
        "period": "development 2020-2023 (free exploration)",
        "tests": tests,
        "hard_failures": hard,
        "weaknesses": soft,
        "verdict": "rejected" if hard else ("fragile" if soft else "survived"),
    }


def _view(data: dict[str, np.ndarray], t: int):  # noqa: ANN202
    from ..backtest.interface import BarView

    return BarView(data, t)
