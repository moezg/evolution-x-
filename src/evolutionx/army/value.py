"""P7: measured value of each research role (cost vs recorded contributions) + one controlled with/without comparison.

Only persisted records are used (army_tasks, army_usage, stat_tests, specialist artifacts). A contribution is
counted only when it is recorded as an outcome (a source verified, a duplicate stopped, an invalid candidate rejected,
a hard failure found, a registered test, a supported finding). Roles with cost and no recorded contribution are
FLAGGED for a human decision; nothing is disabled automatically, and agent count is never a goal.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .roles import ROLES
from .store import Store

OUT = Path("artifacts/army/agent_value.json")


def _contributions(s: Store) -> dict[str, dict[str, int]]:
    c: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in s.q("SELECT role, kind, status, result FROM army_tasks"):
        r = t["result"] if isinstance(t["result"], dict) else {}
        role, kind = t["role"], t["kind"]
        if kind == "discover":
            ns, sel = r.get("new_sources", 0), r.get("selected_for_verification", 0)
            c[role]["new_sources_found"] += len(ns) if isinstance(ns, list) else int(ns or 0)
            c[role]["sources_sent_to_verification"] += len(sel) if isinstance(sel, list) else int(sel or 0)
        elif kind == "verify" and r.get("record_refetched"):
            c[role]["sources_verified"] += 1
            c[role]["crossref_matched"] += int(bool((r.get("crossref") or {}).get("matched")))
        elif kind == "novelty":
            if r.get("decision") == "duplicate_mechanism":
                c[role]["duplicates_stopped"] += 1
            elif r.get("decision") == "novel":
                c[role]["novel_ideas_passed"] += 1
        elif kind == "test" and t["status"] == "rejected":
            c[role]["invalid_candidates_rejected"] += 1
        elif kind == "challenge":
            c[role]["hard_failures_found"] += sum(
                1 for v in (r.get("tests") or {}).values() if isinstance(v, dict) and v.get("hard_failure")
            )
            c[role]["candidates_challenged"] += 1
        elif kind == "evaluate" and r.get("verdict"):
            c[role][f"candidates_{r['verdict']}"] += 1
        elif kind == "formulate":
            c[role]["hypotheses_formulated"] += 1
    for r in s.q("SELECT role, status, COUNT(*) n FROM stat_tests GROUP BY role, status"):
        c[r["role"]]["registered_tests"] += r["n"]
        if r["status"] == "supported":
            c[r["role"]]["supported_test_rows"] += r["n"]
    for p in Path("artifacts/army/specialists").glob("*.json"):
        d = json.loads(p.read_text())
        for prop in d.get("proposals", []):
            if prop["by"].startswith("G1"):
                c["G1"][f"specialist_proposals_{prop['validation']['status']}"] += 1
        for st in d.get("steps", []):
            if st.get("role") == "A1" and (st.get("validation") or {}).get("valid"):
                c["A1"]["specialist_claims_verified"] += 1
            if st.get("role") == "E3" and st.get("critique"):
                c["E3"]["specialist_critiques"] += 1
    return {k: dict(v) for k, v in c.items()}


def dedup_counterfactual(s: Store) -> dict[str, Any]:
    """Controlled with/without comparison for A4 (novelty/dedup), on the recorded cycles.

    WITH A4: duplicates stop at the novelty gate (measured). WITHOUT A4: the same sources continue down the
    identical pipeline; their cost is the MEASURED mean cost of the downstream chain for the candidates that did
    continue (formulate -> render/contract/test/security -> evaluate -> stats -> challenge), and each adds one
    counted validation trial (which tightens the deflated-Sharpe hurdle for every other candidate)."""
    dup = s.q("SELECT COUNT(*) n FROM army_tasks WHERE kind='novelty' AND result LIKE '%duplicate_mechanism%'")[0]["n"]
    chain = ("formulate", "render", "contract", "test", "security", "evaluate", "stats", "challenge")
    rows = s.q(
        f"SELECT kind, AVG(wall_s) w, COUNT(*) n FROM army_tasks WHERE status IN ('done','rejected') AND kind IN ({','.join('?' * len(chain))}) AND role NOT LIKE 'control%' GROUP BY kind",  # noqa: S608  # nosec B608 - fixed list
        chain,
    )
    per_candidate = sum(r["w"] or 0 for r in rows)
    llm = s.q("SELECT COALESCE(SUM(llm_cost_usd),0) c, COALESCE(SUM(llm_calls),0) n FROM army_usage WHERE role IN ('C1','C2','C3','E3')")[0]  # fmt: skip
    evaluated = s.q("SELECT COUNT(*) n FROM army_tasks WHERE kind='evaluate'")[0]["n"] or 1
    return {
        "duplicates_stopped_with_A4": dup,
        "with_A4": {"downstream_wall_s": 0.0, "extra_validation_trials": 0, "extra_llm_calls": 0},
        "without_A4_estimate": {
            "downstream_wall_s": round(dup * per_candidate, 1),
            "extra_validation_trials": dup,
            "extra_llm_calls_upper_bound": dup * 2,
            "extra_llm_usd_at_measured_mean": round(dup * float(llm["c"]) / evaluated, 3),
        },
        "A4_cost_measured_wall_s": s.q("SELECT COALESCE(SUM(wall_s),0) w FROM army_tasks WHERE role='A4'")[0]["w"],
        "measured_chain_wall_s_per_candidate": round(per_candidate, 2),
        "label": "replay estimate from measured per-stage costs on the recorded cycles (the pipeline was not re-run without A4)",
    }


def report(store: Store | None = None) -> dict[str, Any]:
    s = store or Store()
    usage = {
        r["role"]: r
        for r in s.q(
            "SELECT role, SUM(llm_calls) llm_calls, ROUND(SUM(llm_cost_usd),4) usd, ROUND(SUM(wall_s),1) wall_s, SUM(ext_requests) ext FROM army_usage GROUP BY role"
        )  # fmt: skip
    }
    tasks = {r["role"]: r for r in s.q("SELECT role, COUNT(*) tasks, SUM(status='done') done, SUM(status='failed') failed FROM army_tasks GROUP BY role")}  # fmt: skip
    contrib = _contributions(s)
    roles = []
    for r in ROLES:
        u, t, c = usage.get(r.id, {}), tasks.get(r.id, {}), contrib.get(r.id, {})
        cost = (u.get("wall_s") or 0) + 60 * (u.get("llm_calls") or 0)
        benefit = sum(v for k, v in c.items() if k not in ("novel_ideas_passed", "candidates_challenged"))
        roles.append(
            {
                "role": r.id,
                "title": r.title,
                "impl": r.impl,
                "tasks": t.get("tasks", 0),
                "failed": t.get("failed", 0),
                "llm_calls": u.get("llm_calls") or 0,
                "llm_usd_api_equiv": u.get("usd") or 0.0,
                "wall_s": u.get("wall_s") or 0.0,
                "external_requests": u.get("ext") or 0,
                "contributions": c,
                "flag": "cost without recorded contribution - human review"
                if cost > 5 and benefit == 0
                else ("no activity" if not t else None),
            }
        )
    out = {
        "roles": roles,
        "flagged": [r["role"] for r in roles if r["flag"] and r["flag"].startswith("cost")],
        "dedup_with_without": dedup_counterfactual(s),
        "policy": "flags are recommendations; disabling a role is a human control (army set). Agent count is not a goal.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=str))
    return out
