# Status: v0.6 research army (2026-11-03)

A 24-role research organization now runs durable, restartable research cycles: DISCOVER → VERIFY → UNDERSTAND →
FORMULATE → IMPLEMENT → TEST → CHALLENGE → EVALUATE → ARCHIVE → REASSESS. It builds on the existing research
lab, memory, forecasting engine and simulator. Details, roles and limitations are in `docs/ARMY.md`.

**Headline: 3 cycles, 3 mechanisms evaluated, 0 promotions, 0 validated improvements.** No trading code exists.

### Stage A: stabilization (`1e9e81d`)
- **Verified in the committed code:**
  - raw and scored forecast series;
  - realized-vol Holm family of 2 tests;
  - quantile levels;
  - abstention rule 4 on resolved ledger forecasts;
  - header text.
- **Evolution 404 reproduced and diagnosed.** Artifact routes resolved relative to the server's working directory, so a server started from another directory answered 404 everywhere. The app now anchors to the repo root, and `/api/health` reports paths. The original report itself predates the artifact (written 21:45:26).
- **Tests:** 3 new regressions.

### Research cycles

| Cycle | Evaluated | Outcome |
|---|---|---|
| 1 (LLM off) | funding carry, breakout | both **refuted** by the lab's frozen rule. Trend paper = duplicate of 59 earlier hypotheses. 2 planted invalid strategies rejected |
| 2 | — | all 4 sources were duplicates (deduplication against memory works). One rejection came from a **classifier error**, found and fixed. The source was re-opened with a journaled reason |
| 3 | volatility-managed long | **inconclusive**. Selection Sharpe 1.04 vs 0.66 vol-matched buy-and-hold, but P = 0.89 and DSR 0.49 fail the frozen rule (54 trials counted). The adversarial placebo says it is mostly BTC beta. 2 order-book papers declared infeasible. A regression-test proposal passed isolated-worktree checks and awaits human review |

- **External sources that work:** arXiv and Crossref. Semantic Scholar, OpenAlex, SSRN and GitHub are blocked or rate-limited here.
- **LLM:** 2 real calls, $0.164 API-equivalent (estimate).
  - Both answers were lost to over-strict schema caps; the deterministic fallback was used. Fixed afterwards.
  - The affected hypothesis was not re-run, to avoid outcome-driven retesting.
- **Prospective evidence:** 32 forecasts open, 0 resolved. Each cycle now resolves and issues forecasts and monitors drift.

### Tests
- `tests/test_army.py`, 19 tests:
  - roles, eligibility, context scrubbing and protected paths;
  - untrusted XML and injection handling; LLM output cannot set a status; truncation;
  - templates, classifier fix, adversarial hard failure;
  - the orchestrator: DAG, retry, failure propagation, barrier, pause/stop, crash recovery, tick;
  - code proposals: protected path blocked, real worktree check;
  - paper ledger and drift alert.
- Full suite: 160 passed; pyright 0 errors.

---

# Status: predictive intelligence foundation (2026-11-03)

The project's top-level objective is now **out-of-sample predictive skill, calibration and reliability of
probabilistic forecasts about real-world events**, starting with BTC. The simulator, observatory, research memory and
evolution machinery are preserved and reused. Details and limitations are in `docs/FORECASTING.md`.

**Headline.** A working end-to-end forecasting system exists. It has data with publication lag, a rolling-origin
backtest, baselines, ML models, an experimental simulator hybrid, proper scoring, an append-only ledger, prospective
paper forecasts, abstention, guarded evolution, an API and a dashboard.

**No predictive superiority is claimed.** All retrospective evidence comes from previously exposed data. The first 32
prospective forecasts (origin 2026-11-04 00:00 UTC) are recorded but not yet resolved.

### 1. Protocol
- `evals/frozen/forecast_protocol_v1.json` was frozen before any model was fitted.
- **Amendment 1, also before fitting:** funding features were removed because funding archives publish monthly and would not be available at issue time.
- **Lag:** 24 h. Daily archives arrive about a day late, and the live API returns HTTP 451 here.
- **Origins:** daily at 00:00 UTC.
- **Targets:**
  - realized volatility over 24/72 h;
  - P(|move| ≥ 3%) and P(|move| ≥ 5%) over 24/72 h;
  - P(up) over 24/72 h.

### 2. Retrospective rolling-origin backtest
Previously exposed data, so screening evidence only. The run is `artifacts/forecast/backtest_v1.json`, code `38d9e125`, 89 s. Earlier runs on code `4b9e4800` and `10d4f9ed` gave identical scored forecasts. Protocol amendment 2 records two corrections found in a dashboard code review: the realized-vol Holm family is back to its registered 2 tests (both still reject), and prospective abstention rule 4 uses resolved ledger forecasts, with a recorded backtest proxy until 60 exist.

