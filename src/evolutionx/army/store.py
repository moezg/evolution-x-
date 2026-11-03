"""Durable state of the research army: the existing research Memory schema plus orchestration and graph tables.

artifacts/army/research.db
  (research Memory)  hypotheses, candidates, experiments, trials   <- knowledge reused, not replaced
  army_cycles        one research cycle (DISCOVER .. REASSESS)
  army_tasks         typed task contracts with status, attempts, deps, lease, checkpoint result
  army_usage         per-role LLM calls / wall time / external requests
  army_sources       ingested external research items (untrusted content + provenance)
  army_edges         knowledge-graph edges (source -> hypothesis -> candidate -> result ...)
  army_control       pause / stop / budgets / source switches set by humans (dashboard or CLI)
artifacts/army/journal.jsonl  append-only, hash-chained record of every state change
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from ..research.journal import Journal
from ..research.memory import Memory, now

ROOT = Path("artifacts/army")
SCHEMA = """
CREATE TABLE IF NOT EXISTS army_cycles (id TEXT PRIMARY KEY, status TEXT, config TEXT, created TEXT, updated TEXT,
  summary TEXT);
CREATE TABLE IF NOT EXISTS army_tasks (id TEXT PRIMARY KEY, cycle_id TEXT, stage TEXT, role TEXT, kind TEXT,
  status TEXT, attempts INTEGER, max_attempts INTEGER, deps TEXT, payload TEXT, result TEXT, error TEXT,
  lease_until REAL, created TEXT, updated TEXT, wall_s REAL, llm_calls INTEGER);
CREATE TABLE IF NOT EXISTS army_usage (cycle_id TEXT, role TEXT, llm_calls INTEGER, llm_cost_usd REAL, wall_s REAL,
  ext_requests INTEGER, PRIMARY KEY (cycle_id, role));
CREATE TABLE IF NOT EXISTS army_sources (id TEXT PRIMARY KEY, origin TEXT, url TEXT, title TEXT, authors TEXT,
  published TEXT, updated TEXT, retrieved TEXT, abstract TEXT, doi TEXT, journal_ref TEXT, license_note TEXT,
  query TEXT, verification TEXT, mechanism TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS army_edges (src TEXT, rel TEXT, dst TEXT, data TEXT, created TEXT,
  PRIMARY KEY (src, rel, dst));
CREATE TABLE IF NOT EXISTS army_control (key TEXT PRIMARY KEY, value TEXT, updated TEXT, actor TEXT);
"""
_lock = threading.Lock()


class Store:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.mem = Memory(root / "research.db")
        with self.mem._c() as c:
            c.executescript(SCHEMA)
        self.journal = Journal(root / "journal.jsonl")

    # thin helpers over the Memory connection (same DB file, same locking)
    def x(self, sql: str, args: tuple = ()) -> None:
        self.mem.x(sql, args)

    def q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        return self.mem.q(sql, args)

    def log(self, actor: str, event: str, data: dict[str, Any]) -> None:
        with _lock:
            self.journal.append(actor, event, data)

    # control ---------------------------------------------------------------------------------------
    def control(self, key: str, default: Any = None) -> Any:
        r = self.q("SELECT value FROM army_control WHERE key=?", (key,))
        return json.loads(r[0]["value"]) if r and isinstance(r[0]["value"], str) else (r[0]["value"] if r else default)

    def set_control(self, key: str, value: Any, actor: str = "human") -> None:
        self.x("INSERT OR REPLACE INTO army_control VALUES (?,?,?,?)", (key, json.dumps(value), now(), actor))
        self.log(actor, "control", {"key": key, "value": value})

    # usage -----------------------------------------------------------------------------------------
    def add_usage(
        self, cycle: str, role: str, llm_calls: int = 0, cost: float = 0.0, wall: float = 0.0, ext: int = 0
    ) -> None:
        with _lock:
            self.x("INSERT OR IGNORE INTO army_usage VALUES (?,?,0,0,0,0)", (cycle, role))
            self.x(
                "UPDATE army_usage SET llm_calls=llm_calls+?, llm_cost_usd=llm_cost_usd+?, wall_s=wall_s+?, "
                "ext_requests=ext_requests+? WHERE cycle_id=? AND role=?",
                (llm_calls, cost, wall, ext, cycle, role),
            )

    def usage(self, cycle: str) -> list[dict[str, Any]]:
        return self.q("SELECT * FROM army_usage WHERE cycle_id=? ORDER BY role", (cycle,))

    # graph -----------------------------------------------------------------------------------------
    def edge(self, src: str, rel: str, dst: str, data: dict[str, Any] | None = None) -> None:
        self.x("INSERT OR IGNORE INTO army_edges VALUES (?,?,?,?,?)", (src, rel, dst, json.dumps(data or {}), now()))

    def edges(self, node: str | None = None) -> list[dict[str, Any]]:
        if node is None:
            return self.q("SELECT * FROM army_edges ORDER BY created")
        return self.q("SELECT * FROM army_edges WHERE src=? OR dst=? ORDER BY created", (node, node))
