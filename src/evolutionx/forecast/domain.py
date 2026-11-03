"""Forecasting domains. A domain defines origins, point-in-time features, targets and outcomes.

Only `BTCDomain` exists so far; the engine (backtest, ledger, prospective mode, evolution) talks to the
`Domain` protocol, so further domains can be registered in DOMAINS without touching the engine.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .data import HOUR, Bars, load_bars

DAY = 24 * HOUR


@dataclass(frozen=True)
class Target:
    name: str  # e.g. "move3_24"
    kind: str  # "binary" | "rv"
    horizon_h: int
    threshold: float | None = None  # |log return| threshold for move targets
    direction: bool = False  # True for "up"


def btc_targets() -> list[Target]:
    out = []
    for h in (24, 72):
        out += [
            Target(f"rv_{h}", "rv", h),
            Target(f"move3_{h}", "binary", h, 0.03),
            Target(f"move5_{h}", "binary", h, 0.05),
            Target(f"up_{h}", "binary", h, None, True),
        ]
    return out


class Domain(Protocol):
    name: str
    lag_ms: int

    def targets(self) -> list[Target]: ...
    def origins(self, start: str, end: str) -> list[int]: ...
    def features(self, origin: int, as_of: int | None = None) -> dict[str, float]: ...
    def outcome(self, target: Target, origin: int) -> float | None: ...
    def outcome_time(self, target: Target, origin: int) -> int: ...


FEATURES = (
    "lrv_24",
    "lrv_72",
    "lrv_168",
    "lrv_720",
    "ret_24",
    "ret_168",
    "ret_720",
    "absret_24",
    "range_24",
    "lvol_ratio",
    "lsig_ewma",
)


class BTCDomain:
    """BTCUSDT perpetual, hourly bars on a regular grid (missing hours stay NaN; nothing is filled)."""

    name = "btc_perp"

    def __init__(self, bars: Bars | None = None, lag_ms: int = 24 * HOUR, ewma_lambda: float = 0.99) -> None:
        b = bars if bars is not None else load_bars()
        self.lag_ms = lag_ms
        self.t0 = int(b.open_time[0])
        n = int((b.open_time[-1] - self.t0) // HOUR) + 1
        idx = ((b.open_time - self.t0) // HOUR).astype(int)
        self.close = np.full(n, np.nan)
        self.high = np.full(n, np.nan)
        self.low = np.full(n, np.nan)
        self.vol = np.full(n, np.nan)
        self.close[idx], self.high[idx], self.low[idx], self.vol[idx] = b.close, b.high, b.low, b.volume
        self.bars = b
        self.r = np.r_[np.nan, np.diff(np.log(self.close))]  # r[k]: return of bar k (needs bars k-1 and k)
        r2 = np.nan_to_num(self.r**2, nan=0.0)
        # causal EWMA of squared hourly returns: ewma[k] uses r[0..k] only
        e = np.empty(n)
        acc = float(np.nanmean(self.r[1:721] ** 2))
        for k in range(n):
            if np.isfinite(self.r[k]):
                acc = ewma_lambda * acc + (1 - ewma_lambda) * r2[k]
            e[k] = acc
        self.ewma = e
        self.end_ms = self.t0 + n * HOUR  # end of last bar

    # --- time helpers -------------------------------------------------------------------------
    def _k(self, t_ms: int) -> int:
        """Number of grid bars that are complete strictly before time t (bar k covers [t0+kH, t0+(k+1)H))."""
        return int(min(len(self.close), max(0, (t_ms - self.t0) // HOUR)))

    def targets(self) -> list[Target]:
        return btc_targets()

    def origins(self, start: str, end: str) -> list[int]:
        a = int(dt.datetime.fromisoformat(start).replace(tzinfo=dt.UTC).timestamp() * 1000)
        b = int(dt.datetime.fromisoformat(end).replace(tzinfo=dt.UTC).timestamp() * 1000)
        return list(range(a, b + 1, DAY))

    # --- features (point in time) ---------------------------------------------------------------
    def features(self, origin: int, as_of: int | None = None) -> dict[str, float]:
        """Features from bars complete before `as_of` (default origin - lag). Never reads later bars."""
        e = self._k(origin - self.lag_ms if as_of is None else as_of)
        if e < 721:
            return {k: float("nan") for k in (*FEATURES, "missing_frac_720", "as_of_ms")}
        r = self.r[:e]
        c = self.close[:e]

        def lrv(nh: int) -> float:
            w = r[e - nh : e]
            ok = np.isfinite(w)
            if ok.sum() < 0.5 * nh:
                return float("nan")
            return math.log(100 * math.sqrt(float(np.sum(w[ok] ** 2)) * nh / ok.sum()) + 1e-9)

        def ret(nh: int) -> float:
            a, b = c[e - 1 - nh], c[e - 1]
            return float(math.log(b / a)) if np.isfinite(a) and np.isfinite(b) else float("nan")

        hl = (self.high[e - 24 : e] - self.low[e - 24 : e]) / c[e - 24 : e]
        v24, v720 = np.nanmean(self.vol[e - 24 : e]), np.nanmean(self.vol[e - 720 : e])
        f = {
            "lrv_24": lrv(24),
            "lrv_72": lrv(72),
            "lrv_168": lrv(168),
            "lrv_720": lrv(720),
            "ret_24": ret(24),
            "ret_168": ret(168),
            "ret_720": ret(720),
            "absret_24": abs(ret(24)),
            "range_24": float(np.nanmean(hl)),
            "lvol_ratio": float(math.log(v24 / v720)) if v24 > 0 and v720 > 0 else float("nan"),
            "lsig_ewma": 0.5 * math.log(self.ewma[e - 1]),
            "missing_frac_720": float(np.mean(~np.isfinite(self.close[e - 720 : e]))),
            "as_of_ms": float(self.t0 + e * HOUR),
        }
        return f

    def sigma_h(self, feats: dict[str, float], horizon_h: int) -> float:
        return math.exp(feats["lsig_ewma"]) * math.sqrt(horizon_h)

    # --- outcomes -------------------------------------------------------------------------------
    def outcome_time(self, target: Target, origin: int) -> int:
        return origin + target.horizon_h * HOUR

    def outcome(self, target: Target, origin: int) -> float | None:
        """Outcome over (origin, origin + h]; None if any needed bar is missing or not yet available."""
        k0 = self._k(origin) - 1  # bar ending at origin
        k1 = k0 + target.horizon_h
        if k0 < 0 or k1 >= len(self.close):
            return None
        c0, c1 = self.close[k0], self.close[k1]
        if not (np.isfinite(c0) and np.isfinite(c1)):
            return None
        lr = math.log(c1 / c0)
        if target.kind == "rv":
            w = self.r[k0 + 1 : k1 + 1]
            if not np.all(np.isfinite(w)):
                return None
            return math.log(100 * math.sqrt(float(np.sum(w**2))) + 1e-9)
        if target.direction:
            return float(lr > 0)
        assert target.threshold is not None
        return float(abs(lr) >= target.threshold)


DOMAINS = {"btc_perp": BTCDomain}
