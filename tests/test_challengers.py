"""Challenger evaluation (challenger_policy_v1/v2): pairing requires the same origin, target AND information cutoff;
the frozen futility rule retires a clearly worse challenger and issuance then skips it.
SYNTHETIC forecasts and outcomes only (tmp ledger); nothing here touches the production ledger."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolutionx.forecast import challengers as CH
from evolutionx.forecast.ledger import ForecastLedger

REPO = Path(__file__).resolve().parents[1]
DAY = 86_400_000
H = 3_600_000


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "evals").symlink_to(REPO / "evals")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _rec(fid, model, origin, as_of, value):
    return {"id": fid, "domain": "btc_perp", "target": "move3_24", "model": model, "model_version": "v", "origin_ms": origin,
            "window_end_ms": origin + 24 * H, "as_of_ms": as_of, "inputs": {}, "scored_value": value}  # fmt: skip


def test_pairs_need_the_same_information_cutoff(ws):
    led = ForecastLedger(ws / "l.jsonl")
    o = 10 * DAY
    led.issue(_rec("c1", "M1_logistic", o, o - 24 * H, 0.2), now_ms=o - H)
    led.issue(_rec("x1", "CH:f", o, o - 48 * H, 0.1), now_ms=o - H)  # different cutoff
    o2 = 11 * DAY
    led.issue(_rec("c2", "M1_logistic", o2, o2 - 24 * H, 0.2), now_ms=o2 - H)
    led.issue(_rec("x2", "CH:f", o2, o2 - 24 * H, 0.1), now_ms=o2 - H)
    for f in ("c1", "x1", "c2", "x2"):
        led.resolve(f, 1.0, {}, now_ms=13 * DAY)
    p = CH.paired(led)
    assert len(p[("CH:f", "move3_24")]) == 1 and len(CH.EXCLUDED) == 1


def test_futility_rule_retires_a_clearly_worse_challenger(ws, monkeypatch):
    led = ForecastLedger(ws / "l.jsonl")
    for i in range(70):  # challenger always predicts 0.9, champion 0.1, outcome 0 -> challenger much worse
        o = (20 + i) * DAY
        led.issue(_rec(f"c{i}", "M1_logistic", o, o - 24 * H, 0.1), now_ms=o - H)
        led.issue(_rec(f"x{i}", "CH:f", o, o - 24 * H, 0.9), now_ms=o - H)
        led.resolve(f"c{i}", 0.0, {}, now_ms=o + 25 * H)
        led.resolve(f"x{i}", 0.0, {}, now_ms=o + 25 * H)
    r = CH.review(led)
    assert r["reviews"]["CH:f:move3_24"]["action"].startswith("RETIRED")
    assert CH.retired("CH:f", "move3_24") and not CH.retired("CH:f", "rv_24")


def test_rv_loss_is_plain_squared_error_on_log_scale_targets():
    """Regression: rv targets are log values (can be negative); a second log made losses explode (11-07: ~750)."""
    from evolutionx.forecast import audit as A

    assert CH._loss("rv_24", 0.786, -0.5868) == pytest.approx((0.786 + 0.5868) ** 2)
    assert A._loss("rv_24", 0.786, -0.5868) == pytest.approx((0.786 + 0.5868) ** 2)
    assert CH._loss("move3_24", 0.2, 1.0) == pytest.approx(0.64)
