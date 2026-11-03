"""Market makers: layered two-sided quotes, inventory skew, volatility withdrawal."""

from __future__ import annotations

from ..agents.base import Agent, CancelAll, Command, Limit, Observation
from .common import btc, realized_vol_bps


def decide(agent: Agent, obs: Observation) -> list[Command]:
    p = agent.params
    v = agent.home_venue
    view = obs.venues[v]
    other = obs.venues[1 - v] if len(obs.venues) > 1 else view
    if view.halted:
        return [CancelAll(v)]
    ref = (1 - p["index_w"]) * (0.8 * view.mid + 0.2 * other.mid) + p["index_w"] * obs.index_price
    inv_btc = obs.positions[v] / 1e4
    vol = realized_vol_bps(agent, 20)
    scale = agent.memory.get("liquidity_scale", 1.0)  # scenario-controlled (e.g. liquidity drought)
    hs = p["half_spread_bps"]
    size = p["quote_btc"] * scale
    withdrawing = vol > p["vol_withdraw_bps"]
    if withdrawing:
        hs *= 3
        size *= 0.3
        agent.memory["withdrawals"] = agent.memory.get("withdrawals", 0) + 1
    skew = p["skew_bps_per_btc"] * inv_btc
    q = btc(size)
    cmds: list[Command] = [CancelAll(v)]
    agent.stance = -max(-1.0, min(1.0, inv_btc / p["max_inv_btc"]))
    agent.decisions.append({"t": obs.t, "ref": int(ref), "vol_bps": round(vol, 2), "inv_btc": round(inv_btc, 3),
                            "withdrawing": withdrawing, "half_spread_bps": round(hs, 2)})
    if q <= 0:
        return cmds
    for i in range(int(p["levels"])):
        off = hs + i * p["level_step_bps"]
        if inv_btc < p["max_inv_btc"]:
            cmds.append(Limit(v, 1, q, max(1, int(ref * (1 - (off + skew) / 1e4)))))
        if inv_btc > -p["max_inv_btc"]:
            cmds.append(Limit(v, -1, q, max(1, int(ref * (1 + (off - skew) / 1e4)) + 1)))
    return cmds
