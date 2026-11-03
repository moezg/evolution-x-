# Audit: requirement → implementation → command → artifact → status

Status vocabulary:

- **implemented**: code exists
- **executed**: it was run in this session
- **verified**: an automated test or recomputation checks it
- **unverified**: it exists but was not checked here
- **unavailable**: it could not be done in this environment

## 1. Re-check of the v0.1.0 claims (baseline commit `b89ad87`)

| v0.1 claim | Finding after re-reading code, tests and data |
|---|---|
| 256 agents, 2-venue synthetic market | **Confirmed**: `test_population_is_256_unique_stateful_agents` |
| Eval 4 seeds × 1 h per model | **Confirmed** (`evaluation/suite.py`). The statement "each component improves fit" is **withdrawn**: the 4-seed CIs overlap |
| Historical refs 5 / 2 / 2 days | **Confirmed**: 9 daily 1m files present. Only 1-minute BTC data: too short for strategy research, hence the new 2020–2026 perp dataset |
| Simulated volatility ~4.7× too high | **Confirmed** (21.4 vs 4.5 bps). After calibration: 16.5 bps, still ~3.7× |
| Vol-matched random walk beats the full model on some statistics | **Confirmed** (`artifacts/eval/report.md`) |
| Evolution 3 × 6, challenger rejected | **Confirmed**: rejection due to CI lower bound ≤ 0 |
| Council uses a mock | **Confirmed**: offline rules; no LLM key in this environment |
| Code proposals from a catalogue | **Confirmed** for v0.1. **Replaced** for strategies by a grammar-based generator that writes new source |
| Docker and CI written, not executed | **Still true**: Docker daemon unavailable; CI commands run locally instead |
| v0.1 code-evolution sandbox | **Weaker than claimed**: `unshare -rn` gave no network, but the candidate could write anywhere the user could (e.g. `artifacts/evolution.db`), and the frozen-suite scores were printed by the candidate's own process. **Superseded** for the research loop by the mount-namespace + chroot sandbox and an out-of-process evaluator |
| Replay mode (v0.1 "Mode B") | It injects historical bars as the latent fundamental of a synthetic book. It is **not** a reconstruction of historical executions; it is labelled `counterfactual_synthetic`. Historical backtesting is now a separate mode (`backtest/`) |
| Insurance fund | Could go negative without bound. **Fixed** (KC-1) |

## 2. Matrix

