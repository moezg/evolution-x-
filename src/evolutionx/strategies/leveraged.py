"""Leveraged speculators: momentum + herd, funding-aware, stop-loss; liquidation-prone."""

from __future__ import annotations

import math

from ..agents.base import Agent, Command, Observation
from .common import clip, ret_bps, take, trade_toward


def decide(agent: Agent, obs: Observation) -> list[Command]:
    p = agent.params
    v = agent.home_venue
    m = agent.memory
    if m.get("cooldown_until", -1) > obs.t:
        return []
    pos = obs.positions[v]
    mid = obs.venues[v].mid
    if pos and "entry" in m:
        pnl_bps = (mid / m["entry"] - 1) * 1e4 * (1 if pos > 0 else -1)
        if pnl_bps < -p["stop_bps"]:
            m["cooldown_until"] = obs.t + 120_000
            m["stops"] = m.get("stops", 0) + 1
            agent.decisions.append({"t": obs.t, "action": "stop_loss", "pnl_bps": round(pnl_bps, 1)})
            return take(obs, v, -1 if pos > 0 else 1, abs(pos), 60)
    r = ret_bps(agent, p["lookback_s"] * 1000)
    if r is None:
        return []
    sw = p["social_w"]
    signal = clip((1 - sw) * math.tanh(r / p["threshold_bps"]) + sw * obs.social)
    signal -= clip(obs.funding_rate * p["funding_sens"], -0.5, 0.5)  # paying funding discourages longs
    signal = clip(signal)
    agent.stance = signal
    if abs(signal) < 0.25:
        signal = 0.0
    eq_usd = min(max(obs.equity, 0) / 1e6, 2 * agent.capital_usd)  # sizing capped at 2x initial capital
    target_usd = signal * eq_usd * agent.max_leverage * p["leverage_use"]
    target = int(target_usd / (mid / 100) * 1e4)
    if pos == 0 or (target > 0) != (pos > 0):
        m["entry"] = mid
    agent.decisions.append(
        {"t": obs.t, "ret_bps": round(r, 2), "signal": round(signal, 3), "target": target, "funding": obs.funding_rate}
    )
    return trade_toward(obs, v, target, abs(target) // 2 + 50, 40)
