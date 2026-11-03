"""Premise verification, behaviour diagnostics, classification, memory migration, dossier (understanding tests)."""

import json
import sqlite3

import numpy as np
import pytest

from evolutionx.backtest.engine import CostModel
from evolutionx.research import premises as P
from evolutionx.research.behaviour import behaviour
from evolutionx.research.lessons import classify, mechanism_result
from evolutionx.research.memory import SCHEMA_VERSION, Memory

H = 3_600_000
PARENT = {
    "BTCUSDT": {
        "small_change_execution_ratio": 0.49,
        "decision_change_rate": 0.70,
        "trading_cost_share": 0.91,
        "funding_cost_share": 0.31,
        "avg_holding_bars": 33.0,
        "mean_abs_exposure": 0.6,
    }
}


def test_rebalance_misconception_is_rejected_before_backtest():
    """The claude -p candidate (cli-2) assumed the executor rebalances on every small change; a band exists."""
    feats = P.feature_registry()
    assert feats["rebalance_band"]["present"] and "engine.py" in feats["rebalance_band"]["code"]["file"]
    res = P.verify(
        [
            {
                "id": "P1",
                "claim": "no rebalance band",
                "check": {"type": "engine_feature", "feature": "rebalance_band", "expect": "absent"},
            },
            {
                "id": "P2",
                "claim": "every small change is executed",
                "check": {
                    "type": "parent_metric",
                    "metric": "small_change_execution_ratio",
                    "symbol": "BTCUSDT",
                    "op": ">",
                    "value": 0.9,
                },
            },
            {
                "id": "P3",
                "claim": "signal changes on most bars",
                "check": {
                    "type": "parent_metric",
                    "metric": "decision_change_rate",
                    "symbol": "BTCUSDT",
                    "op": ">",
                    "value": 0.5,
                },
            },
        ],
        feats,
        P.view_api(),
        PARENT,
    )
    st = {r["id"]: r["status"] for r in res["results"]}
    assert st == {"P1": "falsified", "P2": "falsified", "P3": "verified"} and res["verdict"] == "rejected_false_premise"


def test_correct_premises_pass_and_bad_checks_are_rejected():
    feats, api = P.feature_registry(), P.view_api()
    ok = P.verify(
        [
            {
                "id": "P1",
                "claim": "about half of small changes still trade",
                "check": {
                    "type": "parent_metric",
                    "metric": "small_change_execution_ratio",
                    "symbol": "BTCUSDT",
                    "op": ">",
                    "value": 0.3,
                },
            },
            {
                "id": "P2",
                "claim": "funding visible",
                "check": {"type": "view_api", "method": "funding", "expect": "present"},
            },
        ],
        feats,
        api,
        PARENT,
    )
    assert ok["verdict"] == "accepted"
    assert (
        P.verify(
            [{"id": "P1", "claim": "x", "check": {"type": "view_api", "method": "orderbook", "expect": "present"}}],
            feats,
            api,
            PARENT,
        )["verdict"]
        == "rejected_false_premise"
    )  # BarView has no order book
    assert (
        P.verify([{"id": "P1", "claim": "x", "check": {"type": "unverifiable", "reason": "r"}}], feats, api, PARENT)[
            "verdict"
        ]
        == "rejected_unverifiable"
    )
    assert (
        P.verify(
            [
                {
                    "id": "P1",
                    "claim": "x",
                    "check": {"type": "parent_metric", "metric": "made_up", "op": ">", "value": 1},
                }
            ],
            feats,
            api,
            PARENT,
        )["verdict"]
        == "rejected_malformed"
    )


def test_every_engine_feature_probe_runs_and_points_to_code():
    for name, f in P.feature_registry().items():
        assert f["present"], name
        assert f["code"]["line"] is not None, name


def _bars(r):
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[100, c[:-1]]
    t = 1_577_836_800_000 + np.arange(len(c), dtype=np.int64) * H
    return {
        "open_time": t,
        "open": o,
        "high": np.maximum(o, c) * 1.001,
        "low": np.minimum(o, c) * 0.999,
        "close": c,
        "volume": np.full(len(c), 1e9),
        "available_at": t + H,
        "funding": np.zeros(len(c)),
    }


