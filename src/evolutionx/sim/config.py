"""Validated simulation configuration (Pydantic v2)."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ShockType = Literal["fundamental_drop", "flash_sell", "liquidity_drought", "whale_liquidation",
                    "funding_spike", "news_panic", "arb_outage"]


class Shock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: ShockType
    at_s: int = Field(ge=0)
    duration_s: int = Field(default=300, ge=0)
    magnitude: float
    armed: bool = True  # disarmed = setup only (used for paired baselines)
    note: str = ""


class SimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int = 42
    duration_s: int = Field(default=1800, ge=10, le=7 * 24 * 3600)
    mode: Literal["synthetic", "replay"] = "synthetic"
    scale: float = Field(default=1.0, gt=0, le=50)
    population_overrides: dict[str, int] = Field(default_factory=dict)
    param_overrides: dict[str, dict[str, float]] = Field(default_factory=dict)
    heterogeneity: float = Field(default=0.3, ge=0, le=1)
    initial_price_usd: float = 60_000.0
    n_venues: int = Field(default=2, ge=1, le=4)
    maker_fee_bps: float = 1.0
    taker_fee_bps: float = 5.0
    maintenance_margin: float = 0.02
    funding_interval_s: int = 300
    funding_k: float = 0.1
    funding_cap: float = 0.0075
    circuit_breaker_pct: float = 0.10
    world_annual_vol: float = 0.6
    news_rate_per_hour: float = 6.0
    news_impact: float = 0.004
    social_enabled: bool = True
    social_k: int = 6
    social_rewire_p: float = 0.1
    imitation_enabled: bool = True
    imitation_interval_s: int = 300
    imitation_prob: float = 0.2
    shocks: list[Shock] = Field(default_factory=list)
    replay_dataset: str | None = None  # path to historical parquet/csv for Mode B
    invariant_check_every_s: int = 60

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:16]
