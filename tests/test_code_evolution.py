"""Level-4 code evolution: protection policy, security scan, sandboxed pipeline and human gate."""

import subprocess

import pytest

from evolutionx.council.schemas import CodeProposal
from evolutionx.evolution.archive import Archive
from evolutionx.evolution.code import policy
from evolutionx.evolution.code.pipeline import propose_and_evaluate, record_decision


@pytest.fixture(autouse=True)
def _proposals_in_tmp(tmp_path, monkeypatch):  # noqa: ANN001, ANN202
    from evolutionx.evolution.code import pipeline

    monkeypatch.setattr(pipeline, "PROP_DIR", tmp_path / "proposals")  # never write test proposals into artifacts/


@pytest.fixture(autouse=True)
def _cleanup_branches():
    before = set(subprocess.run(["git", "branch", "--list", "evo/*"], capture_output=True, text=True).stdout.split())
    yield
    after = set(subprocess.run(["git", "branch", "--list", "evo/*"], capture_output=True, text=True).stdout.split())
    for b in after - before - {"*", "+"}:
        subprocess.run(["git", "branch", "-D", b], capture_output=True)


def test_path_policy():
    assert policy.path_violations(["src/evolutionx/strategies/momentum.py"]) == []
    for bad in [
        "src/evolutionx/kernel/clearing.py",
        "src/evolutionx/evaluation/stats.py",
        "tests/test_x.py",
        "src/evolutionx/strategies/../kernel/x.py",
        "/etc/passwd",
        "src/evolutionx/strategies/params.py",
        "src/evolutionx/evolution/code/policy.py",
    ]:
        assert policy.path_violations([bad]), bad


@pytest.mark.parametrize(
    "src",
    [
        "import subprocess",
        "from os import system",
        "eval('1')",
        "open('/etc/passwd')",
        "x = ().__class__.__bases__",
        "import socket",
        "__import__('os')",
        "from ...kernel import clearing",
    ],
)
def test_security_scan_flags_dangerous_code(src):
    assert policy.security_scan(src, "strategies/x.py")


def test_security_scan_accepts_real_strategies():
    from pathlib import Path

    for p in Path("src/evolutionx/strategies").glob("*.py"):
        assert policy.security_scan(p.read_text(), str(p)) == [], p


def test_protected_manifest_covers_kernel_and_policy():
    from pathlib import Path

    m = policy.protected_manifest(Path("."))
    assert "src/evolutionx/kernel/clearing.py" in m
    assert "src/evolutionx/evolution/code/policy.py" in m
    assert "evals/frozen/suite.json" in m
    assert not any(k.startswith("src/evolutionx/strategies/") and not k.endswith("params.py") for k in m)


def test_kernel_edit_is_rejected_before_any_worktree(tmp_path):
    A = Archive(tmp_path / "e.db")
    r = propose_and_evaluate("redteam-kernel-fee-bypass", archive=A)
    assert r["status"] == "policy_rejected"
    assert [g["name"] for g in r["report"]["gates"]] == ["protection_policy"]
    with pytest.raises(ValueError):
        record_decision(r["id"], "approve", "alice", "", archive=A)


def test_unsafe_strategy_fails_security_and_is_never_executed(tmp_path):
    A = Archive(tmp_path / "e.db")
    r = propose_and_evaluate("redteam-shell-escape", archive=A)
    names = {g["name"]: g["passed"] for g in r["report"]["gates"]}
    assert r["status"] == "gates_failed" and names["security_scan"] is False
    assert "tests" not in names  # pipeline stops before running candidate code


def test_schema_rejects_paths_outside_package():
    with pytest.raises(ValueError):
        CodeProposal.model_validate(
            {
                "key": "abc",
                "title": "t",
                "rationale": "r",
                "hypothesis": "h",
                "edits": [{"path": "../../etc/x.py", "search": "a", "replace": "b"}],
            }
        )


@pytest.mark.slow
def test_full_sandboxed_proposal_reaches_human_gate(tmp_path):
    A = Archive(tmp_path / "e.db")
    r = propose_and_evaluate("noise-panic-hysteresis", archive=A)
    gates = {g["name"]: g["passed"] for g in r["report"]["gates"]}
    assert set(gates) == {
        "protection_policy",
        "apply_patch",
        "protected_integrity",
        "security_scan",
        "lint_format",
        "tests",
        "deterministic_replay",
        "performance_benchmark",
        "frozen_eval_suite",
    }
    assert r["status"] == ("awaiting_approval" if all(gates.values()) else "gates_failed")
    assert "worktree" in r["report"] and r["report"]["diff"].count("obs.social < -0.5") == 1
    if r["status"] == "awaiting_approval":
        d = record_decision(r["id"], "approve", "alice", "looks good", archive=A)
        assert d["status"] == "approved" and "Nothing has been merged" in d["decision"]["merge_instructions"]
        with pytest.raises(ValueError):
            record_decision(r["id"], "reject", "bob", "", archive=A)
