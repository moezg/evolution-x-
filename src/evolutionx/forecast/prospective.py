"""Prospective paper-forecasting: issue forecasts before the outcome exists, resolve them later from published data.

issue():   fetch fresh official archives, train every model on all labels observable at as_of, forecast the next
           daily origin (00:00 UTC strictly after now) and write each forecast to the ledger before its window starts.
resolve(): fetch archives again and write outcomes for forecasts whose window has ended and is fully published.
score():   proper scores of resolved prospective forecasts only (the independent evidence), with abstention fallback.
No order is ever sent anywhere; this is paper forecasting.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from . import scoring as S
from . import simfeatures as SF
from .backtest import MIN_TRAIN, OUT, ZMAX, code_version, protocol_sha
from .data import FRESH, HOUR, fetch_fresh, load_bars
from .domain import DAY, FEATURES, BTCDomain
from .ledger import ForecastLedger, forecast_id
from .models import make

MAX_LAG_H = 48  # older data at issue time -> abstain (stale)
PROMOTION_MIN_RESOLVED = 180


def _sim_decision() -> bool:
    p = OUT / "backtest_v1.json"
    if not p.exists():
        return False
    return json.loads(p.read_text()).get("simulator_inclusion", {}).get("decision", "").startswith("KEEP")


def _trailing_skill_from_backtest(target: str, model: str) -> float | None:
    """Abstention rule 4 at issue time: skill of the model's last 180 scored backtest forecasts vs B0."""
    p = OUT / "backtest_v1.json"
    if not p.exists():
        return None
    s = json.loads(p.read_text())["series"].get(target)
    if not s or model not in s["forecast"]:
        return None
    y = np.array([np.nan if v is None else v for v in s["y"]])
    f = np.array([np.nan if v is None else v for v in s["forecast"][model]])
    b = np.array([np.nan if v is None else v for v in s["forecast"]["B0_climatology"]])
    k = np.where(np.isfinite(y) & np.isfinite(f) & np.isfinite(b))[0][-180:]
    if len(k) < 60:
        return None
    loss = S.brier if not target.startswith("rv_") else S.sq_err
    lb = loss(b[k], y[k]).mean()
    return float(1 - loss(f[k], y[k]).mean() / lb) if lb > 0 else None


