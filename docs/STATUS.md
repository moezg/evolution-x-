# Status: v0.2 research laboratory (2026-11-03)

- **Initial commit:** `b89ad87`, with its reproducible baseline in `artifacts/baseline/b89ad877b237/manifest.json`.
- **Commits since:** see `git log b89ad87..HEAD`.
- **Machine:** 4-vCPU Intel Xeon 2.1 GHz Linux container, Python 3.13.18.
- **Provenance labels:** **[HIST]** historical backtest on Binance data, **[SYN]** synthetic simulator,
  **[MECH]** controlled mechanism test, which is not evidence about markets.

## Headline results (negative and inconclusive results kept)

1. **Question C, value of self-evolution [HIST]: no progress demonstrated.**
   - Setup: two autonomous campaigns at equal budget (20 tasks each, offline generator, guided vs random
     experiment selection). Each promoted nothing under the frozen promotion rule.
   - Final vault (2025-07 to 2026-10, revealed once, blind, plan pre-registered): both arms' champions are the
     frozen v0. Paired ΔSharpe = 0, Holm: no rejection.
   - Exploratory picks (best development Sharpe per arm) showed higher final Sharpe than v0:
     - guided: +0.26, 95% CI [−0.81, +1.58];
     - random: +0.53, 95% CI [−0.19, +1.41].
   - The CIs include 0 and these picks were never selected on validation, so this is not evidence of progress.
2. **Question B, strategy robustness [HIST]: no generated strategy passed validation.**
   - 33 validation trials in total. The best paired ΔSharpe vs v0 on validation was +0.53 (P = 0.80, DSR 0.45),
     below the pre-registered threshold P ≥ 0.95 and DSR ≥ 0.90.
   - Strong development-period gains (walk-forward OOS Sharpe up to 1.14 vs −0.01) did not carry over with
     enough confidence. This is consistent with search overfitting on development data.
3. **Question A, simulator realism [SYN vs HIST targets]: calibration helped slightly, not significantly.**
   - Mean stylized-fact distance on validation days fell from 2.71 to 2.27 and on held-out days from 2.36 to
     1.94 (6 seeds). The 95% CIs overlap: default [1.61, 3.20], calibrated [1.09, 2.90] on held-out days.
   - 1-minute volatility is still 3.7× too high (16.5 vs ~4.5 bps).
4. **Mechanisms [MECH]: verified by tests.**
   - Leak detection, promotion with real activation, automatic rollback, crash/resume without duplication,
     sandbox escape attempts, user stop, and budget caps.

## Claude-driven cycles (added after the user's request to test with the Claude plan)

Two kinds of LLM involvement, kept separate and labelled:

