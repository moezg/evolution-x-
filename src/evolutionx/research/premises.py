"""Premise verification (TRUSTED): reject hypotheses built on false technical or empirical premises BEFORE any
costly backtest.

Three sources of truth, all computed from the real project state, never from a description:
  1. ENGINE FEATURES: each feature is proven by an executable micro-probe on synthetic bars (e.g. the rebalance
     band: a 2% target change must produce no fill). The registry also records where the feature lives in code.
  2. STRATEGY API: the public methods of BarView, from introspection.
  3. PARENT BEHAVIOUR: metrics measured by replaying the parent's cached development decisions through the engine
     (e.g. which fraction of small target changes is actually executed).

A premise is a structured, checkable claim:
  {"id": "P1", "claim": "...", "check": {"type": "engine_feature", "feature": "rebalance_band", "expect": "absent"}}
  {"id": "P2", "claim": "...", "check": {"type": "parent_metric", "metric": "small_change_execution_ratio",
                                          "symbol": "BTCUSDT", "op": ">", "value": 0.8}}
  {"id": "P3", "claim": "...", "check": {"type": "view_api", "method": "funding", "expect": "present"}}
  {"id": "P4", "claim": "...", "check": {"type": "unverifiable", "reason": "..."}}
Verdict: rejected if any premise is FALSIFIED or malformed, or if no premise is verifiable.
"""

from __future__ import annotations

import hashlib
import inspect
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from ..backtest.engine import CostModel, run_backtest
from ..backtest.interface import BarView

H = 3_600_000
SRC = Path(__file__).resolve().parents[1]


def _bars(n: int, price: float = 100.0, vol: float = 0.0, seed: int = 0, volume: float = 1e9) -> dict:
    rng = np.random.default_rng(seed)
    c = price * np.exp(np.cumsum(rng.normal(0, vol, n))) if vol else np.full(n, price)
    o = np.r_[price, c[:-1]]
    t = np.arange(n, dtype=np.int64) * H
    return {
        "open_time": t,
        "open": o,
        "high": np.maximum(o, c) * 1.0005,
        "low": np.minimum(o, c) * 0.9995,
        "close": c,
        "volume": np.full(n, volume),
        "available_at": t + H,
        "funding": np.zeros(n),
    }


def _cost(**kw: Any) -> CostModel:
    from ..data.datasets import protocol

    base = CostModel.from_protocol(protocol(), "BTCUSDT")
    return CostModel(**{**base.__dict__, **kw})


# ---------------------------------------------------------------- engine feature probes (executable evidence)


def _probe_rebalance_band() -> tuple[bool, str]:
    d = _bars(6)
    dec = np.array([0.5, 0.52, 0.5, 0.52, 0.5, 0.52])  # 2% exposure wiggles after the initial entry
    r = run_backtest(d, dec, _cost())
    fills_after_entry = int((r.fill_notional[2:] > 0).sum())
    band = _cost().rebalance_band
    return fills_after_entry == 0, (
        f"protocol rebalance_band={band}: a 0.02 target wiggle produced "
        f"{fills_after_entry} fills after entry (expected 0)"
    )


def _probe_next_open_execution() -> tuple[bool, str]:
    d = _bars(5)
    d["close"][2] = 200.0
    d["high"][2] = 200.0
    dec = np.array([0.0, 0.0, 1.0, 1.0, 1.0])
    r = run_backtest(d, dec, _cost(rebalance_band=0.0))
    ok = r.position[2] == 0.0 and r.position[3] != 0.0
    return ok, f"decision at bar 2 -> position at bar 2 = {r.position[2]}, bar 3 = {r.position[3]:.4f}"


def _probe_participation_cap() -> tuple[bool, str]:
    d = _bars(4, volume=1.0)
    r = run_backtest(d, np.ones(4), _cost(rebalance_band=0.0, lot_step=1e-6))
    return r.position[
        1
    ] <= 0.02 + 1e-9 and r.unfilled_qty > 0, f"position after 1 bar = {r.position[1]:.4f} BTC with 1 BTC bar volume"


def _probe_funding_charged() -> tuple[bool, str]:
    d = _bars(4)
    d["funding"][:] = 0.001
    r = run_backtest(d, np.ones(4) * 0.5, _cost(rebalance_band=0.0))
    return r.costs["funding"] > 0, f"funding cost charged = {r.costs['funding']:.2f}"


def _probe_fees_on_every_fill() -> tuple[bool, str]:
    d = _bars(4)
    r = run_backtest(d, np.array([0.5, -0.5, 0.5, -0.5]), _cost(rebalance_band=0.0))
    return r.costs["fees"] > 0 and r.n_fills >= 3, f"fills={r.n_fills}, fees={r.costs['fees']:.2f}"


