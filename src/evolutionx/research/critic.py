"""Critique role: structured, number-backed objections. Every claim references a computed metric."""

from __future__ import annotations

from typing import Any

import numpy as np


def critique(
    task: dict[str, Any],
    cand_eval: dict[str, Any],
    champ_eval: dict[str, Any],
    decision: dict[str, Any] | None,
    n_val_trials: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(claim: str, ref: str, value: Any, severity: str) -> None:
        out.append({"claim": claim, "metric_ref": ref, "value": value, "severity": severity})

    cd, hd = cand_eval["development"], champ_eval["development"]
    wins = []
    for s, v in cd["per_symbol"].items():
        cw = [w["test_sharpe"] for w in v["per_window"]]
        hw = [w["test_sharpe"] for w in hd["per_symbol"][s]["per_window"]]
        wins += [a > b for a, b in zip(cw, hw, strict=False)]
    frac = float(np.mean(wins)) if wins else 0.0
    add(
        f"Candidate beats champion in {sum(wins)}/{len(wins)} development OOS windows",
        "development.per_window",
        round(frac, 3),
        "high" if frac < 0.5 else "info",
    )
    sy = {s: v["oos_sharpe"] for s, v in cd["per_symbol"].items()}
    if len(sy) > 1 and (min(sy.values()) < 0 < max(sy.values())):
        add(
            "Development OOS Sharpe has opposite signs across instruments",
            "development.per_symbol.oos_sharpe",
            sy,
            "high",
        )
    if decision:
        b = decision["bootstrap"]
        add(
            f"Validation delta Sharpe {b['delta_sharpe']:+.3f}, 90% CI [{b['ci90_lo']:+.3f}, {b['ci90_hi']:+.3f}]",
            "decision.bootstrap",
            b["delta_sharpe"],
            "info",
        )
        add(
            f"Deflated Sharpe {decision['dsr']['dsr']:.3f} with N={n_val_trials} validation trials",
            "decision.dsr",
            decision["dsr"]["dsr"],
            "high" if decision["dsr"]["dsr"] < 0.9 else "info",
        )
        failed = [k for k, ok in decision["checks"].items() if not ok]
        if failed:
            add(f"Promotion checks failed: {', '.join(failed)}", "decision.checks", failed, "high")
    add(
        f"Validation split has been used by {n_val_trials} trials so far; its evidential value declines with reuse",
        "memory.trials.validation",
        n_val_trials,
        "medium" if n_val_trials > 20 else "info",
    )
    return out
