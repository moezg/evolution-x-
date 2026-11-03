"""Volatility diagnosis (pre-registered in evals/frozen/volatility_diagnosis_v1.json).

One factor changed at a time from the default population, paired seeds, minimal runs.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from ..evaluation.calibration import target_stats, window_targets
from ..sim.config import SimConfig
from ..sim.simulation import Simulation
from .market_stats import market_properties

OUT = Path("artifacts/observatory")
CONDITIONS: dict[str, dict[str, Any]] = {
    "default": {},
    "fundamental_realistic": {"world_annual_vol": 0.33, "news_impact": 0.0},
    "fundamental_frozen": {"world_annual_vol": 0.0, "news_impact": 0.0, "news_rate_per_hour": 0.0},
    "no_leverage": {"population_overrides": {"leveraged": 0}},
    "no_social": {"social_enabled": False, "imitation_enabled": False},
}

# amendment_v2 of the protocol (positive-feedback amplification), base R = realistic fundamental
_R: dict[str, Any] = {"world_annual_vol": 0.33, "news_impact": 0.0}
AMPLIFICATION_V2: dict[str, dict[str, Any]] = {
    "R": _R,
    "R_low_belief": {**_R, "param_overrides": {"value": {"info_noise_bps": 2.0}, "whale": {"info_noise_bps": 1.0}}},
    "R_no_momentum": {**_R, "population_overrides": {"momentum": 0}},
    "R_no_leverage": {**_R, "population_overrides": {"leveraged": 0}},
    "R_no_social": {**_R, "social_enabled": False, "imitation_enabled": False},
    "R_no_noise": {**_R, "population_overrides": {"noise": 0}},
}


def run_amplification_v2(workers: int = 4) -> dict[str, Any]:
    """Re-runs the amendment_v2 study exactly as recorded in volatility_v2_amplification.json."""
    return run(list(AMPLIFICATION_V2), extra=AMPLIFICATION_V2, tag="v2_amplification", workers=workers)


def _run(args: tuple[str, dict[str, Any], int, int]) -> dict[str, Any]:
    name, over, seed, dur = args
    t0 = time.perf_counter()
    sim = Simulation(SimConfig(seed=seed, duration_s=dur, invariant_check_every_s=600, **over)).run()
    sim.exchange.check_invariants()
    p = market_properties(sim)
    p.update(condition=name, seed=seed, wall_s=round(time.perf_counter() - t0, 2), fingerprint=sim.fingerprint()[:16])
    return p


def run(
    conditions: list[str] | None = None,
    seeds: tuple[int, ...] = (501, 502, 503),
    duration_s: int = 3600,
    workers: int = 4,
    extra: dict[str, dict[str, Any]] | None = None,
    tag: str = "v1",
) -> dict[str, Any]:
    conds = {**CONDITIONS, **(extra or {})}
    names = conditions or list(CONDITIONS)
    jobs = [(c, conds[c], s, duration_s) for c in names for s in seeds]
    with ProcessPoolExecutor(workers) as ex:
        rows = list(ex.map(_run, jobs))
    tr = target_stats(window_targets("train"))
    summary = {}
    for c in names:
        rs = [r for r in rows if r["condition"] == c]

        def m(path: str, rs: list[dict[str, Any]] = rs) -> dict[str, float]:
            vals = []
            for r in rs:
                cur: Any = r
                for k in path.split("."):
                    cur = cur.get(k) if isinstance(cur, dict) else None
                if isinstance(cur, int | float):
                    vals.append(float(cur))
            return {
                "mean": float(np.mean(vals)) if vals else float("nan"),
                "min": float(np.min(vals)) if vals else float("nan"),
                "max": float(np.max(vals)) if vals else float("nan"),
            }

        summary[c] = {
            k: m(k)
            for k in (
                "mid_ret_std_bps.1m",
                "mid_ret_std_bps.15m",
                "fundamental_ret_std_bps.1m",
                "corr_mid_fundamental.1m",
                "corr_mid_fundamental.15m",
                "excess_kurtosis_1m",
                "acf_ret_lag1",
                "acf_absret_lag1",
                "vol_volume_corr",
                "spread_bps.median",
                "one_sided_or_empty_book_frac",
                "signed_flow_acf_lag1",
                "impact_bps_per_btc_signed_flow",
                "volume_btc_per_min",
                "tracking_error_bps",
            )
        }
    rep = {
        "protocol": "volatility-diagnosis-v1",
        "tag": tag,
        "created_utc": dt.datetime.now(dt.UTC).isoformat(),
        "seeds": list(seeds),
        "duration_s": duration_s,
        "conditions": {c: conds[c] for c in names},
        "historical_train_targets": {k: {"median": v[0], "iqr": v[1]} for k, v in tr.items()},
        "summary": summary,
        "runs": rows,
        "label": "SYNTHETIC runs vs HISTORICAL TRAIN-day targets",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"volatility_{tag}.json").write_text(json.dumps(rep, indent=2, default=float))
    return rep