Brier skill vs climatology B0 on SCREEN (2024-01 to 2025-06, n = 545 daily origins):

| Target | B1 EWMA-Gauss | M1 logistic | M2 boosted | H1 hybrid (sim) |
|---|---:|---:|---:|---:|
| move3 24 h | −3.1% | **+2.1%** | +1.9% | +2.6% |
| move5 24 h | −2.4% | +2.0% | +2.8% | +2.2% |
| up 24 h | −0.2% | −0.2% | −0.6% | 0.0% |
| move3 72 h | −0.3% | −1.0% | −0.9% | −1.2% |
| move5 72 h | −3.5% | +0.1% | −1.8% | −0.4% |
| up 72 h | −0.5% | −0.2% | −0.1% | −0.5% |
| realized vol 24 h (MSE skill on log RV) | −4.5% | **+14.3%** | +11.7% | +13.6% |
| realized vol 72 h (MSE skill on log RV) | −1.4% | **+19.6%** | +15.3% | +16.9% |

**Pre-registered comparisons on SCREEN (Holm over 24 binary tests):**
- Survive:
  - M1 beats B1 on move3 24 h (ΔBrier −0.0091, 95% CI −0.0135 to −0.0040);
  - M1 beats B1 on move5 24 h (−0.0029);
  - M1 beats B1 on realized vol at 24 h and 72 h.

  The Gaussian EWMA baseline is badly calibrated in the tails.
- **Do not survive:** every model vs climatology. The best is move3 24 h, p = 0.037 against a Holm threshold of 0.0025.
- **Direction (up/down):** no model has skill on any period.
- **72 h move targets:** no skill on SCREEN.
- **Calibration:** M1 has an ECE of 0.015–0.023 on 24 h targets (SCREEN).
- **Abstention:** it is active (for example, M1 covers 48% of up-24 h origins). Abstained origins are scored as climatology.

### 3. Do simulator features add skill?
**No.** The simulator was run on 119 input cells (2 seeds, 900 s, scale 0.5).

- H1 vs M1 on SCREEN: no binary target is significant after Holm (best p = 0.20).
- Realized volatility: H1 is slightly worse than M1 (rv 72 h: +0.0039, CI +0.0005 to +0.0084).
- Following the pre-registered rule, simulator features are **EXCLUDED** from all non-experimental models and are not issued prospectively.

### 4. Ledger and prospective mode
- `artifacts/forecast/ledger.jsonl` (copy in `docs/evidence/forecast/`) is hash-chained and append-only.
- Forecasts can only be issued before their window starts; each is resolved once, after the window has ended and been published.
- At 21:44 UTC, 32 forecasts were issued for origin 2026-11-04 00:00 (4 models × 8 targets, as of 2026-11-03 00:00). 2 abstained: M1 and M2 on up-24 h, because their trailing skill is negative. Status: 0 resolved, 32 open; the chain verifies.
- **Promotion needs at least 180 resolved prospective forecasts per target.** No promotion is possible for months.

### 5. Evolution with safeguards
- Candidates are configs in a frozen space: model family, feature subset, L2, boosting settings. Targets, data, lag, periods and scoring cannot change.
- Every evaluation counts as a trial. Acceptance on SCREEN needs one-sided p < 0.05 / (trials for that target) and no degradation on DEV.
- First cycle: 9 candidates over 3 targets (proposed from DEV evidence only), **all rejected**. None beat the frozen champion M1.
- An accepted candidate would only become a prospective challenger. Nothing replaces the champion automatically.

### 6. Tests
`tests/test_forecast.py` has 10 tests:
- features never read bars after as-of;
- outcome definitions are correct;
- training never uses unobservable labels;
- abstentions are scored as climatology;
- the backtest is deterministic;
- scores and Holm are correct;
- the ledger is prospective, append-only and tamper-evident;
- the full issue → resolve → score cycle works on synthetic bars;
- candidates cannot leave the frozen space;
- the trial-adjusted threshold tightens and never replaces the champion.

### 7. What would make this system better (in order)
1. Run `evox forecast issue` and `evox forecast resolve` **every day**. Prospective resolved forecasts are the only independent evidence. Two to three months give enough 24 h outcomes for a first real assessment.
2. Add information unavailable to the current features, each tested through the same frozen comparison: options-implied volatility, intraday order flow, cross-asset signals. (Funding stays out until it can be obtained point-in-time.)
3. Add LLM forecasting only after these baselines are stable, as another candidate in the same ledger and scoring.

