"""On-demand LLM specialist agents (P3; policy evals/frozen/specialist_policy_v1.json).

Three roles make a real LLM call (official claude CLI, no tools, one turn, budgeted):
  A1 Research Scout          picks ONE fetched arXiv record, extracts a claim + verbatim quote
  G1 Quantitative Scientist  proposes ONE hypothesis citing registry test ids and the scout's source
  E3 Adversarial Scientist   critiques it
Everything an LLM says is checked by deterministic code before it is kept (citations exist, quotes are verbatim,
data is available, the hypothesis is not a duplicate). Accepted proposals are only QUEUED for prospective evaluation.
Without the CLI (or with LLM disabled) the session still runs and says, per role, that no LLM was used.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import sources as SRC
from .llm import LLM, CritiqueOut, wrap_untrusted
from .store import Store

POLICY = Path("evals/frozen/specialist_policy_v1.json")
OUT = Path("artifacts/army/specialists")
FAMILIES = ("F-DOM", "F-DOW", "F-MOY", "F-TOM", "F-FOMC", "F-ELECT", "F-CYCLE", "F-XEVENT")
METRICS = ("mean_ret", "mean_ret_wd_adj", "mean_absret", "up_rate", "left_tail_rate", "absret_0_4h", "ret_0_1h", "ret_0_24h", "rv_0_4h")  # fmt: skip
AVAILABLE = {
    "btc_spot_1h": "Binance spot 1h, 2017-08..present (official archives, checksums)",
    "btc_spot_1d": "Binance spot daily, 2017-08..present",
    "dgs10": "FRED 10-year Treasury yield",
    "sp500": "FRED S&P 500 (10 years)",
    "fed_target": "FRED DFEDTARU (policy actions)",
    "fomc_calendar": "federalreserve.gov meeting calendar 2017-2027 with statement times",
    "us_elections": "statutory U.S. election dates 1962-2026",
}
UNAVAILABLE = {
    "cpi_release_times": "bls.gov blocked (HTTP 403) in this environment",
    "consensus_expectations": "licensed data, not available",
    "options_expiry": "not ingested",
    "geopolitical_events": "no verified timestamped source",
}


LABEL_RE = re.compile(r"[A-Za-z0-9_]{1,24}")
CONDITIONS = {  # attributes recorded on registry events that define genuine sub-hypotheses
    "F-FOMC": ("hike", "cut", "hold", "sep", "no_sep", "unscheduled"),
    "F-ELECT": ("midterm", "presidential"),
}


def policy() -> dict[str, Any]:
    return json.loads(POLICY.read_text())


class ScoutOut(BaseModel):
    arxiv_id: str = Field(max_length=40)
    claim: str = Field(max_length=500)
    verbatim_quote: str = Field(max_length=400)
    relevance: str = Field(max_length=400)


class ProposalOut(BaseModel):
    family: Literal["F-DOM", "F-DOW", "F-MOY", "F-TOM", "F-FOMC", "F-ELECT", "F-CYCLE", "F-XEVENT"]
    label: str = Field(max_length=40)
    metric: str = Field(max_length=40)
    direction: Literal[-1, 1]
    statement: str = Field(max_length=500)
    rationale: str = Field(max_length=800)
    cites_tests: list[str] = Field(min_length=1, max_length=6)
    cites_sources: list[str] = Field(default_factory=list, max_length=3)
    data_needed: list[str] = Field(min_length=1, max_length=5)
    prospective_evaluation: str = Field(max_length=500)


class SpecialistLLM(LLM):
    """The army LLM wrapper with the specialist per-role caps (same connector, same per-session total)."""

    def __init__(self, store: Store, cycle: str) -> None:
        super().__init__(store, cycle)
        p = policy()
        self.pol = {"llm_calls_per_cycle": p["per_session"]["llm_calls"], "per_role_llm_calls": p["per_role_llm_calls"]}
        self.max_usd = float(p["per_session"]["usd_api_equivalent"])

    def allowed(self, role: str) -> tuple[bool, str]:
        spent = sum(r["llm_cost_usd"] for r in self.store.usage(self.cycle))
        if spent >= self.max_usd:
            return False, f"session USD budget exhausted ({spent:.3f})"
        return super().allowed(role)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


# --------------------------------------------------------------------------- deterministic validators
def validate_scout(out: ScoutOut, items: list[dict[str, Any]]) -> dict[str, Any]:
    it = next((i for i in items if i["id"] == out.arxiv_id), None)
    if it is None:
        return {"valid": False, "reason": f"cited record {out.arxiv_id!r} was not among the fetched records"}
    q = _norm(out.verbatim_quote)
    if len(q) < 20 or q not in _norm(it["abstract"] + " " + it["title"]):
        return {"valid": False, "reason": "quote does not occur verbatim in the cited record"}
    return {"valid": True, "source": {k: it[k] for k in ("id", "url", "title", "published", "retrieved")}}


def validate_proposal(
    p: ProposalOut, registry_rows: list[dict[str, Any]], prior_keys: set[str], sources: set[str]
) -> dict[str, Any]:
    key = f"{p.family}:{p.label}:{p.metric}" if p.label else f"{p.family}:{p.metric}"
    ids = {r["id"]: r for r in registry_rows}
    errors = []
    if p.label and not LABEL_RE.fullmatch(p.label):
        errors.append(
            f"label {p.label!r} is not an identifier (^[A-Za-z0-9_]{{1,24}}$); free text cannot define a new hypothesis"
        )
    if p.metric not in METRICS:
        errors.append(f"metric {p.metric!r} not in the allowed list")
    bad = [t for t in p.cites_tests if t not in ids]
    if bad:
        errors.append(f"cited test ids do not exist: {bad}")
    conf = [t for t in p.cites_tests if t in ids and ids[t]["period"] != "DISCOVERY"]
    if conf:
        errors.append(f"cited tests outside the allowed DISCOVERY context: {conf}")
    unk_src = [s for s in p.cites_sources if s not in sources]
    if unk_src:
        errors.append(f"cited sources were not verified in this session: {unk_src}")
    unavailable = [d for d in p.data_needed if d not in AVAILABLE]
    if unavailable:
        errors.append(f"needs unavailable data: {unavailable} (available: {sorted(AVAILABLE)})")
    if errors:
        return {"status": "rejected_invalid", "key": key, "reasons": errors}
    registered = {r["hypothesis"] for r in registry_rows}
    if key in registered or key.replace("mean_ret_wd_adj", "mean_ret") in registered or key in prior_keys:
        return {"status": "rejected_duplicate", "key": key, "reasons": [f"{key} is already registered or proposed"]}
    # event families are registered without a label: a label is only a NEW hypothesis when it is a known
    # conditioning attribute (a subset of events); anything else re-tests the registered event-level hypothesis
    if f"{p.family}:{p.metric}" in registered and p.label not in CONDITIONS.get(p.family, ()):
        return {
            "status": "rejected_duplicate",
            "key": key,
            "reasons": [
                f"same event set and metric as the registered {p.family}:{p.metric}; label {p.label!r} is not a conditioning attribute ({sorted(CONDITIONS.get(p.family, ()))})"
            ],
        }
    return {"status": "queued_prospective", "key": key, "reasons": []}


def _prior_keys() -> set[str]:
    keys = set()
    for p in OUT.glob("*.json"):
        for prop in json.loads(p.read_text()).get("proposals", []):
            if prop["validation"]["status"] == "queued_prospective":
                keys.add(prop["validation"]["key"])
    return keys


# --------------------------------------------------------------------------- session
def session(
    query: str = "FOMC announcement bitcoin volatility", max_results: int = 4, controls: bool = True
) -> dict[str, Any]:
    from ..quant.stats import TestRegistry

    store = Store()
    sid = "spec-" + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S")
    llm = SpecialistLLM(store, sid)
    out: dict[str, Any] = {
        "session": sid,
        "policy_sha256": hashlib.sha256(POLICY.read_bytes()).hexdigest(),
        "steps": [],
    }
    store.log("F1", "specialist_session_start", {"session": sid, "query": query})

    # A1 scout: real fetch, LLM selection, verbatim-quote check
    items = [i.to_row() for i in SRC.search_arxiv(query, max_results=max_results)]
    store.add_usage(sid, "A1", ext=1)
    listing = "\n".join(wrap_untrusted(i) + f"\n(id: {i['id']})" for i in items)
    so, info = llm.ask(
        "A1",
        "Role A1 Research Scout. From the records below choose the ONE most relevant to measurable crypto-market "
        "reactions to scheduled macro announcements. Keys: arxiv_id (exactly as given), claim (what the paper "
        "reports, in your words), verbatim_quote (copied exactly from its abstract, >= 20 characters), relevance.\n"
        + listing,
        ScoutOut,
    )
    scout = {"role": "A1", "llm": info, "fetched": [{k: i[k] for k in ("id", "title", "published")} for i in items]}
    verified: set[str] = set()
    if isinstance(so, ScoutOut):
        v = validate_scout(so, items)
        scout |= {"output": so.model_dump(), "validation": v}
        if v["valid"]:
            verified.add(so.arxiv_id)
    out["steps"].append(scout)

    # G1 quantitative scientist: DISCOVERY rows only
    reg = TestRegistry(store)
    rows = reg.rows()
    disc = [r for r in rows if r["period"] in ("DISCOVERY", "ALL")]
    ctx_rows = [
        {"id": r["id"], "hypothesis": r["hypothesis"], "status_discovery": "survived_bh" if r["status"] != "rejected" else "rejected", "effect": r["effect"], "n": r["n"], "p_adj": r["p_adj"]}
        for r in disc
        if r["family"] in ("F-DOW", "F-FOMC", "F-XEVENT", "F-ELECT", "F-TOM")
    ][:80]  # fmt: skip
    claim = scout.get("output") if scout.get("validation", {}).get("valid") else None
    po, info = llm.ask(
        "G1",
        "Role G1 Quantitative Scientist. Propose ONE new, falsifiable calendar/event hypothesis about BTC that is NOT "
        "already in the registry rows below. It will only ever be evaluated prospectively (all history is used). "
        f"Keys: family (one of {list(FAMILIES)}), label (an identifier; for event families only one of {CONDITIONS} or empty), metric (one of {list(METRICS)}), direction (1 or -1), "
        "statement, rationale, cites_tests (registry ids from the rows), cites_sources (arxiv ids, only the verified "
        f"one), data_needed (keys of {sorted(AVAILABLE)}), prospective_evaluation.\n"
        f"Unavailable data: {json.dumps(UNAVAILABLE)}\nVerified scout claim: {json.dumps(claim)}\n"
        f"Registry (DISCOVERY context only): {json.dumps(ctx_rows, default=float)}",
        ProposalOut,
    )
    proposals = []
    prior = _prior_keys()
    if isinstance(po, ProposalOut):
        proposals.append(
            {"by": "G1 (LLM)", "proposal": po.model_dump(), "validation": validate_proposal(po, rows, prior, verified)}
        )
    out["steps"].append({"role": "G1", "llm": info})

    # planted controls (deterministic): one duplicate, one needing unavailable data - both must be rejected
    if controls:
        fomc_id = next(r["id"] for r in disc if r["hypothesis"] == "F-FOMC:absret_0_4h")
        dup = ProposalOut(family="F-FOMC", label="", metric="absret_0_4h", direction=1, statement="BTC moves more in the 4 h after FOMC statements", rationale="planted duplicate control (re-proposes a registered hypothesis)", cites_tests=[fomc_id], data_needed=["btc_spot_1h", "fomc_calendar"], prospective_evaluation="n/a")  # fmt: skip
        inv = ProposalOut(family="F-FOMC", label="hot_cpi", metric="absret_0_4h", direction=1, statement="FOMC moves are larger when CPI beat consensus", rationale="planted invalid control", cites_tests=[fomc_id], data_needed=["consensus_expectations", "cpi_release_times"], prospective_evaluation="n/a")  # fmt: skip
        for c in (dup, inv):
            proposals.append(
                {
                    "by": "planted control",
                    "proposal": c.model_dump(),
                    "validation": validate_proposal(c, rows, prior, verified),
                }
            )
    out["proposals"] = proposals

    # E3 adversarial scientist: critique the LLM proposal if it survived validation, else the scout claim
    target = next(
        (p for p in proposals if p["by"].startswith("G1") and p["validation"]["status"] == "queued_prospective"), None
    )
    if target or claim:
        co, info = llm.ask(
            "E3",
            "Role E3 Adversarial Scientist. Attack this research item: list concrete concerns (data snooping, "
            "multiple testing, confounders, data availability, regime dependence), the most likely failure, and one "
            "additional test that could refute it. Keys: concerns, most_likely_failure, additional_test.\n"
            + json.dumps(target["proposal"] if target else claim),
            CritiqueOut,
        )
        out["steps"].append({"role": "E3", "llm": info, "critique": co.model_dump() if isinstance(co, CritiqueOut) else None, "target": "G1 proposal" if target else "scout claim"})  # fmt: skip
    out["usage"] = store.usage(sid)
    out["lineage"] = {
        "sources": sorted(verified),
        "tests_cited": sorted({t for p in proposals for t in p["proposal"]["cites_tests"]}),
        "journal": "artifacts/army/journal.jsonl (specialist_session_start / specialist_session_end)",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{sid}.json"
    path.write_text(json.dumps(out, indent=1, default=str))
    store.log("F1", "specialist_session_end", {"session": sid, "artifact": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "proposals": [(p["by"], p["validation"]["status"]) for p in proposals]})  # fmt: skip
    return out


def revalidate(path: Path, reason: str) -> dict[str, Any]:
    """Re-run the CURRENT deterministic validators on a recorded session (no LLM call). The original verdicts are
    kept; the new ones are appended under `revalidations` and journaled."""
    from ..quant.stats import TestRegistry

    store = Store()
    d = json.loads(path.read_text())
    rows = TestRegistry(store).rows()
    srcs = set(d.get("lineage", {}).get("sources", []))
    others = {k for k in _prior_keys() if k not in {p["validation"]["key"] for p in d["proposals"]}}
    new = []
    for p in d["proposals"]:
        v = validate_proposal(ProposalOut(**p["proposal"]), rows, others, srcs)
        new.append({"by": p["by"], "original": p["validation"]["status"], "now": v})
        if v["status"] != "queued_prospective":
            p["validation"] = {**v, "superseded": p["validation"]}
    d.setdefault("revalidations", []).append(
        {"utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "reason": reason, "results": new}
    )
    path.write_text(json.dumps(d, indent=1, default=str))
    store.log("F1", "specialist_revalidation", {"session": d["session"], "reason": reason, "results": [(r["by"], r["original"], r["now"]["status"]) for r in new]})  # fmt: skip
    return {"session": d["session"], "results": new}
