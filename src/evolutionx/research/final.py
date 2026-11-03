"""Final evaluation on the vault (TRUSTED). Reveals the final split ONCE and records it in the ledger.

Compares, on 2025-07-01..2026-10-31 data never used by any campaign:
  * frozen system: the initial champion v0 (no evolution)
  * each research arm's active champion (e.g. guided vs random experiment selection, equal task budget)
  * benchmarks: flat (no position) and buy-and-hold (constant 0.5 exposure)
Parameters of every strategy are chosen by the same rule as validation: best Sharpe over the 12 months before the
final split. Reported: Sharpe (x1, x2 costs), return, max drawdown, paired stationary-bootstrap vs frozen v0,
Holm-adjusted across the arm comparisons. After this call the final split is CONSUMED.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from ..backtest.engine import CostModel, run_backtest
from ..backtest.metrics import daily_returns, max_drawdown, sharpe
from ..data.datasets import load_split, protocol
from ..stats.overfit import deflated_sharpe, holm, moments, paired_sharpe_bootstrap
from .contract import literal_symbols, param_sets
from .evaluator import EvalConfig, _portfolio, sandbox_decisions
from .supervisor import Lab
from .vault import Vault

FINAL_DIR = Path("artifacts/research/final")


def _eval_strategy(src: str, name: str, hist: dict[str, dict], final: dict[str, dict], proto: dict) -> dict[str, Any]:
    lit = literal_symbols(src)
    psets = param_sets(lit["PARAMS"], lit["PARAM_GRID"])
    per, d1, d2 = {}, {}, {}
    for s in final:
        full = {k: np.concatenate([hist[s][k], final[s][k]]) for k in final[s]}
        n_hist = len(hist[s]["close"])
        decs, _ = sandbox_decisions(
            src, [(f"{s}_all", full, ps) for ps in psets], EvalConfig(proto, 0), f"final-{name}"
        )
        sel_a = int(np.searchsorted(full["open_time"], full["open_time"][n_hist - 1] - 365 * 86_400_000))
        c1 = CostModel.from_protocol(proto, s)
        sc = []
        for d in decs:
            r = run_backtest({k: v[sel_a:n_hist] for k, v in full.items()}, d[sel_a:n_hist], c1)
            sc.append(sharpe(daily_returns(r.equity, r.open_time)[1]))
        best = int(np.argmax(sc))
        seg = {k: v[n_hist:] for k, v in full.items()}
        r1 = run_backtest(seg, decs[best][n_hist:], c1)
        r2 = run_backtest(seg, decs[best][n_hist:], CostModel.from_protocol(proto, s, 2.0))
        d1[s], d2[s] = daily_returns(r1.equity, r1.open_time), daily_returns(r2.equity, r2.open_time)
        per[s] = {
            "params": psets[best],
            "sharpe": sharpe(d1[s][1]),
            "return": float(r1.equity[-1] / r1.equity[0] - 1),
            "max_drawdown": max_drawdown(r1.equity),
            "n_fills": r1.n_fills,
            "liquidations": r1.n_liquidations,
        }
    days, port = _portfolio(d1)
    _, port2 = _portfolio(d2)
    return {
        "name": name,
        "per_symbol": per,
        "sharpe": sharpe(port),
        "sharpe_2x_costs": sharpe(port2),
        "return": float(np.prod(1 + port) - 1),
        "max_drawdown": max_drawdown(np.r_[1.0, np.cumprod(1 + port)]),
        "days": days,
        "daily": port,
    }


def final_report(roots: list[Path], campaign_id: str, reason: str, dry_run: bool = False) -> dict[str, Any]:
    proto = protocol()
    syms = [i["symbol"] for i in proto["instruments"]]
    flab = Lab(FINAL_DIR)
    vault = Vault(flab.memory, flab.journal)
    previously = vault.status()["reveals"]
    if dry_run:  # exercises every code path on the VALIDATION split; the vault is not read, nothing is consumed
        prereg = {"dry_run": True}
        final = {s: load_split(s, "validation") for s in syms}
    else:
        prereg = preregister(roots, campaign_id, flab)
        final = vault.reveal(campaign_id, "supervisor", reason or "final comparison of research arms", syms)
    hist_splits = ("development",) if dry_run else ("development", "validation")
    hist = {s: {k: np.concatenate([load_split(s, sp)[k] for sp in hist_splits]) for k in final[s]} for s in syms}
    labs = [Lab(r) for r in roots]
    v0 = labs[0].registry.load_source(0)[1]
    strategies = {"frozen_v0": v0}
    exploratory: dict[str, str] = {}
    trials = 0
    for r, lab in zip(roots, labs, strict=True):
        if not dry_run:
            lab.journal.append(
                "supervisor", "final_reveal_used", {"campaign": campaign_id, "final_lab": str(FINAL_DIR)}
            )
        v, src = lab.registry.load_source()
        strategies[f"{r.name}_champion_v{v}"] = src
        trials += lab.memory.n_trials("validation")
        best = best_by_development(lab)
        if best:
            exploratory[f"{r.name}_exploratory_best_dev_{best[0]}"] = best[1]
    res = {k: _eval_strategy(src, k, hist, final, proto) for k, src in {**strategies, **exploratory}.items()}
    flat = {s: np.zeros(1) for s in syms}
    _ = flat
    bh = """from __future__ import annotations\n\nNAME = "buy_and_hold"\nPARAMS = {"x": 0.5}\nPARAM_GRID = {"x": [0.5]}\n\n\ndef signal(view, p):\n    return p["x"]\n"""
    res["benchmark_buy_and_hold_0.5"] = _eval_strategy(bh, "bh", hist, final, proto)
    base = res["frozen_v0"]
    comparisons, pvals = {}, {}
    for k, r in res.items():
        if k == "frozen_v0":
            continue
        common = np.intersect1d(r["days"], base["days"])
        a = r["daily"][np.isin(r["days"], common)]
        b = base["daily"][np.isin(base["days"], common)]
        boot = paired_sharpe_bootstrap(a, b, **{"mean_block": 10, "resamples": 2000, "seed": 7})
        comparisons[k] = boot
        pvals[k] = 1 - boot["prob_positive"]
    adj = holm({k: v for k, v in pvals.items() if k in strategies})  # primary (pre-registered) family only
    out_strats = {}
    for k, r in res.items():
        sk, ku = moments(r["daily"])
        sd = r["daily"].std(ddof=1)
        dsr = (
            deflated_sharpe(
                r["daily"].mean() / sd if sd > 0 else 0.0, len(r["daily"]), sk, ku, max(1, trials), (0.5 / 365)
            )
            if k != "frozen_v0" and not k.startswith("benchmark")
            else None
        )
        out_strats[k] = {kk: vv for kk, vv in r.items() if kk not in ("days", "daily")} | {"dsr_vs_all_trials": dsr}
    report = {
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "final_split": proto["splits"]["final"],
        "label": "HISTORICAL BACKTEST (final vault split)",
        "blind": not previously,
        "previous_reveals": previously,
        "validation_trials_across_arms": trials,
        "strategies": out_strats,
        "primary_comparisons": [k for k in strategies if k != "frozen_v0"],
        "exploratory_comparisons": list(exploratory),
        "preregistration": prereg,
        "paired_vs_frozen_v0": comparisons,
        "holm_one_sided_alpha_0.05": adj,
        "note": "DSR uses N = all validation trials across arms and an assumed trial-Sharpe variance of 0.5/yr "
        "(not estimated on final data). One reveal; the final split is consumed afterwards.",
    }
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    if dry_run:
        report["label"] = "DRY RUN on the VALIDATION split (vault not read)"
        (FINAL_DIR / "dryrun").mkdir(exist_ok=True)
        (FINAL_DIR / "dryrun" / f"{campaign_id}.json").write_text(json.dumps(report, indent=2, default=_np))
        return json.loads(json.dumps(report, default=_np))
    (FINAL_DIR / f"{campaign_id}.json").write_text(json.dumps(report, indent=2, default=_np))
    return json.loads(json.dumps(report, default=_np))


def _np(o: Any) -> Any:
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return str(o)


def best_by_development(lab: Lab) -> tuple[str, str] | None:
    """Exploratory pick: highest DEVELOPMENT walk-forward OOS Sharpe among evaluated, non-rejected candidates."""
    best = None
    for r in lab.memory.q(
        "SELECT id, code_sha256, path, status FROM candidates WHERE status IN "
        "('refuted','inconclusive','promote','promoted')"
    ):
        rows = lab.memory.q("SELECT result FROM experiments WHERE candidate_id=? AND stage='eval'", (r["id"],))
        if not rows:
            continue
        dev = rows[0]["result"]["development"]["portfolio_oos_sharpe"]
        if best is None or dev > best[0]:
            best = (dev, r["id"], Path(r["path"]).read_text())
    return (best[1], best[2]) if best else None


def preregister(roots: list[Path], campaign_id: str, flab: Lab) -> dict[str, Any]:
    """Written and journaled BEFORE the vault is read."""
    import hashlib

    plan = {
        "campaign": campaign_id,
        "written_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "arms": [str(r) for r in roots],
        "primary": "each arm's ACTIVE champion vs frozen v0: paired stationary bootstrap of daily net returns on the "
        "final split (block 10d, 2000 resamples, seed 7); Holm across arms at alpha 0.05 (one-sided)",
        "exploratory": "each arm's best candidate by DEVELOPMENT walk-forward OOS Sharpe (never selected on "
        "validation or final data); reported, not used for any claim of progress",
        "benchmark": "constant 0.5 long exposure (buy-and-hold)",
        "parameter_rule": "best Sharpe over the 12 months before the final split",
        "costs": "x1 and x2 of the protocol cost model",
    }
    blob = json.dumps(plan, sort_keys=True)
    plan["sha256"] = hashlib.sha256(blob.encode()).hexdigest()
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    (FINAL_DIR / f"preregistration-{campaign_id}.json").write_text(json.dumps(plan, indent=2))
    flab.journal.append("supervisor", "final_preregistered", {"campaign": campaign_id, "sha256": plan["sha256"]})
    return plan
