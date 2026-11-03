"""C2 liquidation-cascade laboratory: margin mechanics, KC-2 counterfactual switch, measurement neutrality,
event classification, classifier guard, research-memory dedup and proposal handling."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from evolutionx.kernel.clearing import ClearingHouse
from evolutionx.kernel.exchange import Exchange, VenueConfig
from evolutionx.kernel.orderbook import BUY, SELL
from evolutionx.observatory import cascade as C
from evolutionx.observatory import knowledge as K
from evolutionx.sim.config import SimConfig
from evolutionx.sim.simulation import Simulation

MM = 0.02


def _small_job(arm: str, seed: int = 3, size: float = 300.0) -> dict:
    return {
        "config": f"{int(size)}btc|lu1.0",
        "arm": arm,
        "role": "test",
        "whale_btc": size,
        "leverage_use": 1.0,
        "at_s": 300,
        "cfg": {
            "seed": seed,
            "duration_s": 420,
            "invariant_check_every_s": 30,
            "world_annual_vol": 0.33,
            "news_impact": 0.0,
            "param_overrides": {"leveraged": {"leverage_use": 1.0}},
            "shocks": [{"type": "whale_liquidation", "at_s": 300, "magnitude": size}],
            "execute_secondary_liquidations": arm == "A",
        },
    }


# --------------------------------------------------------------------------- margin geometry and validity
@given(
    st.integers(1, 5_000),  # lots
    st.floats(1.5, 60.0),  # effective leverage
    st.booleans(),
)
@settings(max_examples=80, deadline=None)
def test_margin_distance_matches_the_engine_breach_rule(lots, lev, is_long):
    price = 6_000_000  # ticks (60,000 USD)
    ch = ClearingHouse(1, 1.0, 5.0, MM)
    pos = lots if is_long else -lots
    gross = lots * price
    cash = int(gross / lev) - pos * price  # equity = gross / lev at the current mark
    ch.open_account(0, cash, 100.0)
    ch.accounts[0].positions[0] = pos
    eq = ch.accounts[0].equity([price])
    d, direction = C.margin_distance(eq, pos * price, gross, MM)
    if eq < MM * gross:
        assert direction == "breached" and d == 0.0
        assert ch.needs_liquidation(0, [price])
        return
    assert not ch.needs_liquidation(0, [price])
    sign = -1 if direction == "down" else 1
    inside = int(price * (1 + sign * d * 0.98))
    beyond = int(price * (1 + sign * d * 1.02)) + sign
    assert not ch.needs_liquidation(0, [inside])
    assert ch.needs_liquidation(0, [beyond])


def test_no_agent_can_trade_without_resources():
    ch = ClearingHouse(1, 1.0, 5.0, MM)
    ex = Exchange([VenueConfig("v")], ch, 6_000_000)
    ch.open_account(1, 10**12, 10)  # liquidity provider
    ch.open_account(2, 0, 10)  # no collateral
    ch.open_account(3, 600 * 10**6, 2)  # $600 at 2x -> at most $1,200 gross
    ex.submit(0, 1, 0, SELL, 10_000, 6_000_000)
    assert ex.submit(1, 2, 0, BUY, 1, 6_000_000) is None and ch.accounts[2].positions == [0]
    before = ex.rejections
    ex.submit(2, 3, 0, BUY, 10_000, None)  # 1 BTC = $60,000 >> $1,200
    assert ex.rejections == before + 1 and ch.accounts[3].positions == [0]
    ex.submit(3, 3, 0, BUY, 1, None)  # 0.0001 BTC = $6 is fine
    assert ch.accounts[3].positions == [1]
    ch.check_invariants()


def _force_breach(sim: Simulation) -> int:
    """Move an agent just below maintenance margin by transferring its cash to the insurance fund
    (keeps cash conservation exact). Returns the agent id."""
    marks = sim.exchange.marks()
    for a in sim.agents:
        acct = sim.clearing.accounts[a.id]
        if any(acct.positions):
            gross = acct.gross_notional(marks)
            target_eq = int(0.5 * MM * gross)
            delta = acct.equity(marks) - target_eq
            acct.cash -= delta
            sim.clearing.insurance_fund += delta
            return a.id
    raise AssertionError("no agent with a position")


@pytest.mark.parametrize("execute", [True, False])
def test_breach_vs_liquidation_and_primary_secondary_classification(execute):
    sim = Simulation(SimConfig(seed=5, duration_s=120, execute_secondary_liquidations=execute))
    sim.run_until(60_000)
    aid = _force_breach(sim)
    pos_before = list(sim.clearing.accounts[aid].positions)
    sim.run_until(61_000)
    b = [x for x in sim.exchange.breaches if x["agent"] == aid]
    assert len(b) == 1 and b[0]["executed"] is execute
    liq = [e for e in sim.liquidation_log if e["agent"] == aid]
    if execute:
        assert liq and liq[0]["role"] == "secondary"
        assert sim.exchange.forced_notional.get(aid, 0) > 0
    else:
        assert not liq and sim.clearing.accounts[aid].positions == pos_before
    sim.run()
    sim.exchange.check_invariants()
    assert sum(a.fees_paid for a in sim.clearing.accounts.values()) == sim.clearing.fee_pool


def test_primary_liquidation_survives_the_counterfactual_switch():
    for arm in ("A", "B"):
        r = C.run_one(_small_job(arm))
        assert r["primary_selling"]["btc"] > 0
        assert any(e["type"] == "primary_liquidation" for e in r["trace"])
        if arm == "B":
            assert r["secondary_liquidations"] == 0


def test_measurement_is_read_only_and_runs_are_deterministic():
    job = _small_job("A")
    r1, r2 = C.run_one(job), C.run_one(job)
    plain = Simulation(SimConfig(**job["cfg"])).run()
    assert r1["run_fingerprint"] == plain.fingerprint()[:16]
    strip = lambda r: {k: v for k, v in r.items() if k != "wall_s"}  # noqa: E731
    assert strip(r1) == strip(r2)


def test_kc2_default_is_neutral():
    a = SimConfig(seed=9, duration_s=60)
    b = SimConfig(seed=9, duration_s=60, execute_secondary_liquidations=True)
    c = SimConfig(seed=9, duration_s=60, execute_secondary_liquidations=False)
    assert a.fingerprint() == b.fingerprint() != c.fingerprint()
    assert Simulation(a).run().fingerprint() == Simulation(c).run().fingerprint()  # no breach -> identical


# --------------------------------------------------------------------------- classifier guard
@given(
    st.integers(0, 8),
    st.floats(-0.2, 0.2),
    st.floats(-0.2, 0.2),
    st.floats(-0.2, 0.0),
    st.integers(0, 8),
)
@settings(max_examples=200, deadline=None)
def test_cascade_label_requires_secondary_liquidations_and_chain(k_sec, mean, half, drop_b, k_chain):
    incr = {"mean": mean, "t_lo": mean - abs(half), "t_hi": mean + abs(half)}
    out = C.classify(k_sec, incr, drop_b, k_chain)
    assert out["label"] in C.CLASSES
    if k_sec < 2 or k_chain < 2:
        assert out["label"] != "cascade"
    if k_sec < 2:
        assert out["label"] == "no_secondary_liquidations"


def test_analysis_of_identical_arms_is_not_a_cascade():
    rows = []
    for s in (1, 2):
        for arm in ("A", "B"):
            j = _small_job(arm, seed=s)
            rows.append(C.run_one(j))
    rep = C.analyse(rows, {"design": {"leverage_use": [1.0]}})
    v = next(iter(rep["configs"].values()))
    assert v["classification"]["label"] != "cascade"
    if v["seeds_with_secondary_liquidation"] == 0:
        assert v["classification"]["label"] == "no_secondary_liquidations"


# --------------------------------------------------------------------------- research memory
def test_identical_experiments_are_refused_and_replications_need_new_seeds(tmp_path):
    mem = K.open_memory(tmp_path / "k.db")
    cond = {"whale_btc": 2000, "leverage_use": 1.0}
    key = K.register_experiment(mem, "H", cond, [1, 2], "sha", {"x": 1})
    ck = key.split(":")[0]
    with pytest.raises(K.DuplicateExperiment):
        K.register_experiment(mem, "H", cond, [3, 4], "sha", {"x": 1})
    with pytest.raises(K.DuplicateExperiment):
        K.register_experiment(mem, "H", cond, [2, 3], "sha", {"x": 1}, replication_of=ck)
    K.register_experiment(mem, "H", cond, [3, 4], "sha", {"x": 1}, replication_of=ck)
    with pytest.raises(K.DuplicateExperiment):
        K.guard_new(mem, "H", cond)
    K.guard_new(mem, "H", {**cond, "whale_btc": 1000})


def test_ranking_excludes_already_run_conditions(tmp_path):
    mem = K.open_memory(tmp_path / "k.db")
    c = C.NEXT_CANDIDATES
    K.register_experiment(mem, c[0]["hypothesis_id"], c[0]["conditions"], [901], "sha", {})
    ranked = K.rank_next(mem, c)
    assert ranked[-1]["id"] == c[0]["id"] and ranked[-1]["already_run"]
    assert all(r["bits"] <= 1.0 for r in ranked)


def test_proposals_are_never_applied_and_out_of_space_ones_cannot_be_evaluated(tmp_path):
    mem = K.open_memory(tmp_path / "k.db")
    K.propose(mem, "P", "gap", {"funding_k": 0.0001}, "x", False)
    (p,) = K.proposals(mem)
    assert p["status"] == "needs_human_rules_review"
    with pytest.raises(ValueError):
        K.evaluate_proposal(mem, "P")
    with pytest.raises(ValueError):
        K.record_mechanism(mem, "m", "s", "proven", {}, "mechanism")
