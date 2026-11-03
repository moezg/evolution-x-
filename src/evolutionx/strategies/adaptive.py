"""Adaptive learning agents: softmax bandit over behavioural modes + risk adaptation.

Level-1 behavioural evolution: the agent changes its own bounded parameters
in response to realised performance; every change is recorded in its lineage.
"""

from __future__ import annotations

import math

from ..agents.base import Agent, Command, Observation
from .common import btc, clip, ret_bps, trade_toward
from .params import clip_params

ARMS = ("momentum", "reversion", "crowd", "flat")


def decide(agent: Agent, obs: Observation) -> list[Command]:
    p = agent.params
    m = agent.memory
    v = agent.home_venue
    q = m.setdefault("q", {a: 0.0 for a in ARMS})
    counts = m.setdefault("counts", {a: 0 for a in ARMS})
    eq = obs.equity / 1e6
    last = m.get("last")
    if last is not None:
        arm, eq0 = last
        reward = (eq - eq0) / max(agent.capital_usd, 1.0) * 1e4  # bps of capital
        q[arm] += p["lr"] * (reward - q[arm])
        counts[arm] += 1
        m["reward_ewm"] = 0.9 * m.get("reward_ewm", 0.0) + 0.1 * reward
    # softmax arm selection
    t = p["temperature"]
    mx = max(q.values())
    w = [math.exp((q[a] - mx) / t) for a in ARMS]
    u = agent.rng.random() * sum(w)
    arm = ARMS[-1]
    for a, wi in zip(ARMS, w, strict=True):
        u -= wi
        if u <= 0:
            arm = a
            break
    m["last"] = (arm, eq)
    m["arm"] = arm
    # bounded risk adaptation every 30 wakes
    if agent.wakes % 30 == 29 and p["risk_adapt"] > 0:
        r = m.get("reward_ewm", 0.0)
        factor = 1 + p["risk_adapt"] * (0.2 if r > 0 else -0.2)
        new = clip_params(agent.kind, {**p, "max_btc": p["max_btc"] * factor})
        if abs(new["max_btc"] - p["max_btc"]) > 1e-9:
            agent.record_strategy_change(obs.t, f"risk_adapt reward_ewm={r:.2f}bps", new, None)
            p = agent.params
    r = ret_bps(agent, p["lookback_s"] * 1000) or 0.0
    if arm == "momentum":
        sig = math.tanh(r / 15)
    elif arm == "reversion":
        sig = -math.tanh(r / 15)
    elif arm == "crowd":
        sig = obs.social
    else:
        sig = 0.0
    sig = clip(sig)
    agent.stance = sig
    target = int(sig * btc(p["max_btc"]))
    agent.decisions.append({"t": obs.t, "arm": arm, "q": {a: round(x, 3) for a, x in q.items()}, "target": target})
    return trade_toward(obs, v, target, btc(p["max_btc"]) // 2 + 1, 25)
