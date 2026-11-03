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
    if a.research:
        from .data.datasets import build_all

        m = build_all()
        _print(
            {
                s: {"qc": v["qc"], "files": v["files"], "checksums": v["all_checksums_verified"]}
                for s, v in m["instruments"].items()
            }
        )


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


def cmd_audit(a: argparse.Namespace) -> None:
    from .research.audit import capture_baseline, verify_baseline

    if a.verify:
        _print(verify_baseline(Path(a.verify)))
    else:
        _print(capture_baseline(run_tests=not a.no_tests))


def _lab(root: str, generator: str = "offline"):  # noqa: ANN202
    from .research.supervisor import Lab, Supervisor

    lab = Lab(Path(root), repo=Path.cwd())
    sup = Supervisor(lab)
    if generator == "claude-cli":
        from .research.llm_connectors import ClaudeCLIGenerator

        sup.generator = ClaudeCLIGenerator(sup.policy["llm"]["connectors"]["claude-cli"])
    return lab, sup


def cmd_backtest(a: argparse.Namespace) -> None:
    from .backtest.engine import CostModel, run_backtest
    from .backtest.metrics import summarize
    from .data.datasets import load_split, protocol
    from .research.contract import literal_symbols
    from .research.evaluator import EvalConfig, sandbox_decisions

    if a.strategy == "v0":
        src = Path("src/evolutionx/evolvable/tsmom_v0.py").read_text()
    elif a.strategy == "champion":
        lab, _ = _lab(a.root)
        v, src = lab.registry.load_source()
        print(f"active champion: v{v} ({(lab.registry.active() or {}).get('candidate_id')})")
    else:
        src = Path(a.strategy).read_text()
    proto = protocol()
    d = load_split(a.symbol, a.split)
    lit = literal_symbols(src)
    from .research import sandbox

    if sandbox.AVAILABLE:
        decs, _ = sandbox_decisions(src, [("bt", d, lit["PARAMS"])], EvalConfig(proto, 0), "bt")
    elif a.strategy == "v0":  # trusted in-repo file: in-process execution is acceptable without a sandbox
        import importlib

        from .backtest.interface import decisions_for, load_module_strategy

        decs = [decisions_for(load_module_strategy(importlib.import_module("evolutionx.evolvable.tsmom_v0")), d)]
    else:
        raise SystemExit(
            "sandbox unavailable on this host (needs Linux user/mount/net namespaces): generated code is not executed"
        )
    r = run_backtest(d, decs[0], CostModel.from_protocol(proto, a.symbol, a.costs))
    print(f"[HISTORICAL BACKTEST] {a.symbol} {a.split} params={lit['PARAMS']} cost_multiplier={a.costs}")
    _print(summarize(r))


def cmd_research(a: argparse.Namespace) -> None:
    lab, sup = _lab(a.root, a.generator)
    if a.inherit_trials_from:
        print(
            "inherited validation trials:",
            sup.inherit_validation_trials([Path(r) for r in a.inherit_trials_from.split(",")]),
        )
    if a.action == "import":
        hyp = json.loads(Path(a.hypothesis).read_text())
        meta = hyp.pop("_provenance", {})
        r = sup.import_candidate(
            a.campaign,
            a.mode,
            Path(a.source).read_text(),
            hyp,
            meta.get("generator", "unknown"),
            meta.get("provenance", ""),
            meta.get("exposure", []),
            meta.get("risk", ""),
        )
        print("imported:", r)
        st = sup.run(a.campaign)
    elif a.action == "run":
        sup.create_campaign(a.campaign, a.mode, a.selector, a.tasks, a.wall, a.seed)
        st = sup.run(a.campaign)
    elif a.action == "status":
        st = (
            sup.status(a.campaign) if a.campaign else {"active": lab.registry.active(), "journal": lab.journal.verify()}
        )
    elif a.action == "stop":
        sup.request_stop("human", a.reason)
        st = {"stop_requested": True}
    elif a.action == "resume":
        sup.human_resume("human", confirm=a.confirm)
        st = sup.run(a.campaign) if a.campaign else {"stop_cleared": True}
    elif a.action == "rollback":
        st = lab.registry.rollback("human", a.reason)
    elif a.action == "verify":
        st = {
            "journal": lab.journal.verify(),
            "versions": [
                {
                    "version": m["version"],
                    "sha256_ok": __import__("hashlib")
                    .sha256((lab.root / "registry" / "versions" / f"v{m['version']}" / "strategy.py").read_bytes())
                    .hexdigest()
                    == m["sha256"],
                }
                for m in lab.registry.versions()
            ],
        }
    else:
        from .research.final import final_report

        st = final_report([Path(r) for r in a.roots.split(",")], a.campaign or "final-comparison", a.reason)
    _print(st)


