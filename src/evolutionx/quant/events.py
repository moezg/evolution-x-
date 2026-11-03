"""Versioned, append-only Event Registry (data/quant/events/registry.jsonl, hash-chained).

Every event keeps its authoritative source URL, the sha256 of the retrieved page, the retrieval time, the time
precision and the as-known attributes. Re-registering an event with different content creates a new version that
supersedes the previous one; nothing is overwritten. No event is invented to fill gaps: categories whose
authoritative calendars are unreachable (e.g. BLS CPI release dates, HTTP 403) are simply absent.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..research.journal import Journal
from .data import load_fred

REGISTRY = Path("data/quant/events/registry.jsonl")
CACHE = Path("data/quant/events/pages")
ET = ZoneInfo("America/New_York")
FOMC_CURRENT = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FOMC_HIST = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm"
STATUTE = "https://www.law.cornell.edu/uscode/text/2/7"
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        1,
    )
}
ABBR = {m[:3]: i for m, i in MONTHS.items()}


class Registry:
    def __init__(self, path: Path = REGISTRY) -> None:
        self.j = Journal(path)

    def entries(self) -> list[dict[str, Any]]:
        return [json.loads(x) for x in self.j.path.read_text().splitlines() if x.strip()]

    def current(self, category: str | None = None) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for e in self.entries():
            latest[e["data"]["event_id"]] = e["data"]
        ev = [v for v in latest.values() if category is None or v["category"] == category]
        return sorted(ev, key=lambda v: v["event_time_utc"])

    def register(self, ev: dict[str, Any], actor: str) -> str:
        """Append if new or changed (new version); unchanged events are not re-written."""
        prev = next((e for e in reversed(self.current()) if e["event_id"] == ev["event_id"]), None)
        if prev is not None:  # builders own only the keys they set; attributes added by enrichers are kept
            ev = {**ev, "attributes": {**prev.get("attributes", {}), **ev.get("attributes", {})}}
        body = {
            k: v for k, v in ev.items() if k not in ("version", "supersedes", "registered_utc", "source_retrieved_utc")
        }
        if prev is not None:
            old = {
                k: v
                for k, v in prev.items()
                if k not in ("version", "supersedes", "registered_utc", "source_retrieved_utc")
            }
            if old == body:
                return "unchanged"
        rec = {
            **ev,
            "version": (prev["version"] + 1) if prev else 1,
            "supersedes": prev["version"] if prev else None,
            "registered_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }
        self.j.append(actor, "event", rec)
        return "new_version" if prev else "registered"


def _page(url: str, client: httpx.Client) -> tuple[str, str, str]:
    """Fetch (or reuse the cached copy of) a public page; returns text, sha256, retrieval time."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".html")
    meta = f.with_suffix(".json")
    if not f.exists():
        r = client.get(url)
        r.raise_for_status()
        f.write_bytes(r.content)
        meta.write_text(
            json.dumps({"url": url, "retrieved_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")})
        )
    raw = f.read_bytes()
    return (
        raw.decode("utf-8", "replace"),
        hashlib.sha256(raw).hexdigest(),
        json.loads(meta.read_text())["retrieved_utc"],
    )


# ----------------------------------------------------------------------------- U.S. federal elections
def election_day(year: int) -> dt.date:
    """2 U.S.C. 7: the Tuesday next after the first Monday in November."""
    d = dt.date(year, 11, 1)
    first_monday = d + dt.timedelta(days=(0 - d.weekday()) % 7)
    return first_monday + dt.timedelta(days=1)


def build_elections(reg: Registry, first: int = 1962, last: int = 2026) -> dict[str, int]:
    out: dict[str, int] = {}
    for y in range(first + (first % 2), last + 1, 2):
        d = election_day(y)
        sub = "presidential" if y % 4 == 0 else "midterm"
        st = reg.register(
            {
                "event_id": f"us_election_{y}",
                "category": "us_election",
                "subcategory": sub,
                "event_time_utc": dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).isoformat(),
                "time_precision": "day",
                "market_reference": "close of election day (UTC daily candle) / next trading day close for daily FRED series",
                "source_url": STATUTE,
                "source_sha256": None,
                "derivation": "computed from statute 2 U.S.C. 7 (Tuesday after the first Monday in November, even years)",
                "attributes": {"year": y},
            },
            "I1",
        )
        out[st] = out.get(st, 0) + 1
    return out


# ----------------------------------------------------------------------------- FOMC
def _final_day(year: int, month_txt: str, date_txt: str) -> tuple[dt.date, dict[str, Any]]:
    flags = {
        "sep": "*" in date_txt,
        "unscheduled": "unscheduled" in date_txt.lower(),
        "notation_vote": "notation" in date_txt.lower(),
        "cancelled": "cancel" in date_txt.lower(),
    }
    days = [int(x) for x in re.findall(r"\d+", date_txt)]
    months = [MONTHS.get(m) or ABBR[m[:3]] for m in month_txt.split("/")]
    return dt.date(year, months[-1], days[-1]), flags


