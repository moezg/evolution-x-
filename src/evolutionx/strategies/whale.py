"""Large institutional traders: well-informed, lumpy, sliced aggressive execution."""

from __future__ import annotations

import math

from ..agents.base import Agent, Command, Observation
from .common import btc, clip, trade_toward


def decide(agent: Agent, obs: Observation) -> list[Command]:
    p = agent.params
    if obs.fundamental is None or agent.rng.random() > p["p_act"]:
        return []
    v = agent.home_venue
    mid_usd = obs.venues[v].mid / 100
    mis_bps = (obs.fundamental / mid_usd - 1) * 1e4
    x = mis_bps / p["threshold_bps"]
    signal = math.copysign(math.log1p(abs(x)) / math.log(2), x) if abs(x) > 1 else x
    if abs(signal) < 0.3:
        signal = 0.0
    agent.stance = clip(signal)
    target = int(signal * btc(p["size_btc"]))
    chunk = btc(p["size_btc"] / p["chunks"])
    agent.decisions.append({"t": obs.t, "mispricing_bps": round(mis_bps, 2), "target": target})
    return trade_toward(obs, v, target, chunk, p["slip_bps"], min_lots=btc(0.5))
