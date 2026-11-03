# Forecasting laboratory (predictive intelligence foundation)

The objective is demonstrable **out-of-sample predictive skill, calibration and reliability** of probabilistic
forecasts about real BTC prices. Simulator complexity and simulated profits are not the objective. The agent-based
simulator is one candidate feature source and has to earn its place. So far it has not.

Paper forecasts only: no order is ever sent anywhere.

## Reuse audit: what came from the existing repository

| Need | Reused component | Status |
|---|---|---|
| Point-in-time historical data with checksums | `data/datasets.py` (`_fetch`, `_rows`, Binance archive conventions); BTC 1 h splits on disk | reused |
| Exposure accounting | `evals/frozen/exposure_registry.json` (development free; validation exposed; final consumed; SOL/BNB vault untouched) | reused as period labels |
| Append-only, tamper-evident log | `research/journal.py` (hash chain) | wrapped by `forecast/ledger.py` |
| Experimental memory, trials, dedup | `research/memory.py` (SQLite schema: experiments, trials, candidates) | reused by `forecast/evolve.py` |
| Statistics | moving-block bootstrap and Holm, newly written in `forecast/scoring.py`; the strategy lab's DSR/PBO (`stats/overfit.py`) is not needed for proper scores | new |
| Simulator | `sim/*`, `observatory/market_stats.py` | reused for experimental features |
| Frozen-protocol discipline | `evals/frozen/*` and amendments written before results | reused |
| API and dashboard | FastAPI routers, Next.js components | extended |
| Not reused | the strategy backtester (`backtest/`): this task scores probabilities, not positions; no fees apply because no trades are simulated | — |

## Architecture (`src/evolutionx/forecast/`)

| Module | Role |
|---|---|
| `data.py` | Loads the BTC 1 h bars: existing splits plus fresh daily archives from 2026-11-01 (checksum verified). Never reads the SOL/BNB vault |
| `domain.py` | `Domain` protocol and the `DOMAINS` registry; `BTCDomain` builds the hourly grid (gaps stay missing), point-in-time features and outcome definitions. New domains plug in here |
| `models.py` | Numpy-only models: B0 climatology, B1 EWMA-Gaussian, M1 L2 logistic / ridge, M2 boosted depth-2 trees, H1 = M1 + simulator features |
| `simfeatures.py` | Simulator features: observed 7 d volatility and 24 h return become simulator inputs; outputs are the amplification ratio, kurtosis, \|r\| ACF, spread and liquidations. Cached by input cell |
| `backtest.py` | Rolling-origin backtest under the frozen protocol, with abstention, fallback scoring and pre-registered comparisons with Holm correction |
| `scoring.py` | Brier, log loss, reliability/ECE, MSE and QLIKE for log RV, moving-block bootstrap, Holm |
| `ledger.py` | Append-only forecast/resolution ledger |
| `prospective.py` | Issue → resolve → score cycle for prospective paper forecasts |
| `evolve.py` | Candidate configs in a frozen space, trial accounting, challenger status (never automatic promotion) |

API: `/api/forecast/{protocol, backtest, series, ledger, prospective, evolution}`. Dashboard: `/forecast`.

## Commands
```bash
uv run evox forecast fetch      # fresh official daily archives (checksums)
```
```bash
uv run evox forecast backtest   # registered retrospective backtest (about 90 s)
```
```bash
uv run evox forecast issue      # prospective forecasts for the next 00:00 UTC origin
```
```bash
uv run evox forecast resolve    # resolve matured forecasts from published archives
```
```bash
uv run evox forecast score      # prospective scores and ledger verification
```
```bash
uv run evox forecast evolve     # bounded candidate cycle with trial accounting
```
To build prospective evidence, run `issue` once a day (any time before 00:00 UTC) and `resolve` daily.

## Evidence rules
- **Information lag.** At origin o a model sees bars complete before o − 24 h, because archives publish about a day late and the live API is unreachable (HTTP 451). Training labels must have been observable by then.
- **Retrospective periods:**
  - DEV (2021–2023): free exploration.
  - SCREEN (2024-01 to 2025-06): previously exposed; used for screening only.
  - CONSUMED (2025-07 to 2026-10): never fresh validation.

  None of the three is independent.
- **Independent evidence** comes only from prospective forecasts resolved after issuance. Promotion of any challenger needs ≥ 180 resolved prospective forecasts per target, a block-bootstrap CI below 0, and human approval.
- **Abstention never hides hard cases.** An abstained forecast is scored as the climatology forecast.

## Limitations
- **Retrospective numbers come from data the operator has seen,** including strategy results on the same calendar periods. They are exploratory.
- **Lag inflates difficulty.** The 24 h data lag is realistic for this environment but makes short-horizon forecasts harder than with live data.
- **Funding features are excluded** (amendment 1): funding archives publish monthly, so they would leak unavailable information into retrospective tests.
- **Overlapping windows.** 72 h targets on daily origins overlap. The block bootstrap (10 origins) only approximates the dependence.
- **The ledger is tamper-evident, not tamper-proof.** Publishing its head hash externally (for example in a pushed commit) would add an independent timestamp. That has not been done, because pushing needs authorization.
- **Small model set.** No LLM forecasting and no external information (news, order flow, options) yet.
- **The simulator features add no measurable skill** on any target, so they are excluded under the pre-registered rule. H1 is kept only as an experimental model in retrospective runs and is not issued prospectively.
