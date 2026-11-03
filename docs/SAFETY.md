# Safety model

EVOLUTION X runs in **research-only mode**. These properties are enforced in code, not just policy text.

| Control | Where | How it is enforced |
|---|---|---|
| No real-money trading / no exchange order routing | whole codebase | There is no exchange client. The only outbound HTTP calls are the read-only Binance public archive download (`data/historical.py`) and optional LLM providers (`council/llm.py`). |
| Market data is read-only and untrusted | `data/historical.py` | Archives are size-capped, schema-validated (monotonic timestamps, OHLC consistency, positivity), checksummed in `manifest.json`, never modified. |
| Agents cannot see the future or hidden state | `sim/simulation.py::observe`, `kernel/marketdata.py` | Observations come from snapshots at `t - md_latency`; news filtered by publication time; the latent fundamental is visible only as a private, noisy, delayed signal to agents with research access. Tested in `tests/test_simulation.py`. |
| No credentials exposed to agents | `agents/base.py` | Agents receive an immutable `Observation`; they hold no reference to the API, environment or file system. |
| Council cannot drive the engine | `council/workflow.py` | The council receives a JSON-only context and returns schema-validated documents; it has no handle on `Simulation`, `Exchange` or the archive's write paths except its own report. |
| Code evolution limited to `src/evolutionx/strategies/*.py` (minus `params.py`) | `evolution/code/policy.py` | Path allowlist checked before a worktree exists; protected-file SHA-256 manifest compared against the base commit inside each worktree. |
| Kernel, security policy, evaluation, CI, deployment are immutable to candidates | `PROTECTED_GLOBS` | Includes `policy.py` itself, `sandbox.py`, `pipeline.py`, `tests/`, `evals/frozen/`, `.github/`, `Dockerfile`, `pyproject.toml`. |
| No shell/network for evolution workers | `evolution/code/sandbox.py` | `unshare -rn` (empty network namespace), `RLIMIT_CPU/AS/FSIZE`, wall timeout, scrubbed env (no API keys, no proxies), temp HOME; AST scan forbids `os/sys/subprocess/socket/...`, `eval/exec/open/getattr`, dunder access. Code that fails the scan is never executed. |
| Independent evaluation | `pipeline.py` | Tests and the frozen suite are taken from a detached worktree at the base commit; the candidate cannot alter them. |
| No autonomous merge / deploy | `pipeline.record_decision` | Approval only records a decision and prints manual merge instructions. There is no merge or deploy code path. |
| Full audit trail | `evolution/archive.py` (`audit` table) | Every proposal, gate outcome, approval/rejection, promotion, rollback and council run is logged with actor and timestamp. |
| Resource quotas + emergency stop | `api/jobs.py`, `api/live.py`, `Simulation.stop` | Max queued jobs (HTTP 429 beyond quota), bounded request parameters, `POST /api/sim/stop` halts the event loop immediately. |
| LLM cost control | `council/llm.py` | Per-run call budget, max output tokens, timeouts, bounded retries, prompt-hash cache; default provider is the offline mock. |