def issue(now: dt.datetime | None = None, fetch: bool = True, ledger: ForecastLedger | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.UTC)
    now_ms = int(now.timestamp() * 1000)
    manifest: dict[str, Any] = (
        fetch_fresh()
        if fetch
        else json.loads((FRESH / "manifest.json").read_text())
        if (FRESH / "manifest.json").exists()
        else {}
    )
    bars = load_bars()
    dom = BTCDomain(bars)
    as_of = dom.end_ms
    origin = (now_ms // DAY + 1) * DAY
    lag_h = (origin - as_of) / HOUR
    feats = dom.features(origin, as_of=as_of)
    x = np.array([feats[k] for k in FEATURES])
    use_sim = _sim_decision()
    sim_x = None
    if use_sim:
        c = SF.cell(feats)
        cache = SF.ensure({c}) if c else SF.load_cache()
        sim_x = np.array([SF.features_for(feats, cache)[k] for k in SF.SIM_FEATURES])
    led = ledger or ForecastLedger()
    version = f"{code_version()}+{protocol_sha()[:12]}"
    origins = np.array(dom.origins("2020-02-01", dt.datetime.fromtimestamp(as_of / 1000, dt.UTC).strftime("%Y-%m-%d")))
    tabX = np.array([[dom.features(o)[k] for k in FEATURES] for o in origins])
    out = []
    models = ["B0_climatology", "B1_ewma_gauss", "M1_logistic", "M2_gbm"] + (["H1_hybrid"] if use_sim else [])
    for t in dom.targets():
        y = np.array([np.nan if (v := dom.outcome(t, o)) is None else v for o in origins])
        # labels observable at as_of (outcome window fully inside published data)
        lab = (origins + t.horizon_h * HOUR <= as_of) & np.isfinite(y) & np.all(np.isfinite(tabX), axis=1)
        b0 = make("B0_climatology")
        b0.fit(tabX[lab], y[lab], t)
        sig = dom.sigma_h(feats, t.horizon_h)
        for m in models:
            Xtr, xx = tabX, x
            if m == "H1_hybrid" and sim_x is not None:
                tab_sim = np.array(
                    [[SF.features_for(dom.features(o), SF.load_cache())[k] for k in SF.SIM_FEATURES] for o in origins]
                )
                Xtr, xx = np.c_[tabX, tab_sim], np.r_[x, sim_x]
            ok = lab & np.all(np.isfinite(Xtr), axis=1)
            mod = make(m)
            mod.fit(Xtr[ok], y[ok], t)
            val = mod.predict(xx, t, sig)
            reason = None
            if ok.sum() < MIN_TRAIN:
                reason = "insufficient_training"
            elif lag_h > MAX_LAG_H or feats["missing_frac_720"] > 0.05:
                reason = "stale_or_missing_data"
            elif m not in ("B0_climatology", "B1_ewma_gauss"):
                mu, sd = Xtr[ok].mean(0), Xtr[ok].std(0)
                z = (xx - mu) / np.where(sd > 0, sd, 1)
                if not np.all(np.isfinite(z)) or np.max(np.abs(z)) > ZMAX:
                    reason = "out_of_range"
            if reason is None and m != "B0_climatology":
                ts = _trailing_skill_from_backtest(t.name, m)
                if ts is not None and ts < 0:
                    reason = "negative_trailing_skill"
            if not math.isfinite(val):
                reason = reason or "missing_data"
            fallback = b0.predict(xx, t, sig)
            rec = {
                "id": forecast_id(dom.name, t.name, m, origin, version),
                "domain": dom.name,
                "target": t.name,
                "kind": t.kind,
                "horizon_h": t.horizon_h,
                "model": m,
                "experimental": m == "H1_hybrid",
                "model_version": version,
                "origin_ms": origin,
                "window_end_ms": origin + t.horizon_h * HOUR,
                "as_of_ms": as_of,
                "lag_h": lag_h,
                "value": val,
                "abstained": reason is not None,
                "abstain_reason": reason,
                "fallback_B0": fallback,
                "scored_value": fallback if reason else val,
                "training_n": int(ok.sum()),
                "inputs": {
                    "bars_digest": bars.digest(0, len(bars)),
                    "n_bars": len(bars),
                    "last_bar_open_ms": int(bars.open_time[-1]),
                    "fresh_archives": [f["day"] for f in manifest.get("files", [])],
                    "features": {k: round(float(v), 6) for k, v in feats.items()},
                    "sim_features": None if sim_x is None else [float(v) for v in sim_x],
                },
                "label": "PROSPECTIVE paper forecast",
            }
            led.issue(rec, now_ms)
            out.append({k: rec[k] for k in ("target", "model", "value", "abstained", "abstain_reason", "scored_value")})
    return {
        "origin_utc": dt.datetime.fromtimestamp(origin / 1000, dt.UTC).isoformat(),
        "as_of_utc": dt.datetime.fromtimestamp(as_of / 1000, dt.UTC).isoformat(),
        "lag_h": lag_h,
        "simulator_features_used": use_sim,
        "forecasts": out,
    }


def resolve(now: dt.datetime | None = None, fetch: bool = True, ledger: ForecastLedger | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.UTC)
    if fetch:
        fetch_fresh()
    dom = BTCDomain(load_bars())
    led = ledger or ForecastLedger()
    targets = {t.name: t for t in dom.targets()}
    done, pending = [], []
    manifest = json.loads((FRESH / "manifest.json").read_text()) if (FRESH / "manifest.json").exists() else {}
    for e in led.open_forecasts():
        d = e["data"]
        if d["window_end_ms"] > dom.end_ms:
            pending.append(d["id"])
            continue
        v = dom.outcome(targets[d["target"]], d["origin_ms"])
        if v is None:
            pending.append(d["id"])
            continue
        led.resolve(
            d["id"], v, {"archives": manifest.get("files", []), "bars_end_ms": dom.end_ms}, int(now.timestamp() * 1000)
        )
        done.append(d["id"])
    return {"resolved": len(done), "pending": len(pending)}


def score(ledger: ForecastLedger | None = None) -> dict[str, Any]:
    led = ledger or ForecastLedger()
    fc, rs = led.forecasts(), led.resolutions()
    by: dict[tuple[str, str], list[tuple[float, float, float]]] = {}
    for fid, r in rs.items():
        d = fc[fid]["data"]
        by.setdefault((d["target"], d["model"]), []).append((d["scored_value"], r["data"]["outcome"], d["fallback_B0"]))
    out = {}
    for (t, m), rows in sorted(by.items()):
        a = np.array(rows)
        s = (
            S.summarize_binary(a[:, 0], a[:, 1], a[:, 2])
            if not t.startswith("rv_")
            else S.summarize_rv(a[:, 0], a[:, 1], a[:, 2])
        )
        s["promotion_evidence_sufficient"] = len(rows) >= PROMOTION_MIN_RESOLVED
        out[f"{t}:{m}"] = s
    open_n = len(led.open_forecasts())
    return {
        "resolved": len(rs),
        "open": open_n,
        "scores": out,
        "verify": led.verify(),
        "label": "PROSPECTIVE (independent) evidence",
    }


def status_path() -> Path:
    return OUT / "prospective_status.json"
