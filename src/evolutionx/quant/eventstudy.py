"""Universal Event Study Engine (I1/I2/H4/E2) - families F-FOMC, F-XEVENT, F-ELECT of quant_protocol_v1.

An event study needs: event times (from the Event Registry), a price series, windows in that series' units, and a
placebo pool of matched non-event times. It answers: what happens before (anticipation), right after and over
longer horizons; volatility and downside changes; regime differences. Events are the unit of replication.
Inference only when n >= min_n_inference (20); smaller families are DESCRIPTIVE with placebo percentiles.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from .calendar import protocol, protocol_sha
from .data import DAY, HOUR, load_btc, load_fred
from .events import Registry
from .stats import TestRegistry, bh, bootstrap_ci, holm, placebo_test

ET = ZoneInfo("America/New_York")


# ----------------------------------------------------------------------------- generic engine (hourly)
def hourly_metrics(t: np.ndarray, close: np.ndarray, t0: int) -> dict[str, float]:
    """Metrics around event time t0 (ms, on an hour boundary) from hourly bars (open time t, close = price at t+1h)."""
    k0 = int(np.searchsorted(t, t0))
    if k0 >= len(t) or t[k0] != t0 or k0 < 25 or k0 + 168 >= len(t):
        return {}
    seg = t[k0 - 25 : k0 + 168]
    if np.any(np.diff(seg) != HOUR):
        return {}  # gaps are not filled
    p0 = close[k0 - 1]

    def r(h: int) -> float:
        return float(np.log(close[k0 + h - 1] / p0))

    lr = np.diff(np.log(close[k0 - 1 : k0 + 4]))
    return {
        "ret_0_1h": r(1),
        "ret_0_4h": r(4),
        "absret_0_4h": abs(r(4)),
        "rv_0_4h": float(np.sqrt(np.sum(lr**2))),
        "ret_0_24h": r(24),
        "ret_0_7d": r(168),
        "pre_ret_24h": float(np.log(p0 / close[k0 - 25])),
        "pre_absret_24h": abs(float(np.log(p0 / close[k0 - 25]))),
        "pre_rv_30d": float(np.std(np.diff(np.log(close[max(0, k0 - 721) : k0])))),
    }


def _in(day: str, period: str) -> bool:
    a, b = protocol()["periods"][period]
    return a <= day <= b


def fomc_study(run_id: str, reg: TestRegistry | None = None) -> dict[str, Any]:
    reg = reg or TestRegistry()
    s = load_btc("1h")
    data_sha = _sha(s.t, s.close)
    ev = [
        e for e in Registry().current("fomc") if e["subcategory"] == "scheduled" and not e["attributes"].get("future")
    ]
    ev_days = {e["attributes"]["final_meeting_day"] for e in Registry().current("fomc")}
    near = {(dt.date.fromisoformat(d) + dt.timedelta(days=k)).isoformat() for d in ev_days for k in range(-2, 3)}
    rows = []
    for e in ev:
        t0 = int(dt.datetime.fromisoformat(e["event_time_utc"]).timestamp() * 1000)
        m = hourly_metrics(s.t, s.close, t0)
        if m:
            rows.append(
                {
                    "event_id": e["event_id"],
                    "day": e["attributes"]["final_meeting_day"],
                    "action": e["attributes"].get("action"),
                    "sep": e["attributes"].get("sep"),
                    **m,
                }
            )
    # placebo: 14:00 ET on non-FOMC days (+-2 days excluded) with the same weekday as FOMC statements (Wed)
    pool = []
    d = dt.date(2017, 9, 1)
    while d <= dt.date(2026, 10, 24):
        if d.weekday() == 2 and d.isoformat() not in near:
            t0 = int(dt.datetime(d.year, d.month, d.day, 14, 0, tzinfo=ET).astimezone(dt.UTC).timestamp() * 1000)
            m = hourly_metrics(s.t, s.close, t0)
            if m:
                pool.append({"day": d.isoformat(), **m})
        d += dt.timedelta(days=1)
    fam = protocol()["families"]["F-FOMC"]
    metrics = fam["metrics"]
    out: dict[str, Any] = {"events": rows, "placebo_pool": len(pool), "periods": {}}
    res: dict[str, dict[str, Any]] = {}
    for per in ("DISCOVERY", "CONFIRMATION"):
        E = [r for r in rows if _in(r["day"], per)]
        P = [r for r in pool if _in(r["day"], per)]
        res[per] = {}
        for met in metrics:
            ev_v = np.array([r[met] for r in E])
            pl_v = np.array([r[met] for r in P])
            pt = placebo_test(ev_v, pl_v)
            lo, hi = bootstrap_ci(ev_v)
            c0 = pt.get("placebo_median_of_means", float("nan"))
            res[per][met] = {
                **pt,
                "event_mean_ci": [lo, hi],
                "effect_ci": [lo - c0, hi - c0],  # event-mean bootstrap CI shifted by the placebo centre
                "placebo_mean": float(pl_v.mean()) if len(pl_v) else None,
            }
        out["periods"][per] = {"n_events": len(E), "n_placebo": len(P)}
    b = bh({m: res["DISCOVERY"][m]["p"] for m in metrics}, 0.10)
    surv = [m for m in metrics if b[m]["reject"]]
    one = {}
    for m in surv:
        d0 = res["DISCOVERY"][m]["effect"]
        ev_c = np.array([r[m] for r in rows if _in(r["day"], "CONFIRMATION")])
        pl_c = np.array([r[m] for r in pool if _in(r["day"], "CONFIRMATION")])
        pt = placebo_test(ev_c, pl_c)
        one[m] = pt["p_less"] if d0 < 0 else pt["p_greater"]  # one-sided in the discovery direction, never 0
    h = holm(one, 0.05)
    status = {}
    for m in metrics:
        if not b[m]["reject"]:
            status[m] = "rejected"
        else:
            c = res["CONFIRMATION"][m]
            ok = h[m]["reject"] and np.sign(c["effect"]) == np.sign(res["DISCOVERY"][m]["effect"]) and c["n"] >= 20
            status[m] = "supported" if ok else "inconclusive"
        reg.record(
            {
                "family": "F-FOMC",
                "hypothesis": f"F-FOMC:{m}",
                "role": "I2",
                "method": "matched placebo resampling (2000) + BH(0.10)",
                "period": "DISCOVERY",
                "n": res["DISCOVERY"][m]["n"],
                "n_ref": res["DISCOVERY"][m].get("n_placebo_pool"),
                "effect": res["DISCOVERY"][m]["effect"],
                "ci_lo": res["DISCOVERY"][m]["effect_ci"][0],
                "ci_hi": res["DISCOVERY"][m]["effect_ci"][1],
                "data_sha": data_sha,
                "p": res["DISCOVERY"][m]["p"],
                "p_adj": b[m]["p_adj"],
                "adj_method": f"BH within F-FOMC ({len(metrics)})",
                "status": status[m],
                "direction": int(np.sign(res["DISCOVERY"][m]["effect"])),
                "protocol_sha": protocol_sha(),
                "run_id": run_id,
                "details": {
                    "ci": "effect CI = event-mean bootstrap CI minus the placebo centre (placebo variability not included)"
                },
            }
        )
        if m in one:
            c = res["CONFIRMATION"][m]
            reg.record(
                {
                    "family": "F-FOMC",
                    "hypothesis": f"F-FOMC:{m}",
                    "role": "E2",
                    "method": "matched placebo one-sided + Holm(0.05)",
                    "period": "CONFIRMATION",
                    "n": c["n"],
                    "n_ref": c.get("n_placebo_pool"),
                    "effect": c["effect"],
                    "ci_lo": c["effect_ci"][0],
                    "ci_hi": c["effect_ci"][1],
                    "data_sha": data_sha,
                    "details": {"ci": "effect CI = event-mean bootstrap CI minus the placebo centre"},
                    "p": one[m],
                    "p_adj": h[m]["p_adj"],
                    "adj_method": f"Holm over {len(one)} survivors",
                    "status": status[m],
                    "direction": int(np.sign(res["DISCOVERY"][m]["effect"])),
                    "protocol_sha": protocol_sha(),
                    "run_id": run_id,
                }
            )
    out["results"] = res
    out["status"] = status
    out["xevent"] = xevent(rows, pool, run_id, reg, data_sha)
    return out


def _interaction(E: list[dict[str, Any]], key: str, metric: str, seed: int = 0) -> dict[str, Any]:
    g = np.array([bool(r[key]) for r in E])
    v = np.array([r[metric] for r in E])
    n1, n0 = int(g.sum()), int((~g).sum())
    diff = float(v[g].mean() - v[~g].mean()) if n1 and n0 else float("nan")
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(2000):
        pg = rng.permutation(g)
        null.append(v[pg].mean() - v[~pg].mean())
    p = (1 + np.sum(np.abs(null) >= abs(diff))) / 2001 if np.isfinite(diff) else float("nan")
    return {"n_true": n1, "n_false": n0, "diff": diff, "p": float(p)}


def xevent(
    rows: list[dict[str, Any]], pool: list[dict[str, Any]], run_id: str, reg: TestRegistry, data_sha: str | None = None
) -> dict[str, Any]:
    """F-XEVENT: FOMC x pre-event volatility regime; FOMC x policy action. Min 15 events per cell."""
    min_cell = protocol()["families"]["F-XEVENT"]["min_n_per_cell"]
    med = float(np.median([r["pre_rv_30d"] for r in pool if _in(r["day"], "DISCOVERY")]))
    out = {}
    for per in ("DISCOVERY", "CONFIRMATION"):
        E = [
            {**r, "high_vol": r["pre_rv_30d"] > med, "changed": r["action"] in ("hike", "cut")}
            for r in rows
            if _in(r["day"], per)
        ]
        out[per] = {}
        for key in ("high_vol", "changed"):
            if any(r["action"] is None for r in E) and key == "changed":
                E2 = [r for r in E if r["action"] is not None]
            else:
                E2 = E
            it = _interaction(E2, key, "absret_0_4h")
            testable = it["n_true"] >= min_cell and it["n_false"] >= min_cell
            it["status"] = "tested" if testable else f"not tested (cell n < {min_cell})"
            out[per][key] = it
            if testable:
                reg.record(
                    {
                        "family": "F-XEVENT",
                        "hypothesis": f"F-XEVENT:fomc_x_{key}:absret_0_4h",
                        "role": "H4",
                        "method": "label permutation (2000) of event attribute",
                        "period": per,
                        "n": it["n_true"] + it["n_false"],
                        "n_ref": None,
                        "effect": it["diff"],
                        "p": it["p"],
                        "adj_method": "none: 2 exploratory interaction tests, reported uncorrected",
                        "data_sha": data_sha,
                        "status": "exploratory",
                        "protocol_sha": protocol_sha(),
                        "run_id": run_id,
                        "details": {
                            "cells": {"true": it["n_true"], "false": it["n_false"]},
                            "split": "pre-event 30-day hourly vol vs placebo median (DISCOVERY)"
                            if key == "high_vol"
                            else "target change (hike/cut) vs hold, FRED DFEDTARU",
                        },
                    }
                )
    out["note"] = "expectation-based surprises (e.g. CPI above consensus) cannot be tested: no licensed consensus data"
    return out


# ----------------------------------------------------------------------------- elections (daily)
def daily_window_metrics(t: np.ndarray, v: np.ndarray, i0: int, diff_kind: str) -> dict[str, float]:
    """Windows in observations (trading days for FRED, calendar days for BTC). diff_kind: 'log' prices or 'level'."""

    def ch(a: int, b: int) -> float:
        if a < 0 or b >= len(v):
            return float("nan")
        return float(np.log(v[b] / v[a])) if diff_kind == "log" else float(v[b] - v[a])

    return {
        "pre_30": ch(i0 - 30, i0),
        "post_1": ch(i0, i0 + 1),
        "post_7": ch(i0, i0 + 7),
        "post_30": ch(i0, i0 + 30),
        "post_90": ch(i0, i0 + 90),
    }


def election_study(run_id: str, reg: TestRegistry | None = None) -> dict[str, Any]:
    reg = reg or TestRegistry()
    ev = Registry().current("us_election")
    min_n = protocol()["methods"]["min_n_inference"]
    btc = load_btc("1d")
    assets = {
        "BTC (spot daily, log return, calendar days)": (btc.t, btc.close, "log"),
        "DGS10 (10y yield change in pp, trading days)": (*_fred("DGS10"), "level"),
        "SP500 (log return, trading days)": (*_fred("SP500"), "log"),
    }
    out: dict[str, Any] = {
        "note": "elections are analysed per asset; conclusions are not transferred between asset classes",
        "assets": {},
    }
    for name, (t, v, kind) in assets.items():
        days = np.array([dt.datetime.fromtimestamp(x / 1000, dt.UTC).date() for x in t])
        day_ord = np.array([d.toordinal() for d in days])
        res: dict[str, Any] = {}
        for sub in ("midterm", "presidential"):
            rows = []
            for e in ev:
                if e["subcategory"] != sub:
                    continue
                d = dt.date.fromisoformat(e["event_time_utc"][:10])
                # reference = last observation at or before election day (markets were often closed on election
                # day; results arrive after the close), so the post windows start from pre-result information
                i0 = int(np.searchsorted(day_ord, d.toordinal(), side="right")) - 1
                if i0 < 0 or (d - days[i0]).days > 4:
                    continue
                m = daily_window_metrics(t, v, i0, kind)
                rows.append(
                    {
                        "event_id": e["event_id"],
                        "date": d.isoformat(),
                        "reference_date": days[i0].isoformat(),
                        **m,
                        "complete": bool(np.isfinite(m["post_90"])),
                        "pending": d.isoformat() >= protocol()["periods"]["CONFIRMATION"][1],
                    }
                )
            # placebo pool: Tuesdays in October-December of odd (non-election) years, same series
            pool_idx = [
                i for i, d in enumerate(days) if d.year % 2 == 1 and d.month in (10, 11, 12) and d.weekday() == 1
            ]
            pool = [daily_window_metrics(t, v, i, kind) for i in pool_idx]
            stats = {}
            for w in ("pre_30", "post_1", "post_7", "post_30", "post_90"):
                # pending (prospective) events are excluded from every window, including pre_30
                vals = np.array([r[w] for r in rows if np.isfinite(r[w]) and not r["pending"]])
                pv = np.array([p[w] for p in pool if np.isfinite(p[w])])
                pct = [float(np.mean(pv < x)) for x in vals] if len(pv) else []
                stats[w] = {
                    "n": len(vals),
                    "event_values": [float(x) for x in vals],
                    "placebo_n": len(pv),
                    "event_percentiles_in_placebo": pct,
                    "mean": float(vals.mean()) if len(vals) else None,
                    "placebo_mean": float(pv.mean()) if len(pv) else None,
                }
                if len(vals) >= min_n:
                    pt = placebo_test(vals, pv)
                    stats[w]["placebo_test"] = pt
                n_ok = len(vals)
                reg.record(
                    {
                        "family": "F-ELECT",
                        "hypothesis": f"F-ELECT:{name.split(' ')[0]}:{sub}:{w}",
                        "role": "I1",
                        "method": "descriptive (n < 20): placebo percentiles only"
                        if n_ok < min_n
                        else "matched placebo resampling",
                        "period": "ALL",
                        "n": n_ok,
                        "n_ref": len(pv),
                        "effect": (float(vals.mean() - pv.mean()) if n_ok and len(pv) else None),
                        "p": stats[w].get("placebo_test", {}).get("p"),
                        "status": "descriptive_only" if n_ok < min_n else "exploratory",
                        "protocol_sha": protocol_sha(),
                        "run_id": run_id,
                        "data_sha": _sha(t, v),
                    }
                )
            res[sub] = {
                "events": rows,
                "windows": stats,
                "n_events": sum(not r["pending"] for r in rows),
                "n_pending": sum(r["pending"] for r in rows),
                "inference": "descriptive only (n < 20)"
                if sum(not r["pending"] for r in rows) < min_n
                else "placebo test",
            }
        out["assets"][name] = res
    out["pending"] = [e["event_id"] for e in ev if e["event_time_utc"][:10] >= "2026-11-01"]
    out["pending_note"] = "the 2026 midterm (2026-11-03) has no post-event data yet; it is a prospective observation"
    return out


def _sha(*arrs: np.ndarray) -> str:
    import hashlib

    h = hashlib.sha256()
    for a in arrs:
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()[:16]


def _fred(sid: str) -> tuple[np.ndarray, np.ndarray]:
    s = load_fred(sid)
    return s.t, s.close


__all__ = ["DAY", "election_study", "fomc_study", "hourly_metrics"]
