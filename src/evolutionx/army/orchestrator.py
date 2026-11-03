"""Durable, restartable research-cycle orchestrator (role F1). Deterministic; no LLM decides scheduling.

* Typed task contracts in army_tasks: id, stage, role, kind, deps, payload, status, attempts, lease, result.
* Ready = all deps 'done'. Dispatch to a bounded thread pool (policy max_concurrency); kinds in SERIAL run alone.
* Failures retry up to max_attempts; a task whose dependency failed / was rejected is 'skipped' with a reason.
* Barrier tasks (REASSESS) run when every other task of the cycle is terminal.
* Crash recovery: tasks left 'running' (expired lease) return to 'pending' on the next run.
* Human control (army_control): state = running | paused | stopped; budgets; source switches.
* Scheduling: `tick()` is idempotent and meant to be called by cron / a scheduled task - there is no infinite loop.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from ..research.memory import now
from .policy import policy, policy_sha
from .store import Store

TERMINAL = {"done", "failed", "skipped", "cancelled", "rejected"}
# the research lab is a single-writer store; novelty/formulate must see each other's hypotheses (no duplicate LLM work)
SERIAL = {"evaluate", "novelty", "formulate"}


class Ctx:
    def __init__(self, store: Store, cycle: str, config: dict[str, Any]) -> None:
        from .llm import LLM

        self.store, self.cycle, self.config = store, cycle, config
        self.llm = LLM(store, cycle)

    def task_result(self, tid: str) -> dict[str, Any]:
        r = self.store.q("SELECT result FROM army_tasks WHERE id=?", (tid,))
        return (r[0]["result"] or {}) if r else {}

    def results_of(self, kind: str) -> list[dict[str, Any]]:
        rows = self.store.q("SELECT id, result, status FROM army_tasks WHERE cycle_id=? AND kind=?", (self.cycle, kind))
        return [{"id": r["id"], "status": r["status"], **(r["result"] or {})} for r in rows]


Handler = Callable[[Ctx, dict[str, Any]], dict[str, Any]]


def new_task(
    store: Store,
    cycle: str,
    kind: str,
    role: str,
    stage: str,
    payload: dict[str, Any] | None = None,
    deps: list[str] | None = None,
    barrier: bool = False,
) -> str:
    tid = f"{cycle}:{kind}:{uuid.uuid4().hex[:6]}"
    store.x(
        "INSERT INTO army_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            tid, cycle, stage, role, kind, "pending", 0, policy()["orchestration"]["task_max_attempts"],
            json.dumps({"deps": deps or [], "barrier": barrier}), json.dumps(payload or {}), None, None, None,
            now(), now(), 0.0, 0,
        ),
    )  # fmt: skip
    return tid


def create_cycle(store: Store, config: dict[str, Any], seed_tasks: Callable[[Store, str, dict[str, Any]], None]) -> str:
    cid = "c" + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S") + uuid.uuid4().hex[:4]
    cfg = {**config, "policy_sha256": policy_sha()}
    store.x("INSERT INTO army_cycles VALUES (?,?,?,?,?,?)", (cid, "running", json.dumps(cfg), now(), now(), None))
    store.log("F1", "cycle_created", {"cycle": cid, "config": cfg})
    seed_tasks(store, cid, cfg)
    return cid


def _tasks(store: Store, cycle: str) -> list[dict[str, Any]]:
    return store.q("SELECT * FROM army_tasks WHERE cycle_id=? ORDER BY created, id", (cycle,))


def _set(store: Store, tid: str, **kw: Any) -> None:
    allowed = {"status", "attempts", "lease_until", "result", "error", "wall_s", "llm_calls"}
    if set(kw) - allowed:
        raise ValueError(f"not an updatable task column: {sorted(set(kw) - allowed)}")
    cols = ", ".join(f"{k}=?" for k in kw) + ", updated=?"
    vals = [json.dumps(v, default=str) if isinstance(v, dict | list) else v for v in kw.values()]
    store.x(f"UPDATE army_tasks SET {cols} WHERE id=?", (*vals, now(), tid))  # noqa: S608  # nosec B608 - allow-listed columns


def recover(store: Store, cycle: str) -> int:
    n = 0
    for t in _tasks(store, cycle):
        if t["status"] == "running" and (t["lease_until"] or 0) < time.time():
            _set(store, t["id"], status="pending", error="recovered after interruption")
            n += 1
    if n:
        store.log("F1", "recovered_tasks", {"cycle": cycle, "n": n})
    return n


def run_cycle(store: Store, cycle: str, handlers: dict[str, Handler], max_wall_s: float = 3600) -> dict[str, Any]:
    pol = policy()["orchestration"]
    cfg = store.q("SELECT config FROM army_cycles WHERE id=?", (cycle,))[0]["config"] or {}  # Memory.q parses JSON
    ctx = Ctx(store, cycle, cfg)
    recover(store, cycle)
    store.x("UPDATE army_cycles SET status='running', updated=? WHERE id=?", (now(), cycle))
    t0 = time.time()
    running: dict[Future, dict[str, Any]] = {}
    with ThreadPoolExecutor(pol["max_concurrency"]) as pool:
        while True:
            state = store.control("state", "running")
            if state == "stopped":
                for t in _tasks(store, cycle):
                    if t["status"] == "pending":
                        _set(store, t["id"], status="cancelled", error="stopped by human control")
            if state in ("paused", "stopped") and not running:
                store.x("UPDATE army_cycles SET status=?, updated=? WHERE id=?", (state, now(), cycle))
                store.log("F1", f"cycle_{state}", {"cycle": cycle})
                return {"cycle": cycle, "status": state}
            tasks = _tasks(store, cycle)
            status = {t["id"]: t["status"] for t in tasks}
            # propagate failures to dependents
            for t in tasks:
                if t["status"] == "pending":
                    deps = (t["deps"] or {}).get("deps", [])
                    bad = [d for d in deps if status.get(d) in {"failed", "skipped", "cancelled", "rejected"}]
                    if bad:
                        _set(store, t["id"], status="skipped", error=f"dependency not done: {bad}")
                        status[t["id"]] = "skipped"
            busy_serial = any(r["kind"] in SERIAL for r in running.values())
            ready = []
            if state == "running" and time.time() - t0 < max_wall_s:
                others_open = [
                    t for t in tasks if status[t["id"]] not in TERMINAL and not (t["deps"] or {}).get("barrier")
                ]
                for t in tasks:
                    if status[t["id"]] != "pending" or any(t["id"] == r["id"] for r in running.values()):
                        continue
                    meta = t["deps"] or {}
                    if meta.get("barrier"):
                        if not others_open and not running:
                            ready.append(t)
                        continue
                    if all(status.get(d) == "done" for d in meta.get("deps", [])):
                        if t["kind"] in SERIAL and (busy_serial or any(r["kind"] in SERIAL for r in ready)):
                            continue
                        ready.append(t)
            for t in ready[: max(0, pol["max_concurrency"] - len(running))]:
                _set(
                    store,
                    t["id"],
                    status="running",
                    attempts=t["attempts"] + 1,
                    lease_until=time.time() + pol["task_lease_s"],
                )
                running[pool.submit(_execute, ctx, handlers, t)] = t
            if not running:
                open_ = [t for t in _tasks(store, cycle) if t["status"] not in TERMINAL]
                if not open_ or time.time() - t0 >= max_wall_s:
                    break
                time.sleep(0.2)
                continue
            done, _ = wait(list(running), timeout=1.0, return_when=FIRST_COMPLETED)
            for f in done:
                t = running.pop(f)
                f.result()  # _execute never raises; it records the outcome itself
    tasks = _tasks(store, cycle)
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    final = "completed" if all(t["status"] in TERMINAL for t in tasks) else "incomplete"
    summary = {"counts": counts, "usage": store.usage(cycle), "wall_s": round(time.time() - t0, 1)}
    store.x(
        "UPDATE army_cycles SET status=?, updated=?, summary=? WHERE id=?",
        (final, now(), json.dumps(summary, default=str), cycle),
    )
    store.log("F1", "cycle_finished", {"cycle": cycle, "status": final, **summary})
    return {"cycle": cycle, "status": final, **summary}


def _execute(ctx: Ctx, handlers: dict[str, Handler], t: dict[str, Any]) -> None:
    store = ctx.store
    t0 = time.time()
    before = sum(r["llm_calls"] for r in store.usage(ctx.cycle))
    try:
        out = handlers[t["kind"]](ctx, {**t, "payload": t["payload"] or {}})
        status = out.pop("_status", "done")
        wall = time.time() - t0
        after = sum(r["llm_calls"] for r in store.usage(ctx.cycle))
        _set(
            store,
            t["id"],
            status=status,
            result=out,
            error=None,
            wall_s=wall,
            llm_calls=after - before,
            lease_until=None,
        )
        store.add_usage(ctx.cycle, t["role"], wall=wall)
        store.log(t["role"], f"task_{status}", {"task": t["id"], "kind": t["kind"], "wall_s": round(wall, 2)})
    except Exception as e:  # noqa: BLE001 - every failure is recorded and retried by policy
        wall = time.time() - t0
        st = "pending" if t["attempts"] < t["max_attempts"] else "failed"
        _set(store, t["id"], status=st, error=f"{type(e).__name__}: {e}"[:600], wall_s=wall, lease_until=None)
        store.add_usage(ctx.cycle, t["role"], wall=wall)
        store.log(
            t["role"],
            "task_error",
            {
                "task": t["id"],
                "error": str(e)[:300],
                "will_retry": st == "pending",
                "trace": traceback.format_exc()[-800:],
            },
        )


def tick(
    store: Store,
    handlers: dict[str, Handler],
    seed_tasks: Callable[[Store, str, dict[str, Any]], None],
    config: dict[str, Any],
    force_new: bool = False,
) -> dict[str, Any]:
    """Idempotent scheduler entry point: resume an unfinished cycle, else start one when the schedule is due."""
    if store.control("state", "running") != "running":
        return {"action": "none", "reason": f"state={store.control('state')}"}
    open_c = store.q(
        "SELECT id FROM army_cycles WHERE status IN ('running','paused','incomplete') ORDER BY created DESC"
    )
    if open_c:
        return {"action": "resumed", **run_cycle(store, open_c[0]["id"], handlers)}
    last = store.q("SELECT created FROM army_cycles ORDER BY created DESC LIMIT 1")
    every = float(store.control("schedule_every_hours", policy()["orchestration"]["schedule_every_hours"]))
    if last and not force_new:
        age_h = (dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(last[0]["created"])).total_seconds() / 3600
        if age_h < every:
            return {"action": "none", "reason": f"next cycle due in {every - age_h:.1f} h"}
    cid = create_cycle(store, config, seed_tasks)
    return {"action": "started", **run_cycle(store, cid, handlers)}
