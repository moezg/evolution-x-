"""Research Army Control Center API. Reads the durable army store; controls write human decisions to army_control.

No endpoint can place an order, change a frozen policy, merge code or alter a recorded result.
"""

from __future__ import annotations

import threading
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/army")
_run_lock = threading.Lock()
_last_run: dict[str, Any] = {}


def _store():  # noqa: ANN202
    from ..army.store import Store

    return Store()


@router.get("/roles")
def roles() -> dict[str, Any]:
    from ..army.roles import as_dicts

    s = _store()
    cyc = s.q("SELECT id FROM army_cycles ORDER BY created DESC LIMIT 1")
    cid = cyc[0]["id"] if cyc else None
    tasks = (
        s.q(
            "SELECT id, role, kind, status, error, deps, wall_s, llm_calls, updated FROM army_tasks WHERE cycle_id=?",
            (cid,),
        )
        if cid
        else []
    )
    usage = {u["role"]: u for u in s.usage(cid)} if cid else {}
    status = {t["id"]: t["status"] for t in tasks}
    out = []
    for r in as_dicts():
        mine = [t for t in tasks if t["role"] == r["id"]]
        blockers = [
            {"task": t["id"], "waiting_for": [d for d in (t["deps"] or {}).get("deps", []) if status.get(d) != "done"]}
            for t in mine
            if t["status"] == "pending"
        ]
        out.append(
            {
                **r,
                "tasks": {st: sum(t["status"] == st for t in mine) for st in {t["status"] for t in mine}},
                "activity": next((t["kind"] for t in mine if t["status"] == "running"), "idle"),
                "last_task": max(mine, key=lambda t: t["updated"])["kind"] if mine else None,
                "blockers": blockers,
                "errors": [t["error"] for t in mine if t["error"]][:3],
                "usage": usage.get(r["id"], {"llm_calls": 0, "llm_cost_usd": 0.0, "wall_s": 0.0, "ext_requests": 0}),
            }
        )
    return {"cycle": cid, "roles": out, "simulated_market_participants": "256 (separate; not research agents)"}


@router.get("/cycles")
def cycles() -> list[dict[str, Any]]:
    return _store().q("SELECT * FROM army_cycles ORDER BY created DESC")


