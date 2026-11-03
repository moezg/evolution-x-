"""Read models and controls for the research laboratory (all backed by persistent state on disk)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

ROOT = Path("artifacts/research")
router = APIRouter(prefix="/api/research")


def _lab(name: str):  # noqa: ANN202
    from ..research.supervisor import Lab, Supervisor

    if not re.fullmatch(r"[a-z0-9_]+", name) or not (ROOT / name / "research.db").exists():
        raise HTTPException(404, "lab not found")
    lab = Lab(ROOT / name, repo=Path.cwd())
    return lab, Supervisor(lab)


@router.get("/labs")
def labs() -> list[dict[str, Any]]:
    out = []
    for d in sorted(ROOT.glob("*/research.db")):
        lab, _ = _lab(d.parent.name)
        camps = lab.memory.q("SELECT id, mode, selector, status, budget, consumed, created, updated FROM campaigns")
        out.append(
            {
                "name": d.parent.name,
                "superseded": "superseded" in d.parent.name,
                "campaigns": camps,
                "active": lab.registry.active(),
                "stop_requested": lab.stop_file.exists(),
            }
        )
    return out


@router.get("/{name}/overview")
def overview(name: str) -> dict[str, Any]:
    lab, sup = _lab(name)
    hyp = lab.memory.q("SELECT status, COUNT(*) n FROM hypotheses GROUP BY status")
    tasks = lab.memory.q("SELECT status, COUNT(*) n FROM tasks GROUP BY status")
    return {
        "name": name,
        "campaigns": lab.memory.q("SELECT * FROM campaigns"),
        "active": lab.registry.active(),
        "versions": lab.registry.versions(),
        "hypotheses": {h["status"]: h["n"] for h in hyp},
        "tasks": {t["status"]: t["n"] for t in tasks},
        "journal": lab.journal.verify(),
        "stop_requested": lab.stop_file.exists(),
        "trials": {"development": lab.memory.n_trials("development"), "validation": lab.memory.n_trials("validation")},
        "protocol": {
            "name": sup.protocol["name"],
            "sha256": sup.protocol_sha,
            "splits": sup.protocol["splits"],
            "promotion_rule": sup.protocol["promotion_rule"],
            "amendments": sup.protocol.get("amendments", []),
        },
        "policy": sup.policy,
    }


@router.get("/{name}/tasks")
def tasks(name: str) -> list[dict[str, Any]]:
    lab, _ = _lab(name)
    out = []
    for t in lab.memory.q("SELECT * FROM tasks ORDER BY seq"):
        ck = t["checkpoint"] or {}
        d = ck.get("decision") or {}
        out.append(
            {
                "id": t["id"],
                "seq": t["seq"],
                "stage": t["stage"],
                "status": t["status"],
                "error": t["error"],
                "operator": ck.get("operator"),
                "design_parent": ck.get("design_parent"),
                "candidate_id": ck.get("candidate_id"),
                "verdict": (ck.get("archived") or {}).get("verdict") or ck.get("verdict"),
                "screen": ck.get("screen"),
                "rejection": ck.get("rejection"),
                "delta_sharpe": (d.get("bootstrap") or {}).get("delta_sharpe"),
                "prob_positive": (d.get("bootstrap") or {}).get("prob_positive"),
                "checks": d.get("checks"),
                "activation": ck.get("activation"),
                "duplicate_of": ck.get("duplicate_of"),
                "classification": (ck.get("classification") or {}).get("class"),
                "premise_verdict": (ck.get("premise_check") or {}).get("verdict"),
                "premise_counts": (ck.get("premise_check") or {}).get("counts"),
                "mechanism_observed": (ck.get("mechanism") or ck.get("mechanism_v2") or {}).get("observed"),
                "generator": (ck.get("external") or {}).get("generator") or ck.get("generator"),
                "updated": t["updated"],
            }
        )
    return out


@router.get("/{name}/tasks/{tid}")
def task(name: str, tid: str) -> dict[str, Any]:
    lab, _ = _lab(name)
    rows = lab.memory.q("SELECT * FROM tasks WHERE id=?", (tid,))
    if not rows:
        raise HTTPException(404, "task not found")
    t = rows[0]
    ck = t["checkpoint"] or {}
    cand = {}
    if ck.get("candidate_id"):
        d = lab.root / "candidates" / ck["candidate_id"]
        if d.exists():
            cand = {
                "diff": (d / "patch.diff").read_text() if (d / "patch.diff").exists() else "",
                "proposal": json.loads((d / "proposal.json").read_text()) if (d / "proposal.json").exists() else {},
                "source": (d / "strategy.py").read_text(),
            }
    exp = lab.memory.get_experiment(ck["experiment_key"]) if ck.get("experiment_key") else None
    if exp:
        exp = {k: v for k, v in exp.items() if k not in ("_dec",)}
        exp["development"] = {k: v for k, v in exp["development"].items() if k not in ("daily", "day_index")}
    dossier = None
    dp = lab.root / "dossiers" / f"{tid}.json"
    if dp.exists():
        dj = json.loads(dp.read_text())
        dossier = {
            "dossier_sha256": dj.get("dossier_sha256"),
            "git_commit": dj.get("git_commit"),
            "generated_utc": dj.get("generated_utc"),
            "sources": dj.get("sources"),
            "engine_features": dj.get("execution", {}).get("engine_features"),
            "rebalance_rule": dj.get("execution", {}).get("rebalance_rule"),
            "parent_behaviour": dj.get("parent", {}).get("measured_behaviour_development"),
            "has_lessons": "lessons_from_memory" in dj,
            "size_chars": len(dp.read_text()),
        }
    return {
        "task": t,
        "candidate": cand,
        "experiment": exp,
        "dossier": dossier,
        "premise_check": ck.get("premise_check"),
        "classification": ck.get("classification"),
        "mechanism": ck.get("mechanism") or ck.get("mechanism_v2"),
    }


@router.get("/{name}/hypotheses")
def hypotheses(name: str) -> list[dict[str, Any]]:
    lab, _ = _lab(name)
    return lab.memory.q("SELECT * FROM hypotheses ORDER BY created")


@router.get("/{name}/registry")
def registry(name: str) -> dict[str, Any]:
    lab, _ = _lab(name)
    hist = lab.registry.root / "history.jsonl"
    return {
        "active": lab.registry.active(),
        "versions": lab.registry.versions(),
        "history": [json.loads(x) for x in hist.read_text().splitlines()] if hist.exists() else [],
    }


@router.get("/{name}/journal")
def journal(name: str, n: int = 200) -> dict[str, Any]:
    lab, _ = _lab(name)
    return {"verify": lab.journal.verify(), "entries": lab.journal.tail(min(n, 2000))[::-1]}


class StopReq(BaseModel):
    reason: str = "stopped from dashboard"


@router.post("/{name}/stop")
def stop(name: str, req: StopReq) -> dict[str, Any]:
    _, sup = _lab(name)
    sup.request_stop("human:dashboard", req.reason)
    return {"stop_requested": True}


class ResumeReq(BaseModel):
    confirm: bool = False


@router.post("/{name}/resume")
def resume(name: str, req: ResumeReq) -> dict[str, Any]:
    _, sup = _lab(name)
    try:
        sup.human_resume("human:dashboard", req.confirm)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    return {"stop_cleared": True}


class RollbackReq(BaseModel):
    reviewer: str = Field(min_length=1, max_length=80)
    reason: str = ""


@router.post("/{name}/rollback")
def rollback(name: str, req: RollbackReq) -> dict[str, Any]:
    lab, _ = _lab(name)
    try:
        return lab.registry.rollback(req.reviewer, req.reason)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(409, str(e)) from e


class RunReq(BaseModel):
    campaign: str = Field(pattern=r"^[a-z0-9_\-]{2,40}$")
    mode: Literal["smoke", "research", "autonomous-experimental"] = "smoke"
    selector: Literal["guided", "random"] = "guided"
    tasks: int = Field(default=2, ge=1, le=60)
    wall_s: int = Field(default=900, ge=60, le=14400)


def register_run(app_jobs: Any) -> None:
    @router.post("/{name}/run")
    def run(name: str, req: RunReq) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise HTTPException(400, "bad lab name")

        def fn(progress, **p):  # noqa: ANN001, ANN003, ANN202
            from ..research.supervisor import Lab, Supervisor

            lab = Lab(ROOT / name, repo=Path.cwd())
            sup = Supervisor(lab)
            existing = lab.memory.q("SELECT mode, selector FROM campaigns WHERE id=?", (p["campaign"],))
            if existing and (existing[0]["mode"], existing[0]["selector"]) != (p["mode"], p["selector"]):
                raise ValueError("campaign id exists with a different mode/selector; use a new campaign id")
            sup.create_campaign(p["campaign"], p["mode"], p["selector"], p["tasks"], p["wall_s"])
            progress("running")
            return sup.run(p["campaign"])

        try:
            return app_jobs.submit("research", fn, req.model_dump())
        except RuntimeError as e:
            raise HTTPException(429, str(e)) from e


@router.get("/data")
def data_status() -> dict[str, Any]:
    from ..research.memory import Memory

    man = Path("data/research/manifest.json")
    m = json.loads(man.read_text()) if man.exists() else None
    ledger = []
    fdb = ROOT / "final" / "research.db"
    if fdb.exists():
        ledger = Memory(fdb).q("SELECT * FROM vault_ledger ORDER BY id")
    return {
        "manifest": m,
        "vault_ledger": ledger,
        "final_split_consumed": bool(ledger),
        "note": "final split is consumed once revealed; later reports are not blind",
    }


@router.get("/final")
def final_reports() -> list[dict[str, Any]]:
    reports = [json.loads(p.read_text()) for p in sorted((ROOT / "final").glob("*.json"))]
    return [r for r in reports if "strategies" in r]  # pre-registrations are served by /final/preregistrations


@router.get("/final/preregistrations")
def final_preregistrations() -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted((ROOT / "final").glob("preregistration-*.json"))]


@router.get("/calibration")
def calibration() -> dict[str, Any]:
    p = Path("artifacts/calibration/report.json")
    if not p.exists():
        raise HTTPException(404, "run `evox calibrate`")
    r = json.loads(p.read_text())
    liq = Path("artifacts/analysis/liquidity_supply.json")
    r["liquidity_supply"] = json.loads(liq.read_text()) if liq.exists() else None
    return r


@router.get("/comparisons")
def comparisons() -> list[dict[str, Any]]:
    out = []
    for p in sorted((ROOT / "comparisons").glob("*.json")):
        r = json.loads(p.read_text())
        for a in r.get("arms", {}).values():
            a.pop("rows", None)
        out.append(r)
    return out


@router.get("/comparisons/{tag}")
def comparison(tag: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9_\-]+", tag) or not (ROOT / "comparisons" / f"{tag}.json").exists():
        raise HTTPException(404, "comparison not found")
    return json.loads((ROOT / "comparisons" / f"{tag}.json").read_text())


@router.get("/lessons")
def lessons_view() -> dict[str, Any]:
    from ..research.lessons import operator_summary

    roots = [ROOT / n for n in ("arm_guided", "arm_random", "claude_session", "claude_cli")]
    summ = Path("artifacts/research/analysis/reclassification_summary.json")
    return {
        "summary_by_change_type": operator_summary(roots),
        "classes_by_lab": json.loads(summ.read_text()) if summ.exists() else None,
        "note": "descriptive classes from development measurements; a class does not prove the cause",
    }


@router.get("/exposure")
def exposure() -> dict[str, Any]:
    p = Path("evals/frozen/exposure_registry.json")
    reg = json.loads(p.read_text())
    v2 = Path("data/vault_v2/manifest.json")
    reg["vault_v2_manifest"] = json.loads(v2.read_text()) if v2.exists() else None
    return reg


@router.get("/premise-audit")
def premise_audit() -> dict[str, Any]:
    p = ROOT / "premise_audit" / "cli2_premises.json"
    if not p.exists():
        raise HTTPException(404, "no premise audit")
    return json.loads(p.read_text())
