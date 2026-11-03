"""Multi-objective selection: Pareto ranking + crowding (NSGA-II style) and novelty (QD)."""

from __future__ import annotations

import math
from typing import Any


def dominates(a: list[float], b: list[float]) -> bool:
    return all(x >= y for x, y in zip(a, b, strict=True)) and any(x > y for x, y in zip(a, b, strict=True))


def pareto_ranks(points: list[list[float]]) -> list[int]:
    n = len(points)
    ranks = [-1] * n
    remaining = set(range(n))
    r = 0
    while remaining:
        front = [i for i in remaining if not any(dominates(points[j], points[i]) for j in remaining if j != i)]
        for i in front:
            ranks[i] = r
        remaining -= set(front)
        r += 1
    return ranks


def crowding(points: list[list[float]], idx: list[int]) -> dict[int, float]:
    d = {i: 0.0 for i in idx}
    if len(idx) <= 2:
        return {i: math.inf for i in idx}
    for m in range(len(points[idx[0]])):
        s = sorted(idx, key=lambda i: points[i][m])
        lo, hi = points[s[0]][m], points[s[-1]][m]
        d[s[0]] = d[s[-1]] = math.inf
        if hi - lo <= 0:
            continue
        for k in range(1, len(s) - 1):
            d[s[k]] += (points[s[k + 1]][m] - points[s[k - 1]][m]) / (hi - lo)
    return d


def select(cands: list[dict[str, Any]], keys: list[str], k: int) -> list[dict[str, Any]]:
    pts = [[c["objectives"][key] for key in keys] for c in cands]
    ranks = pareto_ranks(pts)
    for c, r in zip(cands, ranks, strict=True):
        c["pareto_rank"] = r
    chosen: list[int] = []
    for r in sorted(set(ranks)):
        front = [i for i, x in enumerate(ranks) if x == r]
        if len(chosen) + len(front) <= k:
            chosen += front
        else:
            cd = crowding(pts, front)
            chosen += sorted(front, key=lambda i: -cd[i])[: k - len(chosen)]
            break
    return [cands[i] for i in chosen]


def novelty(behavior: list[float], archive: list[list[float]], k: int = 3) -> float:
    if not archive:
        return 1.0
    ds = sorted(math.dist(behavior, b) for b in archive)
    return sum(ds[:k]) / min(k, len(ds))
