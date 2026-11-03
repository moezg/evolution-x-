"""End-to-end simulation properties: population, determinism, no look-ahead, scenarios."""

import pytest

from evolutionx.agents.population import population_counts
from evolutionx.sim.config import SimConfig
from evolutionx.sim.scenarios import SCENARIOS, scenario_at
from evolutionx.sim.simulation import Simulation


def run(seed=3, duration=240, **kw):
    return Simulation(SimConfig(seed=seed, duration_s=duration, invariant_check_every_s=10, **kw)).run()


def test_population_is_256_unique_stateful_agents():
    counts = population_counts()
    assert sum(counts.values()) == 256
    s = Simulation(SimConfig(seed=1, duration_s=60))
    assert len(s.agents) == 256 and len({a.id for a in s.agents}) == 256
    assert len({tuple(sorted(a.params.items())) for a in s.agents}) == 256  # individually parameterised
    assert counts == {"noise": 64, "momentum": 40, "value": 32, "market_maker": 24, "arbitrage": 20,
                      "execution": 20, "whale": 16, "leveraged": 16, "news": 12, "adaptive": 12}


def test_same_seed_is_bit_identical_and_different_seed_differs():
    a, b, c = run(seed=5), run(seed=5), run(seed=6)
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != c.fingerprint()
    assert len(a.exchange.trades) > 100


def test_invariants_hold_after_run():
    s = run(seed=9, duration=300)
    s.exchange.check_invariants()
    for a in s.agents:
        assert a.wakes > 0


def test_observation_never_contains_future_data():
    s = Simulation(SimConfig(seed=2, duration_s=120))
    s.run_until(100_000)
    for a in s.agents[:40]:
        obs = s.observe(a, 100_000)
        assert obs is not None
        assert obs.data_t <= 100_000 - a.md_latency_ms
        assert all(n.t <= 100_000 - a.md_latency_ms for n in obs.news)
        assert (obs.fundamental is None) == (not a.memory.get("research"))


@pytest.mark.parametrize("name", ["btc_drop_5pct", "liquidity_drought_70", "whale_liquidation", "funding_spike",
                                  "news_panic", "arb_outage", "flash_sell"])
def test_scenarios_execute_and_preserve_invariants(name):
    cfg = scenario_at(name, 120).apply(SimConfig(seed=4, duration_s=300, invariant_check_every_s=10))
    s = Simulation(cfg).run()
    s.exchange.check_invariants()
    assert any(e.type == "shock" for e in s.sim_events)
    if name == "whale_liquidation":
        assert any(x["kind"] == "external" for x in s.liquidation_log)


def test_paired_baseline_identical_before_shock():
    sc = SCENARIOS["btc_drop_5pct"]
    t = Simulation(scenario_at("btc_drop_5pct", 150).apply(SimConfig(seed=8, duration_s=200))).run()
    b = Simulation(scenario_at("btc_drop_5pct", 150).apply(SimConfig(seed=8, duration_s=200), armed=False)).run()
    assert sc.name == "btc_drop_5pct"
    pre_t = [x for x in t.exchange.trades if x.t < 150_000]
    pre_b = [x for x in b.exchange.trades if x.t < 150_000]
    assert pre_t == pre_b and len(pre_t) > 0
    assert t.fingerprint() != b.fingerprint()


def test_scale_changes_population():
    s = Simulation(SimConfig(seed=1, duration_s=30, scale=1000 / 256))
    assert 990 <= len(s.agents) <= 1010


def test_emergency_stop():
    s = Simulation(SimConfig(seed=1, duration_s=600))
    s.run_until(10_000)
    s.stop()
    s.run_until(600_000)
    assert s.now <= 10_000
