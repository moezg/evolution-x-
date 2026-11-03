"""Information/influence network between agents (Watts-Strogatz small world)."""

from __future__ import annotations

import math
import random

from .base import Agent


class SocialNetwork:
    def __init__(self, n: int, seed: int, k: int = 6, rewire_p: float = 0.1, enabled: bool = True) -> None:
        self.enabled = enabled
        rng = random.Random(f"social:{seed}")
        nbrs: list[set[int]] = [set() for _ in range(n)]
        half = max(1, k // 2)
        for i in range(n):
            for j in range(1, half + 1):
                a, b = i, (i + j) % n
                if a != b:
                    nbrs[a].add(b)
                    nbrs[b].add(a)
        # rewire
        for i in range(n):
            for j in range(1, half + 1):
                b = (i + j) % n
                if rng.random() < rewire_p and b in nbrs[i] and n > k + 1:
                    c = rng.randrange(n)
                    while c == i or c in nbrs[i]:
                        c = rng.randrange(n)
                    nbrs[i].discard(b)
                    nbrs[b].discard(i)
                    nbrs[i].add(c)
                    nbrs[c].add(i)
        self.neighbors: list[tuple[int, ...]] = [tuple(sorted(s)) for s in nbrs]

    def signal(self, agent_id: int, agents: list[Agent]) -> float:
        if not self.enabled:
            return 0.0
        num = den = 0.0
        for j in self.neighbors[agent_id]:
            a = agents[j]
            num += a.reputation * a.stance
            den += a.reputation
        return num / den if den > 0 else 0.0

    def edges(self) -> list[tuple[int, int]]:
        return [(i, j) for i, ns in enumerate(self.neighbors) for j in ns if i < j]


def reputation_from_return(ret: float) -> float:
    """Public reputation in (0, 2) from return since start (fraction)."""
    return 1.0 + math.tanh(ret * 20)
