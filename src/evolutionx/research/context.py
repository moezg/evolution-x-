"""Technical dossier assembled by the TRUSTED supervisor before each generation (read-only, from the real project).

Contents (each item carries a source reference and hash):
  * contract + BarView public API (introspected signatures)
  * execution rules: protocol execution block, CostModel values, engine features proven by micro-probes,
    and a numbered excerpt of the engine's execution/rebalance code
  * parent: version, source, default params, measured development behaviour (yearly segments, ruin flagged)
  * building blocks already implemented by the offline grammar (to avoid re-proposing them unknowingly)
  * constraints and accessible data
  * optional lessons from research memory (see research/lessons.py)
  * the premise / mechanism-test language the answer must use
"""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
import subprocess
from pathlib import Path
from typing import Any

from ..backtest.interface import BarView
from . import premises
from .generator import FILTERS, SIGNALS

SRC = Path(__file__).resolve().parents[1]
MECH_METRICS = (
    "turnover_per_year",
    "avg_holding_bars",
    "trading_cost_share",
    "funding_cost_share",
    "max_drawdown",
    "decision_change_rate",
    "small_change_execution_ratio",
    "fills_per_day",
    "mean_abs_exposure",
    "exposure_frac",
    "gross_sharpe",
    "net_sharpe",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _excerpt(rel: str, start_pat: str, n: int) -> dict[str, Any]:
    p = SRC / rel
    lines = p.read_text().splitlines()
    i = next(k for k, ln in enumerate(lines) if start_pat in ln)
    return {
        "file": f"src/evolutionx/{rel}",
        "first_line": i + 1,
        "sha256": _sha(p),
        "code": "\n".join(f"{i + 1 + k:4d}  {ln}" for k, ln in enumerate(lines[i : i + n])),
    }


def _head() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False, timeout=5
            ).stdout.strip()
            or "unknown"
        )
    except OSError:
        return "unknown"


def build(
    parent: dict[str, Any],
    diagnostics: dict[str, Any],
    protocol: dict[str, Any],
    policy: dict[str, Any],
    lessons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    feats = premises.feature_registry()
    api = {
        n: str(inspect.signature(getattr(BarView, n))) if callable(getattr(BarView, n)) else "property"
        for n in premises.view_api()
    }
    from .contract import ALLOWED_IMPORTS, FORBIDDEN_ATTRS, MAX_GRID

    d: dict[str, Any] = {
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_commit": _head(),
        "sources": {
            f: _sha(SRC / f)
            for f in (
                "backtest/engine.py",
                "backtest/interface.py",
                "research/contract.py",
                "research/behaviour.py",
                "research/premises.py",
            )
        },
        "contract": {
            "symbols": f"NAME, PARAMS (literal dict), PARAM_GRID (literal dict, <= {MAX_GRID} combos), signal(view, p) -> float in [-1, 1] = target exposure as a fraction of max leverage",
            "allowed_imports": sorted(ALLOWED_IMPORTS),
            "forbidden_attributes": sorted(FORBIDDEN_ATTRS),
            "barview_api": api,
            "barview_semantics": "each method returns a COPY of the last n CLOSED bars (fewer at the start); "
            "view.t is the index of the current closed bar",
        },
        "execution": {
            "protocol": protocol["execution"],
            "engine_features": feats,
            "rebalance_rule": "a target is converted to a quantity from CURRENT equity; the trade is skipped "
            "if |target_qty - position| x price < rebalance_band x max_leverage x equity, "
            "unless the target is exactly 0. The band applies to the gap between target and "
            "position (which drifts with equity and prices), not to the change in decision.",
            "engine_excerpt": _excerpt("backtest/engine.py", "execute the decision of bar t-1", 34),
        },
        "parent": {
            "id": parent["id"],
            "version": parent.get("version"),
            "params": parent.get("params"),
            "source": parent["source"],
            "measured_behaviour_development": diagnostics,
            "behaviour_method": "calendar-year segments with fresh equity; ruined_segments lists years in which "
            "equity fell below 5% (statistics after ruin would be meaningless)",
        },
        "existing_building_blocks": {
            "signals": {k: sorted(v) for k, v in SIGNALS.items()},
            "filters": {k: sorted(v) for k, v in FILTERS.items()},
            "note": "already implemented by the offline generator; re-using one is allowed "
            "but must be justified by a new mechanism or evidence",
        },
        "constraints": {
            "evolvable_zone": policy["evolvable_paths"],
            "never_modified": policy["protected_paths"],
            "data_visible_to_you": "development-period diagnostics only (2020-2023)",
            "evaluation": "walk-forward on development, then frozen promotion rule on validation; you "
            "cannot change evaluator, thresholds, data, permissions or budgets",
        },
        "premise_language": {
            "check_types": {
                "engine_feature": {"feature": sorted(feats), "expect": ["present", "absent"]},
                "view_api": {"method": sorted(api), "expect": ["present", "absent"]},
                "parent_metric": {
                    "metric": list(premises.PARENT_METRICS),
                    "symbol": ["BTCUSDT", "ETHUSDT", "ALL"],
                    "op": list(premises.OPS),
                    "value": "number",
                },
                "unverifiable": {"reason": "text"},
            },
            "rule": "every hypothesis must rest on at least one VERIFIABLE premise; any falsified premise rejects it",
            "mechanism_test": {
                "metric": list(MECH_METRICS),
                "symbol": ["BTCUSDT", "ETHUSDT", "ALL"],
                "direction": ["decrease", "increase"],
                "min_relative_change": "number in (0, 1)",
                "meaning": "measured on development by the trusted evaluator, candidate vs parent",
            },
        },
    }
    if lessons is not None:
        d["lessons_from_memory"] = lessons
    d["dossier_sha256"] = hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()
    return d


def render(d: dict[str, Any]) -> str:
    return json.dumps(d, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
