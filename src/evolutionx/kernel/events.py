"""Deterministic discrete-event queue and immutable domain events."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any


class EventQueue:
    """Priority queue ordered by (time_ms, priority, insertion sequence).

    The insertion sequence breaks ties deterministically, so two runs that
    schedule the same events in the same order always pop them identically.
    """

    __slots__ = ("_heap", "_seq", "now")

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, int, str, Any]] = []
        self._seq = 0
        self.now = 0

    def schedule(self, time_ms: int, kind: str, payload: Any = None, priority: int = 5) -> None:
        if time_ms < self.now:
            raise ValueError(f"cannot schedule in the past: {time_ms} < {self.now}")
        self._seq += 1
        heapq.heappush(self._heap, (time_ms, priority, self._seq, kind, payload))

    def pop(self) -> tuple[int, str, Any]:
        t, _p, _s, kind, payload = heapq.heappop(self._heap)
        self.now = t
        return t, kind, payload

    def peek_time(self) -> int | None:
        return self._heap[0][0] if self._heap else None

    def __len__(self) -> int:
        return len(self._heap)


# --- Immutable domain events (event-sourced history) ------------------------


@dataclass(frozen=True, slots=True)
class Trade:
    t: int
    venue: int
    price: int
    qty: int
    buyer: int
    seller: int
    aggressor_side: int  # +1 buyer-initiated, -1 seller-initiated
    buyer_fee: int
    seller_fee: int
    trade_id: int


@dataclass(frozen=True, slots=True)
class SimEvent:
    """Generic typed event for the event log (non-trade)."""

    t: int
    type: str
    agent: int = -1
    venue: int = -1
    data: dict[str, Any] = field(default_factory=dict)
