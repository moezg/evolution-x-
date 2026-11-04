# Quantitative intelligence: calendar, cycle and event discovery

Divisions G (quantitative), H (temporal and calendar) and I (political, macro and geopolitical) extend the research
army from 24 to **36 roles**. The quant workflow runs on the same durable orchestrator:

DATA → PATTERN DETECTION → HYPOTHESIS → STATISTICAL TEST → ADVERSARIAL REVIEW → OUT-OF-SAMPLE → MEMORY

All results are produced by `evox quant run` (protocol `evals/frozen/quant_protocol_v1.json`; 0 LLM calls; about 20 s).

## Data and events

| Item | Source | Coverage |
|---|---|---|
| BTC daily and hourly | Binance spot official archives (checksums verified) | 2017-08-17 .. 2026-10-31 |
| 10-year Treasury yield | FRED DGS10 (sha256 recorded) | 1962 .. |
| S&P 500 | FRED SP500 (S&P licence, research use) | 2016-11 .. |
| Fed funds target (policy actions) | FRED DFEDTARU | 2008-12 .. |
| U.S. elections | computed from 2 U.S.C. §7 (Cornell LII source URL) | 1962 .. 2026 (33) |
| FOMC meetings | federalreserve.gov calendars (page sha256 + retrieval time) | 2017 .. 2027: 87 scheduled, 3 unscheduled, 5 notation votes |
| CPI, NFP, GDP releases | ALFRED vintage dates (v0.7; bls.gov still 403) + BEA schedule | 2017 .. 2026-10 (117 CPI, 117 NFP, 40 GDP advance) |
| Consensus expectations / surprises | licensed data | not available, so "above expectations" cannot be tested |
| Geopolitical events | no verified timestamped source | not ingested |

**Event Registry** (`data/quant/events/registry.jsonl`):
- Append-only and hash-chained.
- Events are versioned: re-registration with new content creates a new version with `supersedes`, while enrichments such as policy actions are preserved.
- Each event records its time precision and keeps provenance.

## Methods (choice depends on the question)

| Question | Method |
|---|---|
| Calendar labels (day of month, weekday, month, turn of month) | Rotation null: returns are circularly shifted against the calendar, which keeps volatility clustering. Shifts that re-align the label are excluded. The p-value uses the null's mean and SD (amendment 2) |
| Event studies | Matched placebo resampling (same weekday and clock time, non-event days); event-level bootstrap CI; anticipation windows; windows from 1 h to 90 d |
| Event × regime interactions | Label permutation; at least 15 events per cell |
| Cycles | Periodogram ordinate ranked within its band [P/2, 2P]; must hold in both halves and in confirmation |
| Multiple testing | BH (q 0.10) per family on DISCOVERY (2017-08..2022). Survivors get one one-sided test on CONFIRMATION (2023..2026-10) with Holm (0.05) |
| Forecast integration | Forecast-protocol rolling origin: M1 + feature vs M1, block bootstrap, Holm |

**Method validation** (`tests/test_quant.py`, synthetic data):

| Scenario | Result |
|---|---|
| i.i.d. fat-tailed series | 2 of 20 runs (each 124 tests) produced a false "supported" result, both on the **left-tail-rate** metric (rare-event counts make the normal approximation anti-conservative) |
| Planted day-14 effect | 0.33σ recovered 2/10; 0.5σ 7/10; 0.67σ 10/10 |

The validation also exposed a defect in the first version: empirical rotation p-values could not go below 0.001, under BH's first threshold of 0.0008. Isolated effects could never be found. Amendment 2 fixed it, and the dry-run conclusions did not change.

## Answers, with evidence (run `c20261103T233607736b`, 271 registered tests; the first registered run `c20261103T2323577382` had identical statuses - the re-run only corrected how results are recorded: no p = 0, effect CIs, data hashes, pending events excluded, confirmation rows for cycles)

**Is the 14th statistically unusual?** **No.**

