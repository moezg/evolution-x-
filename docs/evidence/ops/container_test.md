# Container runtime test (2026-11-04 03:41–03:43 UTC)

The image build (`docker compose build`) could **not** be tested here. Build containers in this sandbox have no DNS and no route to the TLS-intercepting proxy (`Could not resolve 'deb.debian.org'` at the apt step). That is an environment limit, untested here, not a verified property of the Dockerfile.

**What was tested** is the scheduler's container runtime behaviour:
- Image: official `python:3.13-slim` (same interpreter path and version as the project venv).
- Mounts: the repository, including the real `artifacts/` and `data/`.
- Settings: `--restart unless-stopped`, `--stop-timeout 90`.
- Command: `evox ops daemon --interval 20`, started from `/tmp` with `EVOX_ROOT` set.

| Check | Result |
|---|---|
| Ticks run in the container against the real state | yes; `forecast_issue` correctly `pending` (11-03 archive not yet published) |
| Graceful restart (`docker restart`, SIGTERM) | exits during its 1 s sleep slice, restarts, continues |
| Crash (`kill -9` of the daemon from the host) | Docker restarted it automatically (RestartCount 1); the next tick ran within 1 s |
| Persistence across container restarts | `ops.db`: 7 runs for 7 distinct (job, slot) pairs, no duplicates; heartbeat advanced |
| Ledger after both interruptions | `verify` ok, 34 entries, head unchanged |
| Compose health-check expression, run inside the container | exit 0 |

The container was then recreated with `--interval 60` and left running as the live scheduler. Tick log: `container_test_ticks.log`.
