"""Persistent research memory (SQLite, schema-versioned): campaigns, tasks, hypotheses, trials, experiments,
vault ledger. Keeps failures, refutations and inconclusive results, not only winners."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS campaigns (
  id TEXT PRIMARY KEY, mode TEXT, selector TEXT, status TEXT, budget TEXT, consumed TEXT, config TEXT,
  created TEXT, updated TEXT, stop_reason TEXT);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, campaign_id TEXT, seq INTEGER, stage TEXT, status TEXT, attempts INTEGER, max_attempts INTEGER,
  deadline_s REAL, task TEXT, checkpoint TEXT, error TEXT, created TEXT, updated TEXT,
  UNIQUE(campaign_id, seq));
CREATE TABLE IF NOT EXISTS hypotheses (
  id TEXT PRIMARY KEY, signature TEXT, statement TEXT, operator TEXT, parent_id TEXT, candidate_id TEXT,
  status TEXT, evidence TEXT, novelty TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY, parent_id TEXT, code_sha256 TEXT, generator TEXT, operator TEXT, spec TEXT, path TEXT,
  status TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS experiments (
  key TEXT PRIMARY KEY, candidate_id TEXT, stage TEXT, protocol_sha256 TEXT, data_sha256 TEXT, result TEXT,
  created TEXT);
CREATE TABLE IF NOT EXISTS trials (
  id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT, split TEXT, params TEXT, metric TEXT, value REAL,
  created TEXT);
CREATE TABLE IF NOT EXISTS vault_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT, actor TEXT, reason TEXT, files TEXT, ts TEXT);
"""
_lock = threading.Lock()


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class Memory:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._c() as c:
            c.executescript(SCHEMA)
            cur = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if cur is None:
                c.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            elif int(cur[0]) != SCHEMA_VERSION:
                raise RuntimeError(f"research DB schema {cur[0]} != code schema {SCHEMA_VERSION}; migrate first")

    def _c(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def x(self, sql: str, args: tuple = ()) -> None:
        with _lock, self._c() as c:
            c.execute(sql, args)

    def q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._c() as c:
            rows = [dict(r) for r in c.execute(sql, args).fetchall()]
        for r in rows:
            for k, v in r.items():
                if isinstance(v, str) and v[:1] in "{[":
                    with contextlib.suppress(json.JSONDecodeError):
                        r[k] = json.loads(v)
        return rows

    # experiments are idempotent: same key -> stored result reused, never re-run
    def get_experiment(self, key: str) -> dict[str, Any] | None:
        r = self.q("SELECT result FROM experiments WHERE key=?", (key,))
        return r[0]["result"] if r else None

    def put_experiment(
        self, key: str, candidate_id: str, stage: str, protocol_sha: str, data_sha: str, result: dict[str, Any]
    ) -> None:
        self.x(
            "INSERT OR IGNORE INTO experiments VALUES (?,?,?,?,?,?,?)",
            (key, candidate_id, stage, protocol_sha, data_sha, json.dumps(result, default=float), now()),
        )

    def add_trial(self, candidate_id: str, split: str, params: dict[str, Any], metric: str, value: float) -> None:
        self.x(
            "INSERT INTO trials (candidate_id, split, params, metric, value, created) VALUES (?,?,?,?,?,?)",
            (candidate_id, split, json.dumps(params, sort_keys=True), metric, float(value), now()),
        )

    def n_trials(self, split: str) -> int:
        return int(self.q("SELECT COUNT(*) n FROM trials WHERE split=?", (split,))[0]["n"])

    def trial_values(self, split: str, metric: str) -> list[float]:
        return [r["value"] for r in self.q("SELECT value FROM trials WHERE split=? AND metric=?", (split, metric))]
