"""Experiment C2: liquidation cascade threshold scan with a causal counterfactual arm.

Protocol: evals/frozen/cascade_c2_v1.json (sha256 stored in every report).
Arm A runs normal mechanics; arm B suppresses execution of secondary (agent) liquidations while still recording
margin breaches (KC-2 switch). Everything else, including the primary whale liquidation, is identical.

The runner only reads simulation state between `run_until` steps; tests check that a measured run has the same
fingerprint as an unmeasured one.
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

from ..evaluation.stats import paired_diff
from ..sim.config import SimConfig
from ..sim.simulation import Simulation
from .market_stats import _clean, minute_returns
from .sampler import near_depth_by_kind

SPEC = Path("evals/frozen/cascade_c2_v1.json")
OUT = Path("artifacts/observatory")
CLASSES = ("no_secondary_liquidations", "secondary_without_amplification", "amplification_without_chain", "cascade")


def spec() -> dict[str, Any]:
    return json.loads(SPEC.read_text())


def spec_sha() -> str:
    return hashlib.sha256(SPEC.read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- margin geometry
def margin_distance(equity: int, net: int, gross: int, mm: float) -> tuple[float, str]:
    """Smallest uniform relative price move that puts the account in breach (E + N x < mm G (1 + x))."""
    if gross == 0:
        return math.inf, "none"
    if equity < mm * gross:
        return 0.0, "breached"
    den = net - mm * gross
    if den == 0:
        return math.inf, "none"
    x = (mm * gross - equity) / den
    return abs(x), ("down" if x < 0 else "up")


def margin_snapshot(sim: Simulation) -> list[dict[str, Any]]:
    marks = sim.exchange.marks()
    mm = sim.clearing.maintenance_margin
    out = []
    for a in sim.agents:
        acct = sim.clearing.accounts[a.id]
        if not any(acct.positions):
            continue
        eq = acct.equity(marks)
        net = sum(p * m for p, m in zip(acct.positions, marks, strict=True))
        gross = acct.gross_notional(marks)
        d, direction = margin_distance(eq, net, gross, mm)
        out.append(
            {
                "agent": a.id,
                "kind": a.kind,
                "distance": d,
                "direction": direction,
                "eff_leverage": gross / eq if eq > 0 else math.inf,
                "long": net > 0,
            }
        )
    return out


# ----------------------------------------------------------------------------- one run
def _mid_avg(series: list[tuple], ncols: int) -> np.ndarray:
    a = np.array(series, dtype=float)
    return a[:, 1 : 1 + ncols].mean(1) / 100


def _trade_hashes(sim: Simulation, lo_ms: int, hi_ms: int) -> list[str]:
    """Cumulative hash of the trade tape at each second in [lo, hi): first difference = arm divergence time."""
    h = hashlib.sha256()
    out = []
    trades = sim.exchange.trades
    i = 0
    for t in range(lo_ms, hi_ms, 1000):
        while i < len(trades) and trades[i].t < t:
            tr = trades[i]
            h.update(f"{tr.t},{tr.venue},{tr.price},{tr.qty},{tr.buyer},{tr.seller};".encode())
            i += 1
        out.append(h.hexdigest()[:10])
    return out


def run_one(job: dict[str, Any], step_s: int = 5) -> dict[str, Any]:
    t0 = time.perf_counter()
    cfg = SimConfig(**job["cfg"])
    at = job["at_s"] * 1000
    sim = Simulation(cfg)
    n = len(sim.agents)
    sim.run_until(at - 1000)
    pre_margin = margin_snapshot(sim)
    pre_near = near_depth_by_kind(sim)
    whale_id = sim.external.get("whale_0")
    whale_lots = sum(abs(p) for p in sim.clearing.accounts[whale_id].positions) if whale_id is not None else 0
    near_depth = []
    t = at - 1000
    while t < at + 300_000:
        t += step_s * 1000
        sim.run_until(t)
        near_depth.append(round(sum(near_depth_by_kind(sim).values()), 3))
    sim.run()
    sim.exchange.check_invariants()

    cols = sim.series_columns()
    a = np.array(sim.series, dtype=float)
    ts = a[:, 0].astype(int)
    mid = _mid_avg(sim.series, cfg.n_venues)
    spread = a[:, cols.index("spread_bps")]
    depth = a[:, cols.index("depth")] / 1e4

    def idx(t_ms: int) -> int:
        return int(min(len(ts) - 1, max(0, np.searchsorted(ts, t_ms))))

    pre_i = idx(at - 1000)
    pre_mid = float(mid[pre_i])
    liq = sim.liquidation_log
    prim = [e for e in liq if e.get("role") == "primary"]
    sec = [e for e in liq if e.get("role") == "secondary" and at <= e["t"] < at + 300_000]
    t_l = prim[0]["t"] if prim else at
    win = (ts >= at) & (ts < at + 300_000)
    pre = (ts >= at - 300_000) & (ts < at)
    trough_i = int(np.argmin(np.where(win, mid, np.inf)))
    trough = float(mid[trough_i])
    drop = trough / pre_mid - 1
    half = pre_mid + 0.5 * (trough - pre_mid)
    rec = [int(ts[i]) for i in range(trough_i, len(ts)) if mid[i] >= half]
    breaches = [
        {
            **b,
            "kind": sim.agents[b["agent"]].kind if b["agent"] < n else "external",
            "role": "secondary" if b["agent"] < n else "primary",
        }
        for b in sim.exchange.breaches
    ]
    sec_breach = [b for b in breaches if b["role"] == "secondary" and at <= b["t"] < at + 300_000]
    pre_breach = [b for b in breaches if b["role"] == "secondary" and b["t"] < at]

    # generations: primary = 0; a breach gets 1 + generation of the latest forced execution strictly before it
    forced = sorted([(e["t"], e["agent"], e.get("role")) for e in liq if e["t"] >= at])
    gen_of_agent: dict[int, int] = {p["agent"]: 0 for p in prim}
    gens = []
    for b in sorted(sec_breach, key=lambda x: (x["t"], x["agent"])):
        before = [f for f in forced if f[0] < b["t"] and f[1] in gen_of_agent]
        g = 1 + gen_of_agent[before[-1][1]] if before else 1
        gens.append({"t": b["t"], "agent": b["agent"], "kind": b["kind"], "generation": g, "executed": b["executed"]})
        if b["executed"]:
            gen_of_agent.setdefault(b["agent"], g)

    stops = [
        {"t": d["t"], "agent": ag.id}
        for ag in sim.agents
        if ag.kind == "leveraged"
        for d in ag.decisions
        if d.get("action") == "stop_loss" and at <= d["t"] < at + 300_000
    ]
    panics = sum(
        1 for ag in sim.agents for d in ag.decisions if d.get("action") == "panic_sell" and at <= d["t"] < at + 300_000
    )
    r_pre = minute_returns(mid[(ts >= at - 300_000) & (ts < at + 1000)])
    r_win = minute_returns(mid[(ts >= at - 1000) & (ts < at + 300_000)])
    bins = list(range(at, at + 300_000, 10_000))
    lev = [m for m in pre_margin if m["kind"] == "leveraged"]
    dist = [m["distance"] for m in pre_margin if math.isfinite(m["distance"])]
    trace = sorted(
        [{"t": e["t"], "type": "primary_liquidation", "agent": e["agent"]} for e in prim]
        + [{"t": e["t"], "type": "secondary_liquidation", "agent": e["agent"], "kind": e["kind"]} for e in sec]
        + [
            {
                "t": g["t"],
                "type": "breach",
                "agent": g["agent"],
                "kind": g["kind"],
                "generation": g["generation"],
                "executed": g["executed"],
            }
            for g in gens
        ]
        + [{"t": s["t"], "type": "stop_loss", "agent": s["agent"]} for s in stops],
        key=lambda e: (e["t"], e["type"]),
    )
    for e in trace:
        e["mid_rel"] = round(float(mid[idx(e["t"])]) / pre_mid - 1, 6)
    # primary forced selling is a process: the external account stays in liquidation while the book refills
    psell = [tr for tr in sim.exchange.trades if whale_id is not None and tr.seller == whale_id and tr.t >= at]
    p_end = psell[-1].t if psell else t_l
    primary_selling = {
        "first_t": psell[0].t if psell else None,
        "last_t": p_end,
        "duration_s": (p_end - psell[0].t) / 1000 if psell else 0.0,
        "btc": sum(tr.qty for tr in psell) / 1e4,
        "mid_rel_at_end": float(mid[idx(p_end)]) / pre_mid - 1,
        "btc_per_10s": [round(sum(tr.qty for tr in psell if lo <= tr.t < lo + 10_000) / 1e4, 3) for lo in bins],
    }
    traj_lo, traj_hi = at - 120_000, at + 600_000
    tw = (ts >= traj_lo) & (ts < traj_hi)
    rec_out = {
        "config": job["config"],
        "arm": job["arm"],
        "seed": cfg.seed,
        "role": job["role"],
        "whale_btc": job["whale_btc"],
        "leverage_use": job["leverage_use"],
        "config_fingerprint": cfg.fingerprint(),
        "run_fingerprint": sim.fingerprint()[:16],
        "whale_position_btc_at_shock": whale_lots / 1e4,
        "pre_mid": pre_mid,
        "primary_liquidation_t": t_l,
        "primary_forced_notional_usd": sum(sim.exchange.forced_notional.get(p["agent"], 0) for p in prim) / 1e6,
        "primary_closed_btc": sum(p.get("closed_lots", 0) for p in prim) / 1e4,
        "direct_impact": float(mid[idx(t_l)]) / pre_mid - 1,
        "primary_selling": primary_selling,
        "mid_rel_at": {str(k): float(mid[idx(t_l + k * 1000)]) / pre_mid - 1 for k in (10, 60, 300)},
        "max_adverse_move": drop,
        "trough_t": int(ts[trough_i]),
        "half_recovery_s": (rec[0] - int(ts[trough_i])) / 1000 if rec else None,
        "half_recovery_censored": not rec,
        "secondary_breaches": len(sec_breach),
        "secondary_breach_agents": sorted({b["agent"] for b in sec_breach}),
        "secondary_breaches_by_kind": _count(b["kind"] for b in sec_breach),
        "pre_shock_secondary_breaches": len(pre_breach),
        "secondary_liquidations": len(sec),
        "secondary_liquidated_agents": sorted({e["agent"] for e in sec}),
        "secondary_forced_notional_usd": sum(
            sim.exchange.forced_notional.get(e["agent"], 0) for e in {x["agent"]: x for x in sec}.values()
        )
        / 1e6,
        "first_secondary_breach_s": (min(b["t"] for b in sec_breach) - t_l) / 1000 if sec_breach else None,
        "first_secondary_liquidation_s": (min(e["t"] for e in sec) - t_l) / 1000 if sec else None,
        "max_breach_generation": max((g["generation"] for g in gens), default=0),
        "propagation_10s": {
            "breaches": [sum(lo <= b["t"] < lo + 10_000 for b in sec_breach) for lo in bins],
            "secondary_liquidations": [sum(lo <= e["t"] < lo + 10_000 for e in sec) for lo in bins],
        },
        "margin_pre": {
            "n_accounts_with_positions": len(pre_margin),
            "min_distance_all": min(dist) if dist else None,
            "quantiles_all": [float(q) for q in np.quantile(dist, [0.05, 0.25, 0.5])] if dist else None,
            "leveraged": [
                {
                    "agent": m["agent"],
                    "distance": m["distance"],
                    "direction": m["direction"],
                    "eff_leverage": m["eff_leverage"],
                }
                for m in lev
            ],
            "min_distance_leveraged_down": min((m["distance"] for m in lev if m["direction"] == "down"), default=None),
            "histogram_edges": [0, 0.01, 0.02, 0.03, 0.05, 0.1, 0.2, 0.5, 1e9],
            "histogram_all": np.histogram(dist, [0, 0.01, 0.02, 0.03, 0.05, 0.1, 0.2, 0.5, 1e9])[0].tolist()
            if dist
            else [],
        },
        "depth": {
            "pre_median_10lvl_btc": float(np.median(depth[pre])),
            "min_10lvl_btc_window": float(np.min(depth[win])),
            "pre_near_20bps_btc": round(sum(pre_near.values()), 3),
            "near_20bps_btc_5s": near_depth,
        },
        "volatility_1m_bps": {
            "pre": float(np.std(r_pre)) if len(r_pre) > 1 else None,
            "window": float(np.std(r_win)) if len(r_win) > 1 else None,
        },
        "spread_median_bps": {"pre": float(np.nanmedian(spread[pre])), "window": float(np.nanmedian(spread[win]))},
        "circuit_breakers_window": sum(
            1 for e in sim.exchange.events if e.type == "circuit_breaker" and at <= e.t < at + 300_000
        ),
        "stop_losses_leveraged": len(stops),
        "panic_sales": panics,
        "trace": trace[:300],
        "trajectory": {"t0_ms": traj_lo, "mid_rel": [round(float(x) / pre_mid - 1, 6) for x in mid[tw]]},
        "trade_hashes_from_shock": _trade_hashes(sim, at - 1000, at + 300_000),
        "wall_s": round(time.perf_counter() - t0, 2),
    }
    return _clean(rec_out)


def _count(it: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for k in it:
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


# ----------------------------------------------------------------------------- jobs
def jobs(sp: dict[str, Any], role: str) -> list[dict[str, Any]]:
    d = sp["design"]
    seeds = d["pilot"]["seeds"] if role == "pilot" else d["confirmatory"]["seeds"]
    out = []
    for size in d["whale_btc"]:
        for lu in d["leverage_use"]:
            for seed in seeds:
                for arm in ("A", "B"):
                    cfg = {
                        "seed": seed,
                        "duration_s": d["duration_s"],
                        "invariant_check_every_s": 300,
                        **d["base_profile"],
                        "param_overrides": {"leveraged": {"leverage_use": lu}},
                        "shocks": [{"type": "whale_liquidation", "at_s": d["shock_at_s"], "magnitude": float(size)}],
                        "execute_secondary_liquidations": arm == "A",
                    }
                    out.append(
                        {
                            "config": f"{size}btc|lu{lu}",
                            "arm": arm,
                            "role": role,
                            "whale_btc": size,
                            "leverage_use": lu,
                            "at_s": d["shock_at_s"],
                            "cfg": cfg,
                        }
                    )
    return out


# ----------------------------------------------------------------------------- analysis
def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    z = 1.96
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(c - h, 3), round(c + h, 3))


def classify(n_secondary_seeds: int, incr: dict[str, Any], mean_b_drop: float, n_chain_seeds: int) -> dict[str, Any]:
    """Pre-registered rule. Cannot return 'cascade' without secondary liquidations AND an observed chain."""
    a = n_secondary_seeds >= 2
    t_hi = incr.get("t_hi")
    b = t_hi is not None and math.isfinite(t_hi) and t_hi < 0
    m = incr.get("mean")
    c = m is not None and math.isfinite(m) and mean_b_drop != 0 and -m >= 0.10 * abs(mean_b_drop)
    d = n_chain_seeds >= 2
    if not a:
        label = "no_secondary_liquidations"
    elif not (b and c):
        label = "secondary_without_amplification"
    elif not d:
        label = "amplification_without_chain"
    else:
        label = "cascade"
    return {
        "label": label,
        "criteria": {
            "a_secondary_in_2of8": a,
            "b_t_interval_below_0": b,
            "c_ge_10pct_of_direct": c,
            "d_chain_in_2of8": d,
        },
    }


def first_divergence_s(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    ha, hb = a["trade_hashes_from_shock"], b["trade_hashes_from_shock"]
    for i, (x, y) in enumerate(zip(ha, hb, strict=True)):
        if x != y:
            return i - 1  # seconds relative to the shock (index 0 = shock - 1 s)
    return None


def analyse(rows: list[dict[str, Any]], sp: dict[str, Any]) -> dict[str, Any]:
    meta = {r["config"]: (r["leverage_use"], r["whale_btc"], r["config"]) for r in rows}
    configs = sorted(meta, key=lambda c: meta[c])
    out: dict[str, Any] = {}
    for c in configs:
        seeds = sorted({r["seed"] for r in rows if r["config"] == c})
        pairs = []
        for s in seeds:
            ra = next(r for r in rows if r["config"] == c and r["seed"] == s and r["arm"] == "A")
            rb = next(r for r in rows if r["config"] == c and r["seed"] == s and r["arm"] == "B")
            induced = sorted(set(ra["secondary_breach_agents"]) - set(rb["secondary_breach_agents"]))
            first_sec = ra["first_secondary_liquidation_s"]
            induced_after = [
                e
                for e in ra["trace"]
                if e["type"] == "breach"
                and e["agent"] in induced
                and first_sec is not None
                and (e["t"] - ra["primary_liquidation_t"]) / 1000 > first_sec
            ]
            pairs.append(
                {
                    "seed": s,
                    "secondary_liquidations_A": ra["secondary_liquidations"],
                    "secondary_breaches_A": ra["secondary_breaches"],
                    "secondary_breaches_B": rb["secondary_breaches"],
                    "induced_breaches": induced,
                    "chain_observed": bool(ra["secondary_liquidations"]) and bool(induced_after),
                    "drop_A": ra["max_adverse_move"],
                    "drop_B": rb["max_adverse_move"],
                    "incremental_drop": ra["max_adverse_move"] - rb["max_adverse_move"],
                    "incremental_at": {k: ra["mid_rel_at"][k] - rb["mid_rel_at"][k] for k in ra["mid_rel_at"]},
                    "direct_impact_A": ra["direct_impact"],
                    "direct_impact_B": rb["direct_impact"],
                    "first_divergence_s": (div := first_divergence_s(ra, rb)),
                    "pre_shock_identical": div is None or div >= 0,
                    "stop_losses_A": ra["stop_losses_leveraged"],
                    "stop_losses_B": rb["stop_losses_leveraged"],
                }
            )
        k_sec = sum(p["secondary_liquidations_A"] > 0 for p in pairs)
        k_chain = sum(p["chain_observed"] for p in pairs)
        incr = _clean(paired_diff([p["drop_A"] for p in pairs], [p["drop_B"] for p in pairs]))
        mean_b = float(np.mean([p["drop_B"] for p in pairs]))
        ra_all = [r for r in rows if r["config"] == c and r["arm"] == "A"]
        out[c] = {
            "whale_btc": ra_all[0]["whale_btc"],
            "leverage_use": ra_all[0]["leverage_use"],
            "n_seeds": len(pairs),
            "seeds_with_secondary_liquidation": k_sec,
            "wilson95": wilson(k_sec, len(pairs)),
            "seeds_with_chain": k_chain,
            "incremental_drop": incr,
            "incremental_at": {
                k: _clean(paired_diff([p["incremental_at"][k] for p in pairs], [0.0] * len(pairs)))
                for k in ("10", "60", "300")
            },
            "direct_drop_B_mean": mean_b,
            "direct_impact_mean": float(np.mean([p["direct_impact_B"] for p in pairs])),
            "secondary_liquidations_mean": float(np.mean([p["secondary_liquidations_A"] for p in pairs])),
            "secondary_breaches_A_mean": float(np.mean([p["secondary_breaches_A"] for p in pairs])),
            "secondary_breaches_B_mean": float(np.mean([p["secondary_breaches_B"] for p in pairs])),
            "stop_losses_A_mean": float(np.mean([p["stop_losses_A"] for p in pairs])),
            "min_margin_distance_leveraged_down": _clean(
                [r["margin_pre"]["min_distance_leveraged_down"] for r in ra_all]
            ),
            "whale_position_btc_at_shock": [r["whale_position_btc_at_shock"] for r in ra_all],
            "all_pre_shock_identical": all(p["pre_shock_identical"] for p in pairs),
            "classification": classify(k_sec, incr, mean_b, k_chain),
            "pairs": pairs,
        }
    return {"configs": out, "threshold": _threshold(out, sp)}


def _threshold(cfgs: dict[str, Any], sp: dict[str, Any]) -> dict[str, Any]:
    res = {}
    for lu in sp["design"]["leverage_use"]:
        row = sorted((v for v in cfgs.values() if v["leverage_use"] == lu), key=lambda v: v["whale_btc"])
        fr = {v["whale_btc"]: v["seeds_with_secondary_liquidation"] for v in row}
        onset = next((v["whale_btc"] for v in row if v["seeds_with_secondary_liquidation"] >= 2), None)
        lower = max(
            (
                v["whale_btc"]
                for v in row
                if v["seeds_with_secondary_liquidation"] == 0 and (onset is None or v["whale_btc"] < onset)
            ),
            default=None,
        )
        monotone = all(fr[a] <= fr[b] for a, b in zip(sorted(fr), sorted(fr)[1:], strict=False))
        shape = "not applicable (no onset)"
        if onset is not None and lower is not None:
            lo = next(v for v in row if v["whale_btc"] == lower)
            hi = next(v for v in row if v["whale_btc"] == onset)
            li = lo["incremental_drop"]
            neg_lo = (li.get("t_lo") or 0) <= 0 <= (li.get("t_hi") or 0) and abs(li.get("mean") or 0) < 0.1 * abs(
                lo["direct_drop_B_mean"]
            )
            meets_hi = (
                hi["classification"]["criteria"]["b_t_interval_below_0"]
                and hi["classification"]["criteria"]["c_ge_10pct_of_direct"]
            )
            shape = "transition-like" if neg_lo and meets_hi else "graded"
        elif onset is not None:
            shape = "onset at the smallest tested size (no lower bracket)"
        res[f"lu{lu}"] = {
            "seeds_with_secondary_by_size": fr,
            "onset_bracket_btc": [lower, onset] if onset is not None else None,
            "statement": f"secondary liquidations begin between {lower} and {onset} BTC"
            if onset and lower
            else (
                "threshold not observed within the tested range" if onset is None else f"present already at {onset} BTC"
            ),
            "monotone_in_size": monotone,
            "shape": shape,
        }
    return res


# ----------------------------------------------------------------------------- driver
def run(role: str = "confirmatory", workers: int = 4) -> dict[str, Any]:
    sp = spec()
    js = jobs(sp, role)
    t0 = time.perf_counter()
    with ProcessPoolExecutor(workers) as ex:
        rows = list(ex.map(run_one, js))
    rep = analyse(rows, sp)
    rep.update(
        {
            "protocol": sp["name"],
            "protocol_sha256": spec_sha(),
            "role": role,
            "label": ("EXPLORATORY pilot" if role == "pilot" else "CONFIRMATORY")
            + " - SYNTHETIC; no historical data, no holdout, no LLM",
            "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "cost": {
                "runs": len(rows),
                "wall_s": round(time.perf_counter() - t0, 1),
                "cpu_s_sum": round(sum(r["wall_s"] for r in rows), 1),
                "llm_calls": 0,
            },
            "runs": rows,
        }
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"cascade_c2_{role}.json").write_text(json.dumps(_clean(rep), indent=1, default=float))
    return rep


# ----------------------------------------------------------------------------- C2x (exploratory)
SPEC_X = Path("evals/frozen/cascade_c2x_v1.json")
X_CONDITIONS: dict[str, dict[str, Any]] = {
    "default": {},
    "no_funding_term": {"param_overrides": {"leveraged": {"leverage_use": 1.0, "funding_sens": 0.0}}},
    "no_social": {"social_enabled": False, "imitation_enabled": False},
    "neither": {
        "param_overrides": {"leveraged": {"leverage_use": 1.0, "funding_sens": 0.0}},
        "social_enabled": False,
        "imitation_enabled": False,
    },
}
X_SEEDS = (901, 902, 903, 904, 905, 906, 907, 908)


def _x_cfg(cond: str, seed: int, execute: bool = True, duration_s: int = 1800) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "seed": seed,
        "duration_s": duration_s,
        "invariant_check_every_s": 300,
        "world_annual_vol": 0.33,
        "news_impact": 0.0,
        "param_overrides": {"leveraged": {"leverage_use": 1.0}},
        "shocks": [{"type": "whale_liquidation", "at_s": 900, "magnitude": 2000.0}],
        "execute_secondary_liquidations": execute,
    }
    cfg.update(X_CONDITIONS[cond])
    return cfg


def positioning(args: tuple[str, int]) -> dict[str, Any]:
    cond, seed = args
    cfg = SimConfig(**_x_cfg(cond, seed))
    sim = Simulation(cfg)
    sim.run_until(899_000)
    snap = [m for m in margin_snapshot(sim) if m["kind"] == "leveraged"]
    longs = [m for m in snap if m["long"]]
    fr = [e.data["rate"] for e in sim.sim_events if e.type == "funding" and e.venue == 0]
    return {
        "condition": cond,
        "seed": seed,
        "leveraged_long": len(longs),
        "leveraged_short": len(snap) - len(longs),
        "leveraged_flat": 16 - len(snap),
        "min_down_distance_longs": min((m["distance"] for m in longs), default=None),
        "eff_leverage_longs": [round(m["eff_leverage"], 2) for m in longs],
        "funding_path": fr,
    }


def deleveraging_trace(args: tuple[str, int]) -> dict[str, Any]:
    """Leveraged long exposure and margin distance through the shock (read-only stepping)."""
    cond, seed = args
    sim = Simulation(SimConfig(**_x_cfg(cond, seed)))
    out = []
    pre_mid = None
    for t_s in (899, 902, 905, 910, 915, 930, 945, 960, 1000, 1100, 1200):
        sim.run_until(t_s * 1000)
        marks = sim.exchange.marks()
        mid = sum(marks) / len(marks)
        pre_mid = pre_mid or mid
        snap = [m for m in margin_snapshot(sim) if m["kind"] == "leveraged" and m["long"]]
        gross = sum(sim.clearing.accounts[m["agent"]].gross_notional(marks) for m in snap) / 1e12
        out.append(
            {
                "t_s": t_s,
                "mid_rel": mid / pre_mid - 1,
                "leveraged_longs": len(snap),
                "long_gross_usd_m": round(gross, 3),
                "min_down_distance": min((m["distance"] for m in snap), default=None),
            }
        )
    eq = sum(
        max(0, sim.clearing.accounts[a.id].equity(sim.exchange.marks())) for a in sim.agents if a.kind == "leveraged"
    )
    return {"condition": cond, "seed": seed, "path": out, "leveraged_equity_usd_m_end": eq / 1e12}


def run_x(workers: int = 4) -> dict[str, Any]:
    t0 = time.perf_counter()
    with ProcessPoolExecutor(workers) as ex:
        x1 = list(ex.map(positioning, [(c, s) for c in X_CONDITIONS for s in X_SEEDS]))
    means = {c: float(np.mean([r["leveraged_long"] for r in x1 if r["condition"] == c])) for c in X_CONDITIONS}
    cands = [c for c in X_CONDITIONS if c != "default"]
    best = max(cands, key=lambda c: (means[c], c == "no_funding_term"))
    js = [
        {
            "config": f"2000btc|lu1.0|{best}",
            "arm": arm,
            "role": "exploratory",
            "whale_btc": 2000,
            "leverage_use": 1.0,
            "at_s": 900,
            "cfg": _x_cfg(best, s, arm == "A"),
        }
        for s in X_SEEDS
        for arm in ("A", "B")
    ]
    with ProcessPoolExecutor(workers) as ex:
        rows = list(ex.map(run_one, js))
    x2 = analyse(rows, {"design": {"leverage_use": [1.0]}})
    with ProcessPoolExecutor(workers) as ex:
        x2["deleveraging_traces"] = list(ex.map(deleveraging_trace, [(best, s) for s in X_SEEDS]))
    lev_cap = [
        sum(
            a.capital_usd * a.max_leverage
            for a in Simulation(SimConfig(**_x_cfg(best, s))).agents
            if a.kind == "leveraged"
        )
        / 1e6
        for s in X_SEEDS[:2]
    ]
    x2["scale_check"] = {
        "leveraged_max_gross_usd_m_at_initial_capital": lev_cap,
        "primary_forced_notional_usd_m": [r["primary_forced_notional_usd"] / 1e6 for r in rows if r["arm"] == "B"],
    }
    rep = {
        "protocol": "cascade-c2x-v1",
        "protocol_sha256": hashlib.sha256(SPEC_X.read_bytes()).hexdigest(),
        "label": "EXPLORATORY - same seeds as C2 confirmatory; not independent; counterfactual model variants",
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "X1": {"runs": x1, "mean_leveraged_long": means, "selected_for_X2": best},
        "X2": x2,
        "cost": {"runs": len(x1) + len(rows), "wall_s": round(time.perf_counter() - t0, 1), "llm_calls": 0},
        "runs": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cascade_c2x_exploratory.json").write_text(json.dumps(_clean(rep), indent=1, default=float))
    return rep


# ----------------------------------------------------------------------------- research memory
NEXT_CANDIDATES: list[dict[str, Any]] = [
    {
        "id": "C2-more-seeds",
        "hypothesis_id": "C2-H1",
        "conditions": {"grid": "C2", "whale_btc": [1000, 2000, 4000], "leverage_use": [0.7, 1.0]},
        "runs": 96,
        "prior_positive": 0.02,
        "why": "same grid: 0 breaches in 96 runs, a repeat is nearly uninformative (and blocked as a duplicate)",
    },
    {
        "id": "C3-fuel",
        "hypothesis_id": "C3-fuel",
        "conditions": {"whale_btc": 2000, "leverage_use": 1.0, "leveraged_agents": 64},
        "runs": 32,
        "prior_positive": 0.15,
        "why": "4x leveraged agents: more fuel, but funding still pushes them short",
    },
    {
        "id": "C3-funding",
        "hypothesis_id": "C3-funding",
        "conditions": {"whale_btc": 2000, "leverage_use": 1.0, "funding_k": 0.0001},
        "runs": 32,
        "prior_positive": 0.15,
        "why": "realistic funding magnitude: leveraged may stay long, but the sector is ~7% of the shock",
    },
    {
        "id": "C3-fuel-x-funding",
        "hypothesis_id": "C3-factorial",
        "conditions": {
            "whale_btc": 2000,
            "leverage_use": 1.0,
            "leveraged_agents": [16, 64],
            "funding_k": [0.1, 0.0001],
        },
        "runs": 64,
        "prior_positive": 0.35,
        "why": "both blockers removed in one cell, plus the interaction; seeds 909-916 (fresh)",
    },
    {
        "id": "C2-mirror-squeeze",
        "hypothesis_id": "C2-mirror",
        "conditions": {"shock": "short whale forced buy", "whale_btc": 2000},
        "runs": 32,
        "prior_positive": 0.10,
        "why": "funding would make leveraged agents long against a short whale: the same anti-crowding",
    },
]


def ingest_knowledge(evaluate: bool = True) -> dict[str, Any]:
    from . import knowledge as K

    mem = K.open_memory()
    conf = json.loads((OUT / "cascade_c2_confirmatory.json").read_text())
    expl = json.loads((OUT / "cascade_c2x_exploratory.json").read_text())
    sp = spec()
    log: list[str] = []
    try:
        K.register_experiment(
            mem,
            "C2-H1",
            NEXT_CANDIDATES[0]["conditions"],
            sp["design"]["confirmatory"]["seeds"],
            conf["protocol_sha256"],
            {
                "classification": {c: v["classification"]["label"] for c, v in conf["configs"].items()},
                "threshold": conf["threshold"],
            },
        )
        log.append("registered C2-H1")
    except K.DuplicateExperiment as e:
        log.append(f"skip: {e}")
    total_breaches = sum(r["secondary_breaches"] for r in conf["runs"])
    K.record_mechanism(
        mem,
        "C2-H1",
        "a whale forced sale (1000-4000 BTC nominal, leverage_use 0.7/1.0) triggers a liquidation feedback cascade",
        "not_observed",
        {
            "artifact": "artifacts/observatory/cascade_c2_confirmatory.json",
            "protocol_sha256": conf["protocol_sha256"],
            "runs": len(conf["runs"]),
            "secondary_breaches_total": total_breaches,
            "threshold": "not observed within the tested range",
        },
        "mechanism",
    )
    x1 = expl["X1"]["mean_leveraged_long"]
    K.record_mechanism(
        mem,
        "C2x-funding-contrarian",
        "funding-aware leveraged agents take the side opposite the whale's crowded long (funding term), removing cascade fuel",
        "exploratory_supported",
        {
            "artifact": "artifacts/observatory/cascade_c2x_exploratory.json",
            "mean_leveraged_long_of_16": x1,
            "note": "same seeds as C2; exploratory",
        },
        "mechanism",
    )
    K.record_mechanism(
        mem,
        "C2x-voluntary-deleveraging",
        "leveraged longs cut ~80% of exposure through ordinary momentum trading during the slow forced sale, before margin",
        "exploratory_supported",
        {"traces": "X2.deleveraging_traces", "scale_check": expl["X2"]["scale_check"]},
        "mechanism",
    )
    K.record_gap(
        mem,
        "funding-magnitude",
        "funding of ~0.1% per 300 s interval during the whale build-up is ~1000x a typical 8-hour perp funding rate; "
        "with funding_sens 2000 it saturates the leveraged signal",
        {
            "funding_path_seed901": expl["X1"]["runs"][0]["funding_path"],
            "config": "SimConfig.funding_k=0.1, funding_interval_s=300",
        },
    )
    K.record_gap(
        mem,
        "leveraged-capacity",
        "the whole leveraged sector can hold ~$6-7M gross vs a ~$90M primary forced sale (~7%)",
        expl["X2"]["scale_check"],
    )
    K.record_gap(
        mem,
        "whale-build-up-saturation",
        "the whale_liquidation shock cannot build more than ~1500-1800 BTC (market-buy chunks partly unfilled); "
        "an experiment-tool limit, not a market mechanism",
        {"reached_btc": {c: v["whale_position_btc_at_shock"] for c, v in conf["configs"].items()}},
    )
    props = [
        K.propose(
            mem,
            "P1-funding-sensitivity",
            "funding-magnitude",
            {"world_annual_vol": 0.33, "news_impact": 0.0, "param_overrides": {"leveraged": {"funding_sens": 2.0}}},
            "agent-side proxy for realistic funding: same funding term with 1000x lower sensitivity",
            True,
        ),
        K.propose(
            mem,
            "P2-funding-rate",
            "funding-magnitude",
            {"funding_k": 0.0001},
            "root-cause fix of the funding magnitude; funding_k is outside the frozen candidate space",
            False,
        ),
        K.propose(
            mem,
            "P3-leveraged-population",
            "leveraged-capacity",
            {"world_annual_vol": 0.33, "news_impact": 0.0, "population_overrides": {"leveraged": 64}},
            "4x leveraged speculators",
            True,
        ),
    ]
    evals = []
    if evaluate:
        for pid in ("P1-funding-sensitivity", "P3-leveraged-population"):
            evals.append(K.evaluate_proposal(mem, pid))
    ranking = K.rank_next(mem, NEXT_CANDIDATES)
    rep = {
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "log": log,
        "mechanisms": K.mechanisms(mem),
        "proposals": K.proposals(mem),
        "proposal_specs": props,
        "proposal_evaluations": evals,
        "next_experiment_ranking": ranking,
        "note": "priors in the ranking are explicit judgement inputs; proposals are never applied automatically",
    }
    (OUT / "knowledge_c2.json").write_text(json.dumps(_clean(rep), indent=1, default=str))
    return rep
