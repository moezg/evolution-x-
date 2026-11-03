"""Quantitative Intelligence API: event registry, testing registry, calendar / cycle / event studies, lineage.

Read-only. Every number comes from executable results under artifacts/quant/ and the stat_tests registry.
Nothing here marks a finding as a verified signal: statuses are exploratory unless prospectively confirmed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

OUT = Path("artifacts/quant")
router = APIRouter(prefix="/api/quant")


def _latest(name: str) -> dict[str, Any]:
    p = OUT / f"latest_{name}.json"
    if not p.exists():
        raise HTTPException(404, f"{name} not produced yet (run `evox quant run`)")
    return json.loads(p.read_text())


@router.get("/protocol")
def protocol() -> dict[str, Any]:
    return json.loads(Path("evals/frozen/quant_protocol_v1.json").read_text())


@router.get("/events")
def events(category: str | None = None) -> dict[str, Any]:
    from ..quant.events import Registry

    r = Registry()
    return {"events": r.current(category), "verify": r.j.verify(), "versions": len(r.entries())}


@router.get("/tests")
def tests(family: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    from ..quant.stats import TestRegistry

    reg = TestRegistry()
    return {"tests": reg.rows(family, run_id), "counts": reg.counts()}


@router.get("/calendar")
def calendar() -> dict[str, Any]:
    return _latest("calendar")


@router.get("/fomc")
def fomc() -> dict[str, Any]:
    return _latest("fomc")


@router.get("/elections")
def elections() -> dict[str, Any]:
    return _latest("elections")


@router.get("/cycles")
def cycles() -> dict[str, Any]:
    return _latest("cycles")


@router.get("/forecast-link")
def forecast_link() -> dict[str, Any]:
    return _latest("forecast_link")


@router.get("/rankings")
def rankings() -> dict[str, Any]:
    """Hypotheses ranked by evidence: supported (confirmed on later data) > inconclusive > rejected; then |z|/p."""
    from ..quant.stats import TestRegistry

    rows = TestRegistry().rows()
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = r["hypothesis"]
        e = by.setdefault(k, {"hypothesis": k, "family": r["family"], "role": r["role"], "tests": []})
        e["tests"].append(
            {
                x: r[x]
                for x in (
                    "id",
                    "period",
                    "n",
                    "effect",
                    "ci_lo",
                    "ci_hi",
                    "p",
                    "p_adj",
                    "adj_method",
                    "status",
                    "method",
                    "run_id",
                )
            }
        )
        e["status"] = r["status"] if r["period"] != "CONFIRMATION" or e.get("status") is None else e["status"]
    order = {
        "supported": 0,
        "candidate_feature (prospective challenger only)": 0,
        "inconclusive": 1,
        "exploratory": 2,
        "descriptive_only": 3,
        "not_promoted": 4,
        "rejected": 5,
    }
    ranked = sorted(
        by.values(),
        key=lambda e: (
            order.get(str(e.get("status")), 9),
            min((t["p"] if t["p"] is not None else 1.0) for t in e["tests"]),
        ),
    )
    return {
        "ranking": ranked,
        "legend": "supported = survived discovery (BH) and chronological confirmation (Holm); still EXPLORATORY until prospective observations confirm it - never a verified trading signal",
    }


@router.get("/workflow")
def workflow() -> dict[str, Any]:
    from ..army.store import Store

    s = Store()
    cyc = [
        c
        for c in s.q("SELECT * FROM army_cycles ORDER BY created DESC")
        if (c["config"] or {}).get("workflow") == "quant"
    ]
    if not cyc:
        raise HTTPException(404, "no quant workflow run yet")
    c = cyc[0]
    tasks = s.q(
        "SELECT id, stage, role, kind, status, deps, result, error, wall_s, llm_calls FROM army_tasks WHERE cycle_id=? ORDER BY created",
        (c["id"],),
    )
    return {
        "cycle": c,
        "tasks": tasks,
        "runs": [{"id": x["id"], "status": x["status"], "created": x["created"]} for x in cyc],
    }
