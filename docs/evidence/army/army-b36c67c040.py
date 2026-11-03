"""Persistent positive (negative) perpetual funding precedes weaker (stronger) BTC returns, so positioning against the funding sign earns a premium net of funding. Source: arxiv:2506.08573v1. Hypothesis H-e80e66194b.

Rendered by the research army (role D2) from the reviewed template 'funding_carry'."""

from __future__ import annotations

import math

import numpy as np

NAME = 'army_funding_carry_e80e6619'
PARAMS = {"lookback_h": 168.0, "scale": 0.001}
PARAM_GRID = {"lookback_h": [84.0, 168.0, 336.0]}

def signal(view, p):
    L = int(p["lookback_h"])
    f = view.funding(L)
    if len(f) < L:
        return 0.0
    return max(-1.0, min(1.0, -float(np.sum(f)) / float(p["scale"])))
