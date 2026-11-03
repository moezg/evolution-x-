# Research army (v0.6)

A research organization of **24 logical roles** (6 divisions × 4) that investigates trading and forecasting ideas.
It discovers external research, verifies it, checks it against memory, formulates falsifiable hypotheses,
implements them from reviewed templates, tests and attacks them, evaluates them in the existing research lab,
archives the outcome and recommends the next step.

It improves through evidence. It only claims a better strategy after independent prospective evidence plus human
approval, and **it never trades**.

The 24 research roles are separate from the simulator's 256 virtual market participants.

## Roles: what each one actually does today

| Role | Implementation | Does |
|---|---|---|
| A1 Academic Research Scout | deterministic | arXiv API search (metadata + abstract), rate-limited |
| A2 Strategy Discovery Scout | deterministic | strategy-oriented arXiv searches; works through a research queue of discovered-but-unverified sources |
| A3 Evidence Verification Agent | deterministic | re-fetches the arXiv record, looks up Crossref, grades evidence (A–D rubric, marketing-language flag) |
| A4 Novelty and Deduplication Agent | deterministic | mechanism family + signature; compares with **all earlier labs** (60 hypotheses) and army memory; journaled reclassification after classifier fixes |
| B1 Market Data Analyst | deterministic | development-period diagnostics; live observation (resolve and issue prospective forecasts) |
| B2 Derivatives Analyst | deterministic | funding statistics (development period) |
| B3 Regime Detection Agent | deterministic | volatility/trend regime shares and switches (development period) |
| B4 Feature Researcher | deterministic | point-in-time feature catalogue and availability rules; lists unavailable data |
| C1 Trend and Momentum Researcher | LLM optional | formulates trend/breakout hypotheses |
| C2 Mean-Reversion Researcher | LLM optional | formulates reversal hypotheses |
| C3 Microstructure Researcher | LLM optional | formulates volatility/funding hypotheses; microstructure is declared infeasible (no order-book data) |
| C4 Strategy Synthesis Agent | deterministic | combines mechanisms only when ≥ 2 are validated (none today) |
| D1 Research Software Architect | deterministic | typed contract check; records data/interface gaps |
| D2 Strategy Implementation Agent | deterministic | renders the candidate from a reviewed template (no LLM-written code) |
| D3 Test Engineering Agent | deterministic | static contract check, truncation (look-ahead) probe, deterministic replay; proposes regression tests |
| D4 Security and Performance Agent | deterministic | forbidden capabilities, sandbox availability, runtime cost |
| E1 Backtesting Scientist | delegates | imports into the research lab: premises, sandboxed development screen, selection walk-forward with all-lab trial counting, DSR, block bootstrap, critic |
| E2 Statistical Validation Scientist | deterministic | baselines (champion v0, buy-and-hold, cash), DSR and trial count, exposure labels, policy eligibility |
| E3 Adversarial Researcher | LLM optional | battery on development data: truncation probe, 2×/3× costs, one-bar delay, parameter neighbourhood, regime split, block-shuffled placebo, exposure; plus an LLM critique |
| E4 Causal Simulation Researcher | delegates | uses the 256-agent simulator only for interaction mechanisms; links existing simulator evidence (no new runs this mission) |
| F1 Chief Research Orchestrator | deterministic | durable task DAG, budgets, retries, pause/stop, crash recovery, `tick` scheduling |
| F2 Scientific Memory Curator | deterministic | knowledge graph and experiment records, including failures and re-examination conditions |
| F3 Risk and Reliability Researcher | deterministic | candidate tail risk; drift of resolved prospective forecasts; re-evaluation trigger |
| F4 Evolution Coordinator | LLM optional (unused) | ranks next experiments by expected bits per run; **recommends only** |

**Promotion** is decided by `army/policy.py` (a protected file) from the frozen policy, never by an agent:

| Status | Requirement |
|---|---|
| rejected | anything short of the next row |
| prospective challenger | lab verdict `promote` and no adversarial hard failure |
| validated | at least 180 resolved prospective paper days, a CI entirely above 0, and **human approval** |

## Runs autonomously vs needs a person