def _probe_flat_exit_bypasses_band() -> tuple[bool, str]:
    d = _bars(4)
    r = run_backtest(d, np.array([0.03, 0.0, 0.0, 0.0]), _cost(rebalance_band=0.05))
    return r.position[2] == 0.0, f"position after a 0 target = {r.position[2]}"


def _probe_liquidation() -> tuple[bool, str]:
    d = _bars(10)
    d["low"][6] = d["open"][6] * 0.3
    r = run_backtest(d, np.ones(10), _cost(rebalance_band=0.0))
    return r.n_liquidations == 1, f"liquidations={r.n_liquidations}"


FEATURES: dict[str, dict[str, Any]] = {
    "rebalance_band": {
        "desc": "trades smaller than rebalance_band x max_leverage x equity are skipped",
        "code": ("backtest/engine.py", r"rebalance_band \* cost\.max_leverage"),
        "probe": _probe_rebalance_band,
    },
    "next_open_execution": {
        "desc": "decision at bar t close executes at bar t+1 open",
        "code": ("backtest/engine.py", r"execute the decision of bar t-1"),
        "probe": _probe_next_open_execution,
    },
    "participation_cap": {
        "desc": "fills capped at participation_limit x bar volume (partial fills)",
        "code": ("backtest/engine.py", r"participation_limit \* v\[t\]"),
        "probe": _probe_participation_cap,
    },
    "funding_charged": {
        "desc": "historical funding charged on positions held at funding times",
        "code": ("backtest/engine.py", r"longs pay positive funding"),
        "probe": _probe_funding_charged,
    },
    "fees_on_every_fill": {
        "desc": "taker fee + half spread + sqrt impact on every fill",
        "code": ("backtest/engine.py", r"impact_bps = cost\.impact_coef_bps"),
        "probe": _probe_fees_on_every_fill,
    },
    "flat_exit_bypasses_band": {
        "desc": "a zero target always closes the position, even below the band",
        "code": ("backtest/engine.py", r"moving_to_flat"),
        "probe": _probe_flat_exit_bypasses_band,
    },
    "worst_case_liquidation": {
        "desc": "maintenance-margin liquidation at the adverse intrabar extreme",
        "code": ("backtest/engine.py", r"intrabar liquidation check"),
        "probe": _probe_liquidation,
    },
}


def code_ref(rel: str, pattern: str) -> dict[str, Any]:
    p = SRC / rel
    text = p.read_text()
    line = next((i for i, ln in enumerate(text.splitlines(), 1) if re.search(pattern, ln)), None)
    return {"file": f"src/evolutionx/{rel}", "line": line, "sha256": hashlib.sha256(text.encode()).hexdigest()}


def feature_registry() -> dict[str, dict[str, Any]]:
    out = {}
    for name, f in FEATURES.items():
        ok, ev = f["probe"]()
        out[name] = {"present": bool(ok), "description": f["desc"], "probe_evidence": ev, "code": code_ref(*f["code"])}
    return out


def view_api() -> list[str]:
    return sorted(n for n, _ in inspect.getmembers(BarView) if not n.startswith("_"))


# ---------------------------------------------------------------- parent behaviour (measured, development only)

PARENT_METRICS = (
    "net_sharpe",
    "gross_sharpe",
    "max_drawdown",
    "turnover_per_year",
    "avg_holding_bars",
    "trading_cost_share",
    "funding_cost_share",
    "exposure_frac",
    "decision_change_rate",
    "small_change_rate",
    "small_change_execution_ratio",
    "fills_per_day",
    "mean_abs_exposure",
    "sharpe_low_vol_tercile",
    "sharpe_high_vol_tercile",
)


def parent_behaviour(data: dict[str, np.ndarray], dec: np.ndarray, cost: CostModel) -> dict[str, Any]:
    """Measured on calendar-year segments with fresh equity (research/behaviour.py)."""
    from .behaviour import behaviour

    return behaviour(data, dec, cost)


# ---------------------------------------------------------------- verification

OPS: dict[str, Callable[[float, float], bool]] = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