| Requirement | Implementation | Command | Artifact | Status |
|---|---|---|---|---|
| Reproducible baseline before changes | `research/audit.py` | `evox audit`, `evox audit --verify` | `artifacts/baseline/b89ad877b237/manifest.json` | executed, verified |
| Historical data with provenance, checksums, QC, UTC, units | `data/datasets.py` | `evox data --research` | `data/research/manifest.json` (copy in `docs/data/`) | executed, verified (all Binance checksums match) |
| No silent filling of missing data | gaps kept; engine cannot trade across gaps | — | `test_gap_blocks_trading_and_is_reported` | verified |
| Train / validation / final splits, vault | `evals/frozen/research_protocol.json`, `research/vault.py` | `evox research final-report` | `artifacts/research/final/` (ledger, preregistration) | executed once; blind on first reveal; now **consumed** |
| Historical backtest distinct from simulation | `backtest/` | `evox backtest` | — | executed |
| Causality (no future info, next-open execution) | `BarView` copies; physical-truncation checks at secret checkpoints | — | `test_execution_happens_at_next_open_not_decision_close`, leak tests | verified |
| Costs, slippage, funding, partial fills, rounding, margin, liquidation | `backtest/engine.py` | `--costs` multiplier | accounting identity on every run | verified (unit tests); impact coefficient **unvalidated** |
| Walk-forward with embargo | `backtest/walkforward.py` | — | `test_walk_forward_windows_are_chronological_with_embargo` | verified |
| Gross/net, DD, CVaR, turnover, exposure, holding, cost sensitivity | `backtest/metrics.py`, evaluator ×2 costs | — | per-task results in `research.db` | executed |
| Benchmarks | flat, buy&hold, frozen v0; turnover-matched random in `backtest/baselines.py` | final report | `final-2026-11-03.json` | executed (the random null is implemented but not used in the final report) |
| Trial accounting | `trials` table | — | `research.db` | executed |
| DSR | `stats/overfit.py` | — | `test_dsr_matches_bailey_lopez_de_prado_numerical_example` | verified |
| PBO (CSCV) | `stats/overfit.py` | — | `test_pbo_noise_is_near_half_and_true_edge_is_low` | verified as code; **not applied** to campaign results |
| Multiple comparisons | Holm in the final report | — | — | executed |
| Pre-registered protocol, sizes, stopping | task `preregistration_sha256`; final-report preregistration | — | `tasks.task` | executed |
| Persistent research state machine | `research/supervisor.py` | `evox research run/status` | `artifacts/research/*/research.db` | executed |
| Research memory incl. failures | `hypotheses`, `candidates`, `experiments` | API `/api/research/*` | — | executed |
| Duplicate detection / novelty | signatures, code hashes, exhaustion stop | — | `test_exhausted_search_space_…` | verified |
| CandidateGenerator writing new code | `research/generator.py` (offline) | — | `candidates/*/patch.diff` | executed |
| Real LLM generator | `research/llm_connectors.py::ClaudeCLIGenerator` (official `claude -p`, no tools, bounded); API-key adapters unused | `evox research run --generator claude-cli` | `artifacts/research/claude_cli/` (journal, `llm_raw/`) | executed (1 valid call); API-key path unavailable |
| Session-written candidates | `Supervisor.import_candidate` (provenance + declared exposure) | `evox research import` | `artifacts/research/claude_session/`, `research_inputs/claude_session/` | executed |
| Isolated execution | `research/sandbox.py` (userns + mountns + netns + chroot + rlimits) | — | `test_H_*` | verified (Linux only) |
| Independent evaluator recomputing from traces | `research/evaluator.py` | — | `test_H_sandbox_blocks_escape_and_forged_reports` | verified |
| Generator cannot write the registry | process boundary + hidden `artifacts/` | — | same | verified |
| Atomic activation, effect on next run, rollback | `research/registry.py` | `evox research rollback`, `evox backtest --strategy champion` | `registry/active.json`, `history.jsonl`, branch `experimental/research` | verified (MECH); no real promotion occurred |
| Post-activation control + auto rollback | `Supervisor.smoke_check` (validation tail + canary) | — | `test_F_automatic_rollback_on_post_activation_failure` | verified |
| Budgets, caps, stop priority, resume | `evals/frozen/research_policy.json`, STOP file | `evox research stop`, `resume --confirm` | `test_budget_caps_cannot_be_raised`, `test_user_stop_…` | verified |
| Checkpoint/resume without duplication | stage checkpoints, experiment cache | — | `test_I_crash_and_resume_without_duplicate_experiments` | verified |
| Append-only journal with integrity check outside the candidate | `research/journal.py` | `evox research verify` | `journal.jsonl` | verified |
| Calibration as a separate experiment | `evaluation/calibration.py` | `evox calibrate` | `artifacts/calibration/report.json` | executed |
| Kernel accounting changes reviewed separately | KC-1 | — | `docs/KERNEL_CHANGES.md`, reference tests | verified |
| Dashboard research page | `web/src/app/research` | `make dev` | — | see `STATUS.md` |
| Docker / CI | `Dockerfile`, `.github/workflows/ci.yml` | — | — | **unavailable / unverified** |

## v0.3 additions

| Requirement | Implementation | Command | Artifact | Status |
|---|---|---|---|---|
| Understand the system before proposing | `research/context.py` dossier | automatic before LLM generation | `artifacts/research/*/dossiers/*.json` | executed |
| Verify premises before backtests | `research/premises.py`, PREMISES stage | automatic | `premise_check` in tasks; `premise_audit/cli2_premises.json` | verified (tests) |
| Detect the rebalance misconception | probe + measured ratio | `pytest tests/test_premises.py` | — | verified |
| Exploit existing memory | reclassification + lessons + per-change-type summary | `evox reclassify --roots …` | `analysis/reclassification_summary.json` | executed |
| Compare research methods A/B/C | `research/compare.py`, frozen protocol | `evox compare --tag p1 --arms A,B,C --tasks 3` | `artifacts/research/comparisons/p1.json` | pilot executed; full study not run (quota approval needed) |
| Reserved evaluation data | `data/vault_v2.py` | `python -c "from evolutionx.data.vault_v2 import build; build()"` | `data/vault_v2/manifest.json` | built, unrevealed |
| Simple references with comparable risk | constant-long reference in validation critique | automatic | `validation_summary.reference_buy_and_hold` | executed |
| Separate simulator calibration | H-cal-1 sensitivity | `run_mm_sensitivity()` | `artifacts/calibration/mm_sensitivity.json` | executed, hypothesis refuted |