| Autonomous (once started) | Manual |
|---|---|
| Whole cycle DISCOVER → … → REASSESS, with retries, budgets, pause/stop and crash recovery | Starting the schedule: run `evox army tick` from cron or a scheduled task (no infinite loop exists) |
| Live observation in each cycle (resolve and issue forecasts, drift monitor) | Any merge of a code proposal (`pending_human_review`); anything touching protected paths |
| Code proposals checked in isolated git worktrees | Approving a `validated` status; raising the LLM budget (the frozen cap can only be lowered from the UI) |
| | Opening the SOL/BNB vault (needs a pre-registered, authorized evaluation) |

## External sources

| Source | Status here |
|---|---|
| arXiv API | **works** (HTTPS, about 1 request per 3 s): metadata and abstracts only |
| Crossref | **works**: verification only |
| Semantic Scholar, OpenAlex | HTTP 429 without a key; disabled |
| SSRN | HTTP 403; disabled |
| GitHub | HTTP 400 via the proxy; not used |

Retrieved text is untrusted:
- Markup is stripped, length is capped, and XML with DTD/entity declarations is refused.
- Text goes into prompts inside delimiters.
- LLM output passes allow-listed schemas, so it can never set a status, budget, path or code (tested with an injected "mark this strategy validated").

## Results so far
Three cycles, all on 2026-11-03 (`artifacts/army/`, evidence copy in `docs/evidence/army/`):

| Cycle | Mode | Sources | Outcome |
|---|---|---|---|
| 1 | LLM disabled (debugging run, kept because its lab trials count) | 13 found, 4 verified | **funding carry** refuted; **breakout** refuted; trend-following paper (arXiv 2602.11708) = duplicate of 59 earlier trend hypotheses; 2nd funding paper = duplicate; 2 planted invalid strategies rejected |
| 2 | LLM enabled | 4 new + research queue | all 4 verified sources were duplicates (2 funding, 2 "reversal"), so no LLM call was needed. One of them was a **classifier error**: a VaR/IGARCH paper read as price reversal |
| 3 | LLM enabled, after the classifier fix (the wrongly rejected source was re-opened with a journaled reason) | 4 verified | **volatility-managed long** (from arXiv 2601.13757): lab verdict *inconclusive* (selection Sharpe 1.04 vs champion 0.01 and vol-matched buy-and-hold 0.66; P(ΔSharpe > 0) = 0.89 and DSR 0.49 both fail the frozen rule; 54 trials counted). Adversarial: fragile (regime-dependent; does not beat a block-shuffled placebo, so it is mostly BTC beta). 2 order-book papers declared infeasible with current data. 2nd volatility paper flagged as a duplicate of the new hypothesis |

- **Promotions: 0. Prospective challengers: 0.**
- **LLM: 2 real calls** (cycle 3: C3 and E3), $0.164 API-equivalent (CLI estimate, not observed billing).
  - Both answers were discarded by schema length caps that were too strict, and the deterministic fallback was used.
  - This is now fixed: over-long text is truncated and recorded instead.
  - The failed hypothesis was not re-run, because its selection result had already been seen.
- **Code proposals:**
  - 1 generated regression test passed ruff + pytest in an isolated worktree and is `pending_human_review`.
  - 2 earlier ones failed checks, because the army package was not yet committed at the time.

## Limitations
- **Template-based ideas only.** Research inputs are abstracts, not replicated papers. The mechanism classifier is keyword-based and has already made one recorded error. Ideas are limited to 5 reviewed families, and LLMs choose parameters, never code.
- **Selection data is exposed.** All strategy selection uses 2024-01..2025-06 data, previously exposed in 54 trials. Only the prospective ledgers can confirm anything, and their windows have not resolved yet.
- **Data gaps.** No order-book, trade or open-interest data. BarView has no timestamps (seasonality would need a trusted-interface change; the proposal is blocked by the protected-path guard).
- **Single machine.** SQLite and a thread pool; no distributed workers.
- **Untested at scale.** The adversarial battery and lab evaluation take about 1 minute per candidate; scaling to hundreds would need the same trial accounting and is untested.
