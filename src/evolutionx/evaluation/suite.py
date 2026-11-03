"""`make eval`: realism vs historical data, simple baselines and ablations, with uncertainty.

Question answered: does the full agent-based model reproduce historical
stylized facts better than (a) a Gaussian random walk, (b) a zero-intelligence
market, and (c) ablated versions of itself? Uses TRAIN windows for reference
bands, VALIDATION windows for model comparison, HELD-OUT windows only for the
final report on the full model.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from ..sim.config import SimConfig
from ..sim.simulation import Simulation
from .metrics import minute_bars, run_metrics
from .reference import historical_bands, window_facts
from .stats import mean_ci
from .stylized import LITERATURE_BANDS, facts_from_series, realism_score

EVAL_DIR = Path("artifacts/eval")
FACTS = list(LITERATURE_BANDS)

ZERO = {k: 0 for k in ("momentum", "value", "arbitrage", "execution", "whale", "leveraged", "news", "adaptive")}
MODELS: dict[str, dict[str, Any]] = {
    "full_model": {},
    "zero_intelligence": {"population_overrides": ZERO},
    "ablation_no_social": {"social_enabled": False, "imitation_enabled": False},
    "ablation_no_leverage": {"population_overrides": {"leveraged": 0}},
    "ablation_no_fundamental_traders": {"population_overrides": {"value": 0, "whale": 0}},
}


def _run(args: tuple[str, int, int]) -> dict[str, Any]:
    name, seed, duration = args
    sim = Simulation(SimConfig(seed=seed, duration_s=duration, **MODELS[name])).run()
    closes, vols = minute_bars(sim)
    m = run_metrics(sim)
    return {
        "model": name,
        "seed": seed,
        "facts": facts_from_series(closes, vols),
        "max_drawdown_pct": m["max_drawdown_pct"],
        "spread_bps_median": m["spread_bps_median"],
        "liquidations": m["liquidations"],
        "events_per_s": m["events_per_s"],
        "n_agents": len(sim.agents),
        "fingerprint": sim.fingerprint(),
    }


def _gbm(seed: int, n: int, sigma_bps: float) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    p = 60_000 * np.exp(np.cumsum(rng.normal(0, sigma_bps / 1e4, n)))
    vols = rng.lognormal(0, 0.5, n)
    return {"model": "gbm_baseline", "seed": seed, "facts": facts_from_series(p, vols)}


def _fact_distance(f: dict[str, float], ref_mean: dict[str, float], ref_std: dict[str, float]) -> float:
    ds = [
        abs(f[k] - ref_mean[k]) / ref_std[k]
        for k in FACTS
        if k in f and k in ref_mean and math.isfinite(f[k]) and ref_std[k] > 0
    ]
    return float(np.mean(ds)) if ds else float("nan")


def run_eval(seeds: int = 4, duration_s: int = 3600, workers: int = 4) -> dict[str, Any]:
    bands = historical_bands()
    ref_name = "historical TRAIN split (Binance BTCUSDT 1m)" if bands else "literature bands (uncalibrated)"
    train, val, held = window_facts("train"), window_facts("validation"), window_facts("heldout")

    def stats(ws: list[dict[str, float]]) -> tuple[dict[str, float], dict[str, float]]:
        mean = {k: float(np.mean([w[k] for w in ws if math.isfinite(w.get(k, float("nan")))])) for k in FACTS}
        std = {k: float(np.std([w[k] for w in ws if math.isfinite(w.get(k, float("nan")))])) for k in FACTS}
        return mean, std

    have_hist = bool(train and val and held)
    tr_std = stats(train)[1] if have_hist else {}
    val_mean = stats(val)[0] if have_hist else {}
    held_mean = stats(held)[0] if have_hist else {}
    jobs = [(m, 3000 + i, duration_s) for m in MODELS for i in range(seeds)]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        runs = list(ex.map(_run, jobs))
    hist_sigma = float(np.mean([w["ret_std_bps"] for w in train])) if train else 5.0
    runs += [_gbm(3000 + i, duration_s // 60, hist_sigma) for i in range(seeds)]
    results: dict[str, Any] = {}
    for name in [*MODELS, "gbm_baseline"]:
        rs = [r for r in runs if r["model"] == name]
        real = [realism_score(r["facts"], bands) for r in rs]
        results[name] = {
            "realism_inside_frac": mean_ci([x["score"] for x in real]),
            "realism_distance": mean_ci([x["distance"] for x in real]),
            "validation_fact_distance": mean_ci([_fact_distance(r["facts"], val_mean, tr_std) for r in rs])
            if have_hist
            else None,
            "facts_mean": {
                k: float(np.nanmean([r["facts"].get(k, float("nan")) for r in rs])) for k in [*FACTS, "ret_std_bps"]
            },
            "max_drawdown_pct": mean_ci([r.get("max_drawdown_pct", float("nan")) for r in rs]),
            "liquidations": mean_ci([r.get("liquidations", float("nan")) for r in rs]),
            "events_per_s": mean_ci([r.get("events_per_s", float("nan")) for r in rs]),
            "n_runs": len(rs),
        }
    heldout = None
    if have_hist:
        heldout = {
            "full_model_heldout_fact_distance": mean_ci(
                [_fact_distance(r["facts"], held_mean, tr_std) for r in runs if r["model"] == "full_model"]
            ),
            "heldout_windows": len(held),
            "note": "held-out windows are used only here, after model choices were fixed",
        }
    report = {
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "reference": ref_name,
        "bands": bands or LITERATURE_BANDS,
        "seeds": seeds,
        "duration_s": duration_s,
        "historical": {
            "train_windows": len(train),
            "validation_windows": len(val),
            "heldout_windows": len(held),
            "train_ret_std_bps": hist_sigma,
            "validation_facts_mean": val_mean,
        },
        "models": results,
        "heldout": heldout,
        "fingerprints": {f"{r['model']}:{r['seed']}": r.get("fingerprint") for r in runs if r.get("fingerprint")},
        "caveats": [
            "Facts estimated from 60 one-minute returns per run are noisy; see CIs.",
            "Realism bands are 5-95% quantiles of 60-minute historical TRAIN windows.",
            "Synthetic results are not forecasts and are not calibrated probabilities.",
        ],
    }
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "report.json").write_text(json.dumps(report, indent=2, default=float))
    (EVAL_DIR / "report.md").write_text(render(report))
    return report


def _ci(c: dict[str, float] | None, f: str = ".3f") -> str:
    if not c or c.get("mean") is None or c["mean"] != c["mean"]:
        return "n/a"
    return f"{c['mean']:{f}} [{c['lo']:{f}}, {c['hi']:{f}}]"


def render(r: dict[str, Any]) -> str:
    L = [
        "# Evaluation report",
        "",
        f"Reference: {r['reference']}; {r['seeds']} seeds x {r['duration_s']}s per model.",
        f"Historical windows: train {r['historical']['train_windows']}, validation "
        f"{r['historical']['validation_windows']}, held-out {r['historical']['heldout_windows']}.",
        "",
        "| model | facts inside bands (mean [95% CI]) | validation fact distance (lower=better) | "
        "1-min vol bps | excess kurtosis | |r| ACF lag1 | max DD % |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, m in r["models"].items():
        fm = m["facts_mean"]
        L.append(
            f"| {name} | {_ci(m['realism_inside_frac'], '.2f')} | {_ci(m['validation_fact_distance'], '.2f')} | "
            f"{fm['ret_std_bps']:.1f} | {fm['excess_kurtosis']:.2f} | {fm['acf_absret_lag1']:.3f} | "
            f"{_ci(m['max_drawdown_pct'], '.2f')} |"
        )
    if r.get("heldout"):
        L += ["", f"Held-out distance (full model): {_ci(r['heldout']['full_model_heldout_fact_distance'], '.2f')}"]
    L += ["", f"Historical TRAIN 1-min volatility: {r['historical']['train_ret_std_bps']:.1f} bps", ""]
    L += [f"- {c}" for c in r["caveats"]]
    return "\n".join(L) + "\n"
