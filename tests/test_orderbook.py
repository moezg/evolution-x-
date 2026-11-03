"""Matching-engine invariants: price-time priority, partial fills, cancels, no crossed book."""

from hypothesis import given, settings
from hypothesis import strategies as st

from evolutionx.kernel.orderbook import BUY, SELL, Order, OrderBook


def _add(book, oid, agent, side, price, qty, t=0):
    o = Order(oid, agent, side, price, qty, t, 0, qty)
    fills, rem, _ = book.match(side, price, qty, agent)
    if rem:
        o.qty = rem
        book.add(o)
    return fills, rem


def test_fifo_within_level_and_price_priority():
    b = OrderBook()
    _add(b, 1, 1, SELL, 101, 5, t=1)
    _add(b, 2, 2, SELL, 100, 5, t=2)  # better price, later time
    _add(b, 3, 3, SELL, 100, 5, t=3)
    fills, rem = _add(b, 4, 9, BUY, 101, 12)
    assert rem == 0
    assert [(f.maker.order_id, f.price, f.qty) for f in fills] == [(2, 100, 5), (3, 100, 5), (1, 101, 2)]
    assert b.best_ask() == 101 and b.level_qty(SELL, 101) == 3
    b.check_invariants()


def test_partial_fill_rests_remainder_and_cancel():
    b = OrderBook()
    _add(b, 1, 1, SELL, 100, 3)
    fills, rem = _add(b, 2, 2, BUY, 100, 10)
    assert sum(f.qty for f in fills) == 3 and rem == 7
    assert b.best_bid() == 100 and b.best_ask() is None
    assert b.cancel(2) is not None and b.best_bid() is None
    assert b.cancel(2) is None
    b.check_invariants()


def test_market_order_sweeps_levels():
    b = OrderBook()
    for i, p in enumerate([100, 101, 102]):
        _add(b, i + 1, i + 1, SELL, p, 2)
    fills, rem, _ = b.match(BUY, None, 5, 99)
    assert [f.price for f in fills] == [100, 101, 102] and rem == 0
    assert b.level_qty(SELL, 102) == 1


def test_self_trade_prevention_cancels_resting():
    b = OrderBook()
    _add(b, 1, 7, SELL, 100, 5)
    _add(b, 2, 8, SELL, 100, 5)
    fills, rem, stp = b.match(BUY, 100, 5, 7)
    assert [o.order_id for o in stp] == [1]
    assert [f.maker.agent for f in fills] == [8] and rem == 0
    b.check_invariants()


order_st = st.tuples(
    st.integers(1, 6), st.sampled_from([BUY, SELL]), st.integers(95, 105), st.integers(1, 20), st.booleans()
)


@settings(max_examples=300, deadline=None)
@given(st.lists(order_st, min_size=1, max_size=80))
def test_random_sequences_preserve_invariants(orders):
    b = OrderBook()
    submitted = filled = 0
    resting_before = 0
    for oid, (agent, side, price, qty, cancel_prev) in enumerate(orders, start=1):
        if cancel_prev and b.orders:
            first = next(iter(b.orders))
            resting_before -= b.orders[first].qty
            b.cancel(first)
        fills, rem, stp = b.match(side, price, qty, agent)
        resting_before -= sum(o.qty for o in stp)
        for f in fills:
            assert f.qty > 0 and f.maker.agent != agent
            assert (f.price <= price) if side == BUY else (f.price >= price)  # never worse than limit
        traded = sum(f.qty for f in fills)
        filled += traded
        resting_before -= traded
        submitted += qty
        if rem:
            b.add(Order(oid, agent, side, price, rem, oid, 0, rem))
            resting_before += rem
        b.check_invariants()
    assert resting_before == sum(o.qty for o in b.orders.values())
