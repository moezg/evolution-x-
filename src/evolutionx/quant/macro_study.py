"""F-MACRO (quant_protocol_v1 amendment 3): BTC around CPI and Employment Situation FIRST releases.

Same engine as F-FOMC: hourly spot bars, matched placebo resampling, BH(0.10) on DISCOVERY, one one-sided Holm(0.05)
test per survivor on CONFIRMATION. The window starts with the hourly bar containing the 08:30 ET release (08:00 ET),
so it includes 30 minutes before the release. Surprise effects are untestable (no consensus data).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np

from .calendar import protocol, protocol_sha
from .data import load_btc
from .events import Registry
from .eventstudy import ET, _in, _sha, hourly_metrics
from .stats import TestRegistry, bh, bootstrap_ci, holm, placebo_test

SUBS = ("cpi", "nfp")


def _bar_open(e: dict[str, Any]) -> int:
    t = dt.datetime.fromisoformat(e["event_time_utc"]).astimezone(ET)
    return int(t.replace(minute=0).astimezone(dt.UTC).timestamp() * 1000)  # 08:00 ET bar contains 08:30


def macro_study(run_id: str, reg: TestRegistry | None = None) -> dict[str, Any]:
    reg = reg or TestRegistry()
    fam = protocol()["amendment_3"]["new_family"]["F-MACRO"]
    metrics = fam["metrics_per_subcategory"]
    s = load_btc("1h")
    data_sha = _sha(s.t, s.close)
    R = Registry()
    macro = R.current("macro_release")
    excl = {
        (dt.date.fromisoformat(e["event_time_utc"][:10]) + dt.timedelta(days=k)).isoformat()
        for e in macro
        for k in (-1, 0, 1)
    }
    excl |= {
        (dt.date.fromisoformat(e["attributes"]["final_meeting_day"]) + dt.timedelta(days=k)).isoformat()
        for e in R.current("fomc")
        for k in range(-2, 3)
    }
    events: dict[str, list[dict[str, Any]]] = {}
    pools: dict[str, list[dict[str, Any]]] = {}
    for sub in SUBS:
        ev = [e for e in macro if e["subcategory"] == sub and e["attributes"]["kind"] == "first_release"]
        rows = []
        for e in ev:
            m = hourly_metrics(s.t, s.close, _bar_open(e))
            if m:
                rows.append({"event_id": e["event_id"], "day": e["event_time_utc"][:10], **m})
        events[sub] = rows
        wds = {dt.date.fromisoformat(r["day"]).weekday() for r in rows}
        pool = []
        d = dt.date(2017, 9, 1)
        while d <= dt.date(2026, 10, 24):
            if d.weekday() in wds and d.isoformat() not in excl:
                t0 = int(dt.datetime(d.year, d.month, d.day, 8, 0, tzinfo=ET).astimezone(dt.UTC).timestamp() * 1000)
                m = hourly_metrics(s.t, s.close, t0)
                if m:
                    pool.append({"day": d.isoformat(), **m})
            d += dt.timedelta(days=1)
        pools[sub] = pool
    res: dict[str, dict[str, Any]] = {"DISCOVERY": {}, "CONFIRMATION": {}}
    for per in res:
        for sub in SUBS:
            E = [r for r in events[sub] if _in(r["day"], per)]
            P = [r for r in pools[sub] if _in(r["day"], per)]
            for met in metrics:
                ev_v = np.array([r[met] for r in E])
                pl_v = np.array([r[met] for r in P])
                pt = placebo_test(ev_v, pl_v)
                lo, hi = bootstrap_ci(ev_v) if len(ev_v) else (float("nan"), float("nan"))
                c0 = pt.get("placebo_median_of_means", float("nan"))
                res[per][f"{sub}:{met}"] = {**pt, "event_mean_ci": [lo, hi], "effect_ci": [lo - c0, hi - c0], "n_events": len(E)}  # fmt: skip
    keys = [f"{sub}:{m}" for sub in SUBS for m in metrics]
    b = bh({k: res["DISCOVERY"][k]["p"] for k in keys}, 0.10)
    one = {}
    for k in keys:
        if b[k]["reject"]:
            c = res["CONFIRMATION"][k]
            one[k] = c["p_less"] if res["DISCOVERY"][k]["effect"] < 0 else c["p_greater"]
    h = holm(one, 0.05)
    status = {}
    for k in keys:
        if not b[k]["reject"]:
            status[k] = "rejected"
        else:
            c, d0 = res["CONFIRMATION"][k], res["DISCOVERY"][k]
            ok = h[k]["reject"] and np.sign(c["effect"]) == np.sign(d0["effect"]) and c["n"] >= 20
            status[k] = "supported" if ok else "inconclusive"
        d0 = res["DISCOVERY"][k]
        reg.record(
            {
                "family": "F-MACRO", "hypothesis": f"F-MACRO:{k}", "role": "I3",
                "method": "matched placebo resampling (2000) + BH(0.10) [amendment 3]", "period": "DISCOVERY",
                "n": d0["n"], "n_ref": d0.get("n_placebo_pool"), "effect": d0["effect"],
                "ci_lo": d0["effect_ci"][0], "ci_hi": d0["effect_ci"][1], "data_sha": data_sha, "p": d0["p"],
                "p_adj": b[k]["p_adj"], "adj_method": f"BH within F-MACRO ({len(keys)})", "status": status[k],
                "direction": int(np.sign(d0["effect"])), "protocol_sha": protocol_sha(), "run_id": run_id,
                "details": {"window": "08:00 ET bar (contains the 08:30 release)", "placebo": "same weekday set, 08:00 ET, non-release days"},
            }
        )  # fmt: skip
        if k in one:
            c = res["CONFIRMATION"][k]
            reg.record(
                {
                    "family": "F-MACRO", "hypothesis": f"F-MACRO:{k}", "role": "E2",
                    "method": "matched placebo one-sided + Holm(0.05) [amendment 3]", "period": "CONFIRMATION",
                    "n": c["n"], "n_ref": c.get("n_placebo_pool"), "effect": c["effect"],
                    "ci_lo": c["effect_ci"][0], "ci_hi": c["effect_ci"][1], "data_sha": data_sha, "p": one[k],
                    "p_adj": h[k]["p_adj"], "adj_method": f"Holm over {len(one)} survivors", "status": status[k],
                    "direction": int(np.sign(res["DISCOVERY"][k]["effect"])), "protocol_sha": protocol_sha(), "run_id": run_id,
                }
            )  # fmt: skip
    return {
        "run_id": run_id,
        "data_sha": data_sha,
        "n_events": {sub: {p: sum(_in(r["day"], p) for r in events[sub]) for p in res} for sub in SUBS},
        "n_placebo": {sub: {p: sum(_in(r["day"], p) for r in pools[sub]) for p in res} for sub in SUBS},
        "results": res,
        "bh": b,
        "confirmation_holm": h,
        "status": status,
        "label": "exploratory; surprise effects untestable (no consensus data)",
    }
