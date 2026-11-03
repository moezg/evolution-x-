"""Read-only live observation: calibration / skill drift of RESOLVED prospective forecasts (role F3).

Compares each model's prospective Brier skill vs climatology with what the retrospective SCREEN period suggested.
Unresolved forecasts never enter any statistic. A degradation triggers a re-evaluation task; it never trades.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ..forecast import scoring as S
from ..forecast.ledger import ForecastLedger

MIN_RESOLVED = 30
DEGRADE_MARGIN = 0.05  # absolute Brier-skill drop vs the retrospective expectation


def expected_skill(report: Path = Path("artifacts/forecast/backtest_v1.json")) -> dict[str, float]:
    if not report.exists():
        return {}
    d = json.loads(report.read_text())
    out = {}
    for t, v in d["targets"].items():
        if v["kind"] != "binary":
            continue
        for m, s in v["scores"]["SCREEN"].items():
            if isinstance(s, dict) and "brier_skill_vs_B0" in s:
                out[f"{t}:{m}"] = float(s["brier_skill_vs_B0"])
    return out


def check(
    ledger: ForecastLedger | None = None, report: Path = Path("artifacts/forecast/backtest_v1.json")
) -> dict[str, Any]:
    led = ledger or ForecastLedger()
    fc, rs = led.forecasts(), led.resolutions()
    exp = expected_skill(report)
    rows: dict[str, list[tuple[float, float, float]]] = {}
    for fid, r in rs.items():
        d = fc[fid]["data"]
        if d.get("kind") != "binary":
            continue
        rows.setdefault(f"{d['target']}:{d['model']}", []).append(
            (d["scored_value"], r["data"]["outcome"], d["fallback_B0"])
        )
    status: dict[str, Any] = {}
    alerts = []
    for k, v in sorted(rows.items()):
        a = np.array(v)
        if len(a) < MIN_RESOLVED:
            status[k] = {"n": len(a), "state": "insufficient_data"}
            continue
        bs, b0 = S.brier(a[:, 0], a[:, 1]).mean(), S.brier(a[:, 2], a[:, 1]).mean()
        skill = 1 - bs / b0 if b0 > 0 else float("nan")
        rel = S.reliability(a[:, 0], a[:, 1])
        degraded = k in exp and skill < exp[k] - DEGRADE_MARGIN
        status[k] = {
            "n": len(a),
            "skill": skill,
            "expected": exp.get(k),
            "ece": rel["ece"],
            "bias": float(np.mean(a[:, 0] - a[:, 1])),
            "state": "degraded" if degraded else "ok",
        }
        if degraded:
            alerts.append(k)
    return {
        "resolved": len(rs),
        "open": len(led.open_forecasts()),
        "min_resolved_for_assessment": MIN_RESOLVED,
        "status": status,
        "alerts": alerts,
        "verify": led.verify(),
    }
