"""Predictive Intelligence Control Center API (P8). GET only; every number is read from persisted records
(forecast ledger, ops.db, army store, test registry, calibration study, proposal index). Where prospective evidence
is insufficient the payload says so explicitly - nothing is extrapolated or filled in.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/control")


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).isoformat(timespec="minutes")


def _read(p: str) -> Any:
    f = Path(p)
    return json.loads(f.read_text()) if f.exists() else None


CHAMPION = "M1_logistic"  # forecast protocol v1 champion (artifacts/forecast/evolution_v1.json)


def _role(model: str) -> str:
    if model.startswith("CH:"):
        return "challenger"
    if model == CHAMPION:
        return "champion"
    return "baseline" if model in ("B0_climatology", "B1_ewma_gauss") else "alternative"


@router.get("/forecasts")
def forecasts() -> dict[str, Any]:
    from ..forecast.ledger import ForecastLedger
    from ..forecast.prospective import PROMOTION_MIN_RESOLVED

    led = ForecastLedger()
    fc, rs = led.forecasts(), led.resolutions()
    by_origin: dict[int, list[dict[str, Any]]] = {}
    for fid, e in fc.items():
        d = e["data"]
        by_origin.setdefault(d["origin_ms"], []).append(
            {
                "id": fid,
                "target": d["target"],
                "model": d["model"],
                "role": _role(d["model"]),
                "value": d["value"],
                "scored_value": d["scored_value"],
                "abstained": d["abstained"],
                "abstain_reason": d.get("abstain_reason"),
                "issued_utc": _iso(d["issued_ms"]),
                "window_end_utc": _iso(d["window_end_ms"]),
                "model_version": d["model_version"],
                "feature_version": d.get("feature_version"),
                "snapshot_sha256": (d.get("input_snapshot") or {}).get("sha256"),
                "resolved": fid in rs,
                "outcome": rs[fid]["data"]["outcome"] if fid in rs else None,
            }
        )
    resolved_by_target: dict[str, int] = {}
    for fid in rs:
        t = fc[fid]["data"]["target"]
        resolved_by_target[t] = resolved_by_target.get(t, 0) + 1
    targets = sorted({e["data"]["target"] for e in fc.values()})
    return {
        "origins": [
            {
                "origin_utc": _iso(o),
                "lag_h": next((e["data"].get("lag_h") for e in fc.values() if e["data"]["origin_ms"] == o), None),
                "forecasts": sorted(v, key=lambda x: (x["target"], x["model"])),
            }
            for o, v in sorted(by_origin.items(), reverse=True)
        ],  # fmt: skip
        "missed": [
            {
                "origin_utc": _iso(m["data"]["origin_ms"]),
                "reason": m["data"]["reason"],
                "recorded_utc": _iso(m["data"]["recorded_ms"]),
            }
            for m in led.missed()
        ],  # fmt: skip
        "verify": led.verify(),
        "evidence": {
            t: {"resolved": resolved_by_target.get(t, 0), "required_for_promotion": PROMOTION_MIN_RESOLVED}
            for t in targets
        },
        "sufficient_prospective_evidence": any(v >= PROMOTION_MIN_RESOLVED for v in resolved_by_target.values()),
    }


@router.get("/reliability")
def reliability() -> dict[str, Any]:
    from ..army import drift

    status = _read("artifacts/forecast/prospective_status.json")
    cal = _read("artifacts/quant/calibration_v2.json") or _read("artifacts/quant/calibration_v1.json")
    return {
        "prospective_scores": status,
        "drift": drift.check(),
        "calibration_study": None
        if cal is None
        else {
            k: cal[k]
            for k in (
                "protocol",
                "protocol_sha256",
                "label",
                "smoke_test_not_registered",
                "n_rotations",
                "null",
                "power",
                "quarantine",
                "started_utc",
                "finished_utc",
            )
            if k in cal
        },
        "note": "scores exist only for resolved prospective forecasts; until then reliability is UNKNOWN, not good",
    }


@router.get("/army")
def army() -> dict[str, Any]:
    from ..army.roles import ROLES
    from ..army.value import report

    caps = _read("artifacts/army/capability_audit.json") or {}
    sessions = []
    for p in sorted(Path("artifacts/army/specialists").glob("*.json"), reverse=True)[:10]:
        d = json.loads(p.read_text())
        sessions.append(
            {
                "session": d["session"],
                "steps": [
                    {
                        "role": s["role"],
                        "used_llm": (s.get("llm") or {}).get("used_llm"),
                        "cost": (s.get("llm") or {}).get("cost_usd_api_equivalent"),
                        "valid": (s.get("validation") or {}).get("valid"),
                    }
                    for s in d["steps"]
                ],  # fmt: skip
                "proposals": [
                    {"by": x["by"], "status": x["validation"]["status"], "reasons": x["validation"].get("reasons")}
                    for x in d["proposals"]
                ],  # fmt: skip
                "lineage": d.get("lineage"),
                "revalidations": d.get("revalidations", []),
            }
        )
    return {
        "roles": [
            {
                "id": r.id,
                "division": r.division,
                "title": r.title,
                "impl": r.impl,
                "class": (caps.get("roles") or {}).get(r.id),
            }
            for r in ROLES
        ],  # fmt: skip
        "value": report(),
        "specialist_sessions": sessions,
    }


@router.get("/quant")
def quant() -> dict[str, Any]:
    from ..quant.stats import TestRegistry

    reg = TestRegistry()
    rows = reg.rows()
    last_run: dict[str, str] = {}
    for r in rows:
        last_run[r["hypothesis"]] = max(last_run.get(r["hypothesis"], ""), r["run_id"] or "")
    cal = _read("artifacts/quant/calibration_v2.json") or _read("artifacts/quant/calibration_v1.json") or {}
    quarantined = [m for m, v in (cal.get("quarantine") or {}).items() if isinstance(v, dict) and v.get("quarantined")]
    calendar_fams = ("F-DOM", "F-DOW", "F-MOY", "F-TOM")  # the only families the calibration study assessed
    by_h: dict[str, dict[str, Any]] = {}
    for r in rows:  # one entry per hypothesis (its latest run) carrying its discovery and confirmation rows
        if (r["run_id"] or "") != last_run[r["hypothesis"]]:
            continue
        h = by_h.setdefault(
            r["hypothesis"],
            {"hypothesis": r["hypothesis"], "family": r["family"], "status": r["status"], "run_id": r["run_id"]},
        )
        h[r["period"].lower()] = {k: r[k] for k in ("id", "n", "effect", "p", "p_adj", "ci_lo", "ci_hi")}
    findings = []
    for h in by_h.values():
        if h["status"] not in ("supported", "inconclusive"):
            continue
        metric = h["hypothesis"].split(":")[-1].replace("_wd_adj", "")
        h["quarantined_metric"] = h["family"] in calendar_fams and metric in quarantined
        findings.append(h)
    fu = Path("artifacts/ops/event_followups.jsonl")
    return {
        "counts": reg.counts(),
        "findings": sorted(findings, key=lambda x: (x["status"] != "supported", x["hypothesis"])),
        "note": "status is per hypothesis (two-stage rule); each finding carries its discovery and confirmation rows",
        "quarantined_metrics": quarantined,
        "event_followups": [json.loads(x) for x in fu.read_text().splitlines()] if fu.exists() else [],
        "label": "all 'supported' results are exploratory until prospectively confirmed",
    }


@router.get("/evolution")
def evolution() -> dict[str, Any]:
    from ..evolution.categories import build

    return build()


@router.get("/ops")
def ops() -> dict[str, Any]:
    from ..army.store import Store
    from ..ops import scheduler as S

    st = S.status()
    hb = st["heartbeat"].get("last_tick_utc")
    age = (dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(hb)).total_seconds() if hb else None
    return {
        **st,
        "last_tick_age_s": age,
        "scheduler_alive": age is not None and age < 900,
        "army_state": Store().control("state", "running"),
    }


@router.get("/decisions")
def decisions() -> dict[str, Any]:
    from ..ops.decisions import Decisions

    D = Decisions()
    return {
        "decisions": D.view(),
        "verify": D.j.verify(),
        "agenda": _read("data/decisions/agenda.json"),
        "challengers": _read("data/decisions/challengers.json") or {},
    }


@router.get("/candidates")
def candidates() -> dict[str, Any]:
    from ..forecast.candidates import build

    return build()
