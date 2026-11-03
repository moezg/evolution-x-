"""Agent state, observations and validated commands.

Actor-style ownership: an Agent owns its private state (params, memory, beliefs,
RNG). The simulation is the only caller of its policy, and the policy's only
output is a list of Commands, which are validated before reaching the exchange.
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..kernel.marketdata import VenueView
from ..sim.world import News

# ---------------------------------------------------------------- commands


@dataclass(frozen=True, slots=True)
class Limit:
    venue: int
    side: int
    qty: int
    price: int
    ioc: bool = False


@dataclass(frozen=True, slots=True)
class Market:
    venue: int
    side: int
    qty: int


@dataclass(frozen=True, slots=True)
class CancelAll:
    venue: int | None = None


Command = Limit | Market | CancelAll


def validate_command(cmd: object, n_venues: int, max_lots: int) -> bool:
    if isinstance(cmd, CancelAll):
        return cmd.venue is None or (isinstance(cmd.venue, int) and 0 <= cmd.venue < n_venues)
    if isinstance(cmd, Limit | Market):
        ok = (isinstance(cmd.qty, int) and 0 < cmd.qty <= max_lots and cmd.side in (1, -1)
              and isinstance(cmd.venue, int) and 0 <= cmd.venue < n_venues)
        if isinstance(cmd, Limit):
            ok = ok and isinstance(cmd.price, int) and cmd.price > 0
        return ok
    return False


# ---------------------------------------------------------------- observation


@dataclass(frozen=True, slots=True)
class Observation:
    """Everything an agent may legitimately know at decision time."""

    t: int  # agent's local clock (true now; data inside is delayed)
    data_t: int  # timestamp of the market snapshot used
    venues: tuple[VenueView, ...]
    funding_rate: float
    index_price: int
    cash: int
    positions: tuple[int, ...]
    equity: int  # marked at observed mids
    open_orders: int
    news: tuple[News, ...]  # headlines that reached this agent since its last wake
    social: float  # reputation-weighted neighbour stance in [-1, 1]
    fundamental: float | None  # private noisy estimate (USD) if this agent has research access


# ---------------------------------------------------------------- agent


Policy = Callable[["Agent", Observation], list[Command]]


@dataclass(slots=True)
class Agent:
    id: int
    kind: str
    policy_name: str
    params: dict[str, float]
    rng: random.Random
    wake_ms: int
    order_latency_ms: int
    md_latency_ms: int
    home_venue: int
    capital_usd: float
    max_leverage: float
    strategy_version: int = 1
    memory: dict[str, Any] = field(default_factory=dict)
    mids: deque = field(default_factory=lambda: deque(maxlen=600))  # (t, mid ticks) private memory
    stance: float = 0.0  # last published directional view [-1,1]
    active: bool = True
    reputation: float = 1.0
    peak_equity: float = 0.0
    max_drawdown: float = 0.0
    equity_curve: list[tuple[int, float]] = field(default_factory=list)  # (t, USD)
    lineage: list[dict[str, Any]] = field(default_factory=list)
    decisions: deque = field(default_factory=lambda: deque(maxlen=20))  # recent decision traces
    last_news_t: int = -1
    wakes: int = 0
    orders_sent: int = 0

    def record_strategy_change(self, t: int, reason: str, new_params: dict[str, float], source: int | None) -> None:
        self.lineage.append({"t": t, "version": self.strategy_version + 1, "reason": reason,
                             "source_agent": source, "before": dict(self.params), "after": dict(new_params)})
        self.params = dict(new_params)
        self.strategy_version += 1
