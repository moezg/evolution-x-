# Status, measured results and limitations (v0.1.0, 2026-11-03)

All numbers below were produced by the commands shown, on a 4-vCPU Intel Xeon @ 2.10 GHz, Python 3.13.
Every result is from **synthetic** simulation unless labelled historical.

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| 256 unique, stateful agents in virtual time | Done | `tests/test_simulation.py::test_population_is_256_unique_stateful_agents` |
| Real order book with consistent executions | Done | Hypothesis property tests (`test_orderbook.py`, `test_accounting.py`); invariants checked every 60 virtual seconds in every run |
| Reproducible outcomes from seed and version | Done | Bit-identical event fingerprints (`test_same_seed_is_bit_identical...`); fingerprints stored in run manifests |
| ≥3 executable stress scenarios | Done (8) | `sim/scenarios.py`; all run under invariants in tests |
| Interactive dashboard connected to the simulation | Done | `web/` (Next.js static export) served by FastAPI; see `web/README.md` |
| Working population evolutionary experiment | Done | `make evolve`, result below |
| Auditable champion/challenger result | Done | `challenges` + `audit` tables in `artifacts/evolution.db`, `artifacts/evolution/<run>/report.md` |
| Tests covering accounting and matching invariants | Done | 47 tests, all passing (`make test`) |
| Complete sandboxed code-change proposal + evaluation | Done | `make propose KEY=momentum-vol-scaling` passed all 9 gates and reached `awaiting_approval`; red-team probes rejected |
| Offline execution with synthetic data + mock LLM | Done | Default `EVOX_LLM=mock`; historical data is optional (falls back to literature bands) |
| Documented performance and limitations | Done | This file |

## Performance (`make bench`)

| Agents | Virtual time | Wall time | Events/s | × real time |
|---:|---:|---:|---:|---:|
| 256 | 1,800 s | 4.6 s | 36,773 | 394× |
| 999 | 600 s | 6.3 s | 34,038 | 96× |
| 10,000 | 120 s | 14.5 s | 28,470 | 8× |

Test suite: about 70 s, including one full sandboxed proposal pipeline (about 50 s).

## Realism vs historical data (`make eval`)

Reference: 5–95% quantile bands from 120 one-hour windows of Binance BTCUSDT 1m klines (train split:
2026-09-01..05). Validation: 2026-09-15..16. Held-out: 2026-10-01..02. 4 seeds × 1 hour per model.

| Model | Facts inside bands | Validation fact distance (lower = better) | 1-min vol (bps) |
|---|---|---|---|
| Full model | 0.79 [0.58, 1.00] | 1.05 [0.85, 1.20] | 21.4 |
| Zero-intelligence (noise + MM only) | 0.54 [0.33, 0.83] | 1.74 [1.16, 2.31] | 13.2 |
| Ablation: no social network | 0.67 [0.54, 0.79] | 1.24 [1.08, 1.46] | 17.5 |
| Ablation: no leverage | 0.58 [0.50, 0.75] | 1.32 [1.25, 1.37] | 16.4 |
| Ablation: no fundamental traders | 0.38 [0.33, 0.46] | 1.69 [1.44, 1.95] | 47.3 |
| GBM (vol matched to history) | 0.88 [0.75, 1.00] | 0.68 [0.52, 0.80] | 4.6 |

Historical 1-min volatility: 4.5 bps. Held-out fact distance for the full model: 0.95 [0.73, 1.11].

**Reading:** each agent component improves fit over its ablation, and the full model beats zero-intelligence.
But a volatility-matched random walk still fits these one-hour shape statistics better. The ABM's volatility
is about 4.7× too high and is not yet calibrated. This is the top calibration priority.

## Stress experiments (`make experiment`, 8 paired replicates, 1,800 s, shock at 900 s)

Paired difference, treatment − baseline, mean [95% bootstrap CI]:

| Scenario | Post-shock min (%) | 5-min return (%) | Shock-window spread (bps) | Max drawdown (pct-pts) | Liquidations |
|---|---|---|---|---|---|
| Fundamental −5% | −5.73 [−5.90, −5.55] | −4.99 [−5.04, −4.94] | +0.54 [+0.22, +0.95] | +5.32 [+5.01, +5.59] | 0 |
| Liquidity drought −70% | +0.01 [−0.02, +0.03] | +0.00 [−0.02, +0.03] | +0.08 [−0.01, +0.18] | −0.01 [−0.03, +0.01] | 0 |
| Whale liquidation (250 BTC) | −0.50 [−0.62, −0.39] | −0.14 [−0.19, −0.10] | +0.17 [+0.02, +0.33] | +0.26 [+0.12, +0.42] | +1.1 (whale only) |
| News panic (no fundamental change) | −0.01 [−0.02, +0.00] | +0.01 [−0.02, +0.05] | +0.14 [+0.01, +0.28] | +0.01 [−0.00, +0.02] | 0 |

Findings (synthetic, uncalibrated, not real-world probabilities):

- The market reprices a 5% fundamental drop almost one-for-one, overshooting by about 0.7 pct-pts.
- A forced 250 BTC liquidation moves price about 0.5% and does **not** cascade: no other liquidations followed.
- A pure-sentiment panic has no measurable price effect. Value traders absorb it.
- Cutting market-maker size by 70% barely matters, because value and retail limit orders supply most resting
  depth. Market-maker dominance of liquidity is therefore *not* a property of this population.

## Evolution (`make evolve`, momentum family, 3 generations × 6 candidates)

The challenger improved validation utility by +0.149 (95% t-CI [−0.009, +0.307], 9 paired runs). It was
**rejected** because the CI lower bound was ≤ 0. The champion is unchanged, the rejection is in the audit log,
and held-out regimes were reported only. With more seeds or generations the same pipeline can promote; rollback
is available (`evox rollback`).

## Code evolution (Level 4)

| Proposal | Outcome |
|---|---|
| `momentum-vol-scaling` | All 9 gates pass (frozen-suite realism 0.930 vs 0.926 baseline; benchmark within 30%), so `awaiting_approval` |
| `redteam-kernel-fee-bypass` | `policy_rejected` before any worktree exists |
| `redteam-shell-escape` | `gates_failed` at the security scan; candidate code never executed |

## Limitations and next priorities

1. **Calibration**: per-minute volatility is about 4–5× historical. Next: calibrate order sizes and depth
   against the train split, with realism as an evolution objective. The plumbing exists.
2. Facts from 60-minute windows are noisy; longer runs and intraday seasonality are not modelled.
3. Single instrument (perp-like, two venues); no spot leg, no auctions or auto-deleveraging; the insurance fund
   may go negative.
4. Level 3 prompt evolution is limited to versioning plus grounding scores. With the mock LLM, prompt variants
   are indistinguishable, so meaningful comparisons need a live model.
5. The offline Evolution Engineer draws code proposals from a curated catalogue. Free-form LLM patches go through
   the same schema and gates but have not been exercised against a live model here.
6. Durable state uses SQLite and Parquet; PostgreSQL is deferred until there are multiple users (see ADR).
7. OpenTelemetry tracing is not wired in yet. Runs record timings and fingerprints in their manifests.
8. Docker image and GitHub Actions CI are provided but were not executed in this environment.
