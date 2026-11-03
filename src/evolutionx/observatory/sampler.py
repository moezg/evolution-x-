"""Read-only sampling of agent-level state during a run.

The sampler advances the simulation with `run_until` in fixed steps and records, at each step,
what the public series does not contain: stances by agent, resting depth near the mid by agent kind,
and cumulative panic counters. It never mutates agents or the book, so a sampled run is identical
(same fingerprint) to an unsampled one; tests/test_observatory.py checks that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..sim.config import SimConfig
from ..sim.simulation import Simulation

DIRECTIONAL = ("noise", "momentum", "value", "leveraged", "news", "adaptive", "whale")
NEAR_BPS = 20.0


@dataclass
class Samples:
    t_ms: list[int] = field(default_factory=list)
    stance: list[np.ndarray] = field(default_factory=list)  # per agent, index = agent id
    depth_by_kind: list[dict[str, float]] = field(default_factory=list)  # BTC within NEAR_BPS of mid, venue 0
    panic_total: list[int] = field(default_factory=list)
    mm_depth: list[np.ndarray] = field(default_factory=list)  # per market maker (ordered by id), BTC near mid

    def stance_matrix(self) -> np.ndarray:
        return np.vstack(self.stance) if self.stance else np.zeros((0, 0))


def near_depth_by_kind(
    sim: Simulation, venue: int = 0, near_bps: float = NEAR_BPS, per_agent: dict[int, float] | None = None
) -> dict[str, float]:
    book = sim.exchange.venues[venue].book
    bb, ba = book.best_bid(), book.best_ask()
    out: dict[str, float] = {}
    if bb is None or ba is None:
        return out
    mid = (bb + ba) / 2
    lo, hi = mid * (1 - near_bps / 1e4), mid * (1 + near_bps / 1e4)
    n_agents = len(sim.agents)
    for levels in (book.bids, book.asks):
        for p, q in levels.items():
            if lo <= p <= hi:
                for o in q:
                    k = sim.agents[o.agent].kind if o.agent < n_agents else "external"
                    out[k] = out.get(k, 0.0) + o.qty / 1e4
                    if per_agent is not None and o.agent in per_agent:
                        per_agent[o.agent] += o.qty / 1e4
    return out


def sample(sim: Simulation, step_s: int = 10) -> Samples:
    s = Samples()
    t = 0
    end = sim.cfg.duration_s * 1000
    mm_ids = [a.id for a in sim.agents if a.kind == "market_maker"]
    while t < end and not sim.stopped:
        t = min(end, t + step_s * 1000)
        sim.run_until(t)
        s.t_ms.append(t)
        s.stance.append(np.array([a.stance for a in sim.agents], dtype=float))
        per = dict.fromkeys(mm_ids, 0.0)
        s.depth_by_kind.append(near_depth_by_kind(sim, per_agent=per))
        s.mm_depth.append(np.array([per[i] for i in mm_ids]))
        s.panic_total.append(sum(int(a.memory.get("panic_events", 0)) for a in sim.agents))
    return s


def run_sampled(cfg: SimConfig, step_s: int = 10) -> tuple[Simulation, Samples]:
    sim = Simulation(cfg)
    smp = sample(sim, step_s)
    sim.exchange.check_invariants()
    return sim, smp


def kinds(sim: Simulation) -> np.ndarray:
    return np.array([a.kind for a in sim.agents])


def summary(smp: Samples) -> dict[str, Any]:
    return {"n_samples": len(smp.t_ms), "step_ms": int(np.diff(smp.t_ms)[0]) if len(smp.t_ms) > 1 else None}
