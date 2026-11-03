"""Limit order book with price-time (FIFO) priority.

Pure data structure: it knows nothing about accounts or margin. The exchange
layer calls `match` and receives fills; settlement happens in the clearing house.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from collections import deque
from dataclasses import dataclass

BUY = 1
SELL = -1


@dataclass(slots=True)
class Order:
    order_id: int
    agent: int
    side: int  # BUY / SELL
    price: int  # limit price in ticks
    qty: int  # remaining lots
    t: int  # acceptance time (ms) -> time priority
    venue: int
    orig_qty: int = 0


@dataclass(frozen=True, slots=True)
class Fill:
    maker: Order
    price: int
    qty: int


class OrderBook:
    __slots__ = ("bids", "asks", "bid_prices", "ask_prices", "orders")

    def __init__(self) -> None:
        self.bids: dict[int, deque[Order]] = {}
        self.asks: dict[int, deque[Order]] = {}
        self.bid_prices: list[int] = []  # ascending; best bid = [-1]
        self.ask_prices: list[int] = []  # ascending; best ask = [0]
        self.orders: dict[int, Order] = {}

    # --- queries -------------------------------------------------------------
    def best_bid(self) -> int | None:
        return self.bid_prices[-1] if self.bid_prices else None

    def best_ask(self) -> int | None:
        return self.ask_prices[0] if self.ask_prices else None

    def level_qty(self, side: int, price: int) -> int:
        levels = self.bids if side == BUY else self.asks
        q = levels.get(price)
        return sum(o.qty for o in q) if q else 0

    def depth(self, n: int = 10) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        bids = [(p, sum(o.qty for o in self.bids[p])) for p in reversed(self.bid_prices[-n:])]
        asks = [(p, sum(o.qty for o in self.asks[p])) for p in self.ask_prices[:n]]
        return bids, asks

    # --- mutation ------------------------------------------------------------
    def match(self, side: int, price: int | None, qty: int, agent: int) -> tuple[list[Fill], int, list[Order]]:
        """Match an incoming order against the opposite side.

        price=None means market order. Returns (fills, remaining_qty, self_trade_cancels).
        Self-trade prevention: resting orders of the same agent are cancelled
        (cancel-resting policy) instead of being matched.
        """
        fills: list[Fill] = []
        stp_cancels: list[Order] = []
        if side == BUY:
            prices, levels = self.ask_prices, self.asks
        else:
            prices, levels = self.bid_prices, self.bids
        while qty > 0 and prices:
            best = prices[0] if side == BUY else prices[-1]
            if price is not None and ((side == BUY and best > price) or (side == SELL and best < price)):
                break
            queue = levels[best]
            while qty > 0 and queue:
                maker = queue[0]
                if maker.agent == agent:
                    queue.popleft()
                    del self.orders[maker.order_id]
                    stp_cancels.append(maker)
                    continue
                q = maker.qty if maker.qty < qty else qty
                maker.qty -= q
                qty -= q
                fills.append(Fill(maker, best, q))
                if maker.qty == 0:
                    queue.popleft()
                    del self.orders[maker.order_id]
            if not queue:
                del levels[best]
                if side == BUY:
                    prices.pop(0)
                else:
                    prices.pop()
        return fills, qty, stp_cancels

    def add(self, order: Order) -> None:
        if order.side == BUY:
            levels, prices = self.bids, self.bid_prices
        else:
            levels, prices = self.asks, self.ask_prices
        q = levels.get(order.price)
        if q is None:
            q = deque()
            levels[order.price] = q
            insort(prices, order.price)
        q.append(order)
        self.orders[order.order_id] = order

    def cancel(self, order_id: int) -> Order | None:
        order = self.orders.pop(order_id, None)
        if order is None:
            return None
        levels, prices = (self.bids, self.bid_prices) if order.side == BUY else (self.asks, self.ask_prices)
        q = levels[order.price]
        q.remove(order)
        if not q:
            del levels[order.price]
            i = bisect_left(prices, order.price)
            prices.pop(i)
        return order

    def check_invariants(self) -> None:
        bb, ba = self.best_bid(), self.best_ask()
        assert bb is None or ba is None or bb < ba, f"crossed book {bb} >= {ba}"
        assert self.bid_prices == sorted(self.bids), "bid index out of sync"
        assert self.ask_prices == sorted(self.asks), "ask index out of sync"
        n = 0
        for levels in (self.bids, self.asks):
            for p, q in levels.items():
                assert q, f"empty level {p}"
                for o in q:
                    assert o.qty > 0 and o.price == p
                    assert self.orders[o.order_id] is o
                    n += 1
        assert n == len(self.orders), "order index out of sync"
