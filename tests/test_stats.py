"""Validation of the statistical tools against a published example and against known nulls."""

import math

import numpy as np

from evolutionx.stats.overfit import deflated_sharpe, holm, paired_sharpe_bootstrap, pbo_cscv


def test_dsr_matches_bailey_lopez_de_prado_numerical_example():
    # Bailey & Lopez de Prado (2014), Deflated Sharpe Ratio: SR=2.5 (annual), T=1250 days, N=100 trials,
    # V[SR]=0.5 (annual), skew=-3, kurtosis=10 -> SR0 ~ 0.1132 per day, DSR ~ 0.9004
    r = deflated_sharpe(2.5 / math.sqrt(250), 1250, -3, 10, 100, 0.5 / 250)
    assert abs(r["sr0"] - 0.1132) < 5e-4 and abs(r["dsr"] - 0.9004) < 5e-4


def test_dsr_of_best_noise_trial_is_rarely_significant():
    rng = np.random.default_rng(1)
    hits = 0
    for _ in range(200):
        m = rng.normal(0, 0.01, (500, 30))
        srs = m.mean(0) / m.std(0, ddof=1)
        best = srs.max()
        hits += deflated_sharpe(best, 500, 0, 3, 30, srs.var(ddof=1))["dsr"] > 0.95
    assert hits / 200 < 0.12  # nominal 5%, allow estimation slack


def test_pbo_noise_is_near_half_and_true_edge_is_low():
    rng = np.random.default_rng(2)
    noise = rng.normal(0, 0.01, (1000, 20))
    assert 0.25 < pbo_cscv(noise)["pbo"] < 0.75
    edge = noise.copy()
    edge[:, 0] += 0.004
    assert pbo_cscv(edge)["pbo"] < 0.1


def test_paired_bootstrap_false_positive_rate_under_null_and_power():
    rng = np.random.default_rng(3)
    fp = 0
    for _ in range(40):
        a, b = rng.normal(0, 0.01, 600), rng.normal(0, 0.01, 600)
        fp += paired_sharpe_bootstrap(a, b, resamples=400, seed=int(rng.integers(1e9)))["prob_positive"] > 0.95
    assert fp / 40 <= 0.15  # nominal 5%
    b = rng.normal(0, 0.01, 800)
    assert paired_sharpe_bootstrap(b + 0.002, b, resamples=400)["prob_positive"] > 0.99


def test_holm_step_down():
    r = holm({"a": 0.001, "b": 0.03, "c": 0.04}, alpha=0.05)
    assert r["a"]["reject_null"] and not r["b"]["reject_null"] and not r["c"]["reject_null"]
