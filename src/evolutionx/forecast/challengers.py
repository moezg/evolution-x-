"""Challenger lifecycle under evals/frozen/challenger_policy_v1.json: paired losses vs the champion, the frozen
interim futility rule, and the persisted status (active / retired:<target>) that issuance respects."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .ledger import ForecastLedger

POLICY = Path("evals/frozen/challenger_policy_v1.json")
STATE = Path("data/decisions/challengers.json")
CHAMPION = "M1_logistic"
EXCLUDED: list[dict[str, Any]] = []  # pairs excluded by the information-cutoff rule (filled by paired())


def state() -> dict[str, Any]:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def active(model: str, target: str) -> bool:
    """Only challengers activated by a journaled decision are issued (a passing feature test is not enough)."""
    return f"{model}:{target}" in state().get("_active", [])


def retired(model: str, target: str) -> bool:
    return target in state().get(model, {}).get("retired_targets", [])


def _loss(target: str, pred: float, y: float) -> float:
    if target.startswith("rv_"):
        return (math.log(max(pred, 1e-12)) - math.log(max(y, 1e-12))) ** 2
    return (pred - y) ** 2


def block_ci(d: np.ndarray, block: int = 7, n: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    k = math.ceil(len(d) / block)
    means = []
    for _ in range(n):
        starts = rng.integers(0, max(1, len(d) - block + 1), k)
        means.append(np.concatenate([d[s : s + block] for s in starts])[: len(d)].mean())
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def paired(led: ForecastLedger | None = None) -> dict[tuple[str, str], np.ndarray]:
    led = led or ForecastLedger()
    EXCLUDED.clear()
    fc, rs = led.forecasts(), led.resolutions()
    champ = {(e["data"]["origin_ms"], e["data"]["target"]): e for e in fc.values() if e["data"]["model"] == CHAMPION}
    out: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for fid, e in fc.items():
        d = e["data"]
        c = champ.get((d["origin_ms"], d["target"]))
        if not d["model"].startswith("CH:") or c is None or fid not in rs or c["data"]["id"] not in rs:
            continue
        if c["data"]["as_of_ms"] != d["as_of_ms"]:  # challenger_policy_v2: same information cutoff required
            EXCLUDED.append({"challenger": fid, "champion": c["data"]["id"], "reason": "as_of_ms differs"})
            continue
        y = rs[fid]["data"]["outcome"]
        diff = _loss(d["target"], d["scored_value"], y) - _loss(d["target"], c["data"]["scored_value"], y)
        out.setdefault((d["model"], d["target"]), []).append((d["origin_ms"], diff))
    return {k: np.array([x for _, x in sorted(v)]) for k, v in out.items()}


def review(led: ForecastLedger | None = None) -> dict[str, Any]:
    pol = json.loads(POLICY.read_text())["interim_futility"]
    st = state()
    res = {}
    for (model, target), d in paired(led).items():
        if model.startswith("_"):
            continue
        r: dict[str, Any] = {"n_pairs": len(d), "mean_diff": float(d.mean()) if len(d) else None}
        if len(d) >= pol["min_resolved_pairs"]:
            lo, hi = block_ci(d)
            r["ci95"] = [lo, hi]
            if lo > 0 and not retired(model, target):
                st.setdefault(model, {}).setdefault("retired_targets", []).append(target)
                r["action"] = "RETIRED (futility rule)"
        else:
            r["action"] = f"insufficient pairs (< {pol['min_resolved_pairs']})"
        res[f"{model}:{target}"] = r
    if st != state():
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, indent=1))
    return {
        "reviews": res,
        "state": st,
        "excluded_pairs": list(EXCLUDED),
        "note": "running means are descriptive, not tests (challenger_policy_v2: efficacy only at planned looks)",
    }
