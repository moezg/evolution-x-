# EVOLUTION X — web dashboard

Next.js (App Router, static export) + React + TypeScript + Tailwind v4. Candlesticks use
`lightweight-charts` v5; all other charts are small hand-written SVG components.
Research-only: the UI only talks to the local FastAPI simulation backend.

## Develop

```bash
# backend (from repo root)
uv run uvicorn evolutionx.api.app:app --port 8000

# frontend
cd web
npm install
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev   # http://localhost:3000
```

`NEXT_PUBLIC_API_BASE` defaults to same-origin (relative `/api/...`).

## Build

```bash
cd web && npm install && npm run build   # writes web/out (index.html, agents.html, ...)
```

FastAPI serves `web/out` automatically when it exists (override with `EVOX_WEB_DIR`), so after a
build the dashboard is at `http://localhost:8000/`.

## Layout

- `src/app/*/page.tsx` — Overview, Agents, Collective, Evolution (+ code proposals), Scenarios, Council
- `src/components/` — charts (`CandleChart`, `OrderBook`, `charts`, `labs`, `NetworkGraph`), sim controls, UI primitives
- `src/lib/` — API client (`api.ts`), polling / SSE / job hooks (`hooks.ts`), types, formatting, colors

Every chart with market data carries a provenance badge: **SYNTHETIC**, **COUNTERFACTUAL · SYNTHETIC**
(replay mode) or **HISTORICAL** (recorded overlay).
