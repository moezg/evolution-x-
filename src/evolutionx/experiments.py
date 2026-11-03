"""What-if experiments: Monte Carlo replications with paired (common-random-number) baselines.

For every seed we run the scenario twice: once with the shock armed and once
disarmed. Both runs share the seed, so every agent's random stream is
identical until the shock fires; differences are attributable to the shock.
Reported numbers are distributions with confidence intervals - never a single
"probability". Synthetic replication frequencies are NOT calibrated real-world
probabilities.
"""

from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from .evaluation.metrics import run_metrics
from .evaluation.stats import mean_ci, paired_diff
from .sim.config import SimConfig
from .sim.scenarios import SCENARIOS, scenario_at
from .sim.simulation import Simulation

EXP_DIR = Path("artifacts/experiments")
KEY_METRICS = [
    "shock.min_after_pct",
    "shock.ret_window_pct",
    "shock.ret_end_pct",
    "shock.realized_vol_bps",
    "shock.spread_bps_window",
    "shock.liquidations_window",
    "max_drawdown_pct",
    "liquidations",
    "spread_bps_median",
    "volume_btc",
    "influence_events",
]


def _get(d: dict[str, Any], path: str) -> float:
    cur: Any = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return float("nan")
        cur = cur[k]
    return float(cur) if cur is not None else float("nan")


def _one(args: tuple[str, int, int, float, bool, dict[str, Any]]) -> dict[str, Any]:
    name, seed, duration_s, scale, armed, extra = args
    at = duration_s // 2
    sc = scenario_at(name, at)
    cfg = sc.apply(SimConfig(seed=seed, duration_s=duration_s, scale=scale, **extra), armed=armed)
    sim = Simulation(cfg).run()
    m = run_metrics(sim, shock_at_s=at)
    m["fingerprint"] = sim.fingerprint()
    m["n_agents"] = len(sim.agents)
    return m


def run_experiment(
    scenario: str,
    replicates: int = 8,
    base_seed: int = 1000,
    duration_s: int = 1800,
    scale: float = 1.0,
    workers: int = 4,
    extra: dict[str, Any] | None = None,
    out_dir: Path = EXP_DIR,
    progress=None,
) -> dict[str, Any]:  # noqa: ANN001
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario}")
    extra = extra or {}
    seeds = [base_seed + i for i in range(replicates)]
    jobs = [(scenario, s, duration_s, scale, armed, extra) for s in seeds for armed in (True, False)]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(_one, jobs)):
            results.append(r)
            if progress:
                progress(i + 1, len(jobs))
    treat, base = results[0::2], results[1::2]
    summary = {}
    for k in KEY_METRICS:
        tv, bv = [_get(r, k) for r in treat], [_get(r, k) for r in base]
        summary[k] = {
            "treatment": mean_ci(tv),
            "baseline": mean_ci(bv),
            "paired_diff": paired_diff(tv, bv),
            "treatment_values": tv,
            "baseline_values": bv,
        }
    exp_id = f"{scenario}-n{replicates}-s{base_seed}-d{duration_s}-x{scale:g}"
    report = {
        "experiment_id": exp_id,
        "scenario": scenario,
        "description": SCENARIOS[scenario].description,
        "replicates": replicates,
        "seeds": seeds,
        "duration_s": duration_s,
        "shock_at_s": duration_s // 2,
        "scale": scale,
        "n_agents": treat[0]["n_agents"],
        "design": "paired seeds (common random numbers)",
        "data_label": "synthetic",
        "summary": summary,
        "fingerprints": {"treatment": [r["fingerprint"] for r in treat], "baseline": [r["fingerprint"] for r in base]},
        "realism": {
            "treatment": mean_ci([r["realism"]["score"] for r in treat]),
            "baseline": mean_ci([r["realism"]["score"] for r in base]),
        },
        "caveat": "Frequencies across synthetic replicates are not calibrated real-world probabilities.",
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "reproduce": f"uv run evox experiment {scenario} --replicates {replicates} --seed {base_seed} "
        f"--duration {duration_s} --scale {scale:g}",
    }
    out = out_dir / exp_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=float))
    (out / "report.md").write_text(render_markdown(report))
    return report


def _fmt(x: float) -> str:
    return "n/a" if x != x else f"{x:+.3f}"


def render_markdown(r: dict[str, Any]) -> str:
    lines = [
        f"# Experiment `{r['experiment_id']}`",
        "",
        f"**Scenario:** {r['scenario']} - {r['description']}",
        "",
        f"- Data: **{r['data_label']}** (simulated, not historical)",
        f"- Design: {r['design']}; {r['replicates']} replicates; seeds {r['seeds'][0]}..{r['seeds'][-1]}",
        f"- Agents: {r['n_agents']}; duration {r['duration_s']}s; shock at t={r['shock_at_s']}s",
        f"- Reproduce: `{r['reproduce']}`",
        "",
        "| metric | treatment mean [95% CI] | baseline mean [95% CI] | paired diff [95% CI] | % runs diff>0 |",
        "|---|---|---|---|---|",
    ]
    for k, v in r["summary"].items():
        t, b, d = v["treatment"], v["baseline"], v["paired_diff"]
        lines.append(
            f"| {k} | {_fmt(t['mean'])} [{_fmt(t['lo'])}, {_fmt(t['hi'])}] | {_fmt(b['mean'])} "
            f"[{_fmt(b['lo'])}, {_fmt(b['hi'])}] | {_fmt(d['mean'])} [{_fmt(d['lo'])}, {_fmt(d['hi'])}] | "
            f"{d.get('frac_positive', float('nan')) * 100:.0f}% |"
        )
    lines += ["", f"> {r['caveat']}", ""]
    return "\n".join(lines)
