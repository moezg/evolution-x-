"""P4: U.S. macro release events (CPI, Employment Situation, GDP) from official, key-free sources.

bls.gov is blocked (HTTP 403) here, but the release history is available from ALFRED (St. Louis Fed real-time
archive): every vintage of a series is dated by the day its values became public. A vintage is a FIRST RELEASE when
it contains a newer observation period than the previous vintage; other vintages are revisions (e.g. annual
seasonal-factor updates) and are registered as such. Future dates come from BEA's official release schedule page.

Two different things are kept apart:
  availability (ALFRED vintage date)  - the day the number was actually public (history)
  schedule (BEA calendar)             - an announced future date and time (may move, e.g. shutdowns)
Time of day: ALFRED gives dates only. The 08:30 ET time is the agencies' standard release time (BEA's page states it
for each scheduled GDP release); for history it is a documented convention, so precision is recorded as
"day (08:30 ET by convention)". Consensus expectations are NOT available: no surprise can be computed.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import io
import re
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .events import Registry

ET = ZoneInfo("America/New_York")
ROOT = Path("data/quant/alfred")
SERIES = {
    "CPIAUCSL": {"subcategory": "cpi", "agency": "BLS", "release": "Consumer Price Index"},
    "PAYEMS": {"subcategory": "nfp", "agency": "BLS", "release": "Employment Situation"},
    "GDPC1": {"subcategory": "gdp", "agency": "BEA", "release": "Gross Domestic Product"},
}
PAGE = "https://alfred.stlouisfed.org/series/downloaddata?seid={sid}"
VINTAGE_CSV = "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={sid}&vintage_date={d}&cosd={start}"
BEA_SCHEDULE = "https://www.bea.gov/news/schedule"
FIRST = "2017-01-01"


def _get(c: httpx.Client, url: str) -> httpx.Response:
    for k in range(4):
        try:
            r = c.get(url)
            r.raise_for_status()
            return r
        except (httpx.TransportError, httpx.HTTPStatusError):
            if k == 3:
                raise
            time.sleep(2 * 2**k)
    raise RuntimeError("unreachable")


def vintage_dates(c: httpx.Client, sid: str) -> tuple[list[str], str, str]:
    r = _get(c, PAGE.format(sid=sid))
    t = r.text
    i = t.find("form_selected_vintage_dates")
    j = t.find("</select>", i)
    if i < 0 or j < 0:
        raise ValueError(f"ALFRED page layout changed for {sid}")
    ds = sorted(set(re.findall(r'<option[^>]*value="(\d{4}-\d{2}-\d{2})"', t[i:j])))
    return ds, hashlib.sha256(r.content).hexdigest(), dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def last_observation(c: httpx.Client, sid: str, vintage: str) -> tuple[str, str]:
    """Latest observation period contained in a vintage (cached; the CSV's sha256 is the provenance)."""
    p = ROOT / sid / f"{vintage}.csv"
    if not p.exists():
        start = (dt.date.fromisoformat(vintage) - dt.timedelta(days=800)).isoformat()
        r = _get(c, VINTAGE_CSV.format(sid=sid, d=vintage, start=start))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
        time.sleep(0.3)  # polite
    raw = p.read_bytes()
    rows = list(csv.reader(io.StringIO(raw.decode())))
    if not rows or not rows[0][1].endswith(vintage.replace("-", "")):
        raise ValueError(f"{sid} {vintage}: ALFRED returned another vintage ({rows[0] if rows else None})")
    obs = [r[0] for r in rows[1:] if len(r) > 1 and r[1] not in ("", ".")]
    return max(obs), hashlib.sha256(raw).hexdigest()


def build_macro(reg: Registry, series: tuple[str, ...] = tuple(SERIES)) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with httpx.Client(timeout=60, follow_redirects=True) as c:
        for sid in series:
            meta = SERIES[sid]
            dates, page_sha, retrieved = vintage_dates(c, sid)
            hist = [d for d in dates if d >= FIRST]
            prev_obs = last_observation(c, sid, max(d for d in dates if d < FIRST))[0]
            counts: dict[str, int] = {}
            for d in hist:
                obs, csv_sha = last_observation(c, sid, d)
                kind = "first_release" if obs > prev_obs else "revision"
                prev_obs = max(prev_obs, obs)
                day = dt.date.fromisoformat(d)
                t = dt.datetime(day.year, day.month, day.day, 8, 30, tzinfo=ET).astimezone(dt.UTC)
                st = reg.register(
                    {
                        "event_id": f"{meta['subcategory']}_{d}",
                        "category": "macro_release",
                        "subcategory": meta["subcategory"],
                        "event_time_utc": t.isoformat(),
                        "time_precision": "day (08:30 ET by agency convention; ALFRED gives the date only)",
                        "source_url": PAGE.format(sid=sid),
                        "source_sha256": page_sha,
                        "source_retrieved_utc": retrieved,
                        "derivation": f"ALFRED vintage date of {sid}; first_release if the vintage adds a newer observation period than the previous vintage",
                        "attributes": {
                            "series": sid,
                            "agency": meta["agency"],
                            "release": meta["release"],
                            "kind": kind,
                            "observation_period": obs,
                            "vintage_csv_sha256": csv_sha,
                            "availability": "actual (vintage)",
                            "consensus_available": False,
                        },
                    },
                    "I3",
                )
                counts[f"{kind}:{st}"] = counts.get(f"{kind}:{st}", 0) + 1
            out[sid] = {"vintages_since_2017": len(hist), "registered": counts}
        out["bea_schedule"] = build_bea_schedule(reg, c)
    return out


def parse_bea(text: str, today: dt.date) -> list[dict[str, Any]]:
    rows = []
    for m in re.finditer(
        r'class="release-date">([A-Za-z]+ \d{1,2})</div>\s*<small[^>]*>([^<]+)</small>.*?class="release-title[^"]*"[^>]*>([^<]+)<',
        text,
        flags=re.S,
    ):
        md, tm, title = m.group(1), m.group(2).strip(), html.unescape(m.group(3)).strip()
        d = dt.datetime.strptime(f"{md} {today.year}", "%B %d %Y").date()
        if d < today - dt.timedelta(days=180):  # the page lists the coming months; wrap into next year
            d = d.replace(year=today.year + 1)
        rows.append({"date": d, "time": tm, "title": title})
    return rows


def build_bea_schedule(reg: Registry, c: httpx.Client) -> dict[str, int]:
    r = _get(c, BEA_SCHEDULE)
    sha, retrieved = hashlib.sha256(r.content).hexdigest(), dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    out: dict[str, int] = {}
    for row in parse_bea(r.text, dt.datetime.now(dt.UTC).date()):
        if not row["title"].startswith("GDP (") or row["time"] != "8:30 AM":
            continue
        d = row["date"]
        t = dt.datetime(d.year, d.month, d.day, 8, 30, tzinfo=ET).astimezone(dt.UTC)
        st = reg.register(
            {
                "event_id": f"gdp_sched_{d.isoformat()}",
                "category": "macro_release",
                "subcategory": "gdp",
                "event_time_utc": t.isoformat(),
                "time_precision": "minute (08:30 ET stated on the BEA schedule)",
                "source_url": BEA_SCHEDULE,
                "source_sha256": sha,
                "source_retrieved_utc": retrieved,
                "attributes": {
                    "title": row["title"],
                    "availability": "scheduled (announced; may move)",
                    "future": d > dt.date.today(),
                    "consensus_available": False,
                },
            },
            "I3",
        )
        out[st] = out.get(st, 0) + 1
    return out
