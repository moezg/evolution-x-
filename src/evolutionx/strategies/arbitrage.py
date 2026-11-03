"""Cross-venue arbitrage: take crossed quotes across venues, unwind on convergence."""

from __future__ import annotations

from ..agents.base import Agent, Command, Limit, Observation
from .common import btc

TAKER_BPS = 5.0


def decide(agent: Agent, obs: Observation) -> list[Command]:
    if len(obs.venues) < 2 or agent.memory.get("disabled_until", -1) > obs.t:
        return []
    p = agent.params
    a, b = obs.venues[0], obs.venues[1]
    edge = (2 * TAKER_BPS + p["threshold_bps"]) / 1e4
    max_q = btc(p["max_btc"])
    inv = btc(p["max_inv_btc"])
    cmds: list[Command] = []
    for lo, hi, vlo, vhi in ((a, b, 0, 1), (b, a, 1, 0)):
        if lo.ask is None or hi.bid is None or lo.halted or hi.halted:
            continue
        if hi.bid > lo.ask * (1 + edge):
            q = min(max_q, lo.ask_qty, hi.bid_qty, inv - max(0, obs.positions[vlo]))
            if q > 0:
                cmds += [Limit(vlo, 1, q, lo.ask, ioc=True), Limit(vhi, -1, q, hi.bid, ioc=True)]
                agent.decisions.append({"t": obs.t, "buy_venue": vlo, "edge_bps": round((hi.bid / lo.ask - 1) * 1e4, 2), "qty": q})
    # unwind converged legs
    pa, pb = obs.positions[0], obs.positions[1]
    if not cmds and pa and pb and (pa > 0) != (pb > 0):
        q = min(abs(pa), abs(pb), max_q)
        long_v, short_v = (0, 1) if pa > 0 else (1, 0)
        lv, sv = obs.venues[long_v], obs.venues[short_v]
        if lv.bid is not None and sv.ask is not None and lv.bid >= sv.ask:
            cmds += [Limit(long_v, -1, q, lv.bid, ioc=True), Limit(short_v, 1, q, sv.ask, ioc=True)]
    # residual single-leg exposure (a leg failed to fill): flatten net
    net = pa + pb
    if not cmds and abs(net) > btc(0.05):
        v = 0 if abs(pa) >= abs(pb) else 1
        view = obs.venues[v]
        side = -1 if net > 0 else 1
        px = view.bid if side < 0 else view.ask
        if px:
            cmds.append(Limit(v, side, min(abs(net), max_q), px, ioc=True))
    agent.stance = 0.0
    return cmds
