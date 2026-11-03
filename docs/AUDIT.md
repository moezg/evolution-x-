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
| Real LLM generator | `LLMGenerator` | `EVOX_LLM=anthropic` + key | — | implemented, **unavailable** (no key); never run |
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