---

# Status: v0.5 critical thresholds for liquidation cascades (2026-11-03)

**Answer to the mission question:** the artificial society did **not** produce a liquidation feedback cascade.

- In 96 confirmatory runs (whale 1000/2000/4000 BTC nominal × leverage_use 0.7/1.0 × 8 seeds × 2 arms), no agent account ever reached a margin breach.
- With secondary liquidation execution switched off, every run is **bit-identical** to its normal-mechanics pair (48/48 run fingerprints equal).
- The whole observed loss (−2.5% to −3.6%) is the mechanical consequence of the whale's forced sale, plus ordinary trading reactions that are the same in both arms.
- The threshold was **not observed within the tested range**.

All results are SYNTHETIC. There were 0 LLM calls, no exchange transactions, and no holdout access. The 60-call campaign was not run, and simulator defaults are unchanged.

### 1. Protocol and reproducibility
- **Pre-registration:** `evals/frozen/cascade_c2_v1.json`, sha `d9a0a4bb…` in the report. It contains inspection facts, design, measurements, causal definitions, hypotheses H1–H3, the classification rule and the stopping rule. Two amendments were written before the confirmatory runs:
  - **Amendment 1, measurement only:** the primary forced sale is a process lasting 80–160 s, not a single sweep.
  - **Amendment 2, after the exploratory pilot (seed 900):** whale build-up saturates, and the leveraged agents are short at the shock. The design was not changed.
- **Seeds:** pilot 900 (exploratory, not used in statistics); confirmatory 901–908.
- **Commands:**
  - `evox observatory cascade --role pilot|confirmatory`
  - `evox observatory cascade-x`
  - `evox observatory knowledge`
- **Artifacts:** `artifacts/observatory/cascade_c2_{pilot,confirmatory}.json`, `cascade_c2x_exploratory.json` and `knowledge_c2.json`. Compact copies are in `docs/evidence/observatory/`.
- **Cost:** 96 confirmatory runs, 135 s wall (527 CPU-s), plus 12 pilot and 48 exploratory runs.

### 2. Causal comparison (arm A normal, arm B secondary execution suppressed; paired by seed)
| Config (nominal) | Reached whale BTC (mean, range) | Primary forced sale | Arm-B max drop | Secondary breaches A / B | Secondary liquidations | A − B incremental drop | Class |
|---|---|---|---:|---|---:|---:|---|
| 1000, lu 0.7 | 1000 | $59M over 83 s | −2.49% | 0 / 0 | 0 | 0 (identical runs) | no_secondary_liquidations |
| 2000, lu 0.7 | 1557 (1465–1679) | $92M over 144 s | −3.31% | 0 / 0 | 0 | 0 | no_secondary_liquidations |
| 4000, lu 0.7 | 1605 (1533–1759) | $95M over 152 s | −3.39% | 0 / 0 | 0 | 0 | no_secondary_liquidations |
| 1000, lu 1.0 | 1000 | $59M over 85 s | −2.49% | 0 / 0 | 0 | 0 | no_secondary_liquidations |
| 2000, lu 1.0 | 1582 (1499–1686) | $94M over 149 s | −3.42% | 0 / 0 | 0 | 0 | no_secondary_liquidations |
| 4000, lu 1.0 | 1625 (1518–1801) | $96M over 161 s | −3.55% | 0 / 0 | 0 | 0 | no_secondary_liquidations |

Other measurements, both arms identical:

- **Volatility:** 1-minute volatility rises from 15–28 to 54–64 bps in the 300 s window.
- **Depth:** 10-level depth falls from 6–8 BTC to a minimum of 1.5–2.4 BTC.
- **Liquidity:** the book is one-sided or empty in **41% of the window's seconds** (15% before the shock). The median spread over two-sided seconds (3.9–5.9 → 3.3–3.6 bps) hides this, and an earlier draft of this section wrongly read it as "spread does not widen".
- **Recovery:** half-recovery takes 35–205 s.
- **Circuit breakers and stops:** 0 circuit breakers; 0 leveraged stop-loss exits.
- **First-tick impact:** −0.4% to −1.3%. Most of the drop comes later, during the multi-tick forced sale.

The causal chain "shock → breach → forced liquidation → pressure → further breach" is **not observed**: its first link, a breach, never occurs.

### 3. Threshold analysis
- For both leverage levels, 0 of 8 seeds have secondary liquidations at every size (Wilson 95% CI 0–0.32).
- The onset bracket is undefined, and no threshold curve was fitted.
- **Dose caveat:** the whale build-up saturates at about 1,500–1,800 BTC, so the 2000 and 4000 BTC nominal cells test nearly the same reached dose. The tested range is effectively 1000–1800 BTC.

