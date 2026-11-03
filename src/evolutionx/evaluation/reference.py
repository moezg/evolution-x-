"""Historical reference statistics (train split only) for realism scoring."""

from __future__ import annotations

from functools import lru_cache

from ..data.historical import load_split
from .stylized import bands_from_reference, facts_from_series


def window_facts(split: str, window_min: int = 60) -> list[dict[str, float]]:
    out = []
    for day in load_split(split):
        for i in range(0, len(day) - window_min + 1, window_min):
            w = day[i : i + window_min]
            f = facts_from_series(w[:, 4], w[:, 5])
            if f:
                out.append(f)
    return out


@lru_cache(maxsize=4)
def historical_bands(window_min: int = 60) -> dict[str, tuple[float, float]] | None:
    """Empirical 5-95% style bands from TRAIN windows; None if no data downloaded (falls back to literature)."""
    facts = window_facts("train", window_min)
    if len(facts) < 10:
        return None
    return bands_from_reference(facts)
