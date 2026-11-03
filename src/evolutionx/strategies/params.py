"""Bounded parameter specifications for every strategy family.

Bounds are hard limits for both in-simulation adaptation (Level 1) and offline
evolution (Level 2). Mutation operators clip to these ranges.
"""

from __future__ import annotations

# param: (default, low, high)
PARAM_SPECS: dict[str, dict[str, tuple[float, float, float]]] = {
    "noise": {
        "p_act": (0.5, 0.05, 1.0),
        "mean_btc": (0.03, 0.002, 0.3),
        "limit_prob": (0.6, 0.0, 1.0),
        "offset_bps": (8.0, 1.0, 50.0),
        "herd": (0.3, 0.0, 1.0),
        "panic_dd": (0.15, 0.03, 0.6),
        "close_prob": (0.1, 0.0, 0.5),
    },
    "momentum": {
        "lookback_s": (120.0, 10.0, 900.0),
        "threshold_bps": (15.0, 2.0, 100.0),
        "max_btc": (2.0, 0.1, 10.0),
        "social_w": (0.3, 0.0, 1.0),
        "slip_bps": (20.0, 2.0, 100.0),
    },
    "value": {
        "k": (1.0, 0.1, 3.0),
        "threshold_bps": (30.0, 5.0, 200.0),
        "max_btc": (8.0, 0.5, 30.0),
        "offset_bps": (2.0, 0.0, 20.0),
        "info_noise_bps": (20.0, 2.0, 200.0),
    },
    "market_maker": {
        "half_spread_bps": (4.0, 0.5, 30.0),
        "quote_btc": (1.0, 0.05, 5.0),
        "levels": (3.0, 1.0, 6.0),
        "level_step_bps": (3.0, 0.5, 20.0),
        "skew_bps_per_btc": (1.5, 0.0, 10.0),
        "max_inv_btc": (15.0, 1.0, 50.0),
        "vol_withdraw_bps": (25.0, 5.0, 200.0),
        "index_w": (0.2, 0.0, 1.0),
    },
    "arbitrage": {"threshold_bps": (2.0, 0.0, 30.0), "max_btc": (3.0, 0.1, 20.0), "max_inv_btc": (15.0, 1.0, 50.0)},
    "execution": {
        "parent_btc": (10.0, 1.0, 100.0),
        "horizon_s": (600.0, 60.0, 3600.0),
        "urgency": (0.3, 0.0, 1.0),
        "p_new": (0.05, 0.0, 0.5),
    },
    "whale": {
        "p_act": (0.3, 0.02, 1.0),
        "size_btc": (40.0, 5.0, 200.0),
        "info_noise_bps": (10.0, 1.0, 100.0),
        "threshold_bps": (50.0, 10.0, 300.0),
        "slip_bps": (20.0, 5.0, 150.0),
        "chunks": (10.0, 1.0, 30.0),
    },
    "leveraged": {
        "lookback_s": (60.0, 10.0, 600.0),
        "threshold_bps": (10.0, 2.0, 80.0),
        "leverage_use": (0.7, 0.1, 1.0),
        "stop_bps": (150.0, 20.0, 1000.0),
        "social_w": (0.5, 0.0, 1.0),
        "funding_sens": (2000.0, 0.0, 20000.0),
    },
    "news": {
        "react_threshold": (0.8, 0.2, 3.0),
        "size_btc": (1.5, 0.1, 10.0),
        "hold_s": (180.0, 10.0, 1800.0),
        "slip_bps": (30.0, 5.0, 150.0),
        "contrarian": (0.1, 0.0, 1.0),
    },
    "adaptive": {
        "lr": (0.1, 0.01, 0.5),
        "temperature": (0.5, 0.05, 3.0),
        "max_btc": (2.0, 0.1, 10.0),
        "lookback_s": (90.0, 10.0, 600.0),
        "risk_adapt": (0.2, 0.0, 1.0),
    },
}


def defaults(kind: str) -> dict[str, float]:
    return {k: v[0] for k, v in PARAM_SPECS[kind].items()}


def clip_params(kind: str, params: dict[str, float]) -> dict[str, float]:
    spec = PARAM_SPECS[kind]
    return {k: min(max(float(params.get(k, d)), lo), hi) for k, (d, lo, hi) in spec.items()}