### 4. Why there is no cascade: mechanism found (exploratory, `cascade_c2x_v1.json`, same seeds, not independent)
1. **Positioning, endogenous and funding-driven.**
   - All 768 leveraged agent-observations were **short** at the shock (2.8–4.8% from margin on the *upside*, 14–20× effective leverage). The forced sale moved the price in their favour.
   - Cause: the whale's long build-up lifts the perpetual premium, so funding turns positive (about +0.12% per 300 s). The leveraged signal subtracts funding × 2000, clipped at 0.5, and social herding spreads the short.
   - X1 ablation, mean leveraged longs out of 16:

     | Condition | Mean longs |
     |---|---:|
     | default | 0 |
     | no funding term | **7.4** |
     | no social | 0 |
     | neither | 0.9 |

   - Without the whale, positioning is mixed. The funding term is the main driver; prediction ≥ 8 was narrowly missed, the refutation level < 4 was not reached.
2. **Voluntary deleveraging pre-empts margin.**
   - With the funding term removed (X2), leveraged agents are long at the shock, yet there are still 0 breaches in 16 runs.
   - Traces show their long exposure falling about 80% within 60 s ($2.8–3.9M → $0.55M) through ordinary momentum trading. The nearest margin distance shrinks to about 1.2% but never reaches 0.
3. **Insufficient fuel.**
   - The entire leveraged sector can hold about **$6–7M** gross, against an $86–97M primary forced sale (about 7%).
   - Even a complete secondary liquidation could add little selling pressure.

**What is missing.** A crowded, slow-to-react leveraged position on the *same side* as the forced seller, large enough to matter. In this simulator the funding rate is about 1000× typical real 8-hour funding: it pushes leverage to the opposite side, and the sector is small. The model was **not** changed to force a cascade.

### 5. Research memory and controlled self-evolution (`observatory/knowledge.py`, existing `Memory` schema, `artifacts/observatory/knowledge.db`)
- **Mechanisms recorded:**
  - C2-H1 `not_observed`;
  - funding-contrarian positioning `exploratory_supported`;
  - voluntary deleveraging `exploratory_supported`.
- **Gaps recorded:** funding magnitude; leveraged capacity; whale build-up saturation.
- **Dedup:** a second ingest of C2 was refused as a duplicate. Replications must declare themselves and use new seeds (tested).
- **Proposals, never applied, judged only by the frozen realism rules (v2):**

  | Proposal | Verdict | Note |
  |---|---|---|
  | P1: leveraged funding_sens 2 | not an improvement vs both baselines | |
  | P3: 64 leveraged agents | not an improvement | scale error 8.9 vs 1.2: the change that would fuel cascades makes volatility much less realistic |
  | P2: funding_k 1e-4 | `needs_human_rules_review` | outside the frozen candidate space |

- **Next-experiment ranking** (bits per 100 runs; priors are stated judgement inputs):

  | Candidate | Score |
  |---|---:|
  | C3-funding | 1.91 |
  | C3-fuel | 1.91 |
  | mirror squeeze | 1.47 |
  | C3 factorial | 1.46 |
  | repeat of C2 | blocked as already run |

### 6. Tests
- `tests/test_cascade.py`, 12 tests:
  - the margin distance matches the engine's breach rule (property test);
  - no trading without resources;
  - breach vs execution, and primary vs secondary classification, in both arms, with accounting and fee checks;
  - the primary liquidation survives the switch;
  - measurement is read-only and deterministic;
  - KC-2 default neutrality;
  - the classifier cannot report "cascade" without secondary liquidations or a chain (property test);
  - identical arms are not classified as a cascade;
  - dedup, ranking, and the proposal guard.
- Full-suite result is in the delivery message.

### 7. Recommended next experiment
**C3-funding.** Set `funding_k` = 1e-4, a realistic funding magnitude, with whale 2000 BTC, leverage_use 1.0, fresh seeds 909–916, arms A/B: 32 runs, about 1 minute, 0 LLM calls.

- It is tied for the best expected information per run.
- It tests the root-cause gap directly: do leveraged agents stay crowded on the whale's side when funding is realistic?
- If they do and there are still no breaches, the binding constraint is fuel and deleveraging speed, and C3-fuel is next.
- `funding_k` changes the model, so the experiment must be pre-registered as a realism-relevant model variant and judged on realism before any cascade claim.

---

# Status: v0.4 Emergent Behavior Observatory (2026-11-03)

