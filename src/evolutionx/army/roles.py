"""The 24 logical research roles (6 divisions x 4). Roles are activated per task; none runs permanently.

`impl` says honestly how a role works today:
  deterministic      - code only
  llm_optional       - code, plus at most one budgeted LLM call when available (deterministic fallback otherwise)
  delegates          - wraps an existing subsystem (research lab, forecasting engine, simulator)
These 24 research agents are distinct from the 256 simulated market participants of the simulator.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Role:
    id: str
    division: str
    title: str
    capability: str
    impl: str
    stage: str


ROLES: tuple[Role, ...] = (
    Role(
        "A1",
        "Research Intelligence",
        "Academic Research Scout",
        "query arXiv for quantitative-finance research (metadata + abstract)",
        "deterministic",
        "DISCOVER",
    ),
    Role(
        "A2",
        "Research Intelligence",
        "Strategy Discovery Scout",
        "query arXiv with strategy-oriented searches (public strategies, indicators)",
        "deterministic",
        "DISCOVER",
    ),
    Role(
        "A3",
        "Research Intelligence",
        "Evidence Verification Agent",
        "re-fetch the record, check dates/DOI via Crossref, grade evidence quality",
        "deterministic",
        "VERIFY",
    ),
    Role(
        "A4",
        "Research Intelligence",
        "Novelty and Deduplication Agent",
        "map ideas to mechanism signatures and compare with all earlier labs and cycles",
        "deterministic",
        "UNDERSTAND",
    ),
    Role(
        "B1",
        "Market Intelligence",
        "Market Data Analyst",
        "development-period price/volume/volatility diagnostics; fresh-data snapshot for monitoring",
        "deterministic",
        "UNDERSTAND",
    ),
    Role(
        "B2",
        "Market Intelligence",
        "Derivatives Analyst",
        "funding-rate statistics (development period, point-in-time)",
        "deterministic",
        "UNDERSTAND",
    ),
    Role(
        "B3",
        "Market Intelligence",
        "Regime Detection Agent",
        "volatility/trend regime labels on development data",
        "deterministic",
        "UNDERSTAND",
    ),
    Role(
        "B4",
        "Market Intelligence",
        "Feature Researcher",
        "catalogue of point-in-time features with availability rules",
        "deterministic",
        "UNDERSTAND",
    ),
    Role(
        "C1",
        "Strategy Discovery",
        "Trend and Momentum Researcher",
        "formulate trend/breakout hypotheses",
        "llm_optional",
        "FORMULATE",
    ),
    Role(
        "C2",
        "Strategy Discovery",
        "Mean-Reversion Researcher",
        "formulate reversal hypotheses",
        "llm_optional",
        "FORMULATE",
    ),
    Role(
        "C3",
        "Strategy Discovery",
        "Microstructure Researcher",
        "formulate volatility/funding/microstructure hypotheses; declare infeasible ones",
        "llm_optional",
        "FORMULATE",
    ),
    Role(
        "C4",
        "Strategy Discovery",
        "Strategy Synthesis Agent",
        "combine mechanisms only if each was validated",
        "deterministic",
        "FORMULATE",
    ),
    Role(
        "D1",
        "Engineering",
        "Research Software Architect",
        "typed contract checks; records interface gaps as code proposals",
        "deterministic",
        "IMPLEMENT",
    ),
    Role(
        "D2",
        "Engineering",
        "Strategy Implementation Agent",
        "render the hypothesis into a contract-conforming module from a reviewed template",
        "deterministic",
        "IMPLEMENT",
    ),
    Role(
        "D3",
        "Engineering",
        "Test Engineering Agent",
        "static contract check, causality (truncation) probe, determinism replay",
        "deterministic",
        "TEST",
    ),
    Role(
        "D4",
        "Engineering",
        "Security and Performance Agent",
        "sandbox availability, forbidden capabilities, runtime cost",
        "deterministic",
        "TEST",
    ),
    Role(
        "E1",
        "Scientific Validation",
        "Backtesting Scientist",
        "import into the research lab: premises, sandboxed screen, validation walk-forward",
        "delegates",
        "EVALUATE",
    ),
    Role(
        "E2",
        "Scientific Validation",
        "Statistical Validation Scientist",
        "baselines, DSR, trial counts, bootstrap, data-exposure labels",
        "deterministic",
        "EVALUATE",
    ),
    Role(
        "E3",
        "Scientific Validation",
        "Adversarial Researcher",
        "falsification battery on development data (+ optional LLM critique)",
        "llm_optional",
        "CHALLENGE",
    ),
    Role(
        "E4",
        "Scientific Validation",
        "Causal Simulation Researcher",
        "use the 256-agent simulator only for interaction mechanisms",
        "delegates",
        "EVALUATE",
    ),
    Role(
        "F1",
        "Evolution Council",
        "Chief Research Orchestrator",
        "schedules bounded tasks, budgets, retries, pause/stop",
        "deterministic",
        "ALL",
    ),
    Role(
        "F2",
        "Evolution Council",
        "Scientific Memory Curator",
        "knowledge graph: sources, hypotheses, candidates, results, edges",
        "deterministic",
        "ARCHIVE",
    ),
    Role(
        "F3",
        "Evolution Council",
        "Risk and Reliability Researcher",
        "tail risk of candidates; drift of prospective forecasts",
        "deterministic",
        "REASSESS",
    ),
    Role(
        "F4",
        "Evolution Council",
        "Evolution Coordinator",
        "rank next experiments by expected information per cost; recommend only",
        "llm_optional",
        "REASSESS",
    ),
)
ROLE = {r.id: r for r in ROLES}


def as_dicts() -> list[dict[str, str]]:
    return [asdict(r) for r in ROLES]
