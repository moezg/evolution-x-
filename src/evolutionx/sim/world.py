"""Exogenous world: latent fundamental value and news arrivals.

The fundamental is HIDDEN state. Agents only see it through private noisy,
delayed signals (value/whale traders) or through public news headlines.
It never sets the traded price; prices emerge from the order book (Mode A).
In Mode B (historical replay) the fundamental path is replaced by the recorded
historical series, which is kept unmodified and labelled as historical.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class News:
    t: int
    sentiment: float  # roughly N(0,1); |s| > 2 is a major headline
    headline: str
    source: str = "synthetic"  # "synthetic" | "scenario"


class World:
    def __init__(self, seed: int, initial_value: float, annual_vol: float = 0.6,
                 news_rate_per_hour: float = 6.0, news_impact: float = 0.004) -> None:
        self.rng = random.Random(f"world:{seed}")
        self.value = initial_value
        self.sigma_per_s = annual_vol / math.sqrt(365 * 24 * 3600)
        self.news_rate_per_s = news_rate_per_hour / 3600.0
        self.news_impact = news_impact
        self.history: list[tuple[int, float]] = []  # (t, value)
        self.news: list[News] = []
        self.replay: list[tuple[int, float]] | None = None  # Mode B path
        self._replay_i = 0

    def step(self, t: int) -> News | None:
        """Advance one second."""
        news = None
        if self.replay is not None:
            while self._replay_i + 1 < len(self.replay) and self.replay[self._replay_i + 1][0] <= t:
                self._replay_i += 1
            self.value = self.replay[self._replay_i][1]
        else:
            self.value *= math.exp(self.sigma_per_s * self.rng.gauss(0, 1) - 0.5 * self.sigma_per_s**2)
        if self.rng.random() < self.news_rate_per_s:
            s = self.rng.gauss(0, 1)
            if self.replay is None:
                self.value *= math.exp(self.news_impact * s)
            news = News(t, s, f"{'positive' if s > 0 else 'negative'} macro headline ({s:+.2f})")
            self.news.append(news)
        self.history.append((t, self.value))
        return news

    def shock(self, t: int, pct: float, headline: str, sentiment: float) -> News:
        self.value *= 1 + pct
        n = News(t, sentiment, headline, source="scenario")
        self.news.append(n)
        return n

    def value_as_of(self, t: int) -> float:
        # history is appended once per second in order; index by second
        if not self.history:
            return self.value
        i = min(len(self.history) - 1, max(0, t // 1000))
        while i > 0 and self.history[i][0] > t:
            i -= 1
        return self.history[i][1]