def test_behaviour_flags_ruin_and_keeps_later_years_meaningful():
    n = 24 * 365 * 2
    r = np.random.default_rng(0).normal(0, 0.002, n)
    d = _bars(r)
    d["low"][500] = d["open"][500] * 0.2  # crash in year 1 -> liquidation at max leverage
    out = behaviour(d, np.ones(n), CostModel(max_leverage=2.0))
    assert out["ruined_segments"] == [2020]
    assert out["per_year"]["2021"]["max_drawdown"] < 0.99  # the second year starts with fresh equity


def test_classification_distinguishes_outcomes():
    pd_ = {
        "BTCUSDT": {
            "net_sharpe": 0.2,
            "gross_sharpe": 0.5,
            "turnover_per_year": 800,
            "max_drawdown": 0.5,
            "trading_cost_share": 0.9,
            "avg_holding_bars": 30,
        }
    }
    costs_ate = {"BTCUSDT": {**pd_["BTCUSDT"], "gross_sharpe": 0.8, "net_sharpe": 0.1}}
    assert (
        classify({"verdict": "refuted", "screen": {"passed": False}}, costs_ate, pd_)["class"]
        == "benefit_absorbed_by_costs"
    )
    mech = mechanism_result(
        {"metric": "turnover_per_year", "symbol": "ALL", "direction": "decrease", "min_relative_change": 0.1},
        {"BTCUSDT": {**pd_["BTCUSDT"], "turnover_per_year": 790}},
        pd_,
    )
    assert mech["observed"] is False
    assert classify({"verdict": "refuted", "mechanism": mech}, pd_, pd_)["class"] == "mechanism_not_observed"
    assert classify({"verdict": "refuted", "screen": {"passed": True}}, pd_, pd_)["class"] == "unstable_across_periods"
    assert (
        classify({"verdict": "inconclusive", "screen": {"passed": True}}, pd_, pd_)["class"] == "insufficient_evidence"
    )
    assert (
        classify({"premise_check": {"verdict": "rejected_false_premise", "counts": {}}}, None, None)["class"]
        == "technically_false_premise"
    )


def test_memory_migrates_existing_v1_store_in_place(tmp_path):
    db = tmp_path / "research.db"
    c = sqlite3.connect(db)
    c.executescript("""CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT); INSERT INTO meta VALUES ('schema_version','1');
    CREATE TABLE hypotheses (id TEXT PRIMARY KEY, signature TEXT, statement TEXT, operator TEXT, parent_id TEXT,
    candidate_id TEXT, status TEXT, evidence TEXT, novelty TEXT, created TEXT, updated TEXT);
    INSERT INTO hypotheses VALUES ('h1','s','old','op','v0',NULL,'refuted','{}','','x','x');""")
    c.commit()
    c.close()
    m = Memory(db)
    row = m.q("SELECT * FROM hypotheses")[0]
    assert row["statement"] == "old" and "classification" in row
    assert m.q("SELECT value FROM meta WHERE key='schema_version'")[0]["value"] == str(SCHEMA_VERSION)


def test_dossier_states_the_rebalance_rule_with_code_evidence():
    from pathlib import Path

    from evolutionx.data.datasets import protocol
    from evolutionx.research.context import build

    pol = json.loads(Path("evals/frozen/research_policy.json").read_text())
    d = build({"id": "v0", "version": 0, "source": "x", "params": {}}, PARENT, protocol(), pol, None)
    assert d["execution"]["engine_features"]["rebalance_band"]["present"]
    assert "rebalance_band" in d["execution"]["engine_excerpt"]["code"]
    assert d["git_commit"] and len(d["dossier_sha256"]) == 64 and "lessons_from_memory" not in d
    with pytest.raises(KeyError):
        _ = d["lessons_from_memory"]
