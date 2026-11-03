"""Council orchestration with LangGraph (supervisor + fan-out/fan-in workflow).

Why LangGraph: provider-agnostic (works with any adapter behind our LLM port,
including the offline mock), explicit deterministic graphs, parallel fan-out,
and first-class human-in-the-loop interrupts for later phases.

Graph:  observe -> research_scientist -> {microstructure, behavioral, macro, risk}
        -> adversarial -> evaluation -> evolution_engineer -> synthesis

The council receives a read-only context and returns validated documents. It
has no reference to the simulation, exchange or file system.
"""

from __future__ import annotations

import json
import operator
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ..evolution.archive import Archive, now
from ..sim.scenarios import SCENARIOS
from .llm import LLMClient, MockLLM, make_provider, render_user
from .roles import COMMON, PROMPTS_V1, ROLE_TITLES, RULES
from .schemas import RoleReport

COUNCIL_DIR = Path("artifacts/council")


class CouncilState(TypedDict):
    context: dict[str, Any]
    reports: Annotated[list[dict[str, Any]], operator.add]


def build_context(question: str, experiment_id: str | None, live_sim: Any, archive: Archive) -> dict[str, Any]:
    """OBSERVE: assemble a read-only, JSON-only view of results."""
    from ..api import views
    from ..evaluation.metrics import run_metrics
    from ..evaluation.reference import historical_bands, window_facts
    from ..evaluation.stylized import realism_score
    from ..experiments import EXP_DIR
    from ..sim.config import SimConfig
    from ..sim.simulation import Simulation

    sim = live_sim.sim if live_sim is not None and live_sim.sim is not None and len(live_sim.sim.series) > 600 else None
    if sim is not None:
        with live_sim.lock:
            m, col, st = run_metrics(sim), views.collective(sim), views.state(sim, live_sim.status, live_sim.speed)
        source = "live simulation"
    else:
        sim = Simulation(SimConfig(seed=2024, duration_s=1800)).run()
        m, col, st = run_metrics(sim), views.collective(sim), views.state(sim, "finished", 0)
        source = "fresh reference run seed=2024, 1800s"
    bands = historical_bands()
    if bands:
        m["realism"] = realism_score(m["facts"], bands)
    m["gap"] = m.get("cross_venue_gap_bps")
    hist = window_facts("train")
    exp = None
    exps = sorted(EXP_DIR.glob("*/report.json"), key=lambda p: p.stat().st_mtime)
    if experiment_id:
        p = EXP_DIR / experiment_id / "report.json"
        exp = json.loads(p.read_text()) if p.exists() else None
    elif exps:
        exp = json.loads(exps[-1].read_text())
    if exp:
        exp = {k: exp[k] for k in ("experiment_id", "scenario", "replicates", "summary", "n_agents", "duration_s")}
        for v in exp["summary"].values():
            v.pop("treatment_values", None)
            v.pop("baseline_values", None)
    ch = archive.challenges()
    return {
        "question": question,
        "source": source,
        "data_label": "synthetic",
        "market": m,
        "collective": {k: col[k] for k in ("panic_events", "mm_withdrawals", "imitation_events", "stance_by_kind")}
        | {"gini": col["wealth"]["gini"]},
        "state": {k: st[k] for k in ("insurance_fund_usd", "liquidations", "n_agents", "t_ms")},
        "experiment": exp,
        "experiments_run": sorted({json.loads(p.read_text())["scenario"] for p in exps}),
        "scenarios": list(SCENARIOS),
        "historical_ret_std_bps": sum(f["ret_std_bps"] for f in hist) / len(hist) if hist else None,
        "evolution": {"n_challenges": len(ch), "n_promoted": sum(1 for c in ch if c["decision"] == "promoted")},
    }


def _grounding(report: dict[str, Any], ctx: dict[str, Any]) -> float:
    """Fraction of cited evidence keys that resolve to something in the context (prompt-quality metric)."""
    keys = [e for c in report["observations"] for e in c["evidence"]]
    if not keys:
        return 0.0

    def resolves(k: str) -> bool:
        cur: Any = ctx
        for part in k.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return part == k.split(".")[-1] and isinstance(cur, dict)  # tolerate dotted metric names
        return True

    return sum(resolves(k) for k in keys) / len(keys)


