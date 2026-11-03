"""Role handlers for one research cycle: DISCOVER -> VERIFY -> UNDERSTAND -> FORMULATE -> IMPLEMENT -> TEST ->
CHALLENGE -> EVALUATE -> ARCHIVE -> REASSESS.

Each handler is one bounded task with a typed payload/result; it may spawn follow-up tasks. Status-changing
decisions (duplicate, rejected, eligibility) are made by deterministic code; LLM output only fills research text.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..research.memory import now
from . import adversarial as ADV
from . import codeprop, drift
from . import mechanisms as M
from . import sources as SRC
from .llm import CritiqueOut, HypothesisOut, wrap_untrusted
from .orchestrator import Ctx, new_task
from .policy import eligibility, scrub_context

LAB_ROOT = Path("artifacts/research/army_v06")
CAND_DIR = Path("artifacts/army/candidates")


def set_source_status(ctx: Ctx, sid: str, status: str) -> None:
    """Source status is mutable; every change is also kept as a graph edge (status history per cycle)."""
    ctx.store.x("UPDATE army_sources SET status=? WHERE id=?", (status, sid))
    ctx.store.edge(f"source:{sid}", f"status@{ctx.cycle}", f"status:{status}", {"cycle": ctx.cycle})


def result_for(ctx: Ctx, kind: str, cid: str) -> dict[str, Any]:
    """Result of this cycle's task of `kind` whose payload concerns candidate `cid`."""
    for r in ctx.store.q("SELECT payload, result FROM army_tasks WHERE cycle_id=? AND kind=?", (ctx.cycle, kind)):
        if (r["payload"] or {}).get("candidate_id") == cid:
            return r["result"] or {}
    return {}


def record_failure(ctx: Ctx, hid: str | None, cid: str, stage: str, why: Any) -> None:
    """Failed experiments are remembered with the stage and reason (F2 duty, also done at rejection points)."""
    ctx.store.x("UPDATE candidates SET status=? WHERE id=?", (f"rejected_{stage}", cid))
    if hid:
        ctx.store.x(
            "UPDATE hypotheses SET status=?, evidence=?, classification=?, updated=? WHERE id=?",
            ("rejected", json.dumps({"stage": stage, "why": why}, default=str), f"rejected_{stage}", now(), hid),
        )
    key = hashlib.sha256(f"{cid}|{stage}".encode()).hexdigest()[:20]
    ctx.store.mem.put_experiment(
        key, cid, f"army-reject-{stage}", "", "", {"cycle": ctx.cycle, "hypothesis": hid, "why": why}
    )
    ctx.store.edge(f"candidate:{cid}", "rejected_at", f"stage:{stage}", {"why": why, "cycle": ctx.cycle})


def reclassify_sources(store: Any, reason: str) -> list[dict[str, Any]]:
    """Maintenance (A4): re-run the classifier on stored sources; a changed family re-opens the source.

    Earlier conclusions are not dogma: a decision that rested on a defective classification is re-examined, and
    the change is journaled with its reason.
    """
    changed = []
    for r in store.q("SELECT id, title, abstract, mechanism, status FROM army_sources"):
        new = M.classify(r["title"], r["abstract"])
        old = (r["mechanism"] or {}).get("family")
        if new["family"] != old:
            reopen = r["status"] in ("duplicate_mechanism", "infeasible_with_current_data")
            status = "discovered" if reopen else r["status"]
            store.x("UPDATE army_sources SET mechanism=?, status=? WHERE id=?", (json.dumps(new), status, r["id"]))
            store.edge(f"source:{r['id']}", "reclassified", f"family:{new['family']}", {"from": old, "reason": reason})
            changed.append({"source": r["id"], "from": old, "to": new["family"], "status": status})
    store.log("A4", "sources_reclassified", {"reason": reason, "changed": changed})
    return changed


# ============================================================================ DISCOVER (A1, A2)
def discover(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    role = t["role"]
    queries = ctx.config.get("queries", {}).get(role) or SRC.DISCOVERY_QUERIES[role]
    enabled = ctx.store.control("source_arxiv_enabled", True)
    found, new = [], []
    for q in queries[:2]:
        SRC._throttle("arxiv", enabled)  # raises if disabled by policy or human control
        items = SRC.search_arxiv(q, int(ctx.config.get("max_results", 4)))
        ctx.store.add_usage(ctx.cycle, role, ext=1)
        for it in items:
            base = re.sub(r"v\d+$", "", it.id)  # same paper, any version
            seen = ctx.store.q("SELECT id FROM army_sources WHERE id LIKE ?", (base + "%",))
            found.append(it.id)
            if seen:
                continue
            row = it.to_row()
            cls = M.classify(it.title, it.abstract)
            ctx.store.x(
                "INSERT OR IGNORE INTO army_sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    it.id, it.origin, it.url, it.title, json.dumps(it.authors), it.published, it.updated, it.retrieved,
                    it.abstract, it.doi, it.journal_ref, it.license_note, q, None, json.dumps(cls), "discovered",
                ),
            )  # fmt: skip
            ctx.store.edge(f"source:{it.id}", "discovered_by", f"role:{role}", {"query": q, "cycle": ctx.cycle})
            new.append({**row, "family": cls["family"], "relevance": _relevance(row, cls)})
    # research queue: sources discovered earlier by these queries but never verified stay eligible
    backlog = []
    for r in ctx.store.q("SELECT * FROM army_sources WHERE status='discovered'"):
        if r["query"] in queries[:2] and r["id"] not in {n["id"] for n in new}:
            cls = r["mechanism"] or M.classify(r["title"], r["abstract"])
            backlog.append({**r, "family": cls["family"], "relevance": _relevance(r, cls), "from_backlog": True})
    pool = sorted(new + backlog, key=lambda r: -r["relevance"])
    picked = [r for r in pool if r["relevance"] > 0][: int(ctx.config.get("verify_per_scout", 2))]
    for r in picked:
        vt = new_task(ctx.store, ctx.cycle, "verify", "A3", "VERIFY", {"source_id": r["id"]})
        new_task(ctx.store, ctx.cycle, "novelty", "A4", "UNDERSTAND", {"source_id": r["id"]}, deps=[vt])
    return {
        "queries": queries[:2],
        "returned": len(found),
        "new_sources": [r["id"] for r in new],
        "backlog_considered": [r["id"] for r in backlog],
        "selected_for_verification": [r["id"] for r in picked],
    }


