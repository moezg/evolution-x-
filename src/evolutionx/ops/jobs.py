"""Job definitions for the durable scheduler (see scheduler.py).

CRITICAL (always run, never depend on the research army):
  fetch_data            hourly   official Binance daily archives (checksums) -> source health
  forecast_issue        daily    champion + challenger forecasts for the next 00:00 UTC origin, issued in the
                                 window [origin - ISSUE_LEAD_H (24 h), origin); waits for fresh data until 1 h before
                                 the deadline, then issues anyway (stale inputs make models abstain to B0)
  forecast_missed_check hourly   every scheduled origin that passed without a forecast is recorded as MISSED
  forecast_resolve      hourly   resolve matured forecasts from published data; refresh prospective scores
  ledger_verify         daily    hash chain + issuance-order invariants
  drift_check           daily    calibration / skill drift of resolved forecasts -> research request on alerts

OPTIONAL (paused army or exhausted daily budget -> skipped, critical jobs unaffected):
  research_army         daily    one bounded army tick (frozen LLM policy; budgets in ops.db)
  fomc_followup         event    after each FOMC statement: observed 4 h |return| vs the registered estimate
                                 (descriptive prospective observation, not a new test)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .scheduler import DEFAULTS, Job, OpsDB, iso

DAY = dt.timedelta(days=1)
SCHEDULE_START = dt.datetime(2026, 11, 4, tzinfo=dt.UTC)  # first scheduled prospective origin
ISSUE_LEAD_H = float(os.environ.get("EVOX_ISSUE_LEAD_H", "24"))  # window opens at 00:00 UTC; waits for data
FRESH_WAIT_LAG_H = 30.0  # wait for the previous day's archive while > 1 h remains before the deadline
RESEARCH_AFTER_H = 6  # optional research starts after 06:00 UTC
FOLLOWUPS = Path("artifacts/ops/event_followups.jsonl")
QUANT_REGISTERED_UTC = "2026-11-03T23:23:57+00:00"  # first registered quant run (c20261103T2323577382)
SPOT_DAILY = "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-{d}.zip"


def _day0(t: dt.datetime) -> dt.datetime:
    return t.replace(hour=0, minute=0, second=0, microsecond=0)


def next_origin(now: dt.datetime) -> dt.datetime:
    return _day0(now) + DAY


def _wall_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _ms(t: dt.datetime) -> int:
    return int(t.timestamp() * 1000)


# --------------------------------------------------------------------------- critical
def fetch_data(slot: str, now: dt.datetime, db: OpsDB) -> dict[str, Any]:
    from ..forecast.data import fetch_fresh

    try:
        m = fetch_fresh()
    except Exception as e:  # network / checksum failure -> source health, then retry with backoff
        db.source_fail("binance_archives", f"{type(e).__name__}: {e}")
        raise
    db.source_ok("binance_archives")
    days = [f["day"] for f in m["files"]]
    gaps = []
    for d in m["not_published"]:  # a day still unpublished 48 h after it ended is a source gap (alert once)
        end = dt.datetime.fromisoformat(d).replace(tzinfo=dt.UTC) + DAY
        filled = any(d in f["fills_days"] for f in m.get("filled_from_monthly", []))
        if now - end > dt.timedelta(hours=48) and not filled:
            key = f"gap_notified:{d}"
            if not db.q("SELECT 1 FROM heartbeat WHERE key=?", (key,)):
                db.notify(
                    "warning",
                    "fetch_data",
                    f"official archive for {d} still unpublished 48 h after the day ended (source gap)",
                )
                db.x("INSERT OR REPLACE INTO heartbeat VALUES (?, ?)", (key, iso(now)))
            gaps.append(d)
    lat = {}
    for d, lm in m.get("publication_last_modified", {}).items():
        if lm:
            pub = dt.datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=dt.UTC)
            lat[d] = round(
                (pub - (dt.datetime.fromisoformat(d).replace(tzinfo=dt.UTC) + DAY)).total_seconds() / 3600, 2
            )
    return {
        "latest_day": max(days) if days else None,
        "not_published": m["not_published"],
        "source_gaps": gaps,
        "publication_latency_h_after_day_end": lat,
        "filled_from_monthly": m.get("filled_from_monthly", []),
    }


def archive_revision_check(slot: str, now: dt.datetime, db: OpsDB) -> dict[str, Any]:
    """Detect post-use revisions of the last 7 stored daily archives (remote CHECKSUM vs stored file). A revision is
    alerted and recorded; stored files are never overwritten (forecasts keep the inputs they were built on)."""
    import hashlib

    import httpx

    from ..forecast.data import DAILY, FRESH

    out: dict[str, Any] = {"checked": [], "revised": []}
    days = sorted(p.stem.replace("BTCUSDT-1h-", "") for p in FRESH.glob("BTCUSDT-1h-*.zip"))[-7:]
    with httpx.Client(timeout=30) as c:
        for d in days:
            r = c.get(DAILY.format(d=d) + ".CHECKSUM")
            if r.status_code != 200:
                continue
            remote = r.text.split()[0]
            local = hashlib.sha256((FRESH / f"BTCUSDT-1h-{d}.zip").read_bytes()).hexdigest()
            out["checked"].append(d)
            if remote != local:
                out["revised"].append({"day": d, "stored_sha256": local, "remote_sha256": remote})
                key = f"revision_notified:{d}:{remote[:12]}"
                if not db.q("SELECT 1 FROM heartbeat WHERE key=?", (key,)):
                    db.notify(
                        "error",
                        "archive_revision_check",
                        f"official archive {d} was REVISED after use (stored {local[:12]}, now {remote[:12]}); stored file kept",
                    )
                    db.x("INSERT OR REPLACE INTO heartbeat VALUES (?, ?)", (key, iso(now)))
    return out


def _data_as_of() -> dt.datetime | None:
    """End of the latest published day (cheap; from the fetch manifest)."""
    p = Path("data/fresh/manifest.json")
    if not p.exists():
        return None
    days = [f["day"] for f in json.loads(p.read_text()).get("files", [])]
    return dt.datetime.fromisoformat(max(days)).replace(tzinfo=dt.UTC) + DAY if days else None


def issue_slot(now: dt.datetime) -> str | None:
    o = next_origin(now)
    return o.date().isoformat() if now >= o - dt.timedelta(hours=ISSUE_LEAD_H) else None


def forecast_issue(slot: str, now: dt.datetime, db: OpsDB) -> dict[str, Any]:
    from ..forecast import prospective as P
    from ..quant.forecast_link import issue_challengers

    origin = dt.datetime.fromisoformat(slot).replace(tzinfo=dt.UTC)
    wall_now = _wall_now()
    if wall_now >= origin:
        # never issue late; the missed-window job records it
        return {"_status": "failed", "error": "issuance deadline passed before the run started (recorded as missed)"}
    as_of = _data_as_of()
    lag_h = (origin - as_of).total_seconds() / 3600 if as_of else float("inf")
    if lag_h > FRESH_WAIT_LAG_H:  # waiting: look for the archive now instead of at the next hourly fetch
        from ..forecast.data import fetch_fresh

        try:
            fetch_fresh()
            db.source_ok("binance_archives")
        except Exception as e:  # the outage is recorded; issuance logic below still applies
            db.source_fail("binance_archives", f"{type(e).__name__}: {e}")
        as_of = _data_as_of()
        lag_h = (origin - as_of).total_seconds() / 3600 if as_of else float("inf")
    if lag_h > FRESH_WAIT_LAG_H and origin - wall_now > dt.timedelta(hours=1):
        return {"_status": "pending", "waiting_for_data": True, "lag_h": lag_h}  # re-checked next tick
    champ = P.issue(now=wall_now, fetch=False, origin_ms=_ms(origin))
    ch = issue_challengers(now=wall_now, origin_ms=_ms(origin))
    n_new = sum(1 for f in champ["forecasts"] if "skipped" not in f)
    n_skip = len(champ["forecasts"]) - n_new
    return {
        "origin_utc": champ["origin_utc"],
        "as_of_utc": champ["as_of_utc"],
        "lag_h": champ["lag_h"],
        "champion_issued": n_new,
        "champion_already_present": n_skip,
        "challengers": ch.get("issued"),
    }


def forecast_missed_check(slot: str, now: dt.datetime, db: OpsDB) -> dict[str, Any]:
    from ..forecast.ledger import ForecastLedger

    led = ForecastLedger()
    issued = {e["data"]["origin_ms"] for e in led.forecasts().values() if not e["data"]["model"].startswith("CH:")}
    missed = {m["data"]["origin_ms"] for m in led.missed()}
    recorded = []
    o = SCHEDULE_START
    while o <= now:  # every origin whose deadline has passed
        oms = _ms(o)
        if oms not in issued and oms not in missed:
            led.record_missed("btc_perp", oms, "no champion forecast issued before the origin", _ms(now))
            db.notify("error", "forecast_missed_check", f"origin {iso(o)} MISSED (recorded; never backfilled)")
            recorded.append(iso(o))
        o += DAY
    return {"recorded_missed": recorded, "missed_total": len(missed) + len(recorded)}


def forecast_resolve(slot: str, now: dt.datetime, db: OpsDB) -> dict[str, Any]:
    from ..forecast import audit as A
    from ..forecast import prospective as P

    r = P.resolve(fetch=False)
    s = P.score()
    P.status_path().write_text(json.dumps(s, indent=1, default=str))
    out = {**r, "scored_pairs": len(s["scores"])}
    if r["resolved"] or now.hour == 12:  # after every new resolution, and once a day regardless
        a = A.audit()
        rep = A.report()
        Path("artifacts/forecast/prospective_report.json").write_text(
            json.dumps({"audit": a, "report": rep}, indent=1, default=str)
        )
        if not a["ok"]:
            db.notify(
                "error",
                "forecast_resolve",
                f"resolution/input audit FAILED: {a['problems'][:3]} verify={a['ledger_verify'].get('ok')}",
            )
        out |= {"audit_ok": a["ok"], "audit_problems": len(a["problems"]), "resolved_cells": rep["resolved_cells"]}
    return out


def ledger_verify(slot: str, now: dt.datetime, db: OpsDB) -> dict[str, Any]:
    from ..forecast.ledger import ForecastLedger

    v = ForecastLedger().verify()
    if not v["ok"]:
        db.notify("error", "ledger_verify", f"forecast ledger verification FAILED: {v}")
        raise RuntimeError(f"ledger verification failed: {v.get('reason')}")
    return v


def drift_check(slot: str, now: dt.datetime, db: OpsDB) -> dict[str, Any]:
    from ..army import drift

    r = drift.check()
    if r["alerts"]:
        db.notify("warning", "drift_check", f"forecast degradation: {r['alerts']}")
        db.x("INSERT OR REPLACE INTO heartbeat VALUES ('research_request', ?)", (json.dumps(r["alerts"]),))
    return {k: r[k] for k in ("resolved", "open", "alerts", "status")}


def challenger_review(slot: str, now: dt.datetime, db: OpsDB) -> dict[str, Any]:
    from ..forecast.challengers import review
    from .decisions import Decisions

    r = review()
    for k, v in r["reviews"].items():
        if str(v.get("action", "")).startswith("RETIRED"):
            db.notify("warning", "challenger_review", f"{k} retired by the frozen futility rule: {v}")
            dec = [d for d in Decisions().view() if d.get("subject") == k.split(":")[0] + ":" + k.split(":")[1]]
            if dec:
                Decisions().outcome(dec[-1]["id"], f"{k} retired by futility rule: {v}", None)
    return r


# --------------------------------------------------------------------------- optional
def _army_llm_calls() -> int:
    from ..army.store import Store

    r = Store().q("SELECT COALESCE(SUM(llm_calls),0) n FROM army_usage")
    return int(r[0]["n"])


def default_research_runner(cfg: dict[str, Any]) -> dict[str, Any]:
    from ..army.cli import run

    return run("tick", config=cfg)


def make_research(runner: Callable[[dict[str, Any]], dict[str, Any]], limits: dict[str, Any]) -> Callable[..., Any]:
    def research_army(slot: str, now: dt.datetime, db: OpsDB) -> dict[str, Any]:
        from ..army.store import Store

        state = Store().control("state", "running")
        if state != "running":
            return {"_status": "skipped", "reason": f"army is {state}; critical forecasting unaffected"}
        b = db.budget(slot)
        if (
            b["research_wall_s"] >= limits["research_daily_wall_s"]
            or b["research_llm_calls"] >= limits["research_daily_llm_calls"]
        ):
            db.notify(
                "warning", "research_army", f"daily research budget exhausted for {slot}; optional research paused"
            )
            return {"_status": "skipped", "reason": "daily research budget exhausted", "budget": b}
        llm_left = limits["research_daily_llm_calls"] - b["research_llm_calls"]
        req = db.q("SELECT value FROM heartbeat WHERE key='research_request'")
        cfg = {
            "llm_critique": llm_left >= 1,
            "scheduled_by": "ops",
            "drift_request": json.loads(req[0]["value"]) if req else None,
        }
        t0, c0 = time.time(), _army_llm_calls()
        try:
            r = runner(cfg)
        finally:
            db.spend(slot, time.time() - t0, max(0, _army_llm_calls() - c0))
        m = re.search(r"next cycle due in ([0-9.]+) h", str(r.get("reason", ""))) if r.get("action") == "none" else None
        if m:  # the army's own cadence says "not yet": wait for it instead of using up today's slot
            wait_s = float(m.group(1)) * 3600 + 60
            end_of_day = (_day0(now) + DAY - now).total_seconds()
            if wait_s < end_of_day:
                return {"_status": "pending", "_retry_after_s": wait_s, "army": r}
            return {"_status": "skipped", "reason": "army cycle not due before the end of this UTC day", "army": r}
        return {"army": r, "budget_after": db.budget(slot)}

    return research_army


def research_slot(now: dt.datetime) -> str | None:
    return now.date().isoformat() if now.hour >= RESEARCH_AFTER_H else None


def fomc_slot(now: dt.datetime) -> str | None:
    """Due from 4 h after an FOMC statement until 7 days later (one slot per event)."""
    from ..quant.events import Registry

    for ev in reversed(Registry().current("fomc")):
        t = dt.datetime.fromisoformat(ev["event_time_utc"])
        if t + dt.timedelta(hours=4) <= now <= t + dt.timedelta(days=7):
            return ev["event_id"]
    return None


def fomc_followup(slot: str, now: dt.datetime, db: OpsDB) -> dict[str, Any]:
    """Same definition as the registered event study: BTC SPOT 1h, |log return| from the close of the bar before
    the statement to the close of the 4th bar after it. Uses official spot DAILY archives (checksum verified)."""
    import math

    import httpx

    from ..quant import data as QD
    from ..quant.events import Registry

    ev = next(e for e in Registry().current("fomc") if e["event_id"] == slot)
    t = _ms(dt.datetime.fromisoformat(ev["event_time_utc"]))
    need = [t - 3_600_000] + [t + h * 3_600_000 for h in range(4)]
    days = sorted({dt.datetime.fromtimestamp(n / 1000, dt.UTC).date().isoformat() for n in need})
    close: dict[int, float] = {}
    archives = []
    with httpx.Client(timeout=60) as c:
        for d in days:
            dest = QD.ROOT / "binance" / "1h_daily" / f"BTCUSDT-1h-{d}.zip"
            try:
                archives.append({"day": d, **QD._fetch(c, SPOT_DAILY.format(d=d), dest)})
            except httpx.HTTPStatusError:
                return {"_status": "pending", "waiting_for_data": True, "unpublished_day": d}
            close |= {QD._ms(r[0]): float(r[4]) for r in QD._rows(dest)}
    rec: dict[str, Any] = {
        "event_id": slot,
        "series": "BTCUSDT spot 1h (Binance daily archives)",
        "archives": archives,
        "recorded_utc": iso(now),
    }
    if any(n not in close for n in need):
        rec |= {"_status": "skipped", "outcome": "source_gap", "missing_bars": [n for n in need if n not in close]}
    else:
        ret = math.log(close[need[-1]] / close[need[0]])
        rec |= {
            "observed_abs_4h_log_return": abs(ret),
            "registered_reference": "confirmation 2023-26: event mean |4h| 1.38% vs matched placebo 0.66% (exploratory)",
            "label": (
                "descriptive PROSPECTIVE observation (event after the registered run); not a new test"
                if ev["event_time_utc"] > QUANT_REGISTERED_UTC
                else "descriptive out-of-sample observation, NOT prospective (event preceded the registered run; "
                "excluded from its sample because the 7-day post window was incomplete); not a new test"
            ),
        }
    FOLLOWUPS.parent.mkdir(parents=True, exist_ok=True)
    with FOLLOWUPS.open("a") as f:
        f.write(json.dumps({k: v for k, v in rec.items() if k != "_status"}) + "\n")
    return rec


ELECTION_WINDOWS = (1, 7, 30, 90)
SPOT_DAILY_1D = "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-{d}.zip"


def _recorded_followups() -> set[str]:
    if not FOLLOWUPS.exists():
        return set()
    return {json.loads(x).get("key", "") for x in FOLLOWUPS.read_text().splitlines() if x.strip()}


def election_slot(now: dt.datetime) -> str | None:
    """Next due post-election window of the latest U.S. election (descriptive prospective record)."""
    from ..quant.events import Registry

    ev = [
        e
        for e in Registry().current("us_election")
        if e["attributes"].get("year") == now.year or e["attributes"].get("year") == now.year - 1
    ]
    done = _recorded_followups()
    for e in sorted(ev, key=lambda x: x["event_time_utc"]):
        day = dt.date.fromisoformat(e["event_time_utc"][:10])
        for w in ELECTION_WINDOWS:
            key = f"{e['event_id']}:post_{w}"
            due = dt.datetime.combine(
                day + dt.timedelta(days=w + 1), dt.time(6), tzinfo=dt.UTC
            )  # candle closed + archive
            if key not in done and due <= now <= due + dt.timedelta(days=30):
                return key
    return None


def election_followup(slot: str, now: dt.datetime, db: OpsDB) -> dict[str, Any]:
    """BTC spot daily close-to-close log return from election day (registered reference) to day +w."""
    import math

    import httpx

    from ..quant import data as QD

    eid, wk = slot.rsplit(":", 1)
    w = int(wk.replace("post_", ""))
    from ..quant.events import Registry

    ev = next(e for e in Registry().current("us_election") if e["event_id"] == eid)
    day = dt.date.fromisoformat(ev["event_time_utc"][:10])
    closes = {}
    archives = []
    with httpx.Client(timeout=60) as c:
        for d in (day, day + dt.timedelta(days=w)):
            dest = QD.ROOT / "binance" / "1d_daily" / f"BTCUSDT-1d-{d.isoformat()}.zip"
            try:
                archives.append({"day": d.isoformat(), **QD._fetch(c, SPOT_DAILY_1D.format(d=d.isoformat()), dest)})
            except httpx.HTTPStatusError:
                return {"_status": "pending", "_retry_after_s": 3600, "waiting_for": d.isoformat()}
            rows = QD._rows(dest)
            closes[d] = float(rows[0][4])
    ret = math.log(closes[day + dt.timedelta(days=w)] / closes[day])
    hist = {"2018": {"post_30": -0.62}, "2022": {"post_30": -0.07}}
    rec = {
        "key": slot, "event_id": eid, "window_days": w, "btc_log_return": ret, "archives": archives,
        "historical_midterms_btc": hist if w == 30 else "see docs/QUANT.md (n=2 completed midterms)",
        "label": "descriptive PROSPECTIVE observation (window entirely after the registered election study); n is far too small for inference",
        "recorded_utc": iso(now),
    }  # fmt: skip
    FOLLOWUPS.parent.mkdir(parents=True, exist_ok=True)
    with FOLLOWUPS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


# --------------------------------------------------------------------------- registry
def build_jobs(
    research_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None, cfg: dict[str, Any] | None = None
) -> list[Job]:
    limits = {**DEFAULTS, **(cfg or {})}
    hourly = lambda now: now.strftime("%Y-%m-%dT%H")  # noqa: E731
    daily = lambda now: now.date().isoformat()  # noqa: E731
    return [
        Job("fetch_data", True, hourly, fetch_data, max_attempts=4),
        Job("forecast_issue", True, issue_slot, forecast_issue, max_attempts=8),
        Job("forecast_missed_check", True, hourly, forecast_missed_check),
        Job("forecast_resolve", True, hourly, forecast_resolve),
        Job("ledger_verify", True, daily, ledger_verify),
        Job("drift_check", True, daily, drift_check),
        Job("challenger_review", True, daily, challenger_review),
        Job("archive_revision_check", True, daily, archive_revision_check, max_attempts=3),
        Job("research_army", False, research_slot, make_research(research_runner or default_research_runner, limits), max_attempts=2),
        Job("fomc_followup", False, fomc_slot, fomc_followup, max_attempts=3),
        Job("election_followup", False, election_slot, election_followup, max_attempts=3),
    ]  # fmt: skip
