"""Public market-data snapshots and latency-respecting observations.

Agents never touch the Exchange or ClearingHouse directly. They receive an
Observation built from the latest public snapshot published at or before
(now - their market-data latency). This enforces "no look-ahead" structurally.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VenueView:
    bid: int | None
    ask: int | None
    bid_qty: int
    ask_qty: int
    depth_bid: int  # lots in top-5 levels
    depth_ask: int
    last: int | None
    mid: int
    volume: int  # cumulative lots
    halted: bool


@dataclass(frozen=True, slots=True)
class Snapshot:
    t: int
    venues: tuple[VenueView, ...]
    funding_rate: float
    index_price: int


class MarketDataFeed:
    def __init__(self) -> None:
        self.snapshots: list[Snapshot] = []
        self._times: list[int] = []

    def publish(self, snap: Snapshot) -> None:
        self.snapshots.append(snap)
        self._times.append(snap.t)

    def as_of(self, t: int) -> Snapshot | None:
        i = bisect_right(self._times, t)
        return self.snapshots[i - 1] if i else None


def take_snapshot(exchange, t: int, funding_rate: float, index_price: int) -> Snapshot:  # noqa: ANN001
    views = []
    for v in exchange.venues:
        bids, asks = v.book.depth(5)
        mid = v.mid()
        views.append(
            VenueView(
                bid=bids[0][0] if bids else None,
                ask=asks[0][0] if asks else None,
                bid_qty=bids[0][1] if bids else 0,
                ask_qty=asks[0][1] if asks else 0,
                depth_bid=sum(q for _, q in bids),
                depth_ask=sum(q for _, q in asks),
                last=v.last_price,
                mid=mid if mid is not None else exchange.initial_price,
                volume=v.volume,
                halted=v.halted(t),
            )
        )
    return Snapshot(t, tuple(views), funding_rate, index_price)
