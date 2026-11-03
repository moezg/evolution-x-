"""Realism track: multi-objective evaluation of simulator configurations with a Pareto archive.

Rules live in evals/frozen/realism_track_v1.json. The archive records the rules' sha256 and refuses to update
if they change, so a candidate (or an evolutionary loop) cannot rewrite the evaluation. Candidates are only
SimConfig overrides from an allow-list. The track can and does answer "not an improvement".
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from ..evaluation.calibration import multi_facts, target_stats, window_targets
from ..evaluation.stats import paired_diff
from ..sim.config import SimConfig
from ..sim.simulation import Simulation
from .market_stats import _clean

VERSION = "v2"  # v1 kept as evidence; see 'supersedes' in the v2 rules
RULES = Path(f"evals/frozen/realism_track_{VERSION}.json")
ARCHIVE = Path(f"artifacts/observatory/realism_archive_{VERSION}.json")


class RulesChanged(RuntimeError):
    pass


def rules() -> tuple[dict[str, Any], str]:
    raw = RULES.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def validate_candidate(over: dict[str, Any], allowed: list[str]) -> None:
    bad = sorted(set(over) - set(allowed))
    if bad:
        raise ValueError(f"candidate touches fields outside the allowed space: {bad}")
    SimConfig(**over)  # type/range validation by the config model itself


def _run(args: tuple[str, dict[str, Any], int, int]) -> dict[str, Any]:
    name, over, seed, dur = args
    t0 = time.perf_counter()
    sim = Simulation(SimConfig(seed=seed, duration_s=dur, invariant_check_every_s=600, **over)).run()
    sim.exchange.check_invariants()
    a = np.array(sim.series, dtype=float)
    cols = sim.series_columns()
    mid = a[:, cols.index("mid_0")] / 100
    vol = a[:, cols.index("volume")] / 1e4
    idx = np.arange(59, len(mid), 60)
    f = multi_facts(mid[idx], np.diff(np.r_[0, vol[idx]]))
    return {
        "candidate": name,
        "seed": seed,
        "facts": f,
        "cpu_s": time.perf_counter() - t0,
        "fingerprint": sim.fingerprint()[:16],
    }


def objectives(
    facts: dict[str, float], cpu_s: float, dur: int, spec: dict[str, Any], tgt: dict[str, tuple[float, float]]
) -> dict[str, float]:
    out = {}
    for name, o in spec["objectives"].items():
        if "facts" in o:
            errs = [abs(facts[k] - tgt[k][0]) / tgt[k][1] for k in o["facts"] if np.isfinite(facts.get(k, np.nan))]
            out[name] = float(np.mean(errs)) if errs else float("nan")
        else:
            out[name] = cpu_s * 3600 / dur
    return out


def dominates(a: dict[str, float], b: dict[str, float], tol: dict[str, float] | None = None) -> bool:
    t = tol or {}
    return all(a[k] <= b[k] * (1 + t.get(k, 0.0)) for k in a) and any(a[k] < b[k] * (1 - t.get(k, 0.0)) for k in a)


def verdict(cand: list[dict[str, float]], inc: list[dict[str, float]], cost_tol: float = 0.1) -> dict[str, Any]:
    """Paired by seed (lists in the same seed order). Error objectives use the t-interval; cost uses means."""
    better, worse, detail = [], [], {}
    for k in cand[0]:
        d = _clean(paired_diff([c[k] for c in cand], [i[k] for i in inc]))
        detail[k] = d
        if k.startswith("cost"):
            m = d.get("mean")
            if m is not None and abs(m) > cost_tol * float(np.mean([i[k] for i in inc])):
                (better if m < 0 else worse).append(k)
            continue
        if d.get("t_hi") is not None and d["t_hi"] < 0:
            better.append(k)
        elif d.get("t_lo") is not None and d["t_lo"] > 0:
            worse.append(k)
    errs_better = [k for k in better if not k.startswith("cost")]
    if errs_better and not worse:
        v = "improvement"
    elif better and worse:
        v = "trade-off"
    else:
        v = "not an improvement"
    return {"verdict": v, "better": better, "worse": worse, "paired": detail}


def load_archive(sha: str) -> dict[str, Any]:
    if not ARCHIVE.exists():
        return {"rules_sha256": sha, "pareto": [], "history": []}
    arc = json.loads(ARCHIVE.read_text())
    if arc["rules_sha256"] != sha:
        raise RulesChanged("realism rules changed since the archive was created; start a new versioned track")
    return arc


def update_archive(arc: dict[str, Any], entry: dict[str, Any], tol: dict[str, float] | None = None) -> dict[str, Any]:
    m = entry["objectives_mean"]
    fp = entry.get("fingerprints")
    dup = next((p["name"] for p in arc["pareto"] if fp and p.get("fingerprints") == fp), None)
    if dup:
        arc["history"].append({**entry, "admitted": False, "behavioural_duplicate_of": dup})
        return arc
    if any(dominates(p["objectives_mean"], m, tol) for p in arc["pareto"]):
        by = next(p["name"] for p in arc["pareto"] if dominates(p["objectives_mean"], m, tol))
        arc["history"].append({**entry, "admitted": False, "dominated_by": by})
        return arc
    keep = []
    for p in arc["pareto"]:
        if dominates(m, p["objectives_mean"], tol):
            arc["history"].append({**p, "admitted": True, "dominated_by": entry["name"]})
        else:
            keep.append(p)
    arc["pareto"] = [*keep, {**entry, "admitted": True}]
    return arc


def evaluate(candidates: dict[str, dict[str, Any]], workers: int = 4, tag: str | None = None) -> dict[str, Any]:
    spec, sha = rules()
    arc = load_archive(sha)
    incumbents = spec["incumbents"]
    missing = [i for i in incumbents if i not in candidates]
    if missing:
        raise ValueError(f"incumbents must be evaluated in the same batch: {missing}")
    tol = spec["dominance"]["tolerance"]
    names = list(candidates)
    for n in names:
        validate_candidate(candidates[n], spec["allowed_fields"])
    tgt = target_stats(window_targets("train"))
    jobs = [(n, candidates[n], s, spec["duration_s"]) for n in names for s in spec["seeds"]]
    t0 = time.perf_counter()
    with ProcessPoolExecutor(workers) as ex:
        rows = list(ex.map(_run, jobs))
    per: dict[str, list[dict[str, float]]] = {n: [] for n in names}
    fps: dict[str, list[str]] = {n: [] for n in names}
    for r in sorted(rows, key=lambda r: (r["candidate"], r["seed"])):
        r["objectives"] = objectives(r["facts"], r["cpu_s"], spec["duration_s"], spec, tgt)
        per[r["candidate"]].append(r["objectives"])
        fps[r["candidate"]].append(r["fingerprint"])
    results = {}
    for n in names:
        om = {k: float(np.mean([o[k] for o in per[n]])) for k in per[n][0]}
        vs = {i: verdict(per[n], per[i], tol["cost_cpu_s_per_sim_hour"]) for i in incumbents if i != n}
        entry = {
            "name": n,
            "overrides": candidates[n],
            "objectives_mean": om,
            "fingerprints": fps[n],
            "verdict_vs": {i: v["verdict"] for i, v in vs.items()},
            "evaluated_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }
        if not any(p["name"] == n for p in arc["pareto"]):
            arc = update_archive(arc, entry, tol)
        results[n] = {**entry, "verdict_detail": vs}
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE.write_text(json.dumps(_clean(arc), indent=2))
    rep = {
        "protocol": spec["name"],
        "rules_sha256": sha,
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "label": "SYNTHETIC simulator configurations vs HISTORICAL TRAIN-day targets; no independent validation",
        "targets_train": {k: {"median": v[0], "iqr": v[1]} for k, v in tgt.items()},
        "results": results,
        "pareto": [p["name"] for p in arc["pareto"]],
        "cost": {"runs": len(rows), "wall_s": round(time.perf_counter() - t0, 1), "llm_calls": 0},
        "runs": rows,
    }
    name = f"realism_{VERSION}.json" if tag is None else f"realism_{VERSION}_{tag}.json"  # batches never overwrite
    (ARCHIVE.parent / name).write_text(json.dumps(_clean(rep), indent=2, default=float))
    return rep


R = {"world_annual_vol": 0.33, "news_impact": 0.0}
CANDIDATES_V2: dict[str, dict[str, Any]] = {
    "default": {},
    "realistic_fundamental": R,
    "R_momentum_size_0.5": {**R, "size_scale": {"momentum": 0.5}},
    "R_leverage_use_0.35": {**R, "param_overrides": {"leveraged": {"leverage_use": 0.35}}},
    "R_mm_size_2": {**R, "size_scale": {"market_maker": 2.0}},
    "R_no_social": {**R, "social_enabled": False, "imitation_enabled": False},
}
