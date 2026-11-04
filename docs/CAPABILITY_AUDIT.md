# Research capability audit (v0.7)

This audit says what each of the 36 research roles **actually is**, judged against the code that runs. The data lives in `src/evolutionx/army/capabilities.py`, is written to `artifacts/army/capability_audit.json`, and is served at `/api/control/army`.

The 256 simulated agents are market participants inside the simulator. They are not researchers.

## Summary

| Class | Roles | Count |
|---|---|---|
| **LLM agent** (an LLM call can produce the role's output) | C1, C2, C3 | 3 |
| **Deterministic analytical worker** (fixed code over data) | A4, B1–B4, F2, F4, G1–G4, H1, H2, H4, I1, I3, I4 | 17 |
| **Tool-based worker** (calls an external API or subsystem) | A1, A2, A3, D2, E1, E4, I2 | 7 |
| **Evaluation / policy engine** (accepts or rejects) | C4, D1, D3, D4, E2, E3, F3, H3 | 8 |
| **Orchestrator** | F1 (army orchestrator and ops scheduler) | 1 |

Only **six** roles ever call an LLM:
- **C1–C3** (default cycle): optional, at most 1 call each, with a deterministic template fallback. C2 has never been activated.
- **E3** (default cycle and on demand): critique only; it can never change a status.
- **A1** and **G1** (on-demand specialist sessions only).

In everything recorded so far, the LLM made **5 calls in the default cycles and 3 in the one specialist session**, about $0.56 API-equivalent in total (CLI estimate, not observed billing).

## Correction made by this audit
The role registry listed **F4 Evolution Coordinator** as `llm_optional`, but no code path calls an LLM for F4. It is a fixed ranking rule (prior × information ÷ cost). The registry now says `deterministic`.

## Specialist agents made operational (P3)
**Session:** `evox army specialists`. Policy: `evals/frozen/specialist_policy_v1.json`.
- Limits: at most 3 calls and $2 per session.
- Each call uses the official claude CLI with no tools, one turn, and an empty temp directory.

| Specialist | What the LLM does | What deterministic code checks before anything is kept |
|---|---|---|
| A1 Research Scout | Picks one record from a real arXiv query and extracts a claim and a **verbatim quote** | The record must be among those fetched; the quote must occur verbatim in its title or abstract |
| G1 Quantitative Scientist | Proposes one hypothesis citing registry test ids and the verified source | Every cited id must exist and be a DISCOVERY row; data needed must be available; family and metric must come from the allowed lists; the label must be an identifier; duplicates of registered or queued hypotheses are rejected |
| E3 Adversarial Scientist | Critiques the proposal (or the claim) | Advisory only; it never changes a status |

Accepted proposals are only *queued for prospective evaluation*. Nothing is tested on historical data, and nothing is promoted.

### First real session (`spec-20261104T031310`)
- **A1:** the arXiv query returned 4 records, none about scheduled macro announcements. The scout said so ("low but the best available") and picked 1405.4498 with a verbatim quote. The quote was verified.
- **G1:** proposed "BTC 4 h |return| after FOMC statements is larger than on matched Wednesdays". In substance this is the already-registered `F-FOMC:absret_0_4h`. The first validator **accepted it as `queued_prospective`**, because the model had put free text in `label`.
  - **Fix:** labels must now be identifiers, and for event families only known conditioning attributes (hike, cut, hold, sep, …) define a new hypothesis.
  - Re-validation without a new LLM call gives `rejected_invalid`. The original verdict is kept, and the correction is appended and journaled.
  - Regression test: `tests/test_specialists.py`.
- **Planted controls:** a duplicate of `F-FOMC:absret_0_4h` gave `rejected_duplicate`. A "hot CPI" hypothesis needing consensus data gave `rejected_invalid`.
- **E3 critique:**
  1. *DST misalignment of control windows.* Checked: not applicable, because placebo windows are built at 14:00 America/New_York per date.
  2. *FOMC-minutes Wednesdays sit in the placebo pool.* Valid. They inflate the placebo mean, so the registered "FOMC > placebo" result is conservative rather than spurious. A sensitivity re-run that excludes minutes days is an open follow-up.
  3. Volatility-regime confounding.
  4. Heavy tails and low power.
- **Cost:** 3 calls, $0.281 API-equivalent, 72 s.

## Not operational as LLM agents (and why)
| Requested specialist | Status |
|---|---|
| Strategy Designer | C1–C3 formulate inside reviewed templates. There is no free-form LLM strategy design: the budget is bounded and the overfitting risk is high. |
| Engineering Agent | D2 renders templates. LLM-written code would need an isolated worktree and human review for every change. The `codeprop` route exists for proposals, but LLM code generation is **not enabled** in this slice. |
| Evolution Coordinator | F4 is a deterministic ranking rule. |

## Measured value per role (P7)
From `artifacts/army/agent_value.json` and `/api/control/army`. Only recorded outcomes count.
- **A3:** 12 sources verified, 6 Crossref matches.
- **A4:** 7 duplicates stopped.
- **D3:** 6 invalid planted candidates rejected.
- **E1:** 2 refuted, 1 inconclusive.
- **H1, I2, G1:** registered tests.

**Controlled with/without comparison for A4 (deduplication).** This is a replay of the recorded cycles using measured per-stage costs; the pipeline was **not** re-run without A4.

| | A4 cost | Downstream pipeline work | Extra counted validation trials | LLM calls |
|---|---|---|---|---|
| With A4 | 1.1 s | none | 0 | 0 |
| Without A4 (estimate) | — | ≈ 241 s | +7 (tighter deflated-Sharpe hurdle for every candidate) | up to +14 |

**Flag rule:** a role with more than 5 s of cost and no recorded outcome is flagged for human review. Nothing is disabled automatically, and agent count is not a goal.

**E3** has found **0 hard failures across 3 challenged candidates.** E1 had already refuted them, so E3's battery has not yet changed an outcome. Its critique in the specialist session did surface a real interpretive issue (FOMC-minutes days). Keep it, and measure it again once a candidate passes E1.
