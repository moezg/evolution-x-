"""Clearing/exchange accounting invariants: cash conservation, zero net position, fees, funding."""

from hypothesis import given, settings
from hypothesis import strategies as st

from evolutionx.kernel.clearing import ClearingHouse
from evolutionx.kernel.exchange import Exchange, VenueConfig
from evolutionx.kernel.orderbook import BUY, SELL


def make(n_agents=4, cash=10**13, lev=5.0):
    ch = ClearingHouse(2, 1.0, 5.0, 0.02)
    for i in range(n_agents):
        ch.open_account(i, cash, lev)
    ex = Exchange([VenueConfig("A"), VenueConfig("B")], ch, 6_000_000)
    return ch, ex


def test_trade_settlement_exact():
    ch, ex = make()
    ex.submit(0, 0, 0, SELL, 1000, 6_000_000)
    ex.submit(1, 1, 0, BUY, 400, None)
    tr = ex.trades[-1]
    assert tr.qty == 400 and tr.price == 6_000_000 and tr.aggressor_side == BUY
    notional = 6_000_000 * 400
    assert ch.accounts[1].cash == 10**13 - notional - notional * 5 // 10_000
    assert ch.accounts[0].cash == 10**13 + notional - notional * 1 // 10_000
    assert ch.accounts[0].positions[0] == -400 and ch.accounts[1].positions[0] == 400
    assert ch.accounts[0].open_sell[0] == 600
    ex.check_invariants()


def test_margin_rejects_overleverage():
    ch, ex = make(cash=10**9, lev=2.0)  # $1000 collateral
    ex.submit(0, 0, 0, SELL, 10_000, 6_000_000)  # 1 BTC = $60k, needs $30k
    assert ex.rejections == 1 and not ex.venues[0].book.orders


def test_funding_is_zero_sum_with_residual_to_insurance():
    ch, ex = make()
    ex.submit(0, 0, 0, SELL, 333, 6_000_000)
    ex.submit(0, 1, 0, BUY, 333, None)
    before = ch.total_cash()
    ch.apply_funding(0, 0.000123, 6_000_123)
    assert ch.total_cash() == before
    assert ch.accounts[1].funding_paid > 0 and ch.accounts[0].funding_paid < 0
    ch.check_invariants()


def test_liquidation_and_bankruptcy_cover_conserve_cash():
    ch = ClearingHouse(1, 1.0, 5.0, 0.05)
    ch.open_account(0, 10**14, 5)  # deep-pocket liquidity provider
    ch.open_account(1, 2 * 10**9, 50)  # $2000, highly levered
    ex = Exchange([VenueConfig("A")], ch, 6_000_000)
    ex.submit(0, 0, 0, SELL, 5000, 6_000_000)
    ex.submit(0, 1, 0, BUY, 100, None)  # 0.01 BTC = $600 notional -> fine
    ex.submit(0, 1, 0, BUY, 1500, None)  # $9600 notional at ~5x
    # price collapses: only far bids remain
    ex.cancel_all(0)
    ex.submit(1, 0, 0, BUY, 100_000, 5_000_000)
    ex.submit(1, 0, 0, SELL, 1, 5_000_001)
    liq = ex.run_liquidations(2)
    assert liq == [1]
    assert ch.accounts[1].positions[0] == 0
    ex.check_invariants()


ops = st.lists(
    st.tuples(
        st.integers(0, 3),
        st.integers(0, 1),
        st.sampled_from([BUY, SELL]),
        st.integers(1, 3000),
        st.one_of(st.none(), st.integers(5_900_000, 6_100_000)),
        st.integers(0, 9),
    ),
    min_size=1,
    max_size=60,
)


@settings(max_examples=200, deadline=None)
@given(ops)
def test_random_order_flow_conserves_cash_and_positions(seq):
    ch, ex = make()
    for t, (agent, venue, side, qty, price, action) in enumerate(seq):
        if action == 0:
            ex.cancel_all(agent)
        elif action == 1:
            ch.apply_funding(venue, 0.0005, ex.marks()[venue])
        elif action == 2:
            ex.run_liquidations(t)
        else:
            ex.submit(t, agent, venue, side, qty, price)
        ex.check_invariants()
