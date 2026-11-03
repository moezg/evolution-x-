"""Controlled synthetic data sources (for mechanism tests ONLY; never reported as market evidence).

`TrendData` plants a known, persistent momentum effect so that a trend strategy has a real edge; this lets tests
verify that the promotion machinery promotes a genuinely better candidate. `canary()` builds edge-case bars
(constant prices, spikes, zero volume) used by the post-activation technical check.
"""

from __future__ import annotations

import numpy as np

H = 3_600_000


def bars(returns: np.ndarray, t0: int = 1_577_836_800_000, p0: float = 100.0, vol_level: float = 1e6) -> dict:
    c = p0 * np.exp(np.cumsum(returns))
    o = np.r_[p0, c[:-1]]
    hi = np.maximum(o, c) * 1.001
    lo = np.minimum(o, c) * 0.999
    t = t0 + np.arange(len(c), dtype=np.int64) * H
    return {
        "open_time": t,
        "open": o,
        "high": hi,
        "low": lo,
        "close": c,
        "volume": np.full(len(c), vol_level),
        "available_at": t + H,
        "funding": np.zeros(len(c)),
    }


class TrendData:
    def __init__(
        self,
        symbols: tuple[str, ...] = ("SYN1", "SYN2"),
        n_dev: int = 6000,
        n_val: int = 3000,
        phi: float = 0.3,
        seed: int = 0,
    ) -> None:
        self.symbols = list(symbols)
        self._d: dict[tuple[str, str], dict] = {}
        for j, s in enumerate(symbols):
            rng = np.random.default_rng(seed + j)
            n = n_dev + n_val
            eps = rng.normal(0, 0.004, n)
            r = np.zeros(n)
            for t in range(n):
                r[t] = phi * r[max(0, t - 24) : t].mean() * 24 / 24 + eps[t] if t else eps[t]
            full = bars(r)
            self._d[(s, "development")] = {k: v[:n_dev] for k, v in full.items()}
            self._d[(s, "validation")] = {k: v[n_dev:] for k, v in full.items()}

    def get(self, symbol: str, split: str) -> dict:
        return self._d[(symbol, split)]


def canary(n: int = 1500) -> dict:
    r = np.zeros(n)
    r[300:310] = 0.15  # violent spike
    r[600:610] = -0.2
    d = bars(r)
    d["volume"][900:1000] = 0.0  # no liquidity
    return d


def synthetic_protocol(base: dict, symbols: list[str]) -> dict:
    import copy

    p = copy.deepcopy(base)
    p["instruments"] = [
        {"symbol": s, "market": "synthetic", "resolution": "1h", "lot_step": 0.001, "spread_bps": 1.0} for s in symbols
    ]
    p["walk_forward"] = {"train_months": 3, "test_months": 1, "step_months": 1, "embargo_bars": 24}
    return p
