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
        "cascade_c2_v1.json",
        "cascade_c2x_v1.json",
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


CASCADE_FILES = {
    "confirmatory": "cascade_c2_confirmatory.json",
    "pilot": "cascade_c2_pilot.json",
    "exploratory": "cascade_c2x_exploratory.json",
}


def _cascade(role: str) -> dict[str, Any]:
    if role not in CASCADE_FILES:
        raise HTTPException(404, "unknown role")
    return _read(OUT / CASCADE_FILES[role])


@router.get("/cascade")
def cascade() -> dict[str, Any]:
    """C2 summary: protocols (with amendments), per-configuration results, threshold, X1/X2, run index."""
    out: dict[str, Any] = {
        "protocol": _read(FROZEN / "cascade_c2_v1.json"),
        "protocol_exploratory": _read(FROZEN / "cascade_c2x_v1.json"),
    }
    for role, name in CASCADE_FILES.items():
        p = OUT / name
        if not p.exists():
            out[role] = None
            continue
        d = json.loads(p.read_text())
        runs = d.pop("runs", [])
        d["run_index"] = [
            {
                k: r[k]
                for k in (
                    "config",
                    "arm",
                    "seed",
                    "role",
                    "whale_btc",
                    "leverage_use",
                    "run_fingerprint",
                    "config_fingerprint",
                )
            }
            for r in runs
        ]
        out[role] = d
    return out


@router.get("/cascade/pair")
def cascade_pair(config: str, seed: int, role: str = "confirmatory") -> dict[str, Any]:
    """Both arms of one paired run: trajectories, event traces, propagation, margin distribution."""
    runs = _cascade(role).get("runs", [])
    arms = {r["arm"]: r for r in runs if r["config"] == config and r["seed"] == seed}
    if set(arms) != {"A", "B"}:
        raise HTTPException(404, "pair not found")
    return {
        "config": config,
        "seed": seed,
        "role": role,
        "arms": {k: {kk: vv for kk, vv in v.items() if kk != "trade_hashes_from_shock"} for k, v in arms.items()},
    }


@router.get("/knowledge")
def knowledge() -> dict[str, Any]:
    return _read(OUT / "knowledge_c2.json")
