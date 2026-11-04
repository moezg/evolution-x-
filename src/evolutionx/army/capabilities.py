"""P3 capability audit: what each of the 36 roles actually IS, measured against the code that runs.

Classes: llm_agent | deterministic_worker | tool_worker | orchestrator | evaluation_engine.
`llm` says whether and when a real LLM call happens. Deterministic tools are not presented as AI researchers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .roles import ROLES

OUT = Path("artifacts/army/capability_audit.json")

# role: (class, llm usage, what runs)
AUDIT: dict[str, tuple[str, str, str]] = {
    "A1": ("tool_worker", "on demand: specialist session (1 call; quote verified verbatim)", "arXiv API queries; in a specialist session an LLM selects one record and extracts a claim"),
    "A2": ("tool_worker", "never", "arXiv API queries with strategy-oriented terms"),
    "A3": ("tool_worker", "never", "re-fetch + Crossref match + rule-based evidence grade"),
    "A4": ("deterministic_worker", "never", "mechanism signatures compared with all earlier hypotheses"),
    "B1": ("deterministic_worker", "never", "price/volume/volatility diagnostics"),
    "B2": ("deterministic_worker", "never", "funding statistics"),
    "B3": ("deterministic_worker", "never", "regime labels"),
    "B4": ("deterministic_worker", "never", "feature catalogue with availability rules"),
    "C1": ("llm_agent", "optional: 1 budgeted call per cycle, deterministic template fallback", "hypothesis extraction from one source within a fixed template"),
    "C2": ("llm_agent", "optional: 1 budgeted call per cycle, deterministic template fallback (never activated so far)", "as C1"),
    "C3": ("llm_agent", "optional: 1 budgeted call per cycle, deterministic template fallback", "as C1"),
    "C4": ("evaluation_engine", "never", "policy rule: combine only validated mechanisms"),
    "D1": ("evaluation_engine", "never", "typed contract checks; gap proposals"),
    "D2": ("tool_worker", "never", "renders reviewed templates (no generated code)"),
    "D3": ("evaluation_engine", "never", "static check, causality probe, determinism replay"),
    "D4": ("evaluation_engine", "never", "sandbox and forbidden-capability checks"),
    "E1": ("tool_worker", "never", "delegates to the research lab (premises, screen, walk-forward)"),
    "E2": ("evaluation_engine", "never", "baselines, DSR, trial counts, bootstrap"),
    "E3": ("evaluation_engine", "optional critique (1 call per cycle / per specialist session)", "falsification battery; the LLM critique is advisory and never changes a status"),
    "E4": ("tool_worker", "never", "256-agent market simulator for interaction mechanisms"),
    "F1": ("orchestrator", "never", "durable task DAG, budgets, retries, pause/stop (army orchestrator + ops scheduler)"),
    "F2": ("deterministic_worker", "never", "memory / knowledge graph store"),
    "F3": ("evaluation_engine", "never", "tail risk; drift of resolved prospective forecasts"),
    "F4": ("deterministic_worker", "never (role registry previously said llm_optional; corrected)", "ranks next experiments by a fixed prior/cost rule"),
    "G1": ("deterministic_worker", "on demand: specialist session (1 call; citations and duplicates checked)", "forecast-link feature tests; in a specialist session an LLM proposes one hypothesis"),
    "G2": ("deterministic_worker", "never", "ACF / volatility clustering diagnostics"),
    "G3": ("deterministic_worker", "never", "periodogram band-rank tests"),
    "G4": ("deterministic_worker", "never", "NOT implemented: records the data gap"),
    "H1": ("deterministic_worker", "never", "calendar rotation scans"),
    "H2": ("deterministic_worker", "never", "event catalogue / coverage gaps"),
    "H3": ("evaluation_engine", "never", "stability checks across years and halves"),
    "H4": ("deterministic_worker", "never", "event x regime interaction tests"),
    "I1": ("deterministic_worker", "never", "statutory election dates + event studies"),
    "I2": ("tool_worker", "never", "federalreserve.gov + FRED ingestion, FOMC event study"),
    "I3": ("deterministic_worker", "never", "BLOCKED: records the CPI/NFP/GDP data gap"),
    "I4": ("deterministic_worker", "never", "cross-asset election responses; geopolitics not ingested"),
}  # fmt: skip

NOT_OPERATIONAL_AS_LLM_AGENTS = {
    "Strategy Designer": "C1-C3 formulate within reviewed templates; no free-form strategy design by an LLM (bounded budget, overfitting risk)",
    "Engineering Agent": "D2 renders templates; LLM-written code would need an isolated worktree + human review per change (codeprop exists for proposals) - not enabled in this slice",
    "Evolution Coordinator": "F4 is a deterministic ranking rule; no LLM involved",
}


def audit() -> dict[str, Any]:
    assert set(AUDIT) == {r.id for r in ROLES}
    by: dict[str, int] = {}
    for c, _, _ in AUDIT.values():
        by[c] = by.get(c, 0) + 1
    out = {
        "roles": {r.id: {"title": r.title, "class": AUDIT[r.id][0], "llm": AUDIT[r.id][1], "runs": AUDIT[r.id][2]} for r in ROLES},
        "by_class": by,
        "llm_capable_roles": sorted(k for k, v in AUDIT.items() if v[1] != "never" and not v[1].startswith("never")),
        "not_operational_as_llm_agents": NOT_OPERATIONAL_AS_LLM_AGENTS,
        "note": "the 256 simulated agents are market participants inside the simulator, not researchers",
    }  # fmt: skip
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    return out
