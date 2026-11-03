"""Benchmarks: flat, buy-and-hold, and turnover-matched random positions (controlled null)."""

from __future__ import annotations

import numpy as np


def flat(n: int) -> np.ndarray:
    return np.zeros(n)


def buy_and_hold(n: int, exposure: float = 0.5) -> np.ndarray:
    return np.full(n, exposure)


def random_matched(n: int, switch_prob: float, seed: int, exposure: float = 0.5) -> np.ndarray:
    """Random long/short/flat regime chain with the same position-change frequency as a candidate."""
    rng = np.random.default_rng(seed)
    states = np.array([-exposure, 0.0, exposure])
    out = np.empty(n)
    s = rng.integers(0, 3)
    for i in range(n):
        if rng.random() < switch_prob:
            s = rng.integers(0, 3)
        out[i] = states[s]
    return out
