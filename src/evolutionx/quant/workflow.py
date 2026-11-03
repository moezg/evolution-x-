"""Quantitative discovery workflow on the army orchestrator:
DATA -> PATTERN DETECTION -> HYPOTHESIS -> STATISTICAL TEST -> ADVERSARIAL REVIEW -> OUT-OF-SAMPLE -> MEMORY.

Seeded with `{"workflow": "quant"}`; every handler is deterministic (0 LLM calls). Results are written to the
statistical-testing registry (stat_tests), the army memory (hypotheses + edges) and artifacts/quant/<cycle>/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ..army.orchestrator import Ctx, new_task
from ..research.memory import now
from . import calendar as CAL
from . import cycles as CY
from . import events as EV
from . import eventstudy as ES
from . import forecast_link as FL
from .stats import TestRegistry

OUT = Path("artifacts/quant")


def _save(ctx: Ctx, name: str, obj: Any) -> str:
    d = OUT / ctx.cycle
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(obj, indent=1, default=float))
    (OUT / f"latest_{name}.json").write_text(
        json.dumps({"cycle": ctx.cycle, **(obj if isinstance(obj, dict) else {"data": obj})}, indent=1, default=float)
    )
    return str(d / f"{name}.json")


def _reg(ctx: Ctx) -> TestRegistry:
    return TestRegistry(ctx.store)


def q_events(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    r = EV.Registry()
    out = {
        "elections": EV.build_elections(r),
        "fomc": EV.build_fomc(r),
        "policy_actions": EV.attach_policy_actions(r),
        "verify": r.j.verify(),
    }
    out["counts"] = {c: len(r.current(c)) for c in ("us_election", "fomc")}
    _save(ctx, "events", {"events": r.current(), **out})
    return out


def q_calendar(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    r = CAL.run(ctx.cycle, reg=_reg(ctx))
    path = _save(ctx, "calendar", r)
    return {
        "artifact": path,
        **{f: {k: v[k] for k in ("tests", "discovery_survivors_bh", "supported")} for f, v in r["families"].items()},
        "day14": [{k: x[k] for k in ("metric", "n", "effect", "p", "p_bh", "status")} for x in r["day14"]["tests"]],
    }


def q_fomc(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    r = ES.fomc_study(ctx.cycle, reg=_reg(ctx))
    path = _save(ctx, "fomc", r)
    return {"artifact": path, "status": r["status"], "periods": r["periods"]}


def q_xevent(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    f = json.loads((OUT / ctx.cycle / "fomc.json").read_text())
    return {"xevent": f["xevent"]}


def q_elections(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    r = ES.election_study(ctx.cycle, reg=_reg(ctx))
    path = _save(ctx, "elections", r)
    return {
        "artifact": path,
        "n_events": {a: {s: v["n_events"] for s, v in x.items()} for a, x in r["assets"].items()},
        "pending": r["pending"],
    }


def q_cycles(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    r = CY.run(ctx.cycle, reg=_reg(ctx))
    path = _save(ctx, "cycles", r)
    return {"artifact": path, "status": {k: v["status"] for k, v in r["cycles"].items()}}


def q_diagnostics(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    fr = CAL.daily_frame()
    x = fr["ret"][np.isfinite(fr["ret"]) & (fr["date"] <= CAL.protocol()["periods"]["DISCOVERY"][1])]
    return {
        "n": int(len(x)),
        "acf_ret_1_5": CY.acf(x, 5),
        "acf_absret_1_5": CY.acf(np.abs(x), 5),
        "band": float(1.96 / np.sqrt(len(x))),
    }


def q_gap(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    gaps = {
        "G4": "statistical arbitrage needs a second spot instrument with the same provenance (e.g. ETHUSDT spot); not fetched in this slice",
        "H2": "recurring events with data: FOMC statements (registry), perpetual funding times (strategy data). Without data: options expiries, CME settlements, index rebalances",
        "I3": "economic releases (CPI, NFP, GDP, PMI): bls.gov returns HTTP 403 here and consensus expectations need licensed data; no study is run and no dates are invented",
        "I4": "geopolitical shocks: no verified, timestamped event source is connected; narratives are not ingested as events",
    }
    gid = t["payload"]["gap"]
    ctx.store.edge(f"role:{t['role']}", "data_gap", f"gap:{gid}", {"why": gaps[gid]})
    return {"gap": gid, "status": "not_run", "why": gaps[gid]}


def q_forecast(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    r = FL.run(ctx.cycle, reg=_reg(ctx))
    path = _save(ctx, "forecast_link", r)
    return {"artifact": path, "status": {k: v["status"] for k, v in r["results"].items()}}


def q_adversarial(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    """E3/H3: attack every 'supported' finding - yearly stability, macro-day exclusion, practical relevance."""
    reg = _reg(ctx)
    sup = [r for r in reg.rows(run_id=ctx.cycle) if r["status"] == "supported" and r["period"] == "DISCOVERY"]
    cal = json.loads((OUT / ctx.cycle / "calendar.json").read_text())
    by = {x["hypothesis"]: x for f in cal["families"].values() for x in f["results"]}
    fr = CAL.daily_frame()
    reviews = []
    for r in sup:
        h = r["hypothesis"]
        rev: dict[str, Any] = {"hypothesis": h, "family": r["family"]}
        if h in by and r["family"] in ("F-DOW", "F-DOM", "F-MOY", "F-TOM"):
            x = by[h]
            key = {"F-DOM": "dom", "F-DOW": "dow", "F-MOY": "moy", "F-TOM": "tom"}[r["family"]]
            ok = np.isfinite(fr["ret"])
            years = {}
            for y in sorted({d[:4] for d in fr["date"]}):
                ym = ok & np.char.startswith(fr["date"].astype(str), y)
                a = np.abs(fr["ret"][ym & (fr[key] == x["label"])])
                b = np.abs(fr["ret"][ym & (fr[key] != x["label"])])
                years[y] = float(a.mean() - b.mean()) if len(a) and len(b) else None
            same = [v for v in years.values() if v is not None and np.sign(v) == np.sign(x["effect"])]
            rev.update(
                {
                    "yearly_absret_diff": years,
                    "years_same_sign": f"{len(same)}/{sum(v is not None for v in years.values())}",
                    "effect_without_fomc_election_days": x["excl_macro_effect"],
                    "practical": "a volatility pattern, not a return predictor; it is not tradable by itself (no directional edge, costs apply)",
                }
            )
        else:
            rev["practical"] = "event-volatility pattern: affects risk and forecast variance, not expected return"
        reviews.append(rev)
    return {"reviews": reviews}


def q_memory(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    """F2: every tested family/hypothesis enters the memory with status and why (failed ones included)."""
    reg = _reg(ctx)
    rows = reg.rows(run_id=ctx.cycle)
    n = 0
    for r in rows:
        if r["period"] not in ("DISCOVERY", "ALL", "SCREEN"):
            continue
        hid = "Q-" + r["id"][2:]
        ctx.store.x(
            "INSERT OR REPLACE INTO hypotheses (id, signature, statement, operator, parent_id, candidate_id, status, evidence, novelty, created, updated, classification, premises) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                hid,
                f"quant|{r['family']}|{r['hypothesis']}",
                r["hypothesis"],
                r["role"],
                None,
                None,
                r["status"],
                json.dumps(
                    {
                        "test": r["id"],
                        "p": r["p"],
                        "p_adj": r["p_adj"],
                        "effect": r["effect"],
                        "n": r["n"],
                        "method": r["method"],
                    }
                ),
                "quant-family",
                now(),
                now(),
                r["family"],
                None,
            ),
        )
        ctx.store.edge(
            f"role:{r['role']}", "tested", f"hypothesis:{hid}", {"family": r["family"], "status": r["status"]}
        )
        n += 1
    counts = reg.counts()
    return {"memory_records": n, "registry": counts}


def q_reassess(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    reg = _reg(ctx)
    rows = [r for r in reg.rows(run_id=ctx.cycle)]
    sup = sorted({r["hypothesis"] for r in rows if r["status"] == "supported"})
    fc = [r for r in rows if r["family"] == "F-FCAST"]
    return {
        "tests_this_run": len(rows),
        "supported_exploratory": sup,
        "forecast_features_promoted": [r["hypothesis"] for r in fc if str(r["status"]).startswith("candidate_feature")],
        "next": [
            {
                "id": "prospective-fomc-vol",
                "why": "track |4h BTC return| after each scheduled FOMC statement prospectively (next: 2026-12-09)",
            },
            {
                "id": "prospective-midterm-2026",
                "why": "the 2026 midterm (2026-11-03) is the first out-of-sample BTC midterm; post windows resolve 2026-11-04..2027-02",
            },
            {
                "id": "acquire-cpi-calendar",
                "why": "CPI/NFP studies need an authoritative release calendar (BLS blocked here) - human: provide a source",
            },
        ],
        "claims": "all 'supported' results are exploratory (confirmation data previously exposed to the operator); none is a verified signal",
    }


QUANT_HANDLERS = {
    "q_events": q_events, "q_calendar": q_calendar, "q_fomc": q_fomc, "q_xevent": q_xevent, "q_elections": q_elections,
    "q_cycles": q_cycles, "q_diagnostics": q_diagnostics, "q_gap": q_gap, "q_forecast": q_forecast,
    "q_adversarial": q_adversarial, "q_memory": q_memory, "q_reassess": q_reassess,
}  # fmt: skip


def seed(store: Any, cycle: str, cfg: dict[str, Any]) -> None:
    ev = new_task(store, cycle, "q_events", "I2", "DISCOVER")
    for g in ("G4", "H2", "I3", "I4"):
        new_task(store, cycle, "q_gap", g, "UNDERSTAND", {"gap": g})
    dg = new_task(store, cycle, "q_diagnostics", "G2", "UNDERSTAND")
    ca = new_task(store, cycle, "q_calendar", "H1", "TEST", deps=[ev])
    fo = new_task(store, cycle, "q_fomc", "I2", "TEST", deps=[ev])
    xe = new_task(store, cycle, "q_xevent", "H4", "TEST", deps=[fo])
    el = new_task(store, cycle, "q_elections", "I1", "TEST", deps=[ev])
    cy = new_task(store, cycle, "q_cycles", "G3", "TEST")
    fc = new_task(store, cycle, "q_forecast", "G1", "EVALUATE", deps=[ca, ev])
    ad = new_task(store, cycle, "q_adversarial", "H3", "CHALLENGE", deps=[ca, fo, cy])
    mem = new_task(store, cycle, "q_memory", "F2", "ARCHIVE", deps=[ca, fo, xe, el, cy, fc, ad, dg])
    new_task(store, cycle, "q_reassess", "F4", "REASSESS", deps=[mem])