## v0.4 capability matrix: Emergent Behavior Observatory mission (2026-11-03)

Statuses use the mission vocabulary: **IMPLEMENTED / PARTIAL / MISSING / UNVERIFIED**.
- Evidence comes from executable probes: `evox observatory audit` writes `artifacts/observatory/audit.json` (seed 11, 900 s, default config).
- Code refs are emitted by the probe itself, from a regex over the current source.

### Intended vs actual architecture

| Capability | Status | Evidence (from `audit.json` unless noted) | Code |
|---|---|---|---|
| 256 heterogeneous agents | IMPLEMENTED | 256 agents, 10 kinds, 256 distinct parameter sets | `agents/population.py:23` |
| Independent agent state | IMPLEMENTED | 256 distinct RNG states, all advanced; 256 distinct memory objects; finite capital and margin checks | `agents/base.py:91` |
| Limited, delayed information | IMPLEMENTED | Observations are built from snapshots at t − latency; the fundamental is a private noisy signal for value/whale only | `sim/simulation.py:204` |
| Interaction through the order book | IMPLEMENTED | 10,363 trades; 98.4% of volume is between different kinds | `kernel/orderbook.py:64` |
| Endogenous prices | IMPLEMENTED (with a caveat) | All agents inactive → the mid never moves while the fundamental does. **Caveat:** market makers blend a lagged public index (index_w 0.2) into their quotes | `strategies/market_maker.py:16` |
| Communication / social influence | IMPLEMENTED | 23 influence events and 11 imitations; cutting the social channel changes the trade fingerprint. Users of the signal: noise, momentum, leveraged, adaptive | `agents/social.py:11` |
| Leverage and liquidations | IMPLEMENTED | Engine rule tested. **0 agent liquidations** in the default run, in all A runs and in all C runs (only the external whale is liquidated) | `kernel/exchange.py:186` |
| Cross-venue arbitrage | **PARTIAL** (implemented, inactive) | 0 arbitrage orders. Mean mid gap 1.3 bps vs a 12 bps trigger (2 taker fees + threshold) | `strategies/arbitrage.py:11` |
| News-reactive agents | PARTIAL | Synthetic random headlines with a sentiment number; no text, no real feed | `sim/world.py:18` |
| Adaptive / learning agents | PARTIAL | Softmax bandit over 4 fixed modes plus imitation of better peers; no model of other agents | `strategies/adaptive.py:15` |
| LLM-assisted market agents | MISSING | By design: no market agent calls an LLM | — |
| LLM research council | PARTIAL | Deterministic mock by default; `claude -p` is used only by the research generator | — |
| Sandboxed, auditable code evolution | IMPLEMENTED | Namespace sandbox available; hash-chained journal; `tests/test_research.py` | `research/sandbox.py:110` |
| Historical replay | PARTIAL | Mode B replays closes as the fundamental, not historical order flow | `sim/replay.py` |
| Emergent Behavior Observatory | PARTIAL (new) | 8 detectors with a stated programmed basis; paired-seed ablations; experiments A/B/C. Panic, cascade and endogenous maker-withdrawal detectors **never fired** in registered runs; they are tested on constructed inputs only | `observatory/metrics.py`, `observatory/experiments.py` |
| Realism track with a Pareto archive | IMPLEMENTED (new) | Frozen rules sha256-locked; allow-listed candidate space; "not an improvement" returned for 5 of 5 candidates vs default | `observatory/realism.py` |
| Docker / CI | UNVERIFIED | No Docker daemon; CI never ran on a remote | `Dockerfile`, `.github/workflows/ci.yml` |

