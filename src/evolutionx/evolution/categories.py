"""P6: one index of improvement proposals across subsystems, each in exactly ONE category with its own evaluator.

Categories (what success is measured by):
  research_efficiency  cost / time / duplicates per research outcome
  scientific_validity  false-positive control, calibration, data integrity
  predictive_skill     proper scores of PROSPECTIVE forecasts vs the champion
  trading_performance  paper returns after costs on untouched data (then >= 180 resolved paper days)
  system_reliability   scheduler, recovery, tests, operations
A proposal is promotable only by independent evidence IN ITS OWN CATEGORY (progress in one category never counts for
another), and every code change additionally needs human review. Nothing here promotes anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATEGORIES = {
    "research_efficiency": "measured cost/time/duplicates per recorded outcome (army value report)",
    "scientific_validity": "synthetic calibration (false-positive rate with CI) and adversarial checks",
    "predictive_skill": ">= 180 resolved PROSPECTIVE forecasts per target, CI vs champion below 0, human approval",
    "trading_performance": "frozen selection rule on untouched data, then >= 180 resolved paper days, human approval",
    "system_reliability": "regression + integration tests and an observed operational run",
}
OUT = Path("artifacts/evolution/proposals_index.json")
TEST_FIXTURE_KEYS = ("redteam-", "noise-panic-hysteresis")  # written by tests/test_code_evolution.py runs


def _forecast_candidates() -> list[dict[str, Any]]:
    p = Path("artifacts/forecast/evolution_v1.json")
    if not p.exists():
        return []
    out = []
    for i, r in enumerate(json.loads(p.read_text())["results"]):
        out.append(
            {
                "id": f"fc-evo-{r['target']}-{i}",
                "source": "forecast evolution (frozen candidate space)",
                "category": "predictive_skill",
                "title": f"{r['spec'].get('model')} variant for {r['target']}",
                "status": r["status"],
                "independent_evidence": "none (retrospective SCREEN on exposed data only)",
                "promotable": False,
            }
        )
    return out


def _challengers() -> list[dict[str, Any]]:
    from ..forecast.ledger import ForecastLedger
    from ..forecast.prospective import PROMOTION_MIN_RESOLVED

    led = ForecastLedger()
    res = led.resolutions()
    by: dict[str, list[int]] = {}
    for fid, e in led.forecasts().items():
        if e["data"]["model"].startswith("CH:"):
            by.setdefault(e["data"]["model"], [0, 0])
            by[e["data"]["model"]][0] += 1
            by[e["data"]["model"]][1] += int(fid in res)
    return [
        {
            "id": m,
            "source": "quant discovery -> forecast challenger",
            "category": "predictive_skill",
            "title": f"{m} issued next to the unchanged champion",
            "status": "prospective_challenger",
            "independent_evidence": f"{n_res} resolved of {n} issued (needs {PROMOTION_MIN_RESOLVED} per target)",
            "promotable": False,
        }
        for m, (n, n_res) in by.items()
    ]


def _army_code() -> list[dict[str, Any]]:
    from ..army import codeprop

    return [
        {
            "id": p["id"],
            "source": f"army {p['author_role']} code proposal (isolated worktree)",
            "category": "system_reliability",
            "title": p["title"],
            "status": p["status"],
            "independent_evidence": "worktree checks "
            + ("passed" if p["status"] == "pending_human_review" else "failed"),
            "promotable": False,
            "requires_human_review": True,
        }
        for p in codeprop.proposals()
    ]


def _code_pipeline() -> tuple[list[dict[str, Any]], int]:
    out, fixtures = [], 0
    for d in sorted(Path("artifacts/proposals").glob("*/report.json")):
        r = json.loads(d.read_text())
        if r["key"].startswith(TEST_FIXTURE_KEYS):
            fixtures += 1
            continue
        gates = {g["name"]: g["passed"] for g in r.get("gates", [])}
        out.append(
            {
                "id": r["id"],
                "source": "code evolution pipeline (sandbox + gates)",
                "category": "trading_performance" if "momentum" in r["key"] else "scientific_validity",
                "title": r.get("summary") or r["key"],
                "status": "gates_passed" if gates and all(gates.values()) else "gates_failed",
                "independent_evidence": "frozen eval suite only (no untouched data, no paper days)",
                "promotable": False,
                "requires_human_review": True,
            }
        )
    return out, fixtures


def _army_hypotheses() -> list[dict[str, Any]]:
    from ..army.store import Store

    rows = Store().q("SELECT id, status, signature FROM hypotheses WHERE id LIKE 'H-%'")
    return [
        {
            "id": h["id"],
            "source": "research army strategy hypothesis",
            "category": "trading_performance",
            "title": (h["signature"] or "").split("|")[0],
            "status": h["status"],
            "independent_evidence": "none: 0 resolved paper days",
            "promotable": False,
        }
        for h in rows
    ]


def _specialists() -> list[dict[str, Any]]:
    out = []
    for p in sorted(Path("artifacts/army/specialists").glob("*.json")):
        d = json.loads(p.read_text())
        for i, prop in enumerate(d.get("proposals", [])):
            if not prop["by"].startswith("G1"):
                continue
            out.append(
                {
                    "id": f"{d['session']}-{i}",
                    "source": "G1 Quantitative Scientist (LLM specialist)",
                    "category": "predictive_skill",
                    "title": prop["proposal"]["statement"][:160],
                    "status": prop["validation"]["status"],
                    "independent_evidence": "none (queued for prospective evaluation at most)",
                    "promotable": False,
                }
            )
    return out


def _calibration() -> list[dict[str, Any]]:
    p = Path("artifacts/quant/calibration_v1.json")
    if not p.exists():
        return []
    q = json.loads(p.read_text()).get("quarantine", {})
    return [
        {
            "id": f"quarantine:{m}",
            "source": "P5 synthetic-null calibration (quant_calibration_v1)",
            "category": "scientific_validity",
            "title": f"quarantine metric {m} from automatic promotion",
            "status": "applied" if v["quarantined"] else "not_needed",
            "independent_evidence": "; ".join(v["reasons"]) or "false-positive rate within the frozen bounds",
            "promotable": None,
        }
        for m, v in q.items()
    ]


def promotable(p: dict[str, Any], evidence: dict[str, Any]) -> bool:
    """Only evidence in the proposal's own category counts; code changes also need a recorded human approval."""
    ok = bool(evidence.get(p["category"]))
    if p.get("requires_human_review"):
        ok = ok and bool(evidence.get("human_approval"))
    return ok


def build() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    errors = {}
    for name, fn in (
        ("forecast", _forecast_candidates),
        ("challengers", _challengers),
        ("army_code", _army_code),
        ("army_hypotheses", _army_hypotheses),
        ("specialists", _specialists),
        ("calibration", _calibration),
    ):
        try:
            items += fn()
        except Exception as e:  # noqa: BLE001 - one missing store must not hide the others
            errors[name] = f"{type(e).__name__}: {e}"
    code, fixtures = _code_pipeline()
    items += code
    out = {
        "categories": CATEGORIES,
        "proposals": items,
        "by_category": {c: sum(1 for p in items if p["category"] == c) for c in CATEGORIES},
        "promoted": [p["id"] for p in items if p.get("promotable")],
        "excluded_test_fixtures": fixtures,
        "errors": errors,
        "rule": "progress in one category is never evidence for another; code changes need human review",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=str))
    return out
