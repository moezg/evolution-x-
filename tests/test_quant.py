"""Quant discovery: method validation (false anomalies are not promoted; planted signals are recovered), event
engine, statutory election dates, FOMC parsing, registry versioning, multiple-testing math. Synthetic data only."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from evolutionx.quant import calendar as CAL
from evolutionx.quant import events as EV
from evolutionx.quant import stats as ST
from evolutionx.quant.eventstudy import hourly_metrics


def synth_frame(seed: int, plant: float = 0.0) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    days = [dt.date(2017, 8, 17) + dt.timedelta(days=i) for i in range(3363)]
    r = 0.03 * rng.standard_t(4, len(days)) / np.sqrt(2.0)
    dom = np.array([d.day for d in days])
    r = r + plant * (dom == 14)
    nxt = [d + dt.timedelta(days=1) for d in days]
    return {
        "date": np.array([d.isoformat() for d in days]),
        "ret": r,
        "dom": dom,
        "dow": np.array([d.weekday() for d in days]),
        "moy": np.array([d.month for d in days]),
        "tom": np.array([int(d.day <= 3 or n.month != d.month) for d, n in zip(days, nxt, strict=True)]),
    }


def decide(f: dict[str, np.ndarray]) -> list[str]:
    """The registered decision rule (BH q 0.10 on DISCOVERY, one-sided Holm 0.05 on CONFIRMATION)."""
    disc = CAL.scan(f, "F-DOM", "DISCOVERY", True)
    b = ST.bh({f"{r['label']}:{r['metric']}": r["p"] for r in disc["rows"]}, 0.10)
    surv = [r for r in disc["rows"] if b[f"{r['label']}:{r['metric']}"]["reject"]]
    conf = {f"{r['label']}:{r['metric']}": r for r in CAL.scan(f, "F-DOM", "CONFIRMATION", True)["rows"]}
    one = {
        f"{r['label']}:{r['metric']}": conf[f"{r['label']}:{r['metric']}"]["p_up" if r["effect"] > 0 else "p_down"]
        for r in surv
    }
    h = ST.holm(one, 0.05)
    return [
        k
        for k in one
        if h[k]["reject"]
        and np.sign(conf[k]["effect"]) == np.sign(next(r["effect"] for r in surv if f"{r['label']}:{r['metric']}" == k))
    ]


@pytest.fixture(autouse=True)
def fast_rotations(monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(CAL, "N_ROT", 199)


def test_false_synthetic_anomalies_are_not_systematically_promoted():
    promoted = [decide(synth_frame(seed)) for seed in range(20)]
    runs_with_any = sum(bool(p) for p in promoted)
    assert runs_with_any <= 2, promoted  # 124 tests per run; the two-stage rule keeps false 'supported' rare


def test_planted_day14_effect_is_recovered_with_adequate_power():
    hits = sum("14:mean_ret_wd_adj" in decide(synth_frame(100 + s, plant=0.02)) for s in range(10))
    assert hits >= 8


def test_event_engine_detects_planted_post_event_volatility_and_not_noise():
    rng = np.random.default_rng(0)
    n = 24 * 400
    t = np.arange(n, dtype=np.int64) * 3_600_000
    lr = rng.normal(0, 0.005, n)
    events = np.arange(30 * 24 + 14, n - 24 * 8, 24 * 7)[:40]
    for k in events:
        lr[k : k + 4] *= 4.0
    close = 100 * np.exp(np.cumsum(lr))
    ev = np.array([hourly_metrics(t, close, int(t[k]))["absret_0_4h"] for k in events])
    pool_idx = [k + 24 * 3 for k in events] + [k + 24 * 2 for k in events] + [k - 24 * 2 for k in events]
    pl = np.array([hourly_metrics(t, close, int(t[k]))["absret_0_4h"] for k in pool_idx])
    assert ST.placebo_test(ev, pl)["p"] < 0.01
    noise = np.array([hourly_metrics(t, close, int(t[k + 24]))["absret_0_4h"] for k in events])
    assert ST.placebo_test(noise, pl)["p"] > 0.01


def test_hourly_metrics_refuse_gaps():
    t = np.r_[np.arange(100), np.arange(101, 400)].astype(np.int64) * 3_600_000
    close = np.ones(len(t))
    assert hourly_metrics(t, close, int(t[60])) == {}


def test_statutory_election_days():
    assert [EV.election_day(y).isoformat() for y in (2018, 2020, 2022, 2024, 2026)] == [
        "2018-11-06",
        "2020-11-03",
        "2022-11-08",
        "2024-11-05",
        "2026-11-03",
    ]
    assert EV.election_day(2016).isoformat() == "2016-11-08" and EV.election_day(2010).isoformat() == "2010-11-02"


def test_fomc_parsers():
    cur = '<h4>2024 FOMC Meetings</h4><div class="fomc-meeting__month x"><strong>Apr/May</strong></div><div class="fomc-meeting__date x">30-1</div><div class="fomc-meeting__month x"><strong>June</strong></div><div class="fomc-meeting__date x">11-12*</div>'
    rows = EV.parse_current(cur)
    assert [(d.isoformat(), f["sep"]) for d, f in rows] == [("2024-05-01", False), ("2024-06-12", True)]
    hist = "<h5>March 15 (unscheduled) Meeting - 2020</h5><h5>March 17-18 (cancelled) Meeting - 2020</h5><h5>April 28-29 Meeting - 2020</h5>"
    rows = EV.parse_historical(hist, 2020)
    assert [(d.isoformat(), f["unscheduled"], f["cancelled"]) for d, f in rows] == [
        ("2020-03-15", True, False),
        ("2020-03-18", False, True),
        ("2020-04-29", False, False),
    ]


def test_registry_versions_and_preserves_enrichments(tmp_path):
    reg = EV.Registry(tmp_path / "r.jsonl")
    base = {
        "event_id": "e1",
        "category": "c",
        "subcategory": "s",
        "event_time_utc": "2020-01-01T00:00:00+00:00",
        "attributes": {"a": 1},
    }
    assert reg.register(base, "x") == "registered"
    assert reg.register(base, "x") == "unchanged"
    assert reg.register({**base, "attributes": {"b": 2}}, "x") == "new_version"  # enrichment merges, never drops
    cur = reg.current()[0]
    assert cur["version"] == 2 and cur["supersedes"] == 1 and cur["attributes"] == {"a": 1, "b": 2}
    assert reg.register(base, "x") == "unchanged"  # a builder re-run does not revert enrichments
    assert reg.j.verify()["ok"]


def test_multiple_testing_math():
    p = {"a": 0.001, "b": 0.01, "c": 0.03, "d": 0.5}
    b = ST.bh(p, 0.10)
    assert [b[k]["reject"] for k in "abcd"] == [True, True, True, False]
    h = ST.holm(p, 0.05)
    assert [h[k]["reject"] for k in "abcd"] == [True, True, False, False]
    assert h["b"]["p_adj"] == pytest.approx(0.03)


def test_rotation_test_preserves_dependence_and_is_calibrated():
    rng = np.random.default_rng(1)
    x = rng.normal(size=2000)
    lab = np.arange(2000) % 7

    def stat(v, lab):  # noqa: ANN001, ANN202
        return float(v[lab == 3].mean() - v[lab != 3].mean())

    ps = [ST.rotation_test(rng.normal(size=2000), lab, stat, n=199, seed=s, label_period=7)[1] for s in range(40)]
    assert 0.0 < np.mean(np.array(ps) < 0.05) <= 0.15
    x[lab == 3] += 0.3
    assert ST.rotation_test(x, lab, stat, n=199, label_period=7)[1] < 0.01
