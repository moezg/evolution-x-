# Research laboratory: architecture, trust boundary, autonomy levels

This document describes what is implemented and how it is enforced. Results are in [STATUS.md](STATUS.md); the
requirement-by-requirement audit is in [AUDIT.md](AUDIT.md).

## Three separate scientific questions

| | Question | Where it is answered | What would NOT answer it |
|---|---|---|---|
| A | Does the simulator reproduce observable market properties on data not used to calibrate it? | `evox calibrate` → `artifacts/calibration/report.json`; `evox eval` | Charts that look plausible; volatility matching alone |
| B | Does a strategy keep acceptable decisions and risk in causal historical backtests with documented execution assumptions? | `evox backtest`, research tasks (walk-forward + validation) and the final vault report | Simulator profits, which can exploit simulator defects |
| C | Does the self-evolution mechanism improve a pre-defined measure versus a frozen system at comparable budget? | `evox research run` (guided vs random arms) + `evox research final-report` | A promotion on a controlled example, which tests the mechanism, not progress |

## Research chain (persistent state machine)

`OBSERVE → HYPOTHESIZE → PROTOCOL → DESIGN → ADMISSIBILITY → EXPERIMENT → EVALUATE → CRITIQUE → DECIDE → ARCHIVE`

The supervisor executes each stage and persists a checkpoint after it. The stages are resumable and
idempotent, and identical experiments are cached by `(code sha, protocol sha, data sha)`.

| Role | Module | Can read | Can write |
|---|---|---|---|
| Formulation | `research/hypothesizer.py` | development-only diagnostics, research memory | a pre-registered task (hashed) |
| Construction | `research/generator.py` (offline grammar; LLM interface) | parent source, hypothesis | source text only |
| Execution | `research/sandbox.py` + `research/entry.py` | dev+validation bars it is given, its own source | `/out` decision arrays |
| Evaluation | `research/evaluator.py` (trusted) | decision arrays, data | experiment results |
| Critique | `research/critic.py` | computed results only | structured objections with metric refs |
| Decision and promotion | `research/supervisor.py` + `research/registry.py` | verified results, frozen protocol | registry, journal, memory |

Independence does not come from different LLM prompts. It comes from:

- **Data control:** the generator never sees validation or final data, and validation results never rank
  exploration parents.
- **Process boundaries:** candidate code runs only in the sandbox.
- **Recomputation:** the evaluator recomputes every number from validated decision arrays.
- **Frozen protocol:** the promotion rule is pre-registered in `evals/frozen/research_protocol.json`.

## Data and splits

- **Source:** Binance USD-M perpetual 1h klines and funding for BTCUSDT and ETHUSDT, 2020-01 to 2026-10.
  Binance SHA-256 checksums are verified, convention changes are detected (header rows, µs timestamps) and quality
  checks run (duplicates, alignment, OHLC validity, partial bars, gaps). Missing hours are never filled.
- **Splits:** development 2020–2023, validation 2024-01 to 2025-06, final 2025-07 to 2026-10.
- **Final split:**
  - It lives in `data/vault/` and is never mounted in sandboxes.
  - Reveals go through `Vault.reveal()` and are recorded in a ledger and the journal.
  - Once revealed, the split is consumed and later reports are labelled not blind.
  - Limitation: the trusted supervisor runs as the same OS user, so this is an audited procedure, not
    cryptographic isolation.

## Historical backtest (distinct from simulation and counterfactuals)

- **Strategy contract:** `signal(view, p) -> exposure in [-1, 1]`. `BarView` returns copies of closed bars only.
- **Execution:**
  - A decision made at bar t's close executes at bar t+1's open.
  - Costs: half the spread plus √-impact plus taker fee.
  - Fills are capped at 2% participation (partial fills), with lot rounding and a 5% rebalance band
    (protocol amendment v2, documented).
  - Historical funding is charged; leverage is capped at 2×.
  - Maintenance margin is 0.5%, with worst-case intrabar liquidation using the bar's high/low.
- **Not modelled with OHLCV:** queue priority and intrabar liquidity.
- **Accounting identity:** checked on every run.
- **Walk-forward:** 12-month inner selection window, 168-bar embargo, 3-month outer test windows, step of 3
  months.

## Anti-overfitting

- Every development and validation evaluation is recorded in the `trials` table.
- The Deflated Sharpe Ratio uses N = all validation trials so far. The implementation is validated against the
  numerical example in Bailey and López de Prado (2014): DSR 0.9004, SR0 0.1132.
- PBO via CSCV (Bailey et al.) is implemented and validated on null and edge cases. It is not applied to the
  campaign trial matrix yet.
- Holm–Bonferroni corrects the final multi-arm comparison.
- Paired stationary bootstrap is used for Sharpe differences. Its false-positive rate under the null is tested.
- Experiment sizes are fixed per campaign before it runs, with no sequential peeking.

## Trust boundary for code evolution

- **Isolation:** candidate code runs in fresh user, mount and network namespaces with `chroot` into a tmpfs root.
  - Read-only: `/usr /lib /etc`, the virtualenv, `src/`, and the per-run inputs.
  - Writable: `/out` and a 32 MiB `/tmp`.
  - Hidden: `data/`, the vault, `artifacts/` (registry, journal, memory) and tests.
  - No network. CPU, memory, file-size and open-file limits plus a wall-clock kill. Scrubbed environment.
- **Inputs:** each sandbox receives only the data files that run needs. Secret-checkpoint causality runs receive
  data physically truncated at the checkpoint.
- **Defence in depth:** static checks restrict imports to math/numpy and forbid file/system access and dunder
  access. They are not the boundary.
- **Output handling:** the evaluator never trusts candidate outputs beyond decision arrays. It never follows
  symlinks and ignores forged reports.
- **Promotion authority:** the generator cannot write the registry. Only the supervisor promotes, after reading
  verified results. A post-activation check (validation tail plus an edge-case canary) triggers an automatic
  rollback on failure.
- **Protected paths:** the kernel, backtest, stats, research, evaluation, data, frozen protocol/policy and tests.
- **Policy caps:** `evals/frozen/research_policy.json` caps tasks, wall-clock, disk, LLM tokens (0) and sandbox
  limits. Campaign requests are clipped to these caps.
- **Stop:** a STOP file halts the loop before the next stage. Only `resume --confirm` by a human clears it, and
  the system never restarts itself.
- **Git:** each promoted champion is committed to the local branch `experimental/research` via git plumbing.
  `main` and remotes are never touched, and nothing is pushed or deployed.

## Autonomy levels: what is actually operational

| Level | What changes | Status |
|---|---|---|
| 1. Parameter adaptation | Choice inside `PARAM_GRID` by walk-forward inner selection | Operational |
| 2. Strategy change | Signal family / filters (e.g. tsmom → breakout) | Operational (offline generator) |
| 3. Application code change | New strategy modules written as source, with diffs against the parent | Operational for the evolvable zone. The offline grammar generator writes new code. A lab-called `claude -p` connector wrote one free-form patch (refuted). A session-written patch was imported (refuted) |
| 4. Research-process optimisation | Experiment-selection policy (guided vs random) compared at equal budget | Comparison implemented and run (see STATUS) |

None of this changes foundation-model weights. Code and prompt changes are not weight updates.
