"""Retail / noise traders: random flow with herding, news reaction and panic."""

from __future__ import annotations

import math

from ..agents.base import Agent, CancelAll, Command, Limit, Observation
from .common import btc, clip, news_pressure, take


def decide(agent: Agent, obs: Observation) -> list[Command]:
    p = agent.params
    v = agent.home_venue
    pos = obs.positions[v]
    cmds: list[Command] = []
    dd = agent.max_drawdown
    # Panic: personal losses + bearish neighbourhood -> dump inventory
    if pos > 0 and dd > p["panic_dd"] and obs.social < -0.3:
        agent.memory["panic_events"] = agent.memory.get("panic_events", 0) + 1
        agent.stance = -1.0
        agent.decisions.append({"t": obs.t, "action": "panic_sell", "dd": round(dd, 4), "social": round(obs.social, 3)})
        return [CancelAll(v), *take(obs, v, -1, pos, 80)]
    if agent.rng.random() > p["p_act"]:
        return cmds
    if agent.rng.random() < 0.3:
        cmds.append(CancelAll(v))
    if pos and agent.rng.random() < p["close_prob"]:
        return cmds + take(obs, v, -1 if pos > 0 else 1, abs(pos) // 2 + 1, 40)
    bias = clip(p["herd"] * obs.social + 0.15 * math.tanh(news_pressure(obs)), -0.9, 0.9)
    p_buy = 0.5 + 0.5 * bias
    side = 1 if agent.rng.random() < p_buy else -1
    agent.stance = bias
    qty = max(1, btc(p["mean_btc"] * agent.rng.lognormvariate(0, 0.8)))
    view = obs.venues[v]
    if agent.rng.random() < p["limit_prob"]:
        off = p["offset_bps"] * agent.rng.random() / 1e4
        px = int(view.mid * (1 - side * off))
        cmds.append(Limit(v, side, qty, max(px, 1)))
    else:
        cmds += take(obs, v, side, qty, 40)
    agent.decisions.append({"t": obs.t, "action": "buy" if side > 0 else "sell", "qty": qty, "bias": round(bias, 3)})
    return cmds
