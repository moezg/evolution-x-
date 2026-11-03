"""The 36 logical research roles (9 divisions x 4). Roles are activated per task; none runs permanently.

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
QUANT_ROLES: tuple[Role, ...] = (
    Role(
        "G1",
        "Quantitative and Statistical Intelligence",
        "Quantitative Research Scientist",
        "turns supported findings into forecast features and tests incremental skill (F-FCAST)",
        "deterministic",
        "EVALUATE",
    ),
    Role(
        "G2",
        "Quantitative and Statistical Intelligence",
        "Time-Series Scientist",
        "ACF of returns and |returns|, volatility clustering diagnostics",
        "deterministic",
        "UNDERSTAND",
    ),
    Role(
        "G3",
        "Quantitative and Statistical Intelligence",
        "Cycle Discovery Scientist",
        "periodogram band-rank tests with stability checks (F-CYCLE)",
        "deterministic",
        "TEST",
    ),
    Role(
        "G4",
        "Quantitative and Statistical Intelligence",
        "Statistical Arbitrage Scientist",
        "cointegration / relative value - NOT implemented in this slice (needs a second spot asset); records the gap",
        "deterministic",
        "UNDERSTAND",
    ),
    Role(
        "H1",
        "Temporal and Calendar Intelligence",
        "Calendar Anomaly Scientist",
        "day-of-month (incl. the 14th), weekday, month, turn-of-month scans with rotation tests (F-DOM/DOW/MOY/TOM)",
        "deterministic",
        "TEST",
    ),
    Role(
        "H2",
        "Temporal and Calendar Intelligence",
        "Recurring Event Scientist",
        "catalogue of recurring events with data coverage (FOMC available; options expiry, index rebalances unavailable)",
        "deterministic",
        "UNDERSTAND",
    ),
    Role(
        "H3",
        "Temporal and Calendar Intelligence",
        "Multi-Scale Cycle Scientist",
        "stability of calendar effects and cycles across years and halves",
        "deterministic",
        "CHALLENGE",
    ),
    Role(
        "H4",
        "Temporal and Calendar Intelligence",
        "Cycle Interaction Scientist",
        "event x regime interactions with minimum cell sizes (F-XEVENT)",
        "deterministic",
        "TEST",
    ),
    Role(
        "I1",
        "Political, Macroeconomic and Geopolitical Intelligence",
        "Political Cycle Scientist",
        "U.S. presidential and midterm elections (statutory dates), per-asset event studies (F-ELECT)",
        "deterministic",
        "TEST",
    ),
    Role(
        "I2",
        "Political, Macroeconomic and Geopolitical Intelligence",
        "Monetary Policy Scientist",
        "FOMC calendar from federalreserve.gov, policy actions from FRED, hourly BTC event study (F-FOMC)",
        "deterministic",
        "TEST",
    ),
    Role(
        "I3",
        "Political, Macroeconomic and Geopolitical Intelligence",
        "Economic Calendar Scientist",
        "CPI/NFP/GDP release studies - BLOCKED (bls.gov HTTP 403, no consensus data); records the data gap",
        "deterministic",
        "UNDERSTAND",
    ),
    Role(
        "I4",
        "Political, Macroeconomic and Geopolitical Intelligence",
        "Geopolitical and Cross-Asset Scientist",
        "cross-asset election responses (BTC, 10y yield, S&P 500); geopolitical events NOT ingested (no verified timestamped source)",
        "deterministic",
        "UNDERSTAND",
    ),
)
ROLES = ROLES + QUANT_ROLES
ROLE = {r.id: r for r in ROLES}


def as_dicts() -> list[dict[str, str]]:
    return [asdict(r) for r in ROLES]
