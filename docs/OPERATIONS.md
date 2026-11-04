# Operations runbook: continuous prospective forecasting

The scheduler (`src/evolutionx/ops/`) keeps the forecasting lifecycle running without a human:

collect → freeze inputs → issue champion and challengers → persist → wait → resolve from published data → score → drift check → research request

Optional research runs separately and can never block it.

## 1. Jobs

| Job | Class | Slot | What it does |
|---|---|---|---|
| `fetch_data` | critical | hourly | Downloads official Binance daily archives (checksums verified) and updates source health (`up` / `degraded` / `down` after 3 failures) |
| `forecast_issue` | critical | next 00:00 UTC origin | Issues champion and challenger forecasts with a frozen input snapshot (`artifacts/forecast/snapshots/`), model version and feature version. Waits (`pending`) for the previous day's archive while more than 1 h remains, then issues anyway; stale inputs make models abstain to climatology. Never runs after the origin. |
| `forecast_missed_check` | critical | hourly | Every scheduled origin since 2026-11-04 that passed without a champion forecast is appended to the ledger as **missed**. A missed origin can never receive a forecast later. |
| `forecast_resolve` | critical | hourly | Resolves matured forecasts from published bars and refreshes `artifacts/forecast/prospective_status.json` |
| `ledger_verify` | critical | daily | Checks the hash chain and the order invariants (issued before origin, resolved after window end, nothing after a miss); sends an error notification on failure |
| `drift_check` | critical | daily | Calibration and skill drift of resolved forecasts. Alerts create a research request; there is no automatic model switch. |
| `research_army` | optional | daily after 06:00 UTC | One bounded army tick. Skipped when the army is paused or stopped, or when today's budget is spent. |
| `fomc_followup` | optional | 4 h to 7 days after each FOMC statement | Observed 4 h \|return\| (spot daily archives) next to the registered estimate. Descriptive only, not a new test. |

**Ordering:** critical jobs always run first in every tick. An optional job that fails is retried and then marked failed, without touching critical state.

## 2. Guarantees and how they are enforced

| Guarantee | Mechanism | Test (`tests/test_ops.py`) |
|---|---|---|
| A slot runs once | `runs` primary key (job, slot) in `artifacts/ops/ops.db`; terminal statuses are never re-run | `test_slot_runs_exactly_once_across_repeated_ticks` |
| One tick at a time | non-blocking `flock` on `artifacts/ops/scheduler.lock` | `test_overlapping_tick_is_refused_by_the_lock` |
| Restart recovery | a `running` row whose lease expired (default 30 min) is re-run | `test_run_left_running_by_a_killed_process_is_recovered_after_its_lease` |
| Retries | exponential backoff `60 s × 2^(attempt−1)`; `failed` plus an error notification after `max_attempts` | `test_exponential_backoff_then_failure_notification` |
| Waiting for data does not use up attempts | `_status: pending`, re-checked after 10 min | `test_pending_wait_does_not_consume_attempts` |
| Outage detection | `sources` table; DOWN notification after 3 consecutive failures | `test_source_outage_detection` |
| Research failure does not stop forecasting | critical-first ordering, per-job isolation | `test_research_failure_never_stops_forecasting` |
| Budget exhaustion pauses only research | daily `budgets` row; research `skipped` | `test_budget_exhaustion_pauses_only_optional_research`, `test_paused_army_skips_research` |
| No backfill | `issue()` refuses `now ≥ origin`; the ledger refuses forecasts for origins recorded as missed | `test_missed_origins_are_recorded_once_and_never_backfilled`, `test_issue_after_the_deadline_is_refused` |
| Interrupted issuance resumes without duplicates or changes | deterministic forecast ids; already-issued ids are skipped; earlier lines stay byte-identical | `test_interrupted_issuance_resumes_without_duplicates_or_changes` |

## 3. Running it

All times are UTC. Every command anchors itself to the repository root, or to `$EVOX_ROOT`, so it works from any directory.

```bash
evox ops tick       # one tick (for cron)
```

```bash
evox ops daemon --interval 300      # always-on loop; SIGTERM finishes the current tick and exits
```

```bash
evox ops status     # persisted runs, sources, notifications, budget, heartbeat
```

**cron** (`deploy/evox-ops.cron`):

```bash
crontab deploy/evox-ops.cron
```

The cron file runs `evox ops tick` every 5 minutes. Overlapping ticks are refused by the lock.

**systemd:** `deploy/evox-ops.service` with `Restart=always`.

**Docker:** `docker compose up -d scheduler`. The service runs `evox ops daemon` with `./artifacts` and `./data` as volumes and `restart: unless-stopped`. Its health check fails when no tick has completed for 15 min. Section 6 records what was actually tested.

Run exactly **one** scheduler per `artifacts/` directory. The lock protects one host only; it does not protect a shared network volume.

## 4. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `EVOX_ROOT` | repository of the installed package | directory containing `artifacts/`, `data/`, `evals/frozen/` |
| `EVOX_NOTIFY_WEBHOOK` | unset | if set, warnings and errors are POSTed as `{level, job, message}`. They are always stored in `notifications` and printed to stderr. |
| `EVOX_ISSUE_LEAD_H` | 24 | the issuance window opens this many hours before the origin |

Defaults in `ops/scheduler.py: DEFAULTS`:

| Setting | Default |
|---|---|
| research wall time per day | 1800 s |
| LLM calls per day | 3 (the frozen per-cycle cap) |
| lease | 1800 s |
| backoff base | 60 s |
| pending wait | 600 s |

## 5. Procedures

| Situation | What to do |
|---|---|
| Notification "source binance_archives is DOWN" | Check https://data.binance.vision. Nothing else is needed: issuance waits until 1 h before the deadline, then issues with abstentions. If no forecast is issued before 00:00 UTC, the origin is recorded as **missed**. That is the correct outcome, not a failure to hide. |
| `forecast_issue` failed | Read `evox ops status`, fix the cause, run `evox ops tick` again. A failed slot is terminal; the next origin gets a new slot. |
| Scheduler host restarted | Nothing to do. Expired leases are recovered on the next tick, and already-issued forecasts are skipped by id. |
| Research is burning budget | `evox army pause`. Forecasting continues. Resume with `evox army start`. |
| Ledger verification failed | Stop the scheduler and keep the file as evidence. `git diff` against the last commit shows edits; the hash chain names the first bad line. Never "repair" by rewriting history. Corrections are new events. |
| A forecast is late | It cannot be added. The missed-window job records it. |

## 6. What was actually tested (2026-11-04)

See `docs/evidence/ops/` for logs:

- the unit and integration tests above;
- real ticks from `/tmp`, an unrelated working directory;
- a real issuance cycle for origin 2026-11-05 with an interruption and a restart;
- the docker-compose scheduler, built and run with the real volumes.

Anything not listed in the evidence was **not** tested.
