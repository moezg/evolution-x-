"""Scaling long BTC exposure inversely to trailing realized volatility improves risk-adjusted return versus constant exposure. Source: arxiv:2601.13757v1. Hypothesis H-fc291fc13d.

Rendered by the research army (role D2) from the reviewed template 'vol_managed_long'."""

from __future__ import annotations

import math

import numpy as np

NAME = 'army_vol_managed_long_fc291fc1'
PARAMS = {"lookback_h": 336.0, "target_vol": 0.4}
PARAM_GRID = {"lookback_h": [168.0, 336.0, 672.0]}

def signal(view, p):
    L = int(p["lookback_h"])
    c = view.close(L + 1)
    if len(c) <= L:
        return 0.0
    ann = float(np.std(np.diff(np.log(c)))) * math.sqrt(8760) + 1e-12
    # exposure 1.0 = engine max leverage (2x); 0.5 = 1x notional; capped at 1x notional
    return max(0.0, min(0.5, 0.5 * float(p["target_vol"]) / ann))