def parse_current(text: str) -> list[tuple[dt.date, dict[str, Any]]]:
    out = []
    parts = re.split(r"(\d{4}) FOMC Meetings", text)
    for i in range(1, len(parts), 2):
        y = int(parts[i])
        months = re.findall(r"fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>", parts[i + 1])
        dates = re.findall(r"fomc-meeting__date[^>]*>([^<]+)</div>", parts[i + 1])
        for m, d in zip(months, dates, strict=True):
            out.append(_final_day(y, m.strip(), d.strip()))
    return out


def parse_historical(text: str, year: int) -> list[tuple[dt.date, dict[str, Any]]]:
    out = []
    for h in re.findall(r"<h5[^>]*>([^<]*)</h5>", text):
        m = re.match(r"\s*([A-Za-z/]+)\s+([\d\-]+(?:\s*\([^)]*\))?)\s*(?:Meeting)?\s*-\s*(\d{4})", h)
        if m and int(m.group(3)) == year:
            out.append(_final_day(year, m.group(1), m.group(2)))
    return out


def build_fomc(reg: Registry, hist_years: tuple[int, ...] = (2017, 2018, 2019, 2020)) -> dict[str, int]:
    out: dict[str, int] = {}
    with httpx.Client(timeout=60) as c:
        pages = [(FOMC_CURRENT, *_page(FOMC_CURRENT, c), None)]
        pages += [(FOMC_HIST.format(y=y), *_page(FOMC_HIST.format(y=y), c), y) for y in hist_years]
    seen: set[dt.date] = set()
    for url, text, sha, retrieved, year in pages:
        rows = parse_current(text) if year is None else parse_historical(text, year)
        for day, flags in rows:
            if day in seen:
                continue
            seen.add(day)
            if flags["cancelled"]:
                continue
            kind = "notation_vote" if flags["notation_vote"] else "unscheduled" if flags["unscheduled"] else "scheduled"
            t = dt.datetime(day.year, day.month, day.day, 14, 0, tzinfo=ET).astimezone(dt.UTC)
            st = reg.register(
                {
                    "event_id": f"fomc_{day.isoformat()}",
                    "category": "fomc",
                    "subcategory": kind,
                    "event_time_utc": t.isoformat()
                    if kind == "scheduled"
                    else dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).isoformat(),
                    "time_precision": "minute (scheduled 14:00 ET statement)"
                    if kind == "scheduled"
                    else "day (release time not standardised)",
                    "source_url": url,
                    "source_sha256": sha,
                    "source_retrieved_utc": retrieved,
                    "attributes": {
                        "final_meeting_day": day.isoformat(),
                        "sep": flags["sep"],
                        "future": day > dt.date.today(),
                    },
                },
                "I2",
            )
            out[st] = out.get(st, 0) + 1
    return out


def attach_policy_actions(reg: Registry) -> dict[str, int]:
    """Target-range changes (FRED DFEDTARU, effective dates) linked to the FOMC event that announced them."""
    s = load_fred("DFEDTARU")
    chg = [
        (int(s.t[i]), float(s.close[i] - s.close[i - 1]))
        for i in range(1, len(s.t))
        if abs(s.close[i] - s.close[i - 1]) > 1e-9
    ]
    fomc = reg.current("fomc")
    out = {"linked": 0, "unlinked_changes": 0, "versions": 0}
    by_day = {e["attributes"]["final_meeting_day"]: e for e in fomc}
    linked: dict[str, float] = {}
    for t, d in chg:
        eff = dt.datetime.fromtimestamp(t / 1000, dt.UTC).date()
        cand = [eff - dt.timedelta(days=k) for k in (1, 0, 2, 3)]
        hit = next((by_day[c.isoformat()] for c in cand if c.isoformat() in by_day), None)
        if hit is None:
            out["unlinked_changes"] += 1
            continue
        linked[hit["event_id"]] = d
    first = min(dt.datetime.fromtimestamp(x / 1000, dt.UTC).date() for x in s.t)
    for e in fomc:
        if e["attributes"].get("future") or dt.date.fromisoformat(e["attributes"]["final_meeting_day"]) < first:
            continue
        action = linked.get(e["event_id"], 0.0)
        attrs = {
            **e["attributes"],
            "target_upper_change_pp": action,
            "action": "hike" if action > 0 else "cut" if action < 0 else "hold",
            "action_source": "FRED DFEDTARU (effective-date series)",
        }
        if attrs != e["attributes"]:
            reg.register({**e, "attributes": attrs}, "I2")
            out["versions"] += 1
        out["linked"] += action != 0.0
    return out
