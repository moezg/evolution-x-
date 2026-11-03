"""Strategy contract shared by historical backtests.

A strategy maps the information available at a bar close to a TARGET EXPOSURE
in [-1, 1] (fraction of the maximum allowed leverage). It never sees the
engine, accounts or future bars: `BarView` only returns COPIES of trailing
windows ending at the current, already-closed bar (no `.base` back-reference
to the full array).

Observation differences vs the synthetic simulator: here the strategy sees
closed OHLCV bars and realised funding only (no order book, no other agents);
execution is modelled by the trusted engine, not by matching.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


class LookaheadError(RuntimeError):
    pass


class BarView:
    __slots__ = ("_d", "_t")

    def __init__(self, data: dict[str, np.ndarray], t: int) -> None:
        self._d = data
        self._t = t  # index of the last CLOSED bar

    def __len__(self) -> int:
        return self._t + 1

    @property
    def t(self) -> int:
        return self._t

    def _win(self, key: str, n: int) -> np.ndarray:
        if n <= 0:
            raise ValueError("window must be positive")
        lo = max(0, self._t + 1 - n)
        return np.array(self._d[key][lo : self._t + 1], copy=True)

    def close(self, n: int = 1) -> np.ndarray:
        return self._win("close", n)

    def open(self, n: int = 1) -> np.ndarray:
        return self._win("open", n)

    def high(self, n: int = 1) -> np.ndarray:
        return self._win("high", n)

    def low(self, n: int = 1) -> np.ndarray:
        return self._win("low", n)

    def volume(self, n: int = 1) -> np.ndarray:
        return self._win("volume", n)

    def funding(self, n: int = 1) -> np.ndarray:
        return self._win("funding", n)

    def time_ms(self) -> int:
        return int(self._d["open_time"][self._t])


class Strategy(Protocol):
    name: str
    params: dict[str, Any]

    def decide(self, view: BarView) -> float: ...


@dataclass
class FunctionStrategy:
    """Adapter for generated modules exposing `signal(view, params) -> float`."""

    name: str
    params: dict[str, Any]
    fn: Callable[[BarView, dict[str, Any]], float]

    def decide(self, view: BarView) -> float:
        return float(self.fn(view, self.params))


def load_module_strategy(module: Any, params: dict[str, Any] | None = None) -> FunctionStrategy:
    p = dict(getattr(module, "PARAMS", {}))
    if params:
        p.update(params)
    return FunctionStrategy(getattr(module, "NAME", module.__name__), p, module.signal)


def decisions_for(strategy: Strategy, data: dict[str, np.ndarray], start: int = 0) -> np.ndarray:
    """Target exposure decided at the close of each bar t (index aligned with data)."""
    n = len(data["close"])
    out = np.zeros(n)
    for t in range(start, n):
        x = strategy.decide(BarView(data, t))
        out[t] = x
    return out
