"""Proper scoring, calibration and paired comparison of forecasts (definitions frozen in forecast_protocol_v1)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

EPS = 1e-4


def brier(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (p - y) ** 2


def logloss(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    q = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(q) + (1 - y) * np.log(1 - q))


def sq_err(f: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (f - y) ** 2


def qlike(f_log: np.ndarray, y_log: np.ndarray) -> np.ndarray:
    """QLIKE on variance: y/f - log(y/f) - 1 with f, y = RV^2 (inputs are log RV)."""
    ratio = np.exp(2 * (y_log - f_log))
    return ratio - np.log(ratio) - 1


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict[str, Any]:
    edges = np.linspace(0, 1, bins + 1)
    rows = []
    ece = 0.0
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= edges[i + 1]))
        n = int(m.sum())
        if n:
            mp, fy = float(p[m].mean()), float(y[m].mean())
            ece += n / len(p) * abs(mp - fy)
            rows.append({"bin": [float(edges[i]), float(edges[i + 1])], "n": n, "mean_p": mp, "freq": fy})
    return {"bins": rows, "ece": ece}


def block_bootstrap_mean(d: np.ndarray, block: int = 10, n_boot: int = 2000, seed: int = 0) -> dict[str, float]:
    """Moving-block bootstrap of the mean of a (serially correlated) loss-difference series."""
    d = np.asarray(d, float)
    n = len(d)
    if n == 0:
        return {"n": 0, "mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "p_better": float("nan")}
    rng = np.random.default_rng(seed)
    b = max(1, min(block, n))
    starts = np.arange(n - b + 1)
    k = math.ceil(n / b)
    means = np.empty(n_boot)
    for i in range(n_boot):
        s = rng.choice(starts, k)
        means[i] = np.concatenate([d[j : j + b] for j in s])[:n].mean()
    m = float(d.mean())
    return {
        "n": n,
        "mean": m,
        "lo": float(np.quantile(means, 0.025)),
        "hi": float(np.quantile(means, 0.975)),
        # one-sided: share of bootstrap means >= 0 when "model better" means a negative loss difference
        "p_better": float(np.mean(means >= 0)),
    }


def holm(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, dict[str, Any]]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out: dict[str, dict[str, Any]] = {}
    still = True
    for i, (k, p) in enumerate(items):
        thr = alpha / (m - i)
        rej = still and p <= thr
        still = rej
        out[k] = {"p": p, "threshold": thr, "reject_null": rej}
    return out


def summarize_binary(p: np.ndarray, y: np.ndarray, p_ref: np.ndarray) -> dict[str, Any]:
    bs = float(brier(p, y).mean())
    ref = float(brier(p_ref, y).mean())
    return {
        "n": len(y),
        "base_rate": float(y.mean()),
        "brier": bs,
        "logloss": float(logloss(p, y).mean()),
        "brier_skill_vs_B0": 1 - bs / ref if ref > 0 else float("nan"),
        "reliability": reliability(p, y),
    }


def summarize_rv(f: np.ndarray, y: np.ndarray, f_ref: np.ndarray) -> dict[str, Any]:
    mse = float(sq_err(f, y).mean())
    return {
        "n": len(y),
        "mse_log_rv": mse,
        "qlike": float(qlike(f, y).mean()),
        "mse_skill_vs_B0": 1 - mse / float(sq_err(f_ref, y).mean()),
        "error_quantiles": [float(q) for q in np.quantile(f - y, [0.05, 0.25, 0.5, 0.75, 0.95])],
    }
