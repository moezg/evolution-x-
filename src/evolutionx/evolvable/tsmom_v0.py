"""Initial champion (v0): volatility-normalised time-series momentum on 1h perpetual bars.

Rendered from the generator grammar so that every child differs from it by exactly one operator.
Frozen baseline that the evolutionary process must beat."""

from __future__ import annotations

import math

import numpy as np

NAME = "tsmom_v0"
PARAMS = {"lookback": 168}
PARAM_GRID = {"lookback": [72, 168, 336]}
SPEC = {"filters": [], "grid": {"lookback": [72, 168, 336]}, "signal": {"kind": "tsmom", "lookback": 168}}


def _raw(view, p):
    n = int(p["lookback"])
    c = view.close(n + 1)
    if len(c) <= n:
        return 0.0
    r = math.log(c[-1] / c[0])
    vol = float(np.std(np.diff(np.log(c)))) * math.sqrt(n) + 1e-12
    return max(-1.0, min(1.0, r / vol))


def signal(view, p):
    x = _raw(view, p)
    return max(-1.0, min(1.0, x))
