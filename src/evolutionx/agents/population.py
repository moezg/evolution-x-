"""Population construction: 256 heterogeneous, individually parameterised agents."""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..strategies.params import PARAM_SPECS, clip_params
from .base import Agent


@dataclass(frozen=True, slots=True)
class KindProfile:
    count: int
    capital_usd: float
    max_leverage: float
    wake_ms: int  # mean decision interval
    order_latency_ms: tuple[int, int]
    md_latency_ms: tuple[int, int]
    research: bool  # receives a private noisy fundamental estimate


DEFAULT_POPULATION: dict[str, KindProfile] = {
    "noise": KindProfile(64, 20_000, 3, 20_000, (80, 400), (200, 1500), False),
    "momentum": KindProfile(40, 300_000, 3, 10_000, (20, 120), (50, 500), False),
    "value": KindProfile(32, 1_000_000, 2, 15_000, (20, 150), (100, 800), True),
    "market_maker": KindProfile(24, 3_000_000, 5, 1_500, (1, 10), (1, 20), False),
    "arbitrage": KindProfile(20, 1_500_000, 5, 1_000, (1, 15), (1, 30), False),
    "execution": KindProfile(20, 8_000_000, 2, 5_000, (5, 40), (10, 100), False),
    "whale": KindProfile(16, 40_000_000, 3, 30_000, (20, 150), (50, 400), True),
    "leveraged": KindProfile(16, 20_000, 20, 8_000, (30, 200), (100, 800), False),
    "news": KindProfile(12, 400_000, 3, 3_000, (5, 60), (20, 3000), False),
    "adaptive": KindProfile(12, 500_000, 3, 10_000, (10, 100), (50, 500), False),
}


def population_counts(scale: float = 1.0, overrides: dict[str, int] | None = None) -> dict[str, int]:
    counts = {k: max(1, round(p.count * scale)) for k, p in DEFAULT_POPULATION.items()}
    if overrides:
        counts.update({k: int(v) for k, v in overrides.items()})
    return counts


def build_population(
    seed: int,
    counts: dict[str, int],
    n_venues: int,
    param_overrides: dict[str, dict[str, float]] | None = None,
    heterogeneity: float = 0.3,
) -> list[Agent]:
    """Create agents with individually jittered parameters.

    `param_overrides[kind]` replaces the family's central parameters (this is
    how evolved genomes are deployed); individual agents still jitter around it.
    """
    rng = random.Random(f"population:{seed}")
    agents: list[Agent] = []
    aid = 0
    for kind, prof in DEFAULT_POPULATION.items():
        center = {k: v[0] for k, v in PARAM_SPECS[kind].items()}
        if param_overrides and kind in param_overrides:
            center.update(param_overrides[kind])
        for i in range(counts.get(kind, 0)):
            params = {k: v * (1 + heterogeneity * (2 * rng.random() - 1)) for k, v in center.items()}
            agents.append(
                Agent(
                    id=aid,
                    kind=kind,
                    policy_name=kind,
                    params=clip_params(kind, params),
                    rng=random.Random(f"agent:{seed}:{aid}"),
                    wake_ms=max(200, int(prof.wake_ms * (0.6 + 0.8 * rng.random()))),
                    order_latency_ms=rng.randint(*prof.order_latency_ms),
                    md_latency_ms=rng.randint(*prof.md_latency_ms),
                    home_venue=i % n_venues,
                    capital_usd=prof.capital_usd * (0.5 + rng.random()),
                    max_leverage=prof.max_leverage,
                    memory={"research": prof.research},
                )
            )
            aid += 1
    return agents
