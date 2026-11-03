"""News/sentiment traders: react to headlines that reach them (with latency)."""

from __future__ import annotations

from ..agents.base import Agent, Command, Observation
from .common import btc, take, trade_toward


def decide(agent: Agent, obs: Observation) -> list[Command]:
    p = agent.params
    v = agent.home_venue
    m = agent.memory
    for n in obs.news:
        if abs(n.sentiment) >= p["react_threshold"]:
            d = 1 if n.sentiment > 0 else -1
            if agent.rng.random() < p["contrarian"]:
                d = -d
            size = btc(p["size_btc"] * min(abs(n.sentiment), 3.0))
            m["target"] = d * size
            m["exit_t"] = obs.t + int(p["hold_s"] * 1000)
            m["reactions"] = m.get("reactions", 0) + 1
            agent.stance = float(d)
            agent.decisions.append({"t": obs.t, "news": n.headline, "sentiment": round(n.sentiment, 2), "dir": d})
    target = m.get("target", 0)
    if target and obs.t > m.get("exit_t", 0):
        m["target"] = target = 0
        agent.stance = 0.0
    if target == 0 and obs.positions[v] == 0:
        return []
    if target == 0:
        pos = obs.positions[v]
        return take(obs, v, -1 if pos > 0 else 1, abs(pos), p["slip_bps"])
    return trade_toward(obs, v, target, abs(target), p["slip_bps"])
