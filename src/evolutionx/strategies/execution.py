"""Algorithmic execution (TWAP-style) of exogenous institutional parent orders."""

from __future__ import annotations

from ..agents.base import Agent, Command, Limit, Observation
from .common import btc, take


def decide(agent: Agent, obs: Observation) -> list[Command]:
    p = agent.params
    m = agent.memory
    parent = m.get("parent")
    if parent is None:
        if agent.rng.random() < p["p_new"]:
            side = 1 if agent.rng.random() < 0.5 else -1
            total = max(10, btc(p["parent_btc"] * agent.rng.lognormvariate(0, 0.5)))
            parent = {
                "side": side,
                "total": total,
                "done": 0,
                "start": obs.t,
                "end": obs.t + int(p["horizon_s"] * 1000),
            }
            m["parent"] = parent
            m["parents_started"] = m.get("parents_started", 0) + 1
        else:
            return []
    # infer progress from own positions (fills are not reported directly)
    pos = sum(obs.positions)
    if "pos0" not in parent:
        parent["pos0"] = pos
    done = (pos - parent["pos0"]) * parent["side"]
    remaining = parent["total"] - done
    if remaining <= 10 or obs.t > parent["end"] + 120_000:
        m["parent"] = None
        return []
    frac = min(1.0, (obs.t - parent["start"]) / max(1, parent["end"] - parent["start"]))
    behind = int(parent["total"] * frac) - done
    agent.stance = 0.5 * parent["side"]
    if behind <= 0:
        return []
    side = parent["side"]
    # choose the venue with the better price for our side
    vs = obs.venues
    v = min(range(len(vs)), key=lambda i: (vs[i].ask or 10**12) if side > 0 else -(vs[i].bid or 0))
    qty = min(behind, remaining)
    agent.decisions.append({"t": obs.t, "behind": behind, "frac": round(frac, 3), "venue": v})
    if agent.rng.random() < p["urgency"] or obs.t > parent["end"]:
        return take(obs, v, side, qty, 30)
    touch = vs[v].bid if side > 0 else vs[v].ask
    return [Limit(v, side, qty, touch)] if touch else take(obs, v, side, qty, 30)
