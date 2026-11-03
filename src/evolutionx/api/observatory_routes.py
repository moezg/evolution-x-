"""Read-only API for the Emergent Behavior Observatory (artifacts/observatory/*.json, evals/frozen specs).

Endpoints only read files written by the observatory modules; they never start runs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

OUT = Path("artifacts/observatory")
FROZEN = Path("evals/frozen")
router = APIRouter(prefix="/api/observatory")


def _read(p: Path) -> Any:
    if not p.exists():
        raise HTTPException(404, f"{p.name} not produced yet")
    return json.loads(p.read_text())


def _strip_runs(d: dict[str, Any], keep_runs: bool) -> dict[str, Any]:
    if keep_runs:
        return d
    return {k: v for k, v in d.items() if k != "runs"}


@router.get("/index")
def index() -> dict[str, Any]:
    files = sorted(p.name for p in OUT.glob("*.json")) if OUT.exists() else []
    specs = {}
    for name in (
        "volatility_diagnosis_v1.json",
        "observatory_experiments_v1.json",
        "realism_track_v1.json",
        "realism_track_v2.json",
    ):
        p = FROZEN / name
        if p.exists():
            specs[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {
        "artifacts": files,
        "frozen_specs_sha256": specs,
        "label": "SYNTHETIC simulator research; no trading claims",
    }


@router.get("/audit")
def audit() -> dict[str, Any]:
    return _read(OUT / "audit.json")


@router.get("/volatility")
def volatility(runs: bool = False) -> dict[str, Any]:
    spec = _read(FROZEN / "volatility_diagnosis_v1.json")
    reports = {
        p.stem.removeprefix("volatility_"): _strip_runs(json.loads(p.read_text()), runs)
        for p in sorted(OUT.glob("volatility_*.json"))
    }
    return {"protocol": spec, "reports": reports}


@router.get("/experiments")
def experiments(runs: bool = False) -> dict[str, Any]:
    rep = _read(OUT / "experiments_v1.json")
    return {"protocol": _read(FROZEN / "observatory_experiments_v1.json"), "report": _strip_runs(rep, runs)}


@router.get("/realism")
def realism(runs: bool = False) -> dict[str, Any]:
    from ..observatory.realism import VERSION

    return {
        "version": VERSION,
        "rules": _read(FROZEN / f"realism_track_{VERSION}.json"),
        "report": _strip_runs(_read(OUT / f"realism_{VERSION}.json"), runs),
        "archive": _read(OUT / f"realism_archive_{VERSION}.json"),
    }
