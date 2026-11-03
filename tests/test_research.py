"""Acceptance tests for the research loop (E, F, H, I). These test MECHANISMS on controlled synthetic data; they are
not scientific findings about markets."""

import copy
import json
import os
from pathlib import Path

import numpy as np
import pytest
from fixtures.strategies import ANTI, ESCAPE, FRAGILE, GOOD

from evolutionx.data.datasets import protocol
from evolutionx.research import sandbox
from evolutionx.research.evaluator import CandidateFailure, EvalConfig, evaluate, sandbox_decisions
from evolutionx.research.generator import OfflineGenerator, Proposal, code_hash
from evolutionx.research.supervisor import POLICY, Lab, Supervisor
from evolutionx.research.synthetic import TrendData, synthetic_protocol

pytestmark = pytest.mark.skipif(not sandbox.AVAILABLE, reason="namespace sandbox unavailable")

DATA = TrendData()
PROTO = synthetic_protocol(protocol(), DATA.symbols)


def policy(auto: bool = True) -> dict:
    p = json.loads(POLICY.read_text())
    p = copy.deepcopy(p)
    for m in p["modes"].values():
        m.update(causality_checks=2, symbols=None, dev_tail_bars=None)
    p["modes"]["autonomous-experimental"]["auto_activate"] = auto
    return p


class FixedGenerator:
    """Test double that proposes given sources (to build controlled promotion/rollback/scope examples)."""

    name = "fixed-test-generator"

    def __init__(self, sources: list[str], files: list[str] | None = None) -> None:
        self.sources, self.files, self.i = sources, files, 0

    def propose(self, op, parent, rng, budget):  # noqa: ANN001
        src = self.sources[min(self.i, len(self.sources) - 1)]
        self.i += 1
        cid = "fixed-" + code_hash(src)[:10]
        return Proposal(
            cid,
            parent["id"],
            op,
            {"statement": "controlled example"},
            {},
            src,
            "",
            self.files or [f"src/evolutionx/evolvable/generated/{cid}.py"],
            "contract",
            "n/a",
            "n/a",
            budget,
            "n/a",
            self.name,
            code_hash(src),
            [],
        )


def lab_with(tmp_path: Path, champion: str, gen, auto: bool = True) -> tuple[Lab, Supervisor]:  # noqa: ANN001
    lab = Lab(tmp_path / "lab")
    lab.registry.bootstrap(champion, "anti_champion")
    return lab, Supervisor(lab, DATA, PROTO, policy(auto), gen)