def _role_node(role: str, client: LLMClient, progress: Callable[[str], None]) -> Callable[[CouncilState], dict]:
    system = PROMPTS_V1[role] + COMMON

    def node(state: CouncilState) -> dict[str, Any]:
        progress(f"{ROLE_TITLES[role]} thinking")
        ctx = {"_rule": role, **state["context"], "peer_reports": [r["role"] for r in state["reports"]]}
        rep = client.json(
            system,
            render_user(f"Role: {ROLE_TITLES[role]}. Question: {ctx['question']}", ctx),
            RoleReport.model_validate,
        )
        d = rep.model_dump()
        return {
            "reports": [
                {
                    "role": role,
                    "title": ROLE_TITLES[role],
                    "prompt_version": 1,
                    "output": d,
                    "grounding": _grounding(d, state["context"]),
                }
            ]
        }

    return node


def build_graph(client: LLMClient, progress: Callable[[str], None]):  # noqa: ANN201
    g = StateGraph(CouncilState)
    for role in RULES:
        g.add_node(role, _role_node(role, client, progress))
    parallel = ["microstructure_analyst", "behavioral_scientist", "macro_scenario_designer", "risk_researcher"]
    g.add_edge(START, "research_scientist")
    for r in parallel:
        g.add_edge("research_scientist", r)
        g.add_edge(r, "adversarial_researcher")
    g.add_edge("adversarial_researcher", "evaluation_scientist")
    g.add_edge("evaluation_scientist", "evolution_engineer")
    g.add_edge("evolution_engineer", END)
    return g.compile()


def synthesize(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Supervisor synthesis: merge recommendations, keep conclusions that survived the adversarial pass."""
    recs: dict[str, dict[str, Any]] = {}
    for r in reports:
        for e in r["output"]["recommended_experiments"]:
            cur = recs.setdefault(e["scenario"], {"scenario": e["scenario"], "replicates": 0, "votes": 0, "why": []})
            cur["votes"] += 1
            cur["replicates"] = max(cur["replicates"], e["replicates"])
            cur["why"].append(f"{r['title']}: {e['rationale']}")
    challenged = [
        o["text"] for r in reports if r["role"] == "adversarial_researcher" for o in r["output"]["observations"]
    ]
    return {
        "prioritised_experiments": sorted(recs.values(), key=lambda x: (-x["votes"], x["scenario"])),
        "open_challenges": challenged,
        "conclusions": [{"role": r["title"], "text": c["text"]} for r in reports for c in r["output"]["conclusions"]],
        "hypotheses_to_test": [
            {"role": r["title"], "text": h["text"]} for r in reports for h in r["output"]["hypotheses"]
        ],
        "mean_grounding": sum(r["grounding"] for r in reports) / max(1, len(reports)),
    }


def run_council(
    question: str,
    experiment_id: str | None = None,
    live_sim: Any = None,
    archive: Archive | None = None,
    progress: Callable[[str], None] = lambda _m: None,
) -> dict[str, Any]:
    A = archive or Archive()
    provider = make_provider()
    if isinstance(provider, MockLLM):
        provider.rules.update(RULES)
    client = LLMClient(provider, use_cache=not isinstance(provider, MockLLM))
    progress("observing (building read-only context)")
    ctx = build_context(question, experiment_id, live_sim, A)
    graph = build_graph(client, progress)
    final = graph.invoke({"context": ctx, "reports": []})
    order = list(RULES)
    reports = sorted(final["reports"], key=lambda r: order.index(r["role"]))
    rid = f"council-{now().replace(':', '').replace('-', '')}"
    doc = {
        "id": rid,
        "created": now(),
        "question": question,
        "context_source": ctx["source"],
        "experiment_id": (ctx.get("experiment") or {}).get("experiment_id"),
        "llm": {
            "provider": provider.name,
            "model": provider.model,
            "calls": client.budget.calls,
            "cache_hits": client.budget.cache_hits,
            "budget": client.budget.max_calls,
        },
        "orchestration": "langgraph: research_scientist -> 4 parallel specialists -> adversarial -> evaluation -> "
        "evolution_engineer -> supervisor synthesis",
        "roles": reports,
        "synthesis": synthesize(reports),
        "validated": True,
    }
    COUNCIL_DIR.mkdir(parents=True, exist_ok=True)
    (COUNCIL_DIR / f"{rid}.json").write_text(json.dumps(doc, indent=2, default=str))
    A.audit("council", "council_report", rid, {"provider": provider.name, "calls": client.budget.calls})
    for role, text in PROMPTS_V1.items():
        A.execute(
            "INSERT OR IGNORE INTO prompts VALUES (?,?,?,?,?,?,?)", (role, 1, text + COMMON, None, 1, now(), None)
        )
    for r in reports:  # Level-3: accumulate per-prompt-version evaluation evidence
        A.execute(
            "UPDATE prompts SET score = COALESCE((score + ?) / 2, ?) WHERE role=? AND version=?",
            (r["grounding"], r["grounding"], r["role"], 1),
        )
    return doc
