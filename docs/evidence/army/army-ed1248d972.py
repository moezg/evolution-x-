"""The position of the close inside its lookback high-low channel predicts continuation. Source: arxiv:2604.01431v1. Hypothesis H-6cac1a9a4c.

Rendered by the research army (role D2) from the reviewed template 'breakout'."""

from __future__ import annotations

import math

import numpy as np

NAME = 'army_breakout_6cac1a9a'
PARAMS = {"lookback_h": 168.0}
PARAM_GRID = {"lookback_h": [84.0, 168.0, 336.0]}

def signal(view, p):
    L = int(p["lookback_h"])
    h, lo, c = view.high(L), view.low(L), view.close(1)
    if len(h) < L or len(c) < 1:
        return 0.0
    hi, lw = float(np.max(h)), float(np.min(lo))
    if hi <= lw:
        return 0.0
    return max(-1.0, min(1.0, (float(c[-1]) - (hi + lw) / 2) / ((hi - lw) / 2)))
