"""Genome operators over bounded strategy parameters (Level 2 strategy evolution)."""

from __future__ import annotations

import hashlib
import json
import math
import random

from ..strategies.params import PARAM_SPECS, clip_params, defaults


def genome_id(family: str, genome: dict[str, float]) -> str:
    blob = json.dumps({"f": family, "g": {k: round(v, 6) for k, v in sorted(genome.items())}}, sort_keys=True)
    return f"{family[:3]}-{hashlib.sha256(blob.encode()).hexdigest()[:10]}"


def mutate(
    family: str, genome: dict[str, float], rng: random.Random, sigma: float = 0.25, p_gene: float = 0.5
) -> dict[str, float]:
    """Log-normal multiplicative mutation for positive params, additive for [0,1] params; clipped."""
    out = dict(genome)
    for k, (_d, lo, hi) in PARAM_SPECS[family].items():
        if rng.random() > p_gene:
            continue
        v = out[k]
        if lo >= 0 and hi <= 1:
            out[k] = v + rng.gauss(0, sigma * 0.5)
        elif v > 0:
            out[k] = v * math.exp(rng.gauss(0, sigma))
        else:
            out[k] = v + rng.gauss(0, sigma * (hi - lo) * 0.1)
    return clip_params(family, out)


def crossover(family: str, a: dict[str, float], b: dict[str, float], rng: random.Random) -> dict[str, float]:
    return clip_params(family, {k: (a[k] if rng.random() < 0.5 else b[k]) for k in PARAM_SPECS[family]})


def seed_genome(family: str) -> dict[str, float]:
    return defaults(family)


def normalized(family: str, genome: dict[str, float]) -> list[float]:
    return [(genome[k] - lo) / (hi - lo) if hi > lo else 0.0 for k, (_d, lo, hi) in PARAM_SPECS[family].items()]
