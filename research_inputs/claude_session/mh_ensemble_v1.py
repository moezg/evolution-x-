"""Multi-horizon trend ensemble (written in a human-driven Claude Code session, not by the lab's own generator).

Change versus parent v0: instead of one volatility-normalised trend horizon chosen per window, average the
normalised trend signal over several horizons (24h ... up to max_h). Nothing else changes.
"""

from __future__ import annotations

import math

import numpy as np

NAME = "claude_session_mh_ensemble_v1"
PARAMS = {"max_h": 720}
PARAM_GRID = {"max_h": [336, 720]}
HORIZONS = (24, 72, 168, 336, 720)


def _norm_trend(lr, h):
    seg = lr[-h:]
    vol = float(np.std(seg)) * math.sqrt(h) + 1e-12
    return max(-1.0, min(1.0, float(np.sum(seg)) / vol))


def signal(view, p):
    hs = [h for h in HORIZONS if h <= int(p["max_h"])]
    c = view.close(max(hs) + 1)
    if len(c) <= max(hs):
        return 0.0
    lr = np.diff(np.log(c))
    x = sum(_norm_trend(lr, h) for h in hs) / len(hs)
    return max(-1.0, min(1.0, x))
