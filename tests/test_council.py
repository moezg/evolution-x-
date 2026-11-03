"""Research council: schema-validated, grounded outputs; budgets enforced; offline by default."""

import pytest

from evolutionx.council.llm import Budget, LLMBudgetExceeded, LLMClient, MockLLM, render_user
from evolutionx.council.schemas import RoleReport
from evolutionx.council.workflow import run_council
from evolutionx.evolution.archive import Archive


def test_council_runs_offline_with_eight_validated_roles(tmp_path):
    d = run_council("why?", archive=Archive(tmp_path / "e.db"))
    assert d["llm"]["provider"] == "mock" and d["llm"]["calls"] == 8
    assert len(d["roles"]) == 8
    for r in d["roles"]:
        RoleReport.model_validate(r["output"])
        assert set(r["output"]) >= {"observations", "hypotheses", "assumptions", "conclusions"}
    assert d["synthesis"]["prioritised_experiments"]


def test_budget_and_validation_retry():
    m = MockLLM()
    calls = {"n": 0}

    def bad(_ctx):
        calls["n"] += 1
        return {"role": "nope"}

    m.rules["bad"] = bad
    c = LLMClient(m, Budget(max_calls=2, retries=5), use_cache=False)
    with pytest.raises(LLMBudgetExceeded):
        c.json("s", render_user("u", {"_rule": "bad"}), RoleReport.model_validate)
    assert calls["n"] == 2