def test_E_autonomous_cycle_with_generated_patch(tmp_path):
    lab = Lab(tmp_path / "lab")
    lab.registry.bootstrap(Path("src/evolutionx/evolvable/tsmom_v0.py").read_text(), "tsmom_v0")
    sup = Supervisor(lab, DATA, PROTO, policy(), OfflineGenerator())
    sup.create_campaign("c1", "autonomous-experimental", "guided", 1, 600)
    st = sup.run("c1")
    t = lab.memory.q("SELECT * FROM tasks")[0]
    ck = t["checkpoint"]
    assert t["status"] == "done" and ck["archived"]["verdict"] in ("promote", "refuted", "inconclusive", "rejected")
    task = t["task"]
    for field in (
        "hypothesis",
        "mechanism",
        "alternatives",
        "testable_prediction",
        "primary_metric",
        "minimal_useful_effect",
        "refutation_criteria",
        "allowed_data",
        "time_split",
        "statistical_plan",
        "stopping_rule",
        "preregistration_sha256",
        "budget",
    ):
        assert task[field], field
    cand = lab.root / "candidates" / ck["candidate_id"]
    diff = (cand / "patch.diff").read_text()
    added = [ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    assert diff.startswith("--- a/v0.py") and any(ln.startswith(("+def ", "+    x = ")) for ln in added)
    assert json.loads((cand / "proposal.json").read_text())["generator"] == "offline-grammar-v1"
    assert lab.memory.q("SELECT status FROM hypotheses")[0]["status"] in (
        "confirmed",
        "refuted",
        "inconclusive",
        "failed",
    )
    assert st["journal"]["ok"]


def test_F_controlled_promotion_changes_next_run(tmp_path):
    lab, sup = lab_with(tmp_path, ANTI, FixedGenerator([GOOD]))
    sup.create_campaign("c", "autonomous-experimental", "guided", 1, 600)
    sup.run("c")
    ck = lab.memory.q("SELECT checkpoint FROM tasks")[0]["checkpoint"]
    assert ck["verdict"] == "promote" and ck["activation"]["activated"] is True
    act = lab.registry.active()
    assert act["version"] == 1 and act["sha256"] == code_hash(GOOD)
    v, src = lab.registry.load_source()
    assert src == GOOD  # the next run loads the promoted code
    assert lab.registry.versions()[0]["candidate_id"] == "anti_champion"  # previous champion preserved


def test_F_automatic_rollback_on_post_activation_failure(tmp_path):
    lab, sup = lab_with(tmp_path, ANTI, FixedGenerator([FRAGILE]))
    sup.create_campaign("c", "autonomous-experimental", "guided", 1, 600)
    sup.run("c")
    ck = lab.memory.q("SELECT checkpoint FROM tasks")[0]["checkpoint"]
    assert ck["verdict"] == "promote"  # it genuinely won the statistical test...
    act = ck["activation"]
    assert act["activated"] is False and act["rolled_back_to"] == 0  # ...but failed the canary and was rolled back
    assert lab.registry.active()["version"] == 0
    events = [e["event"] for e in lab.journal.tail(50)]
    assert "activate" in events and "rollback" in events
    assert lab.journal.verify()["ok"]


def test_F_research_mode_never_auto_activates(tmp_path):
    lab, sup = lab_with(tmp_path, ANTI, FixedGenerator([GOOD]), auto=False)
    sup.create_campaign("c", "research", "guided", 1, 600)
    sup.run("c")
    ck = lab.memory.q("SELECT checkpoint FROM tasks")[0]["checkpoint"]
    assert ck["verdict"] == "promote" and ck["activation"]["activated"] is False
    assert lab.registry.active()["version"] == 0


def test_manual_rollback(tmp_path):
    lab, sup = lab_with(tmp_path, ANTI, FixedGenerator([GOOD]))
    sup.create_campaign("c", "autonomous-experimental", "guided", 1, 600)
    sup.run("c")
    assert lab.registry.rollback("alice", "test")["active"] == 0
    assert lab.registry.active()["version"] == 0


def test_H_sandbox_blocks_escape_and_forged_reports(tmp_path):
    reg = tmp_path / "lab" / "registry" / "active.json"
    reg.parent.mkdir(parents=True)
    reg.write_text('{"version": 0}')
    src = ESCAPE.format(
        registry=str(reg),
        vault=str(Path("data/vault/BTCUSDT_1h_final.npz").resolve()),
        data_dir=str(Path("data").resolve()),
        tests=str(Path("tests/test_research.py").resolve()),
    )
    os.environ["EVOX_FAKE_SECRET"] = "s3cr3t"
    try:
        out_root = tmp_path / "probe"
        out_root.mkdir()
        ind = out_root / "in"
        ind.mkdir()
        (ind / "candidate.py").write_text(src)
        np.savez(ind / "d.npz", **DATA.get("SYN1", "validation"))
        (ind / "job.json").write_text(json.dumps({"items": [{"data": "d.npz", "params": {"n": 1}}]}))
        res = sandbox.run("evolutionx.research.entry", ["/in", "/out"], ind, out_root / "out")
        probe = json.loads((out_root / "out" / "probe.json").read_text())
    finally:
        os.environ.pop("EVOX_FAKE_SECRET")
    allowed = {k for k, v in probe.items() if v[0] != "blocked"}
    assert allowed == {"symlink_out"}, allowed  # /out is writable by design; the evaluator never follows links
    assert reg.read_text() == '{"version": 0}'
    assert res["returncode"] != 0  # entry could not write dec_0.npy over the planted symlink... or did; see next
    # the trusted evaluator path: forged report and symlinked outputs are never trusted
    with pytest.raises(CandidateFailure) as e:
        sandbox_decisions(src, [("d", DATA.get("SYN1", "validation"), {"n": 1})], EvalConfig(PROTO, 0), "esc")
    assert e.value.gate in ("sandbox_execution", "output_integrity")


def test_H_out_of_scope_patch_and_static_violations_rejected(tmp_path):
    lab, sup = lab_with(tmp_path, ANTI, FixedGenerator([GOOD], files=["src/evolutionx/kernel/clearing.py"]))
    sup.create_campaign("c", "autonomous-experimental", "guided", 1, 600)
    sup.run("c")
    ck = lab.memory.q("SELECT checkpoint FROM tasks")[0]["checkpoint"]
    assert ck["verdict"] == "rejected" and ck["rejection"]["gate"] == "scope"
    bad = GOOD.replace("from __future__ import annotations", "from __future__ import annotations\nimport os")
    with pytest.raises(CandidateFailure) as e:
        evaluate(bad, "x", DATA, EvalConfig(PROTO, 1), 1)
    assert e.value.gate == "static_admissibility"


def test_H_resource_exhaustion_and_invalid_decisions(tmp_path):
    hog = GOOD.replace("    c = view.close", "    while True:\n        pass\n    c = view.close")
    with pytest.raises(CandidateFailure) as e:
        sandbox_decisions(
            hog,
            [("d", DATA.get("SYN1", "validation"), {"n": 24})],
            EvalConfig(PROTO, 0, sandbox.Limits(cpu_s=2, wall_s=10)),
            "hog",
        )
    assert e.value.gate == "sandbox_execution"
    lev = GOOD.replace("return 0.5 if", "return 5.0 if")  # tries to exceed leverage bounds
    with pytest.raises(CandidateFailure) as e:
        sandbox_decisions(lev, [("d", DATA.get("SYN1", "validation"), {"n": 24})], EvalConfig(PROTO, 0), "lev")
    assert e.value.gate == "decision_validity"


def test_H_leak_through_input_file_is_caught_by_physical_truncation(tmp_path, monkeypatch):
    """Even if static checks are bypassed, a candidate that reads the future from its input file is caught: in the
    secret-checkpoint runs the file physically ends at the checkpoint, so its decisions differ."""
    leaky = """from __future__ import annotations

import numpy as np

NAME = "leaky_file"
PARAMS = {"n": 1}
PARAM_GRID = {"n": [1]}


def _future(t):
    for f in ("/in/SYN1_devval.npz", "/in/SYN1_cut.npz", "/in/SYN2_devval.npz", "/in/SYN2_cut.npz"):
        try:
            c = np.load(f)["close"]
        except OSError:
            continue
        return float(c[t + 1] - c[t]) if t + 1 < len(c) else 0.0
    return 0.0


def signal(view, p):
    return 0.5 if _future(view.t) > 0 else -0.5
"""
    from evolutionx.research import contract, evaluator

    assert contract.static_check(leaky)  # the static layer flags numpy file IO...
    monkeypatch.setattr(evaluator, "static_check", lambda s: [])  # ...but suppose it missed it
    with pytest.raises(CandidateFailure) as e:
        evaluate(leaky, "leak", DATA, EvalConfig(PROTO, 6), 3)
    assert e.value.gate == "causality" and e.value.detail["violations"]


def test_I_crash_and_resume_without_duplicate_experiments(tmp_path, monkeypatch):
    lab, sup = lab_with(tmp_path, ANTI, FixedGenerator([GOOD, ANTI.replace("anti_trend", "anti2")]))
    sup.create_campaign("c", "research", "guided", 2, 600)
    monkeypatch.setenv("EVOX_TEST_CRASH_AFTER_STAGE", "EXPERIMENT")
    with pytest.raises(SystemExit):
        sup.run("c")
    t1 = lab.memory.q("SELECT stage, status FROM tasks")[0]
    assert t1 == {"stage": "EVALUATE", "status": "open"}
    n_exp = len(lab.memory.q("SELECT key FROM experiments"))
    monkeypatch.delenv("EVOX_TEST_CRASH_AFTER_STAGE")
    sup2 = Supervisor(lab, DATA, PROTO, policy(False), sup.generator)  # fresh process state, same persistent lab
    st = sup2.run("c")
    tasks = lab.memory.q("SELECT status FROM tasks")
    assert [t["status"] for t in tasks] == ["done", "done"] and st["campaign"]["status"] == "budget_exhausted"
    exp_events = [e for e in lab.journal.tail(200) if e["event"] == "experiment"]
    cands = [e["data"]["candidate"] for e in exp_events]
    assert len(cands) == len(set(cands))  # every candidate evaluated exactly once
    assert len(lab.memory.q("SELECT key FROM experiments")) > n_exp


def test_user_stop_has_priority_and_needs_human_resume(tmp_path):
    lab, sup = lab_with(tmp_path, ANTI, FixedGenerator([GOOD]))
    sup.create_campaign("c", "research", "guided", 3, 600)
    sup.request_stop("user", "stop now")
    st = sup.run("c")
    assert st["campaign"]["status"] == "stopped_by_user" and st["tasks"] == []
    st = sup.run("c")  # the system does not restart itself
    assert st["campaign"]["status"] == "stopped_by_user" and st["tasks"] == []
    with pytest.raises(PermissionError):
        sup.human_resume("user", confirm=False)
    sup.human_resume("user", confirm=True)
    sup.create_campaign("c", "research", "guided", 3, 600)
    assert sup.run("c", max_steps=3)["tasks"]


def test_budget_caps_cannot_be_raised(tmp_path):
    lab, sup = lab_with(tmp_path, ANTI, FixedGenerator([GOOD]))
    c = sup.create_campaign("big", "research", "guided", 10_000, 10**9)
    assert c["budget"]["max_tasks"] == 60 and c["budget"]["max_wall_s"] == 14400 and c["budget"]["max_llm_tokens"] == 0


def test_design_uses_exploration_parent_source_and_records_lineage(tmp_path):
    """Regression: when the hypothesis names a candidate as design parent, the child must extend THAT source."""
    import random

    from evolutionx.research.generator import OfflineGenerator as G

    lab = Lab(tmp_path / "lab")
    v0 = Path("src/evolutionx/evolvable/tsmom_v0.py").read_text()
    lab.registry.bootstrap(v0, "tsmom_v0")
    sup = Supervisor(lab, DATA, PROTO, policy(), G())
    parent = G().propose(
        "add_funding_guard", {"id": "v0", "spec": Supervisor._spec_of(v0), "source": v0}, random.Random(1), {}
    )
    d = lab.root / "candidates" / parent.candidate_id
    d.mkdir(parents=True)
    (d / "strategy.py").write_text(parent.source)
    act = lab.registry.active()
    ck = {
        "parent_version": 0,
        "parent_sha": act["sha256"],
        "operator": "add_vol_target",
        "design_parent": parent.candidate_id,
        "design_parent_kind": "candidate",
        "design_parent_sha": parent.code_sha256,
        "hypothesis_id": "h",
    }
    out = sup._s_design({"id": "c", "config": {"seed": 0}, "budget": {"sandbox": {}}}, {"id": "t1"}, ck, DATA)
    child = (lab.root / "candidates" / out["candidate_id"] / "strategy.py").read_text()
    assert "_f_funding_guard" in child and "_f_vol_target" in child
    row = lab.memory.q("SELECT parent_id FROM candidates WHERE id=?", (out["candidate_id"],))[0]
    assert row["parent_id"] == parent.candidate_id
    with pytest.raises(CandidateFailure):  # tampered parent source is refused
        (d / "strategy.py").write_text(parent.source + "\n# tampered\n")
        sup._s_design({"id": "c", "config": {"seed": 0}, "budget": {"sandbox": {}}}, {"id": "t2"}, dict(ck), DATA)


def test_exhausted_search_space_stops_instead_of_proposing_duplicates(tmp_path):
    from evolutionx.research.hypothesizer import ALL_OPS, signature

    lab = Lab(tmp_path / "lab")
    lab.registry.bootstrap(ANTI, "anti")
    sha = lab.registry.active()["sha256"]
    for op in ALL_OPS:  # every operator already tested on the only available parent
        lab.memory.x("INSERT INTO hypotheses VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (f"h-{op}", signature(sha, op), op, op, "v0", None, "refuted", "{}", "", "x", "x"))
    sup = Supervisor(lab, DATA, PROTO, policy(), FixedGenerator([GOOD]))
    sup.create_campaign("c", "research", "guided", 5, 600)
    st = sup.run("c")
    assert st["campaign"]["status"] == "search_space_exhausted"
    assert len(lab.memory.q("SELECT id FROM tasks")) == 1 and not lab.memory.q("SELECT id FROM candidates")
