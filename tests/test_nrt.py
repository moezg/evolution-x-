"""Protocol v2 near-real-time challenger: deadline/cutoff guards, idempotent issuance, stale-input abstention and
the policy-v3 pairing exception. Uses the stored historical spot/perp data (no network: the API rows are injected)
and a temporary ledger; nothing touches the production ledger."""

from __future__ import annotations

import datetime as dt

import pytest

from evolutionx.forecast import challengers, nrt
from evolutionx.forecast.ledger import ForecastLedger

ORIGIN = int(dt.datetime(2026, 10, 20, tzinfo=dt.UTC).timestamp() * 1000)
H = 3_600_000


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(nrt, "SNAP", tmp_path / "snap")
    monkeypatch.setattr(challengers, "active", lambda m, t: True)
    monkeypatch.setattr(challengers, "retired", lambda m, t: False)
    return ForecastLedger(tmp_path / "l.jsonl")


def test_guards(env):
    with pytest.raises(ValueError, match="no backfill"):
        nrt.issue_nrt(dt.datetime.fromtimestamp(ORIGIN / 1000 + 60, dt.UTC), ORIGIN, env, recent=([], "x"))
    with pytest.raises(ValueError, match="cutoff"):
        nrt.issue_nrt(dt.datetime.fromtimestamp((ORIGIN - 3 * H) / 1000, dt.UTC), ORIGIN, env, recent=([], "x"))


def test_issue_is_idempotent_and_uses_the_2h_cutoff(env):
    now = dt.datetime.fromtimestamp((ORIGIN - 2 * H) / 1000 + 600, dt.UTC)
    r = nrt.issue_nrt(now, ORIGIN, env, recent=([], "x"))
    assert r["fresh"] and len([x for x in r["issued"] if "skipped" not in x]) == 2
    d = next(iter(env.forecasts().values()))["data"]
    assert d["as_of_ms"] == ORIGIN - 2 * H and d["model"] == nrt.MODEL and d["input_snapshot"]["sha256"]
    r2 = nrt.issue_nrt(now, ORIGIN, env, recent=([], "x"))
    assert all("skipped" in x for x in r2["issued"]) and len(env.entries()) == 2
    assert env.verify()["ok"]


def test_stale_spot_bars_abstain(env, monkeypatch):
    real = nrt.spot_bars

    def drop_last_day(rows):
        b = real(rows)
        keep = b.open_time < ORIGIN - 26 * H  # the last day before the cutoff is missing
        return type(b)(*(getattr(b, f)[keep] for f in ("open_time", "close", "high", "low", "volume", "source")))

    monkeypatch.setattr(nrt, "spot_bars", drop_last_day)
    now = dt.datetime.fromtimestamp((ORIGIN - 2 * H) / 1000 + 600, dt.UTC)
    r = nrt.issue_nrt(now, ORIGIN, env, recent=([], "x"))
    assert not r["fresh"] and all(x["abstained"] and x["reason"] == "stale_or_missing_data" for x in r["issued"])


def test_nrt_pairs_despite_a_different_cutoff():
    assert nrt.MODEL in challengers.DIFFERENT_CUTOFF_BY_DESIGN
