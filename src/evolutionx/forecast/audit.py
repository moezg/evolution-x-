"""Resolution integrity audit and the prospective error report.

For every forecast (resolved or not):
  * ledger hash chain + order invariants (ForecastLedger.verify)
  * input snapshot: the stored npz re-hashed equals the sha256 recorded at issuance (inputs never rewritten)
  * training inputs: the digest of all bars before the information cutoff, recomputed from today's data, equals the
    recorded bars_digest (detects any later revision of the history the model was trained on)
For every resolution:
  * the outcome recomputed from today's data equals the recorded outcome (reproducibility)
  * the resolved forecast's original record is unchanged (hash chain) and was issued before its origin
The report compares each model with the champion and climatology on the SAME resolved origins/targets; it is
descriptive until the planned looks of challenger_policy_v2 (n is printed everywhere).
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np

from .data import Bars, load_bars
from .domain import BTCDomain
from .ledger import ForecastLedger

CHAMPION = "M1_logistic"


def _loss(target: str, pred: float, y: float) -> float:
    # rv targets are already log(100 * realised vol) (domain.outcome): the registered loss is plain squared error
    # for every target (forecast protocol v1 scoring.sq_err / brier). A second log here was a bug (fixed 2026-11-08).
    return (pred - y) ** 2


def _snapshot_sha(path: str) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    z = np.load(p)
    h = hashlib.sha256()
    for k in ("open_time", "close", "high", "low", "volume"):
        h.update(np.ascontiguousarray(z[k]).tobytes())
    return h.hexdigest()


def _digest_before(bars: Bars, as_of: int) -> str:
    n = int(np.searchsorted(bars.open_time, as_of))
    return bars.digest(0, n)


def audit(ledger: ForecastLedger | None = None, bars: Bars | None = None) -> dict[str, Any]:
    led = ledger or ForecastLedger()
    bars = bars if bars is not None else load_bars()
    dom = BTCDomain(bars)
    targets = {t.name: t for t in dom.targets()}
    fc, rs = led.forecasts(), led.resolutions()
    problems: list[dict[str, Any]] = []
    snap_cache: dict[str, str | None] = {}
    digest_cache: dict[int, str] = {}
    for fid, e in fc.items():
        d = e["data"]
        snap = d.get("input_snapshot") or {}
        if snap.get("path"):
            if snap["path"] not in snap_cache:
                snap_cache[snap["path"]] = _snapshot_sha(snap["path"])
            got = snap_cache[snap["path"]]
            if got != snap.get("sha256"):
                problems.append(
                    {"forecast": fid, "check": "input_snapshot", "recorded": snap.get("sha256"), "now": got}
                )
        rec_digest = (d.get("inputs") or {}).get("bars_digest")
        if rec_digest:
            a = d["as_of_ms"]
            if a not in digest_cache:
                digest_cache[a] = _digest_before(bars, a)
            if digest_cache[a] != rec_digest:
                problems.append(
                    {
                        "forecast": fid,
                        "check": "training_history_digest",
                        "recorded": rec_digest,
                        "now": digest_cache[a],
                    }
                )
        if fid in rs:
            y = rs[fid]["data"]["outcome"]
            again = dom.outcome(targets[d["target"]], d["origin_ms"])
            if again is None or not math.isclose(again, y, rel_tol=0, abs_tol=1e-12):
                problems.append({"forecast": fid, "check": "outcome_reproducible", "recorded": y, "now": again})
    v = led.verify()
    return {
        "ok": v["ok"] and not problems,
        "ledger_verify": v,
        "forecasts_checked": len(fc),
        "resolutions_checked": len(rs),
        "snapshots_checked": len(snap_cache),
        "problems": problems,
    }


def report(ledger: ForecastLedger | None = None) -> dict[str, Any]:
    """Per resolved origin/target: realized outcome and every model's loss; per model: mean loss and mean difference vs
    the champion and vs climatology over the SAME resolved (origin, target) pairs. Descriptive only."""
    led = ledger or ForecastLedger()
    fc, rs = led.forecasts(), led.resolutions()
    cells: dict[tuple[int, str], dict[str, Any]] = {}
    for fid, r in rs.items():
        d = fc[fid]["data"]
        c = cells.setdefault((d["origin_ms"], d["target"]), {"outcome": r["data"]["outcome"], "models": {}})
        c["models"][d["model"]] = {"scored": d["scored_value"], "loss": _loss(d["target"], d["scored_value"], r["data"]["outcome"]), "abstained": d["abstained"]}  # fmt: skip
    by_model: dict[tuple[str, str], dict[str, list[float]]] = {}
    for (_, tgt), c in cells.items():
        champ = c["models"].get(CHAMPION)
        clim = c["models"].get("B0_climatology")
        for m, x in c["models"].items():
            s = by_model.setdefault((tgt, m), {"loss": [], "vs_champion": [], "vs_climatology": []})
            s["loss"].append(x["loss"])
            if champ:
                s["vs_champion"].append(x["loss"] - champ["loss"])
            if clim:
                s["vs_climatology"].append(x["loss"] - clim["loss"])
    summary = {
        f"{t}:{m}": {
            "n": len(v["loss"]),
            "mean_loss": float(np.mean(v["loss"])),
            "mean_diff_vs_champion": float(np.mean(v["vs_champion"])) if v["vs_champion"] else None,
            "mean_diff_vs_climatology": float(np.mean(v["vs_climatology"])) if v["vs_climatology"] else None,
        }
        for (t, m), v in sorted(by_model.items())
    }
    return {
        "resolved_cells": len(cells),
        "cells": [{"origin_ms": o, "target": t, **c} for (o, t), c in sorted(cells.items())],
        "summary": summary,
        "label": "DESCRIPTIVE: prospective outcomes so far; no skill claim before the planned looks (challenger_policy_v2)",
    }
