"""Clearing house: collateral, positions, margin, funding, bankruptcy.

Instrument model: cash-settled linear perpetual per venue. Every account starts
flat, so for each venue the sum of positions is exactly zero (every fill has a
buyer and a seller). Cash moves only through:

  * trade settlement (buyer pays seller exactly price*qty),
  * fees (account -> venue fee pool),
  * funding (longs <-> shorts, rounding residual -> insurance fund),
  * bankruptcy cover (insurance fund -> bankrupt account),
  * explicitly recorded external flows (deposits for exogenous participants).

Conservation invariant (checked continuously in tests and at run end):
  sum(account cash) + fee_pool + insurance_fund == initial_cash + external_inflows
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .units import fee_for, notional


@dataclass(slots=True)
class Account:
    agent: int
    cash: int  # micro-USDT collateral (can go negative only transiently before bankruptcy cover)
    max_leverage: float
    positions: list[int] = field(default_factory=list)  # lots per venue
    open_buy: list[int] = field(default_factory=list)  # resting buy lots per venue
    open_sell: list[int] = field(default_factory=list)
    fees_paid: int = 0
    funding_paid: int = 0
    liquidations: int = 0
    bankrupt_cover: int = 0
    liquidating: bool = False

    def equity(self, marks: list[int]) -> int:
        return self.cash + sum(p * m for p, m in zip(self.positions, marks, strict=True))

    def gross_notional(self, marks: list[int]) -> int:
        return sum(abs(p) * m for p, m in zip(self.positions, marks, strict=True))


class ClearingHouse:
    def __init__(self, n_venues: int, maker_fee_bps: float, taker_fee_bps: float, maintenance_margin: float) -> None:
        self.n_venues = n_venues
        self.maker_fee_bps = maker_fee_bps
        self.taker_fee_bps = taker_fee_bps
        self.maintenance_margin = maintenance_margin
        self.accounts: dict[int, Account] = {}
        self.fee_pool = 0
        self.insurance_fund = 0
        self.initial_cash = 0
        self.external_inflows = 0

    # --- account lifecycle ---------------------------------------------------
    def open_account(self, agent: int, cash: int, max_leverage: float, external: bool = False) -> Account:
        if agent in self.accounts:
            raise ValueError(f"account {agent} exists")
        acct = Account(agent, cash, max_leverage, [0] * self.n_venues, [0] * self.n_venues, [0] * self.n_venues)
        self.accounts[agent] = acct
        if external:
            self.external_inflows += cash
        else:
            self.initial_cash += cash
        return acct

    # --- pre-trade risk ------------------------------------------------------
    def can_take(self, agent: int, venue: int, side: int, qty: int, price: int, marks: list[int]) -> bool:
        """Initial-margin check assuming the order and all same-side resting orders fill."""
        a = self.accounts[agent]
        eq = a.equity(marks)
        if eq <= 0:
            return False
        gross = 0
        for v in range(self.n_venues):
            pos = a.positions[v]
            worst_long = pos + a.open_buy[v]
            worst_short = pos - a.open_sell[v]
            if v == venue:
                if side > 0:
                    worst_long += qty
                else:
                    worst_short -= qty
            m = marks[v] if v != venue else max(marks[v], price)
            gross += max(abs(worst_long), abs(worst_short)) * m
        # reducing orders are always allowed
        pos = a.positions[venue]
        if (side > 0 and pos < 0 and qty <= -pos) or (side < 0 and pos > 0 and qty <= pos):
            return True
        return gross <= eq * a.max_leverage

    # --- settlement ----------------------------------------------------------
    def settle_fill(
        self, venue: int, price: int, qty: int, buyer: int, seller: int, aggressor_side: int
    ) -> tuple[int, int]:
        cash = notional(price, qty)
        b, s = self.accounts[buyer], self.accounts[seller]
        b.cash -= cash
        s.cash += cash
        b.positions[venue] += qty
        s.positions[venue] -= qty
        bfee = fee_for(cash, self.taker_fee_bps if aggressor_side > 0 else self.maker_fee_bps)
        sfee = fee_for(cash, self.taker_fee_bps if aggressor_side < 0 else self.maker_fee_bps)
        b.cash -= bfee
        s.cash -= sfee
        b.fees_paid += bfee
        s.fees_paid += sfee
        self.fee_pool += bfee + sfee
        return bfee, sfee

    def apply_funding(self, venue: int, rate: float, mark: int) -> int:
        """Longs pay shorts `rate * notional` (negative rate reverses). Returns residual to insurance."""
        total = 0
        for a in self.accounts.values():
            pos = a.positions[venue]
            if pos:
                pay = int(pos * mark * rate)  # truncation toward zero, deterministic
                a.cash -= pay
                a.funding_paid += pay
                total += pay
        # payments sum to ~0 because positions sum to 0; keep cash exactly conserved
        self.insurance_fund += total
        return total

    def cover_bankruptcy(self, agent: int) -> int:
        a = self.accounts[agent]
        if a.cash >= 0 or any(a.positions):
            return 0
        deficit = -a.cash
        a.cash = 0
        a.bankrupt_cover += deficit
        self.insurance_fund -= deficit
        return deficit

    def needs_liquidation(self, agent: int, marks: list[int]) -> bool:
        a = self.accounts[agent]
        if not any(a.positions):
            return False
        return a.equity(marks) < self.maintenance_margin * a.gross_notional(marks)

    # --- invariants ----------------------------------------------------------
    def total_cash(self) -> int:
        return sum(a.cash for a in self.accounts.values()) + self.fee_pool + self.insurance_fund

    def check_invariants(self) -> None:
        expected = self.initial_cash + self.external_inflows
        actual = self.total_cash()
        assert actual == expected, f"cash not conserved: {actual} != {expected} (diff {actual - expected})"
        for v in range(self.n_venues):
            net = sum(a.positions[v] for a in self.accounts.values())
            assert net == 0, f"venue {v} net position {net} != 0"
            for a in self.accounts.values():
                assert a.open_buy[v] >= 0 and a.open_sell[v] >= 0, f"negative open qty for {a.agent}"
