"""P5 calibration study: the pure decision function equals the registered calendar.run() rule; generators are
deterministic, calendar-free under the null, and produce volatility clustering. SYNTHETIC data only."""

from __future__ import annotations

import numpy as np
import pytest

from evolutionx.quant import calendar as CAL
from evolutionx.quant import calibration as C


@pytest.fixture(autouse=True)
def fast(monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(CAL, "N_ROT", 199)


def test_decide_matches_the_registered_run(monkeypatch):
    r, _ = C.generate("garch_t5", 7)
    r = r + 0.035 * (C.frame(r)["dom"] == 14)  # planted, so both paths have something to agree on
    f = C.frame(r)
    monkeypatch.setattr(CAL, "daily_frame", lambda: f)
    monkeypatch.setattr(CAL, "macro_exclusion_mask", lambda f: np.zeros(len(f["ret"]), bool))
    monkeypatch.setattr(CAL, "day14_report", lambda f, rows: {})

    class Reg:
        def record(self, rec):  # noqa: ANN001, ANN201
            return "x"

    ref = CAL.run("t", reg=Reg())  # type: ignore[arg-type]
    supported = sorted(h for fam in ref["families"].values() for h in fam["supported"])
    survivors = sorted(h for fam in ref["families"].values() for h in fam["discovery_survivors_bh"])
    d = C.decide(f)
    assert sorted(d["supported"]) == supported and sorted(d["bh_survivors"]) == survivors
    assert "F-DOM:14:mean_ret_wd_adj" in supported


def test_generators_are_deterministic_and_cluster_volatility():
    a, _ = C.generate("garch_t5", 1)
    b, _ = C.generate("garch_t5", 1)
    assert np.array_equal(a, b) and len(a) == C.N_DAYS
    x = np.abs(a)
    ac = np.corrcoef(x[:-1], x[1:])[0, 1]
    i, _ = C.generate("iid_t4", 1)
    ac_iid = np.corrcoef(np.abs(i)[:-1], np.abs(i)[1:])[0, 1]
    assert ac > 0.1 and abs(ac_iid) < 0.06  # |r| autocorrelation: clustering only in the GARCH generator
    assert 0.025 < a.std() < 0.05


def test_wilson_interval():
    lo, hi = C.wilson(0, 300)
    assert lo == 0 and 0.01 < hi < 0.015
    lo, hi = C.wilson(15, 300)
    assert lo < 0.05 < hi


def test_quarantine_rule_is_the_frozen_one():
    def s(k, n=300):
        return {
            "per_metric": {m: {"wilson95": list(C.wilson(k if m == "left_tail_rate" else 0, n))} for m in CAL.METRICS}
        }

    assert C.quarantine({"g": s(1)})["left_tail_rate"]["quarantined"] is False
    q = C.quarantine({"g": s(12)})
    assert q["left_tail_rate"]["quarantined"] and not q["mean_ret"]["quarantined"]
