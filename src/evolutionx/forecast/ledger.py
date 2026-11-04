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
        res, unr = self.resolutions(), self.unresolvable()
        return [e for fid, e in self.forecasts().items() if fid not in res and fid not in unr]

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
        fc = self.forecasts()
        if rec["id"] in fc:
            raise LedgerError(f"forecast {rec['id']} already issued")
        key = (rec["domain"], rec["origin_ms"], rec["target"], rec["model"])
        if any((d["domain"], d["origin_ms"], d["target"], d["model"]) == key for d in (e["data"] for e in fc.values())):
            raise LedgerError(
                f"a forecast for {key} already exists (one forecast per origin/target/model, any version)"
            )
        if any(m["data"]["origin_ms"] == rec["origin_ms"] for m in self.missed()):
            raise LedgerError("this origin was recorded as MISSED; a late forecast can never be added (no backfill)")
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

    def unresolvable(self) -> dict[str, dict[str, Any]]:
        return {e["data"]["forecast_id"]: e for e in self.entries() if e["event"] == "unresolvable"}

    def record_unresolvable(self, fid: str, reason: str, now_ms: int) -> dict[str, Any]:
        """Outcome data never published by the registered source (checked after the monthly archive). Applied to
        every model of the same origin/target together, so paired comparisons stay unbiased; never a resolution."""
        f = self.forecasts().get(fid)
        if f is None:
            raise LedgerError("unknown forecast")
        if fid in self.resolutions() or fid in self.unresolvable():
            raise LedgerError("forecast already closed")
        if now_ms < f["data"]["window_end_ms"] + 35 * 86_400_000:
            raise LedgerError(
                "unresolvable only after the monthly archive could have been published (window end + 35 days)"
            )
        return self.j.append(
            "forecast-engine", "unresolvable", {"forecast_id": fid, "reason": reason, "recorded_ms": now_ms}
        )

    def missed(self) -> list[dict[str, Any]]:
        return [e for e in self.entries() if e["event"] == "missed"]

    def record_missed(self, domain: str, origin_ms: int, reason: str, now_ms: int | None = None) -> dict[str, Any]:
        """A forecasting window that passed without an issued forecast is recorded as missed (never backfilled)."""
        now_ms = now_ms if now_ms is not None else int(dt.datetime.now(dt.UTC).timestamp() * 1000)
        if now_ms < origin_ms:
            raise LedgerError("an origin can only be declared missed after its issuance deadline")
        if any(m["data"]["origin_ms"] == origin_ms and m["data"]["domain"] == domain for m in self.missed()):
            raise LedgerError("origin already recorded as missed")
        issued = [f for f in self.forecasts().values() if f["data"]["origin_ms"] == origin_ms]
        return self.j.append(
            "forecast-engine",
            "missed",
            {
                "domain": domain,
                "origin_ms": origin_ms,
                "reason": reason,
                "recorded_ms": now_ms,
                "partially_issued_models": sorted({f["data"]["model"] for f in issued}),
            },
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
        keys = [
            (e["data"]["domain"], e["data"]["origin_ms"], e["data"]["target"], e["data"]["model"])
            for e in issued.values()
        ]
        if len(keys) != len(set(keys)):
            return {"ok": False, "reason": "more than one forecast for the same origin/target/model"}
        for e in issued.values():
            if e["data"]["issued_ms"] >= e["data"]["origin_ms"]:
                return {"ok": False, "reason": f"forecast {e['data']['id']} issued after its window started"}
        for m in self.missed():
            if m["data"]["recorded_ms"] < m["data"]["origin_ms"]:
                return {"ok": False, "reason": "missed recorded before its deadline"}
            late = [
                f for f in issued.values() if f["data"]["origin_ms"] == m["data"]["origin_ms"] and f["seq"] > m["seq"]
            ]
            if late:
                return {"ok": False, "reason": "forecast issued after its origin was recorded as missed"}
        for fid in self.unresolvable():
            if fid in self.resolutions():
                return {"ok": False, "reason": f"forecast {fid} both resolved and unresolvable"}
        return {
            **v,
            "forecasts": len(issued),
            "resolved": len(self.resolutions()),
            "missed": len(self.missed()),
            "unresolvable": len(self.unresolvable()),
        }
