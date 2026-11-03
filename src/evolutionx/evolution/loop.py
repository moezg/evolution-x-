"""Offline evolutionary loop with champion/challenger selection (no LLM required).

Observe -> Hypothesize -> Propose -> Mutate -> Test -> Evaluate -> Select -> Archive

Data hygiene: three disjoint seed/regime sets.
  TRAIN       seeds 100+  regimes {baseline, btc_drop_5pct}           -> drives selection
  VALIDATION  seeds 500+  regimes {baseline, btc_drop_5pct, liquidity_drought_70} -> champion/challenger gate
  HELD-OUT    seeds 900+  regimes {news_panic, whale_liquidation, funding_spike}  -> reported only, never selects
"""

from __future__ import annotations

import datetime as dt
import json
import math
import random
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from ..evaluation.metrics import run_metrics
from ..evaluation.stats import mean_ci, paired_diff
from ..evaluation.stylized import realism_score
from ..sim.config import SimConfig
from ..sim.scenarios import scenario_at
from ..sim.simulation import Simulation
from .archive import Archive
from .genome import crossover, genome_id, mutate, seed_genome
from .selection import novelty, select

TRAIN_REGIMES = ["baseline", "btc_drop_5pct"]
VALIDATION_REGIMES = ["baseline", "btc_drop_5pct", "liquidity_drought_70"]
HELDOUT_REGIMES = ["news_panic", "whale_liquidation", "funding_spike"]
OBJECTIVES = ["ret", "neg_dd", "cvar", "robust", "realism", "neg_cost", "novelty"]
EVO_DIR = Path("artifacts/evolution")


def run_utility(m: dict[str, float]) -> float:
    """Risk-adjusted scalar used for the champion/challenger decision."""
    return m["ret"] - 0.5 * m["dd"] + 0.25 * m["cvar"]


