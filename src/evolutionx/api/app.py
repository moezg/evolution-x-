"""FastAPI application: live simulation control, read models, labs and approval gates.

Research-only: there is no endpoint that can place orders on a real exchange.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import ENGINE_VERSION
from ..evolution.archive import Archive
from ..experiments import EXP_DIR, run_experiment
from ..sim.config import Shock
from ..sim.scenarios import SCENARIOS
from . import views
from .jobs import JobManager
from .live import LiveSession

app = FastAPI(
    title="EVOLUTION X",
    version=ENGINE_VERSION,
    description="Self-evolving multi-agent market simulation laboratory (research-only).",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

live = LiveSession()
jobs = JobManager()
archive = Archive()


def _require_sim() -> None:
    if live.sim is None:
        raise HTTPException(409, "no simulation running; POST /api/sim/start first")


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "engine_version": ENGINE_VERSION, "mode": "research-only", "real_trading": False}


@app.get("/api/scenarios")
def scenarios() -> list[dict[str, Any]]:
    return [
        {
            "name": s.name,
            "description": s.description,
            "shocks": [x.model_dump() for x in s.shocks],
            "population_overrides": dict(s.population_overrides),
        }
        for s in SCENARIOS.values()
    ]


# ------------------------------------------------------------------ live simulation
class StartRequest(BaseModel):
    seed: int = 42
    duration_s: int = Field(default=3600, ge=60, le=86_400)
    scenario: str = "baseline"
    speed: float = Field(default=20.0, description="virtual seconds per wall second; 0 = max")
    scale: float = Field(default=1.0, gt=0, le=40)
    mode: Literal["synthetic", "replay"] = "synthetic"
    replay_day: str | None = None
    shock_at_s: int | None = None


@app.post("/api/sim/start")
def sim_start(req: StartRequest) -> dict[str, Any]:
    if req.scenario not in SCENARIOS:
        raise HTTPException(400, f"unknown scenario {req.scenario}")
    dataset = None
    if req.mode == "replay":
        day = req.replay_day or "2026-10-01"
        p = Path(f"data/historical/BTCUSDT-1m-{day}.npy")
        if not p.exists():
            raise HTTPException(400, f"historical dataset for {day} not downloaded (run `make data`)")
        dataset = str(p)
    live.start(req.seed, req.duration_s, req.scenario, req.speed, req.scale, req.mode, dataset, req.shock_at_s)
    return live.snapshot(views.state, live.status, live.speed)


@app.post("/api/sim/pause")
def sim_pause() -> dict[str, str]:
    live.pause()
    return {"status": live.status}


@app.post("/api/sim/resume")
def sim_resume() -> dict[str, str]:
    live.resume()
    return {"status": live.status}


@app.post("/api/sim/stop")
def sim_stop() -> dict[str, str]:
    """EMERGENCY STOP: halts the event loop immediately."""
    live.emergency_stop()
    return {"status": live.status}


class SpeedRequest(BaseModel):
    speed: float


@app.post("/api/sim/speed")
def sim_speed(req: SpeedRequest) -> dict[str, float]:
    live.set_speed(req.speed)
    return {"speed": live.speed}


@app.post("/api/sim/inject")
def sim_inject(shock: Shock) -> dict[str, Any]:
    _require_sim()
    try:
        live.inject(shock)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"injected": shock.model_dump()}


@app.post("/api/sim/save")
def sim_save() -> dict[str, str]:
    _require_sim()
    from ..evaluation.metrics import run_metrics
    from ..sim.persist import save_run

    with live.lock:
        assert live.sim is not None
        path = save_run(live.sim, run_metrics(live.sim), name=f"live-{live.scenario}")
    return {"path": str(path)}


@app.get("/api/sim/state")
def sim_state() -> dict[str, Any]:
    s = live.snapshot(views.state, live.status, live.speed)
    return s or {"status": "idle"}


@app.get("/api/sim/candles")
def sim_candles(venue: int = 0) -> dict[str, Any]:
    _require_sim()
    return {
        "venue": venue,
        "data_label": live.snapshot(lambda s: views.state(s, "", 0)["data_label"]),
        "candles": live.snapshot(views.candles, venue),
        "historical": live.snapshot(views.historical_overlay),
    }


@app.get("/api/sim/book")
def sim_book(venue: int = 0, levels: int = Query(20, le=100)) -> dict[str, Any]:
    _require_sim()
    return live.snapshot(views.book, venue, levels)


@app.get("/api/sim/series")
def sim_series(step: int = Query(5, ge=1, le=600)) -> dict[str, Any]:
    _require_sim()
    return live.snapshot(views.series, step)


@app.get("/api/sim/trades")
def sim_trades(limit: int = Query(100, le=1000)) -> list[dict[str, Any]]:
    _require_sim()
    return live.snapshot(views.trades, limit)


@app.get("/api/sim/agents")
def sim_agents() -> list[dict[str, Any]]:
    _require_sim()
    return live.snapshot(views.agents)


@app.get("/api/sim/agents/{aid}")
def sim_agent(aid: int) -> dict[str, Any]:
    _require_sim()
    if live.sim is None or not 0 <= aid < len(live.sim.agents):
        raise HTTPException(404, "agent not found")
    return live.snapshot(views.agent_detail, aid)


@app.get("/api/sim/network")
def sim_network() -> dict[str, Any]:
    _require_sim()
    return live.snapshot(views.network)


@app.get("/api/sim/collective")
def sim_collective() -> dict[str, Any]:
    _require_sim()
    return live.snapshot(views.collective)


@app.get("/api/sim/events")
def sim_events(types: str | None = None, limit: int = Query(200, le=2000)) -> list[dict[str, Any]]:
    _require_sim()
    return live.snapshot(views.events, set(types.split(",")) if types else None, limit)


@app.get("/api/sim/metrics")
def sim_metrics() -> dict[str, Any]:
    _require_sim()
    return live.snapshot(views.metrics)


@app.get("/api/stream")
async def stream() -> StreamingResponse:
    """Server-sent events: compact live state every 500 ms."""

    async def gen():  # noqa: ANN202
        while True:
            s = live.snapshot(views.state, live.status, live.speed) or {"status": "idle"}
            book = live.snapshot(views.book, 0, 15)
            last = live.snapshot(views.candles, 0)
            payload = {"state": s, "book": book, "last_candle": last[-1] if last else None}
            yield f"data: {json.dumps(payload, default=str)}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")


# ------------------------------------------------------------------ jobs
@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return jobs.list()


@app.get("/api/jobs/{jid}")
def get_job(jid: str) -> dict[str, Any]:
    if jid not in jobs.jobs:
        raise HTTPException(404, "job not found")
    return jobs.jobs[jid]


def _quota(fn):  # noqa: ANN001, ANN202
    def wrapped(*a: Any, **k: Any) -> Any:
        try:
            return fn(*a, **k)
        except RuntimeError as e:
            raise HTTPException(429, str(e)) from e

    return wrapped


# ------------------------------------------------------------------ scenario lab
class ExperimentRequest(BaseModel):
    scenario: str
    replicates: int = Field(default=6, ge=2, le=64)
    base_seed: int = 1000
    duration_s: int = Field(default=1800, ge=300, le=14_400)
    scale: float = Field(default=1.0, gt=0, le=40)


@app.post("/api/experiments")
@_quota
def start_experiment(req: ExperimentRequest) -> dict[str, Any]:
    if req.scenario not in SCENARIOS:
        raise HTTPException(400, "unknown scenario")

    def fn(progress, **p):  # noqa: ANN001, ANN003, ANN202
        return run_experiment(**p, progress=lambda i, n: progress(f"{i}/{n} runs"))

    return jobs.submit("experiment", fn, req.model_dump())


@app.get("/api/experiments")
def list_experiments() -> list[dict[str, Any]]:
    out = []
    for p in sorted(EXP_DIR.glob("*/report.json"), key=os.path.getmtime, reverse=True):
        r = json.loads(p.read_text())
        out.append(
            {
                k: r[k]
                for k in (
                    "experiment_id",
                    "scenario",
                    "replicates",
                    "duration_s",
                    "scale",
                    "n_agents",
                    "created_utc",
                    "data_label",
                )
            }
        )
    return out


@app.get("/api/experiments/{eid}")
def get_experiment(eid: str) -> dict[str, Any]:
    p = EXP_DIR / eid / "report.json"
    if not p.exists() or ".." in eid:
        raise HTTPException(404, "experiment not found")
    return json.loads(p.read_text())


@app.get("/api/experiments/{eid}/report.md", response_class=PlainTextResponse)
def get_experiment_md(eid: str) -> str:
    p = EXP_DIR / eid / "report.md"
    if not p.exists() or ".." in eid:
        raise HTTPException(404, "experiment not found")
    return p.read_text()


# ------------------------------------------------------------------ evolution lab
class EvolutionRequest(BaseModel):
    family: str = "momentum"
    generations: int = Field(default=3, ge=1, le=20)
    pop: int = Field(default=6, ge=3, le=24)
    train_seeds: int = Field(default=2, ge=1, le=8)
    val_seeds: int = Field(default=3, ge=2, le=12)
    heldout_seeds: int = Field(default=2, ge=1, le=8)
    duration_s: int = Field(default=900, ge=300, le=7200)
    seed: int = 0
    use_llm_synthesis: bool = True


@app.post("/api/evolution/run")
@_quota
def evolution_run(req: EvolutionRequest) -> dict[str, Any]:
    from ..strategies.params import PARAM_SPECS

    if req.family not in PARAM_SPECS:
        raise HTTPException(400, "unknown family")

    def fn(progress, use_llm_synthesis, **p):  # noqa: ANN001, ANN003, ANN202
        from ..council.engineer import synthesize_genomes
        from ..evaluation.reference import historical_bands
        from ..evolution.loop import EvolutionRun

        return EvolutionRun(
            **p,
            archive=archive,
            bands=historical_bands(),
            synthesizer=synthesize_genomes if use_llm_synthesis else None,
            progress=progress,
        ).run()

    return jobs.submit("evolution", fn, req.model_dump())


@app.get("/api/evolution/lineage")
def evolution_lineage(family: str | None = None) -> dict[str, Any]:
    return {
        "candidates": archive.candidates(family),
        "champions": archive.champions(family),
        "challenges": archive.challenges(family),
        "runs": archive.query("SELECT * FROM evo_runs ORDER BY created DESC"),
    }


class RollbackRequest(BaseModel):
    family: str
    reviewer: str = "human"


@app.post("/api/evolution/rollback")
def evolution_rollback(req: RollbackRequest) -> dict[str, Any]:
    t = archive.rollback(req.family, actor=req.reviewer)
    if t is None:
        raise HTTPException(409, "nothing to roll back to")
    return {"active": t}


@app.get("/api/audit")
def audit(limit: int = 200) -> list[dict[str, Any]]:
    return archive.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))


# ------------------------------------------------------------------ code proposals (Level 4)
class ProposalRequest(BaseModel):
    proposal_key: str | None = None  # pick from the engineer's catalogue; None = next untried


@app.get("/api/proposals")
def proposals() -> list[dict[str, Any]]:
    return archive.query("SELECT * FROM proposals ORDER BY created DESC")


@app.get("/api/proposals/catalogue")
def proposal_catalogue() -> list[dict[str, Any]]:
    from ..council.engineer import catalogue

    return catalogue()


@app.post("/api/proposals/generate")
@_quota
def proposal_generate(req: ProposalRequest) -> dict[str, Any]:
    def fn(progress, proposal_key):  # noqa: ANN001, ANN202
        from ..evolution.code.pipeline import propose_and_evaluate

        return propose_and_evaluate(proposal_key, archive=archive, progress=progress)

    return jobs.submit("proposal", fn, req.model_dump())


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=1, max_length=80)
    comment: str = ""


@app.post("/api/proposals/{pid}/decision")
def proposal_decision(pid: str, d: Decision) -> dict[str, Any]:
    from ..evolution.code.pipeline import record_decision

    try:
        return record_decision(pid, d.decision, d.reviewer, d.comment, archive=archive)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e)) from e


# ------------------------------------------------------------------ research council
class CouncilRequest(BaseModel):
    question: str = "What mechanisms drive price dynamics after the last shock, and what should we test next?"
    experiment_id: str | None = None


@app.post("/api/council/run")
@_quota
def council_run(req: CouncilRequest) -> dict[str, Any]:
    def fn(progress, **p):  # noqa: ANN001, ANN003, ANN202
        from ..council.workflow import run_council

        return run_council(**p, live_sim=live, archive=archive, progress=progress)

    return jobs.submit("council", fn, req.model_dump())


@app.get("/api/council/reports")
def council_reports() -> list[dict[str, Any]]:
    from ..council.workflow import COUNCIL_DIR

    out = []
    for p in sorted(COUNCIL_DIR.glob("*.json"), key=os.path.getmtime, reverse=True)[:30]:
        out.append(json.loads(p.read_text()))
    return out


@app.get("/api/eval/latest")
def eval_latest() -> dict[str, Any]:
    p = Path("artifacts/eval/report.json")
    if not p.exists():
        raise HTTPException(404, "no evaluation yet; run `make eval`")
    return json.loads(p.read_text())


@app.get("/api/runs")
def runs() -> list[dict[str, Any]]:
    out = []
    for p in sorted(Path("artifacts/runs").glob("*/manifest.json"), key=os.path.getmtime, reverse=True)[:50]:
        m = json.loads(p.read_text())
        out.append(
            {
                k: m.get(k)
                for k in (
                    "run_id",
                    "data_label",
                    "created_utc",
                    "event_fingerprint",
                    "n_agents",
                    "performance",
                    "reproduce",
                )
            }
        )
    return out


# ------------------------------------------------------------------ static dashboard
WEB_OUT = Path(os.environ.get("EVOX_WEB_DIR", "web/out"))
if WEB_OUT.exists():
    app.mount("/_next", StaticFiles(directory=WEB_OUT / "_next"), name="next-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        f = WEB_OUT / path
        if path and f.is_file() and WEB_OUT.resolve() in f.resolve().parents:
            return FileResponse(f)
        html = WEB_OUT / f"{path}.html"
        if path and html.is_file():
            return FileResponse(html)
        return FileResponse(WEB_OUT / "index.html")
