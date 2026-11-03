"""Collective-behaviour detectors for one finished, sampled run.

Each detector returns plain numbers plus a `basis` note saying what in the code directly produces the
quantity (programmed) and what can only come from interaction. A single run cannot tell the two apart;
observatory/emergence.py does that with paired-seed ablations. Thresholds are fixed constants defined
here (not tuned per run) and are part of the pre-registered protocol (evals/frozen/observatory_experiments_v1.json).
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

import numpy as np

from ..sim.simulation import Simulation
from .market_stats import _clean, _corr, minute_returns
from .sampler import DIRECTIONAL, Samples, kinds

ACTIVE_STANCE = 0.05
WITHDRAWAL_FRAC = 0.5  # MM near-depth below 50% of its trailing 5-min median
CASCADE_GAP_MS = 60_000
SECONDARY_WINDOW_MS = 300_000
REGIME_WIN_MIN = 10
REGIME_HIGH = 1.5  # rolling vol above 1.5x the run median = high-vol regime
REGIME_MIN_DWELL_MIN = 5
PANIC_WINDOW_MS = 60_000


# ----------------------------------------------------------------------------- herding
def herding(sim: Simulation, smp: Samples) -> dict[str, Any]:
    """Directional alignment of stances. H_t = |sum s_i| / sum |s_i| over active directional agents."""
    S = smp.stance_matrix()
    k = kinds(sim)
    mask = np.isin(k, DIRECTIONAL)
    D = S[:, mask]
    act = np.abs(D) > ACTIVE_STANCE
    num = np.abs(np.where(act, D, 0).sum(1))
    den = np.where(act, np.abs(D), 0).sum(1)
    h = np.where(den > 0, num / np.maximum(den, 1e-12), np.nan)
    by_kind = {kd: S[:, k == kd].mean(1) for kd in DIRECTIONAL if (k == kd).any()}
    pairs = {}
    names = sorted(by_kind)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            pairs[f"{a}~{b}"] = _corr(by_kind[a], by_kind[b])
    return {
        "herding_index_mean": float(np.nanmean(h)),
        "herding_index_p95": float(np.nanpercentile(h, 95)),
        "frac_time_herding_gt_0_5": float(np.nanmean(h > 0.5)),
        "cross_kind_stance_corr": pairs,
        "basis": "stances are set by each policy; common price input alone aligns momentum/leveraged agents "
        "(programmed common response). Alignment beyond that requires interaction: compare with no_social.",
    }


# ----------------------------------------------------------------------------- liquidity
def liquidity_withdrawal(smp: Samples, shock_window_ms: tuple[int, int] | None = None) -> dict[str, Any]:
    mm = np.array([d.get("market_maker", 0.0) for d in smp.depth_by_kind])
    tot = np.array([sum(d.values()) for d in smp.depth_by_kind])
    t = np.array(smp.t_ms)
    lag = 30  # 5 min at 10 s sampling
    low = np.zeros(len(mm), dtype=bool)
    for i in range(lag, len(mm)):
        ref = float(np.median(mm[i - lag : i]))
        low[i] = ref > 0 and mm[i] < WITHDRAWAL_FRAC * ref
    episodes = int(np.sum(low[1:] & ~low[:-1])) + int(low[0]) if len(low) else 0
    outside = low.copy()
    if shock_window_ms:
        outside &= ~((t >= shock_window_ms[0]) & (t < shock_window_ms[1] + 120_000))
    return {
        "mm_near_depth_btc_median": float(np.median(mm)) if len(mm) else float("nan"),
        "mm_share_of_near_depth": float(np.median(mm / np.maximum(tot, 1e-9))) if len(mm) else float("nan"),
        "frac_time_mm_withdrawn": float(np.mean(low)) if len(low) else float("nan"),
        "withdrawal_episodes": episodes,
        "frac_time_withdrawn_outside_shock": float(np.mean(outside)) if len(low) else float("nan"),
        "basis": "MM quote size and inventory limits are programmed; an episode outside any imposed shock "
        "is an endogenous response to order flow / inventory (still a programmed rule, triggered by others).",
    }


# ----------------------------------------------------------------------------- panic
def panic_contagion(sim: Simulation, n_perm: int = 200) -> dict[str, Any]:
    """Share of panic sales preceded (<=60 s) by a panic of a network neighbour, vs a permutation null."""
    ev = [(d["t"], a.id) for a in sim.agents for d in a.decisions if d.get("action") == "panic_sell"]
    ev.sort()
    nbr = [set(n) for n in sim.social.neighbors]

    def share(evs: list[tuple[int, int]]) -> float:
        if not evs:
            return float("nan")
        hit = 0
        for i, (t, aid) in enumerate(evs):
            hit += any(t - t2 <= PANIC_WINDOW_MS and a2 in nbr[aid] for t2, a2 in evs[:i] if t2 < t)
        return hit / len(evs)

    obs = share(ev)
    null = []
    if len(ev) >= 3:
        rng = random.Random(f"panic:{sim.cfg.seed}")
        ids = [a.id for a in sim.agents if a.kind == "noise"]
        for _ in range(n_perm):
            null.append(share([(t, rng.choice(ids)) for t, _ in ev]))
    p = float(np.mean([x >= obs for x in null])) if null else float("nan")
    return {
        "panic_events": len(ev),
        "panicking_agents": len({a for _, a in ev}),
        "neighbour_preceded_share": obs,
        "null_share_mean": float(np.mean(null)) if null else float("nan"),
        "perm_p_value": p,
        "basis": "PROGRAMMED trigger: noise.py panics only when drawdown > panic_dd AND neighbour stance "
        "< -0.3, so neighbour dependence is built in. What is not built in: whether panics chain in time.",
    }


# ----------------------------------------------------------------------------- liquidations
def liquidation_cascades(sim: Simulation) -> dict[str, Any]:
    log = sorted(sim.liquidation_log, key=lambda x: x["t"])
    clusters: list[list[dict[str, Any]]] = []
    for e in log:
        if clusters and e["t"] - clusters[-1][-1]["t"] <= CASCADE_GAP_MS:
            clusters[-1].append(e)
        else:
            clusters.append([e])
    ext = [e["t"] for e in log if e["kind"] == "external"]
    secondary = (
        [e for e in log if e["kind"] != "external" and 0 < e["t"] - ext[0] <= SECONDARY_WINDOW_MS] if ext else []
    )
    return {
        "liquidations": len(log),
        "external_liquidations": len(ext),
        "clusters": len(clusters),
        "max_cluster_size": max((len(c) for c in clusters), default=0),
        "multi_agent_clusters": sum(len({e["agent"] for e in c}) > 1 for c in clusters),
        "secondary_after_external_300s": len(secondary),
        "secondary_kinds": dict(
            sorted({k: sum(e["kind"] == k for e in secondary) for k in {e["kind"] for e in secondary}}.items())
        ),
        "basis": "liquidation is a programmed engine rule; a cascade (one liquidation's price impact pushing "
        "other accounts under maintenance margin) is an interaction outcome.",
    }


# ----------------------------------------------------------------------------- momentum
def _aggressor_flow_by_kind(sim: Simulation, venue: int | None = None) -> dict[str, np.ndarray]:
    n = int(sim.cfg.duration_s // 60)
    out: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(n))
    na = len(sim.agents)
    for tr in sim.exchange.trades:
        if venue is not None and tr.venue != venue:
            continue
        m = tr.t // 60_000
        if m >= n:
            continue
        aid = tr.buyer if tr.aggressor_side > 0 else tr.seller
        k = sim.agents[aid].kind if aid < na else "external"
        out[k][m] += tr.aggressor_side * tr.qty / 1e4
    return dict(out)


def momentum_amplification(sim: Simulation) -> dict[str, Any]:
    a = np.array(sim.series, dtype=float)
    cols = sim.series_columns()
    mid = a[:, cols.index("mid_0")] / 100
    r = minute_returns(mid)  # r[m] = return over minute m+1 (minute 0 has no prior close)
    flows = _aggressor_flow_by_kind(sim)
    trend = np.zeros(int(sim.cfg.duration_s // 60))
    for k in ("momentum", "leveraged"):
        if k in flows:
            trend += flows[k]
    f = trend[1 : 1 + len(r)]
    fb = _corr(f[1:], r[:-1])  # flow in minute m vs return in minute m-1 (chasing)
    imp = _corr(f, r)  # flow vs same-minute return (pushing)
    tot = sum(np.abs(v).sum() for v in flows.values())
    return {
        "trend_flow_share_of_aggressive_volume": float(np.abs(trend).sum() / tot) if tot else float("nan"),
        "corr_trend_flow_vs_lagged_return": fb,
        "corr_trend_flow_vs_same_minute_return": imp,
        "feedback_loop_present": bool(fb > 0.1 and imp > 0.1) if np.isfinite(fb) and np.isfinite(imp) else False,
        "basis": "chasing past returns is PROGRAMMED (momentum/leveraged policies). The loop closes only if "
        "their flow then moves price, which depends on liquidity supplied by others (interaction).",
    }


# ----------------------------------------------------------------------------- influence
def _gini(x: np.ndarray) -> float:
    x = np.sort(np.asarray(x, float))
    if x.sum() <= 0:
        return float("nan")
    n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def influence_concentration(sim: Simulation) -> dict[str, Any]:
    na = len(sim.agents)
    vol = np.zeros(na)
    taker = np.zeros(na)
    for tr in sim.exchange.trades:
        q = tr.qty / 1e4
        for aid in (tr.buyer, tr.seller):
            if aid < na:
                vol[aid] += q
        aid = tr.buyer if tr.aggressor_side > 0 else tr.seller
        if aid < na:
            taker[aid] += q
    share = vol / vol.sum() if vol.sum() else vol
    tshare = taker / taker.sum() if taker.sum() else taker
    k = kinds(sim)
    top = np.argsort(-tshare)[:10]
    return {
        "volume_hhi": float(np.sum(share**2)),
        "volume_gini": _gini(vol),
        "taker_volume_hhi": float(np.sum(tshare**2)),
        "taker_top10_share": float(tshare[top].sum()),
        "taker_top10_kinds": dict(sorted({kd: int(np.sum(k[top] == kd)) for kd in set(k[top])}.items())),
        "hhi_equal_share_reference": 1 / na,
        "basis": "concentration partly reflects programmed capital/size heterogeneity; a change under ablation "
        "with the same population shows interaction-driven concentration.",
    }


# ----------------------------------------------------------------------------- regimes
def regime_transitions(sim: Simulation) -> dict[str, Any]:
    a = np.array(sim.series, dtype=float)
    mid = a[:, sim.series_columns().index("mid_0")] / 100
    r = minute_returns(mid)
    if len(r) < 2 * REGIME_WIN_MIN:
        return {"switches": 0, "basis": "run too short"}
    rv = np.array([np.std(r[i - REGIME_WIN_MIN : i]) for i in range(REGIME_WIN_MIN, len(r) + 1)])
    med = float(np.median(rv))
    raw = rv > REGIME_HIGH * med
    # enforce minimum dwell so single noisy minutes do not count as regimes
    state = raw.copy()
    cur, run = state[0], 0
    for i in range(len(state)):
        if raw[i] != cur:
            run += 1
            if run >= REGIME_MIN_DWELL_MIN:
                cur = raw[i]
                run = 0
        else:
            run = 0
        state[i] = cur
    return {
        "switches": int(np.sum(state[1:] != state[:-1])),
        "frac_time_high_vol": float(np.mean(state)),
        "rolling_vol_max_over_median": float(rv.max() / med) if med > 0 else float("nan"),
        "basis": "descriptive only: switches can be driven by exogenous news/fundamental jumps; attribute "
        "only via ablations with a frozen or smooth fundamental.",
    }


# ----------------------------------------------------------------------------- clustering
def _kmeans(X: np.ndarray, k: int, seed: int, iters: int = 50) -> np.ndarray:
    rng = np.random.default_rng(seed)
    c = [X[rng.integers(len(X))]]
    for _ in range(1, k):
        d = np.min([((X - ci) ** 2).sum(1) for ci in c], axis=0)
        c.append(X[rng.choice(len(X), p=d / d.sum())] if d.sum() > 0 else X[rng.integers(len(X))])
    C = np.array(c)
    lab = np.zeros(len(X), dtype=int)
    for _ in range(iters):
        lab = np.argmin(((X[:, None, :] - C[None]) ** 2).sum(2), axis=1)
        newC = np.array([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
        if np.allclose(newC, C):
            break
        C = newC
    return lab


def adjusted_rand_index(a: np.ndarray, b: np.ndarray) -> float:
    from math import comb

    ua, ia = np.unique(a, return_inverse=True)
    ub, ib = np.unique(b, return_inverse=True)
    M = np.zeros((len(ua), len(ub)), dtype=int)
    np.add.at(M, (ia, ib), 1)
    s = sum(comb(int(x), 2) for x in M.ravel())
    sa = sum(comb(int(x), 2) for x in M.sum(1))
    sb = sum(comb(int(x), 2) for x in M.sum(0))
    n = comb(len(a), 2)
    exp = sa * sb / n if n else 0
    mx = (sa + sb) / 2
    # mx == exp only when both partitions are all-singletons or both one cluster: identical (sklearn convention)
    return float((s - exp) / (mx - exp)) if mx != exp else 1.0


def agent_features(sim: Simulation, smp: Samples) -> np.ndarray:
    na = len(sim.agents)
    vol = np.zeros(na)
    taker = np.zeros(na)
    signed = np.zeros(na)
    for tr in sim.exchange.trades:
        q = tr.qty / 1e4
        if tr.buyer < na:
            vol[tr.buyer] += q
            signed[tr.buyer] += q
        if tr.seller < na:
            vol[tr.seller] += q
            signed[tr.seller] -= q
        aid = tr.buyer if tr.aggressor_side > 0 else tr.seller
        if aid < na:
            taker[aid] += q
    S = smp.stance_matrix()
    orders = np.array([a.orders_sent for a in sim.agents], float)
    wakes = np.array([max(1, a.wakes) for a in sim.agents], float)
    X = np.column_stack(
        [
            np.log1p(vol),
            taker / np.maximum(vol, 1e-9),
            signed / np.maximum(vol, 1e-9),
            S.mean(0),
            S.std(0),
            np.log1p(orders / wakes),
        ]
    )
    sd = X.std(0)
    return (X - X.mean(0)) / np.where(sd > 0, sd, 1)


def behavioral_clustering(sim: Simulation, smp: Samples) -> dict[str, Any]:
    X = agent_features(sim, smp)
    k = kinds(sim)
    nk = len(set(k))
    lab = _kmeans(X, nk, sim.cfg.seed)
    ari = adjusted_rand_index(lab, k)
    # within-kind divergence: share of agents outside their kind's modal behavioural cluster
    div = {}
    for kd in sorted(set(k)):
        ls = lab[k == kd]
        div[kd] = float(1 - np.bincount(ls).max() / len(ls))
    return {
        "n_clusters": nk,
        "ari_cluster_vs_programmed_kind": ari,
        "within_kind_divergence": div,
        "basis": "ARI near 1 = observed behaviour is fully explained by programmed type; lower values mean "
        "agents of one type behave differently (parameters, state, or interaction). Not causal by itself.",
    }


def all_metrics(sim: Simulation, smp: Samples, shock_window_ms: tuple[int, int] | None = None) -> dict[str, Any]:
    return _clean(
        {
            "herding": herding(sim, smp),
            "liquidity_withdrawal": liquidity_withdrawal(smp, shock_window_ms),
            "panic_contagion": panic_contagion(sim),
            "liquidation_cascades": liquidation_cascades(sim),
            "momentum_amplification": momentum_amplification(sim),
            "influence_concentration": influence_concentration(sim),
            "regime_transitions": regime_transitions(sim),
            "behavioral_clustering": behavioral_clustering(sim, smp),
        }
    )
