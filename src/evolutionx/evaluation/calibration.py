"""Simulator calibration as a separate experiment (question A: realism on data not used for calibration).

Train targets: stylized facts of 60-minute windows from the historical TRAIN days only (1m BTCUSDT).
Search: random search over population size scales and latent volatility, scored ONLY against train targets.
Evaluation: default vs calibrated configuration on VALIDATION and HELD-OUT days (never used in the search), with
seed-level bootstrap CIs. Unfavourable results are kept as they are.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from ..sim.config import SimConfig
from ..sim.simulation import Simulation
from .stats import mean_ci
from .stylized import facts_from_series

OUT = Path("artifacts/calibration")
FACTS = [
    "ret_std_bps",
    "ret5_std_bps",
    "ret15_std_bps",
    "excess_kurtosis",
    "acf_ret_lag1",
    "acf_absret_lag1",
    "vol_volume_corr",
]


def multi_facts(close: np.ndarray, vol: np.ndarray) -> dict[str, float]:
    f = facts_from_series(close, vol)
    if not f:
        return {}
    for h in (5, 15):
        c = close[::h]
        r = np.diff(np.log(c))
        f[f"ret{h}_std_bps"] = float(r.std() * 1e4) if len(r) > 2 else float("nan")
    return f


def window_targets(split: str) -> list[dict[str, float]]:
    from ..data.historical import load_split

    out = []
    for day in load_split(split):
        for i in range(0, len(day) - 60 + 1, 60):
            w = day[i : i + 60]
            f = multi_facts(w[:, 4], w[:, 5])
            if f:
                out.append(f)
    return out


def target_stats(ws: list[dict[str, float]]) -> dict[str, tuple[float, float]]:
    out = {}
    for k in FACTS:
        v = np.array([w[k] for w in ws if math.isfinite(w.get(k, float("nan")))])
        q1, q3 = np.quantile(v, [0.25, 0.75])
        out[k] = (float(np.median(v)), float(max(q3 - q1, 1e-9)))
    return out


def distance(f: dict[str, float], tgt: dict[str, tuple[float, float]]) -> float:
    ds = [abs(f[k] - m) / s for k, (m, s) in tgt.items() if k in f and math.isfinite(f[k])]
    return float(np.mean(ds)) if ds else float("nan")


def _sim(args: tuple[dict[str, Any], int, int]) -> dict[str, float]:
    knobs, seed, dur = args
    cfg = SimConfig(
        seed=seed,
        duration_s=dur,
        world_annual_vol=knobs["world_annual_vol"],
        size_scale={k: knobs[k] for k in knobs if k != "world_annual_vol"},
        invariant_check_every_s=600,
    )
    s = Simulation(cfg).run()
    s.exchange.check_invariants()
    mids = np.array([r[1] for r in s.series], float) / 100
    vols = np.array([r[-2] for r in s.series], float) / 1e4
    idx = np.arange(59, len(mids), 60)
    return multi_facts(mids[idx], np.diff(np.r_[0, vols[idx]]))


DEFAULT = {
    "world_annual_vol": 0.6,
    "noise": 1.0,
    "momentum": 1.0,
    "leveraged": 1.0,
    "adaptive": 1.0,
    "market_maker": 1.0,
    "value": 1.0,
    "whale": 1.0,
    "execution": 1.0,
    "news": 1.0,
}


def sample(rng: random.Random) -> dict[str, float]:
    k = {"world_annual_vol": rng.uniform(0.3, 0.8)}
    for kind, (lo, hi) in {
        "noise": (0.2, 2.0),
        "momentum": (0.1, 1.2),
        "leveraged": (0.1, 1.2),
        "adaptive": (0.1, 1.2),
        "market_maker": (0.5, 5.0),
        "value": (0.2, 1.5),
        "whale": (0.1, 1.0),
        "execution": (0.1, 1.0),
        "news": (0.1, 1.2),
    }.items():
        k[kind] = math.exp(rng.uniform(math.log(lo), math.log(hi)))
    return k


def run_calibration(
    n_configs: int = 16,
    search_seeds: int = 2,
    eval_seeds: int = 6,
    duration_s: int = 3600,
    workers: int = 4,
    seed: int = 11,
) -> dict[str, Any]:
    train, val, held = window_targets("train"), window_targets("validation"), window_targets("heldout")
    t_tr, t_va, t_he = target_stats(train), target_stats(val), target_stats(held)
    rng = random.Random(seed)
    configs = [DEFAULT] + [sample(rng) for _ in range(n_configs - 1)]
    jobs = [(c, 5000 + s, duration_s) for c in configs for s in range(search_seeds)]
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(_sim, jobs))
    search = []
    for i, c in enumerate(configs):
        fs = res[i * search_seeds : (i + 1) * search_seeds]
        search.append(
            {
                "knobs": c,
                "train_distance": float(np.nanmean([distance(f, t_tr) for f in fs])),
                "facts_mean": {k: float(np.nanmean([f.get(k, np.nan) for f in fs])) for k in FACTS},
            }
        )
    best = min(search[1:], key=lambda r: r["train_distance"])
    # evaluation on seeds and target days never used in the search
    ev_jobs = [(c, 9000 + s, duration_s) for c in (DEFAULT, best["knobs"]) for s in range(eval_seeds)]
    with ProcessPoolExecutor(workers) as ex:
        ev = list(ex.map(_sim, ev_jobs))
    d_runs, b_runs = ev[:eval_seeds], ev[eval_seeds:]

    def summary(runs: list[dict[str, float]]) -> dict[str, Any]:
        return {
            "train_distance": mean_ci([distance(f, t_tr) for f in runs]),
            "validation_distance": mean_ci([distance(f, t_va) for f in runs]),
            "heldout_distance": mean_ci([distance(f, t_he) for f in runs]),
            "facts": {k: mean_ci([f.get(k, float("nan")) for f in runs]) for k in FACTS},
        }

    # sensitivity: log-linear regression of 1-min vol on log knobs across the search runs
    x = np.array([[math.log(c[k]) for k in DEFAULT] for c in configs for _ in range(search_seeds)])
    y = np.array([math.log(max(f.get("ret_std_bps", np.nan), 1e-9)) for f in res])
    ok = np.isfinite(y)
    coef = np.linalg.lstsq(np.c_[np.ones(ok.sum()), x[ok]], y[ok], rcond=None)[0][1:]
    report = {
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "question": "A: does calibration on TRAIN days improve fit on VALIDATION/HELD-OUT days?",
        "targets": {
            "train": {k: v for k, v in t_tr.items()},
            "validation": t_va,
            "heldout": t_he,
            "windows": {"train": len(train), "validation": len(val), "heldout": len(held)},
        },
        "search": {
            "n_configs": n_configs,
            "seeds_per_config": search_seeds,
            "duration_s": duration_s,
            "results": search,
        },
        "selected_knobs": best["knobs"],
        "evaluation": {
            "seeds": list(range(9000, 9000 + eval_seeds)),
            "default": summary(d_runs),
            "calibrated": summary(b_runs),
        },
        "sensitivity_dlog_vol_dlog_knob": dict(zip(DEFAULT, map(float, coef), strict=True)),
        "caveats": [
            "Distance = mean |fact - median| / IQR over 60-min windows; facts from 60 returns are noisy.",
            "Only 5 train / 2 validation / 2 held-out days of 1m data; conclusions are limited to those days.",
            "Matching return statistics does not validate order-book microstructure (no historical L2 data).",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(report, indent=2, default=float))
    return report
