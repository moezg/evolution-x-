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
