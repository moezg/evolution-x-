"""Named stress scenarios. Each is a config transformation - nothing hardcodes an outcome.

The shock only changes an exogenous input (fundamental, external flow,
participation, funding). Whatever happens to the price afterwards emerges
from agent behaviour and the order book.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Shock, SimConfig


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    shocks: tuple[Shock, ...] = ()
    population_overrides: tuple[tuple[str, int], ...] = ()

    def apply(self, cfg: SimConfig, armed: bool = True) -> SimConfig:
        shocks = [s.model_copy(update={"armed": armed}) for s in self.shocks]
        pop = dict(cfg.population_overrides)
        if armed:
            pop.update(dict(self.population_overrides))
        return cfg.model_copy(update={"shocks": list(cfg.shocks) + shocks, "population_overrides": pop})


def _at(cfg_duration: int) -> int:
    return cfg_duration // 2


SCENARIOS: dict[str, Scenario] = {
    "baseline": Scenario("baseline", "No intervention."),
    "btc_drop_5pct": Scenario(
        "btc_drop_5pct",
        "Exogenous repricing: latent fundamental falls 5% with a public headline. Market response is emergent.",
        (Shock(type="fundamental_drop", at_s=900, magnitude=0.05, note="fundamental -5% + headline"),)),
    "flash_sell": Scenario(
        "flash_sell",
        "External participant market-sells 150 BTC over 60s (exogenous flow, recorded as external account).",
        (Shock(type="flash_sell", at_s=900, duration_s=60, magnitude=150.0),)),
    "liquidity_drought_70": Scenario(
        "liquidity_drought_70", "Market-maker quote size drops by 70% for 10 minutes.",
        (Shock(type="liquidity_drought", at_s=900, duration_s=600, magnitude=0.7),)),
    "whale_liquidation": Scenario(
        "whale_liquidation",
        "Exogenous leveraged whale builds a 250 BTC long, then its collateral is haircut and the engine force-liquidates it.",
        (Shock(type="whale_liquidation", at_s=900, magnitude=250.0),)),
    "funding_spike": Scenario(
        "funding_spike", "Funding rate forced to +0.75% per interval for 15 minutes (longs pay shorts).",
        (Shock(type="funding_spike", at_s=900, duration_s=900, magnitude=0.0075),)),
    "news_panic": Scenario(
        "news_panic", "Major negative headline (sentiment -4) with NO change in fundamentals: tests self-fulfilling panic.",
        (Shock(type="news_panic", at_s=900, magnitude=4.0),)),
    "arb_outage": Scenario(
        "arb_outage", "All cross-venue arbitrageurs offline for 10 minutes.",
        (Shock(type="arb_outage", at_s=900, duration_s=600, magnitude=1.0),)),
    "momentum_dominance": Scenario(
        "momentum_dominance", "Population mix: 120 momentum traders, value traders reduced to 8.",
        population_overrides=(("momentum", 120), ("value", 8))),
}


def scenario_at(name: str, at_s: int | None = None) -> Scenario:
    sc = SCENARIOS[name]
    if at_s is None:
        return sc
    return Scenario(sc.name, sc.description, tuple(s.model_copy(update={"at_s": at_s}) for s in sc.shocks),
                    sc.population_overrides)