### Requirements of this mission

| Requirement | Implementation | Command | Artifact | Status |
|---|---|---|---|---|
| Verifiable baseline / capability audit | `observatory/audit.py` | `evox observatory audit` | `artifacts/observatory/audit.json` | executed |
| Volatility diagnosis (falsifiable, one factor at a time, no corrective constant) | `observatory/volatility.py`, `observatory/market_stats.py`; frozen `volatility_diagnosis_v1.json` plus amendment_v2 | `evox observatory volatility --tag v1` / `--tag v2` | `volatility_v1.json`, `volatility_v2_amplification.json` | executed; 2 causes measured, 5 alternatives refuted |
| Market-maker withdrawal shock | `sim/config.py` ShockType, `sim/simulation.py`, scenario `mm_withdrawal_90`, dashboard shock panel | — | — | verified (tests) |
| Observatory detectors | `observatory/sampler.py`, `observatory/metrics.py` | — | per-run `metrics` in `experiments_v1.json` | verified on constructed inputs; executed |
| Programmed vs emergent | paired ablations (no_social, zero_intelligence, leveraged absent) and labels in the frozen spec | `evox observatory experiments` | `experiments_v1.json` | executed |
| Experiments A/B/C | `observatory/experiments.py`, frozen `observatory_experiments_v1.json` plus amendment 1 | same | same | executed (56 runs) |
| Scientific-quality evolution track | `observatory/realism.py`, frozen `realism_track_v2.json` (v1 superseded, reasons inside) | `evox observatory realism` | `realism_v2.json`, `realism_archive_v2.json` (v1 kept) | executed |
| Track cannot rewrite its rules | sha256 lock and allow-list | `pytest tests/test_observatory.py -k "rules or touch"` | — | verified |
| Dashboard | `/api/observatory/*` (`api/observatory_routes.py`), `web/src/app/observatory` | `make dev` | — | see delivery message |
| Holdout / LLM budget untouched | no code path in `observatory/` reads vault v2 or calls an LLM | `grep -r "vault\|claude" src/evolutionx/observatory` | — | verified by inspection (the only match is a descriptive string in `audit.py`) |

## v0.5: liquidation cascade threshold mission (2026-11-03)

### Inspection before implementation (code facts used to design C2)
| Question | Finding | Code |
|---|---|---|
| Margin accounting | Breach when equity < 0.02 × gross notional, checked once per 1 s tick on mids. The whole position goes out as a forced IOC market order on each non-halted venue; while the account stays in breach, the unfilled remainder is retried every tick | `kernel/clearing.py` `needs_liquidation`; `kernel/exchange.py` `run_liquidations` |
| Margin distance vs leverage | Breach after a uniform move x with E + N·x < mm·G·(1+x), so x* = (mm·G − E)/(N − mm·G). At 20× long that is about 3% | `observatory/cascade.py` `margin_distance`; property test against the engine |
| Meaning of `leverage_use` | Target = signal × min(equity, 2 × capital) × 20 × leverage_use; flat if \|signal\| < 0.25. Each agent's value is the centre ±30%, clipped to [0.1, 1.0]. Pre-trade cap: gross ≤ 20 × equity | `strategies/leveraged.py`, `agents/population.py`, `kernel/clearing.py` `can_take` |
| Other exits before margin | Stop-loss at about 150 bps, checked only on wake; funding term subtracted from the signal | `strategies/leveraged.py` |
| `size_scale` defect | C2 varies `param_overrides.leveraged.leverage_use`, never `size_scale`; `size_scale['leveraged']` raises | `agents/population.py` (v0.4) |
| Primary shock | External whale builds a long (market-buy chunks from 60 s to shock − 120 s), its collateral is cut to 1% of gross, and the engine liquidates it. **The build-up saturates near 1,500–1,800 BTC** | `sim/simulation.py` `_setup_whale`, `_shock` |

