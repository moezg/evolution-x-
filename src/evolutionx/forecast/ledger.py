"""Append-only Forecast Ledger (hash-chained via research/journal.Journal; tamper-evident, not tamper-proof).

Two event types:
  forecast    - written BEFORE the target window starts (enforced): model, version, timestamps, value, inputs.
  resolution  - written once per forecast after the outcome is observable in published data.
There is no update or delete operation. Corrections, if ever needed, are new events that reference the old one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from ..research.journal import Journal

LEDGER = Path("artifacts/forecast/ledger.jsonl")


class LedgerError(RuntimeError):
    pass


def forecast_id(domain: str, target: str, model: str, origin_ms: int, model_version: str) -> str:
    return hashlib.sha256(f"{domain}|{target}|{model}|{origin_ms}|{model_version}".encode()).hexdigest()[:16]


class ForecastLedger:
    def __init__(self, path: Path = LEDGER) -> None:
        self.j = Journal(path)

    def entries(self) -> list[dict[str, Any]]:
        lines = self.j.path.read_text().splitlines()
        return [json.loads(x) for x in lines if x.strip()]

    def forecasts(self) -> dict[str, dict[str, Any]]:
        return {e["data"]["id"]: e for e in self.entries() if e["event"] == "forecast"}

    def resolutions(self) -> dict[str, dict[str, Any]]:
        return {e["data"]["forecast_id"]: e for e in self.entries() if e["event"] == "resolution"}

    def open_forecasts(self) -> list[dict[str, Any]]:
        res = self.resolutions()
        return [e for fid, e in self.forecasts().items() if fid not in res]

    def issue(self, rec: dict[str, Any], now_ms: int | None = None) -> dict[str, Any]:
        now_ms = now_ms if now_ms is not None else int(dt.datetime.now(dt.UTC).timestamp() * 1000)
        for k in (
            "id",
            "domain",
            "target",
            "model",
            "model_version",
            "origin_ms",
            "window_end_ms",
            "as_of_ms",
            "inputs",
        ):
            if k not in rec:
                raise LedgerError(f"forecast record missing {k}")
        if now_ms >= rec["origin_ms"]:
            raise LedgerError("prospective forecasts must be issued before their target window starts")
        if rec["as_of_ms"] > now_ms:
            raise LedgerError("as_of cannot be in the future")
        if rec["id"] in self.forecasts():
            raise LedgerError(f"forecast {rec['id']} already issued")
        return self.j.append("forecast-engine", "forecast", {**rec, "issued_ms": now_ms})

    def resolve(self, fid: str, outcome: float, evidence: dict[str, Any], now_ms: int | None = None) -> dict[str, Any]:
        f = self.forecasts().get(fid)
        if f is None:
            raise LedgerError("unknown forecast")
        if fid in self.resolutions():
            raise LedgerError("forecast already resolved")
        now_ms = now_ms if now_ms is not None else int(dt.datetime.now(dt.UTC).timestamp() * 1000)
        if now_ms < f["data"]["window_end_ms"]:
            raise LedgerError("cannot resolve before the window has ended")
        return self.j.append(
            "forecast-engine",
            "resolution",
            {"forecast_id": fid, "outcome": outcome, "evidence": evidence, "resolved_ms": now_ms},
        )

    def verify(self) -> dict[str, Any]:
        v = self.j.verify()
        if not v["ok"]:
            return v
        issued = self.forecasts()
        for fid, r in self.resolutions().items():
            if fid not in issued:
                return {"ok": False, "reason": f"resolution without forecast {fid}"}
            if r["seq"] < issued[fid]["seq"]:
                return {"ok": False, "reason": f"resolution before forecast {fid}"}
        for e in issued.values():
            if e["data"]["issued_ms"] >= e["data"]["origin_ms"]:
                return {"ok": False, "reason": f"forecast {e['data']['id']} issued after its window started"}
        return {**v, "forecasts": len(issued), "resolved": len(self.resolutions())}