| Metric (n = 64 discovery days) | Effect vs other days | p |
|---|---|---|
| Mean return (weekday-adjusted) | −0.11 pp | 0.82 |
| Mean absolute return | +0.24 pp | 0.48 |
| Up rate | +3.8 pp | 0.52 |
| Left-tail rate | +4.5 pp | 0.10 |

None of the 124 day-of-month tests survives BH. There is no yearly regularity either (`by_year`).

**Strongest currently supported calendar anomaly:** Saturdays (UTC) have smaller BTC moves.

| Metric | Discovery (n = 281 days) | Confirmation |
|---|---|---|
| Mean absolute return | −0.97 pp (z = −2.7) | −1.12 pp (one-sided p ≈ 1.5e-7) |
| Left-tail-day rate | −3.0 pp | −4.1 pp |

- Same sign in 10 of 10 years, and it survives excluding FOMC and election days.
- It is a **volatility** pattern (traditional markets are closed), not a return predictor. A higher Saturday up-rate appeared in discovery but was **not** confirmed.
- No month-of-year or turn-of-month effect survives. A 7-day cycle in |returns| is the same effect seen in the frequency domain: *inconclusive*, because it failed stability in 2017–2020.

**Do FOMC events create predictable volatility?** For the size of the move, yes; for direction, no.

| Period | Events | Mean |4 h abs return| after the 14:00 ET statement | Matched placebo | p |
|---|---|---|---|---|
| Discovery 2017–22 | 39 | 1.73% (event-mean 95% CI 1.23–2.29) | 1.09% | 0.004 |
| Confirmation 2023–26 | 29 | 1.38% (effect CI +0.32 to +1.22 pp) | 0.66% | 0.0005 (one-sided) |

- **Status:** supported (exploratory).
- **Direction:** a positive first-hour return in discovery did not replicate (inconclusive). No 24 h / 7 d return effect and no pre-event anticipation.
- **Interactions:** neither the pre-event volatility regime (p = 0.20) nor hikes/cuts vs holds (p = 0.12) changes the size of the move in discovery, and confirmation cells are below 15 events.
- **"FOMC with inflation above expectations"** cannot be tested here (no consensus data).

**Does Bitcoin behave differently after U.S. midterm elections?** **Unknown: the sample is far too small.**
- BTC has **2 completed midterms**: 30-day log returns of −0.62 (2018, ≈ −46%) and −0.07 (2022, ≈ −7%). It also has 2 presidential elections: +0.33 and +0.33 (≈ +39%). This is descriptive only, with no statistical confidence.
- The 2026 midterm (today) is the first prospective observation; its post windows resolve from 2026-11-04.
- **10-year yield:** 16 completed midterms since 1962. Mean 30-day change −0.19 pp vs −0.01 pp for matched non-election Tuesdays. n < 20, so this is descriptive only under the frozen rule. It must not be transferred to BTC.
- **S&P 500:** 2–3 events per type in the available 10 years; descriptive only.

**Which combinations add incremental predictive information?**

| Feature | Target | Selection period, M1 + feature vs M1 | Development period | Outcome |
|---|---|---|---|---|
| Saturday target day | 24 h realized vol | log-RV MSE −0.049 (95% CI −0.060 to −0.037) | −0.023 | Holm passes |
| Saturday target day | P(|move| ≥ 3%) | Brier −0.0068 | — | Holm passes |
| FOMC in window | any of three targets | nothing | — | not promoted |

- The Saturday feature is now a **prospective challenger** (`CH:saturday_target_day`), issued daily into the forecast ledger next to the unchanged champion. The first forecasts are for 2026-11-04.
- It is not promoted: it needs 180 resolved forecasts per target and human approval.

**Which findings survived prospective validation?** **None yet.** No prospective window has resolved.

**Which patterns disappeared?** Within this run, effects that appeared in discovery and failed confirmation:
- the Saturday up-rate;
- the FOMC first-hour return.

## v0.7: CPI, payroll and GDP releases (amendment 3)

