"""Shared helpers for strategy policies (pure functions over observations)."""

from __future__ import annotations

import math

from ..agents.base import Agent, Command, Limit, Observation
from ..kernel.units import LOTS_PER_BTC


def btc(lots_btc: float) -> int:
    return int(lots_btc * LOTS_PER_BTC)


def clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def take(obs: Observation, venue: int, side: int, qty: int, slip_bps: float) -> list[Command]:
    """Marketable IOC limit with slippage protection relative to the observed mid."""
    if qty <= 0:
        return []
    m = obs.venues[venue].mid
    px = int(m * (1 + side * slip_bps / 1e4))
    return [Limit(venue, side, qty, max(px, 1), ioc=True)]


def trade_toward(
    obs: Observation, venue: int, target: int, clip_lots: int, slip_bps: float, min_lots: int = 10
) -> list[Command]:
    diff = target - obs.positions[venue]
    if abs(diff) < min_lots:
        return []
    side = 1 if diff > 0 else -1
    return take(obs, venue, side, min(abs(diff), clip_lots), slip_bps)


def ret_bps(agent: Agent, lookback_ms: float) -> float | None:
    """Return over lookback from the agent's own remembered mids (private memory)."""
    if len(agent.mids) < 2:
        return None
    t_now, p_now = agent.mids[-1]
    cutoff = t_now - lookback_ms
    past = None
    for t, p in agent.mids:
        if t >= cutoff:
            past = p
            break
    if past is None or past <= 0:
        return None
    return (p_now / past - 1) * 1e4


def realized_vol_bps(agent: Agent, n: int = 30) -> float:
    pts = list(agent.mids)[-n:]
    if len(pts) < 3:
        return 0.0
    rs = [math.log(b[1] / a[1]) for a, b in zip(pts, pts[1:], strict=False) if a[1] > 0 and b[1] > 0]
    if len(rs) < 2:
        return 0.0
    mu = sum(rs) / len(rs)
    return math.sqrt(sum((r - mu) ** 2 for r in rs) / (len(rs) - 1)) * 1e4


def news_pressure(obs: Observation) -> float:
    return sum(n.sentiment for n in obs.news)
