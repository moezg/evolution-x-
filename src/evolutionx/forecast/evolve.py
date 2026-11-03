"""Controlled evolution of forecasting models against frozen baselines (forecast_protocol_v1 'evolution').

* A candidate is a config in a frozen space (model family, feature subset, L2 / boosting settings). It cannot
  change targets, data, lag, periods or scoring - those live in code the candidate never touches.
* Every evaluation is counted as a trial per target in the research Memory (artifacts/forecast/research.db).
* Acceptance on SCREEN: one-sided block-bootstrap p < 0.05 / (trials so far for that target) vs the frozen champion
  (M1_logistic) AND no Brier/MSE degradation on DEV. Identical candidates are refused (dedup).
* An accepted candidate becomes a CHALLENGER for prospective issue. It never replaces the champion automatically;
  promotion needs >= 180 resolved prospective forecasts and human approval.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..research.memory import Memory
from .backtest import compare, run_target
from .domain import FEATURES, Target

DB = Path("artifacts/forecast/research.db")
CHAMPION = "M1_logistic"
ALLOWED_KEYS = {"model", "features", "l2", "rounds", "lr", "min_leaf"}


class CandidateRejected(ValueError):
    pass


def validate(spec: dict[str, Any]) -> None:
    extra = set(spec) - ALLOWED_KEYS
    if extra:
        raise CandidateRejected(f"fields outside the frozen candidate space: {sorted(extra)}")
    if spec.get("model") not in ("logistic", "gbm"):
        raise CandidateRejected("model must be logistic or gbm")
    feats = spec.get("features", [])
    if not feats or any(f not in FEATURES for f in feats):
        raise CandidateRejected("features must be a non-empty subset of the frozen feature list")


def _key(target: str, spec: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"t": target, "s": spec}, sort_keys=True).encode()).hexdigest()[:20]


def evaluate(
    target: Target, spec: dict[str, Any], tab: dict[str, Any], lag_ms: int, mem: Memory | None = None
) -> dict[str, Any]:
    validate(spec)
    mem = mem or Memory(DB)
    key = _key(target.name, spec)
    if mem.get_experiment(key) is not None:
        raise CandidateRejected("identical candidate already evaluated for this target")
    cand = "CAND:" + json.dumps(spec, sort_keys=True)
    res = run_target((target, {**tab, "sim": None}, lag_ms, ("B0_climatology", CHAMPION, cand)))
    screen = compare(res, cand, CHAMPION, "SCREEN")
    dev = compare(res, cand, CHAMPION, "DEV")
    mem.add_trial(key, f"forecast-screen:{target.name}", spec, "loss_diff_vs_champion", screen["mean"])
    n_trials = mem.n_trials(f"forecast-screen:{target.name}")
    threshold = 0.05 / n_trials
    accepted = screen["p_better"] < threshold and dev["mean"] <= 0
    result = {
        "target": target.name,
        "spec": spec,
        "screen_vs_champion": screen,
        "dev_vs_champion": dev,
        "trials_for_target": n_trials,
        "p_threshold": threshold,
        "status": "challenger (prospective only)" if accepted else "rejected",
        "replaces_champion": False,
    }
    mem.put_experiment(key, key, "forecast-evolution", "", "", result)
    mem.x(
        "INSERT OR IGNORE INTO candidates (id, parent_id, code_sha256, generator, operator, spec, path, status, created) VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
        (key, CHAMPION, None, "rule:forecast-proposer", target.name, json.dumps(spec), None, result["status"]),
    )
    return result


def propose(target: Target, report: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic proposer from retrospective DEV evidence only (never SCREEN, to keep SCREEN a selection test)."""
    dev = report["targets"][target.name]["scores"]["DEV"]
    base = list(FEATURES)
    vol_only = [f for f in FEATURES if f.startswith(("lrv", "lsig", "range", "absret"))]
    props = [
        {"model": "logistic", "features": vol_only, "l2": 1.0},
        {"model": "logistic", "features": base, "l2": 10.0},
        {"model": "gbm", "features": base, "rounds": 50, "lr": 0.05},
    ]
    if dev.get("M2_gbm", {}).get("brier", 1) < dev.get(CHAMPION, {}).get("brier", 0):
        props.append({"model": "gbm", "features": vol_only, "rounds": 100, "lr": 0.05})
    return props


def run_evolution(targets: tuple[str, ...] = ("move3_24", "move5_24", "rv_24")) -> dict[str, Any]:
    """Bounded demo cycle: propose from DEV evidence, evaluate with trial accounting, never replace the champion."""
    import datetime as dt

    from .backtest import OUT, build_table
    from .domain import HOUR, BTCDomain

    report = json.loads((OUT / "backtest_v1.json").read_text())
    dom = BTCDomain(lag_ms=24 * HOUR)
    tab = build_table(dom, "2020-02-01", "2026-10-28", with_sim=False)
    mem = Memory(DB)
    tmap = {t.name: t for t in dom.targets()}
    results = []
    for name in targets:
        for spec in propose(tmap[name], report):
            try:
                results.append(evaluate(tmap[name], spec, tab, dom.lag_ms, mem))
            except CandidateRejected as e:
                results.append({"target": name, "spec": spec, "status": f"refused: {e}"})
    out = {
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "champion": CHAMPION,
        "rule": "accept if SCREEN one-sided p < 0.05 / trials(target) and DEV not worse; accepted -> prospective challenger only",
        "results": results,
        "trials_by_target": {n: mem.n_trials(f"forecast-screen:{n}") for n in targets},
        "label": "retrospective screening on previously exposed data; no superiority claim",
    }
    (OUT / "evolution_v1.json").write_text(json.dumps(out, indent=1, default=float))
    return out