def verify(
    premises: list[dict[str, Any]],
    features: dict[str, dict[str, Any]],
    api: list[str],
    parent: dict[str, dict[str, float]],
) -> dict[str, Any]:
    results = []
    for p in premises:
        chk = p.get("check") or {}
        typ = chk.get("type")
        res: dict[str, Any] = {"id": p.get("id"), "claim": p.get("claim"), "check": chk}
        if typ == "engine_feature":
            f = features.get(chk.get("feature", ""))
            if f is None or chk.get("expect") not in ("present", "absent"):
                res.update(status="invalid", evidence=f"unknown feature or expect; known: {sorted(features)}")
            else:
                ok = f["present"] == (chk["expect"] == "present")
                res.update(
                    status="verified" if ok else "falsified",
                    evidence=f"{f['probe_evidence']} [{f['code']['file']}:{f['code']['line']}]",
                )
        elif typ == "view_api":
            present = chk.get("method") in api
            if chk.get("expect") not in ("present", "absent"):
                res.update(status="invalid", evidence="expect must be present/absent")
            else:
                ok = present == (chk["expect"] == "present")
                res.update(status="verified" if ok else "falsified", evidence=f"BarView public API: {api}")
        elif typ == "parent_metric":
            sym, m, op = chk.get("symbol", "ALL"), chk.get("metric"), chk.get("op")
            syms = list(parent) if sym == "ALL" else [sym]
            if (
                m not in PARENT_METRICS
                or op not in OPS
                or any(s not in parent for s in syms)
                or not isinstance(chk.get("value"), int | float)
            ):
                res.update(status="invalid", evidence=f"metric must be one of {PARENT_METRICS}; op in {list(OPS)}")
            else:
                vals = {s: float(parent[s][m]) for s in syms}
                ok = all(OPS[op](v, float(chk["value"])) for v in vals.values() if math.isfinite(v))
                res.update(
                    status="verified" if ok else "falsified",
                    evidence=f"measured {m} = { {s: round(v, 4) for s, v in vals.items()} } (claim {op} {chk['value']})",
                )
        elif typ == "unverifiable":
            res.update(status="unverifiable", evidence=chk.get("reason", ""))
        else:
            res.update(status="invalid", evidence="unknown check type")
        results.append(res)
    st = [r["status"] for r in results]
    verdict = (
        "rejected_false_premise"
        if "falsified" in st
        else "rejected_malformed"
        if "invalid" in st
        else "rejected_unverifiable"
        if "verified" not in st
        else "accepted"
    )
    return {
        "verdict": verdict,
        "results": results,
        "counts": {k: st.count(k) for k in ("verified", "falsified", "unverifiable", "invalid")},
    }


# ---------------------------------------------------------------- premises of the offline grammar operators
# (so that all generators are held to the same pre-check)

OPERATOR_PREMISES: dict[str, list[dict[str, Any]]] = {
    "add_deadzone": [
        {
            "id": "P1",
            "claim": "trading costs are a large share of gross PnL",
            "check": {
                "type": "parent_metric",
                "metric": "trading_cost_share",
                "symbol": "ALL",
                "op": ">",
                "value": 0.2,
            },
        }
    ],
    "add_funding_guard": [
        {
            "id": "P1",
            "claim": "funding is a material cost",
            "check": {
                "type": "parent_metric",
                "metric": "funding_cost_share",
                "symbol": "ALL",
                "op": ">",
                "value": 0.1,
            },
        },
        {
            "id": "P2",
            "claim": "funding is visible to strategies",
            "check": {"type": "view_api", "method": "funding", "expect": "present"},
        },
    ],
    "add_trend_filter": [
        {
            "id": "P1",
            "claim": "positions flip often (short holding periods)",
            "check": {"type": "parent_metric", "metric": "avg_holding_bars", "symbol": "ALL", "op": "<", "value": 72},
        }
    ],
    "add_vol_target": [
        {
            "id": "P1",
            "claim": "exposure is not already volatility-scaled to near zero",
            "check": {"type": "parent_metric", "metric": "mean_abs_exposure", "symbol": "ALL", "op": ">", "value": 0.2},
        },
        {
            "id": "P2",
            "claim": "high-volatility periods hurt (diagnostic in the dossier)",
            "check": {"type": "unverifiable", "reason": "tercile Sharpe gap is a development diagnostic"},
        },
    ],
    "change_horizon": [
        {"id": "P1", "claim": "horizon matters", "check": {"type": "unverifiable", "reason": "exploratory"}}
    ],
    "swap_signal": [
        {"id": "P1", "claim": "signal definition matters", "check": {"type": "unverifiable", "reason": "exploratory"}}
    ],
    "try_reversion": [
        {
            "id": "P1",
            "claim": "positions change frequently enough for reversion",
            "check": {
                "type": "parent_metric",
                "metric": "decision_change_rate",
                "symbol": "ALL",
                "op": ">",
                "value": 0.01,
            },
        }
    ],
}