### Requirements
| Requirement | Implementation | Command | Artifact | Status |
|---|---|---|---|---|
| Pre-registered protocol | `evals/frozen/cascade_c2_v1.json` (+ amendments 1–2 before confirmatory runs) | — | — | written before runs |
| Breach vs executed liquidation; primary vs secondary | KC-2 (`docs/KERNEL_CHANGES.md`) | — | `breaches`, `role` in each run | verified (tests) |
| Arm B counterfactual | `SimConfig.execute_secondary_liquidations` | — | — | verified; default neutral (baseline and v0.4 fingerprints reproduce) |
| C2 executable, reproducible seeds | `observatory/cascade.py` | `evox observatory cascade --role pilot` / `--role confirmatory` | `cascade_c2_pilot.json`, `cascade_c2_confirmatory.json` | executed (12 + 96 runs) |
| Causal comparison | paired A − B, per-second trade-tape hashes for divergence | same | same | executed: 48/48 pairs identical |
| Threshold analysis | `_threshold`, Wilson intervals, no curve fit | same | `threshold` | executed: not observed within the tested range |
| Mechanism (exploratory) | X1 positioning ablation, X2 counterfactual variant, deleveraging traces, scale check | `evox observatory cascade-x` | `cascade_c2x_exploratory.json` | executed (48 runs) |
| Research memory / self-evolution | `observatory/knowledge.py` on `research/memory.py` | `evox observatory knowledge` | `knowledge.db`, `knowledge_c2.json` | executed; proposals evaluated, none applied |
| API | `/api/observatory/cascade`, `/cascade/pair`, `/knowledge` | — | — | executed |
| Dashboard | `web/src/app/observatory/cascade` | `make dev` | — | see delivery message |
| No holdout / LLM / exchange | no code path in `observatory/` touches the vault, an LLM or a network | `grep -rn "vault\|claude\|httpx" src/evolutionx/observatory` | — | verified by inspection |

## Predictive intelligence foundation (2026-11-03)

The reuse audit is in `docs/FORECASTING.md`. Requirements of the mission:

| # | Requirement | Implementation | Command | Status |
|---|---|---|---|---|
| 1 | Audit of reusable components | `docs/FORECASTING.md` reuse table | — | done |
| 2 | General forecasting engine, pluggable domains | `forecast/domain.py` (`Domain` protocol, `DOMAINS`) | — | implemented (1 domain) |
| 3 | BTC forecasting with point-in-time data | `forecast/data.py`, `BTCDomain` (24 h publication lag) | `evox forecast fetch` | executed; leakage test passes |
| 4 | Verifiable targets: RV, 3–5% moves, direction, explicit horizons | `btc_targets()` (24 h, 72 h) | — | implemented; outcome test passes |
| 5 | Statistical and ML baselines before any LLM | B0, B1, M1, M2 (numpy) | — | executed |
| 6 | Experimental hybrid with simulator features | `forecast/simfeatures.py`, H1 | `evox forecast backtest` | executed (119 cells) |
| 7 | Strict rolling-origin backtest, no leakage | `forecast/backtest.py` | same | executed; label-availability test passes. Fees: not applicable (no trading) |
| 8 | Brier, log loss, calibration, baseline comparison | `forecast/scoring.py`; Holm, block bootstrap | same | executed |
| 9 | Does the simulator add skill? Exclude it if not | pre-registered inclusion rule | same | **EXCLUDED** |
| 10 | Append-only forecast ledger | `forecast/ledger.py` on `research/journal.py` | `evox forecast score` | verified (tests; chain ok) |
| 11 | Prospective paper-forecasting mode | `forecast/prospective.py` | `evox forecast issue`, `evox forecast resolve` | 32 forecasts issued; resolution pending |
| 12 | Evolution against frozen baselines with safeguards | `forecast/evolve.py` (frozen space, trial-adjusted threshold, dedup, challenger only) | `evox forecast evolve` | executed: 9/9 rejected |
| 13 | Abstention | 4 rules plus a stale-data rule at issue time; abstention scored as climatology | — | executed |
| 14 | Dashboard | `/api/forecast/*`, `web/src/app/forecast` | `make dev` | see delivery message |
| — | Holdouts | SOL/BNB vault never read; consumed BTC/ETH split labelled CONSUMED, never fresh | `grep -rn vault_v2 src/evolutionx/forecast` | verified |

## v0.6 research army (2026-11-03)

