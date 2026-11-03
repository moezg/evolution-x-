"""Mean-reversion / value traders acting on a private, noisy fundamental estimate."""

from __future__ import annotations

import math

from ..agents.base import Agent, CancelAll, Command, Limit, Observation
from .common import btc, clip, take


def decide(agent: Agent, obs: Observation) -> list[Command]:
    p = agent.params
    v = agent.home_venue
    if obs.fundamental is None:
        return []
    mid_usd = obs.venues[v].mid / 100
    mis_bps = (obs.fundamental / mid_usd - 1) * 1e4
    x = p["k"] * mis_bps / p["threshold_bps"]
    # conviction grows (log-) with mispricing; margin is the binding constraint at extremes
    signal = math.copysign(math.log1p(abs(x)) / math.log(2), x) if abs(x) > 1 else x
    agent.stance = clip(signal)
    target = int(signal * btc(p["max_btc"]))
    diff = target - obs.positions[v]
    agent.decisions.append({"t": obs.t, "mispricing_bps": round(mis_bps, 2), "target": target})
    if abs(diff) < 20:
        return []
    side = 1 if diff > 0 else -1
    qty = min(abs(diff), btc(p["max_btc"]) // 3 + 1)
    if abs(mis_bps) > 3 * p["threshold_bps"]:
        return [CancelAll(v), *take(obs, v, side, qty, min(abs(mis_bps) / 3, 30.0))]
    px = int(obs.venues[v].mid * (1 - side * p["offset_bps"] / 1e4))
    return [CancelAll(v), Limit(v, side, qty, max(px, 1))]