| | Session-driven cycle | Lab-callable connector |
|---|---|---|
| Who wrote the hypothesis and code | Claude in this interactive Claude Code session (claude-opus-5-5), human-driven | `claude -p` (official CLI, the environment's existing authentication; can use plan quota), called by the supervisor |
| How it entered the lab | `evox research import` with declared provenance and exposure | `evox research run --generator claude-cli` |
| What the author had seen | development diagnostics, **validation outcomes of 33 trials, the final-vault report** (declared; the validation test is not independent of the author's knowledge) | development diagnostics and earlier ideas with their development-screen results only; no tools, 1 turn |
| Candidate | `sess-a74fc0848b`: multi-horizon trend ensemble (outside the offline grammar). Code and hypothesis committed before evaluation (`58a6b32`) | `llm-…`: rounds the target exposure to steps of 0.25/0.5 to cut small rebalances |
| Development screen | passed (0.28 vs −0.01) but beat v0 in only 10/24 windows | passed (0.32 vs −0.01) |
| Validation (frozen rule) | **refuted**: ΔSharpe −0.61, 90% CI [−1.16, −0.12], P = 0.025, DSR 0.04 (N = 34) | **refuted**: ΔSharpe −0.47, 90% CI [−0.94, −0.00], P = 0.05, DSR 0.04 (N recorded as 68, a double-count since corrected to 35; verdict unaffected) |
| Cost | n/a (session) | 1 valid call: 10,029 tokens, $0.05 list-price equivalent, 25 s. An earlier campaign `cli-1` made 2 calls whose outputs failed schema validation; their usage was **not recorded** because of a bug, now fixed and regression-tested |

Observations:

- The lab-callable model explained its proposal by saying the executor rebalances on every small signal change.
  That is wrong: the engine already has a 5% rebalance band, which the prompt did not mention. The independent
  evaluation still applied unchanged.
- Neither LLM candidate was promoted.
- The lab cannot call a model unattended beyond the policy caps: at most 3 calls and $2 equivalent per campaign,
  no tools. The policy amendment v1→v2 that enabled this was authorized by the user.

## Acceptance evidence (A–J)

| | Evidence | Status |
|---|---|---|
| A | `evox audit`. Baseline for `b89ad87`: 48/48 tests passed, sim fingerprints recorded. `evox audit --verify …` still reproduces them after the kernel change KC-1 | Executed, verified |
| B | `evox backtest`, research tasks, final report: causal engine on 2020–2026 BTC/ETH perp 1h with fees, spread, √-impact, participation cap, funding, lot rounding, margin and liquidation; 12 walk-forward windows per instrument | Executed |
| C | `tests/test_backtest.py::test_leaky_strategy_is_detected` and `tests/test_research.py::test_H_leak_through_input_file_is_caught_by_physical_truncation` (detected even with static checks bypassed) | Executed, passing |
| D | `evox calibrate`, `artifacts/calibration/report.json`: train-only search, evaluated on validation and held-out days; unfavourable (non-significant) result kept | Executed |
| E | Autonomous cycle with an offline-generated patch: `test_E_autonomous_cycle_with_generated_patch`, plus 40 real tasks in `artifacts/research/arm_*` (offline grammar generator). Plus one session-driven Claude cycle (`claude_session`) and one lab-called `claude -p` cycle (`claude_cli`), both refuted | Executed |
| F | `test_F_controlled_promotion_changes_next_run`, `test_F_automatic_rollback_on_post_activation_failure`, `test_manual_rollback`. Mechanism tests on planted synthetic data, not discoveries | Executed, passing |
| G | Guided vs random vs frozen at equal budget, final vault: no progress demonstrated | Executed |
| H | `test_H_*`: hidden registry, vault and data; read-only src and tests; no network; scrubbed secrets; symlink and forged-report outputs ignored; CPU exhaustion killed; out-of-scope patch and leverage exploit rejected | Executed, passing |
| I | `test_I_crash_and_resume_without_duplicate_experiments`, `test_user_stop_has_priority_and_needs_human_resume` | Executed, passing |
| J | Dashboard `/research` page reading the real lab state (see `web/README.md`, screenshots in the session) | See section below |

## Research campaigns (all kept, including superseded runs)

| Lab | Tasks | Outcome | Notes |
|---|---|---|---|
| `arm_guided` (g3) | 20 | 0 promoted, 7 refuted, 13 inconclusive | 304 s, 280 sandbox runs, 0 LLM tokens |
| `arm_random` (r3) | 20 | 0 promoted, 14 refuted, 6 inconclusive | 229 s, 280 sandbox runs |
| `*_run1_superseded` | 12 / partial | — | The selector re-proposed duplicates after exhausting operators. Fixed by exploration parents and early stop |
| `*_run2_superseded` | partial | — | The design-parent fix had not been applied (silent failed edit). Fixed, with a regression test |
| `smoke`, `pilot` | 2, 1 | refuted | Pilot cost: 20 s per task (first task includes the champion evaluation), 4.7 MB |

Validation-split usage: 33 trials (18 guided + 15 random). Its evidential value is reduced accordingly.

**Example lineage (guided arm).** Each candidate is the parent of the next:
`v0 → cand-92b0 (change_horizon) → cand-398e (add_deadzone) → cand-d760 (add_vol_target) → cand-6d40 (add_vol_target) → cand-9b9d (add_funding_guard) → cand-dbef (add_deadzone)`

- **Task `g3-t016`:**
  - Pre-registration sha `b65fe3e6…`.
  - Hypothesis: "Ignoring weak signals reduces transaction costs enough to raise net Sharpe".
  - Chosen because trading costs = 0.32 × |gross PnL| in development diagnostics.
- **Development screen:** OOS Sharpe 1.14 vs −0.01; the candidate beats the champion in 18/24 windows.
- **Validation:** ΔSharpe +0.525, 90% CI [−0.54, +1.54], P = 0.80, DSR 0.45 (N = 14).
- **Verdict:** inconclusive. Not promoted.

## Simulator (question A) details

- **Calibration knobs:** per-population order-size scales and latent volatility. 16 configs × 2 seeds (train),
  then 6 new seeds for evaluation.
- **Sensitivity** (d log vol / d log knob): momentum size +0.20, value size −0.33, market-maker size −0.01.
- **Liquidity supply** (`artifacts/analysis/liquidity_supply.json`):
  - Market makers provide 68% of the depth within 20 bps.
  - In the 70% drought, MM depth falls 123 → 36 BTC but total depth only 181 → 92 BTC.
  - Value and execution limit orders remain, and the remaining depth still exceeds typical aggressive order
    sizes (0.03–4 BTC). This explains the small price effect of the drought scenario. It is a property of the
    population rules, not a bug.
- **Kernel change KC-1** (`docs/KERNEL_CHANGES.md`): the insurance fund is bounded and losses beyond it are
  socialised, with reference tests. Baseline fingerprints are unchanged.
- **Earlier v0.1 statement corrected:** "each agent component improves fit" was based on 4 seeds with
  overlapping CIs and is withdrawn as a claim.

## Verification status

| Item | Status |
|---|---|
| Static checks (ruff, format, pyright, bandit `-ll`) | Executed locally: pass |
| Test suite | 87 passed (last full run: 86 passed in 138 s before the trial-inheritance test was added) |
| GitHub Actions CI | Workflow written. **Not executed** (no remote); the same commands were run locally |
| Docker / Compose | **Unavailable**: no Docker daemon in this environment, not executed |
| LLM candidate generation | `claude -p` connector **executed** (1 valid call + 2 invalid outputs); the Anthropic/OpenAI API-key adapters remain unused (no key). The mock is never counted as an LLM experiment |
| Sandbox on macOS | **Unavailable** by design (needs Linux namespaces); see `docs/MACOS.md` |
| Real-money trading, order routing, pushes, deployments | Not implemented, by design |

## Limitations and next priorities

1. **Statistics:**
   - One campaign per arm. Process comparisons need multiple independent campaigns (seeds) before any claim.
   - The final vault is now consumed. A further blind test needs data after 2026-10, or another instrument or
     period not yet seen.
2. **Execution model (OHLCV only):** no queue position, no intrabar path, no L2 replay. Impact is a √-model
   with an unvalidated coefficient.
3. **Simulator:** volatility is still 3.7× too high. Next hypothesis to test: the volatility floor comes from
   market-maker quote structure (half-spread, level spacing, re-centring), which the calibration search did not
   vary.
4. **Generator:** the offline grammar has 7 operators, so the space is small. An LLM generator would widen it;
   it is untested here.
5. **PBO:** CSCV is implemented and validated but not yet applied to the full campaign trial matrix.
6. **Vault isolation:** it is audited (ledger and journal), not cryptographic. The supervisor runs as the same OS
   user.
