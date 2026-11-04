"""On-demand specialist agents: deterministic validation of everything an LLM says (citations exist, quotes are
verbatim, data is available, duplicates rejected), per-role/session budgets, and an offline session with a FAKE LLM
and FAKE arXiv records (clearly synthetic; no network, no LLM calls)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolutionx.army import specialists as SP
from evolutionx.army.llm import LLM
from evolutionx.army.sources import SourceItem
from evolutionx.army.store import Store

REPO = Path(__file__).resolve().parents[1]
ITEM = {"id": "2401.00001", "title": "Synthetic paper", "abstract": "We find that crypto volatility rises sharply after scheduled central bank announcements.", "url": "u", "published": "p", "retrieved": "r"}  # fmt: skip
ROWS = [
    {"id": "T-a", "hypothesis": "F-FOMC:absret_0_4h", "period": "DISCOVERY", "family": "F-FOMC", "status": "supported", "effect": 0.6, "n": 39, "p_adj": 0.01},
    {"id": "T-b", "hypothesis": "F-FOMC:absret_0_4h", "period": "CONFIRMATION", "family": "F-FOMC", "status": "supported", "effect": 0.7, "n": 29, "p_adj": 0.001},
    {"id": "T-c", "hypothesis": "F-DOM:14:mean_ret_wd_adj", "period": "DISCOVERY", "family": "F-DOM", "status": "rejected", "effect": 0.0, "n": 64, "p_adj": 0.9},
]  # fmt: skip


def prop(**kw):
    base = dict(family="F-FOMC", label="sep", metric="absret_0_4h", direction=1, statement="s", rationale="r", cites_tests=["T-a"], data_needed=["btc_spot_1h", "fomc_calendar"], prospective_evaluation="p")  # fmt: skip
    return SP.ProposalOut(**(base | kw))


def test_scout_quote_must_be_verbatim_and_record_fetched():
    ok = SP.ScoutOut(
        arxiv_id="2401.00001", claim="c", verbatim_quote="volatility rises  sharply after scheduled", relevance="r"
    )
    assert SP.validate_scout(ok, [ITEM])["valid"]
    fake = ok.model_copy(update={"verbatim_quote": "volatility collapses after every announcement"})
    assert not SP.validate_scout(fake, [ITEM])["valid"]
    other = ok.model_copy(update={"arxiv_id": "9999.99999"})
    assert "not among the fetched" in SP.validate_scout(other, [ITEM])["reason"]


def test_proposal_validation():
    assert SP.validate_proposal(prop(), ROWS, set(), set())["status"] == "queued_prospective"
    assert (
        SP.validate_proposal(prop(family="F-DOM", label="14", metric="mean_ret_wd_adj"), ROWS, set(), set())["status"]
        == "rejected_duplicate"
    )
    assert SP.validate_proposal(prop(), ROWS, {"F-FOMC:sep:absret_0_4h"}, set())["status"] == "rejected_duplicate"
    v = SP.validate_proposal(prop(data_needed=["consensus_expectations"]), ROWS, set(), set())
    assert v["status"] == "rejected_invalid" and "unavailable" in v["reasons"][0]
    assert SP.validate_proposal(prop(cites_tests=["T-zzz"]), ROWS, set(), set())["status"] == "rejected_invalid"
    v = SP.validate_proposal(prop(cites_tests=["T-b"]), ROWS, set(), set())  # confirmation rows are out of context
    assert v["status"] == "rejected_invalid" and "DISCOVERY" in v["reasons"][0]
    assert SP.validate_proposal(prop(cites_sources=["1234.5"]), ROWS, set(), set())["status"] == "rejected_invalid"
    # regression from the first real session: free text in `label` must not disguise a registered hypothesis
    v = SP.validate_proposal(prop(label="FOMC statement 4h abs-return spike vs m"), ROWS, set(), set())
    assert v["status"] == "rejected_invalid" and "identifier" in v["reasons"][0]
    v = SP.validate_proposal(prop(label="spike"), ROWS, set(), set())
    assert v["status"] == "rejected_duplicate" and "conditioning attribute" in v["reasons"][0]


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "evals").symlink_to(REPO / "evals")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_offline_session_with_fake_llm(ws, monkeypatch):
    from evolutionx.quant.stats import TestRegistry

    reg = TestRegistry()
    reg.record(
        {
            "family": "F-FOMC",
            "hypothesis": "F-FOMC:absret_0_4h",
            "period": "DISCOVERY",
            "method": "m",
            "run_id": "r",
            "status": "supported",
        }
    )
    fomc_id = reg.rows()[0]["id"]
    item = SourceItem(id="2401.00001", origin="arxiv", url="u", title="Synthetic paper", authors=[], published="p", updated="p", retrieved="r", abstract=ITEM["abstract"], doi=None, journal_ref=None, license_note="", query="q")  # fmt: skip
    monkeypatch.setattr(SP.SRC, "search_arxiv", lambda q, max_results=4: [item])
    calls = []

    def fake_ask(self, role, prompt, schema):
        calls.append(role)
        assert "CONFIRMATION" not in prompt or role != "G1" or '"period"' not in prompt
        if role == "A1":
            return SP.ScoutOut(
                arxiv_id="2401.00001",
                claim="c",
                verbatim_quote="volatility rises sharply after scheduled",
                relevance="r",
            ), {"used_llm": True}
        if role == "G1":
            return prop(cites_tests=[fomc_id], cites_sources=["2401.00001"]), {"used_llm": True}
        return schema(concerns=["x"], most_likely_failure="y", additional_test="z"), {"used_llm": True}

    monkeypatch.setattr(SP.SpecialistLLM, "ask", fake_ask)
    out = SP.session()
    assert calls == ["A1", "G1", "E3"]
    st = [(p["by"], p["validation"]["status"]) for p in out["proposals"]]
    assert st == [
        ("G1 (LLM)", "queued_prospective"),
        ("planted control", "rejected_duplicate"),
        ("planted control", "rejected_invalid"),
    ]
    assert out["lineage"]["sources"] == ["2401.00001"] and fomc_id in out["lineage"]["tests_cited"]
    assert (ws / "artifacts/army/specialists" / f"{out['session']}.json").exists()
    out2 = SP.session()  # the same proposal again is now a duplicate of the queued one
    assert out2["proposals"][0]["validation"]["status"] == "rejected_duplicate"


def test_specialist_budgets(ws, monkeypatch):
    s = Store()
    llm = SP.SpecialistLLM(s, "spec-x")
    monkeypatch.setattr(SP.shutil if hasattr(SP, "shutil") else __import__("shutil"), "which", lambda b: "/bin/claude")
    assert llm.allowed("A1") == (True, "ok")
    assert llm.allowed("C1")[0] is False  # strategy formulators get no specialist calls
    s.add_usage("spec-x", "A1", llm_calls=1, cost=0.1)
    assert "role A1" in llm.allowed("A1")[1]
    s.add_usage("spec-x", "G1", llm_calls=1, cost=2.0)
    assert "USD budget" in llm.allowed("E3")[1]
    assert isinstance(llm, LLM)
