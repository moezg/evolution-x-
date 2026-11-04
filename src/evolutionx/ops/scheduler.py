"""Durable scheduler for continuous operation (cron `evox ops tick` or `evox ops daemon` on an always-on host).

Design
* Every job has a SLOT (UTC string) per period; a run is keyed by (job, slot) in artifacts/ops/ops.db, so a slot is
  executed once even if ticks overlap, crash or repeat (idempotent).
* One tick at a time per host: non-blocking flock on artifacts/ops/scheduler.lock.
* A run left 'running' by a killed process is re-tried after its lease expires (restart recovery).
* Failures retry with exponential backoff; after max_attempts the run fails and a notification is recorded
  (and POSTed to $EVOX_NOTIFY_WEBHOOK when set).
* CRITICAL jobs (data fetch, forecast issuance, missed-window recording, resolution, drift) run first and never
  depend on the research army; OPTIONAL research jobs run only when the army is not paused and the daily research
  budget is not exhausted. Budget exhaustion pauses optional research only.
* All times are UTC; event times are converted from their official time zone when registered.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import socket
import sqlite3
import sys
import time
import traceback
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path("artifacts/ops")
DAY_MS = 86_400_000
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (job TEXT, slot TEXT, critical INTEGER, status TEXT, attempts INTEGER,
  next_attempt_utc TEXT, lease_until REAL, started_utc TEXT, finished_utc TEXT, error TEXT, result TEXT, host TEXT,
  pid INTEGER, PRIMARY KEY (job, slot));
CREATE TABLE IF NOT EXISTS sources (name TEXT PRIMARY KEY, last_ok_utc TEXT, last_error_utc TEXT, last_error TEXT,
  consecutive_failures INTEGER, state TEXT);
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, job TEXT,
  message TEXT, delivered TEXT);
CREATE TABLE IF NOT EXISTS budgets (day TEXT PRIMARY KEY, research_wall_s REAL, research_llm_calls INTEGER);
CREATE TABLE IF NOT EXISTS heartbeat (key TEXT PRIMARY KEY, value TEXT);
"""
DEFAULTS = {
    "research_daily_wall_s": 1800.0,
    "research_daily_llm_calls": 3,  # frozen policy: <= 3 LLM calls per cycle
    "lease_s": 1800,
    "backoff_s": 60.0,
    "pending_wait_s": 600.0,
}


def utc(now: dt.datetime | None = None) -> dt.datetime:
    return (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).isoformat(timespec="seconds")


