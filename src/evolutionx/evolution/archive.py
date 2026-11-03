"""Durable lineage archive (SQLite): candidates, champions, proposals, prompts, audit log.

SQLite is chosen for v1 because the workload is single-writer, local and
transactional; PostgreSQL can replace it behind the same functions when the
platform becomes multi-user (see docs/adr/0001-architecture.md).
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

DB_PATH = Path("artifacts/evolution.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY, family TEXT, run_id TEXT, generation INTEGER, parents TEXT, origin TEXT,
  genome TEXT, status TEXT, objectives TEXT, train TEXT, behavior TEXT, pareto_rank INTEGER, created TEXT);
CREATE TABLE IF NOT EXISTS champions (
  version INTEGER PRIMARY KEY AUTOINCREMENT, family TEXT, candidate_id TEXT, promoted_at TEXT,
  reason TEXT, evidence TEXT, active INTEGER);
CREATE TABLE IF NOT EXISTS challenges (
  id INTEGER PRIMARY KEY AUTOINCREMENT, family TEXT, run_id TEXT, challenger TEXT, champion TEXT,
  decision TEXT, evidence TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS evo_runs (
  run_id TEXT PRIMARY KEY, family TEXT, config TEXT, status TEXT, summary TEXT, created TEXT, finished TEXT);
CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY, created TEXT, title TEXT, author TEXT, target_files TEXT, branch TEXT, status TEXT,
  report TEXT, decision TEXT);
CREATE TABLE IF NOT EXISTS prompts (
  role TEXT, version INTEGER, text TEXT, score REAL, active INTEGER, created TEXT, evaluation TEXT,
  PRIMARY KEY (role, version));
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT, subject TEXT, detail TEXT);
"""

_lock = threading.Lock()


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class Archive:
    def __init__(self, path: Path = DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def execute(self, sql: str, args: tuple = ()) -> None:
        with _lock, self._conn() as c:
            c.execute(sql, args)

    def query(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if isinstance(v, str) and v[:1] in "{[":
                    try:
                        d[k] = json.loads(v)
                    except json.JSONDecodeError:
                        pass
            out.append(d)
        return out

    # --- audit -------------------------------------------------------------
    def audit(self, actor: str, action: str, subject: str, detail: dict[str, Any] | None = None) -> None:
        self.execute("INSERT INTO audit (ts, actor, action, subject, detail) VALUES (?,?,?,?,?)",
                     (now(), actor, action, subject, json.dumps(detail or {}, default=str)))

    # --- candidates ----------------------------------------------------------
    def add_candidate(self, c: dict[str, Any]) -> None:
        self.execute(
            "INSERT OR REPLACE INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (c["id"], c["family"], c["run_id"], c["generation"], json.dumps(c.get("parents", [])), c["origin"],
             json.dumps(c["genome"]), c.get("status", "evaluated"), json.dumps(c.get("objectives", {})),
             json.dumps(c.get("train", {}), default=float), json.dumps(c.get("behavior", {})),
             c.get("pareto_rank"), now()))

    def set_status(self, cid: str, status: str) -> None:
        self.execute("UPDATE candidates SET status=? WHERE id=?", (status, cid))

    def candidates(self, family: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM candidates WHERE 1=1", []
        if family:
            sql += " AND family=?"
            args.append(family)
        if run_id:
            sql += " AND run_id=?"
            args.append(run_id)
        return self.query(sql + " ORDER BY created, generation, id", tuple(args))

    def candidate(self, cid: str) -> dict[str, Any] | None:
        r = self.query("SELECT * FROM candidates WHERE id=?", (cid,))
        return r[0] if r else None

    # --- champions -----------------------------------------------------------
    def active_champion(self, family: str) -> dict[str, Any] | None:
        r = self.query("SELECT * FROM champions WHERE family=? AND active=1 ORDER BY version DESC LIMIT 1", (family,))
        return r[0] if r else None

    def promote(self, family: str, cid: str, reason: str, evidence: dict[str, Any], actor: str = "evolution-loop") -> int:
        with _lock, self._conn() as c:
            c.execute("UPDATE champions SET active=0 WHERE family=?", (family,))
            cur = c.execute("INSERT INTO champions (family, candidate_id, promoted_at, reason, evidence, active) "
                            "VALUES (?,?,?,?,?,1)", (family, cid, now(), reason, json.dumps(evidence, default=float)))
            version = int(cur.lastrowid or 0)
            c.execute("UPDATE candidates SET status='champion' WHERE id=?", (cid,))
        self.audit(actor, "promote_champion", cid, {"family": family, "version": version, "reason": reason})
        return version

    def champions(self, family: str | None = None) -> list[dict[str, Any]]:
        if family:
            return self.query("SELECT * FROM champions WHERE family=? ORDER BY version", (family,))
        return self.query("SELECT * FROM champions ORDER BY version")

    def rollback(self, family: str, actor: str = "human") -> dict[str, Any] | None:
        hist = self.champions(family)
        active = [h for h in hist if h["active"]]
        if not active:
            return None
        cur = active[-1]
        prev = [h for h in hist if h["version"] < cur["version"]]
        if not prev:
            return None
        target = prev[-1]
        with _lock, self._conn() as c:
            c.execute("UPDATE champions SET active=0 WHERE family=?", (family,))
            c.execute("UPDATE champions SET active=1 WHERE version=?", (target["version"],))
            c.execute("UPDATE candidates SET status='retired' WHERE id=?", (cur["candidate_id"],))
            c.execute("UPDATE candidates SET status='champion' WHERE id=?", (target["candidate_id"],))
        self.audit(actor, "rollback_champion", cur["candidate_id"],
                   {"family": family, "from_version": cur["version"], "to_version": target["version"]})
        return target

    def record_challenge(self, family: str, run_id: str, challenger: str, champion: str, decision: str,
                         evidence: dict[str, Any]) -> None:
        self.execute("INSERT INTO challenges (family, run_id, challenger, champion, decision, evidence, created) "
                     "VALUES (?,?,?,?,?,?,?)",
                     (family, run_id, challenger, champion, decision, json.dumps(evidence, default=float), now()))

    def challenges(self, family: str | None = None) -> list[dict[str, Any]]:
        if family:
            return self.query("SELECT * FROM challenges WHERE family=? ORDER BY id", (family,))
        return self.query("SELECT * FROM challenges ORDER BY id")
