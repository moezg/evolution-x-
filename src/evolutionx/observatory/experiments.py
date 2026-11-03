"""Experiments A/B/C of the Emergent Behavior Observatory.

Pre-registered in evals/frozen/observatory_experiments_v1.json (hash recorded in every report).
Every run is SYNTHETIC; every treatment is paired with a same-seed control. Verdicts are computed from
the pre-registered thresholds by code, not chosen after looking at the numbers.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from ..evaluation.stats import mean_ci, paired_diff
from ..sim.config import SimConfig
from .market_stats import _clean, market_properties, minute_returns, signed_flow_per_minute
from .metrics import all_metrics
from .sampler import run_sampled

SPEC = Path("evals/frozen/observatory_experiments_v1.json")
OUT = Path("artifacts/observatory")


def spec() -> dict[str, Any]:
    return json.loads(SPEC.read_text())


def window_stats(sim: Any, smp: Any, lo_s: int, hi_s: int) -> dict[str, Any]:
    a = np.array(sim.series, dtype=float)
    cols = sim.series_columns()
    t = a[:, 0]
    w = (t >= lo_s * 1000) & (t < hi_s * 1000)
    mid = a[:, cols.index("mid_0")] / 100
    spread = a[w, cols.index("spread_bps")]
    pre = mid[(t < lo_s * 1000)]
    ref = float(pre[-1]) if len(pre) else float(mid[w][0])
    seg = mid[(t >= lo_s * 1000 - 1000) & (t < hi_s * 1000)]
    r = minute_returns(seg)
    flow = signed_flow_per_minute(sim)[lo_s // 60 : hi_s // 60]
    liq = [e for e in sim.liquidation_log if lo_s * 1000 <= e["t"] < hi_s * 1000]
    st = np.array(smp.t_ms)
    sw = (st >= lo_s * 1000) & (st < hi_s * 1000)
    mm = np.vstack(smp.mm_depth)[sw].mean(0) if sw.any() else np.zeros(0)
    return {
        "spread_median_bps": float(np.nanmedian(spread)) if np.isfinite(spread).any() else float("nan"),
        "one_sided_frac": float(np.mean(~np.isfinite(spread))),
        "depth_median_btc": float(np.median(a[w, cols.index("depth")]) / 1e4),
        "ret_std_1m_bps": float(np.std(r)) if len(r) > 1 else float("nan"),
        "impact_bps_per_btc": float(np.sum(np.abs(r)) / max(np.sum(np.abs(flow[: len(r)])), 1e-9)),
        "min_mid_rel_pre": float(np.min(mid[w]) / ref - 1),
        "max_abs_dev_fundamental": float(np.max(np.abs(mid[w] / a[w, cols.index("fundamental")] - 1))),
        "liquidations_agents": sum(e["kind"] != "external" for e in liq),
        "liquidations_external": sum(e["kind"] == "external" for e in liq),
        "mm_near_depth_by_agent": [round(float(x), 4) for x in mm],
    }


def _job(job: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    cfg = SimConfig(**job["cfg"])
    sim, smp = run_sampled(cfg)
    windows = {k: window_stats(sim, smp, lo, hi) for k, (lo, hi) in job["windows"].items()}
    shock = job.get("shock_window_ms")
    a = np.array(sim.series, dtype=float)
    cols = sim.series_columns()
    rec = {
        "exp": job["exp"],
        "condition": job["condition"],
        "seed": cfg.seed,
        "config_fingerprint": cfg.fingerprint(),
        "run_fingerprint": sim.fingerprint()[:16],
        "properties": market_properties(sim),
        "metrics": all_metrics(sim, smp, tuple(shock) if shock else None),
        "windows": windows,
        "circuit_breakers": sum(e.type == "circuit_breaker" for e in sim.exchange.events),
        "max_abs_dev_fundamental": float(
            np.max(np.abs(a[:, cols.index("mid_0")] / 100 / a[:, cols.index("fundamental")] - 1))
        ),
        "wall_s": round(time.perf_counter() - t0, 2),
        "events_processed": sim.events_processed,
    }
    return _clean(rec)


def _base(sp: dict[str, Any], seed: int, **over: Any) -> dict[str, Any]:
    c = {"seed": seed, "duration_s": sp["common"]["duration_s"], "invariant_check_every_s": 300}
    c.update(sp["base_profile"]["overrides"])
    c.update(over)
    return c


def jobs_A(sp: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for cond, over in sp["A_stable"]["conditions"].items():
        for s in sp["common"]["seeds"]:
            out.append({"exp": "A", "condition": cond, "cfg": _base(sp, s, **over), "windows": {"all": (60, 1800)}})
    return out


def jobs_B(sp: dict[str, Any]) -> list[dict[str, Any]]:
    b = sp["B_liquidity_crisis"]["shock"]
    out = []
    for f in [0.0, *b["magnitude"]]:
        for s in sp["common"]["seeds"]:
            shock = {
                "type": "mm_withdrawal",
                "at_s": b["at_s"],
                "duration_s": b["duration_s"],
                "magnitude": max(f, 0.5),
                "armed": f > 0,
            }
            out.append(
                {
                    "exp": "B",
                    "condition": "control" if f == 0 else f"f={f}",
                    "cfg": _base(sp, s, shocks=[shock]),
                    "windows": {"pre": (600, 900), "crisis": (900, 1200), "recovery": (1200, 1500)},
                    "shock_window_ms": (b["at_s"] * 1000, (b["at_s"] + b["duration_s"]) * 1000),
                }
            )
    return out


def jobs_C(sp: dict[str, Any]) -> list[dict[str, Any]]:
    c = sp["C_liquidation_cascade"]
    at = sp["common"]["shock_at_s"]
    out = []
    for size in c["factors"]["whale_btc"]:
        for pop, n in c["factors"]["leveraged_agents"].items():
            for armed in (False, True):
                for s in sp["common"]["seeds"]:
                    shock = {"type": "whale_liquidation", "at_s": at, "magnitude": float(size), "armed": armed}
                    out.append(
                        {
                            "exp": "C",
                            "condition": f"{size}btc|lev_{pop}|{'armed' if armed else 'disarmed'}",
                            "cfg": _base(sp, s, shocks=[shock], population_overrides={"leveraged": n}),
                            "windows": {"pre": (600, 900), "crisis": (900, 1200)},
                        }
                    )
    return out


def run(experiments: tuple[str, ...] = ("A", "B", "C"), workers: int = 4) -> dict[str, Any]:
    sp = spec()
    builders = {"A": jobs_A, "B": jobs_B, "C": jobs_C}
    jobs = [j for e in experiments for j in builders[e](sp)]
    t0 = time.perf_counter()
    with ProcessPoolExecutor(workers) as ex:
        rows = list(ex.map(_job, jobs))
    cost = {
        "runs": len(rows),
        "wall_s_total": round(time.perf_counter() - t0, 1),
        "cpu_s_sum": round(sum(r["wall_s"] for r in rows), 1),
        "llm_calls": 0,
    }
    rep = analyse(rows, sp)
    rep.update(
        {
            "protocol": sp["name"],
            "protocol_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest(),
            "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "label": "SYNTHETIC market experiments; no historical data, no holdout, no LLM",
            "cost": cost,
            "runs": rows,
        }
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "experiments_v1.json").write_text(json.dumps(_clean(rep), indent=2, default=float))
    return rep


# ----------------------------------------------------------------------------- analysis
def _get(r: dict[str, Any], path: str) -> float:
    cur: Any = r
    for k in path.split("."):
        cur = cur.get(k) if isinstance(cur, dict) else None
    return float(cur) if isinstance(cur, int | float) and not isinstance(cur, bool) else float("nan")


def _vals(rows: list[dict[str, Any]], exp: str, cond: str, path: str) -> list[float]:
    rs = sorted((r for r in rows if r["exp"] == exp and r["condition"] == cond), key=lambda r: r["seed"])
    return [_get(r, path) for r in rs]


def _pd(rows: list[dict[str, Any]], exp: str, t: str, c: str, path: str) -> dict[str, Any]:
    return _clean(paired_diff(_vals(rows, exp, t, path), _vals(rows, exp, c, path)))


def _excl0(d: dict[str, Any], sign: int = 1, keys: tuple[str, str] = ("lo", "hi")) -> bool:
    lo, hi = d.get(keys[0]), d.get(keys[1])
    if lo is None or hi is None:
        return False
    return lo > 0 if sign > 0 else hi < 0


def _ci_verdict(d: dict[str, Any], sign: int = 1) -> str:
    """Amendment 1: bootstrap AND t-interval must exclude 0 for 'supported'."""
    boot = _excl0(d, sign)
    tint = _excl0(d, sign, ("t_lo", "t_hi"))
    if boot and tint:
        return "supported"
    return "weak (bootstrap only)" if boot else "not supported"


def _verdict(ok: bool, refuted: bool) -> str:
    return "supported" if ok else ("refuted" if refuted else "inconclusive")


def analyse(rows: list[dict[str, Any]], sp: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if any(r["exp"] == "A" for r in rows):
        out["A"] = _analyse_A(rows)
    if any(r["exp"] == "B" for r in rows):
        out["B"] = _analyse_B(rows, sp)
    if any(r["exp"] == "C" for r in rows):
        out["C"] = _analyse_C(rows)
    return out


def _summary(rows: list[dict[str, Any]], exp: str, paths: list[str]) -> dict[str, Any]:
    conds = sorted({r["condition"] for r in rows if r["exp"] == exp})
    return {c: {p: _clean(mean_ci(_vals(rows, exp, c, p))) for p in paths} for c in conds}


def _analyse_A(rows: list[dict[str, Any]]) -> dict[str, Any]:
    full = [r for r in rows if r["exp"] == "A" and r["condition"] == "full"]
    dev = [r["max_abs_dev_fundamental"] for r in full]
    cb = [r["circuit_breakers"] for r in full]
    ratio = [_get(r, "properties.mid_ret_std_bps.1m") / _get(r, "properties.fundamental_ret_std_bps.1m") for r in full]
    vol = _pd(rows, "A", "full", "no_social", "properties.mid_ret_std_bps.1m")
    herd = _pd(rows, "A", "full", "no_social", "metrics.herding.herding_index_mean")
    acf = _pd(rows, "A", "full", "zero_intelligence", "properties.acf_absret_lag1")
    kur = _pd(rows, "A", "full", "zero_intelligence", "properties.excess_kurtosis_1m")
    detectors = {
        k: {
            "full_vs_no_social": _pd(rows, "A", "full", "no_social", p),
            "full_vs_zero_intelligence": _pd(rows, "A", "full", "zero_intelligence", p),
        }
        for k, p in {
            "herding_index": "metrics.herding.herding_index_mean",
            "taker_volume_hhi": "metrics.influence_concentration.taker_volume_hhi",
            "ari_cluster_vs_kind": "metrics.behavioral_clustering.ari_cluster_vs_programmed_kind",
            "regime_switches": "metrics.regime_transitions.switches",
            "trend_flow_vs_lagged_return": "metrics.momentum_amplification.corr_trend_flow_vs_lagged_return",
            "mm_withdrawn_time_frac": "metrics.liquidity_withdrawal.frac_time_mm_withdrawn",
            "panic_events": "metrics.panic_contagion.panic_events",
            "liquidations": "metrics.liquidation_cascades.liquidations",
            "mid_ret_std_1m": "properties.mid_ret_std_bps.1m",
        }.items()
    }
    return {
        "hypotheses": {
            "HA1-anchoring": {
                "max_abs_dev_by_seed": dev,
                "circuit_breakers_by_seed": cb,
                "verdict": _verdict(max(dev) < 0.03 and sum(cb) == 0, True),
            },
            "HA2-amplification-replicates": {
                "ratio_by_seed": ratio,
                "mean": float(np.mean(ratio)),
                "verdict": _verdict(float(np.mean(ratio)) > 1.3, float(np.mean(ratio)) <= 1.1),
            },
            "HA3-social-amplification": {"paired": vol, "verdict": _ci_verdict(vol)},
            "HA4-herding-needs-interaction": {"paired": herd, "verdict": _ci_verdict(herd)},
            "HA5-stylized-facts-need-strategic-agents": {
                "acf_absret": acf,
                "excess_kurtosis": kur,
                "verdict_acf": _ci_verdict(acf),
                "verdict_kurtosis": _ci_verdict(kur),
            },
        },
        "detector_ablation": detectors,
        "summary": _summary(
            rows,
            "A",
            [
                "properties.mid_ret_std_bps.1m",
                "properties.fundamental_ret_std_bps.1m",
                "properties.excess_kurtosis_1m",
                "properties.acf_absret_lag1",
                "metrics.herding.herding_index_mean",
                "metrics.behavioral_clustering.ari_cluster_vs_programmed_kind",
                "metrics.influence_concentration.taker_volume_hhi",
                "metrics.liquidation_cascades.liquidations",
                "metrics.panic_contagion.panic_events",
            ],
        ),
    }


def _analyse_B(rows: list[dict[str, Any]], sp: dict[str, Any]) -> dict[str, Any]:
    res: dict[str, Any] = {}
    fs = [f"f={f}" for f in sp["B_liquidity_crisis"]["shock"]["magnitude"]]
    for f in fs:
        res[f] = {
            m: _pd(rows, "B", f, "control", f"windows.crisis.{m}")
            for m in ("spread_median_bps", "depth_median_btc", "ret_std_1m_bps", "impact_bps_per_btc", "one_sided_frac")
        }
        res[f]["recovery_spread"] = _pd(rows, "B", f, "control", "windows.recovery.spread_median_bps")
        res[f]["recovery_depth"] = _pd(rows, "B", f, "control", "windows.recovery.depth_median_btc")
    hi = fs[-1]
    mono = _clean(
        paired_diff(
            _vals(rows, "B", fs[-1], "windows.crisis.spread_median_bps"),
            _vals(rows, "B", fs[0], "windows.crisis.spread_median_bps"),
        )
    )
    ctrl_rec = _vals(rows, "B", "control", "windows.recovery.spread_median_bps")
    rec = _vals(rows, "B", hi, "windows.recovery.spread_median_bps")
    rec_ratio = float(np.mean(rec) / np.mean(ctrl_rec)) if ctrl_rec else float("nan")
    # HB6: remaining makers (not withdrawn) vs the same makers in control
    contagion = {}
    for f, frac in zip(fs, sp["B_liquidity_crisis"]["shock"]["magnitude"], strict=True):
        tr = sorted((r for r in rows if r["exp"] == "B" and r["condition"] == f), key=lambda r: r["seed"])
        cr = sorted((r for r in rows if r["exp"] == "B" and r["condition"] == "control"), key=lambda r: r["seed"])
        t_v, c_v = [], []
        for a, b in zip(tr, cr, strict=True):
            da = a["windows"]["crisis"]["mm_near_depth_by_agent"]
            db = b["windows"]["crisis"]["mm_near_depth_by_agent"]
            k = round(frac * len(da))
            t_v.append(float(np.sum(da[k:])))
            c_v.append(float(np.sum(db[k:])))
        d = _clean(paired_diff(t_v, c_v))
        contagion[f] = {
            "remaining_makers": len(tr[0]["windows"]["crisis"]["mm_near_depth_by_agent"])
            - round(frac * len(tr[0]["windows"]["crisis"]["mm_near_depth_by_agent"])),
            "remaining_near_depth_btc_treat": t_v,
            "remaining_near_depth_btc_control": c_v,
            "paired": d,
            "verdict_increase": _ci_verdict(d),
            "verdict_decrease": _ci_verdict(d, -1),
        }
    h = res[hi]
    return {
        "effects": res,
        "hypotheses": {
            "HB1-spread": {
                "f0.9_vs_control": h["spread_median_bps"],
                "f0.9_vs_f0.5": mono,
                "verdict": _ci_verdict(h["spread_median_bps"]),
                "verdict_monotone": _ci_verdict(mono),
            },
            "HB2-depth": {"paired": h["depth_median_btc"], "verdict": _ci_verdict(h["depth_median_btc"], -1)},
            "HB3-volatility": {"paired": h["ret_std_1m_bps"], "verdict": _ci_verdict(h["ret_std_1m_bps"])},
            "HB4-impact": {"paired": h["impact_bps_per_btc"], "verdict": _ci_verdict(h["impact_bps_per_btc"])},
            "HB5-recovery": {
                "spread_ratio_vs_control": rec_ratio,
                "verdict": _verdict(rec_ratio <= 1.2, rec_ratio > 1.2),
            },
            "HB6-withdrawal-contagion": contagion,
        },
    }


def _analyse_C(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def dd(size: int, pop: str, path: str) -> list[float]:
        a = _vals(rows, "C", f"{size}btc|lev_{pop}|armed", path)
        b = _vals(rows, "C", f"{size}btc|lev_{pop}|disarmed", path)
        return [x - y for x, y in zip(a, b, strict=True)]

    cells = {}
    for size in (250, 1000):
        for pop in ("present", "absent"):
            cells[f"{size}btc|lev_{pop}"] = {
                "secondary_liquidations_armed_minus_disarmed": dd(size, pop, "windows.crisis.liquidations_agents"),
                "drop_armed_minus_disarmed": dd(size, pop, "windows.crisis.min_mid_rel_pre"),
                "external_liquidated": _vals(
                    rows, "C", f"{size}btc|lev_{pop}|armed", "windows.crisis.liquidations_external"
                ),
                "liquidations_agents_armed": _vals(
                    rows, "C", f"{size}btc|lev_{pop}|armed", "windows.crisis.liquidations_agents"
                ),
                "liquidations_agents_disarmed": _vals(
                    rows, "C", f"{size}btc|lev_{pop}|disarmed", "windows.crisis.liquidations_agents"
                ),
            }
    sec = cells["1000btc|lev_present"]["secondary_liquidations_armed_minus_disarmed"]
    n_pos = sum(x > 0 for x in sec)
    amp = _clean(
        paired_diff(
            cells["1000btc|lev_absent"]["drop_armed_minus_disarmed"],
            cells["1000btc|lev_present"]["drop_armed_minus_disarmed"],
        )
    )
    dose = _clean(
        paired_diff(
            cells["250btc|lev_present"]["drop_armed_minus_disarmed"],
            cells["1000btc|lev_present"]["drop_armed_minus_disarmed"],
        )
    )
    return {
        "cells": cells,
        "hypotheses": {
            "HC1-secondary-liquidations": {"seeds_with_secondary": n_pos, "verdict": _verdict(n_pos >= 3, n_pos <= 1)},
            "HC2-leverage-amplifies-drop": {
                "note": "positive = drop is deeper with leveraged agents present (drops are negative numbers; absent - present)",
                "paired": amp,
                "verdict": _ci_verdict(amp),
            },
            "HC3-dose": {
                "note": "positive = deeper drop at 1000 BTC than 250 BTC",
                "paired": dose,
                "verdict": _ci_verdict(dose),
            },
        },
    }