def _eval_job(job: tuple[str, dict[str, float], int, str, int, dict | None]) -> dict[str, Any]:
    family, genome, seed, regime, duration, bands = job
    cfg = scenario_at(regime, duration // 2).apply(SimConfig(seed=seed, duration_s=duration,
                                                             param_overrides={family: genome}))
    try:
        sim = Simulation(cfg).run()
        sim.exchange.check_invariants()
    except AssertionError as e:  # invariant violation -> candidate fails hard
        return {"failed": True, "error": str(e)[:300], "seed": seed, "regime": regime}
    m = run_metrics(sim)
    cohort = [a for a in sim.agents if a.kind == family]
    marks = sim.exchange.marks()
    rets = sorted(sim.clearing.accounts[a.id].equity(marks) / 1e6 / a.capital_usd - 1 for a in cohort)
    realism = realism_score(m["facts"], {k: tuple(v) for k, v in bands.items()} if bands else None)
    wakes = sum(a.wakes for a in cohort) or 1
    return {
        "failed": False, "seed": seed, "regime": regime,
        "ret": float(np.mean(rets) * 100), "dd": float(np.mean([a.max_drawdown for a in cohort]) * 100),
        "cvar": float(np.mean(rets[: max(1, len(rets) // 10)]) * 100),
        "realism": 1 - realism["distance"], "realism_inside": realism["score"],
        "turnover": sum(a.orders_sent for a in cohort) / wakes,
        "abs_pos_btc": float(np.mean([sum(abs(p) for p in sim.clearing.accounts[a.id].positions) / 1e4 for a in cohort])),
        "wall_s": sim.wall_time_s, "market_dd_pct": m["max_drawdown_pct"], "liquidations": m["liquidations"],
    }


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in runs if not r["failed"]]
    if len(ok) < len(runs) or not ok:
        return {"failed": True, "errors": [r.get("error") for r in runs if r["failed"]]}
    rets = [r["ret"] for r in ok]
    return {
        "failed": False,
        "objectives": {"ret": float(np.mean(rets)), "neg_dd": -float(np.mean([r["dd"] for r in ok])),
                       "cvar": float(np.mean([r["cvar"] for r in ok])), "robust": -float(np.std(rets)),
                       "realism": float(np.mean([r["realism"] for r in ok])),
                       "neg_cost": -float(np.mean([r["turnover"] for r in ok])), "novelty": 0.0},
        "utility": float(np.mean([run_utility(r) for r in ok])),
        "behavior": [float(np.mean([r["turnover"] for r in ok])), float(np.mean([r["abs_pos_btc"] for r in ok]))],
        "runs": ok,
    }


class EvolutionRun:
    def __init__(self, family: str = "momentum", generations: int = 3, pop: int = 6, train_seeds: int = 2,
                 val_seeds: int = 3, heldout_seeds: int = 2, duration_s: int = 900, workers: int = 4, seed: int = 0,
                 archive: Archive | None = None, bands: dict[str, tuple[float, float]] | None = None,
                 synthesizer: Callable[[str, list[dict[str, Any]], int], list[dict[str, float]]] | None = None,
                 progress: Callable[[str], None] | None = None) -> None:
        self.family, self.generations, self.pop = family, generations, pop
        self.train = [100 + i for i in range(train_seeds)]
        self.val = [500 + i for i in range(val_seeds)]
        self.heldout = [900 + i for i in range(heldout_seeds)]
        self.duration, self.workers, self.rng = duration_s, workers, random.Random(f"evo:{seed}")
        self.archive = archive or Archive()
        self.bands = {k: list(v) for k, v in bands.items()} if bands else None
        self.synthesizer = synthesizer
        self.progress = progress or (lambda _m: None)
        self.run_id = f"evo-{family}-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%S')}-s{seed}"
        self.config = {"family": family, "generations": generations, "pop": pop, "train_seeds": self.train,
                       "val_seeds": self.val, "heldout_seeds": self.heldout, "duration_s": duration_s,
                       "train_regimes": TRAIN_REGIMES, "val_regimes": VALIDATION_REGIMES,
                       "heldout_regimes": HELDOUT_REGIMES, "seed": seed, "realism_reference": "historical-train"
                       if bands else "literature"}

    # ------------------------------------------------------------------
    def _evaluate(self, genomes: list[dict[str, float]], seeds: list[int], regimes: list[str]) -> list[dict[str, Any]]:
        jobs = [(self.family, g, s, r, self.duration, self.bands) for g in genomes for s in seeds for r in regimes]
        with ProcessPoolExecutor(max_workers=self.workers) as ex:
            res = list(ex.map(_eval_job, jobs))
        per = len(seeds) * len(regimes)
        return [aggregate(res[i * per:(i + 1) * per]) for i in range(len(genomes))]

    def _record(self, gen: int, genome: dict[str, float], origin: str, parents: list[str], ev: dict[str, Any]) -> dict:
        cid = genome_id(self.family, genome)
        c = {"id": cid, "family": self.family, "run_id": self.run_id, "generation": gen, "parents": parents,
             "origin": origin, "genome": genome, "status": "failed" if ev["failed"] else "evaluated",
             "objectives": ev.get("objectives", {}), "behavior": ev.get("behavior", []),
             "train": {"utility": ev.get("utility"), "errors": ev.get("errors")}, "utility": ev.get("utility")}
        return c

    def run(self) -> dict[str, Any]:
        A = self.archive
        A.execute("INSERT INTO evo_runs (run_id, family, config, status, created) VALUES (?,?,?,?,?)",
                  (self.run_id, self.family, json.dumps(self.config), "running", dt.datetime.now(dt.UTC).isoformat()))
        A.audit("evolution-loop", "start_run", self.run_id, self.config)
        champ_row = A.active_champion(self.family)
        if champ_row is None:
            g0 = seed_genome(self.family)
            cid = genome_id(self.family, g0)
            A.add_candidate({"id": cid, "family": self.family, "run_id": self.run_id, "generation": 0, "parents": [],
                             "origin": "default", "genome": g0, "status": "champion"})
            A.promote(self.family, cid, "initial default strategy", {})
            champ_row = A.active_champion(self.family)
        assert champ_row is not None
        champ = A.candidate(champ_row["candidate_id"])
        assert champ is not None
        champ_genome = champ["genome"]
        self.progress(f"champion v{champ_row['version']} {champ['id']}")

        # generation 0: champion + mutants (+ optional LLM-synthesised genomes)
        genomes = [champ_genome] + [mutate(self.family, champ_genome, self.rng, sigma=0.35) for _ in range(self.pop - 1)]
        origins = ["champion"] + ["mutation"] * (self.pop - 1)
        parents = [[]] + [[champ["id"]]] * (self.pop - 1)
        if self.synthesizer:
            for g in self.synthesizer(self.family, A.candidates(self.family)[-30:], 2):
                genomes.append(g)
                origins.append("llm_synthesis")
                parents.append([champ["id"]])
        evs = self._evaluate(genomes, self.train, TRAIN_REGIMES)
        population = [self._record(0, g, o, p, e) for g, o, p, e in zip(genomes, origins, parents, evs, strict=True)]
        behaviors = [c["behavior"] for c in population if c["behavior"]]
        self._finish_generation(population, behaviors)
        self.progress(f"gen 0 evaluated {len(population)}")

        for gen in range(1, self.generations + 1):
            alive = [c for c in population if c["status"] != "failed"]
            parents_sel = select(alive, OBJECTIVES, max(2, self.pop // 2))
            kids, kid_origin, kid_parents = [], [], []
            while len(kids) < self.pop - len(parents_sel):
                a = parents_sel[self.rng.randrange(len(parents_sel))]
                if self.rng.random() < 0.3 and len(parents_sel) > 1:
                    b = parents_sel[self.rng.randrange(len(parents_sel))]
                    g = mutate(self.family, crossover(self.family, a["genome"], b["genome"], self.rng), self.rng, 0.15)
                    kid_origin.append("crossover")
                    kid_parents.append([a["id"], b["id"]])
                else:
                    g = mutate(self.family, a["genome"], self.rng)
                    kid_origin.append("mutation")
                    kid_parents.append([a["id"]])
                kids.append(g)
            evs = self._evaluate(kids, self.train, TRAIN_REGIMES)
            children = [self._record(gen, g, o, p, e) for g, o, p, e in zip(kids, kid_origin, kid_parents, evs, strict=True)]
            self._finish_generation(children, behaviors)
            behaviors += [c["behavior"] for c in children if c["behavior"]]
            pool = parents_sel + [c for c in children if c["status"] != "failed"]
            population = select(pool, OBJECTIVES, self.pop) + [c for c in children if c["status"] == "failed"]
            self.progress(f"gen {gen}: best train utility {max(c['utility'] or -1e9 for c in pool):.3f}")

        return self._champion_challenger(champ, champ_row, population)

    def _finish_generation(self, cands: list[dict[str, Any]], behaviors: list[list[float]]) -> None:
        for c in cands:
            if c["status"] != "failed":
                c["objectives"]["novelty"] = novelty(c["behavior"], [b for b in behaviors if b is not c["behavior"]])
        ok = [c for c in cands if c["status"] != "failed"]
        if ok:
            select(ok, OBJECTIVES, len(ok))  # assigns pareto_rank
        for c in cands:
            existing = self.archive.candidate(c["id"])
            if existing and existing["status"] == "champion":
                continue  # never overwrite the champion's record
            self.archive.add_candidate(c)

    def _champion_challenger(self, champ: dict[str, Any], champ_row: dict[str, Any],
                             population: list[dict[str, Any]]) -> dict[str, Any]:
        A = self.archive
        front = [c for c in population if c["status"] != "failed" and c.get("pareto_rank") == 0 and c["id"] != champ["id"]]
        pool = front or [c for c in population if c["status"] != "failed" and c["id"] != champ["id"]]
        decision: dict[str, Any] = {"run_id": self.run_id}
        if not pool:
            decision.update(decision="no_challenger")
        else:
            ch = max(pool, key=lambda c: c["utility"])
            self.progress(f"validating challenger {ch['id']} vs champion {champ['id']}")
            ev_ch, ev_cp = self._evaluate([ch["genome"], champ["genome"]], self.val, VALIDATION_REGIMES)
            if ev_ch["failed"]:
                verdict, reasons = "rejected", ["challenger failed invariants on validation"]
                evidence: dict[str, Any] = {"errors": ev_ch.get("errors")}
            else:
                u_ch = [run_utility(r) for r in ev_ch["runs"]]
                u_cp = [run_utility(r) for r in ev_cp["runs"]]
                diff = paired_diff(u_ch, u_cp)
                real_gap = ev_ch["objectives"]["realism"] - ev_cp["objectives"]["realism"]
                dd_gap = ev_ch["objectives"]["neg_dd"] - ev_cp["objectives"]["neg_dd"]
                reasons = []
                if not (diff["t_lo"] > 0):
                    reasons.append(f"utility improvement not significant (95% CI lower {diff['t_lo']:.4f} <= 0)")
                if real_gap < -0.05:
                    reasons.append(f"market realism regressed by {-real_gap:.3f}")
                if dd_gap < -1.0:
                    reasons.append(f"drawdown regressed by {-dd_gap:.2f} pct-pts")
                verdict = "promoted" if not reasons else "rejected"
                evidence = {"utility_challenger": mean_ci(u_ch), "utility_champion": mean_ci(u_cp),
                            "paired_diff": diff, "realism_gap": real_gap, "drawdown_gap": dd_gap,
                            "validation_objectives": {"challenger": ev_ch["objectives"], "champion": ev_cp["objectives"]},
                            "per_run": [{"seed": a["seed"], "regime": a["regime"], "u_challenger": run_utility(a),
                                         "u_champion": run_utility(b)} for a, b in zip(ev_ch["runs"], ev_cp["runs"], strict=True)]}
            evidence["reasons"] = reasons
            A.record_challenge(self.family, self.run_id, ch["id"], champ["id"], verdict, evidence)
            if verdict == "promoted":
                v = A.promote(self.family, ch["id"], "won paired validation", evidence)
                decision.update(decision="promoted", version=v)
            else:
                A.set_status(ch["id"], "rejected_regression")
                A.audit("evolution-loop", "reject_challenger", ch["id"], {"reasons": reasons})
                decision.update(decision="rejected")
            decision.update(challenger=ch["id"], champion=champ["id"], evidence=evidence)

        # held-out report: active champion vs. original default, never used for selection
        active = A.active_champion(self.family)
        active_c = A.candidate(active["candidate_id"]) if active else champ
        assert active_c is not None
        default = seed_genome(self.family)
        self.progress("held-out evaluation")
        ev_a, ev_d = self._evaluate([active_c["genome"], default], self.heldout, HELDOUT_REGIMES)
        heldout = {"active_champion": active_c["id"], "regimes": HELDOUT_REGIMES, "seeds": self.heldout}
        if not ev_a["failed"] and not ev_d["failed"]:
            ua = [run_utility(r) for r in ev_a["runs"]]
            ud = [run_utility(r) for r in ev_d["runs"]]
            heldout.update(paired_diff_vs_default=paired_diff(ua, ud), champion=ev_a["objectives"],
                           default=ev_d["objectives"])
        summary = {"run_id": self.run_id, "config": self.config, "decision": decision, "heldout": heldout,
                   "n_candidates": len(A.candidates(self.family, self.run_id))}
        out = EVO_DIR / self.run_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(summary, indent=2, default=_json_default))
        (out / "report.md").write_text(render_report(summary))
        A.execute("UPDATE evo_runs SET status=?, summary=?, finished=? WHERE run_id=?",
                  ("finished", json.dumps(summary, default=_json_default), dt.datetime.now(dt.UTC).isoformat(),
                   self.run_id))
        A.audit("evolution-loop", "finish_run", self.run_id, {"decision": decision.get("decision")})
        return summary


def _json_default(o: Any) -> Any:
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, np.generic):
        return o.item()
    return str(o)


def render_report(s: dict[str, Any]) -> str:
    d = s["decision"]
    lines = [f"# Evolution run `{s['run_id']}`", "", f"Family: **{s['config']['family']}** - "
             f"{s['config']['generations']} generations x {s['config']['pop']} candidates; data: synthetic", "",
             "## Champion / challenger decision", "", f"- Decision: **{d.get('decision')}**"]
    if "challenger" in d:
        ev = d["evidence"]
        lines += [f"- Challenger `{d['challenger']}` vs champion `{d['champion']}`"]
        if "paired_diff" in ev:
            pdf = ev["paired_diff"]
            lines += [f"- Paired utility diff (validation, {pdf['n']} runs): {pdf['mean']:+.4f} "
                      f"[95% t-CI {pdf['t_lo']:+.4f}, {pdf['t_hi']:+.4f}]",
                      f"- Realism gap: {ev['realism_gap']:+.3f}; drawdown gap: {ev['drawdown_gap']:+.3f}"]
        for r in ev.get("reasons", []):
            lines.append(f"- Rejection reason: {r}")
    h = s["heldout"]
    lines += ["", "## Held-out (unseen regimes, reporting only)", "",
              f"Regimes: {', '.join(h['regimes'])}; seeds {h['seeds']}"]
    if "paired_diff_vs_default" in h:
        p = h["paired_diff_vs_default"]
        lines.append(f"- Active champion `{h['active_champion']}` vs default: {p['mean']:+.4f} "
                     f"[95% t-CI {p['t_lo']:+.4f}, {p['t_hi']:+.4f}] (n={p['n']})")
    lines += ["", "Utility = cohort return% - 0.5 x max-drawdown% + 0.25 x CVaR10%. Selection on TRAIN, gate on "
              "VALIDATION, report on HELD-OUT seeds/regimes.", ""]
    return "\n".join(lines)
