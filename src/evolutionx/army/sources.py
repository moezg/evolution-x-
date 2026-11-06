"""Controlled ingestion of external research (arXiv discovery, Crossref verification).

Retrieved content is UNTRUSTED DATA: markup and control characters are stripped, length is capped, and nothing in
it is ever executed or allowed to set a status, budget, path or instruction. Each item keeps provenance (URL,
publication and update dates, retrieval time, authors, DOI / journal reference) and a licence/terms note. Requests
respect per-origin minimum intervals from the frozen policy.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET  # nosec B405 - expat does not resolve external entities; input is size-capped
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from .policy import policy

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
MAX_ABSTRACT = 3000
_last_call: dict[str, float] = {}
_throttle_lock = __import__("threading").Lock()

DISCOVERY_QUERIES = {  # the original fixed pair per scout (kept for reproducibility of earlier cycles)
    "A1": ['all:cryptocurrency AND all:"time series momentum"', 'all:cryptocurrency AND all:"realized volatility"'],
    "A2": ['abs:"perpetual" AND abs:"funding rate"', 'abs:"volatility-managed" OR abs:"volatility managed portfolio"'],
}
# Rotating pool (2 per scout per UTC day, deterministic): covers every implementable family so the scouts stop
# re-finding the same volatility-managed papers (all duplicates since 2026-11-03).
QUERY_POOL = {
    "A1": [
        'all:bitcoin AND all:"weekend effect"',
        'all:cryptocurrency AND all:"day-of-the-week"',
        'all:bitcoin AND all:"intraday seasonality"',
        'all:cryptocurrency AND all:"short-term reversal"',
        'all:cryptocurrency AND all:"time series momentum"',
        'all:bitcoin AND all:"calendar anomalies"',
    ],
    "A2": [
        'abs:bitcoin AND abs:"trading range breakout"',
        'abs:"perpetual" AND abs:"funding rate"',
        'abs:cryptocurrency AND abs:"mean reversion" AND abs:"intraday"',
        'abs:bitcoin AND abs:"overnight" AND abs:"returns"',
        'abs:cryptocurrency AND abs:"trend following"',
        'abs:bitcoin AND abs:"seasonality"',
    ],
}


def queries_for(role: str, day_ordinal: int) -> list[str]:
    pool = QUERY_POOL[role]
    i = (2 * day_ordinal) % len(pool)
    return [pool[i], pool[(i + 1) % len(pool)]]


@dataclass
class SourceItem:
    id: str
    origin: str
    url: str
    title: str
    authors: list[str]
    published: str
    updated: str
    retrieved: str
    abstract: str
    doi: str | None
    journal_ref: str | None
    license_note: str
    query: str
    categories: list[str] = field(default_factory=list)

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


class SourceDisabled(RuntimeError):
    pass


def sanitize(text: str | None, cap: int = MAX_ABSTRACT) -> str:
    t = re.sub(r"<[^>]{0,200}>", " ", text or "")
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:cap]


def _throttle(origin: str, enabled_override: bool | None = None) -> None:
    cfg = policy()["sources"][origin]
    if not cfg.get("enabled") or enabled_override is False:
        raise SourceDisabled(f"{origin} is disabled: {cfg.get('reason', 'human control')}")
    with _throttle_lock:  # rate limit is per origin and shared by all worker threads
        wait = cfg.get("min_interval_s", 1.0) - (time.monotonic() - _last_call.get(origin, -1e9))
        if wait > 0:
            time.sleep(wait)
        _last_call[origin] = time.monotonic()


def _get(origin: str, url: str, client: httpx.Client | None = None) -> httpx.Response:
    _throttle(origin)
    c = client or httpx.Client(timeout=30, headers={"User-Agent": "evolutionx-research/0.6 (research-only)"})
    r = c.get(url)
    r.raise_for_status()
    if len(r.content) > 5_000_000:
        raise ValueError("response too large")
    return r


def parse_arxiv(xml_text: str, query: str) -> list[SourceItem]:
    if re.search(r"<!(DOCTYPE|ENTITY)", xml_text[:5000], re.I):
        raise ValueError("refusing XML with DTD/entity declarations")  # no entity expansion possible below
    root = ET.fromstring(xml_text)  # noqa: S314  # nosec B314 - DTDs rejected above, input size-capped
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    out = []
    for e in root.findall(f"{ATOM}entry"):
        url = (e.findtext(f"{ATOM}id") or "").strip()
        aid = url.rsplit("/abs/", 1)[-1]
        doi = e.findtext(f"{ARXIV_NS}doi")
        out.append(
            SourceItem(
                id="arxiv:" + aid,
                origin="arxiv",
                url=url,
                title=sanitize(e.findtext(f"{ATOM}title"), 400),
                authors=[sanitize(a.findtext(f"{ATOM}name"), 120) for a in e.findall(f"{ATOM}author")][:20],
                published=(e.findtext(f"{ATOM}published") or "")[:20],
                updated=(e.findtext(f"{ATOM}updated") or "")[:20],
                retrieved=now,
                abstract=sanitize(e.findtext(f"{ATOM}summary")),
                doi=sanitize(doi, 200) or None,
                journal_ref=sanitize(e.findtext(f"{ARXIV_NS}journal_ref"), 300) or None,
                license_note="arXiv metadata/abstract via the public API; cite the original; full text not retrieved",
                query=query,
                categories=[c.get("term", "") for c in e.findall(f"{ATOM}category")][:10],
            )
        )
    return out


def search_arxiv(query: str, max_results: int = 5, client: httpx.Client | None = None) -> list[SourceItem]:
    ep = policy()["sources"]["arxiv"]["endpoint"]
    url = f"{ep}?search_query={urllib.parse.quote(query)}&start=0&max_results={max_results}&sortBy=relevance"
    return parse_arxiv(_get("arxiv", url, client).text, query)


def fetch_arxiv_record(arxiv_id: str, client: httpx.Client | None = None) -> SourceItem | None:
    ep = policy()["sources"]["arxiv"]["endpoint"]
    items = parse_arxiv(_get("arxiv", f"{ep}?id_list={urllib.parse.quote(arxiv_id)}", client).text, f"id:{arxiv_id}")
    return items[0] if items else None


def crossref_lookup(title: str, doi: str | None, client: httpx.Client | None = None) -> dict[str, Any]:
    ep = policy()["sources"]["crossref"]["endpoint"]
    if doi:
        r = _get("crossref", f"{ep}/{urllib.parse.quote(doi)}", client).json().get("message", {})
        items = [r]
    else:
        q = urllib.parse.quote(title[:200])
        items = (
            _get("crossref", f"{ep}?query.bibliographic={q}&rows=3", client).json().get("message", {}).get("items", [])
        )

    def norm(s: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]{3,}", s.lower()))

    best, score = None, 0.0
    for it in items:
        t = " ".join(it.get("title") or [])
        a, b = norm(t), norm(title)
        j = len(a & b) / max(1, len(a | b))
        if j > score:
            best, score = it, j
    if best is None or score < 0.6:
        return {"matched": False, "similarity": round(score, 3)}
    return {
        "matched": True,
        "similarity": round(score, 3),
        "doi": best.get("DOI"),
        "type": best.get("type"),
        "container": " ".join(best.get("container-title") or [])[:200],
        "published": (best.get("issued") or {}).get("date-parts", [[None]])[0],
        "publisher": best.get("publisher"),
    }


EVIDENCE_KEYS = {
    "out_of_sample": r"out-of-sample|out of sample|walk-forward|hold-?out",
    "costs": r"transaction cost|trading cost|fees|slippage",
    "data_period": r"\b(19|20)\d{2}\b",
    "statistical_test": r"significan|t-stat|bootstrap|p-value|confidence interval",
    "crypto": r"bitcoin|btc|crypto|ethereum|perpetual",
}
HYPE = r"guarantee|risk-free|100%|secret|get rich"


def grade(item: dict[str, Any], crossref: dict[str, Any]) -> dict[str, Any]:
    text = f"{item['title']} {item['abstract']}".lower()
    flags = {k: bool(re.search(v, text)) for k, v in EVIDENCE_KEYS.items()}
    peer = bool(crossref.get("matched") and crossref.get("type") == "journal-article")
    pts = 2 * peer + sum(flags[k] for k in ("out_of_sample", "costs", "statistical_test", "data_period"))
    level = "A" if pts >= 5 else "B" if pts >= 3 else "C" if pts >= 1 else "D"
    return {
        "grade": level,
        "points": pts,
        "peer_reviewed": peer,
        "flags": flags,
        "marketing_language": bool(re.search(HYPE, text)),
        "note": "deterministic rubric over metadata and abstract; it does not replicate the paper's results",
    }


def source_hash(item: dict[str, Any]) -> str:
    return hashlib.sha256((item["title"] + item["abstract"]).encode()).hexdigest()[:16]
