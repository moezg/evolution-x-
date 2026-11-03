"""Evolution engine: operators stay in bounds, Pareto logic, archive lineage, champion/challenger + rollback."""

import random

from evolutionx.evolution.archive import Archive
from evolutionx.evolution.genome import crossover, mutate, seed_genome
from evolutionx.evolution.loop import EvolutionRun
from evolutionx.evolution.selection import dominates, pareto_ranks, select
from evolutionx.strategies.params import PARAM_SPECS


def test_mutation_and_crossover_respect_bounds():
    rng = random.Random(0)
    for fam, spec in PARAM_SPECS.items():
        g = seed_genome(fam)
        for _ in range(50):
            g = mutate(fam, g, rng, sigma=1.0, p_gene=1.0)
            g = crossover(fam, g, seed_genome(fam), rng)
            for k, (_d, lo, hi) in spec.items():
                assert lo <= g[k] <= hi


def test_pareto_ranks_and_select():
    pts = [[1, 1], [2, 0], [0, 2], [0, 0], [1, 0]]
    assert dominates([1, 1], [0, 0]) and not dominates([2, 0], [0, 2])
    assert pareto_ranks(pts) == [0, 0, 0, 2, 1]
    cands = [{"objectives": {"a": p[0], "b": p[1]}} for p in pts]
    chosen = select(cands, ["a", "b"], 3)
    assert all(c["pareto_rank"] == 0 for c in chosen)


def test_archive_promote_and_rollback(tmp_path):
    A = Archive(tmp_path / "e.db")
    for cid in ("a", "b"):
        A.add_candidate({"id": cid, "family": "momentum", "run_id": "r", "generation": 0, "origin": "x", "genome": {}})
    A.promote("momentum", "a", "init", {})
    A.promote("momentum", "b", "better", {})
    assert A.active_champion("momentum")["candidate_id"] == "b"
    A.rollback("momentum", actor="tester")
    assert A.active_champion("momentum")["candidate_id"] == "a"
    assert A.candidate("b")["status"] == "retired"
    actions = [r["action"] for r in A.query("SELECT action FROM audit")]
    assert actions.count("promote_champion") == 2 and "rollback_champion" in actions


def test_small_evolution_run_produces_auditable_decision(tmp_path):
    A = Archive(tmp_path / "e.db")
    r = EvolutionRun(
        "momentum",
        generations=1,
        pop=3,
        train_seeds=1,
        val_seeds=2,
        heldout_seeds=1,
        duration_s=300,
        workers=2,
        seed=1,
        archive=A,
    ).run()
    assert r["decision"]["decision"] in ("promoted", "rejected")
    ch = A.challenges("momentum")
    assert len(ch) == 1 and ch[0]["evidence"]["paired_diff"]["n"] == 6  # 2 seeds x 3 validation regimes
    cands = A.candidates("momentum")
    assert len(cands) >= 4 and any(c["parents"] for c in cands)
    assert "paired_diff_vs_default" in r["heldout"]
