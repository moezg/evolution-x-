"""`evox army ...` - human controls and scheduled entry point for the research army."""

from __future__ import annotations

import json
from typing import Any

from . import orchestrator as O
from . import stages as ST
from .store import Store

DEFAULT_CONFIG: dict[str, Any] = {
    "max_results": 4,
    "verify_per_scout": 2,
    "max_candidates": 3,
    "n_placebo": 8,
    "controls": ["invalid_strategy", "out_of_range"],
    "llm_critique": True,
}


def run(
    action: str, cycles: int = 1, config: dict[str, Any] | None = None, key: str | None = None, value: str | None = None
) -> dict[str, Any]:
    s = Store()
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    if action == "tick":  # scheduled entry point (cron / scheduled task); resumes or starts when due
        return O.tick(s, ST.HANDLERS, ST.seed, cfg)
    if action == "run":
        out = []
        for _ in range(cycles):
            cid = O.create_cycle(s, cfg, ST.seed)
            out.append(O.run_cycle(s, cid, ST.HANDLERS))
        return {"cycles": out}
    if action == "resume":
        c = s.q("SELECT id FROM army_cycles WHERE status IN ('running','paused','incomplete') ORDER BY created DESC")
        return O.run_cycle(s, c[0]["id"], ST.HANDLERS) if c else {"resumed": None}
    if action in ("pause", "stop", "start"):
        s.set_control("state", {"pause": "paused", "stop": "stopped", "start": "running"}[action])
        return {"state": s.control("state")}
    if action == "set":
        assert key is not None
        s.set_control(key, json.loads(value) if value is not None else None)
        return {key: s.control(key)}
    return {
        "state": s.control("state", "running"),
        "cycles": s.q("SELECT id, status, created, updated FROM army_cycles ORDER BY created DESC LIMIT 10"),
        "journal": s.journal.verify(),
    }
