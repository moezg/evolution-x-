"""Trusted evaluator: re-computes every metric from validated decision arrays; never trusts candidate output.

Pipeline for one candidate (all decisions produced in the sandbox):
  1. one run over development+validation data (all param sets, all symbols)
  2. determinism: a second run of the first item must reproduce identical decisions
  3. causality: K runs on data PHYSICALLY truncated at secret checkpoints; decisions must match the full run
  4. development screen: walk-forward (inner param selection, embargo, outer OOS), equal-weight across symbols
  5. validation (only if screened in): params fixed from the last development train window, x1 and x2 costs
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import math
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..backtest.causality import compare, truncate
from ..backtest.engine import CostModel, InvalidDecisions, run_backtest, validate_decisions
from ..backtest.metrics import daily_returns, max_drawdown, sharpe, summarize
from ..backtest.walkforward import walk_forward
from ..stats.overfit import deflated_sharpe, moments, paired_sharpe_bootstrap
from . import sandbox
from .contract import literal_symbols, param_sets, static_check

MAX_DEC_BYTES = 50_000_000
EVALUATOR_VERSION = "evaluator-v2"  # bump when evaluation outputs change (part of the experiment cache key)


class DataSource(Protocol):
    symbols: list[str]

    def get(self, symbol: str, split: str) -> dict[str, np.ndarray]: ...


class RealData:
    def __init__(self, symbols: list[str] | None = None, dev_tail_bars: int | None = None) -> None:
        from ..data.datasets import load_split, protocol

        self.symbols = symbols or [i["symbol"] for i in protocol()["instruments"]]
        self._cache: dict[tuple[str, str], dict[str, np.ndarray]] = {}
        self._load = load_split
        self.dev_tail_bars = dev_tail_bars  # smoke mode: shorter development history

    def get(self, symbol: str, split: str) -> dict[str, np.ndarray]:
        k = (symbol, split)
        if k not in self._cache:
            d = self._load(symbol, split)
            if split == "development" and self.dev_tail_bars:
                d = {kk: v[-self.dev_tail_bars :] for kk, v in d.items()}
            self._cache[k] = d
        return self._cache[k]


def data_sha(ds: DataSource) -> str:
    h = hashlib.sha256()
    for s in ds.symbols:
        for sp in ("development", "validation"):
            d = ds.get(s, sp)
            h.update(s.encode())
            h.update(d["open_time"].tobytes())
            h.update(d["close"].tobytes())
    return h.hexdigest()


def concat(a: dict[str, np.ndarray], b: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {k: np.concatenate([a[k], b[k]]) for k in a}


@dataclass
class EvalConfig:
    protocol: dict[str, Any]
    causality_checks: int = 12
    limits: sandbox.Limits = sandbox.Limits()
    workers: int = 4


class CandidateFailure(RuntimeError):
    def __init__(self, gate: str, detail: Any) -> None:
        super().__init__(f"{gate}: {detail}")
        self.gate, self.detail = gate, detail


def _safe_load(path: Path, n: int) -> np.ndarray:
    st = os.lstat(path)  # never follow symlinks planted by the candidate
    if not stat.S_ISREG(st.st_mode):
        raise CandidateFailure("output_integrity", f"{path.name} is not a regular file")
    if st.st_size > MAX_DEC_BYTES:
        raise CandidateFailure("output_integrity", f"{path.name} too large")
    arr = np.load(path, allow_pickle=False)
    try:
        return validate_decisions(arr, n)
    except InvalidDecisions as e:
        raise CandidateFailure("decision_validity", str(e)) from e


def sandbox_decisions(
    source: str, items: list[tuple[str, dict[str, np.ndarray], dict[str, Any]]], cfg: EvalConfig, tag: str
) -> tuple[list[np.ndarray], dict[str, Any]]:
    """items: (data_key, data, params). Each data_key is written once; ONLY these files are visible."""
    root = Path(tempfile.mkdtemp(prefix=f"evox-{tag}-"))
    ind, outd = root / "in", root / "out"
    ind.mkdir()
    outd.mkdir()
    try:
        (ind / "candidate.py").write_text(source)
        written = set()
        job = []
        for key, data, params in items:
            if key not in written:
                np.savez(ind / f"{key}.npz", **data)  # pyright: ignore[reportArgumentType]
                written.add(key)
            job.append({"data": f"{key}.npz", "params": params})
        (ind / "job.json").write_text(json.dumps({"items": job}))
        res = sandbox.run("evolutionx.research.entry", ["/in", "/out"], ind, outd, cfg.limits)
        if res["returncode"] != 0:
            raise CandidateFailure("sandbox_execution", {"rc": res["returncode"], "stderr": res["stderr"][-1500:]})
        decs = [_safe_load(outd / f"dec_{i}.npy", len(items[i][1]["close"])) for i in range(len(items))]
        return decs, {"wall_s": res["wall_s"]}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _portfolio(daily: dict[str, tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    """Equal-weight across symbols on the intersection of days."""
    days = None
    for d, _ in daily.values():
        days = d if days is None else np.intersect1d(days, d)
    assert days is not None
    rs = [r[np.isin(d, days)] for d, r in daily.values()]
    return days, np.mean(rs, axis=0)


def evaluate(source: str, cand_id: str, ds: DataSource, cfg: EvalConfig, secret_seed: int) -> dict[str, Any]:
    p = cfg.protocol
    issues = static_check(source)
    if issues:
        raise CandidateFailure("static_admissibility", issues)
    lit = literal_symbols(source)
    psets = param_sets(lit["PARAMS"], lit["PARAM_GRID"])
    sym = ds.symbols
    full = {s: concat(ds.get(s, "development"), ds.get(s, "validation")) for s in sym}
    n_dev = {s: len(ds.get(s, "development")["close"]) for s in sym}
    items = [(f"{s}_devval", full[s], ps) for s in sym for ps in psets]
    decs, t1 = sandbox_decisions(source, items, cfg, cand_id[:12])
    dec = {(s, i): decs[k] for k, (s, i) in enumerate((s, i) for s in sym for i in range(len(psets)))}

    # determinism
    again, _ = sandbox_decisions(source, [items[0]], cfg, cand_id[:12] + "-det")
    deterministic = bool(np.array_equal(again[0], decs[0]))
    if not deterministic:
        raise CandidateFailure("determinism", "repeated run produced different decisions")

    # causality: secret checkpoints, each in its own process with physically truncated data
    rng = np.random.default_rng(secret_seed)
    checks = []
    for _ in range(cfg.causality_checks):
        s = sym[int(rng.integers(len(sym)))]
        i = int(rng.integers(len(psets)))
        k = int(rng.integers(500, len(full[s]["close"]) - 1))
        checks.append((s, i, k))

    def one(chk: tuple[str, int, int]) -> tuple[tuple[str, int, int], np.ndarray]:
        s, i, k = chk
        d, _ = sandbox_decisions(source, [(f"{s}_cut", truncate(full[s], k), psets[i])], cfg, cand_id[:8] + "-c")
        return chk, d[0]

    with cf.ThreadPoolExecutor(cfg.workers) as ex:
        results = list(ex.map(one, checks))
    viol = []
    for (s, i, k), d in results:
        rep = compare(dec[(s, i)], {k: d})
        viol += [{"symbol": s, "param_set": i, **v} for v in rep["violations"]]
    causal = {"checked": len(checks), "violations": viol, "causal": not viol, "checkpoints_seed_revealed": secret_seed}
    if viol:
        raise CandidateFailure("causality", causal)

    # development walk-forward
    wf_cfg = p["walk_forward"]
    dev_daily: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    per_symbol: dict[str, Any] = {}
    for s in sym:
        dd = ds.get(s, "development")
        cost = CostModel.from_protocol(p, s)
        wf = walk_forward(dd, {str(i): dec[(s, i)][: n_dev[s]] for i in range(len(psets))}, cost, wf_cfg)
        dev_daily[s] = (wf["oos_days"], wf["oos_daily"])
        per_symbol[s] = {
            "oos_sharpe": wf["oos_sharpe"],
            "n_windows": wf["n_windows"],
            "n_trials": wf["n_trials"],
            "per_window": wf["per_window"],
        }
    days, port = _portfolio(dev_daily)
    report = {
        "candidate_id": cand_id,
        "code_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "param_sets": psets,
        "deterministic": deterministic,
        "causality": causal,
        "timing": t1,
        "development": {
            "portfolio_oos_sharpe": sharpe(port),
            "days": int(len(port)),
            "per_symbol": per_symbol,
            "daily": port.tolist(),
            "day_index": days.tolist(),
        },
    }
    default_index = next((i for i, ps in enumerate(psets) if ps == lit["PARAMS"]), 0)
    report["diagnostics"] = diagnostics(ds, dec, n_dev, p, default_index)
    report["default_param_index"] = default_index
    report["_dec"] = dec  # kept in memory for validation stage (not serialised)
    report["_n_dev"] = n_dev
    report["_full"] = full
    return report


def diagnostics(
    ds: DataSource,
    dec: dict[tuple[str, int], np.ndarray],
    n_dev: dict[str, int],
    p: dict[str, Any],
    default_index: int = 0,
) -> dict[str, Any]:
    """Development-only diagnostics used by the hypothesis formulator (never validation/final data).
    Computed on calendar-year segments with fresh equity (see research/behaviour.py) for the strategy's default
    parameter set (`default_index`)."""
    from .behaviour import behaviour

    out = {}
    for s in ds.symbols:
        dd = ds.get(s, "development")
        out[s] = behaviour(dd, dec[(s, default_index)][: n_dev[s]], CostModel.from_protocol(p, s))
        out[s]["param_index"] = default_index
    return out


def validate_stage(report: dict[str, Any], ds: DataSource, cfg: EvalConfig) -> dict[str, Any]:
    """Validation performance with params fixed on the most recent development train window."""
    p = cfg.protocol
    out: dict[str, Any] = {"per_symbol": {}}
    dailies, dailies2 = {}, {}
    wf = p["walk_forward"]
    for s in ds.symbols:
        dd = ds.get(s, "development")
        n_dev = report["_n_dev"][s]
        full = report["_full"][s]
        cost1, cost2 = CostModel.from_protocol(p, s), CostModel.from_protocol(p, s, 2.0)
        # select params on the last `train_months` of development (chronologically before validation)
        tr_start = int(np.searchsorted(dd["open_time"], dd["open_time"][-1] - wf["train_months"] * 30 * 86_400_000))
        scores = {}
        for i in range(len(report["param_sets"])):
            d = report["_dec"][(s, i)]
            r = run_backtest({k: v[tr_start:n_dev] for k, v in full.items()}, d[tr_start:n_dev], cost1)
            scores[i] = sharpe(daily_returns(r.equity, r.open_time)[1])
        best = max(sorted(scores), key=lambda i: scores[i])
        a = n_dev + wf["embargo_bars"] * 0  # validation starts right after development (selection data ends there)
        seg = {k: v[a:] for k, v in full.items()}
        d = report["_dec"][(s, best)][a:]
        r1, r2 = run_backtest(seg, d, cost1), run_backtest(seg, d, cost2)
        dailies[s] = daily_returns(r1.equity, r1.open_time)
        dailies2[s] = daily_returns(r2.equity, r2.open_time)
        out["per_symbol"][s] = {
            "selected_params": report["param_sets"][best],
            "summary": summarize(r1),
            "net_sharpe_2x_costs": sharpe(dailies2[s][1]),
        }
    days, port = _portfolio(dailies)
    _, port2 = _portfolio(dailies2)
    eq = np.cumprod(1 + port)
    out.update(
        {
            "portfolio_sharpe": sharpe(port),
            "portfolio_sharpe_2x_costs": sharpe(port2),
            "portfolio_max_drawdown": max_drawdown(np.r_[1.0, eq]),
            "days": int(len(port)),
            "daily": port.tolist(),
            "day_index": days.tolist(),
        }
    )
    return out


def decide(
    cand_val: dict[str, Any],
    champ_val: dict[str, Any],
    n_val_trials: int,
    trial_sharpes: list[float],
    protocol: dict[str, Any],
) -> dict[str, Any]:
    """Frozen promotion rule (research_protocol.json -> promotion_rule)."""
    rule = protocol["promotion_rule"]
    sec = rule["secondary_constraints"]
    a_days, a = np.array(cand_val["day_index"]), np.array(cand_val["daily"])
    b_days, b = np.array(champ_val["day_index"]), np.array(champ_val["daily"])
    common = np.intersect1d(a_days, b_days)
    a, b = a[np.isin(a_days, common)], b[np.isin(b_days, common)]
    bs = rule["bootstrap"]
    boot = paired_sharpe_bootstrap(a, b, bs["mean_block_days"], bs["resamples"], bs["seed"])
    sk, ku = moments(a)
    sr_daily = a.mean() / a.std(ddof=1) if a.std(ddof=1) > 0 else 0.0
    var_tr = float(np.var(np.array(trial_sharpes) / math.sqrt(365), ddof=1)) if len(trial_sharpes) > 1 else 0.0
    dsr = deflated_sharpe(sr_daily, len(a), sk, ku, max(1, n_val_trials), var_tr)
    checks = {
        "effect_size": boot["delta_sharpe"] >= rule["minimal_useful_effect_sharpe"],
        "prob_improvement": boot["prob_positive"] >= rule["required_prob_improvement"],
        "drawdown": cand_val["portfolio_max_drawdown"]
        <= champ_val["portfolio_max_drawdown"] + sec["max_drawdown_increase_pct_points"] / 100,
        "cost_robustness": cand_val["portfolio_sharpe_2x_costs"] > sec["net_sharpe_at_2x_costs_min"],
        "deflated_sharpe": dsr["dsr"] >= sec["deflated_sharpe_min"],
    }
    checks = {k: bool(v) for k, v in checks.items()}
    if all(checks.values()):
        verdict = "promote"
    elif boot["prob_positive"] < 0.5:
        verdict = "refuted"
    else:
        verdict = "inconclusive"
    return {
        "verdict": verdict,
        "checks": checks,
        "bootstrap": boot,
        "dsr": dsr,
        "n_validation_trials": n_val_trials,
        "candidate_sharpe": cand_val["portfolio_sharpe"],
        "champion_sharpe": champ_val["portfolio_sharpe"],
        "common_days": int(len(common)),
    }


def strip_private(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if not k.startswith("_")}