This mission moved the work from strategy optimization to making **collective behaviour in the synthetic market
observable and falsifiable**. It claims no trading result. The 60-call LLM campaign was **not** run. No LLM call was
made, the SOL/BNB vault v2 was not opened, and the consumed BTC/ETH data was not used as validation. Historical BTC
1-minute **TRAIN** days serve only as stylized-fact targets for the simulator.

Evidence stays in four separate categories; there is no global score. Everything below is **SYNTHETIC** unless it says otherwise.

### 1. Software quality
| Item | Result |
|---|---|
| Capability matrix | Executable probes, not assertions: `evox observatory audit` → `artifacts/observatory/audit.json`. Summary in `docs/AUDIT.md` (v0.4 section) |
| New shock `mm_withdrawal` | A fraction of market makers stops participating. Their quotes are cancelled and they are inactive, then they return (`sim/simulation.py` `_shock`/`_restore`). Deterministic. Disarmed is bit-identical to no shock (tested) |
| Read-only sampler | Records stances, near-mid depth by kind and per maker, and panic counters every 10 s. A sampled run has the **same fingerprint** as an unsampled one (tested) |
| Bug fixed: `Simulation.finished` | It was `True` before the first event because a next-event time of 0 is falsy |
| Bug fixed: silent no-op knob | `size_scale["leveraged"]` did nothing: leveraged agents size by `leverage_use`. It is now rejected. The v0.1 calibration searched this knob, so its "leveraged" sensitivity coefficient was noise. Calibration filters it, which keeps old runs reproducible. Found because the realism archive held two configs with **identical run fingerprints** |
| Reproducibility | Every report stores the frozen-spec sha256, seeds, config fingerprints and run fingerprints. Commands: `evox observatory {audit, volatility --tag v1/v2, experiments, realism}` |
| Tests | 19 new cases in `tests/test_observatory.py`, plus `mm_withdrawal_90` added to the scenario test: shock mechanics, sampler neutrality, detectors on constructed inputs, ARI/Gini/dominance properties (hypothesis), verdict rule, archive admission/eviction/duplicates, rule-change refusal. Full-suite result is in the delivery message |

### 2. Simulator realism
**Volatility root cause** (pre-registered: `evals/frozen/volatility_diagnosis_v1.json` + `amendment_v2`; 3 seeds × 3600 s per condition).

1-minute return std of the mid, in bps; historical TRAIN median is **4.0**:

| Condition | Mid | Fundamental input | Kurtosis |
|---|---:|---:|---:|
| default | 22.6 | 16.3 | 4.8 |
| realistic fundamental (R: GBM 0.33/yr, no news jumps) | 8.9 | 4.9 | 1.3 |
| frozen fundamental | 0.9 | 0 | 0.4 |
| R, no momentum agents | 3.8 | 4.9 | **12.0** |
| R, no leveraged agents | 4.5 | 4.9 | 5.1 |
| R, no social channel | 5.1 | 4.9 | 3.6 |
| R, no noise traders | 8.7 | 4.9 | 0.9 |

- **Cause 1, exogenous specification (measured).** The latent fundamental alone moves 16 bps/min, which is 4× history. Making it realistic removes about 60% of the excess.
- **Cause 2, positive feedback (measured).** On the realistic base the mid is still 1.8× its own input. Removing momentum, leverage or the social channel each brings it back near the input. The effects are not additive (each one alone nearly closes the gap), which points to one coupled loop rather than three independent sources.
- **Refuted:**
  - a microstructure floor (frozen fundamental gives 0.9 bps);
  - time-scaling or sampling artefacts;
  - one-sided-book artefacts (no one-sided second after the empty first second of each run);
  - private belief noise;
  - retail noise.
- **Not done on purpose:** no corrective multiplier was applied, and SimConfig defaults are unchanged. R is a named profile used as the observatory base.

**Realism track with a Pareto archive** (`evals/frozen/realism_track_v2.json`, `observatory/realism.py`; 3 fresh seeds × 3600 s; objectives are scale error, shape error and CPU cost against TRAIN-day targets).

| Candidate | Scale error | Shape error | Verdict vs default | Verdict vs R | Archive |
|---|---:|---:|---|---|---|
| default | 4.26 | **0.79** | — | not an improvement | Pareto |
| R | 1.16 | 0.83 | not an improvement¹ | — | Pareto |
| R + momentum size ×0.5 | 0.51 | 1.33 | not an improvement | not an improvement | Pareto |
| R + leverage_use 0.35 | 0.60 | 1.31 | not an improvement | improvement² | dominated by R_no_social |
| R + market-maker size ×2 | 1.10 | 0.90 | not an improvement | not an improvement | Pareto |
| R + no social | **0.51** | 1.31 | not an improvement | not an improvement | Pareto |