def _relevance(row: dict[str, Any], cls: dict[str, Any]) -> float:
    text = f"{row['title']} {row['abstract']}".lower()
    crypto = 1.0 if any(k in text for k in ("bitcoin", "crypto", "btc", "perpetual")) else 0.3
    fam = cls["family"]
    return crypto * (max(cls["scores"].values()) + (2 if fam in M.IMPLEMENTABLE else 0))


# ============================================================================ VERIFY (A3)
def verify(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    sid = t["payload"]["source_id"]
    src = ctx.store.q("SELECT * FROM army_sources WHERE id=?", (sid,))[0]
    rec = SRC.fetch_arxiv_record(sid.split(":", 1)[1])
    cr = SRC.crossref_lookup(src["title"], src["doi"])
    ctx.store.add_usage(ctx.cycle, "A3", ext=2)
    exists = rec is not None and rec.title == src["title"]
    g = SRC.grade(src, cr)
    v = {
        "record_refetched": exists,
        "published": rec.published if rec else None,
        "updated": rec.updated if rec else None,
        "crossref": cr,
        "evidence": g,
        "classification": "verified_source" if exists else "unverifiable_source",
        "claim_status": "claimed (abstract-level), not replicated" if exists else "unsupported",
    }
    ctx.store.x(
        "UPDATE army_sources SET verification=?, status=? WHERE id=?", (json.dumps(v), v["classification"], sid)
    )
    ctx.store.edge(f"source:{sid}", "verified_by", "role:A3", {"grade": g["grade"]})
    return {"source_id": sid, **v}


# ============================================================================ UNDERSTAND (A4, B1-B4)
def novelty(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    sid = t["payload"]["source_id"]
    src = ctx.store.q("SELECT * FROM army_sources WHERE id=?", (sid,))[0]
    if src["status"] != "verified_source":
        return {"source_id": sid, "decision": "not_verified", "_status": "rejected"}
    fam = (src["mechanism"] or {}).get("family", "unclassified")
    if fam in M.INFEASIBLE:
        set_source_status(ctx, sid, "infeasible_with_current_data")
        new_task(ctx.store, ctx.cycle, "gap_proposal", "D1", "IMPLEMENT", {"family": fam, "source_id": sid})
        return {"source_id": sid, "family": fam, "decision": "infeasible", "why": M.INFEASIBLE[fam]}
    if fam not in M.IMPLEMENTABLE:
        return {"source_id": sid, "family": fam, "decision": "no_implementable_mechanism", "_status": "rejected"}
    # duplicates at mechanism level: earlier labs + earlier army hypotheses with the same family
    prior = [h for h in M.prior_hypotheses() if h["family"] == fam]
    mine = ctx.store.q("SELECT id, signature, status, statement FROM hypotheses WHERE signature LIKE ?", (fam + "|%",))
    other_sources = ctx.store.q(
        "SELECT id, title FROM army_sources WHERE id != ? AND status IN ('verified_source','formulated')", (sid,)
    )
    near = [s["id"] for s in other_sources if M.jaccard(s["title"], src["title"]) >= 0.5]
    reexamine = ctx.config.get("reexamine", {}).get(fam)
    if (prior or mine) and not reexamine:
        ref = f"hypothesis:{mine[0]['id']}" if mine else f"lab_hypothesis:{prior[0]['lab']}/{prior[0]['id']}"
        ctx.store.edge(
            f"source:{sid}", "duplicate_mechanism_of", ref, {"family": fam, "prior_count": len(prior) + len(mine)}
        )
        set_source_status(ctx, sid, "duplicate_mechanism")
        return {
            "source_id": sid,
            "family": fam,
            "decision": "duplicate_mechanism",
            "duplicate_of": ref,
            "earlier_investigations": len(prior) + len(mine),
            "reexamination_rule": "allowed only with a recorded reason: new data period, changed market conditions or new evidence",
            "near_duplicate_sources": near,
        }
    budget = int(ctx.config.get("max_candidates", 3))
    started = len(ctx.store.q("SELECT id FROM army_tasks WHERE cycle_id=? AND kind='formulate'", (ctx.cycle,)))
    if started >= budget:
        return {"source_id": sid, "family": fam, "decision": "deferred_budget"}
    market = [
        r["id"] for r in ctx.store.q("SELECT id FROM army_tasks WHERE cycle_id=? AND kind='market'", (ctx.cycle,))
    ]
    new_task(
        ctx.store,
        ctx.cycle,
        "formulate",
        M.RESEARCHER[fam],
        "FORMULATE",
        {"source_id": sid, "family": fam, "reexamine": reexamine},
        deps=market,
    )
    set_source_status(ctx, sid, "formulated")
    return {
        "source_id": sid,
        "family": fam,
        "decision": "novel" if not reexamine else "reexamination",
        "near_duplicate_sources": near,
    }


def market(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    from ..data.datasets import load_split

    role = t["role"]
    d = load_split("BTCUSDT", "development")  # DEVELOPMENT ONLY: researcher context never sees selection data
    c = d["close"]
    lr = np.diff(np.log(c))
    if role == "B1":
        daily = lr[: len(lr) // 24 * 24].reshape(-1, 24).sum(1)
        return {
            "period": "development 2020-2023",
            "ann_vol": float(np.std(lr) * math.sqrt(8760)),
            "mean_daily_ret": float(daily.mean()),
            "daily_ret_kurtosis": float(((daily - daily.mean()) ** 4).mean() / daily.var() ** 2 - 3),
            "max_drawdown": float(np.min(c / np.maximum.accumulate(c) - 1)),
        }
    if role == "B2":
        f = d["funding"][d["funding"] != 0]
        return {
            "period": "development 2020-2023",
            "funding_events": int(len(f)),
            "mean_funding_per_event": float(f.mean()),
            "share_positive": float((f > 0).mean()),
            "acf1": float(np.corrcoef(f[:-1], f[1:])[0, 1]),
        }
    if role == "B3":
        w = 720
        vol = np.array([np.std(lr[i - w : i]) for i in range(w, len(lr), 24)])
        trend = np.array(
            [abs(np.sum(lr[i - w : i])) / (np.std(lr[i - w : i]) * math.sqrt(w)) for i in range(w, len(lr), 24)]
        )
        hv = vol > np.median(vol)
        return {
            "period": "development 2020-2023",
            "share_high_vol": float(hv.mean()),
            "share_trending(|z|>1)": float((trend > 1).mean()),
            "regime_switches_high_low": int(np.sum(hv[1:] != hv[:-1])),
        }
    from ..backtest.interface import BarView
    from ..forecast.domain import FEATURES

    api = [m for m in dir(BarView) if not m.startswith("_")]
    return {
        "strategy_view_api": api,
        "forecast_features": list(FEATURES),
        "availability": {
            "strategy": "bar t decided at its close, executed at t+1 open",
            "forecast": "bars complete before origin - 24 h (archive publication lag)",
        },
        "unavailable": ["order book", "trades", "open interest history", "bar timestamps inside BarView"],
    }


def forecast_live(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    """Read-only live observation (B1): resolve matured prospective forecasts, then issue the next origin once."""
    from ..forecast import prospective as P
    from ..forecast.domain import DAY
    from ..forecast.ledger import ForecastLedger

    out: dict[str, Any] = {"resolve": P.resolve(fetch=True)}
    ctx.store.add_usage(ctx.cycle, "B1", ext=1)
    nxt = (int(time.time() * 1000) // DAY + 1) * DAY
    issued = {e["data"]["origin_ms"] for e in ForecastLedger().forecasts().values()}
    if nxt in issued:
        out["issue"] = {"skipped": "origin already issued", "origin_ms": nxt}
    else:
        r = P.issue(fetch=False)
        out["issue"] = {k: r[k] for k in ("origin_utc", "as_of_utc", "lag_h")} | {"n": len(r["forecasts"])}
    return out


def forecast_watch(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    r = drift.check()
    if r["alerts"]:
        ctx.store.log("F3", "forecast_degradation", {"alerts": r["alerts"]})
        new_task(
            ctx.store,
            ctx.cycle,
            "forecast_reevaluate",
            "E2",
            "REASSESS",
            {"alerts": r["alerts"], "status": r["status"]},
        )
    return {k: r[k] for k in ("resolved", "open", "min_resolved_for_assessment", "alerts", "status")}


def forecast_reevaluate(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    """Degradation trigger: record the need and the frozen route (challenger re-evaluation), never auto-switch."""
    rec = {
        "alerts": t["payload"]["alerts"],
        "action": "run `evox forecast evolve` for the alerting targets (trial-counted) and keep issuing champion + challengers",
        "never": "no automatic champion switch; no trading",
    }
    ctx.store.mem.put_experiment(
        hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:20],
        "forecast",
        "drift-trigger",
        "",
        "",
        rec,
    )
    return rec


# ============================================================================ FORMULATE (C1-C3, C4)
def formulate(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    p = t["payload"]
    src = ctx.store.q("SELECT * FROM army_sources WHERE id=?", (p["source_id"],))[0]
    fam = p["family"]
    tpl = M.TEMPLATES[fam]
    # re-check family-level duplicates BEFORE spending an LLM call (another source may have been formulated since)
    same = ctx.store.q("SELECT id FROM hypotheses WHERE signature LIKE ?", (fam + "|%",))
    if same and not p.get("reexamine"):
        ctx.store.edge(
            f"source:{p['source_id']}",
            "duplicate_mechanism_of",
            f"hypothesis:{same[0]['id']}",
            {"family": fam, "at": "formulate"},
        )
        return {
            "decision": "duplicate_mechanism",
            "family": fam,
            "duplicate_of": same[0]["id"],
            "llm_used": False,
            "_status": "rejected",
        }
    mkt = {
        r["role"]: r
        for r in [
            {"role": x["role"], **(x["result"] or {})}
            for x in ctx.store.q("SELECT role, result FROM army_tasks WHERE cycle_id=? AND kind='market'", (ctx.cycle,))
        ]
    }
    memory = {f: sum(1 for h in M.prior_hypotheses() if h["family"] == f) for f in M.IMPLEMENTABLE}
    context = scrub_context(
        {
            "market_development": mkt,
            "earlier_investigations_by_family": memory,
            "template": {
                "family": fam,
                "params": {k: {"min": v[0], "max": v[1], "default": v[2]} for k, v in tpl["params"].items()},
                "long_only": tpl["long_only"],
            },
        }
    )
    prompt = (
        f"Role {t['role']}: extract ONE falsifiable trading hypothesis for BTCUSDT perpetual 1-hour bars from the source. "
        f"The implementation family is fixed to {fam!r}; choose parameters only within the template ranges. "
        "Keys: family, claimed_mechanism, statement, decision_rule, horizon_h, params, alternatives (2-4 rival "
        "explanations), prediction (what result would REFUTE it), data_requirements, limitations.\n"
        f"Context (development-period data only): {json.dumps(context, default=float)}\n" + wrap_untrusted(src)
    )
    out, info = ctx.llm.ask(t["role"], prompt, HypothesisOut)
    abstract_claim = ". ".join(src["abstract"].split(". ")[:2])[:500]
    if isinstance(out, HypothesisOut) and out.family == fam:
        h = out.model_dump()
        generator = "claude-cli"
    else:
        h = {
            "family": fam,
            "claimed_mechanism": f"(from source, unverified) {abstract_claim}",
            "statement": _default_statement(fam),
            "decision_rule": tpl["body"].strip().splitlines()[0],
            "horizon_h": tpl["params"]["lookback_h"][2],
            "params": {},
            "alternatives": [
                "the effect is a development-period artefact",
                "the effect is beta to BTC rather than timing skill",
                "costs and delay remove the effect",
            ],
            "prediction": "refuted if the development walk-forward screen fails, the adversarial battery finds a hard failure, or the frozen selection rule is not met",
            "data_requirements": "BTCUSDT 1 h OHLCV (+ funding for funding_carry)",
            "limitations": "abstract-level claim; paper results not replicated",
        }
        generator = "deterministic-template" + (
            f" (LLM fallback: {info.get('reason')})" if info.get("used_llm") or info.get("reason") else ""
        )
    params = M.clamp_params(fam, h.get("params"))
    sig = M.signature(fam, params["lookback_h"], tpl["long_only"])
    dup = ctx.store.q("SELECT id, status FROM hypotheses WHERE signature=?", (sig,))
    near = [
        x["id"]
        for x in ctx.store.q("SELECT id, statement FROM hypotheses")
        if M.jaccard(x["statement"] or "", h["statement"]) >= 0.6
    ]
    hid = "H-" + hashlib.sha256(f"{sig}|{json.dumps(params, sort_keys=True)}".encode()).hexdigest()[:10]
    if (dup or near) and not p.get("reexamine"):
        ctx.store.edge(
            f"hypothesis:{hid}",
            "duplicate_mechanism_of",
            f"hypothesis:{(dup or [{'id': near[0]}])[0]['id']}",
            {"signature": sig},
        )
        return {
            "hypothesis_id": hid,
            "decision": "duplicate_hypothesis",
            "signature": sig,
            "duplicate_of": [x["id"] for x in dup] + near,
            "_status": "rejected",
        }
    hyp = {
        **h,
        "params": params,
        "signature": sig,
        "source_id": p["source_id"],
        "generator": generator,
        "llm": info,
        "premises": M.PREMISES.get(fam, M.PREMISES["default"]),
        "information_availability": "decision at bar close from closed bars only; executed at next open; funding as published per bar",
        "costs": "lab cost model: taker fees, spread, square-root impact, funding (cost_multiplier 1, stress 2-3x)",
        "risk": "signal in [-1, 1] times engine max leverage 2x; vol_managed_long capped at 1x notional",
        "evaluation": "frozen research protocol v2 + army policy v1",
    }
    ctx.store.x(
        "INSERT OR REPLACE INTO hypotheses (id, signature, statement, operator, parent_id, candidate_id, status, evidence, novelty, created, updated, classification, premises) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            hid,
            sig,
            hyp["statement"],
            fam,
            None,
            None,
            "formulated",
            json.dumps({"source": p["source_id"]}),
            "novel-family" if not p.get("reexamine") else "reexamination",
            now(),
            now(),
            None,
            json.dumps(hyp["premises"]),
        ),
    )
    ctx.store.edge(
        f"source:{p['source_id']}", "motivated", f"hypothesis:{hid}", {"role": t["role"], "generator": generator}
    )
    ct = new_task(ctx.store, ctx.cycle, "contract", "D1", "IMPLEMENT", {"hypothesis": {**hyp, "id": hid}})
    rt = new_task(ctx.store, ctx.cycle, "render", "D2", "IMPLEMENT", {"hypothesis_id": hid}, deps=[ct])
    return {"hypothesis_id": hid, "decision": "formulated", "hypothesis": hyp, "next": [ct, rt]}


def _default_statement(fam: str) -> str:
    return {
        "tsmom": "The sign of the volatility-normalised past return over the lookback predicts the next-period return of BTC.",
        "breakout": "The position of the close inside its lookback high-low channel predicts continuation.",
        "reversal": "Large short-horizon moves (in volatility units) partially revert over the following hours.",
        "vol_managed_long": "Scaling long BTC exposure inversely to trailing realized volatility improves risk-adjusted return versus constant exposure.",
        "funding_carry": "Persistent positive (negative) perpetual funding precedes weaker (stronger) BTC returns, so positioning against the funding sign earns a premium net of funding.",
    }[fam]


def synthesis(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    validated = ctx.store.q("SELECT id, signature FROM hypotheses WHERE status='validated'")
    if len(validated) < 2:
        return {
            "decision": "no_synthesis",
            "why": f"{len(validated)} validated mechanisms; synthesis requires at least 2 independently validated mechanisms (no indicator stacking)",
        }
    return {"decision": "eligible", "mechanisms": [v["id"] for v in validated]}


# ============================================================================ IMPLEMENT (D1, D2)
def contract(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    h = t["payload"]["hypothesis"]
    missing = [
        k
        for k in (
            "statement",
            "claimed_mechanism",
            "alternatives",
            "prediction",
            "premises",
            "params",
            "information_availability",
            "costs",
            "risk",
        )
        if not h.get(k)
    ]
    if h["family"] not in M.IMPLEMENTABLE:
        missing.append("implementable family")
    if missing:
        return {"ok": False, "missing": missing, "_status": "rejected"}
    return {"ok": True, "hypothesis": h}


def render(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    hid = t["payload"]["hypothesis_id"]
    h = ctx.task_result((t["deps"] or {})["deps"][0])["hypothesis"]  # the D1 contract task
    name = f"army_{h['family']}_{hid[2:10]}"
    src = M.render(h["family"], name, h["params"], f"{h['statement']} Source: {h['source_id']}. Hypothesis {hid}.")
    sha = M.code_sha(src)
    cid = "army-" + sha[:10]
    CAND_DIR.mkdir(parents=True, exist_ok=True)
    (CAND_DIR / f"{cid}.py").write_text(src)
    ctx.store.x(
        "INSERT OR IGNORE INTO candidates (id, parent_id, code_sha256, generator, operator, spec, path, status, created) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            cid,
            None,
            sha,
            "army:D2-template",
            h["family"],
            json.dumps({"hypothesis_id": hid, "params": h["params"]}),
            str(CAND_DIR / f"{cid}.py"),
            "implemented",
            now(),
        ),
    )
    ctx.store.x("UPDATE hypotheses SET candidate_id=?, updated=? WHERE id=?", (cid, now(), hid))
    ctx.store.edge(f"hypothesis:{hid}", "implemented_by", f"candidate:{cid}", {"code_sha256": sha})
    payload = {"candidate_id": cid, "hypothesis_id": hid, "hypothesis": h}
    tt = new_task(ctx.store, ctx.cycle, "test", "D3", "TEST", payload)
    st = new_task(ctx.store, ctx.cycle, "security", "D4", "TEST", payload)
    ch = new_task(ctx.store, ctx.cycle, "challenge", "E3", "CHALLENGE", payload, deps=[tt, st])
    ev = new_task(ctx.store, ctx.cycle, "evaluate", "E1", "EVALUATE", payload, deps=[ch])
    ss = new_task(ctx.store, ctx.cycle, "stats", "E2", "EVALUATE", payload, deps=[ev])
    sm = new_task(ctx.store, ctx.cycle, "simulate", "E4", "EVALUATE", payload, deps=[ch])
    rk = new_task(ctx.store, ctx.cycle, "risk", "F3", "EVALUATE", payload, deps=[ch])
    new_task(ctx.store, ctx.cycle, "archive", "F2", "ARCHIVE", payload, deps=[ss, sm, rk])
    if ctx.config.get("generate_test_proposals", True):
        new_task(ctx.store, ctx.cycle, "test_proposal", "D3", "TEST", payload, deps=[tt])
    return {"candidate_id": cid, "code_sha256": sha, "path": str(CAND_DIR / f"{cid}.py")}


def gap_proposal(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    fam = t["payload"]["family"]
    if fam != "seasonality":
        return {"family": fam, "decision": "recorded_data_gap", "why": M.INFEASIBLE[fam]}
    diff = (
        "--- a/src/evolutionx/backtest/interface.py\n+++ b/src/evolutionx/backtest/interface.py\n"
        "@@ -1,1 +1,2 @@\n+# proposal: expose view.open_time(n) so seasonality hypotheses become testable\n"
    )
    meta = codeprop.submit(
        ctx.store,
        "D1",
        "Expose bar timestamps in BarView",
        f"needed by {t['payload']['source_id']} ({M.INFEASIBLE[fam]})",
        diff,
        [],
    )
    return {"family": fam, "proposal": meta["id"], "status": meta["status"]}


# ============================================================================ TEST (D3, D4)
def _source(cid: str) -> str:
    return (CAND_DIR / f"{cid}.py").read_text()


def test(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    from ..backtest.interface import decisions_for, load_module_strategy
    from ..data.datasets import load_split
    from ..research.contract import static_check

    cid = t["payload"]["candidate_id"]
    src = _source(cid)
    issues = static_check(src)
    if issues:
        record_failure(ctx, t["payload"].get("hypothesis_id"), cid, "static_check", issues)
        return {"candidate_id": cid, "static_issues": issues, "verdict": "rejected", "_status": "rejected"}
    d = load_split("BTCUSDT", "development")
    sl = {k: v[:3000] for k, v in d.items()}
    mod = ADV.load_module(src)
    a = decisions_for(load_module_strategy(mod), sl)
    b = decisions_for(load_module_strategy(ADV.load_module(src)), sl)
    det = bool(np.array_equal(a, b))
    probe = [
        i
        for i in (500, 1500, 2999)
        if abs(load_module_strategy(mod).decide(ADV._view({k: v[: i + 1] for k, v in sl.items()}, i)) - a[i]) > 1e-12
    ]
    ok = det and not probe and np.all(np.abs(a) <= 1)
    if not ok:
        record_failure(
            ctx, t["payload"].get("hypothesis_id"), cid, "tests", {"deterministic": det, "truncation": probe}
        )
    return {
        "candidate_id": cid,
        "static_issues": [],
        "deterministic_replay": det,
        "truncation_mismatch_bars": probe,
        "verdict": "passed" if ok else "rejected",
        **({} if ok else {"_status": "rejected"}),
    }


def security(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    from ..research import sandbox

    src = _source(t["payload"]["candidate_id"])
    t0 = time.perf_counter()
    mod = ADV.load_module(src)
    from ..backtest.interface import decisions_for, load_module_strategy
    from ..data.datasets import load_split

    d = load_split("BTCUSDT", "development")
    decisions_for(load_module_strategy(mod), {k: v[:2000] for k, v in d.items()})
    return {
        "sandbox_available": sandbox.AVAILABLE,
        "source_bytes": len(src.encode()),
        "decision_ms_per_1000_bars": round((time.perf_counter() - t0) * 500, 2),
        "imports": sorted({ln.split()[1] for ln in src.splitlines() if ln.startswith("import ")}),
        "note": "the research lab re-runs the candidate inside its namespace sandbox during EVALUATE",
    }


def test_proposal(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    cid = t["payload"]["candidate_id"]
    fam = t["payload"]["hypothesis"]["family"]
    name = f"test_army_{cid.replace('-', '_')}.py"
    body = (
        f'"""Generated by role D3 for {cid}: template {fam!r} renders deterministically and passes the contract."""\n\n'
        "from evolutionx.army import mechanisms as M\nfrom evolutionx.research.contract import static_check\n\n\n"
        f"def test_{fam}_template_is_deterministic_and_static_clean():\n"
        f"    p = M.clamp_params({fam!r}, {json.dumps(t['payload']['hypothesis']['params'])})\n"
        f"    a = M.render({fam!r}, 'x', p, 'doc')\n"
        f"    assert a == M.render({fam!r}, 'x', p, 'doc')\n"
        "    assert static_check(a) == []\n"
    )
    lines = body.splitlines()
    diff = f"--- /dev/null\n+++ b/tests/army_generated/{name}\n@@ -0,0 +1,{len(lines)} @@\n" + "".join(
        f"+{ln}\n" for ln in lines
    )
    meta = codeprop.submit(
        ctx.store,
        "D3",
        f"Regression test for {cid}",
        "pin the template rendering used by this candidate",
        diff,
        [f"tests/army_generated/{name}"],
    )
    return {"proposal": meta["id"], "status": meta["status"], "files": meta["files"]}


# ============================================================================ CHALLENGE (E3)
def challenge(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    p = t["payload"]
    h = p["hypothesis"]
    res = ADV.battery(_source(p["candidate_id"]), h["params"], n_placebo=int(ctx.config.get("n_placebo", 8)))
    summary = {k: {kk: vv for kk, vv in v.items() if kk != "placebo_sharpes"} for k, v in res["tests"].items()}
    prompt = (
        "Role E3 (adversarial): try to refute the claimed edge. Given the hypothesis and development-period test "
        "results, list concrete concerns (leakage, overfitting, unrealistic assumptions, beta in disguise), the most "
        "likely failure, and one additional falsification test. Keys: concerns, most_likely_failure, additional_test.\n"
        + json.dumps(
            scrub_context(
                {
                    "hypothesis": {k: h[k] for k in ("statement", "claimed_mechanism", "decision_rule", "params")},
                    "development_tests": summary,
                }
            ),
            default=float,
        )
    )
    crit, info = (None, {"used_llm": False, "reason": "no LLM critique requested"})
    if ctx.config.get("llm_critique", True):
        crit, info = ctx.llm.ask("E3", prompt, CritiqueOut)
    out = {**res, "llm_critique": crit.model_dump() if crit else None, "llm": info}
    if res["hard_failures"]:
        record_failure(ctx, p.get("hypothesis_id"), p["candidate_id"], "adversarial", res["hard_failures"])
        return {**out, "_status": "rejected"}
    return out


# ============================================================================ EVALUATE (E1, E2, E4, F3)
def evaluate(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    from ..research.supervisor import Lab, Supervisor

    p = t["payload"]
    h = p["hypothesis"]
    lab = Lab(LAB_ROOT, repo=Path.cwd())
    sup = Supervisor(lab)
    if not lab.memory.q("SELECT id FROM trials WHERE candidate_id LIKE 'inherited:%' LIMIT 1"):
        sup.inherit_validation_trials(
            [
                d.parent
                for d in Path("artifacts/research").glob("*/research.db")
                if d.parent != LAB_ROOT and "superseded" not in d.parent.name
            ]
        )
    camp = f"army-{p['candidate_id']}"
    if not lab.memory.q("SELECT id FROM campaigns WHERE id=?", (camp,)):
        sup.import_candidate(
            camp,
            "research",
            _source(p["candidate_id"]),
            {
                "statement": h["statement"],
                "mechanism": h["claimed_mechanism"],
                "alternatives": h["alternatives"],
                "prediction": h["prediction"],
                "novelty": f"research army {h['signature']} from {h['source_id']}",
                "premises": h["premises"],
            },
            f"research-army:{h['generator']}",
            f"rendered by role D2 from a reviewed template; hypothesis {p['hypothesis_id']} from {h['source_id']}",
            [
                "development diagnostics (2020-2023)",
                "source abstract",
                "family counts of earlier investigations; no validation or final results",
            ],
            "selection data are previously exposed (35+ trials); only prospective paper evidence can confirm",
        )
    sup.run(camp)
    task = lab.memory.q("SELECT status, stage, checkpoint, error FROM tasks WHERE campaign_id=?", (camp,))[0]
    ck = task["checkpoint"] or {}
    return {
        "lab": str(LAB_ROOT),
        "campaign": camp,
        "task_status": task["status"],
        "error": task["error"],
        "verdict": ck.get("verdict"),
        "classification": (ck.get("classification") or {}).get("class"),
        "premise_check": (ck.get("premise_check") or {}).get("verdict"),
        "screen": ck.get("screen"),
        "decision": ck.get("decision"),
        "validation_summary": ck.get("validation_summary"),
        "data_labels": {
            "development": "free exploration",
            "validation": "SELECTION - previously exposed, not confirmatory",
        },
    }


def stats(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    p = t["payload"]
    ev = result_for(ctx, "evaluate", p["candidate_id"])
    adv = result_for(ctx, "challenge", p["candidate_id"])
    dec = ev.get("decision") or {}
    elig = eligibility(ev.get("verdict"), adv, None)
    return {
        "candidate_id": p["candidate_id"],
        "lab_verdict": ev.get("verdict"),
        "selection_rule_checks": dec.get("checks"),
        "delta_sharpe_vs_champion": (dec.get("bootstrap") or {}).get("delta_sharpe"),
        "prob_delta_positive": (dec.get("bootstrap") or {}).get("prob_positive"),
        "deflated_sharpe": (dec.get("dsr") or {}).get("dsr"),
        "n_validation_trials_counted": dec.get("n_validation_trials"),
        "baselines": {
            "champion": "parent v0 time-series momentum",
            "buy_and_hold": (ev.get("validation_summary") or {}).get("reference_buy_and_hold"),
            "cash": "Sharpe 0",
        },
        "dev_screen": ev.get("screen"),
        "adversarial_verdict": adv.get("verdict"),
        "adversarial_weaknesses": adv.get("weaknesses"),
        "eligibility": elig,
        "exposure_note": "validation results are selection evidence on previously exposed data; never confirmatory",
    }


def simulate(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    fam = t["payload"]["hypothesis"]["family"]
    interaction = {
        "funding_carry": "leveraged agents' reaction to funding (v0.5 C2x: funding pushes leveraged agents contrarian)",
        "reversal": "liquidity provision / overreaction",
    }
    if fam not in interaction:
        return {
            "applicable": False,
            "why": f"{fam} is a single-asset statistical mechanism; agent interactions add nothing testable here",
            "sim_runs": 0,
        }
    return {
        "applicable": True,
        "linked_evidence": "artifacts/observatory/cascade_c2x_exploratory.json" if fam == "funding_carry" else None,
        "mechanism": interaction[fam],
        "sim_runs": 0,
        "note": "existing simulator evidence linked; a new simulator experiment needs its own pre-registration",
    }


def risk(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    from ..backtest.engine import CostModel, run_backtest
    from ..backtest.interface import decisions_for, load_module_strategy
    from ..backtest.metrics import daily_returns, max_drawdown
    from ..data.datasets import load_split, protocol

    p = t["payload"]
    d = load_split("BTCUSDT", "development")
    dec = decisions_for(load_module_strategy(ADV.load_module(_source(p["candidate_id"])), p["hypothesis"]["params"]), d)
    res = run_backtest(d, dec, CostModel.from_protocol(protocol(), "BTCUSDT"))
    _, r = daily_returns(res.equity, res.open_time)
    q = np.quantile(r, 0.05)
    return {
        "period": "development 2020-2023",
        "max_drawdown": float(max_drawdown(res.equity)),
        "daily_var95": float(-q),
        "daily_cvar95": float(-r[r <= q].mean()),
        "worst_day": float(r.min()),
        "liquidations": res.n_liquidations,
    }


# ============================================================================ ARCHIVE (F2)
def archive(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    p = t["payload"]
    cid, hid = p["candidate_id"], p["hypothesis_id"]
    st = result_for(ctx, "stats", cid)
    rk = result_for(ctx, "risk", cid)
    status = st.get("eligibility", {}).get("status", "unknown")
    hyp_status = {
        "rejected": "refuted" if st.get("lab_verdict") in ("refuted", "reject") else "not_supported",
        "prospective_challenger": "selection_pass",
        "validated": "validated",
    }.get(status, "inconclusive")
    reason = {
        "lab_verdict": st.get("lab_verdict"),
        "why": st.get("eligibility", {}).get("why"),
        "adversarial_weaknesses": st.get("adversarial_weaknesses"),
        "conditions": {
            "data": "BTCUSDT 1h 2020-01..2025-06 (dev + selection)",
            "costs": "lab cost model",
            "code_sha256": M.code_sha(_source(cid)),
        },
        "reexamine_if": [
            "a new data period becomes available (prospective)",
            "market structure changes (e.g. funding regime)",
            "a new mechanism-level argument addresses the recorded weaknesses",
        ],
    }
    ctx.store.x(
        "UPDATE hypotheses SET status=?, evidence=?, classification=?, updated=? WHERE id=?",
        (hyp_status, json.dumps(reason, default=float), status, now(), hid),
    )
    ctx.store.x("UPDATE candidates SET status=? WHERE id=?", (status, cid))
    key = hashlib.sha256(f"{hid}|{reason['conditions']['code_sha256']}".encode()).hexdigest()[:20]
    ctx.store.mem.put_experiment(
        key, cid, "army-cycle", "", "", {"cycle": ctx.cycle, "hypothesis": hid, "status": status, **reason}
    )
    ctx.store.edge(
        f"candidate:{cid}", "evaluated", f"result:{status}", {"lab_verdict": st.get("lab_verdict"), "cycle": ctx.cycle}
    )
    ctx.store.edge(f"hypothesis:{hid}", "outcome", f"status:{hyp_status}", {"why": reason["why"]})
    return {"hypothesis_id": hid, "candidate_id": cid, "status": status, "hypothesis_status": hyp_status, "risk": rk}


# ============================================================================ REASSESS (F4 barrier)
def reassess(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    from ..forecast.prospective import PROMOTION_MIN_RESOLVED

    arch = [a for a in ctx.results_of("archive") if a.get("status")]
    nov = ctx.results_of("novelty")
    fw = (ctx.results_of("forecast_watch") or [{}])[0]
    tried = {h["signature"].split("|")[0] for h in ctx.store.q("SELECT signature FROM hypotheses") if h["signature"]}
    covered = tried | {h["family"] for h in M.prior_hypotheses()}
    cands = [
        {
            "id": "accumulate-prospective-forecasts",
            "why": f"forecasting promotion needs {PROMOTION_MIN_RESOLVED} resolved prospective forecasts per target (strategies need 180 resolved paper days); 0 exist - the only independent evidence",
            "prior_positive": 0.5,
            "cost_runs": 1,
        },
    ]
    for f in M.IMPLEMENTABLE:
        if f not in covered:
            cands.append(
                {
                    "id": f"investigate-{f}",
                    "why": "implementable family never investigated",
                    "prior_positive": 0.1,
                    "cost_runs": 3,
                }
            )
    for a in arch:
        w = (
            next(
                (
                    s.get("adversarial_weaknesses")
                    for s in ctx.results_of("stats")
                    if s.get("candidate_id") == a["candidate_id"]
                ),
                [],
            )
            or []
        )
        if "regime_split" in w:
            cands.append(
                {
                    "id": f"regime-conditional-{a['candidate_id']}",
                    "why": "effect differs by volatility regime (development)",
                    "prior_positive": 0.15,
                    "cost_runs": 2,
                }
            )
    for c in cands:
        p = c["prior_positive"]
        c["bits"] = 0.0 if p in (0, 1) else -(p * math.log2(p) + (1 - p) * math.log2(1 - p))
        c["bits_per_run"] = round(c["bits"] / c["cost_runs"], 3)
    cands.sort(key=lambda c: -c["bits_per_run"])
    return {
        "cycle_outcomes": [
            {k: a.get(k) for k in ("candidate_id", "hypothesis_id", "status", "hypothesis_status")} for a in arch
        ],
        "duplicates_detected": [n for n in nov if n.get("decision") == "duplicate_mechanism"],
        "infeasible": [n for n in nov if n.get("decision") == "infeasible"],
        "forecast_monitor": {k: fw.get(k) for k in ("resolved", "open", "alerts")},
        "promotions": sum(1 for a in arch if a.get("status") == "validated"),
        "recommendation": cands[0],
        "ranking": cands,
        "note": "F4 recommends only; eligibility is computed by army/policy.py; priors are explicit judgement inputs",
    }


CONTROLS = {
    "invalid_strategy": (
        '"""PLANTED NEGATIVE CONTROL: imports os and reads the environment - must be rejected."""\n'
        "import os\n\nNAME = 'control_invalid'\nPARAMS = {}\nPARAM_GRID = {}\n\n\n"
        "def signal(view, p):\n    return 1.0 if os.environ.get('X') else 0.0\n"
    ),
    "out_of_range": (
        '"""PLANTED NEGATIVE CONTROL: 5x the allowed exposure - must be rejected."""\n'
        "NAME = 'control_leverage'\nPARAMS = {}\nPARAM_GRID = {}\n\n\ndef signal(view, p):\n    return 5.0\n"
    ),
}


def control(ctx: Ctx, t: dict[str, Any]) -> dict[str, Any]:
    """Planted invalid candidates prove the rejection path in every cycle (labelled as controls)."""
    name = t["payload"]["control"]
    src = CONTROLS[name]
    cid = f"control-{name}-{ctx.cycle[-6:]}"
    CAND_DIR.mkdir(parents=True, exist_ok=True)
    (CAND_DIR / f"{cid}.py").write_text(src)
    ctx.store.x(
        "INSERT OR IGNORE INTO candidates (id, parent_id, code_sha256, generator, operator, spec, path, status, created) VALUES (?,?,?,?,?,?,?,?,?)",
        (cid, None, M.code_sha(src), "planted-control", name, "{}", str(CAND_DIR / f"{cid}.py"), "control", now()),
    )
    new_task(ctx.store, ctx.cycle, "test", "D3", "TEST", {"candidate_id": cid, "control": name})
    return {"candidate_id": cid, "control": name, "expected": "rejected by D3"}


HANDLERS = {
    "control": control,
    "forecast_live": forecast_live,
    "forecast_reevaluate": forecast_reevaluate,
    "discover": discover, "verify": verify, "novelty": novelty, "market": market, "forecast_watch": forecast_watch,
    "formulate": formulate, "synthesis": synthesis, "contract": contract, "render": render, "gap_proposal": gap_proposal,
    "test": test, "security": security, "test_proposal": test_proposal, "challenge": challenge, "evaluate": evaluate,
    "stats": stats, "simulate": simulate, "risk": risk, "archive": archive, "reassess": reassess,
}  # fmt: skip


def seed(store: Any, cycle: str, cfg: dict[str, Any]) -> None:
    if cfg.get("workflow") == "quant":  # quantitative / calendar / event discovery workflow (divisions G, H, I)
        from ..quant.workflow import seed as quant_seed

        quant_seed(store, cycle, cfg)
        return
    for r in ("A1", "A2"):
        new_task(store, cycle, "discover", r, "DISCOVER")
    for r in ("B1", "B2", "B3", "B4"):
        new_task(store, cycle, "market", r, "UNDERSTAND")
    live = new_task(store, cycle, "forecast_live", "B1", "UNDERSTAND") if cfg.get("live_forecasts", True) else None
    new_task(store, cycle, "forecast_watch", "F3", "REASSESS", deps=[live] if live else [])
    new_task(store, cycle, "synthesis", "C4", "FORMULATE")
    for ctl in cfg.get("controls", []):
        new_task(store, cycle, "control", "D2", "IMPLEMENT", {"control": ctl})
    new_task(store, cycle, "reassess", "F4", "REASSESS", barrier=True)


from ..quant.workflow import QUANT_HANDLERS  # noqa: E402  (registered after the core handlers)

HANDLERS.update(QUANT_HANDLERS)
