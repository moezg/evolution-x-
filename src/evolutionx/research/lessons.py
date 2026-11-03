"""Outcome classification and lessons, computed from the EXISTING research memory (no parallel store).

Classes (descriptive; a class never proves the cause of a failure):
  technically_false_premise      a verifiable premise was falsified before any backtest
  rejected_gate                  static/sandbox/causality/determinism gate failed
  duplicate                      identical code already evaluated
  mechanism_not_observed         the declared mechanism metric did not move as predicted (development)
  benefit_absorbed_by_costs      gross Sharpe improved vs parent but net Sharpe did not (development)
  unstable_across_periods        development and validation disagree, or instruments/windows disagree
  mechanism_observed_no_benefit  mechanism moved as predicted (or none declared) but no net benefit
  insufficient_evidence          validation inconclusive under the frozen rule
  confirmed                      passed the frozen promotion rule (exploratory if validation is compromised)
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .memory import Memory

CLASSES = (
    "technically_false_premise",
    "rejected_gate",
    "duplicate",
    "mechanism_not_observed",
    "benefit_absorbed_by_costs",
    "unstable_across_periods",
    "mechanism_observed_no_benefit",
    "insufficient_evidence",
    "confirmed",
)


def _mean(d: dict[str, dict[str, Any]], key: str) -> float:
    vals = [v[key] for v in d.values() if isinstance(v.get(key), int | float) and math.isfinite(v[key])]
    return sum(vals) / len(vals) if vals else float("nan")


def dev_deltas(cand_diag: dict[str, Any], parent_diag: dict[str, Any]) -> dict[str, float]:
    keys = ("net_sharpe", "gross_sharpe", "turnover_per_year", "max_drawdown", "trading_cost_share", "avg_holding_bars")
    return {k: _mean(cand_diag, k) - _mean(parent_diag, k) for k in keys}


def mechanism_result(test: dict[str, Any] | None, cand_diag: dict[str, Any], parent_diag: dict[str, Any]) -> dict:
    if not test:
        return {"declared": False}
    syms = list(cand_diag) if test.get("symbol", "ALL") == "ALL" else [test["symbol"]]
    m = test["metric"]
    out = {}
    for s in syms:
        a, b = cand_diag[s].get(m), parent_diag[s].get(m)
        rel = (a - b) / abs(b) if b else float("nan")
        want = -1 if test["direction"] == "decrease" else 1
        out[s] = {
            "candidate": a,
            "parent": b,
            "relative_change": rel,
            "ok": bool(math.isfinite(rel) and want * rel >= float(test.get("min_relative_change", 0.0))),
        }
    return {"declared": True, "test": test, "per_symbol": out, "observed": all(v["ok"] for v in out.values())}


def classify(
    ck: dict[str, Any],
    cand_diag: dict[str, Any] | None,
    parent_diag: dict[str, Any] | None,
    cand_dev: dict[str, Any] | None = None,
    parent_dev: dict[str, Any] | None = None,
) -> dict[str, Any]:
    note = "descriptive class from measured numbers; it does not prove the cause of the outcome"
    if (ck.get("premise_check") or {}).get("verdict", "accepted") != "accepted":
        return {"class": "technically_false_premise", "note": note, "premises": ck["premise_check"]["counts"]}
    if ck.get("rejection"):
        return {"class": "rejected_gate", "gate": ck["rejection"].get("gate"), "note": note}
    if ck.get("duplicate_of"):
        return {"class": "duplicate", "of": ck["duplicate_of"], "note": note}
    if not cand_diag or not parent_diag:
        return {"class": "insufficient_evidence", "note": "no development diagnostics", "detail": {}}
    mech = ck.get("mechanism") or {"declared": False}
    dd = dev_deltas(cand_diag, parent_diag)
    verdict = ck.get("verdict")
    detail = {"dev_deltas_vs_parent": dd, "mechanism": mech, "validation_verdict": verdict}
    if verdict == "promote":
        return {"class": "confirmed", "note": note, "detail": detail}
    if mech.get("declared") and not mech.get("observed"):
        return {"class": "mechanism_not_observed", "note": note, "detail": detail}
    if dd["gross_sharpe"] > 0.05 and dd["net_sharpe"] <= 0:
        return {"class": "benefit_absorbed_by_costs", "note": note, "detail": detail}
    screen = ck.get("screen") or {}
    signs = [v.get("oos_sharpe", 0) for v in ((cand_dev or {}).get("per_symbol") or {}).values()]
    instr_disagree = len(signs) > 1 and min(signs) < 0 < max(signs)
    if (screen.get("passed") and verdict == "refuted") or instr_disagree:
        return {
            "class": "unstable_across_periods",
            "note": note,
            "detail": {**detail, "dev_screen_passed": screen.get("passed"), "instruments_disagree": instr_disagree},
        }
    if verdict == "inconclusive":
        return {"class": "insufficient_evidence", "note": note, "detail": detail}
    return {"class": "mechanism_observed_no_benefit", "note": note, "detail": detail}


def lessons(roots: list[Path], limit: int = 40) -> list[dict[str, Any]]:
    """Compact, number-backed lessons from archived tasks across labs (development + coarse validation verdict)."""
    out: list[dict[str, Any]] = []
    for r in roots:
        db = r / "research.db"
        if not db.exists():
            continue
        m = Memory(db)
        for t in m.q("SELECT id, checkpoint FROM tasks WHERE status IN ('done','failed') ORDER BY created"):
            ck = t["checkpoint"] or {}
            cl = ck.get("classification") or {}
            ext = ck.get("external") or {}
            change = ext.get("novelty") or ck.get("operator")
            row = {
                "task": f"{r.name}/{t['id']}",
                "change": (change or "")[:240],
                "operator": ck.get("operator"),
                "design_parent": ck.get("design_parent"),
                "class": cl.get("class", "unclassified"),
                "validation_verdict": ck.get("verdict"),
            }
            det = cl.get("detail") or {}
            if det.get("dev_deltas_vs_parent"):
                row["dev_deltas_vs_parent"] = {
                    k: round(v, 3)
                    for k, v in det["dev_deltas_vs_parent"].items()
                    if isinstance(v, float) and math.isfinite(v)
                }
            if (det.get("mechanism") or {}).get("declared"):
                row["mechanism_observed"] = det["mechanism"]["observed"]
            if ck.get("decision"):
                b = ck["decision"]["bootstrap"]
                row["validation_delta_sharpe"] = round(b["delta_sharpe"], 3)
                row["validation_prob_positive"] = round(b["prob_positive"], 3)
            out.append(row)
    return out[-limit:]