¹ R has a lower scale error in 3 of 3 seeds, but at n = 3 the t-interval includes 0, so the frozen rule says "not an improvement". The rule is underpowered, not wrong.
² Scale error is significantly lower; shape error is worse by +0.49 but not significantly.

**Result:** no configuration improves both objectives. Weakening the feedback loop fixes the volatility level but degrades the return-shape facts (kurtosis, |r| ACF, vol–volume). The same loop that inflates volatility also produces the stylized facts. This is a trade-off, not an improvement.

The track also caught its own defect, and v1 is kept as evidence. The v1 archive let CPU-time noise decide between two behaviourally identical configs. v2 adds a 25% cost tolerance, fingerprint-duplicate rejection and a second incumbent. Candidates can only set allow-listed SimConfig fields. The archive stores the rules' sha256 and refuses to update when they change (tested).

### 3. Collective behaviour (pre-registered: `evals/frozen/observatory_experiments_v1.json` + amendment 1 written before any registered run)
Base R, 4 paired seeds (601–604), 1800 s, sampling every 10 s, 56 runs, 82 s wall, **0 LLM calls**.

Verdict rule (amendment 1): "supported" needs both the bootstrap CI and the t-interval to exclude 0. With only the bootstrap it is "weak". With n = 4 every result here is low-power.

**A: stable market without shocks** (full vs no_social vs zero-intelligence = 232 noise + 24 makers, no social)
| Hypothesis | Result | Verdict |
|---|---|---|
| HA1 anchoring | max \|mid/fundamental − 1\| ≤ 0.3%; 0 circuit breakers; 0 liquidations; 0 panics | supported |
| HA2 amplification replicates on fresh seeds | mid/fundamental volatility ratio 2.1 (1.4–3.0) | supported |
| HA3 the social channel amplifies volatility | +5.3 bps (t-CI 0.7–9.9), 4/4 seeds | supported (**interaction-dependent**) |
| HA4 herding needs interaction | herding index +0.03 (t-CI −0.03 to 0.09) | **not supported**. Stance alignment is explained by a common price/news input (**programmed/common-input**). Zero-intelligence noise traders reach 0.89 because they all read the same news number |
| HA5 stylized facts need strategic agents | \|r\| ACF +0.29 and kurtosis +1.3 vs zero-intelligence, 4/4 | supported. ZI gives Gaussian-like, anti-clustered returns |

Exploratory (not pre-registered, association only):
- With the social channel the momentum–value stance correlation is −0.68; without it, −0.11.
- Trend-follower share of aggressive volume is 0.74 vs 0.50.
- Taker-volume HHI is slightly lower with social, so activity is more dispersed.
- Trend flow does **not** chase the previous minute's return (corr ≈ −0.1). It moves the same minute's return (0.92), so the measured amplification is contemporaneous.
- Behaviour clusters recover programmed types only partly (ARI 0.61). Execution, value and whale agents of one type behave differently.

**B: liquidity crisis, market-maker withdrawal for 300 s** (paired with the disarmed same-seed run)
| Measure in the crisis window | Control | f = 0.5 | f = 0.9 | Verdict at f = 0.9 |
|---|---:|---:|---:|---|
| 1-min volatility (bps) | 7.2 | 12.3 | **31.9** | supported (t-CI +11.8 to +37.6) |
| Impact (bps per BTC of aggressive flow) | 0.18 | 0.31 | 0.55 | supported |
| Median spread (bps) | 3.47 | 3.63 | 3.93 | weak (bootstrap only) |
| Median depth, 10 levels (BTC) | 10.2 | 10.0 | 9.5 | not supported |
| Spread in the 300 s after makers return vs control | — | — | 1.08× | recovery supported (≤ 1.2×) |

- The withdrawal shows up mainly as **volatility and impact**, not as spread or 10-level depth. Non-maker resting orders keep the visible book roughly as deep, but it is much less resilient.
- **HB6, open question (exploratory):** at f = 0.9 the 2 remaining makers *also* reduce their near-mid depth: −0.40 BTC (t-CI −0.68 to −0.11), 4/4 seeds, about −8%. This is withdrawal that spreads through shared market state. It is a programmed inventory/volatility rule triggered by others' absence, so the label is **interaction-dependent**, not "intent".

