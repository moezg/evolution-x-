"""Who supplies resting liquidity? Depth near the mid by owner population (explains shock (in)sensitivity)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ..sim.config import SimConfig
from ..sim.scenarios import scenario_at
from ..sim.simulation import Simulation


def depth_by_kind(sim: Simulation, bps: float = 20.0) -> dict[str, float]:
    out: dict[str, float] = {}
    kinds = {a.id: a.kind for a in sim.agents}
    for v in sim.exchange.venues:
        mid = v.mid()
        if mid is None:
            continue
        for o in v.book.orders.values():
            if abs(o.price - mid) / mid * 1e4 <= bps:
                k = kinds.get(o.agent, "external")
                out[k] = out.get(k, 0.0) + o.qty / 1e4
    return out


def liquidity_study(seeds: tuple[int, ...] = (1, 2, 3), duration_s: int = 1800) -> dict[str, Any]:
    res: dict[str, Any] = {}
    for name in ("baseline", "liquidity_drought_70"):
        shares: dict[str, list[float]] = {}
        for seed in seeds:
            sim = Simulation(scenario_at(name, 600).apply(SimConfig(seed=seed, duration_s=duration_s)))
            samples = []
            for t in range(630, 1200, 30):  # sample strictly inside the shock window (600-1200s)
                sim.run_until(t * 1000)
                samples.append(depth_by_kind(sim))
            tot = {k: float(np.mean([s.get(k, 0.0) for s in samples])) for k in set().union(*samples)}
            z = sum(tot.values()) or 1.0
            for k, v in tot.items():
                shares.setdefault(k, []).append(v / z)
            shares.setdefault("_total_btc", []).append(z)
        res[name] = {
            k: {"mean": float(np.mean(v)), "min": float(np.min(v)), "max": float(np.max(v))}
            for k, v in sorted(shares.items())
        }
    out = Path("artifacts/analysis")
    out.mkdir(parents=True, exist_ok=True)
    (out / "liquidity_supply.json").write_text(json.dumps(res, indent=2))
    return res
