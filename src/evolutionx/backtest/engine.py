"""Causal execution engine for 1h perpetual-futures bars (trusted).

Timing: the decision computed from bar t (available at its close) is executed
at the OPEN of bar t+1 — never at the close of bar t. Fill price includes half
the spread and a square-root impact term. Fills are capped at a participation
limit of the execution bar's volume (partial fills; the remainder is retried at
the next bar). Funding is charged on the position held at each funding time.
Liquidation is checked against the adverse intrabar extreme (worst case,
because the intrabar path is unknown with OHLCV data); queue position and
intrabar liquidity are NOT modelled.

Accounting identity (verified at the end of every run):
  equity_T = equity_0 + gross_pnl - fees - spread_costs - impact_costs - funding - liquidation_fees
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class CostModel:
    taker_fee_bps: float = 5.0
    spread_bps: float = 1.0
    impact_coef_bps: float = 10.0  # impact_bps = coef * sqrt(fill_qty / bar_volume)
    participation_limit: float = 0.02
    max_leverage: float = 2.0
    maintenance_margin: float = 0.005
    liquidation_fee_bps: float = 50.0
    lot_step: float = 0.001
    cost_multiplier: float = 1.0  # sensitivity analysis: scales fee, spread and impact
    rebalance_band: float = 0.05  # skip trades smaller than this fraction of max-leverage equity

    @classmethod
    def from_protocol(cls, proto: dict[str, Any], symbol: str, cost_multiplier: float = 1.0) -> CostModel:
        ex = proto["execution"]
        inst = next(i for i in proto["instruments"] if i["symbol"] == symbol)
        return cls(
            ex["taker_fee_bps"],
            inst["spread_bps"],
            ex["impact_coef_bps"],
            ex["participation_limit"],
            ex["max_leverage"],
            ex["maintenance_margin"],
            ex["liquidation_fee_bps"],
            inst["lot_step"],
            cost_multiplier,
            ex.get("rebalance_band", 0.0),
        )


@dataclass
class BacktestResult:
    equity: np.ndarray  # marked at each bar close
    position: np.ndarray  # base units held at each bar close
    cum_cost: np.ndarray  # cumulative costs (fees+spread+impact+funding+liquidation) at each bar close
    gross_pnl: float
    costs: dict[str, float]
    n_fills: int
    n_liquidations: int
    traded_notional: float
    unfilled_qty: float
    open_time: np.ndarray
    events: list[dict[str, Any]] = field(default_factory=list)
    fill_notional: np.ndarray = field(default_factory=lambda: np.zeros(0))  # traded notional per bar (instrumentation)


class InvalidDecisions(ValueError):
    pass


def validate_decisions(dec: np.ndarray, n: int) -> np.ndarray:
    d = np.asarray(dec, dtype=float)
    if d.shape != (n,):
        raise InvalidDecisions(f"decision shape {d.shape} != ({n},)")
    if not np.all(np.isfinite(d)):
        raise InvalidDecisions("non-finite decisions")
    if np.any(np.abs(d) > 1.0 + 1e-9):
        raise InvalidDecisions("decisions outside [-1, 1]")
    return d


def run_backtest(
    data: dict[str, np.ndarray], decisions: np.ndarray, cost: CostModel, equity0: float = 1_000_000.0, start: int = 0
) -> BacktestResult:
    o, h, lo, c, v, f = (data[k] for k in ("open", "high", "low", "close", "volume", "funding"))
    t_open = data["open_time"]
    n = len(c)
    dec = validate_decisions(decisions, n)
    m = cost.cost_multiplier
    cash = equity0
    pos = 0.0
    eq = np.full(n, equity0)
    posa = np.zeros(n)
    cumc = np.zeros(n)
    fill_notional = np.zeros(n)
    gross = 0.0
    costs = {"fees": 0.0, "spread": 0.0, "impact": 0.0, "funding": 0.0, "liquidation": 0.0}
    n_fills = n_liq = 0
    traded = unfilled = 0.0
    events: list[dict[str, Any]] = []
    entry_mark = c[start] if start < n else 0.0
    last_mark = None
    for t in range(start, n):
        # 1) execute the decision of bar t-1 at this bar's open (only if bars are contiguous)
        contiguous = t > start and t_open[t] - t_open[t - 1] == 3_600_000
        if contiguous:
            px = o[t]
            # mark-to-market from previous close to this open (gap risk)
            gross += pos * (px - c[t - 1])
            cash += pos * (px - c[t - 1])
            equity_now = cash  # cash here is "equity including unrealised up to px" (pos marked at px)
            target_notional = dec[t - 1] * cost.max_leverage * max(equity_now, 0.0)
            target_qty = math.floor(abs(target_notional / px) / cost.lot_step) * cost.lot_step
            target_qty = math.copysign(target_qty, target_notional)
            delta = target_qty - pos
            moving_to_flat = target_qty == 0.0 and pos != 0.0
            if not moving_to_flat and abs(delta) * px < cost.rebalance_band * cost.max_leverage * max(equity_now, 0.0):
                delta = 0.0
            cap = cost.participation_limit * v[t]
            qty = math.copysign(min(abs(delta), cap), delta)
            qty = math.copysign(math.floor(abs(qty) / cost.lot_step) * cost.lot_step, qty)
            unfilled += abs(delta) - abs(qty)
            if qty != 0.0:
                notional = abs(qty) * px
                impact_bps = cost.impact_coef_bps * math.sqrt(abs(qty) / max(v[t], 1e-12))
                spread_c = notional * (cost.spread_bps / 2) / 1e4 * m
                impact_c = notional * impact_bps / 1e4 * m
                fee = notional * cost.taker_fee_bps / 1e4 * m
                cash -= spread_c + impact_c + fee
                costs["spread"] += spread_c
                costs["impact"] += impact_c
                costs["fees"] += fee
                pos += qty
                traded += notional
                fill_notional[t] += notional
                n_fills += 1
            last_mark = px
        elif t > start and last_mark is not None:
            # gap: position carried, marked at next available open; no trading possible during the gap
            px = o[t]
            gross += pos * (px - c[t - 1])
            cash += pos * (px - c[t - 1])
            events.append({"t": int(t_open[t]), "type": "gap", "from": int(t_open[t - 1])})
            last_mark = px
        else:
            last_mark = o[t]
        # 2) intrabar liquidation check at the adverse extreme (worst case)
        ref = o[t] if t > start else entry_mark
        if pos != 0.0:
            adverse = lo[t] if pos > 0 else h[t]
            eq_adv = cash + pos * (adverse - ref)
            if eq_adv < cost.maintenance_margin * abs(pos) * adverse:
                mm = cost.maintenance_margin
                # price at which equity == maintenance requirement (continuous path from the open)
                if pos > 0:
                    liq_px = (pos * ref - cash) / (pos * (1 - mm))
                    fill = min(liq_px, ref)  # if the open is already beyond the level, fill at the open
                else:
                    liq_px = (pos * ref - cash) / (pos * (1 + mm))
                    fill = max(liq_px, ref)
                pnl = pos * (fill - ref)
                gross += pnl
                cash += pnl
                lf = abs(pos) * fill * cost.liquidation_fee_bps / 1e4
                cash -= lf
                costs["liquidation"] += lf
                events.append({"t": int(t_open[t]), "type": "liquidation", "qty": pos, "price": fill})
                traded += abs(pos) * fill
                pos = 0.0
                n_liq += 1
                eq[t] = cash
                posa[t] = 0.0
                cumc[t] = sum(costs.values())
                continue
        # 3) mark to close and charge funding on the position held at the close boundary
        gross += pos * (c[t] - ref)
        cash += pos * (c[t] - ref)
        if pos != 0.0 and f[t] != 0.0:
            fund = pos * c[t] * f[t]  # longs pay positive funding
            cash -= fund
            costs["funding"] += fund
        eq[t] = cash
        posa[t] = pos
        cumc[t] = sum(costs.values())
    res = BacktestResult(eq, posa, cumc, gross, costs, n_fills, n_liq, traded, unfilled, t_open, events, fill_notional)
    check_accounting(res, equity0)
    return res


def check_accounting(r: BacktestResult, equity0: float) -> None:
    expected = equity0 + r.gross_pnl - sum(r.costs.values())
    final = r.equity[-1]
    if not math.isclose(final, expected, rel_tol=1e-9, abs_tol=1e-4):
        raise AssertionError(f"accounting identity violated: {final} != {expected}")