**C: liquidation cascade, whale forced liquidation × leveraged agents present/absent**
| Hypothesis | Result | Verdict |
|---|---|---|
| HC1 secondary liquidations | **0** secondary liquidations in all 16 armed runs (250 and 1000 BTC, with and without leveraged agents) | **refuted** |
| HC2 leverage amplifies the drop | Drop with vs without leveraged agents: −2.7% vs −2.7% (difference 0.04 pp, opposite sign) | not supported |
| HC3 dose | 1000 BTC drops 2.1 pp more than 250 BTC | supported (an exogenous dose effect, not a cascade) |

Mechanism check: leveraged agents run at a median effective leverage of about 11 (max 16) before the shock, so they sit about 4% from maintenance margin. The forced sale moves the price only about 2.7%. **The precondition for a cascade never arises in this population.** No liquidation cascade has been observed; the detector is tested only on constructed inputs.

**What the observatory can and cannot say:**
- Herding, liquidity withdrawal, panic contagion, cascades, trend amplification, influence concentration, regime switches and behaviour clustering are all measured on every sampled run, each with a stated "programmed basis".
- In unshocked runs, panic contagion, liquidation cascades and endogenous maker withdrawal **never fired**.
- Regime switches were 0–1 per run (descriptive only).

### 4. Research process
- 4 frozen specs, all written before their runs:
  - volatility v1 plus amendment v2;
  - experiments v1 plus amendment 1;
  - realism track v1, then v2 with documented reasons.
- One pre-registered change made the rule **stricter** (amendment 1). The realism-track change was caused by a defect and is documented.
- Cost of this mission's experiments:
  - experiments: 56 runs, 323 CPU-s;
  - realism: 2 × 18 runs, about 150 s wall;
  - volatility: 33 runs.
- 0 LLM calls; no paid API.
- Strategy-research status from v0.3 is unchanged: 0 promotions, validation consumed, vault v2 sealed.

### Recommended next experiment
**C2, a cascade threshold scan.** Factors: whale size {1000, 2000, 4000} BTC × `leverage_use` {0.7, 1.0} with leveraged agents present, 4 paired seeds, disarmed controls, about 48 runs (≈ 70 s wall, 0 LLM).

Why: experiment C falsified a cascade at today's distance to margin. The informative question is whether a cascade appears once the shock exceeds that distance, and whether secondary liquidations add to the drop beyond the dose. Either outcome is new information: a threshold with super-linear drop is emergent amplification, while a purely linear dose means the leverage channel is inert. Pre-register the threshold and the "excess drop beyond the 0-leverage dose curve" before running.

---

# Status: v0.3 research-quality slice (2026-11-03)

v0.3 does not claim a better strategy. It makes the laboratory's hypotheses technically correct and measures
how the research process behaves. The negative result of v0.2 stands: **no champion has been validated**
(0 promotions in 56 tasks across all non-superseded labs).

Evidence is kept in four separate categories; there is no global score.

### 1. Software quality (did the understanding defects get fixed?)
| Item | Result |
|---|---|
| False premise of the earlier `claude -p` candidate (cli-2) | **Reproduced and rejected before any backtest.** It claimed the executor rebalances on every small change. The engine probe shows a 0.02 target wiggle produces 0 fills (`engine.py:122`). Measured: only 48.8% (BTC) of small decision changes lead to a fill. Partly true in spirit (about half do), false as stated. Artifact: `artifacts/research/premise_audit/cli2_premises.json`; test `test_rebalance_misconception_is_rejected_before_backtest` |
| Generator context | Technical dossier built from the repo at generation time: commit, file hashes, introspected `BarView` API, 7 engine features each proven by a micro-probe with file:line, numbered engine excerpt, the parent's measured development behaviour, existing building blocks, constraints, premise language. Stored per task under `dossiers/` |
| Premise verification stage | New `PREMISES` stage before `DESIGN`. Checks are executable (engine probes, API introspection, measured parent metrics); a falsified, malformed or entirely unverifiable premise set rejects the task. Applied to all generators (offline operators carry fixed premises) |
| Defect found in the diagnostics given to generators | ETHUSDT v0 is liquidated on **2020-03-13** at 2× leverage, so every full-period ETH diagnostic given to the guided selector and the LLM described a ruined account. Diagnostics are now computed on calendar-year segments with fresh equity and flag ruined years. Walk-forward decisions were not affected |
| Defect in my v0.2 statement | "The multi-horizon ensemble reduced BTC turnover (1111 vs 1439)" **was wrong**: it compared v0 at lookback 72 with the candidate at 336. At default parameters turnover went **up** 6% (894 vs 843). The declared mechanism did not occur |
| Measurement defects found by the pilot and fixed | Code-hash duplicate detection missed a semantic duplicate (B t001 ≈ t002), so a behavioural-duplicate measure was added. "Unstable across periods" was assigned to negligible development gains, so it now requires a gain ≥ 0.10 Sharpe |
| Tests | see the final run in the delivery message |

