"""Historical backtest engine: causality, execution timing, accounting, gaps, liquidation, walk-forward."""

import math

import numpy as np
import pytest

from evolutionx.backtest.causality import check_in_process
from evolutionx.backtest.engine import CostModel, InvalidDecisions, run_backtest
from evolutionx.backtest.interface import BarView, FunctionStrategy, decisions_for
from evolutionx.backtest.walkforward import windows

H = 3_600_000


def synth(n=2000, seed=0, drift=0.0, vol=0.01):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, n)
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[100, c[:-1]]
    hi = np.maximum(o, c) * 1.002
    lo = np.minimum(o, c) * 0.998
    t = np.arange(n, dtype=np.int64) * H
    return {
        "open_time": t,
        "open": o,
        "high": hi,
        "low": lo,
        "close": c,
        "volume": np.full(n, 1e6),
        "available_at": t + H,
        "funding": np.zeros(n),
    }


def tsmom(view, p):
    c = view.close(p["L"] + 1)
    return 0.0 if len(c) <= p["L"] else (1.0 if c[-1] > c[0] else -1.0)


def test_barview_returns_copies_without_future_reference():
    d = synth(50)
    v = BarView(d, 10)
    w = v.close(5)
    assert w.base is None and len(w) == 5 and w[-1] == d["close"][10]
    assert len(v.close(1000)) == 11  # cannot reach beyond the current bar


def test_execution_happens_at_next_open_not_decision_close():
    d = synth(10)
    d["close"][4] = 200.0  # huge close move on the decision bar
    d["high"][4] = 200.0
    d["open"][5] = 100.0
    dec = np.zeros(10)
    dec[4] = 1.0
    cost = CostModel(
        taker_fee_bps=0,
        spread_bps=0,
        impact_coef_bps=0,
        max_leverage=1.0,
        lot_step=1e-9,
        rebalance_band=0.0,
        maintenance_margin=0.0,
    )
    r = run_backtest(d, dec, cost, equity0=1000.0)
    assert r.position[4] == 0.0  # nothing executed on the decision bar
    assert math.isclose(r.position[5], 1000.0 / 100.0, rel_tol=1e-6)  # bought at the NEXT open (100), not 200


@pytest.mark.parametrize("seed", range(5))
def test_accounting_identity_random_decisions(seed):
    d = synth(1500, seed)
    rng = np.random.default_rng(seed)
    dec = np.clip(rng.normal(0, 0.7, 1500), -1, 1)
    r = run_backtest(d, dec, CostModel(max_leverage=3.0))
    assert math.isclose(r.equity[-1], 1e6 + r.gross_pnl - sum(r.costs.values()), rel_tol=1e-9)


def test_invalid_decisions_are_rejected():
    d = synth(100)
    for bad in (np.full(100, 1.5), np.r_[np.zeros(99), np.nan], np.zeros(50)):
        with pytest.raises(InvalidDecisions):
            run_backtest(d, bad, CostModel())


def test_gap_blocks_trading_and_is_reported():
    d = synth(100)
    d["open_time"] = np.r_[d["open_time"][:50], d["open_time"][50:] + 24 * H]  # 24h hole
    dec = np.zeros(100)
    dec[49] = 1.0  # decision right before the gap
    r = run_backtest(d, dec, CostModel(rebalance_band=0))
    assert r.position[50] == 0.0  # cannot execute across a gap
    assert any(e["type"] == "gap" for e in r.events)


def test_liquidation_on_crash_bar_keeps_accounting():
    d = synth(30, vol=0.0)
    d["low"][20] = d["open"][20] * 0.3  # intrabar crash
    dec = np.ones(30)
    r = run_backtest(d, dec, CostModel(max_leverage=2.0, rebalance_band=0))
    assert r.n_liquidations == 1 and r.position[20] == 0.0
    assert r.equity[-1] >= 0


def test_participation_limit_creates_partial_fills():
    d = synth(20)
    d["volume"][:] = 1.0  # tiny volume
    dec = np.ones(20)
    r = run_backtest(d, dec, CostModel(participation_limit=0.02, rebalance_band=0, lot_step=1e-6))
    assert 0 < r.position[1] <= 0.02 + 1e-12 and r.unfilled_qty > 0


def test_causal_strategy_passes_truncation_check():
    d = synth(1200, 3)
    s = FunctionStrategy("tsmom", {"L": 24}, tsmom)
    rep = check_in_process(lambda data: decisions_for(s, data), d, n_checks=6, seed=11)
    assert rep["causal"] and rep["checked"] == 6


def test_leaky_strategy_is_detected():
    """Acceptance C: a strategy that peeks at the next bar's return through its constructor is caught."""
    d = synth(1200, 4)

    def make_decisions(data):
        nxt = np.r_[np.diff(data["close"]), 0.0]  # FUTURE information baked into a lookup table

        def leaky(view, p):
            return 1.0 if nxt[view.t] > 0 else -1.0

        return decisions_for(FunctionStrategy("leaky", {}, leaky), data)

    rep = check_in_process(make_decisions, d, n_checks=6, seed=11)
    assert not rep["causal"] and rep["violations"]  # caught at the cut points where the peeked sign matters


def test_walk_forward_windows_are_chronological_with_embargo():
    t = np.arange(24 * 365 * 3, dtype=np.int64) * H
    ws = windows(t, 12, 3, 3, 168)
    assert len(ws) >= 7
    for w in ws:
        assert w["train"][1] + 168 == w["test"][0]
        assert w["train"][0] < w["train"][1] < w["test"][0] < w["test"][1]
    assert all(a["test"][0] < b["test"][0] for a, b in zip(ws, ws[1:], strict=False))