def cmd_compare(a: argparse.Namespace) -> None:
    from .research.compare import report, run_arm

    arms = a.arms.split(",")
    if not a.report_only:
        for arm in arms:
            print("running arm", arm)
            run_arm(arm, a.tag, a.tasks)
    r = report(a.tag, arms)
    for arm, m in r["arms"].items():
        print(
            arm,
            {
                k: m[k]
                for k in (
                    "tasks",
                    "premise_correct_rate",
                    "executable_rate",
                    "duplicate_rate",
                    "mechanism_observed_rate",
                    "confirmed",
                    "classes",
                )
            },
            m["cost"],
        )


def cmd_reclassify(a: argparse.Namespace) -> None:
    from .research.reclassify import reclassify

    for r in a.roots.split(","):
        _print(reclassify(Path(r)))


def cmd_calibrate(a: argparse.Namespace) -> None:
    from .evaluation.calibration import run_calibration

    r = run_calibration(a.configs, a.search_seeds, a.eval_seeds, a.duration, a.workers)
    e = r["evaluation"]
    for k in ("default", "calibrated"):
        print(k, {s: round(e[k][s]["mean"], 3) for s in ("train_distance", "validation_distance", "heldout_distance")})
    print("selected knobs:", {k: round(v, 3) for k, v in r["selected_knobs"].items()})


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
    sp = add("backtest", cmd_backtest)
    sp.add_argument("--strategy", default="v0", help="v0 | champion | path/to/strategy.py")
    sp.add_argument("--symbol", default="BTCUSDT")
    sp.add_argument("--split", default="development", choices=["development", "validation"])
    sp.add_argument("--costs", type=float, default=1.0, help="cost multiplier (sensitivity)")
    sp.add_argument("--root", default="artifacts/research/main")
    sp = add("research", cmd_research)
    sp.add_argument(
        "action", choices=["run", "import", "status", "stop", "resume", "rollback", "verify", "final-report"]
    )
    sp.add_argument("--generator", default="offline", choices=["offline", "claude-cli"])
    sp.add_argument("--source", help="import: candidate module path")
    sp.add_argument(
        "--hypothesis",
        help="import: pre-registration JSON (statement, mechanism, alternatives, prediction, _provenance)",
    )
    sp.add_argument(
        "--inherit-trials-from", default="", help="comma-separated lab roots whose validation trials count for DSR"
    )
    sp.add_argument("--root", default="artifacts/research/main")
    sp.add_argument("--roots", default="", help="final-report: comma-separated lab roots to compare")
    sp.add_argument("--campaign", default=None)
    sp.add_argument("--mode", default="smoke", choices=["smoke", "research", "autonomous-experimental"])
    sp.add_argument("--selector", default="guided", choices=["guided", "random"])
    sp.add_argument("--tasks", type=int, default=2)
    sp.add_argument("--wall", type=int, default=900)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--reason", default="")
    sp.add_argument("--confirm", action="store_true", help="resume: explicit human confirmation after a stop")
    sp = add("compare", cmd_compare)
    sp.add_argument("--tag", required=True)
    sp.add_argument("--arms", default="A,B,C")
    sp.add_argument("--tasks", type=int, default=3)
    sp.add_argument("--report-only", action="store_true")
    sp = add("reclassify", cmd_reclassify)
    sp.add_argument("--roots", default="artifacts/research/arm_guided,artifacts/research/arm_random")
    sp = add("calibrate", cmd_calibrate)
    sp.add_argument("--configs", type=int, default=16)
    sp.add_argument("--search-seeds", type=int, default=2)
    sp.add_argument("--eval-seeds", type=int, default=6)
    sp.add_argument("--duration", type=int, default=3600)
    sp.add_argument("--workers", type=int, default=4)
    sp = add("audit", cmd_audit)
    sp.add_argument("--no-tests", action="store_true")
    sp.add_argument("--verify", default=None, help="path to a baseline manifest to re-check")
    sp = add("data", cmd_data)
    sp.add_argument("--research", action="store_true", help="also build 2020-2026 perp 1h datasets + vault")
    add("bench", cmd_bench)
    sp = add("serve", cmd_serve)
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--reload", action="store_true")
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
