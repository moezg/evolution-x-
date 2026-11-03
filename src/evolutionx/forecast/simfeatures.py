"""Simulator-generated features for the EXPERIMENTAL hybrid predictor (H1).

For an origin, point-in-time inputs (observed 7 d realized vol, last 24 h return) are mapped to a simulator
configuration: realistic-fundamental profile with world_annual_vol = observed annualized vol, and a fundamental
repricing equal to the observed 24 h return injected at 60 s. The 256-agent market then runs for 900 s and its
endogenous response is summarized. Inputs are quantized and runs cached (seeds 1, 2), so each cell is simulated once.
"""

from __future__ import annotations

import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from ..observatory.market_stats import market_properties
from ..sim.config import Shock, SimConfig
from ..sim.simulation import Simulation

CACHE = Path("artifacts/forecast/simcache.json")
SIM_FEATURES = ("sim_amp", "sim_kurt", "sim_acf_abs", "sim_spread", "sim_liq")
RET_BUCKETS = (-0.04, -0.02, 0.0, 0.02, 0.04)
SEEDS = (1, 2)


def cell(feats: dict[str, float]) -> tuple[float, float] | None:
    lrv, r24 = feats.get("lrv_168"), feats.get("ret_24")
    if lrv is None or r24 is None or not (math.isfinite(lrv) and math.isfinite(r24)):
        return None
    ann = math.exp(lrv) / 100 * math.sqrt(8760 / 168)
    q = round(math.log(min(max(ann, 0.1), 3.0)) / 0.1) * 0.1
    rb = min(RET_BUCKETS, key=lambda b: abs(b - r24))
    return (round(math.exp(q), 4), rb)


def _run(args: tuple[float, float, int]) -> dict[str, float]:
    vol, rb, seed = args
    shocks = [] if rb == 0 else [Shock(type="fundamental_drop", at_s=60, magnitude=-rb)]
    cfg = SimConfig(
        seed=seed,
        duration_s=900,
        scale=0.5,
        world_annual_vol=vol,
        news_impact=0.0,
        shocks=shocks,
        invariant_check_every_s=900,
    )
    sim = Simulation(cfg).run()
    m = market_properties(sim)
    f1 = (m.get("fundamental_ret_std_bps") or {}).get("1m") or float("nan")
    s1 = (m.get("mid_ret_std_bps") or {}).get("1m") or float("nan")

    def num(v: object) -> float:
        return float(v) if isinstance(v, int | float) else float("nan")

    return {
        "sim_amp": s1 / f1 if f1 and f1 > 0 else float("nan"),
        "sim_kurt": num(m.get("excess_kurtosis_1m")),
        "sim_acf_abs": num(m.get("acf_absret_lag1")),
        "sim_spread": (m.get("spread_bps") or {}).get("median") or float("nan"),
        "sim_liq": float(len(sim.liquidation_log)),
    }


def _key(c: tuple[float, float]) -> str:
    return f"{c[0]}|{c[1]}"


def load_cache() -> dict[str, dict[str, float]]:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def ensure(cells: set[tuple[float, float]], workers: int = 4) -> dict[str, dict[str, float]]:
    cache = load_cache()
    todo = sorted(c for c in cells if _key(c) not in cache)
    if todo:
        jobs = [(v, r, s) for v, r in todo for s in SEEDS]
        with ProcessPoolExecutor(workers) as ex:
            res = list(ex.map(_run, jobs))
        for i, c in enumerate(todo):
            runs = res[i * len(SEEDS) : (i + 1) * len(SEEDS)]
            cache[_key(c)] = {k: float(np.nanmean([r[k] for r in runs])) for k in SIM_FEATURES}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True))
    return cache


def features_for(feats: dict[str, float], cache: dict[str, dict[str, float]]) -> dict[str, float]:
    c = cell(feats)
    if c is None or _key(c) not in cache:
        return dict.fromkeys(SIM_FEATURES, float("nan"))
    return cache[_key(c)]


def info() -> dict[str, Any]:
    c = load_cache()
    return {"cells": len(c), "seeds_per_cell": len(SEEDS), "sim_seconds_per_run": 900, "scale": 0.5}
