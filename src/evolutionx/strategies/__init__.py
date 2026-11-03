"""Strategy policies (EVOLVABLE zone: candidate code patches may target these files)."""

from __future__ import annotations

from . import adaptive, arbitrage, execution, leveraged, market_maker, momentum, news, noise, value, whale

POLICIES = {
    "noise": noise.decide,
    "momentum": momentum.decide,
    "value": value.decide,
    "market_maker": market_maker.decide,
    "arbitrage": arbitrage.decide,
    "execution": execution.decide,
    "whale": whale.decide,
    "leveraged": leveraged.decide,
    "news": news.decide,
    "adaptive": adaptive.decide,
}