### 2. Simulator realism (separate track)
| Hypothesis | Result |
|---|---|
| H-cal-1: the 1-minute volatility floor comes from market-maker quote placement (pre-registered in `evaluation/calibration.py`) | **Refuted**: elasticity of volatility to half-spread −0.12, not monotonic. Volatility stayed at 14–18 bps vs 4.0 bps target (3 seeds per point). `artifacts/calibration/mm_sensitivity.json` |
| Volatility gap | Still about 3.5–4.4× historical. Not solved |

### 3. Strategy robustness [HISTORICAL BACKTEST]
- **Promotions:** 0. No candidate in any arm passed the frozen promotion rule.
- **Simple reference beats every candidate.** On validation, every candidate evaluated in v0.3 had a negative Sharpe (−0.01 to −0.52), while a constant 50% long exposure had **+0.66**. Beating the weak v0 would not have justified the added complexity.
- **Validation is compromised for confirmation** (48 distinct validation trials across labs, and seen by this session). The final BTC/ETH split is consumed. A new reserved set, **vault v2 (SOL/BNB 2024–2026)**, was built and checksummed; only QC counts were computed. It is not independent of the regime knowledge of 2024–2026 (see `evals/frozen/exposure_registry.json`).

### 4. Research-process efficiency (pilot, pre-registered: `evals/frozen/generator_comparison_v1.json`)
PILOT with n = 3 tasks per arm: a mechanism and cost check only, no inferential claim (all Wilson intervals overlap).

| Metric | A: offline grammar | B: LLM + verified dossier | C: B + memory of failures |
|---|---|---|---|
| Premises correct | 3/3 | 3/3 | 3/3 |
| Executable candidates | 3/3 | 3/3 | 3/3 |
| Code duplicates of earlier experiments | 2/3 | 0/3 | 0/3 |
| Behavioural duplicates (identical results) | **3/3** | 1/3 | **0/3** |
| Declared mechanism observed | 1/3 | 3/3 | 2/3 |
| Promotions | 0 | 0 | 0 |
| Wall-clock per informative task | 16 s | 180 s | 105 s |
| LLM API-equivalent USD per informative task (CLI estimate, not observed billing) | 0 | 0.147 | 0.259 |

**Decisions that changed because of context and memory:**
1. All 6 LLM proposals in B and C state the rebalance band correctly ("the engine skips trades whose target–position
   gap is below the band"), each verified by the probe. The v0.2 LLM candidate had stated the opposite.
2. A (no memory) proposed a deadzone again and its mechanism failed again (deadzones moved turnover in 1 of 11
   archived tries). C cited 11 archived tries and explained why: deadzones and rounding act on the decision,
   which the band already filters, while fills come from the drifting target–position gap. C then tested
   position size and a regime gate instead.
3. **Next experiment influenced by the pilot** (`cycle_next/next-1`, motivated by p1-B-t001, p1-C-t001, p1-C-t003,
   cli-2, p1-A-t001): a diagnostic sample-and-hold change separating decision-driven fills from drift-driven band
   crossings, with refutation criteria written before evaluation.
   - **Learned (development, measured):** fills/day fell 87% (BTC) and 83% (ETH), so decision re-evaluation, not
     band drift, drives most fills.
   - **Still negative:** validation ΔSharpe −0.17 (P = 0.39), below the constant-long reference.

**Plateau diagnosis and checkpoint (no unbounded loop was run):**
- Every candidate so far is a variant of one 2×-leveraged time-series-momentum family. Cost reductions move the
  intended mechanism (turnover −60 to −87%), but net benefit does not survive validation.
- A constant long exposure beats the whole family on validation. The binding problem is the strategy family and
  its risk level, not execution noise.
- Suggested next questions, none executed:
  - (a) compare against risk-matched simple references on development, before any validation access;
  - (b) allow exposure-level and long-bias hypotheses with the reference as the bar to beat;
  - (c) run the pre-registered full study only with explicit quota approval.
- Checkpoint: all labs are persisted under `artifacts/research/` and can be resumed with `evox research status|run`.

**Full study (planned, NOT run):**
- Size: 10 campaigns × 3 tasks per LLM arm, so the per-campaign cap of 3 calls is unchanged. 30 tasks per arm.
- Estimated cost from the pilot: about 60 LLM calls ≈ USD 9–16 API-equivalent (an estimate; the effect on the
  subscription quota is not observable from here) and about 2–3 h of wall-clock.
- It needs your approval before it can run.

---

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
