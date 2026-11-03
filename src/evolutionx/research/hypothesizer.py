"""Formulation role: turns development-only diagnostics + research memory into a pre-registered ResearchTask.

Two experiment-selection policies are implemented so that the research PROCESS itself can be compared at equal
budget (level 4):
  guided  - ranks operators by documented diagnostic rules, skips already-tested (parent, operator) pairs
  random  - uniform choice among untested operators (control)
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from .generator import OPERATORS

ALL_OPS = list(OPERATORS)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def rank_operators(diag: dict[str, dict[str, float]]) -> list[tuple[str, float, str]]:
    sy = list(diag.values())
    cost = _mean([d["trading_cost_share"] for d in sy])
    fund = _mean([d["funding_cost_share"] for d in sy])
    vol_gap = _mean([d["sharpe_low_vol_tercile"] - d["sharpe_high_vol_tercile"] for d in sy])
    churn = _mean([1.0 / max(d["avg_holding_bars"], 1.0) for d in sy])
    scores = {
        "add_deadzone": (cost, f"trading costs = {cost:.2f} x |gross PnL|"),
        "add_funding_guard": (fund, f"funding = {fund:.2f} x |gross PnL|"),
        "add_vol_target": (
            max(vol_gap, 0.0) / 2,
            f"Sharpe(low-vol tercile) - Sharpe(high-vol tercile) = {vol_gap:.2f}",
        ),
        "add_trend_filter": (churn * 20, f"mean holding = {1 / max(churn, 1e-9):.1f} bars"),
        "change_horizon": (0.2, "prior"),
        "swap_signal": (0.2, "prior"),
        "try_reversion": (0.1, "prior"),
    }
    return sorted(((k, v[0], v[1]) for k, v in scores.items()), key=lambda x: (-x[1], x[0]))


def signature(parent_sha: str, operator: str) -> str:
    return hashlib.sha256(f"{parent_sha}|{operator}".encode()).hexdigest()[:16]


def choose(
    selector: str, diag: dict[str, Any], tested: set[str], parent_sha: str, rng: random.Random
) -> tuple[str, str, list[dict[str, Any]]]:
    ranking = rank_operators(diag)
    untested = [op for op, _, _ in ranking if signature(parent_sha, op) not in tested]
    pool = untested or [op for op, _, _ in ranking]  # all tested: re-test with new random parameters
    if selector == "guided":
        op = pool[0]
        why = next(w for o, _, w in ranking if o == op)
    elif selector == "random":
        op = pool[rng.randrange(len(pool))]
        why = "uniform random choice among untested operators (control policy)"
    else:
        raise ValueError(selector)
    return op, why, [{"operator": o, "score": round(sc, 4), "evidence": w} for o, sc, w in ranking]


def build_task(
    task_id: str,
    campaign_id: str,
    op: str,
    why: str,
    ranking: list[dict[str, Any]],
    parent: dict[str, Any],
    diag: dict[str, Any],
    protocol: dict[str, Any],
    protocol_sha: str,
    data_manifest_sha: str,
    budget: dict[str, Any],
    champion_ref: str,
) -> dict[str, Any]:
    h = OPERATORS[op]
    rule = protocol["promotion_rule"]
    task = {
        "id": task_id,
        "campaign_id": campaign_id,
        "objective": "Improve the validation net Sharpe of the active champion under the frozen promotion rule.",
        "sources": {
            "champion_evaluation": champion_ref,
            "protocol_sha256": protocol_sha,
            "data_manifest_sha256": data_manifest_sha,
            "parent_version": parent["version"],
            "parent_sha256": parent["sha256"],
        },
        "initial_observation": {
            "diagnostics_development_only": diag,
            "selection_reason": why,
            "operator_ranking": ranking,
        },
        "hypothesis": h["statement"],
        "mechanism": h["mechanism"],
        "alternatives": h["alternatives"],
        "testable_prediction": h["prediction"],
        "primary_metric": rule["primary_metric"],
        "secondary_measures": [
            "development walk-forward OOS Sharpe",
            "max drawdown",
            "net Sharpe at 2x costs",
            "deflated Sharpe ratio",
            "turnover",
            "per-window win rate vs champion",
        ],
        "minimal_useful_effect": {"delta_sharpe": rule["minimal_useful_effect_sharpe"]},
        "refutation_criteria": [
            "development OOS Sharpe not above champion's (screen) -> refuted",
            "validation P(delta Sharpe > 0) < 0.5 -> refuted",
            "otherwise, if any promotion check fails -> inconclusive",
        ],
        "allowed_data": {
            "generator": "none (parent source + development diagnostics only)",
            "candidate_sandbox": "development + validation bars (decisions only; no results visible)",
            "evaluator": "development; validation only if screened in; final: never in tasks",
        },
        "time_split": protocol["splits"],
        "configuration": {"operator": op},
        "budget": budget,
        "statistical_plan": {
            "screen": "walk-forward OOS Sharpe on development (protocol walk_forward)",
            "test": rule["bootstrap"],
            "deflation": "DSR with N = all validation trials to date",
            "multiplicity": protocol["statistics"]["multiple_comparisons"],
        },
        "stopping_rule": "one candidate per task, fixed sample (full validation split); no re-testing on validation "
        "with extra data or seeds",
    }
    task["preregistration_sha256"] = hashlib.sha256(json.dumps(task, sort_keys=True, default=str).encode()).hexdigest()
    return task
