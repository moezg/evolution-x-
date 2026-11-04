"""Forecasting engine: point-in-time integrity, outcomes, ledger, abstention, scoring, evolution guards,
prospective issue/resolve cycle. Synthetic bars only (no network, no historical evaluation data)."""

from __future__ import annotations

import datetime as dt
import json
import math

import numpy as np
import pytest

from evolutionx.forecast import backtest as B
from evolutionx.forecast import evolve as E
from evolutionx.forecast import prospective as P
from evolutionx.forecast import scoring as S
from evolutionx.forecast.data import HOUR, Bars
from evolutionx.forecast.domain import DAY, FEATURES, BTCDomain, Target
from evolutionx.forecast.ledger import ForecastLedger, LedgerError
from evolutionx.research.memory import Memory

T0 = int(dt.datetime(2022, 1, 1, tzinfo=dt.UTC).timestamp() * 1000)


def synth_bars(days: int = 460, seed: int = 0, start: int = T0) -> Bars:
    rng = np.random.default_rng(seed)
    n = days * 24
    vol = 0.006 * np.exp(np.cumsum(rng.normal(0, 0.02, n)) * 0.2)
    r = rng.normal(0, vol)
    close = 30_000 * np.exp(np.cumsum(r))
    t = start + np.arange(n, dtype=np.int64) * HOUR
    return Bars(t, close, close * 1.002, close * 0.998, rng.uniform(100, 200, n), np.zeros(n, dtype=int))


# --------------------------------------------------------------------------- point in time
def test_features_never_read_bars_after_as_of():
    b = synth_bars()
    dom = BTCDomain(b)
    o = T0 + 400 * DAY
    f1 = dom.features(o)
    cut = int(np.searchsorted(b.open_time, o - dom.lag_ms))
    c2 = b.close.copy()
    c2[cut - 0 :] *= 3.0  # corrupt everything from the first bar not complete before o - lag
    b2 = Bars(b.open_time, c2, c2 * 1.002, c2 * 0.998, b.volume, b.source)
    f2 = BTCDomain(b2).features(o)
    assert all((f1[k] == f2[k]) or (math.isnan(f1[k]) and math.isnan(f2[k])) for k in FEATURES)


