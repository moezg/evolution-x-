"""Read-only API for the forecasting laboratory (backtest report, series, ledger, prospective scores, evolution)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

OUT = Path("artifacts/forecast")
router = APIRouter(prefix="/api/forecast")


def _read(p: Path) -> Any:
    if not p.exists():
        raise HTTPException(404, f"{p.name} not produced yet")
    return json.loads(p.read_text())


@router.get("/protocol")
def protocol() -> dict[str, Any]:
    return _read(Path("evals/frozen/forecast_protocol_v1.json"))


@router.get("/backtest")
def backtest() -> dict[str, Any]:
    d = _read(OUT / "backtest_v1.json")
    d.pop("series", None)
    return d


@router.get("/series")
def series(target: str) -> dict[str, Any]:
    d = _read(OUT / "backtest_v1.json")
    s = d.get("series", {}).get(target)
    if s is None:
        raise HTTPException(404, "unknown target")
    return {"target": target, "label": d.get("label"), **s}


@router.get("/ledger")
def ledger(limit: int = 500) -> dict[str, Any]:
    from ..forecast.ledger import ForecastLedger

    led = ForecastLedger()
    entries = led.entries()[-limit:]
    return {"verify": led.verify(), "entries": entries, "open": len(led.open_forecasts())}


@router.get("/prospective")
def prospective() -> dict[str, Any]:
    from ..forecast.prospective import score

    return score()


@router.get("/evolution")
def evolution() -> dict[str, Any]:
    return _read(OUT / "evolution_v1.json")