class OpsDB:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "ops.db"
        with self.c() as c:
            c.executescript(SCHEMA)
            if "owner" not in {r[1] for r in c.execute("PRAGMA table_info(runs)")}:
                c.execute("ALTER TABLE runs ADD COLUMN owner TEXT")  # lock domain of the process that ran it

    def c(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self.c() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def x(self, sql: str, args: tuple = ()) -> None:
        with self.c() as c:
            c.execute(sql, args)

    def notify(self, level: str, job: str, message: str) -> None:
        delivered = "stored"
        hook = os.environ.get("EVOX_NOTIFY_WEBHOOK")
        if hook:
            try:
                import httpx

                httpx.post(hook, json={"level": level, "job": job, "message": message}, timeout=10)
                delivered = "webhook"
            except Exception as e:  # noqa: BLE001 - notification failure must not break operations
                delivered = f"webhook_failed: {e}"[:200]
        print(f"[evox-ops] {level.upper()} {job}: {message}", file=sys.stderr)
        self.x(
            "INSERT INTO notifications (ts, level, job, message, delivered) VALUES (?,?,?,?,?)",
            (iso(utc()), level, job, message[:2000], delivered),
        )

    def source_ok(self, name: str) -> None:
        self.x(
            "INSERT OR REPLACE INTO sources VALUES (?,?,COALESCE((SELECT last_error_utc FROM sources WHERE name=?),NULL),COALESCE((SELECT last_error FROM sources WHERE name=?),NULL),0,'up')",
            (name, iso(utc()), name, name),
        )

    def source_fail(self, name: str, err: str) -> int:
        prev = self.q("SELECT consecutive_failures n, state FROM sources WHERE name=?", (name,))
        n = (prev[0]["n"] if prev else 0) + 1
        state = "down" if n >= 3 else "degraded"
        self.x(
            "INSERT OR REPLACE INTO sources VALUES (?,COALESCE((SELECT last_ok_utc FROM sources WHERE name=?),NULL),?,?,?,?)",
            (name, name, iso(utc()), err[:500], n, state),
        )
        if state == "down" and (not prev or prev[0]["state"] != "down"):
            self.notify("error", "source", f"source {name} is DOWN after {n} consecutive failures: {err[:200]}")
        return n

    def budget(self, day: str) -> dict[str, Any]:
        r = self.q("SELECT * FROM budgets WHERE day=?", (day,))
        return r[0] if r else {"day": day, "research_wall_s": 0.0, "research_llm_calls": 0}

    def spend(self, day: str, wall: float, llm: int) -> None:
        self.x("INSERT OR IGNORE INTO budgets VALUES (?,0,0)", (day,))
        self.x(
            "UPDATE budgets SET research_wall_s=research_wall_s+?, research_llm_calls=research_llm_calls+? WHERE day=?",
            (wall, llm, day),
        )


@dataclass(frozen=True)
class Job:
    name: str
    critical: bool
    slot: Callable[[dt.datetime], str | None]  # None = not due now
    run: Callable[[str, dt.datetime, OpsDB], dict[str, Any]]
    max_attempts: int = 5


@contextmanager
def tick_lock(root: Path = ROOT):  # noqa: ANN201
    root.mkdir(parents=True, exist_ok=True)
    f = (root / "scheduler.lock").open("w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        yield False
        return
    try:
        f.write(f"{socket.gethostname()}:{os.getpid()}:{iso(utc())}\n")
        f.flush()
        yield True
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def lock_domain(root: Path = ROOT) -> str:
    """Identity of the exclusive scheduler lock: kernel boot + lock-file device/inode. Two processes with the same
    domain contend for the same flock, so the holder of the lock knows any other run in its domain is dead."""
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        boot = "unknown-boot"
    st = (root / "scheduler.lock").stat()
    return f"{boot}:{st.st_dev}:{st.st_ino}"


def _run_job(db: OpsDB, job: Job, slot: str, now: dt.datetime, cfg: dict[str, Any]) -> dict[str, Any] | None:
    row = db.q("SELECT * FROM runs WHERE job=? AND slot=?", (job.name, slot))
    if not row:
        db.x(
            "INSERT OR IGNORE INTO runs (job, slot, critical, status, attempts) VALUES (?,?,?,?,0)",
            (job.name, slot, int(job.critical), "pending"),
        )
        row = db.q("SELECT * FROM runs WHERE job=? AND slot=?", (job.name, slot))
    r = row[0]
    if r["status"] in ("succeeded", "skipped", "failed"):
        return None
    domain = cfg.get("_lock_domain")
    if r["status"] == "running" and (r["lease_until"] or 0) > time.time():
        # A 'running' row is written only by a process holding the exclusive scheduler flock for the whole run. We
        # hold that flock now; if the row's owner is in the same lock domain it cannot be alive -> reclaim at once.
        # Other domains (another host, unknown) keep the lease: exactly-once issuance also rests on the ledger key.
        if not (domain and r.get("owner") == domain):
            return None  # another live process may own it
        db.notify(
            "warning",
            job.name,
            f"slot {slot}: previous owner (same lock domain, pid {r.get('pid')}) is dead; reclaimed without waiting for the lease",
        )
    if r["next_attempt_utc"] and r["next_attempt_utc"] > iso(utc()):  # retry times are wall-clock
        return None
    attempts = r["attempts"] + 1
    db.x(
        "UPDATE runs SET status='running', attempts=?, lease_until=?, started_utc=?, host=?, pid=?, owner=? WHERE job=? AND slot=?",
        (attempts, time.time() + cfg["lease_s"], iso(utc()), socket.gethostname(), os.getpid(), domain, job.name, slot),
    )
    try:
        res = job.run(slot, now, db)
        status = res.pop("_status", "succeeded")
        if status == "pending":  # handler is waiting (e.g. for data): not an attempt; re-check after a pause
            wait = res.pop("_retry_after_s", cfg["pending_wait_s"])
            db.x(
                "UPDATE runs SET status='pending', attempts=?, next_attempt_utc=?, result=?, lease_until=NULL WHERE job=? AND slot=?",
                (
                    attempts - 1,
                    iso(utc() + dt.timedelta(seconds=wait)),
                    json.dumps(res, default=str)[:20000],
                    job.name,
                    slot,
                ),
            )
            return {"job": job.name, "slot": slot, "status": "pending"}
        db.x(
            "UPDATE runs SET status=?, finished_utc=?, result=?, error=?, lease_until=NULL WHERE job=? AND slot=?",
            (status, iso(utc()), json.dumps(res, default=str)[:20000], res.get("error"), job.name, slot),
        )
        if status == "failed":
            db.notify("error", job.name, f"slot {slot} FAILED: {str(res.get('error'))[:300]}")
        return {"job": job.name, "slot": slot, "status": status}
    except Exception as e:  # noqa: BLE001 - every failure is recorded, retried with backoff and notified
        err = f"{type(e).__name__}: {e}"
        if attempts >= job.max_attempts:
            db.x(
                "UPDATE runs SET status='failed', finished_utc=?, error=?, lease_until=NULL WHERE job=? AND slot=?",
                (iso(utc()), err[:2000], job.name, slot),
            )
            db.notify("error", job.name, f"slot {slot} FAILED after {attempts} attempts: {err[:300]}")
            return {"job": job.name, "slot": slot, "status": "failed", "error": err}
        nxt = utc() + dt.timedelta(seconds=cfg["backoff_s"] * 2 ** (attempts - 1))
        db.x(
            "UPDATE runs SET status='retry', next_attempt_utc=?, error=?, lease_until=NULL WHERE job=? AND slot=?",
            (iso(nxt), (err + "\n" + traceback.format_exc()[-1500:])[:3000], job.name, slot),
        )
        db.notify("warning", job.name, f"slot {slot} attempt {attempts} failed, retry at {iso(nxt)}: {err[:200]}")
        return {"job": job.name, "slot": slot, "status": "retry", "error": err}


def tick(
    jobs: list[Job], now: dt.datetime | None = None, db: OpsDB | None = None, cfg: dict[str, Any] | None = None
) -> dict[str, Any]:
    now = utc(now)
    db = db or OpsDB()
    cfg = {**DEFAULTS, **(cfg or {})}
    with tick_lock(db.root) as ok:
        if not ok:
            return {"tick": iso(now), "status": "locked", "note": "another tick is running on this host"}
        out: list[dict[str, Any]] = []
        cfg = {**cfg, "_lock_domain": lock_domain(db.root)}  # valid only while we hold the flock
        for job in [j for j in jobs if j.critical] + [j for j in jobs if not j.critical]:
            try:
                slot = job.slot(now)
            except Exception as e:  # noqa: BLE001
                db.notify("error", job.name, f"slot computation failed: {e}")
                continue
            if slot is None:
                continue
            r = _run_job(db, job, slot, now, cfg)
            if r:
                out.append(r)
        db.x("INSERT OR REPLACE INTO heartbeat VALUES ('last_tick_utc', ?)", (iso(utc()),))
        db.x(
            "INSERT OR REPLACE INTO heartbeat VALUES ('last_tick_host', ?)", (f"{socket.gethostname()}:{os.getpid()}",)
        )
        return {"tick": iso(now), "status": "ran", "runs": out}


def daemon(jobs_factory: Callable[[], list[Job]], interval_s: float = 60.0, max_ticks: int | None = None) -> None:
    """Always-on loop. SIGTERM/SIGINT stop it after the current tick (state stays consistent)."""
    import signal

    stop = {"flag": False}

    def _stop(*_: Any) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    n = 0
    while not stop["flag"] and (max_ticks is None or n < max_ticks):
        r = tick(jobs_factory())
        print(json.dumps(r, default=str), flush=True)
        n += 1
        t_end = time.time() + interval_s
        while time.time() < t_end and not stop["flag"]:
            time.sleep(1.0)


def status(db: OpsDB | None = None) -> dict[str, Any]:
    db = db or OpsDB()
    hb = {r["key"]: r["value"] for r in db.q("SELECT * FROM heartbeat")}
    day = iso(utc())[:10]
    return {
        "heartbeat": hb,
        "runs": db.q(
            "SELECT job, slot, critical, status, attempts, started_utc, finished_utc, next_attempt_utc, error FROM runs ORDER BY COALESCE(started_utc, '') DESC LIMIT 40"
        ),
        "counts": db.q("SELECT job, status, COUNT(*) n FROM runs GROUP BY job, status ORDER BY job"),
        "sources": db.q("SELECT * FROM sources"),
        "notifications": db.q("SELECT * FROM notifications ORDER BY id DESC LIMIT 20"),
        "budget_today": {
            **db.budget(day),
            "limits": {k: DEFAULTS[k] for k in ("research_daily_wall_s", "research_daily_llm_calls")},
        },
    }
