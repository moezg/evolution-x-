# EVOLUTION X - research-only multi-agent market simulation lab
.PHONY: install dev web demo test test-fast eval lint typecheck data bench experiment evolve propose council clean \
	audit data-research backtest calibrate research-smoke research-campaign research-status research-stop archive

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

clean:              ## remove frontend build outputs only (research artifacts are never deleted by make)
	rm -rf web/out web/.next

audit:              ## reproducible baseline capture (commit, tests, deterministic fingerprints)
	uv run evox audit

data-research:      ## Binance USD-M perp 1h klines + funding 2020-01..2026-10, checksums, QC, vault split
	uv run evox data --research

backtest:           ## causal historical backtest of the frozen v0 (STRATEGY=champion for the active version)
	uv run evox backtest --strategy $(or $(STRATEGY),v0) --symbol $(or $(SYMBOL),BTCUSDT) --split $(or $(SPLIT),development)

calibrate:          ## simulator calibration on TRAIN days, evaluated on validation/held-out days
	uv run evox calibrate

research-smoke:     ## short end-to-end research cycle (Linux namespace sandbox required)
	uv run evox research run --root artifacts/research/smoke_demo --campaign smoke --mode smoke --tasks 2

research-campaign:  ## bounded autonomous campaign; caps from evals/frozen/research_policy.json
	uv run evox research run --root artifacts/research/$(or $(LAB),campaign) --campaign $(or $(NAME),c1) --mode autonomous-experimental --selector $(or $(SELECTOR),guided) --tasks $(or $(TASKS),20) --wall 3600

research-status:
	uv run evox research status --root artifacts/research/$(or $(LAB),campaign) --campaign $(or $(NAME),c1)

research-stop:      ## user stop: halts before the next stage; requires `evox research resume --confirm`
	uv run evox research stop --root artifacts/research/$(or $(LAB),campaign) --reason "make research-stop"

archive:            ## source archive of HEAD (no data/artifacts) into dist/
	mkdir -p dist
	git archive --format=tar.gz --prefix=evolution-x/ -o dist/evolution-x-src.tar.gz HEAD
