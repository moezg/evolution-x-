# EVOLUTION X - research-only multi-agent market simulation lab
.PHONY: install dev web demo test test-fast eval lint typecheck data bench experiment evolve propose council clean

PORT ?= 8000

install:            ## install Python deps (uv) and web deps (npm)
	uv sync
	cd web && npm install --no-fund --no-audit

web:                ## build the static dashboard into web/out
	cd web && npm run build

dev: install web    ## single command: build dashboard + serve API/UI on http://localhost:$(PORT)
	uv run evox serve --port $(PORT)

demo:               ## seeded 256-agent simulation (baseline + 5% shock), persisted under artifacts/runs
	uv run evox demo --seed 42 --duration 3600

test:               ## full test suite incl. the sandboxed code-evolution pipeline (~1-2 min)
	uv run pytest

test-fast:
	uv run pytest -m "not slow"

eval:               ## realism vs historical data, baselines, ablations (downloads data on first run)
	uv run evox data
	uv run evox eval --seeds 4 --duration 3600

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

typecheck:
	uv run pyright

data:               ## fetch Binance BTCUSDT 1m archives (train/validation/held-out days)
	uv run evox data

bench:
	uv run evox bench

experiment:         ## e.g. make experiment SCENARIO=liquidity_drought_70 N=8
	uv run evox experiment $(or $(SCENARIO),btc_drop_5pct) --replicates $(or $(N),8)

evolve:
	uv run evox evolve --family $(or $(FAMILY),momentum)

propose:
	uv run evox propose $(if $(KEY),--key $(KEY),)

council:
	uv run evox council

clean:
	rm -rf artifacts web/out web/.next
