"""Synthetic multi-venue exchange.

Validates commands, runs matching, settles via the clearing house, enforces
circuit breakers, and performs forced liquidations. Emits immutable events.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from .clearing import ClearingHouse
from .events import SimEvent, Trade
from .orderbook import BUY, SELL, Order, OrderBook
from .units import notional


@dataclass(slots=True)
class VenueConfig:
    name: str
    circuit_breaker_pct: float = 0.10  # halt if mid moves this much vs reference window
    circuit_breaker_window_ms: int = 60_000
    halt_ms: int = 30_000
    max_order_lots: int = 2_000_000  # 200 BTC fat-finger guard


class Venue:
    def __init__(self, idx: int, cfg: VenueConfig) -> None:
        self.idx = idx
        self.cfg = cfg
        self.book = OrderBook()
        self.last_price: int | None = None
        self.halted_until = -1
        self.ref_mids: deque[tuple[int, int]] = deque()  # (t, mid) for circuit breaker
        self.volume = 0  # cumulative lots
        self.n_trades = 0

    def mid(self) -> int | None:
        bb, ba = self.book.best_bid(), self.book.best_ask()
        if bb is not None and ba is not None:
            return (bb + ba) // 2
        if self.last_price is not None:  # one-sided book: last trade is the robust mark
            if bb is not None:
                return max(self.last_price, bb)
            if ba is not None:
                return min(self.last_price, ba)
            return self.last_price
        return bb if bb is not None else ba

    def halted(self, t: int) -> bool:
        return t < self.halted_until


class Exchange:
    def __init__(self, venues: list[VenueConfig], clearing: ClearingHouse, initial_price: int) -> None:
        self.venues = [Venue(i, c) for i, c in enumerate(venues)]
        self.clearing = clearing
        self.initial_price = initial_price
        self.trades: list[Trade] = []
        self.events: list[SimEvent] = []
        self.breached: set[int] = set()  # accounts currently below maintenance margin
        self.breaches: list[dict[str, int | bool]] = []  # each transition into breach (executed or suppressed)
        self.forced_notional: dict[int, int] = {}  # micro-USDT executed by forced liquidation, per account
        self._next_order_id = 0
        self._next_trade_id = 0
        self.agent_orders: dict[int, dict[int, Order]] = {}
        self.rejections = 0

    # --- marks ---------------------------------------------------------------
    def marks(self) -> list[int]:
        out = []
        for v in self.venues:
            m = v.mid()
            out.append(m if m is not None else self.initial_price)
        return out

    # --- order entry ---------------------------------------------------------
    def _reject(self, t: int, agent: int, venue: int, reason: str) -> None:
        self.rejections += 1
        if reason != "margin":  # margin rejections are frequent; counted not logged
            self.events.append(SimEvent(t, "reject", agent, venue, {"reason": reason}))

    def submit(
        self,
        t: int,
        agent: int,
        venue: int,
        side: int,
        qty: int,
        price: int | None,
        ioc: bool = False,
        forced: bool = False,
    ) -> int | None:
        """Submit limit (price) or market (price=None) order. Returns resting order id or None."""
        if side not in (BUY, SELL) or qty <= 0 or not (0 <= venue < len(self.venues)):
            self._reject(t, agent, venue, "invalid")
            return None
        v = self.venues[venue]
        if qty > v.cfg.max_order_lots and not forced:
            self._reject(t, agent, venue, "size")
            return None
        if price is not None and price <= 0:
            self._reject(t, agent, venue, "price")
            return None
        if v.halted(t) and not forced:
            self._reject(t, agent, venue, "halted")
            return None
        marks = self.marks()
        ref_price = (
            price if price is not None else (v.book.best_ask() if side == BUY else v.book.best_bid()) or marks[venue]
        )
        if not forced and not self.clearing.can_take(agent, venue, side, qty, ref_price, marks):
            self._reject(t, agent, venue, "margin")
            return None
        fills, remaining, stp = v.book.match(side, price, qty, agent)
        for o in stp:
            self._forget(o)
        for f in fills:
            maker = f.maker
            buyer, seller = (agent, maker.agent) if side == BUY else (maker.agent, agent)
            bfee, sfee = self.clearing.settle_fill(venue, f.price, f.qty, buyer, seller, side)
            self._reduce_open(maker, f.qty)
            if maker.qty == 0:
                self.agent_orders[maker.agent].pop(maker.order_id, None)
            self._next_trade_id += 1
            self.trades.append(Trade(t, venue, f.price, f.qty, buyer, seller, side, bfee, sfee, self._next_trade_id))
            v.last_price = f.price
            v.volume += f.qty
            v.n_trades += 1
        if remaining > 0 and price is not None and not ioc:
            self._next_order_id += 1
            o = Order(self._next_order_id, agent, side, price, remaining, t, venue, remaining)
            v.book.add(o)
            self.agent_orders.setdefault(agent, {})[o.order_id] = o
            acct = self.clearing.accounts[agent]
            if side == BUY:
                acct.open_buy[venue] += remaining
            else:
                acct.open_sell[venue] += remaining
            return o.order_id
        return None

    def _reduce_open(self, order: Order, qty: int) -> None:
        acct = self.clearing.accounts[order.agent]
        if order.side == BUY:
            acct.open_buy[order.venue] -= qty
        else:
            acct.open_sell[order.venue] -= qty

    def _forget(self, order: Order) -> None:
        self._reduce_open(order, order.qty)
        self.agent_orders.get(order.agent, {}).pop(order.order_id, None)

    def cancel(self, agent: int, order_id: int) -> bool:
        orders = self.agent_orders.get(agent)
        if not orders or order_id not in orders:
            return False
        o = orders[order_id]
        self.venues[o.venue].book.cancel(order_id)
        self._forget(o)
        return True

    def cancel_all(self, agent: int, venue: int | None = None) -> int:
        orders = self.agent_orders.get(agent)
        if not orders:
            return 0
        n = 0
        for oid, o in list(orders.items()):
            if venue is None or o.venue == venue:
                self.venues[o.venue].book.cancel(oid)
                self._forget(o)
                n += 1
        return n

    # --- periodic market processes ------------------------------------------
    def update_circuit_breakers(self, t: int) -> None:
        for v in self.venues:
            m = v.mid()
            if m is None:
                continue
            v.ref_mids.append((t, m))
            while v.ref_mids and v.ref_mids[0][0] < t - v.cfg.circuit_breaker_window_ms:
                v.ref_mids.popleft()
            ref = v.ref_mids[0][1]
            if not v.halted(t) and ref > 0 and abs(m - ref) / ref > v.cfg.circuit_breaker_pct:
                v.halted_until = t + v.cfg.halt_ms
                v.ref_mids.clear()
                self.events.append(SimEvent(t, "circuit_breaker", -1, v.idx, {"mid": m, "ref": ref}))

    def run_liquidations(self, t: int, suppress: Callable[[int], bool] | None = None) -> list[int]:
        """Force-close accounts below maintenance margin. Returns liquidated agent ids.

        Every transition of an account into breach is recorded in `breaches` (whether or not it is executed).
        `suppress(agent)` -> True records the breach but does NOT execute the liquidation (KC-2: nonphysical
        causal counterfactual for experiments only; default None keeps the original behaviour exactly).
        """
        marks = self.marks()
        liquidated = []
        for agent, acct in self.clearing.accounts.items():
            if not self.clearing.needs_liquidation(agent, marks):
                acct.liquidating = False
                self.breached.discard(agent)
                continue
            skip = suppress is not None and suppress(agent)
            if agent not in self.breached:
                self.breached.add(agent)
                self.breaches.append(
                    {
                        "t": t,
                        "agent": agent,
                        "equity": acct.equity(marks),
                        "gross": acct.gross_notional(marks),
                        "executed": not skip,
                    }
                )
            if skip:
                continue
            self.cancel_all(agent)
            eq_before = acct.equity(marks)
            new_episode = not acct.liquidating
            acct.liquidating = True
            closed = 0
            n_trades = len(self.trades)
            for vi, pos in enumerate(list(acct.positions)):
                if pos == 0 or self.venues[vi].halted(t):
                    continue
                side = SELL if pos > 0 else BUY
                self.submit(t, agent, vi, side, abs(pos), None, ioc=True, forced=True)
                closed += abs(pos) - abs(acct.positions[vi])
            self.forced_notional[agent] = self.forced_notional.get(agent, 0) + sum(
                notional(tr.price, tr.qty) for tr in self.trades[n_trades:]
            )
            cover = self.clearing.cover_bankruptcy(agent)
            if not any(acct.positions):
                acct.liquidating = False
            if new_episode:
                acct.liquidations += 1
                self.events.append(
                    SimEvent(
                        t,
                        "liquidation",
                        agent,
                        -1,
                        {"equity": eq_before, "closed_lots": closed, "insurance_cover": cover},
                    )
                )
                liquidated.append(agent)
        return liquidated

    def check_invariants(self) -> None:
        self.clearing.check_invariants()
        open_buy: dict[tuple[int, int], int] = {}
        open_sell: dict[tuple[int, int], int] = {}
        for v in self.venues:
            v.book.check_invariants()
            for o in v.book.orders.values():
                d = open_buy if o.side == BUY else open_sell
                d[(o.agent, v.idx)] = d.get((o.agent, v.idx), 0) + o.qty
        for a in self.clearing.accounts.values():
            for vi in range(len(self.venues)):
                assert a.open_buy[vi] == open_buy.get((a.agent, vi), 0), f"open_buy mismatch agent {a.agent}"
                assert a.open_sell[vi] == open_sell.get((a.agent, vi), 0), f"open_sell mismatch agent {a.agent}"
        for tr in self.trades[-1000:]:
            assert tr.qty > 0 and tr.price > 0 and tr.buyer != tr.seller
