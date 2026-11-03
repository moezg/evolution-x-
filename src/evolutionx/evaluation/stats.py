"""Small, dependency-light statistics for uncertainty reporting."""

from __future__ import annotations

import math

import numpy as np


def mean_ci(x: list[float] | np.ndarray, level: float = 0.95, n_boot: int = 2000, seed: int = 0) -> dict[str, float]:
    """Mean with a percentile-bootstrap CI (seeded, deterministic). Also returns t-interval."""
    a = np.asarray([v for v in x if v is not None and math.isfinite(v)], dtype=float)
    n = len(a)
    if n == 0:
        return {"n": 0, "mean": float("nan"), "std": float("nan"), "lo": float("nan"), "hi": float("nan")}
    m = float(a.mean())
    sd = float(a.std(ddof=1)) if n > 1 else 0.0
    if n < 2:
        return {"n": n, "mean": m, "std": sd, "lo": m, "hi": m, "t_lo": m, "t_hi": m}
    rng = np.random.default_rng(seed)
    boots = a[rng.integers(0, n, size=(n_boot, n))].mean(axis=1)
    alpha = (1 - level) / 2
    tcrit = _t_crit(n - 1, level)
    se = sd / math.sqrt(n)
    return {
        "n": n,
        "mean": m,
        "std": sd,
        "lo": float(np.quantile(boots, alpha)),
        "hi": float(np.quantile(boots, 1 - alpha)),
        "t_lo": m - tcrit * se,
        "t_hi": m + tcrit * se,
    }


def _t_crit(df: int, level: float) -> float:
    # two-sided 95% t critical values; falls back to normal for large df
    table = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        12: 2.179,
        15: 2.131,
        20: 2.086,
        30: 2.042,
    }
    if abs(level - 0.95) > 1e-9:
        return 1.96
    for k in sorted(table):
        if df <= k:
            return table[k]
    return 1.96


def paired_diff(treat: list[float], base: list[float], seed: int = 0) -> dict[str, float]:
    d = [t - b for t, b in zip(treat, base, strict=True) if math.isfinite(t) and math.isfinite(b)]
    out = mean_ci(d, seed=seed)
    out["frac_positive"] = float(np.mean([v > 0 for v in d])) if d else float("nan")
    out["effect_size_dz"] = out["mean"] / out["std"] if d and out["std"] > 0 else float("nan")
    return out


def excess_kurtosis(r: np.ndarray) -> float:
    r = r - r.mean()
    v = (r**2).mean()
    return float((r**4).mean() / v**2 - 3) if v > 0 else float("nan")


def autocorr(x: np.ndarray, lag: int) -> float:
    if len(x) <= lag + 2:
        return float("nan")
    a, b = x[:-lag], x[lag:]
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def hill_tail_index(r: np.ndarray, frac: float = 0.05) -> float:
    a = np.sort(np.abs(r[r != 0]))[::-1]
    k = max(5, int(len(a) * frac))
    if len(a) <= k + 1:
        return float("nan")
    return float(1.0 / np.mean(np.log(a[:k] / a[k])))


def max_drawdown(prices: np.ndarray) -> float:
    if len(prices) == 0:
        return float("nan")
    peak = np.maximum.accumulate(prices)
    return float(np.max(1 - prices / peak))
