"""Uncertainty and multiple-testing tools.

- Stationary bootstrap (Politis & Romano 1994): resampling that preserves serial dependence.
- Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014): probability that the true Sharpe exceeds the expected
  maximum Sharpe of N unskilled trials, correcting for skew/kurtosis and sample length.
- Probability of Backtest Overfitting via CSCV (Bailey, Borwein, Lopez de Prado & Zhu, "The Probability of
  Backtest Overfitting", https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
- Holm-Bonferroni step-down correction.
"""

from __future__ import annotations

import itertools
import math

import numpy as np

EULER_GAMMA = 0.5772156649015329


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _phi_inv(p: float) -> float:
    # Acklam's rational approximation refined by one Newton step (|err| < 1e-12)
    if not 0 < p < 1:
        raise ValueError("p in (0,1)")
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    q = min(p, 1 - p)
    if q < 0.02425:
        r = math.sqrt(-2 * math.log(q))
        x = (((((c[0] * r + c[1]) * r + c[2]) * r + c[3]) * r + c[4]) * r + c[5]) / (
            (((d[0] * r + d[1]) * r + d[2]) * r + d[3]) * r + 1
        )
        x = x if p < 0.5 else -x
    else:
        r = p - 0.5
        s = r * r
        x = (
            (((((a[0] * s + a[1]) * s + a[2]) * s + a[3]) * s + a[4]) * s + a[5])
            * r
            / (((((b[0] * s + b[1]) * s + b[2]) * s + b[3]) * s + b[4]) * s + 1)
        )
    e = _phi(x) - p
    return x - e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)


def stationary_bootstrap_idx(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap indices (geometric block lengths, circular wrap)."""
    new_block = rng.random(n) < 1.0 / mean_block
    new_block[0] = True
    starts = rng.integers(n, size=n)
    pos = np.arange(n)
    block_start = np.maximum.accumulate(np.where(new_block, pos, 0))
    return (starts[block_start] + (pos - block_start)) % n


def paired_sharpe_bootstrap(
    a: np.ndarray, b: np.ndarray, mean_block: float = 10, resamples: int = 2000, seed: int = 7, periods: float = 365.0
) -> dict[str, float]:
    """Distribution of Sharpe(a) - Sharpe(b) under a joint stationary bootstrap of paired returns."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    assert len(a) == len(b) and len(a) > 10

    def sr(x: np.ndarray) -> float:
        s = x.std(ddof=1)
        return 0.0 if s == 0 else x.mean() / s * math.sqrt(periods)

    rng = np.random.default_rng(seed)
    diffs = np.empty(resamples)
    for i in range(resamples):
        idx = stationary_bootstrap_idx(len(a), mean_block, rng)
        diffs[i] = sr(a[idx]) - sr(b[idx])
    return {
        "delta_sharpe": sr(a) - sr(b),
        "prob_positive": float(np.mean(diffs > 0)),
        "ci90_lo": float(np.quantile(diffs, 0.05)),
        "ci90_hi": float(np.quantile(diffs, 0.95)),
        "ci95_lo": float(np.quantile(diffs, 0.025)),
        "ci95_hi": float(np.quantile(diffs, 0.975)),
        "resamples": resamples,
        "mean_block": mean_block,
    }


def deflated_sharpe(sr: float, t: int, skew: float, kurt: float, n_trials: int, var_trials_sr: float) -> dict:
    """All Sharpe inputs are PER-PERIOD (not annualised). kurt is non-excess kurtosis."""
    if n_trials < 1 or t < 3:
        raise ValueError("need n_trials>=1 and t>=3")
    if n_trials == 1:
        sr0 = 0.0
    else:
        sr0 = math.sqrt(max(var_trials_sr, 0.0)) * (
            (1 - EULER_GAMMA) * _phi_inv(1 - 1 / n_trials) + EULER_GAMMA * _phi_inv(1 - 1 / (n_trials * math.e))
        )
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    z = (sr - sr0) * math.sqrt(t - 1) / math.sqrt(max(denom, 1e-12))
    return {"dsr": _phi(z), "sr0": sr0, "z": z}


def moments(r: np.ndarray) -> tuple[float, float]:
    r = np.asarray(r, float)
    m, s = r.mean(), r.std()
    if s == 0:
        return 0.0, 3.0
    z = (r - m) / s
    return float((z**3).mean()), float((z**4).mean())


def pbo_cscv(returns: np.ndarray, n_blocks: int = 10, periods: float = 365.0) -> dict:
    """returns: (T, N) matrix, one column per trial (strategy configuration)."""
    m = np.asarray(returns, float)
    t_len, n = m.shape
    if n < 2 or n_blocks % 2 or t_len < 2 * n_blocks:
        raise ValueError("need >=2 trials, even n_blocks, enough rows")
    blocks = np.array_split(np.arange(t_len), n_blocks)

    def sr(x: np.ndarray) -> np.ndarray:
        s = x.std(axis=0, ddof=1)
        s[s == 0] = np.inf
        return x.mean(axis=0) / s * math.sqrt(periods)

    logits = []
    for combo in itertools.combinations(range(n_blocks), n_blocks // 2):
        is_idx = np.concatenate([blocks[i] for i in combo])
        oos_idx = np.concatenate([blocks[i] for i in range(n_blocks) if i not in combo])
        best = int(np.argmax(sr(m[is_idx])))
        oos = sr(m[oos_idx])
        rank = float((oos < oos[best]).sum() + 1)  # 1..N
        w = rank / (n + 1)
        logits.append(math.log(w / (1 - w)))
    lg = np.array(logits)
    return {"pbo": float(np.mean(lg <= 0)), "n_combinations": len(lg), "median_logit": float(np.median(lg))}


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, dict[str, float | bool]]:
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(items)
    out: dict[str, dict[str, float | bool]] = {}
    stop = False
    for i, (k, p) in enumerate(items):
        thr = alpha / (m - i)
        rej = (not stop) and p <= thr
        stop = stop or not rej
        out[k] = {"p": p, "threshold": thr, "reject_null": rej}
    return out
