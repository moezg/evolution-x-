"""Strict rolling-origin backtest (protocol: evals/frozen/forecast_protocol_v1.json).

At each daily origin o a model may only use (a) features from bars complete before o - lag and (b) training labels
whose outcome window ended before o - lag. Refit every 30 origins on an expanding window. Abstentions are scored
as the B0 climatology forecast. Retrospective results are labelled by exposure period; none is independent.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from . import scoring as S
from . import simfeatures as SF
from .domain import FEATURES, HOUR, BTCDomain, Target
from .models import make

PROTOCOL = Path("evals/frozen/forecast_protocol_v1.json")
OUT = Path("artifacts/forecast")
MODELS = ("B0_climatology", "B1_ewma_gauss", "M1_logistic", "M2_gbm", "H1_hybrid")
PERIODS = {
    "DEV": ("2021-01-01", "2023-12-31"),
    "SCREEN": ("2024-01-01", "2025-06-28"),
    "CONSUMED": ("2025-07-01", "2026-10-28"),
}
LABELS = {
    "DEV": "retrospective, free exploration",
    "SCREEN": "retrospective, previously exposed (screening only)",
    "CONSUMED": "retrospective, CONSUMED split (never fresh validation)",
}
MIN_TRAIN, REFIT, TRAIL, ZMAX = 365, 30, 180, 6.0


def code_version() -> str:
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob("*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def protocol_sha() -> str:
    return hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()


def _ms(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC).timestamp() * 1000)


def build_table(dom: BTCDomain, start: str, end: str, with_sim: bool) -> dict[str, Any]:
    origins = dom.origins(start, end)
    feats = [dom.features(o) for o in origins]
    X = np.array([[f[k] for k in FEATURES] for f in feats])
    miss = np.array([f["missing_frac_720"] for f in feats])
    sim = None
    if with_sim:
        cells = {c for f in feats if (c := SF.cell(f)) is not None}
        cache = SF.ensure(cells)
        sim = np.array([[SF.features_for(f, cache)[k] for k in SF.SIM_FEATURES] for f in feats])
    ys = {t.name: np.array([np.nan if (v := dom.outcome(t, o)) is None else v for o in origins]) for t in dom.targets()}
    sig = {
        h: np.array([dom.sigma_h(f, h) if math.isfinite(f["lsig_ewma"]) else np.nan for f in feats]) for h in (24, 72)
    }
    digests = [
        dom.bars.digest(
            0, int(np.searchsorted(dom.bars.open_time, f["as_of_ms"] if math.isfinite(f["as_of_ms"]) else 0))
        )
        for f in feats[-3:]
    ]
    return {
        "origins": np.array(origins),
        "X": X,
        "sim": sim,
        "missing": miss,
        "y": ys,
        "sigma": sig,
        "digest_tail": digests,
    }


def _abstain_reason(n_train: int, missing: float, z: np.ndarray | None, trailing_skill: float | None) -> str | None:
    if n_train < MIN_TRAIN:
        return "insufficient_training"
    if not math.isfinite(missing) or missing > 0.05:
        return "missing_data"
    if z is not None and (not np.all(np.isfinite(z)) or np.max(np.abs(z)) > ZMAX):
        return "out_of_range"
    if trailing_skill is not None and trailing_skill < 0:
        return "negative_trailing_skill"
    return None


def run_target(args: tuple[Target, dict[str, Any], int, tuple[str, ...]]) -> dict[str, Any]:
    target, tab, lag_ms, models = args
    o = tab["origins"]
    y = tab["y"][target.name]
    X = tab["X"]
    Xh = np.c_[X, tab["sim"]] if tab["sim"] is not None else None
    sig = tab["sigma"][target.horizon_h]
    avail = o + target.horizon_h * HOUR + lag_ms  # time at which each origin's label is observable
    n = len(o)
    preds = {m: np.full(n, np.nan) for m in models}
    raw = {m: np.full(n, np.nan) for m in models}
    reason: dict[str, list[str | None]] = {m: [None] * n for m in models}
    fitted: dict[str, Any] = {}
    last_fit = -(10**9)
    for i in range(n):
        tr = np.where((avail <= o[i]) & np.isfinite(y))[0]
        refit = i - last_fit >= REFIT
        for m in models:
            Xm = Xh if m == "H1_hybrid" else X
            if m.startswith("CAND:"):
                Xm = X[:, [FEATURES.index(f) for f in json.loads(m[5:])["features"]]]
            if Xm is None:
                continue
            ok = tr[np.all(np.isfinite(Xm[tr]), axis=1)] if m not in ("B0_climatology", "B1_ewma_gauss") else tr
            if (refit or m not in fitted) and len(ok) >= 30:
                mod = make(m)
                mod.fit(Xm[ok], y[ok], target)
                fitted[m] = (mod, len(ok))
            if m not in fitted:
                reason[m][i] = "insufficient_training"
                continue
            mod, n_tr = fitted[m]
            x = Xm[i]
            if m in ("B0_climatology", "B1_ewma_gauss"):
                z = None if m == "B0_climatology" else np.array([sig[i]])
                val = (
                    mod.predict(x, target, float(sig[i]))
                    if (m == "B0_climatology" or math.isfinite(sig[i]))
                    else float("nan")
                )
            else:
                z = mod.std(x[None, :])[0] if hasattr(mod, "std") else None
                if z is None:  # GBM: standardize with training statistics for the range check
                    mu, sd = Xm[ok].mean(0), Xm[ok].std(0)
                    z = (x - mu) / np.where(sd > 0, sd, 1)
                val = mod.predict(x, target, float(sig[i])) if np.all(np.isfinite(x)) else float("nan")
            raw[m][i] = val
            # trailing skill of this model's own resolved forecasts (known at o[i]) vs B0
            ts = None
            if m != "B0_climatology":
                k = np.where(
                    (avail <= o[i]) & np.isfinite(raw[m]) & np.isfinite(raw["B0_climatology"]) & np.isfinite(y)
                )[0][-TRAIL:]
                if len(k) >= 60:
                    loss = S.brier if target.kind == "binary" else S.sq_err
                    lm, lb = loss(raw[m][k], y[k]).mean(), loss(raw["B0_climatology"][k], y[k]).mean()
                    ts = 1 - lm / lb if lb > 0 else None
            r = _abstain_reason(n_tr, float(tab["missing"][i]), z, ts)
            if m == "B0_climatology" and r == "negative_trailing_skill":
                r = None
            if not math.isfinite(val):
                r = r or "missing_data"
            reason[m][i] = r
            preds[m][i] = val
        if refit:
            last_fit = i
    # fallback: abstained or missing forecasts are scored as B0
    b0 = preds["B0_climatology"]
    scored = {m: np.where([reason[m][i] is None for i in range(n)], preds[m], b0) for m in models}
    return {"target": target, "raw": raw, "scored": scored, "reason": reason, "y": y, "origins": o}


def _period_mask(o: np.ndarray, p: str) -> np.ndarray:
    a, b = PERIODS[p]
    return (o >= _ms(a)) & (o <= _ms(b))


def evaluate(res: dict[str, Any], models: tuple[str, ...]) -> dict[str, Any]:
    t: Target = res["target"]
    y, o = res["y"], res["origins"]
    out: dict[str, Any] = {}
    for p in PERIODS:
        m = _period_mask(o, p) & np.isfinite(y) & np.isfinite(res["scored"]["B0_climatology"])
        per: dict[str, Any] = {"label": LABELS[p], "n": int(m.sum())}
        for mod in models:
            f = res["scored"][mod][m]
            if not np.all(np.isfinite(f)):
                continue
            s = (
                S.summarize_binary(f, y[m], res["scored"]["B0_climatology"][m])
                if t.kind == "binary"
                else S.summarize_rv(f, y[m], res["scored"]["B0_climatology"][m])
            )
            s["coverage"] = float(np.mean([res["reason"][mod][i] is None for i in np.where(m)[0]]))
            s["abstentions"] = {
                r: sum(res["reason"][mod][i] == r for i in np.where(m)[0])
                for r in {res["reason"][mod][i] for i in np.where(m)[0]}
                if r
            }
            per[mod] = s
        out[p] = per
    return out


def compare(res: dict[str, Any], a: str, b: str, period: str) -> dict[str, float]:
    t: Target = res["target"]
    y, o = res["y"], res["origins"]
    m = _period_mask(o, period) & np.isfinite(y) & np.isfinite(res["scored"][a]) & np.isfinite(res["scored"][b])
    loss = S.brier if t.kind == "binary" else S.sq_err
    d = loss(res["scored"][a][m], y[m]) - loss(res["scored"][b][m], y[m])
    return S.block_bootstrap_mean(d)


def run(with_sim: bool = True, workers: int = 4, models: tuple[str, ...] = MODELS) -> dict[str, Any]:
    t0 = time.perf_counter()
    version = code_version()  # captured before running: describes the code that produced the results
    dom = BTCDomain(lag_ms=24 * HOUR)
    tab = build_table(dom, "2020-02-01", "2026-10-28", with_sim)
    if not with_sim:
        models = tuple(m for m in models if m != "H1_hybrid")
    jobs = [(t, tab, dom.lag_ms, models) for t in dom.targets()]
    with ProcessPoolExecutor(workers) as ex:
        results = list(ex.map(run_target, jobs))
    report: dict[str, Any] = {"targets": {}}
    pvals: dict[str, float] = {}
    comps: dict[str, Any] = {}
    for res in results:
        t = res["target"]
        report["targets"][t.name] = {"kind": t.kind, "horizon_h": t.horizon_h, "scores": evaluate(res, models)}
        pairs = (
            [("M1_logistic", "B1_ewma_gauss")]
            if t.kind == "rv"
            else [("M1_logistic", "B0_climatology"), ("M1_logistic", "B1_ewma_gauss"), ("M2_gbm", "B0_climatology")]
        )
        if "H1_hybrid" in models:
            pairs.append(("H1_hybrid", "M1_logistic"))
        for a, b in pairs:
            key = f"{t.name}:{a}-vs-{b}"
            comps[key] = {p: compare(res, a, b, p) for p in PERIODS}
            if t.kind == "binary":
                pvals[key] = comps[key]["SCREEN"]["p_better"]
    # registered rv family: M1 vs B1 at both horizons only (H1 rv comparisons are reported, not in this family)
    rv_p = {k: v["SCREEN"]["p_better"] for k, v in comps.items() if k.startswith("rv_") and "M1_logistic-vs-B1" in k}
    report["comparisons"] = comps
    report["holm_binary_SCREEN"] = S.holm(pvals)
    report["holm_rv_SCREEN"] = S.holm(rv_p)
    report["simulator_inclusion"] = (
        _sim_rule(comps, report["holm_binary_SCREEN"]) if "H1_hybrid" in models else {"decision": "not evaluated"}
    )
    report["series"] = {
        r["target"].name: {
            "origins": [int(x) for x in r["origins"]],
            "y": [None if not math.isfinite(v) else float(v) for v in r["y"]],
            "forecast": {
                m: [None if not math.isfinite(v) else round(float(v), 5) for v in r["scored"][m]] for m in models
            },
            "raw": {m: [None if not math.isfinite(v) else round(float(v), 5) for v in r["raw"][m]] for m in models},
            "note": "forecast = scored value (B0 fallback where abstained); raw = the model's own output",
            "abstained": {m: [r["reason"][m][i] for i in range(len(r["origins"]))] for m in models},
        }
        for r in results
    }
    report.update(
        {
            "protocol": "forecast-protocol-v1",
            "protocol_sha256": protocol_sha(),
            "code_version": version,
            "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "lag_h": dom.lag_ms // HOUR,
            "data_end_utc": dt.datetime.fromtimestamp(dom.end_ms / 1000, dt.UTC).isoformat(),
            "simulator": SF.info() if with_sim else None,
            "label": "RETROSPECTIVE rolling-origin backtest on previously seen data: exploratory/screening evidence only",
            "cost": {"wall_s": round(time.perf_counter() - t0, 1), "llm_calls": 0},
        }
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "backtest_v1.json").write_text(json.dumps(report, default=float))
    return report


def _sim_rule(comps: dict[str, Any], holm: dict[str, Any]) -> dict[str, Any]:
    keep = []
    for k, v in comps.items():
        if "H1_hybrid-vs-M1_logistic" not in k or k.startswith("rv_"):
            continue
        if holm.get(k, {}).get("reject_null") and v["DEV"]["mean"] <= 0:
            keep.append(k.split(":")[0])
    return {
        "rule": "keep only if H1 beats M1 on SCREEN after Holm and is not worse on DEV",
        "targets_where_sim_helps": keep,
        "decision": "KEEP for " + ", ".join(keep)
        if keep
        else "EXCLUDE simulator features from all non-experimental models",
    }
