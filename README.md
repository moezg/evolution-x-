# EVOLUTION X: self-evolving multi-agent market laboratory

A research-grade, **research-only** simulation platform. 256 heterogeneous, stateful agents trade a synthetic
BTC/USDT perpetual on two venues with a real order book. An evolutionary engine and an LLM research council
propose, test and archive improvements to strategies and source code, with human approval required.

> No real-money trading, no exchange order routing, no autonomous merge or deploy. See [docs/SAFETY.md](docs/SAFETY.md).

## Quick start

```bash
make dev        # install deps, build dashboard, serve UI + API on http://localhost:8000
make demo       # seeded 256-agent run (baseline + 5% shock), persisted to artifacts/runs/
make test       # 47 tests incl. property tests and the full sandboxed code-evolution pipeline
make eval       # realism vs historical BTCUSDT data, baselines, ablations -> artifacts/eval/report.md
```

Other commands: `make experiment SCENARIO=whale_liquidation N=8`, `make evolve FAMILY=momentum`,
`make propose KEY=momentum-vol-scaling`, `uv run evox decide <id> approve --reviewer you`, `make council`,
`make bench`. Run with Docker using `docker compose up --build`.

Offline by default: the council uses a deterministic mock LLM. Set `EVOX_LLM=anthropic` with `ANTHROPIC_API_KEY`
(or `EVOX_LLM=openai`) to use a real model; outputs are schema-validated either way.

## What's inside

| Layer | Implementation |
|---|---|
| Kernel (protected) | Deterministic discrete-event queue; price-time FIFO order book with partial fills, cancels, self-trade prevention; integer-exact clearing (fees, funding, maintenance margin, forced liquidation, insurance fund); circuit breakers; per-agent order and market-data latency |
| Agents | 64 retail, 40 momentum, 32 value, 24 market makers, 20 arbitrage, 20 execution (TWAP), 16 whales, 16 leveraged (20x), 12 news, 12 adaptive (bandit learners). Every agent has individually jittered params, private memory, beliefs (AR(1) belief error), reputation, equity curve and lineage |
| Collective | Small-world influence network with reputation-weighted social signal; herding, panic selling, MM liquidity withdrawal, strategy imitation, logged contagion events |
| Modes | **A**: endogenous synthetic market. **B**: historical replay (Binance 1m klines drive the latent fundamental; simulated prices are labelled `counterfactual_synthetic`; the historical series is never overwritten) |
| Scenarios | 5% fundamental drop, flash sell, 70% liquidity drought, whale liquidation, funding spike, news panic, arbitrage outage, momentum dominance; 256 / 1,000 / 10,000 agents |
| Experiments | Paired-seed (common random numbers) Monte Carlo with bootstrap and t-intervals |
| Evaluation | Stylized facts (fat tails, volatility clustering, ACF, Hill tail, volume-volatility correlation) vs. historical train/validation/held-out splits; GBM and zero-intelligence baselines; ablations |
| Evolution | L1 in-sim adaptation and imitation; L2 NSGA-II-style multi-objective genome evolution with novelty, plus champion/challenger gate on validation, held-out report, SQLite lineage and rollback; L3 versioned council prompts scored by grounding; L4 code proposals in git worktrees, network-isolated rlimited sandbox, 9 gates, human approval |
| Council | 8 roles on LangGraph (fan-out/fan-in), Pydantic-validated observations/hypotheses/assumptions/conclusions, budget/cache/retry |
| Dashboard | Next.js + TypeScript + Tailwind static export served by FastAPI: overview, agent explorer, collective behaviour, evolution lab (incl. approval queue), scenario lab, council |

Architecture decisions: [docs/adr/0001-architecture.md](docs/adr/0001-architecture.md).
Measured results, performance and limitations: [docs/STATUS.md](docs/STATUS.md).
