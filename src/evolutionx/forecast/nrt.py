"""Protocol v2 near-real-time (NRT) challenger track (evals/frozen/forecast_protocol_v2_nrt.json).

CH:nrt_spot_M1 = the v1 champion model class (M1, same features, same abstention rules) fed with Binance SPOT 1h bars
that closed by as_of = origin - 2 h, predicting the SAME perpetual targets as v1. History comes from the official
spot archives already stored (data/quant/binance/1h); the latest hours from the official public market-data endpoint,
whose raw responses are stored with their sha256. v1 is not changed in any way.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from .backtest import MIN_TRAIN, ZMAX, code_version
from .data import HOUR, Bars
from .domain import DAY, FEATURES, BTCDomain
from .ledger import ForecastLedger, forecast_id
from .models import make

PROTOCOL = Path("evals/frozen/forecast_protocol_v2_nrt.json")
API = "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&startTime={a}&limit=1000"
RAW = Path("data/nrt/api")
SNAP = Path("artifacts/forecast/snapshots")
MODEL = "CH:nrt_spot_M1"
CUTOFF_H = 2
TARGETS = ("rv_24", "move3_24")


def protocol_sha() -> str:
    return hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()


def fetch_recent(start_ms: int, now_ms: int) -> tuple[list[tuple[int, float, float, float, float]], str]:
    """Closed spot 1h bars from start_ms (official public endpoint); the raw response is stored with its sha256."""
    r = httpx.get(API.format(a=start_ms), timeout=30)
    r.raise_for_status()
    RAW.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(r.content).hexdigest()
    (RAW / f"klines_{now_ms}_{sha[:12]}.json").write_bytes(r.content)
    rows = [(int(k[0]), float(k[4]), float(k[2]), float(k[3]), float(k[5])) for k in r.json() if int(k[6]) < now_ms]
    return rows, sha


def spot_bars(recent: list[tuple[int, float, float, float, float]]) -> Bars:
    from ..quant.data import load_btc

    s = load_btc("1h")
    assert s.high is not None and s.low is not None and s.volume is not None  # 1h archives carry OHLCV
    rows = {int(t): (float(c), float(h), float(lo), float(v)) for t, c, h, lo, v in zip(s.t, s.close, s.high, s.low, s.volume, strict=True)}  # fmt: skip
    for t, c, h, lo, v in recent:
        if t in rows and abs(rows[t][0] - c) > 1e-9:
            raise ValueError(f"spot archive and API disagree at {t}")
        rows[t] = (c, h, lo, v)
    t = np.array(sorted(rows), dtype=np.int64)
    a = np.array([rows[x] for x in t])
    return Bars(t, a[:, 0], a[:, 1], a[:, 2], a[:, 3], np.zeros(len(t), dtype=int))


def issue_nrt(
    now: dt.datetime, origin_ms: int, ledger: ForecastLedger | None = None, recent: Any = None
) -> dict[str, Any]:
    from .challengers import active, retired
    from .prospective import FEATURE_VERSION

    now_ms = int(now.timestamp() * 1000)
    as_of = origin_ms - CUTOFF_H * HOUR
    if now_ms >= origin_ms:
        raise ValueError("issuance deadline passed (no backfill)")
    if now_ms < as_of:
        raise ValueError("cutoff not reached yet")
    if recent is None:
        rows, api_sha = fetch_recent(as_of - 40 * DAY, now_ms)
    else:
        rows, api_sha = recent
    spot = spot_bars(rows)
    spot = Bars(*(getattr(spot, f)[spot.open_time + HOUR <= as_of] for f in ("open_time", "close", "high", "low", "volume", "source")))  # fmt: skip
    fresh = len(spot) > 0 and int(spot.open_time[-1]) == as_of - HOUR
    dom_s = BTCDomain(bars=spot, lag_ms=CUTOFF_H * HOUR)
    dom_p = BTCDomain(lag_ms=24 * HOUR)  # registered perpetual targets (labels)
    led = ledger or ForecastLedger()
    have = {(e["data"]["origin_ms"], e["data"]["target"], e["data"]["model"]) for e in led.forecasts().values()}
    lo_i = int(np.searchsorted(spot.open_time, as_of - 31 * DAY))
    SNAP.mkdir(parents=True, exist_ok=True)
    snap_path = SNAP / f"btc_spot_nrt_{origin_ms}.npz"
    arrs = {k: getattr(spot, k)[lo_i:] for k in ("open_time", "close", "high", "low", "volume")}
    if not snap_path.exists():
        np.savez_compressed(snap_path, **arrs)
    h = hashlib.sha256()
    for k in ("open_time", "close", "high", "low", "volume"):
        h.update(np.ascontiguousarray(arrs[k]).tobytes())
    snap = {"path": str(snap_path), "sha256": h.hexdigest(), "bars": len(arrs["close"]), "as_of_ms": as_of}
    feats = dom_s.features(origin_ms, as_of=as_of)
    x = np.array([feats[k] for k in FEATURES])
    origins = np.array(dom_p.origins("2020-02-01", dt.datetime.fromtimestamp((origin_ms - 2 * DAY) / 1000, dt.UTC).strftime("%Y-%m-%d")))  # fmt: skip
    X = np.array([[dom_s.features(int(o))[k] for k in FEATURES] for o in origins])
    version = f"{code_version()}+nrt:{protocol_sha()[:12]}"
    out = []
    for t in dom_p.targets():
        if t.name not in TARGETS:
            continue
        if (origin_ms, t.name, MODEL) in have or not active(MODEL, t.name) or retired(MODEL, t.name):
            out.append({"target": t.name, "skipped": "already issued / not activated / retired"})
            continue
        y = np.array([np.nan if (v := dom_p.outcome(t, int(o))) is None else v for o in origins])
        lab = (origins + t.horizon_h * HOUR + 24 * HOUR <= now_ms) & np.isfinite(y)  # labels observable now
        ok = lab & np.all(np.isfinite(X), axis=1)
        b0 = make("B0_climatology")
        b0.fit(X[lab], y[lab], t)
        sig = dom_s.sigma_h(feats, t.horizon_h)
        m = make("M1_logistic")
        m.fit(X[ok], y[ok], t)
        val = m.predict(x, t, sig)
        mu, sd = X[ok].mean(0), X[ok].std(0)
        z = (x - mu) / np.where(sd > 0, sd, 1)
        reason = None
        if ok.sum() < MIN_TRAIN:
            reason = "insufficient_training"
        elif not fresh or feats["missing_frac_720"] > 0.05:
            reason = "stale_or_missing_data"
        elif not np.all(np.isfinite(z)) or np.max(np.abs(z)) > ZMAX:
            reason = "out_of_range"
        if not math.isfinite(val):
            reason = reason or "missing_data"
        fb = b0.predict(x, t, sig)
        rec = {
            "id": forecast_id(dom_p.name, t.name, MODEL, origin_ms, version), "domain": dom_p.name, "target": t.name,
            "kind": t.kind, "horizon_h": t.horizon_h, "model": MODEL, "experimental": True, "model_version": version,
            "origin_ms": origin_ms, "window_end_ms": origin_ms + t.horizon_h * HOUR, "as_of_ms": as_of,
            "lag_h": CUTOFF_H, "value": val, "abstained": reason is not None, "abstain_reason": reason,
            "fallback_B0": fb, "scored_value": fb if reason else val, "training_n": int(ok.sum()),
            "feature_version": FEATURE_VERSION, "input_snapshot": snap,
            "inputs": {"source": "Binance spot 1h (archives + data-api.binance.vision)", "api_response_sha256": api_sha,
                       "spot_digest": spot.digest(0, len(spot)), "last_bar_open_ms": int(spot.open_time[-1]) if len(spot) else None,
                       "features": {k: round(float(v), 6) for k, v in feats.items()}},
            "label": "PROSPECTIVE challenger, protocol v2 near-real-time track (never replaces the champion automatically)",
        }  # fmt: skip
        led.issue(rec, now_ms)
        out.append({"target": t.name, "value": val, "abstained": reason is not None, "reason": reason})
    return {"origin_utc": dt.datetime.fromtimestamp(origin_ms / 1000, dt.UTC).isoformat(), "as_of_ms": as_of, "fresh": fresh, "issued": out}  # fmt: skip
