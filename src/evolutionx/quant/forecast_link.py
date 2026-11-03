"""Discoveries -> Forecasting Engine (G1/E2): incremental skill of calendar/event features, family F-FCAST.

Uses the forecast protocol v1 machinery unchanged (rolling origin, 24 h publication lag, abstention, scoring).
The candidate feature is appended to M1's features through the engine's hybrid slot (H1 = M1 + extra column);
H1 vs M1 is compared on SCREEN (previously exposed data) and DEV with the block bootstrap, Holm over the family.
A feature that does not improve proper scores is not promoted; nothing here changes the issued forecasts.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np

from ..forecast.backtest import build_table, compare, run_target
from ..forecast.domain import HOUR, BTCDomain
from .calendar import protocol_sha
from .events import Registry
from .stats import TestRegistry, holm

TARGETS = ("rv_24", "move3_24", "move5_24")


def features(origins: np.ndarray, horizon_h: int) -> dict[str, np.ndarray]:
    stmts = np.array(
        sorted(
            int(dt.datetime.fromisoformat(e["event_time_utc"]).timestamp() * 1000)
            for e in Registry().current("fomc")
            if e["subcategory"] == "scheduled"
        )
    )
    fomc = np.array([float(np.any((stmts > o) & (stmts <= o + horizon_h * HOUR))) for o in origins])
    sat = np.array([float(dt.datetime.fromtimestamp(o / 1000, dt.UTC).weekday() == 5) for o in origins])
    return {"fomc_in_window": fomc, "saturday_target_day": sat}


def run(run_id: str, reg: TestRegistry | None = None) -> dict[str, Any]:
    reg = reg or TestRegistry()
    dom = BTCDomain(lag_ms=24 * HOUR)
    tab = build_table(dom, "2020-02-01", "2026-10-28", with_sim=False)
    tmap = {t.name: t for t in dom.targets()}
    feats = features(tab["origins"], 24)
    res: dict[str, Any] = {}
    p_screen = {}
    for fname, col in feats.items():
        for tn in TARGETS:
            r = run_target(
                (tmap[tn], {**tab, "sim": col[:, None]}, dom.lag_ms, ("B0_climatology", "M1_logistic", "H1_hybrid"))
            )
            sc, dv = compare(r, "H1_hybrid", "M1_logistic", "SCREEN"), compare(r, "H1_hybrid", "M1_logistic", "DEV")
            k = f"F-FCAST:{fname}:{tn}"
            res[k] = {"SCREEN": sc, "DEV": dv, "feature_rate": float(col.mean())}
            p_screen[k] = sc["p_better"]
    h = holm(p_screen, 0.05)
    for k, v in res.items():
        better = h[k]["reject"] and v["DEV"]["mean"] <= 0
        v["holm"] = h[k]
        v["status"] = "candidate_feature (prospective challenger only)" if better else "not_promoted"
        reg.record(
            {
                "family": "F-FCAST",
                "hypothesis": k,
                "role": "G1",
                "method": "forecast protocol v1 rolling origin; H1(M1+feature) - M1 loss, block bootstrap; Holm over 6",
                "period": "SCREEN",
                "n": v["SCREEN"]["n"],
                "effect": v["SCREEN"]["mean"],
                "ci_lo": v["SCREEN"]["lo"],
                "ci_hi": v["SCREEN"]["hi"],
                "p": v["SCREEN"]["p_better"],
                "p_adj": h[k]["p_adj"],
                "adj_method": "Holm over 6",
                "status": v["status"],
                "protocol_sha": protocol_sha(),
                "run_id": run_id,
                "details": {"DEV": v["DEV"], "label": "SCREEN is previously exposed data: selection evidence only"},
            }
        )
    return {
        "results": res,
        "note": "loss differences are H1 - M1 (negative = the feature helps); Brier for binary targets, MSE of log RV for rv_24",
    }


__all__ = ["dt", "run"]