| Requirement | Implementation | Command | Status |
|---|---|---|---|
| Stage A fixes verified; 404 diagnosed | `api/paths.py`, tests in `tests/test_forecast.py` | `curl /api/health` | verified |
| 24 roles, on-demand activation | `army/roles.py`, `army/stages.py` | `GET /api/army/roles` | implemented (honest impl labels) |
| Durable, restartable pipeline: queues, scheduling, cancellation, checkpoints, retries, budgets, dedup, priorities, progress | `army/orchestrator.py`, `army/store.py` | `evox army run` / `tick` / `pause` / `stop` / `resume` | executed (3 cycles); verified (tests) |
| Controlled research ingestion with provenance | `army/sources.py` | — | arXiv + Crossref work; others disabled with reasons |
| Untrusted content cannot instruct agents | delimiting, schemas, allow-lists | `pytest tests/test_army.py -k "untrusted or llm_output"` | verified |
| Knowledge memory reuses the existing memory | research `Memory` schema + graph tables | `GET /api/army/memory`, `/graph`, `/lineage/{id}` | executed |
| Duplicate mechanisms recognized; failed ideas remembered; re-examination possible | `army/mechanisms.py`, `reclassify_sources` | — | executed (6 duplicates, 1 reclassification) |
| No future or protected results in researcher context | `policy.scrub_context` | test | verified |
| Strategy evolution: templates, lineage, champion/challenger, baselines | `army/mechanisms.py`, E1 via `research/supervisor.py` | — | executed: 3 candidates, 0 promotions |
| Overfitting protection | lab walk-forward, all-lab trial count (54), DSR, block bootstrap, adversarial battery, exposure labels | — | executed |
| Read-only live observation and drift trigger | `army/drift.py`, `forecast_live` | — | executed (0 resolved yet) |
| Self-evolving code in isolated workspaces, human merge | `army/codeprop.py` | — | executed (1 pending review); protected-path block tested |
| Dashboard `/research-army` | `api/army_routes.py`, `web/src/app/research-army` | `make dev` | see delivery message |
| No trading, no holdout access | no order code; `vault_v2` never read | `grep -rn "vault_v2" src/evolutionx/army` | verified |

## Quantitative intelligence (2026-11-03)

| Requirement | Implementation | Command | Status |
|---|---|---|---|
| 12 specialist roles (G1–G4, H1–H4, I1–I4) | `army/roles.py`, `quant/workflow.py` | `GET /api/army/roles` | implemented; G4/I3/I4 record data gaps (honest) |
| Event Registry: versioned, provenance, as-known | `quant/events.py` → `data/quant/events/registry.jsonl` | `evox quant events` | executed (128 events, hash chain ok) |
| Universal Event Study Engine | `quant/eventstudy.py` | `evox quant run` | executed (FOMC hourly; elections daily, 3 assets) |
| Systematic day-of-month scanner incl. the 14th | `quant/calendar.py` | same | executed (124 tests; 14th rejected) |
| Election-cycle study with sample-size disclosure | `eventstudy.election_study` | same | executed (descriptive only) |
| FOMC event study (authoritative dates) | federalreserve.gov + FRED | same | executed (absret 4 h supported) |
| Statistical testing registry + multiple comparisons | `quant/stats.py` (`stat_tests`) | `GET /api/quant/tests` | 263 tests recorded |
| Research memory integration | `q_memory` → hypotheses + graph edges | `GET /api/army/memory` | 258 records |
| One discovery workflow involving the agents | army orchestrator, `{"workflow": "quant"}` | `evox quant run` | executed (15 tasks) |
| Forecasting integration where incremental skill can be evaluated | `quant/forecast_link.py` | same; challengers via `forecast_live` | executed; 1 challenger feature issued prospectively |
| False anomalies not promoted; planted signals recovered | `tests/test_quant.py` | `pytest tests/test_quant.py` | verified (see QUANT.md) |
| Dashboard backed by results | `api/quant_routes.py`, `web/src/app/quant` | `make dev` | see delivery message |
| No holdout / no LLM campaign | no vault access; 0 LLM calls | `grep -rn vault_v2 src/evolutionx/quant` | verified |
