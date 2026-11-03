"""Emergent Behavior Observatory: shock mechanics, read-only sampling, detectors, realism Pareto archive."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from evolutionx.observatory import experiments as E
from evolutionx.observatory import metrics as M
from evolutionx.observatory import realism as R
from evolutionx.observatory.sampler import run_sampled
from evolutionx.sim.config import Shock, SimConfig
from evolutionx.sim.simulation import Simulation


def _cfg(**kw):
    base = {"seed": 7, "duration_s": 240, "invariant_check_every_s": 30}
    base.update(kw)
    return SimConfig(**base)


# --------------------------------------------------------------------------- simulator mechanics
def test_finished_is_false_before_the_first_event():
    assert not Simulation(_cfg()).finished


def test_sampling_does_not_perturb_the_run():
    sim, smp = run_sampled(_cfg())
    ref = Simulation(_cfg()).run()
    assert sim.fingerprint() == ref.fingerprint()
    assert len(smp.t_ms) == 24 and smp.stance_matrix().shape == (24, 256)
    assert len(smp.mm_depth[0]) == 24  # one entry per market maker


@pytest.mark.parametrize("frac", [0.5, 0.9])
def test_mm_withdrawal_removes_exactly_the_fraction_and_restores(frac):
    shock = Shock(type="mm_withdrawal", at_s=100, duration_s=60, magnitude=frac)
    sim = Simulation(_cfg(shocks=[shock]))
    sim.run_until(100_500)
    mms = [a for a in sim.agents if a.kind == "market_maker"]
    k = round(frac * len(mms))
    assert [a.active for a in mms] == [False] * k + [True] * (len(mms) - k)
    for a in mms[:k]:
        assert not sim.exchange.agent_orders.get(a.id), "withdrawn makers keep no resting orders"
    sim.run_until(161_000)
    assert all(a.active for a in mms)
    assert any(e.type == "restore" and e.data["what"] == "mm_withdrawal" for e in sim.sim_events)
    sim.run()
    sim.exchange.check_invariants()


def test_mm_withdrawal_is_deterministic_and_disarmed_equals_no_shock():
    shock = Shock(type="mm_withdrawal", at_s=100, duration_s=60, magnitude=0.9)
    a = Simulation(_cfg(shocks=[shock])).run().fingerprint()
    b = Simulation(_cfg(shocks=[shock])).run().fingerprint()
    off = Simulation(_cfg(shocks=[shock.model_copy(update={"armed": False})])).run().fingerprint()
    none = Simulation(_cfg()).run().fingerprint()
    assert a == b and off == none and a != none


# --------------------------------------------------------------------------- detectors
def test_detectors_on_a_short_run_are_bounded():
    sim, smp = run_sampled(_cfg(duration_s=300))
    m = M.all_metrics(sim, smp)
    h = m["herding"]["herding_index_mean"]
    assert 0 <= h <= 1
    assert 0 <= m["influence_concentration"]["volume_gini"] <= 1
    assert m["influence_concentration"]["volume_hhi"] >= 1 / 256 - 1e-12
    ari = m["behavioral_clustering"]["ari_cluster_vs_programmed_kind"]
    assert -1 <= ari <= 1
    for v in m.values():
        assert "basis" in v, "every detector must state what is programmed"


def _fake_sim(log, decisions=None, neighbors=None, seed=1):
    agents = [SimpleNamespace(id=i, kind="noise", decisions=(decisions or {}).get(i, [])) for i in range(6)]
    return SimpleNamespace(
        liquidation_log=log,
        agents=agents,
        social=SimpleNamespace(neighbors=neighbors or [(1,), (0, 2), (1,), (4,), (3,), ()]),
        cfg=SimpleNamespace(seed=seed),
    )


def test_liquidation_cascade_clustering_and_secondary_window():
    log = [
        {"t": 900_000, "agent": 999, "kind": "external"},
        {"t": 930_000, "agent": 1, "kind": "leveraged"},
        {"t": 980_000, "agent": 2, "kind": "leveraged"},
        {"t": 1_300_000, "agent": 3, "kind": "momentum"},  # > 300 s after the external one
    ]
    r = M.liquidation_cascades(_fake_sim(log))
    assert r["clusters"] == 2 and r["max_cluster_size"] == 3 and r["multi_agent_clusters"] == 1
    assert r["secondary_after_external_300s"] == 2 and r["secondary_kinds"] == {"leveraged": 2}


def test_panic_contagion_counts_neighbour_preceded_events():
    dec = {
        0: [{"t": 1000, "action": "panic_sell"}],
        1: [{"t": 20_000, "action": "panic_sell"}],  # neighbour of 0, within 60 s
        3: [{"t": 500_000, "action": "panic_sell"}],  # isolated
    }
    r = M.panic_contagion(_fake_sim([], dec), n_perm=50)
    assert r["panic_events"] == 3
    assert r["neighbour_preceded_share"] == pytest.approx(1 / 3)


@given(st.lists(st.integers(0, 4), min_size=4, max_size=40))
@settings(max_examples=60, deadline=None)
def test_ari_properties(labels):
    a = np.array(labels)
    if len(set(labels)) < 2:
        return
    assert M.adjusted_rand_index(a, a) == pytest.approx(1.0)
    b = (a + 1) % 7  # relabelling does not change the partition
    assert M.adjusted_rand_index(a, b) == pytest.approx(1.0)
    rng = np.random.default_rng(0)
    c = rng.integers(0, 3, len(a))
    assert M.adjusted_rand_index(a, c) == pytest.approx(M.adjusted_rand_index(c, a))


@given(st.lists(st.floats(0, 1e6), min_size=2, max_size=50))
@settings(max_examples=60, deadline=None)
def test_gini_bounds(x):
    g = M._gini(np.array(x))
    if np.sum(x) > 0:
        assert -1e-9 <= g <= 1


# --------------------------------------------------------------------------- experiment verdict rule
def test_ci_verdict_requires_t_interval_for_support():
    assert E._ci_verdict({"lo": 0.1, "hi": 0.3, "t_lo": 0.05, "t_hi": 0.4}) == "supported"
    assert E._ci_verdict({"lo": 0.1, "hi": 0.3, "t_lo": -0.05, "t_hi": 0.4}) == "weak (bootstrap only)"
    assert E._ci_verdict({"lo": -0.1, "hi": 0.3, "t_lo": -0.2, "t_hi": 0.4}) == "not supported"
    assert E._ci_verdict({"lo": -0.3, "hi": -0.1, "t_lo": -0.4, "t_hi": -0.05}, -1) == "supported"


def test_experiment_jobs_are_paired_and_registered():
    sp = E.spec()
    a, b, c = E.jobs_A(sp), E.jobs_B(sp), E.jobs_C(sp)
    seeds = sp["common"]["seeds"]
    assert len(a) == 3 * len(seeds) and len(b) == 3 * len(seeds) and len(c) == 8 * len(seeds)
    for jobs in (a, b, c):
        for j in jobs:
            SimConfig(**j["cfg"])  # every job is a valid config
            assert j["cfg"]["world_annual_vol"] == 0.33 and j["cfg"]["news_impact"] == 0.0
    ctrl = [j for j in b if j["condition"] == "control"]
    assert all(not j["cfg"]["shocks"][0]["armed"] for j in ctrl)


# --------------------------------------------------------------------------- realism track
@given(
    st.dictionaries(st.sampled_from(["x", "y", "z"]), st.floats(0, 10), min_size=3, max_size=3),
    st.dictionaries(st.sampled_from(["x", "y", "z"]), st.floats(0, 10), min_size=3, max_size=3),
)
def test_dominance_is_irreflexive_and_antisymmetric(a, b):
    assert not R.dominates(a, a)
    assert not (R.dominates(a, b) and R.dominates(b, a))


def test_archive_admission_and_eviction():
    arc = {"rules_sha256": "x", "pareto": [], "history": []}
    e = lambda n, s, c: {"name": n, "objectives_mean": {"scale": s, "cost": c}}  # noqa: E731
    arc = R.update_archive(arc, e("a", 2.0, 1.0))
    arc = R.update_archive(arc, e("b", 1.0, 2.0))  # trade-off: both kept
    assert [p["name"] for p in arc["pareto"]] == ["a", "b"]
    arc = R.update_archive(arc, e("c", 3.0, 3.0))  # dominated: rejected
    assert [p["name"] for p in arc["pareto"]] == ["a", "b"] and arc["history"][-1]["dominated_by"] == "a"
    arc = R.update_archive(arc, e("d", 0.5, 0.5))  # dominates both
    assert [p["name"] for p in arc["pareto"]] == ["d"]


def test_cost_tolerance_and_behavioural_duplicates():
    tol = {"scale": 0.0, "cost": 0.25}
    a = {"name": "a", "objectives_mean": {"scale": 1.0, "cost": 10.0}, "fingerprints": ["x"]}
    b = {"name": "b", "objectives_mean": {"scale": 1.0, "cost": 8.5}, "fingerprints": ["y"]}
    assert not R.dominates(b["objectives_mean"], a["objectives_mean"], tol)  # 15% faster is timing noise
    arc = R.update_archive({"rules_sha256": "x", "pareto": [], "history": []}, a, tol)
    dup = {**b, "name": "c", "fingerprints": ["x"]}
    arc = R.update_archive(arc, dup, tol)
    assert [p["name"] for p in arc["pareto"]] == ["a"] and arc["history"][-1]["behavioural_duplicate_of"] == "a"


def test_noop_size_scale_is_rejected():
    with pytest.raises(ValueError, match="no effect"):
        Simulation(SimConfig(size_scale={"leveraged": 0.5}))
    Simulation(SimConfig(size_scale={"momentum": 0.5}))


def test_identical_candidate_is_not_an_improvement():
    obj = [{"scale_error": 1.0 + i, "shape_error": 0.5, "cost_cpu_s_per_sim_hour": 10.0} for i in range(3)]
    assert R.verdict(obj, obj)["verdict"] == "not an improvement"


def test_candidates_cannot_touch_evaluation_settings():
    spec, _ = R.rules()
    for bad in ({"seed": 1}, {"duration_s": 10}, {"shocks": []}):
        with pytest.raises(ValueError):
            R.validate_candidate(bad, spec["allowed_fields"])
    R.validate_candidate({"world_annual_vol": 0.33}, spec["allowed_fields"])


def test_archive_refuses_changed_rules(tmp_path, monkeypatch):
    rules = tmp_path / "rules.json"
    rules.write_text(R.RULES.read_text())
    arch = tmp_path / "archive.json"
    monkeypatch.setattr(R, "RULES", rules)
    monkeypatch.setattr(R, "ARCHIVE", arch)
    _, sha = R.rules()
    arch.write_text(json.dumps({"rules_sha256": sha, "pareto": [], "history": []}))
    R.load_archive(R.rules()[1])
    spec = json.loads(rules.read_text())
    spec["objectives"]["scale_error"]["facts"] = ["ret_std_bps"]  # an attempt to loosen the rules
    rules.write_text(json.dumps(spec))
    with pytest.raises(R.RulesChanged):
        R.load_archive(R.rules()[1])


def test_observatory_api_reads_current_versions():
    from fastapi.testclient import TestClient

    from evolutionx.api.app import app

    c = TestClient(app)
    idx = c.get("/api/observatory/index").json()
    assert f"realism_track_{R.VERSION}.json" in idx["frozen_specs_sha256"]
    r = c.get("/api/observatory/realism")
    if (R.ARCHIVE.parent / f"realism_{R.VERSION}.json").exists():
        assert r.status_code == 200 and r.json()["version"] == R.VERSION
    else:
        assert r.status_code == 404