**Data.** bls.gov returns HTTP 403 here, but the release history is public elsewhere. **ALFRED** (St. Louis Fed real-time archive) dates every vintage of a series by the day its values became public. Running `build_macro` in `quant/macro_releases.py` registers:

| Series | Vintages since 2017 | First releases | Revisions |
|---|---|---|---|
| CPIAUCSL (CPI) | 124 | 117 | 7 (February seasonal-factor updates) |
| PAYEMS (Employment Situation) | 118 | 117 | 1 |
| GDPC1 (GDP) | 116 | 40 advance estimates | 76 later estimates |

- A vintage counts as a first release when it adds a newer observation period than the previous vintage. Each vintage CSV is cached in `data/quant/alfred/`, with its sha256 recorded on the event.
- The 2025 shutdown appears as it happened: the September payroll report was released on 2025-11-20, and October had no separate release.
- **Availability vs schedule:** ALFRED gives the *actual* release **date**. The 08:30 ET time is the agencies' standard convention, so precision is recorded as "day (08:30 ET by convention)". BEA's official schedule page adds *announced* future GDP releases with their stated 8:30 AM time (2 registered: 2026-11-25 and 2026-12-23).
- The BLS public API is reachable, but anonymous requests are refused (daily quota exhausted for this network), so it is not relied on.
- **Consensus expectations are still unavailable,** so "above expectations" remains untestable.

**F-MACRO study** (pre-registered as amendment 3 at 03:23 UTC, before any BTC data around these releases was examined; run `macro20261104T032607`):
- Design: BTC spot, 4 metrics × {CPI, NFP} = 8 tests. The window starts with the 08:00 ET bar, which contains the release. Placebos are 08:00 ET bars on non-release days with the same weekday set.

| Test | Discovery n | Effect vs placebo | p | BH p | Status |
|---|---|---|---|---|---|
| CPI \|4 h return\| | 55 | +0.13 pp | 0.53 | 0.80 | rejected |
| CPI 4 h realized vol | 55 | +0.40 pp | 0.045 | 0.34 | rejected |
| CPI 4 h return | 55 | +0.14 pp | 0.61 | 0.80 | rejected |
| CPI 24 h return | 55 | −0.91 pp | 0.086 | 0.34 | rejected |
| NFP \|4 h return\| | 57 | −0.19 pp | 0.35 | 0.80 | rejected |
| NFP 4 h realized vol | 57 | −0.09 pp | 0.67 | 0.80 | rejected |
| NFP 4 h return | 57 | +0.01 pp | 0.96 | 0.96 | rejected |
| NFP 24 h return | 57 | −0.20 pp | 0.70 | 0.80 | rejected |

**Answer:** BTC moves around CPI and payroll releases are **not** distinguishable from matched non-release mornings in 2017–2022. Nothing survives, so under the registered rule there is no confirmation test and no forecast-feature test.

Contrast with FOMC (supported): the scheduled statement is a BTC volatility event, while CPI and NFP releases as a group are not. Surprise-conditional effects may still exist but cannot be tested without consensus data.

**Prospective follow-up:** after each FOMC statement, the scheduler records the observed 4 h |return| (`artifacts/ops/event_followups.jsonl`). The first record (2026-10-28) is 0.63%. It is out-of-sample but **not prospective**: the event preceded the registered run. The first version of the job labelled it "prospective"; a correction line was appended.

## Limitations
- Confirmation data (2023–2026-10) is chronologically held out from every scan, but those BTC prices were seen in other project contexts, so it is not independent. All "supported" results are exploratory.
- Left-tail-rate tests are anti-conservative (see validation).
- No CPI/NFP/GDP, consensus, options-expiry, index-rebalance or geopolitical data. G4 (statistical arbitrage) is not implemented in this slice.
- Election studies cannot support inference (n < 20 per type for every asset).
- The dry runs were seen before amendment 2. The registered run reproduces their conclusions.