def test_outcomes_match_definitions():
    b = synth_bars(40)
    dom = BTCDomain(b)
    o = T0 + 20 * DAY
    k0 = int((o - T0) // HOUR) - 1
    lr = math.log(b.close[k0 + 24] / b.close[k0])
    assert dom.outcome(Target("up_24", "binary", 24, None, True), o) == float(lr > 0)
    assert dom.outcome(Target("move3_24", "binary", 24, 0.03), o) == float(abs(lr) >= 0.03)
    rv = math.log(100 * math.sqrt(sum(math.log(b.close[k] / b.close[k - 1]) ** 2 for k in range(k0 + 1, k0 + 25))))
    assert dom.outcome(Target("rv_24", "rv", 24), o) == pytest.approx(rv, rel=1e-9)
    assert dom.outcome(Target("up_24", "binary", 24, None, True), T0 + 40 * DAY) is None  # beyond data


def test_training_never_uses_unobservable_labels(monkeypatch):
    seen: list[tuple[int, int]] = []
    real_make = B.make

    def spy(name: str, **kw):  # noqa: ANN202
        m = real_make(name, **kw)
        orig = m.fit

        def fit(X, y, target):  # noqa: ANN001, ANN202
            seen.append((len(y), int(np.sum(np.isfinite(y)))))
            return orig(X, y, target)

        m.fit = fit
        return m

    monkeypatch.setattr(B, "make", spy)
    b = synth_bars(460)
    dom = BTCDomain(b)
    tab = B.build_table(dom, "2022-02-01", "2023-04-01", with_sim=False)
    t = Target("move3_24", "binary", 24, 0.03)
    res = B.run_target((t, tab, dom.lag_ms, ("B0_climatology", "M1_logistic")))
    o = tab["origins"]
    avail = o + t.horizon_h * HOUR + dom.lag_ms
    # the number of finite labels used at each refit can never exceed those observable at that origin
    max_allowed = max(int(np.sum((avail <= oi) & np.isfinite(tab["y"][t.name]))) for oi in o)
    assert seen and max(n for n, _ in seen) <= max_allowed
    assert res["reason"]["M1_logistic"][0] == "insufficient_training"


def test_abstained_forecasts_are_scored_as_climatology():
    b = synth_bars(460)
    dom = BTCDomain(b)
    tab = B.build_table(dom, "2022-02-01", "2023-04-01", with_sim=False)
    t = Target("move3_24", "binary", 24, 0.03)
    res = B.run_target((t, tab, dom.lag_ms, ("B0_climatology", "M1_logistic")))
    for i, r in enumerate(res["reason"]["M1_logistic"]):
        if r is not None:
            a, b0 = res["scored"]["M1_logistic"][i], res["scored"]["B0_climatology"][i]
            assert (a == b0) or (math.isnan(a) and math.isnan(b0))


def test_backtest_is_deterministic():
    b = synth_bars(420, seed=3)
    dom = BTCDomain(b)
    tab = B.build_table(dom, "2022-02-01", "2023-02-01", with_sim=False)
    t = Target("rv_24", "rv", 24)
    r1 = B.run_target((t, tab, dom.lag_ms, ("B0_climatology", "B1_ewma_gauss", "M1_logistic", "M2_gbm")))
    r2 = B.run_target((t, tab, dom.lag_ms, ("B0_climatology", "B1_ewma_gauss", "M1_logistic", "M2_gbm")))
    for m in r1["scored"]:
        assert np.array_equal(r1["scored"][m], r2["scored"][m], equal_nan=True)


# --------------------------------------------------------------------------- scoring
def test_scores_and_holm():
    p, y = np.array([0.9, 0.1, 0.5]), np.array([1.0, 0.0, 1.0])
    assert S.brier(p, y).mean() == pytest.approx((0.01 + 0.01 + 0.25) / 3)
    assert S.logloss(np.array([0.5]), np.array([1.0]))[0] == pytest.approx(math.log(2))
    rel = S.reliability(np.array([0.05, 0.05, 0.95]), np.array([0.0, 1.0, 1.0]))
    assert sum(r["n"] for r in rel["bins"]) == 3
    h = S.holm({"a": 0.001, "b": 0.02, "c": 0.04})
    assert h["a"]["reject_null"] and h["b"]["reject_null"] is True and h["c"]["reject_null"] is True
    h2 = S.holm({"a": 0.001, "b": 0.03, "c": 0.04})
    assert h2["a"]["reject_null"] and not h2["b"]["reject_null"] and not h2["c"]["reject_null"]
    d = np.r_[np.full(50, -0.01), np.full(50, 0.0)]
    x, z = S.block_bootstrap_mean(d), S.block_bootstrap_mean(d)
    assert x == z and x["hi"] <= 0.0


# --------------------------------------------------------------------------- ledger
def _rec(origin: int, rid: str = "f1") -> dict:
    return {
        "id": rid,
        "domain": "btc_perp",
        "target": "up_24",
        "model": "B0",
        "model_version": "v",
        "origin_ms": origin,
        "window_end_ms": origin + 24 * HOUR,
        "as_of_ms": origin - 24 * HOUR,
        "inputs": {},
    }


def test_ledger_is_prospective_append_only_and_tamper_evident(tmp_path):
    led = ForecastLedger(tmp_path / "l.jsonl")
    o = T0 + 10 * DAY
    led.issue(_rec(o), now_ms=o - HOUR)
    with pytest.raises(LedgerError):
        led.issue(_rec(o), now_ms=o - HOUR)  # duplicate
    with pytest.raises(LedgerError):
        led.issue(_rec(o, "late"), now_ms=o)  # window already started
    with pytest.raises(LedgerError):
        led.resolve("f1", 1.0, {}, now_ms=o + HOUR)  # window not over
    led.resolve("f1", 1.0, {}, now_ms=o + 25 * HOUR)
    with pytest.raises(LedgerError):
        led.resolve("f1", 0.0, {}, now_ms=o + 26 * HOUR)  # resolved once only
    assert led.verify()["ok"] and not hasattr(led, "update") and not hasattr(led, "delete")
    lines = (tmp_path / "l.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    first["data"]["origin_ms"] += 1
    lines[0] = json.dumps(first, sort_keys=True)
    (tmp_path / "l.jsonl").write_text("\n".join(lines) + "\n")
    assert not ForecastLedger(tmp_path / "l.jsonl").verify()["ok"]


def test_prospective_issue_resolve_score_cycle(tmp_path, monkeypatch):
    b_all = synth_bars(460, seed=5)
    cut = 450 * 24
    first = Bars(*(getattr(b_all, f)[:cut] for f in ("open_time", "close", "high", "low", "volume", "source")))
    monkeypatch.setattr(P, "OUT", tmp_path)  # no backtest report -> no simulator, no trailing-skill rule
    monkeypatch.setattr(P, "load_bars", lambda: first)
    monkeypatch.setattr(P, "FRESH", tmp_path)
    monkeypatch.setattr(P, "SNAPSHOTS", tmp_path / "snapshots")  # never write into artifacts/
    led = ForecastLedger(tmp_path / "ledger.jsonl")
    end = int(first.open_time[-1]) + HOUR
    now = dt.datetime.fromtimestamp((end + 2 * HOUR) / 1000, dt.UTC)
    r = P.issue(now=now, fetch=False, ledger=led)
    assert len(r["forecasts"]) == 8 * 4
    for e in led.forecasts().values():
        d = e["data"]
        assert d["issued_ms"] < d["origin_ms"] and d["as_of_ms"] <= d["issued_ms"]
        if d["kind"] == "binary":
            assert 0 < d["scored_value"] < 1
    monkeypatch.setattr(P, "load_bars", lambda: b_all)
    later = dt.datetime.fromtimestamp((int(b_all.open_time[-1]) + 2 * HOUR) / 1000, dt.UTC)
    res = P.resolve(now=later, fetch=False, ledger=led)
    assert res["resolved"] == 32 and res["pending"] == 0
    sc = P.score(ledger=led)
    assert sc["resolved"] == 32 and sc["verify"]["ok"]
    assert all(not v["promotion_evidence_sufficient"] for v in sc["scores"].values())


# --------------------------------------------------------------------------- evolution guards
def test_candidates_cannot_leave_the_frozen_space():
    for bad in (
        {"model": "logistic", "features": ["lrv_24"], "lag_h": 0},
        {"model": "transformer", "features": ["lrv_24"]},
        {"model": "logistic", "features": ["future_return"]},
        {"model": "logistic", "features": []},
    ):
        with pytest.raises(E.CandidateRejected):
            E.validate(bad)


def test_acceptance_threshold_tightens_with_trials_and_never_replaces_champion(tmp_path, monkeypatch):
    mem = Memory(tmp_path / "r.db")
    t = Target("move3_24", "binary", 24, 0.03)
    monkeypatch.setattr(E, "run_target", lambda args: {})
    calls = iter([{"mean": -0.01, "p_better": 0.03}, {"mean": -0.001}] * 3)
    monkeypatch.setattr(E, "compare", lambda res, a, b, p: next(calls))
    specs = [{"model": "logistic", "features": ["lrv_24"], "l2": float(k)} for k in (1, 2, 3)]
    out = [E.evaluate(t, s, {"sim": None}, 24 * HOUR, mem) for s in specs]
    assert out[0]["status"].startswith("challenger") and out[0]["p_threshold"] == 0.05
    assert out[1]["status"] == "rejected" and out[1]["p_threshold"] == pytest.approx(0.025)
    assert all(not o["replaces_champion"] for o in out)
    with pytest.raises(E.CandidateRejected):
        E.evaluate(t, specs[0], {"sim": None}, 24 * HOUR, mem)


# --------------------------------------------------------------------------- stabilization regressions (v0.6 stage A)
def test_rule4_uses_only_resolved_ledger_forecasts(tmp_path):
    led = ForecastLedger(tmp_path / "l.jsonl")
    base = T0 + 10 * DAY
    for i in range(70):
        o = base + i * DAY
        rec = {**_rec(o, f"f{i}"), "target": "move3_24", "model": "M1_logistic", "value": 0.9, "fallback_B0": 0.2}
        led.issue(rec, now_ms=o - HOUR)
        if i < 65:  # 5 forecasts stay unresolved and must not count
            led.resolve(f"f{i}", 0.0, {}, now_ms=o + 25 * HOUR)
    ts = P._trailing_skill_from_ledger(led, "move3_24", "M1_logistic")
    assert ts is not None and ts < 0  # always-wrong 0.9 vs B0 0.2 on outcome 0
    assert P._trailing_skill_from_ledger(led, "move3_24", "M2_gbm") is None  # no resolved forecasts -> proxy path


def test_api_anchors_to_repo_root_from_any_cwd(tmp_path, monkeypatch):
    from evolutionx.api import paths

    monkeypatch.chdir(tmp_path)
    info = paths.ensure_repo_cwd()
    assert info["changed"] and (paths.Path.cwd() / "evals" / "frozen").is_dir()


def test_evolution_endpoint_serves_the_artifact_or_reports_404(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from evolutionx.api import forecast_routes
    from evolutionx.api.app import app

    c = TestClient(app)
    monkeypatch.setattr(forecast_routes, "OUT", tmp_path)
    r = c.get("/api/forecast/evolution")
    assert r.status_code == 404 and "not produced yet" in r.json()["detail"]
    (tmp_path / "evolution_v1.json").write_text('{"results": []}')
    assert c.get("/api/forecast/evolution").json() == {"results": []}
