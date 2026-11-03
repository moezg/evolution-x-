"""Look-ahead detection by physical truncation.

A causal strategy's decision at bar k must be identical whether or not bars
after k exist. We recompute decisions on data physically cut after k (the
future is not present in memory) and compare with the decisions produced on the
full series. Check points are drawn by the TRUSTED caller from a seed the
candidate never sees, so a strategy cannot special-case them.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np


def truncate(data: dict[str, np.ndarray], k: int) -> dict[str, np.ndarray]:
    return {key: np.array(v[: k + 1], copy=True) for key, v in data.items()}


def checkpoints(n: int, k: int, seed: int, min_index: int = 200) -> list[int]:
    rng = np.random.default_rng(seed)
    return sorted(
        int(x) for x in rng.choice(np.arange(min_index, n - 1), size=min(k, n - 1 - min_index), replace=False)
    )


def compare(full: np.ndarray, prefix_decisions: dict[int, np.ndarray], tol: float = 1e-9) -> dict:
    bad = []
    for k, d in prefix_decisions.items():
        if len(d) != k + 1:
            bad.append({"k": k, "reason": f"prefix length {len(d)} != {k + 1}"})
            continue
        diff = np.abs(full[: k + 1] - d)
        if np.any(diff > tol):
            i = int(np.argmax(diff > tol))
            bad.append({"k": k, "first_mismatch": i, "full": float(full[i]), "prefix": float(d[i])})
    return {"checked": len(prefix_decisions), "violations": bad, "causal": not bad}


def check_in_process(
    make_decisions: Callable[[dict[str, np.ndarray]], np.ndarray],
    data: dict[str, np.ndarray],
    n_checks: int = 8,
    seed: int = 0,
) -> dict:
    """Convenience for trusted code/tests; untrusted candidates are checked across processes (research.sandbox)."""
    full = make_decisions(data)
    n = len(data["close"])
    pre = {k: make_decisions(truncate(data, k)) for k in checkpoints(n, n_checks, seed)}
    return compare(full, pre)