@router.get("/cycle/{cid}")
def cycle(cid: str) -> dict[str, Any]:
    s = _store()
    c = s.q("SELECT * FROM army_cycles WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "unknown cycle")
    tasks = s.q("SELECT * FROM army_tasks WHERE cycle_id=? ORDER BY created", (cid,))
    return {"cycle": c[0], "tasks": tasks, "usage": s.usage(cid)}


@router.get("/sources")
def sources() -> list[dict[str, Any]]:
    return _store().q("SELECT * FROM army_sources ORDER BY retrieved DESC")


@router.get("/memory")
def memory() -> dict[str, Any]:
    from ..army.mechanisms import prior_hypotheses

    s = _store()
    prior = prior_hypotheses()
    by_family: dict[str, int] = {}
    for h in prior:
        by_family[h["family"]] = by_family.get(h["family"], 0) + 1
    return {
        "hypotheses": s.q("SELECT * FROM hypotheses ORDER BY updated DESC"),
        "candidates": s.q("SELECT * FROM candidates ORDER BY created DESC"),
        "experiments": s.q("SELECT key, candidate_id, stage, result, created FROM experiments ORDER BY created DESC"),
        "earlier_labs": {"hypotheses": len(prior), "by_family": by_family},
    }


@router.get("/graph")
def graph(node: str | None = None) -> list[dict[str, Any]]:
    return _store().edges(node)


@router.get("/lineage/{hid}")
def lineage(hid: str) -> dict[str, Any]:
    s = _store()
    h = s.q("SELECT * FROM hypotheses WHERE id=?", (hid,))
    if not h:
        raise HTTPException(404, "unknown hypothesis")
    hyp = h[0]
    cid = hyp.get("candidate_id")
    steps = []
    for t in s.q("SELECT * FROM army_tasks ORDER BY created"):
        p, r = t["payload"] or {}, t["result"] or {}
        if (
            p.get("hypothesis_id") == hid
            or (cid and p.get("candidate_id") == cid)
            or r.get("hypothesis_id") == hid
            or (p.get("hypothesis") or {}).get("id") == hid
        ):
            steps.append(
                {
                    k: t[k]
                    for k in (
                        "id",
                        "stage",
                        "role",
                        "kind",
                        "status",
                        "error",
                        "result",
                        "wall_s",
                        "llm_calls",
                        "updated",
                    )
                }
            )
    src_id = (hyp.get("evidence") or {}).get("source") or next(
        (x["result"].get("hypothesis", {}).get("source_id") for x in steps if x["kind"] == "formulate" and x["result"]),
        None,
    )
    src = s.q("SELECT * FROM army_sources WHERE id=?", (src_id,)) if src_id else []
    pre = [
        t
        for t in s.q("SELECT * FROM army_tasks WHERE kind IN ('verify','novelty') ORDER BY created")
        if (t["payload"] or {}).get("source_id") == src_id
    ]
    return {
        "hypothesis": hyp,
        "source": src[0] if src else None,
        "source_steps": pre,
        "steps": steps,
        "edges": _dedup(
            s.edges(f"hypothesis:{hid}")
            + (s.edges(f"candidate:{cid}") if cid else [])
            + (s.edges(f"source:{src_id}") if src_id else [])
        ),
    }


def _dedup(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for e in edges:
        k = (e["src"], e["rel"], e["dst"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


@router.get("/proposals")
def proposals() -> list[dict[str, Any]]:
    from ..army.codeprop import proposals as P

    return P()


@router.get("/forecast")
def forecast() -> dict[str, Any]:
    from ..army.drift import check

    return check()


@router.get("/journal")
def journal(limit: int = 200) -> dict[str, Any]:
    s = _store()
    return {"verify": s.journal.verify(), "entries": s.journal.tail(limit)}


@router.get("/control")
def control_state() -> dict[str, Any]:
    from ..army.policy import policy

    s = _store()
    pol = policy()
    return {
        "state": s.control("state", "running"),
        "llm_enabled": s.control("llm_enabled", True),
        "source_arxiv_enabled": s.control("source_arxiv_enabled", True),
        "llm_calls_per_cycle": s.control("llm_calls_per_cycle", pol["budgets"]["llm_calls_per_cycle"]),
        "policy_llm_calls_per_cycle_max": pol["budgets"]["llm_calls_per_cycle"],
        "sources": pol["sources"],
        "last_run": _last_run,
        "running": _run_lock.locked(),
        "schedule_every_hours": s.control("schedule_every_hours", pol["orchestration"]["schedule_every_hours"]),
    }


class ControlIn(BaseModel):
    action: Literal["start", "pause", "stop", "set", "run_cycle"]
    key: Literal["llm_enabled", "source_arxiv_enabled", "llm_calls_per_cycle", "schedule_every_hours"] | None = None
    value: Any = None


@router.post("/control")
def control(body: ControlIn) -> dict[str, Any]:
    from ..army.policy import policy

    s = _store()
    if body.action in ("start", "pause", "stop"):
        s.set_control("state", {"start": "running", "pause": "paused", "stop": "stopped"}[body.action], "dashboard")
    elif body.action == "set":
        if body.key is None:
            raise HTTPException(400, "key required")
        v = body.value
        if body.key == "llm_calls_per_cycle":
            v = max(0, min(int(v), policy()["budgets"]["llm_calls_per_cycle"]))  # can only lower the frozen cap
        s.set_control(body.key, v, "dashboard")
    elif body.action == "run_cycle":
        if _run_lock.locked():
            raise HTTPException(409, "a cycle is already running")

        def job() -> None:
            with _run_lock:
                from ..army.cli import run

                _last_run.update({"started": True})
                try:
                    _last_run.update(run("tick"))
                except Exception as e:  # noqa: BLE001
                    _last_run.update({"error": str(e)[:300]})

        threading.Thread(target=job, daemon=True).start()
    return control_state()
