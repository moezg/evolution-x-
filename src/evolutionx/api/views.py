"""Read-model projections of a live simulation for the dashboard (CQRS read side).

The dashboard needs aggregated, denormalised views (candles, clusters, graph)
that differ from the write model; these functions compute them on demand.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..evaluation.metrics import gini, performance_by_kind, run_metrics
from ..kernel.units import cash_to_usd
from ..sim.persist import data_label


def state(sim, status: str, speed: float) -> dict[str, Any]:  # noqa: ANN001
    marks = sim.exchange.marks()
    return {
        "status": status,
        "speed": speed,
        "t_ms": sim.now,
        "duration_ms": sim.cfg.duration_s * 1000,
        "seed": sim.cfg.seed,
        "mode": sim.cfg.mode,
        "data_label": data_label(sim),
        "config_fingerprint": sim.cfg.fingerprint(),
        "events_processed": sim.events_processed,
        "wall_time_s": round(sim.wall_time_s, 3),
        "events_per_s": round(sim.events_processed / max(sim.wall_time_s, 1e-9)),
        "n_agents": len(sim.agents),
        "counts": sim.counts,
        "venues": [
            {
                "name": v.cfg.name,
                "mid": marks[i] / 100,
                "last": (v.last_price or 0) / 100,
                "bid": (v.book.best_bid() or 0) / 100,
                "ask": (v.book.best_ask() or 0) / 100,
                "volume_btc": v.volume / 1e4,
                "trades": v.n_trades,
                "halted": v.halted(sim.now),
            }
            for i, v in enumerate(sim.exchange.venues)
        ],
        "funding_rate": sim.funding_rate,
        "latent_fundamental": round(sim.world.value, 2),
        "n_trades": len(sim.exchange.trades),
        "liquidations": len(sim.liquidation_log),
        "influence_events": len(sim.influence_events),
        "insurance_fund_usd": cash_to_usd(sim.clearing.insurance_fund),
        "fee_pool_usd": cash_to_usd(sim.clearing.fee_pool),
        "rejections": sim.exchange.rejections,
        "shocks": [s.model_dump() for s in sim.cfg.shocks],
        "historical": sim.historical and {k: v for k, v in sim.historical.items() if k != "path"},
    }


def candles(sim, venue: int = 0) -> list[dict[str, Any]]:  # noqa: ANN001
    return [
        {"t": m * 60, "open": c[0], "high": c[1], "low": c[2], "close": c[3], "volume": round(c[4], 4), "trades": c[5]}
        for m, c in sorted(sim.candles[venue].items())
    ]


def historical_overlay(sim) -> list[dict[str, Any]]:  # noqa: ANN001
    if not sim.historical:
        return []
    return [{"t": t // 1000, "close": p} for t, p in sim.historical["path"] if t <= sim.now]


def book(sim, venue: int = 0, levels: int = 20) -> dict[str, Any]:  # noqa: ANN001
    bids, asks = sim.exchange.venues[venue].book.depth(levels)
    return {
        "venue": venue,
        "t_ms": sim.now,
        "bids": [[p / 100, q / 1e4] for p, q in bids],
        "asks": [[p / 100, q / 1e4] for p, q in asks],
    }


def series(sim, step: int = 5) -> dict[str, list]:  # noqa: ANN001
    cols = sim.series_columns()
    rows = sim.series[::step]
    out: dict[str, list] = {c: [] for c in cols}
    for r in rows:
        for c, v in zip(cols, r, strict=True):
            out[c].append(None if isinstance(v, float) and not math.isfinite(v) else v)
    out["t"] = [t // 1000 for t in out["t"]]
    for c in cols:
        if c.startswith("mid_"):
            out[c] = [v / 100 for v in out[c]]
    out["volume"] = [v / 1e4 for v in out["volume"]]
    out["depth"] = [v / 1e4 for v in out["depth"]]
    return out


def trades(sim, limit: int = 100, agent: int | None = None) -> list[dict[str, Any]]:  # noqa: ANN001
    tr = sim.exchange.trades
    if agent is not None:
        tr = [t for t in tr if t.buyer == agent or t.seller == agent]
    return [
        {
            "id": t.trade_id,
            "t_ms": t.t,
            "venue": t.venue,
            "price": t.price / 100,
            "qty": t.qty / 1e4,
            "buyer": t.buyer,
            "seller": t.seller,
            "aggressor": "buy" if t.aggressor_side > 0 else "sell",
        }
        for t in tr[-limit:]
    ][::-1]


def _agent_row(sim, a, marks) -> dict[str, Any]:  # noqa: ANN001
    acct = sim.clearing.accounts[a.id]
    eq = acct.equity(marks) / 1e6
    gross = acct.gross_notional(marks) / 1e6
    return {
        "id": a.id,
        "kind": a.kind,
        "equity": round(eq, 2),
        "capital": round(a.capital_usd, 2),
        "return_pct": round((eq / a.capital_usd - 1) * 100, 4),
        "positions_btc": [p / 1e4 for p in acct.positions],
        "leverage": round(gross / eq, 3) if eq > 0 else None,
        "max_drawdown_pct": round(a.max_drawdown * 100, 3),
        "reputation": round(a.reputation, 4),
        "stance": round(a.stance, 3),
        "strategy_version": a.strategy_version,
        "orders_sent": a.orders_sent,
        "wakes": a.wakes,
        "liquidations": acct.liquidations,
        "home_venue": a.home_venue,
        "fees_paid_usd": cash_to_usd(acct.fees_paid),
        "funding_paid_usd": cash_to_usd(acct.funding_paid),
    }


def agents(sim) -> list[dict[str, Any]]:  # noqa: ANN001
    marks = sim.exchange.marks()
    return [_agent_row(sim, a, marks) for a in sim.agents]


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_jsonable(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, int | float | str | bool) or o is None:
        return o
    return str(o)


def agent_detail(sim, aid: int) -> dict[str, Any]:  # noqa: ANN001
    a = sim.agents[aid]
    marks = sim.exchange.marks()
    obs = sim.observe(a, sim.now, peek=True) if sim.now > 0 else None
    inputs = None
    if obs is not None:
        inputs = {
            "data_t_ms": obs.data_t,
            "md_latency_ms": a.md_latency_ms,
            "home_venue_view": {
                k: getattr(obs.venues[a.home_venue], k)
                for k in ("bid", "ask", "mid", "last", "depth_bid", "depth_ask", "halted")
            },
            "funding_rate": obs.funding_rate,
            "index_price": obs.index_price / 100,
            "social_signal": round(obs.social, 4),
            "has_private_fundamental": obs.fundamental is not None,
            "equity_usd": obs.equity / 1e6,
            "positions_btc": [p / 1e4 for p in obs.positions],
        }
    memory = {k: v for k, v in a.memory.items() if k not in ("last",)}
    return {
        **_agent_row(sim, a, marks),
        "params": a.params,
        "order_latency_ms": a.order_latency_ms,
        "md_latency_ms": a.md_latency_ms,
        "wake_ms": a.wake_ms,
        "memory": _jsonable(memory),
        "lineage": _jsonable(a.lineage),
        "equity_curve": a.equity_curve,
        "recent_decisions": _jsonable(list(a.decisions)),
        "observable_inputs": _jsonable(inputs),
        "neighbors": list(sim.social.neighbors[aid]),
        "trades": trades(sim, 50, aid),
        "open_orders": [
            {
                "id": o.order_id,
                "venue": o.venue,
                "side": "buy" if o.side > 0 else "sell",
                "price": o.price / 100,
                "qty": o.qty / 1e4,
            }
            for o in sim.exchange.agent_orders.get(aid, {}).values()
        ][:50],
    }


def network(sim) -> dict[str, Any]:  # noqa: ANN001
    return {
        "nodes": [
            {"id": a.id, "kind": a.kind, "stance": round(a.stance, 3), "reputation": round(a.reputation, 3)}
            for a in sim.agents
        ],
        "edges": sim.social.edges(),
        "enabled": sim.social.enabled,
    }


def _kmeans(x: np.ndarray, k: int, iters: int = 25) -> np.ndarray:
    # deterministic init: evenly spaced points along the first principal axis
    order = np.argsort(x[:, 0] + 1e-6 * np.arange(len(x)))
    centers = x[order[np.linspace(0, len(x) - 1, k).astype(int)]]
    labels = np.zeros(len(x), dtype=int)
    for _ in range(iters):
        d = ((x[:, None, :] - centers[None]) ** 2).sum(-1)
        labels = d.argmin(1)
        for j in range(k):
            if (labels == j).any():
                centers[j] = x[labels == j].mean(0)
    return labels


def collective(sim) -> dict[str, Any]:  # noqa: ANN001
    rows = agents(sim)
    feats = np.array(
        [
            [
                r["stance"],
                r["orders_sent"] / max(r["wakes"], 1),
                r["return_pct"],
                r["leverage"] or 0.0,
                r["max_drawdown_pct"],
            ]
            for r in rows
        ],
        dtype=float,
    )
    z = (feats - feats.mean(0)) / (feats.std(0) + 1e-9)
    labels = _kmeans(z, 5)
    clusters = []
    for j in range(5):
        members = [r for r, lab in zip(rows, labels, strict=True) if lab == j]
        if not members:
            continue
        comp: dict[str, int] = {}
        for m in members:
            comp[m["kind"]] = comp.get(m["kind"], 0) + 1
        clusters.append(
            {
                "id": j,
                "size": len(members),
                "composition": comp,
                "mean_stance": float(np.mean([m["stance"] for m in members])),
                "mean_return_pct": float(np.mean([m["return_pct"] for m in members])),
                "mean_leverage": float(np.mean([m["leverage"] or 0 for m in members])),
                "members": [m["id"] for m in members],
            }
        )
    eq = [r["equity"] for r in rows]
    hist, edges = np.histogram(np.log10(np.maximum(eq, 1)), bins=20)
    per_min: dict[int, int] = {}
    for e in sim.influence_events:
        per_min[e["t"] // 60_000] = per_min.get(e["t"] // 60_000, 0) + 1
    panic = sum(a.memory.get("panic_events", 0) for a in sim.agents)
    withdrawals = sum(a.memory.get("withdrawals", 0) for a in sim.agents)
    return {
        "clusters": clusters,
        "cluster_labels": [int(x) for x in labels],
        "wealth": {"gini": gini(eq), "log10_hist": hist.tolist(), "log10_edges": edges.tolist()},
        "by_kind": performance_by_kind(sim),
        "influence_recent": sim.influence_events[-100:][::-1],
        "influence_per_minute": [{"minute": m, "count": c} for m, c in sorted(per_min.items())],
        "panic_events": panic,
        "mm_withdrawals": withdrawals,
        "imitation_events": sum(1 for e in sim.sim_events if e.type == "imitation"),
        "liquidations_recent": sim.liquidation_log[-50:][::-1],
        "stance_by_kind": {
            k: float(np.mean([a.stance for a in sim.agents if a.kind == k])) for k in sim.counts if sim.counts[k]
        },
    }


def events(sim, types: set[str] | None = None, limit: int = 200) -> list[dict[str, Any]]:  # noqa: ANN001
    ev = sorted(sim.exchange.events + sim.sim_events, key=lambda e: e.t)
    if types:
        ev = [e for e in ev if e.type in types]
    return [
        {"t_ms": e.t, "type": e.type, "agent": e.agent, "venue": e.venue, "data": _jsonable(e.data)}
        for e in ev[-limit:]
    ][::-1]


def metrics(sim) -> dict[str, Any]:  # noqa: ANN001
    return run_metrics(sim) if len(sim.series) > 120 else {}
