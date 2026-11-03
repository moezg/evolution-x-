"""Persist runs as reproducible artifacts (Parquet + JSON manifest)."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

import polars as pl

from .. import ENGINE_VERSION

RUNS_DIR = Path("artifacts/runs")


def git_sha() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5, check=False
            ).stdout.strip()
            or "unknown"
        )
    except OSError:
        return "unknown"


def data_label(sim) -> str:  # noqa: ANN001
    return "counterfactual_synthetic" if sim.cfg.mode == "replay" else "synthetic"


def save_run(sim, metrics: dict[str, Any], name: str = "run", root: Path = RUNS_DIR) -> Path:  # noqa: ANN001
    run_id = f"{name}-s{sim.cfg.seed}-{sim.cfg.fingerprint()[:8]}"
    out = root / run_id
    out.mkdir(parents=True, exist_ok=True)
    tr = sim.exchange.trades
    pl.DataFrame(
        {
            "t_ms": [x.t for x in tr],
            "venue": [x.venue for x in tr],
            "price_usd": [x.price / 100 for x in tr],
            "qty_btc": [x.qty / 1e4 for x in tr],
            "buyer": [x.buyer for x in tr],
            "seller": [x.seller for x in tr],
            "aggressor": [x.aggressor_side for x in tr],
        }
    ).write_parquet(out / "trades.parquet")
    cols = sim.series_columns()
    pl.DataFrame([list(r) for r in sim.series], schema=cols, orient="row").write_parquet(out / "series.parquet")
    rows = [
        {
            "venue": v,
            "minute": m,
            "open": c[0],
            "high": c[1],
            "low": c[2],
            "close": c[3],
            "volume_btc": c[4],
            "trades": c[5],
        }
        for v, cs in enumerate(sim.candles)
        for m, c in sorted(cs.items())
    ]
    if rows:
        pl.DataFrame(rows).write_parquet(out / "candles.parquet")
    with (out / "events.jsonl").open("w") as f:
        for e in sorted(sim.exchange.events + sim.sim_events, key=lambda e: e.t):
            f.write(json.dumps({"t": e.t, "type": e.type, "agent": e.agent, "venue": e.venue, "data": e.data}) + "\n")
        for e in sim.influence_events:
            f.write(json.dumps({"type": "influence", **e}) + "\n")
    agents = [
        {
            "id": a.id,
            "kind": a.kind,
            "params": a.params,
            "strategy_version": a.strategy_version,
            "capital_usd": a.capital_usd,
            "lineage": a.lineage,
            "equity_curve": a.equity_curve,
            "max_drawdown": a.max_drawdown,
        }
        for a in sim.agents
    ]
    (out / "agents.json").write_text(json.dumps(agents))
    manifest = {
        "run_id": run_id,
        "data_label": data_label(sim),
        "engine_version": ENGINE_VERSION,
        "git_sha": git_sha(),
        "config": sim.cfg.model_dump(mode="json"),
        "config_fingerprint": sim.cfg.fingerprint(),
        "event_fingerprint": sim.fingerprint(),
        "n_agents": len(sim.agents),
        "counts": sim.counts,
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "historical_source": sim.historical and {k: v for k, v in sim.historical.items() if k != "path"},
        "performance": {
            "wall_time_s": sim.wall_time_s,
            "events": sim.events_processed,
            "events_per_s": sim.events_processed / max(sim.wall_time_s, 1e-9),
        },
        "reproduce": f"uv run evox run --seed {sim.cfg.seed} --duration {sim.cfg.duration_s}",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return out
