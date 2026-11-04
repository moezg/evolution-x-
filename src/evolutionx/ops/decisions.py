"""Decision journal of the research director (accountability; append-only, hash-chained, committed to git).

Every non-routine decision records: the question, options considered, evidence (with artifact paths), reasoning,
the decision, what would change it (pre-stated review conditions) and, later, its observed outcome. Outcomes are
appended as separate events; nothing is edited. Wrong decisions are kept and their lessons recorded.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from ..research.journal import Journal

PATH = Path("data/decisions/journal.jsonl")


class Decisions:
    def __init__(self, path: Path = PATH) -> None:
        self.j = Journal(path)

    def entries(self) -> list[dict[str, Any]]:
        return [json.loads(x) for x in self.j.path.read_text().splitlines() if x.strip()]

    def record(self, rec: dict[str, Any]) -> str:
        for k in ("question", "options", "evidence", "reasoning", "decision", "review_conditions"):
            if k not in rec:
                raise ValueError(f"decision record missing {k}")
        did = "D-" + hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()[:10]
        self.j.append(
            "director", "decision", {"id": did, "utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), **rec}
        )
        return did

    def outcome(self, did: str, observed: str, correct: bool | None, lesson: str = "") -> None:
        if did not in {e["data"]["id"] for e in self.entries() if e["event"] == "decision"}:
            raise ValueError(f"unknown decision {did}")
        self.j.append("director", "outcome", {"decision_id": did, "utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "observed": observed, "decision_was_correct": correct, "lesson": lesson})  # fmt: skip

    def view(self) -> list[dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for e in self.entries():
            if e["event"] == "decision":
                out[e["data"]["id"]] = {**e["data"], "outcomes": []}
            elif e["event"] == "outcome":
                out[e["data"]["decision_id"]]["outcomes"].append(e["data"])
        return list(out.values())
