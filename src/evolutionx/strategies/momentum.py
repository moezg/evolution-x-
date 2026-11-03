"""Trend followers: own price memory + socially transmitted momentum."""

from __future__ import annotations

import math

from ..agents.base import Agent, Command, Observation
from .common import btc, clip, ret_bps, trade_toward


def decide(agent: Agent, obs: Observation) -> list[Command]:
    p = agent.params
    v = agent.home_venue
    r = ret_bps(agent, p["lookback_s"] * 1000)
    if r is None:
        return []
    own = math.tanh(r / p["threshold_bps"])
    sw = p["social_w"]
    signal = clip((1 - sw) * own + sw * obs.social)
    if abs(own) > 0.2 and (signal * own) < 0:
        agent.memory["social_override"] = agent.memory.get("social_override", 0) + 1
    agent.stance = signal
    target = int(signal * btc(p["max_btc"]))
    agent.decisions.append(
        {"t": obs.t, "ret_bps": round(r, 2), "own": round(own, 3), "social": round(obs.social, 3), "target": target}
    )
    return trade_toward(obs, v, target, btc(p["max_btc"]) // 2 + 1, p["slip_bps"])
