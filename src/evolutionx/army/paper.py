"""Prospective paper ledger for strategy challengers (no orders; read-only market data).

For each challenger (and the champion), the daily target exposure for the next 24 h is recorded BEFORE the window
starts; the realized gross return of that exposure is resolved after publication. Only this ledger can produce
the evidence that the frozen policy requires for 'validated'.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Any

import numpy as np

from ..research.journal import Journal

LEDGER = Path("artifacts/army/paper_ledger.jsonl")
DAY = 86_400_000


class PaperLedger:
    def __init__(self, path: Path = LEDGER) -> None:
        self.j = Journal(path)

    def entries(self) -> list[dict[str, Any]]:
        import json

        return [json.loads(x) for x in self.j.path.read_text().splitlines() if x.strip()]

    def record(
        self, strategy_id: str, origin_ms: int, exposure: float, as_of_ms: int, now_ms: int, code_sha: str
    ) -> dict[str, Any]:
        if now_ms >= origin_ms:
            raise ValueError("paper positions must be recorded before their window starts")
        if not (-1.0 <= exposure <= 1.0) or not math.isfinite(exposure):
            raise ValueError("exposure outside [-1, 1]")
        if any(
            e["event"] == "position" and e["data"]["strategy_id"] == strategy_id and e["data"]["origin_ms"] == origin_ms
            for e in self.entries()
        ):
            raise ValueError("position already recorded")
        return self.j.append(
            "paper",
            "position",
            {
                "strategy_id": strategy_id,
                "origin_ms": origin_ms,
                "window_end_ms": origin_ms + DAY,
                "exposure": exposure,
                "as_of_ms": as_of_ms,
                "code_sha256": code_sha,
                "recorded_ms": now_ms,
            },
        )

    def resolve(self, strategy_id: str, origin_ms: int, gross_return: float, now_ms: int) -> dict[str, Any]:
        if now_ms < origin_ms + DAY:
            raise ValueError("window not over")
        return self.j.append(
            "paper",
            "resolution",
            {"strategy_id": strategy_id, "origin_ms": origin_ms, "gross_return": gross_return, "resolved_ms": now_ms},
        )

    def summary(self) -> dict[str, Any]:
        pos = {
            (e["data"]["strategy_id"], e["data"]["origin_ms"]): e["data"]
            for e in self.entries()
            if e["event"] == "position"
        }
        res = [e["data"] for e in self.entries() if e["event"] == "resolution"]
        by: dict[str, list[float]] = {}
        for r in res:
            p = pos.get((r["strategy_id"], r["origin_ms"]))
            if p:
                by.setdefault(r["strategy_id"], []).append(
                    p["exposure"] * 2.0 * r["gross_return"]
                )  # 1.0 = 2x engine max
        return {
            "positions": len(pos),
            "resolved": len(res),
            "by_strategy": {k: {"days": len(v), "mean_daily": float(np.mean(v))} for k, v in by.items()},
            "verify": self.j.verify(),
            "note": "gross of costs; costs are applied when comparing challengers (same cost model as the lab)",
            "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }
