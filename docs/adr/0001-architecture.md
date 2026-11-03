# ADR 0001 - Architecture of EVOLUTION X v0.1

Status: accepted (2026-11-03)

## Context

We need a research laboratory with 256 heterogeneous agents trading in a synthetic market, reproducible
experiments, an auditable evolutionary loop and an LLM research council - runnable locally with one command and
fully offline. Correctness of the market (matching, accounting) and reproducibility matter more than raw speed.

## Decisions

| # | Decision | Requirement it serves | Alternatives rejected |
|---|---|---|---|
| 1 | **Pure-Python discrete-event kernel** (`heapq`, keys `(time_ms, priority, seq)`), integer ms clock | Determinism, debuggability; 30-40k events/s is enough for 256-10k agents | ABIDES (heavier, different goals), Ray/async actors (non-deterministic scheduling) |
| 2 | **Integer fixed-point units** (ticks 0.01 USDT, lots 1e-4 BTC, cash micro-USDT) | Exact cash conservation invariant | Floats (rounding drift breaks invariants) |
| 3 | **Cash-settled linear perpetual per venue, cross-margin, 2 venues** | Margin, funding, liquidation, cross-venue arbitrage; sum(position)=0 per venue makes conservation provable | Spot + borrow model (more state, weaker invariants) |
| 4 | **Agents never touch the exchange**: they receive an immutable `Observation` built from public snapshots at `t - latency`, and return validated `Command`s | No look-ahead, information latency, actor-style ownership, safe extension (incl. LLM agents) | Agents calling the exchange API directly |
| 5 | **Strategy pattern as pure functions** `decide(agent, obs) -> [Command]`, one module per family, bounded `PARAM_SPECS` | Interchangeable policies; a narrow, file-level *evolvable zone* for code evolution | Class hierarchies per agent type |
| 6 | **Event sourcing light**: immutable `Trade`/`SimEvent` records, run fingerprint = SHA-256 over trades + final balances | Reproducibility tests, replay gate for candidate patches, audit | Full event store (unneeded at this scale) |
| 7 | **Persistence: Parquet (polars) for run datasets, SQLite for lineage/approvals/audit** | Zero-ops local dev, transactional single-writer registry; PostgreSQL is a drop-in later behind `Archive` | PostgreSQL now (extra service without a multi-user requirement), DuckDB for OLTP-style registry |
| 8 | **FastAPI + Pydantic v2**, read-model projections (`api/views.py`) | Dashboard needs denormalised views (clusters, graph, candles) distinct from the write model -> a light CQRS split only there | GraphQL, separate read DB |
| 9 | **Next.js static export served by FastAPI** | One process, one port for `make dev`; no Node server in production | Separate Next server + proxy |
| 10 | **LangGraph** for the research council | Provider-agnostic (works with our offline mock), explicit deterministic graphs, parallel fan-out/fan-in, HITL interrupts | OpenAI Agents SDK (OpenAI-centric tooling, less natural with a deterministic mock), hand-rolled orchestration |
| 11 | **LLM port with Mock / Anthropic / OpenAI-compatible adapters**, JSON-schema validation, call budget, retries, prompt-hash cache | Offline execution, untrusted-output validation, cost control | SDK-specific calls inside roles |
| 12 | **Code evolution via git worktrees + `unshare -rn` + rlimits + scrubbed env; frozen tests/suite run from a detached baseline worktree at the same base commit** | Isolation, no network, no secrets, independent evaluation, never touching the protected kernel | Docker-in-Docker (not available everywhere), in-process exec (unsafe) |
| 13 | **Human approval records a decision only; merging is manual** | No autonomous merge/deploy | Auto-merge on green gates |
| 14 | **No Kafka/Kubernetes/Ray/microservices** | Not required by any measured bottleneck | - |

## Bounded contexts (packages)

- `kernel/` (TRUSTED, protected): event queue, order book, clearing house, exchange, market data.
- `agents/`, `strategies/`: agent state/population/social network; strategy policies (the only evolvable code).
- `sim/`: orchestration, scenarios, world (fundamental + news), replay (Mode B), persistence.
- `evaluation/` (protected): metrics, stylized facts, statistics, historical reference, frozen suite, eval suite.
- `experiments.py`: paired-seed Monte Carlo what-if experiments.
- `evolution/`: archive, genome operators, multi-objective selection, loop; `evolution/code/` (protected) policy, sandbox, pipeline.
- `council/`: schemas, LLM port/adapters, roles, LangGraph workflow, Evolution Engineer.
- `api/`: FastAPI app, live session, jobs, read models.

## Consequences

- Pure Python caps throughput (~8x real time at 10,000 agents). Optimisation (e.g. a compiled order book) should
  follow profiling; the kernel boundary makes that a local change.
- The perp-only instrument means "BTC falls 5%" is modelled as an exogenous repricing of the latent fundamental
  plus a headline; the traded price response is emergent, not imposed.
