"""`evox` command-line interface."""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path


def _print(o: object) -> None:
    print(json.dumps(o, indent=2, default=str))


def cmd_run(a: argparse.Namespace) -> None:
    from .evaluation.metrics import run_metrics
    from .sim.config import SimConfig
    from .sim.persist import save_run
    from .sim.scenarios import scenario_at
    from .sim.simulation import Simulation

    cfg = scenario_at(a.scenario, a.duration // 2).apply(SimConfig(seed=a.seed, duration_s=a.duration, scale=a.scale))
    sim = Simulation(cfg).run()
    sim.exchange.check_invariants()
    m = run_metrics(sim, shock_at_s=a.duration // 2 if a.scenario != "baseline" else None)
    path = save_run(sim, m, name=a.scenario)
    print(
        f"agents={len(sim.agents)} trades={len(sim.exchange.trades)} events={sim.events_processed} "
        f"wall={sim.wall_time_s:.1f}s ({sim.events_processed / sim.wall_time_s:,.0f} ev/s)"
    )
    print(
        f"return={m['return_pct']:+.2f}% maxDD={m['max_drawdown_pct']:.2f}% spread={m['spread_bps_median']:.2f}bps "
        f"liquidations={m['liquidations']} realism={m['realism']['score']:.0%}"
    )
    print(f"fingerprint={sim.fingerprint()[:16]}  invariants=OK  saved={path}")


def cmd_demo(a: argparse.Namespace) -> None:
    print("EVOLUTION X demo: seeded 256-agent synthetic market (research-only, no real trading)")
    a.scenario, a.scale = "baseline", 1.0
    cmd_run(a)
    a2 = argparse.Namespace(**{**vars(a), "scenario": "btc_drop_5pct"})
    print("\nStress scenario on the same seed (shock at mid-run):")
    cmd_run(a2)


def cmd_experiment(a: argparse.Namespace) -> None:
    from .experiments import run_experiment

    r = run_experiment(
        a.scenario,
        a.replicates,
        a.seed,
        a.duration,
        a.scale,
        a.workers,
        progress=lambda i, n: print(f"  {i}/{n}", end="\r"),
    )
    print(Path(f"artifacts/experiments/{r['experiment_id']}/report.md").read_text())


def cmd_eval(a: argparse.Namespace) -> None:
    from .evaluation.suite import run_eval

    run_eval(a.seeds, a.duration, a.workers)
    print(Path("artifacts/eval/report.md").read_text())


def cmd_evolve(a: argparse.Namespace) -> None:
    from .council.engineer import synthesize_genomes
    from .evaluation.reference import historical_bands
    from .evolution.loop import EvolutionRun

    r = EvolutionRun(
        a.family,
        a.generations,
        a.pop,
        a.train_seeds,
        a.val_seeds,
        a.heldout_seeds,
        a.duration,
        a.workers,
        a.seed,
        bands=historical_bands(),
        synthesizer=None if a.no_llm else synthesize_genomes,
        progress=print,
    ).run()
    print(Path(f"artifacts/evolution/{r['run_id']}/report.md").read_text())


def cmd_rollback(a: argparse.Namespace) -> None:
    from .evolution.archive import Archive

    _print(Archive().rollback(a.family, actor=a.reviewer) or "nothing to roll back")


def cmd_propose(a: argparse.Namespace) -> None:
    from .evolution.code.pipeline import propose_and_evaluate

    r = propose_and_evaluate(a.key, progress=print)
    print(Path(f"artifacts/proposals/{r['id']}/report.md").read_text())


def cmd_decide(a: argparse.Namespace) -> None:
    from .evolution.code.pipeline import record_decision

    _print(record_decision(a.id, a.decision, a.reviewer, a.comment))


def cmd_council(a: argparse.Namespace) -> None:
    from .council.workflow import run_council

    d = run_council(a.question, a.experiment, progress=print)
    for r in d["roles"]:
        print(f"\n## {r['title']} (grounding {r['grounding']:.0%})")
        for sec in ("observations", "hypotheses", "assumptions", "conclusions"):
            for c in r["output"][sec]:
                print(f"  [{sec[:-1]}] {c['text']}")
    print("\nPrioritised experiments:")
    for e in d["synthesis"]["prioritised_experiments"][:5]:
        print(f"  {e['scenario']} x{e['replicates']} (votes {e['votes']})")


def cmd_data(a: argparse.Namespace) -> None:
    from .data.historical import fetch_splits

    _print({k: [str(p) for p in v] for k, v in fetch_splits().items()})


def cmd_bench(a: argparse.Namespace) -> None:
    from .sim.config import SimConfig
    from .sim.simulation import Simulation

    rows = []
    for scale, dur in ((1.0, 1800), (1000 / 256, 600), (10000 / 256, 120)):
        t = time.perf_counter()
        s = Simulation(SimConfig(seed=1, duration_s=dur, scale=scale, invariant_check_every_s=0))
        build = time.perf_counter() - t
        s.run()
        rows.append(
            {
                "agents": len(s.agents),
                "virtual_s": dur,
                "build_s": round(build, 2),
                "wall_s": round(s.wall_time_s, 2),
                "events": s.events_processed,
                "events_per_s": round(s.events_processed / s.wall_time_s),
                "speedup_vs_realtime": round(dur / s.wall_time_s, 1),
                "trades": len(s.exchange.trades),
            }
        )
        print(rows[-1])
    out = {
        "machine": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
        },
        "results": rows,
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/bench.json").write_text(json.dumps(out, indent=2))


def cmd_serve(a: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("evolutionx.api.app:app", host=a.host, port=a.port, reload=a.reload)


def main() -> None:
    p = argparse.ArgumentParser(prog="evox", description="EVOLUTION X research lab (research-only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn, **defaults) -> argparse.ArgumentParser:  # noqa: ANN001
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
        return sp

    for name, fn in (("run", cmd_run), ("demo", cmd_demo)):
        sp = add(name, fn)
        sp.add_argument("--seed", type=int, default=42)
        sp.add_argument("--duration", type=int, default=3600)
        sp.add_argument("--scenario", default="baseline")
        sp.add_argument("--scale", type=float, default=1.0)
    sp = add("experiment", cmd_experiment)
    sp.add_argument("scenario")
    sp.add_argument("--replicates", type=int, default=8)
    sp.add_argument("--seed", type=int, default=1000)
    sp.add_argument("--duration", type=int, default=1800)
    sp.add_argument("--scale", type=float, default=1.0)
    sp.add_argument("--workers", type=int, default=4)
    sp = add("eval", cmd_eval)
    sp.add_argument("--seeds", type=int, default=4)
    sp.add_argument("--duration", type=int, default=3600)
    sp.add_argument("--workers", type=int, default=4)
    sp = add("evolve", cmd_evolve)
    sp.add_argument("--family", default="momentum")
    sp.add_argument("--generations", type=int, default=3)
    sp.add_argument("--pop", type=int, default=6)
    sp.add_argument("--train-seeds", type=int, default=2)
    sp.add_argument("--val-seeds", type=int, default=3)
    sp.add_argument("--heldout-seeds", type=int, default=2)
    sp.add_argument("--duration", type=int, default=900)
    sp.add_argument("--workers", type=int, default=4)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--no-llm", action="store_true", help="disable (mock) LLM genome synthesis")
    sp = add("rollback", cmd_rollback)
    sp.add_argument("--family", default="momentum")
    sp.add_argument("--reviewer", default="human")
    sp = add("propose", cmd_propose)
    sp.add_argument("--key", default=None)
    sp = add("decide", cmd_decide)
    sp.add_argument("id")
    sp.add_argument("decision", choices=["approve", "reject"])
    sp.add_argument("--reviewer", required=True)
    sp.add_argument("--comment", default="")
    sp = add("council", cmd_council)
    sp.add_argument("--question", default="What mechanisms drive the observed dynamics, and what should we test next?")
    sp.add_argument("--experiment", default=None)
    add("data", cmd_data)
    add("bench", cmd_bench)
    sp = add("serve", cmd_serve)
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--reload", action="store_true")
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
