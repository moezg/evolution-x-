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


def issue_challengers(now: dt.datetime | None = None) -> dict[str, Any]:
    """Prospective challengers for F-FCAST features with status 'candidate_feature' (never replaces the champion).

    Same domain, lag, training labels and abstention fallback as the champion; the challenger is M1 + feature,
    written to the forecast ledger (experimental=True) BEFORE the origin. Promotion still needs >= 180 resolved
    forecasts per target, a CI below 0 vs the champion and human approval (forecast protocol v1).
    """
    import json
    import math
    from pathlib import Path

    from ..forecast.backtest import code_version
    from ..forecast.backtest import protocol_sha as fsha
    from ..forecast.data import load_bars
    from ..forecast.domain import DAY, FEATURES
    from ..forecast.ledger import ForecastLedger, forecast_id
    from ..forecast.models import make

    p = Path("artifacts/quant/latest_forecast_link.json")
    if not p.exists():
        return {"issued": 0, "why": "no forecast-link results"}
    cand = [
        k for k, v in json.loads(p.read_text())["results"].items() if str(v["status"]).startswith("candidate_feature")
    ]
    now = now or dt.datetime.now(dt.UTC)
    now_ms = int(now.timestamp() * 1000)
    bars = load_bars()
    dom = BTCDomain(bars)
    as_of = dom.end_ms
    origin = (now_ms // DAY + 1) * DAY
    tmap = {t.name: t for t in dom.targets()}
    origins = np.array(dom.origins("2020-02-01", dt.datetime.fromtimestamp(as_of / 1000, dt.UTC).strftime("%Y-%m-%d")))
    X = np.array([[dom.features(o)[k] for k in FEATURES] for o in origins])
    feats_now = dom.features(origin, as_of=as_of)
    x_now = np.array([feats_now[k] for k in FEATURES])
    led = ForecastLedger()
    version = f"{code_version()}+{fsha()[:12]}+quant:{protocol_sha()[:12]}"
    out = []
    for key in cand:
        _, fname, tname = key.split(":")
        t = tmap[tname]
        col = features(origins, t.horizon_h)[fname]
        f_now = features(np.array([origin]), t.horizon_h)[fname][0]
        y = np.array([np.nan if (v := dom.outcome(t, o)) is None else v for o in origins])
        lab = (origins + t.horizon_h * HOUR <= as_of) & np.isfinite(y) & np.all(np.isfinite(X), axis=1)
        Xa = np.c_[X, col]
        mod = make("M1_logistic")
        mod.fit(Xa[lab], y[lab], t)
        b0 = make("B0_climatology")
        b0.fit(Xa[lab], y[lab], t)
        val = mod.predict(np.r_[x_now, f_now], t, dom.sigma_h(feats_now, t.horizon_h))
        model = f"CH:{fname}"
        fid = forecast_id(dom.name, t.name, model, origin, version)
        if fid in led.forecasts():
            out.append({"target": t.name, "model": model, "skipped": "already issued"})
            continue
        fallback = b0.predict(x_now, t, 0.0)
        ok = math.isfinite(val)
        rec = {
            "id": fid, "domain": dom.name, "target": t.name, "kind": t.kind, "horizon_h": t.horizon_h, "model": model,
            "experimental": True, "model_version": version, "origin_ms": origin, "window_end_ms": origin + t.horizon_h * HOUR,
            "as_of_ms": as_of, "lag_h": (origin - as_of) / HOUR, "value": val, "abstained": not ok,
            "abstain_reason": None if ok else "missing_data", "fallback_B0": fallback, "scored_value": val if ok else fallback,
            "training_n": int(lab.sum()), "trailing_skill_source": None,
            "inputs": {"bars_digest": bars.digest(0, len(bars)), "features": {k: round(float(v), 6) for k, v in feats_now.items()}, "extra_feature": {fname: float(f_now)}, "source_test": key},
            "label": "PROSPECTIVE paper forecast - CHALLENGER from quant discovery (never replaces the champion automatically)",
        }  # fmt: skip
        led.issue(rec, now_ms)
        out.append({"target": t.name, "model": model, "value": val, "feature_value": float(f_now)})
    return {"origin_utc": dt.datetime.fromtimestamp(origin / 1000, dt.UTC).isoformat(), "issued": out}
