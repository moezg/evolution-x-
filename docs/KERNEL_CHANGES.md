# Trusted-kernel change log

Changes to `src/evolutionx/kernel/` are made by humans only. Code-evolution candidates can never modify the
kernel; the protection policy and sandbox enforce this. Each change carries reference tests and a determinism check
against the recorded baseline (`artifacts/baseline/b89ad877b237/manifest.json`).

## KC-1: bounded insurance fund and socialised losses (2026-11-03)

- **Problem (v0.1.0):** `cover_bankruptcy` debited the insurance fund without a floor, so the fund could go
  arbitrarily negative. That is an implicit, unaccounted credit line.
- **Change:**
  - The fund pays at most its positive balance.
  - Any remaining deficit is charged pro rata to accounts with positive cash: integer allocation, with the
    rounding remainder charged to the largest account. The total is tracked in `socialized_losses`.
  - If the system as a whole is insolvent, the uncovered amount stays visible in `uncovered_losses`.
  - The fund is seeded with external capital (`SimConfig.insurance_fund_usd`, default $1M), recorded as an
    external inflow.
- **Invariant:** cash conservation (`sum(cash) + fee_pool + insurance_fund == initial + external`) still holds
  exactly.
- **Reference tests:**
  - `tests/test_accounting.py::test_kc1_insurance_fund_never_negative_and_losses_socialised`
  - `tests/test_accounting.py::test_kc1_fund_pays_first_when_sufficient`
- **Determinism:** `evox audit --verify artifacts/baseline/b89ad877b237/manifest.json` reproduces both baseline
  fingerprints. No bankruptcy occurs in those runs, so trade histories are unchanged.
- **Remaining limitation:** pro-rata to cash is a simplification. Real venues use ADL ranking by profit and
  leverage.

## KC-2: margin-breach record and secondary-liquidation counterfactual switch (2026-11-03)

- **Why:** experiment C2 has to tell an agent's margin **breach** apart from an **executed** forced liquidation. It also has to run a causal counterfactual in which secondary liquidations are not executed.
- **Change (`kernel/exchange.py` `run_liquidations`):**
  - Every transition of an account into breach is appended to `Exchange.breaches` as {t, agent, equity, gross, executed}.
  - Forced-liquidation fills are summed per account in `Exchange.forced_notional`.
  - An optional `suppress(agent)` predicate records a breach without executing it.
  - `Simulation` passes the predicate only when `SimConfig.execute_secondary_liquidations=False`, and only for the 256 agents. External (primary) accounts are always liquidated.
  - Liquidation-log entries now carry `role` ∈ {primary, secondary}.
- **Default behaviour unchanged:**
  - With the switch at its default (`True`), the field is left out of `SimConfig.fingerprint()`, so config fingerprints stay as they were.
  - The baseline manifest reproduces (`evox audit --verify artifacts/baseline/b89ad877b237/manifest.json`).
  - Four registered v0.4 runs (one each from A, B and two from C) reproduce their run and config fingerprints.
- **Nature:** `execute_secondary_liquidations=False` is a deliberately nonphysical counterfactual, for experiments only. Breached agents keep trading, and can only reduce positions while their equity is ≤ 0.
- **Reference tests:**
  - `tests/test_cascade.py::test_breach_vs_liquidation_and_primary_secondary_classification`
  - `tests/test_cascade.py::test_kc2_default_is_neutral`
  - `tests/test_cascade.py::test_primary_liquidation_survives_the_counterfactual_switch`
