"""Fixed-point units. All accounting is integer-exact.

price  : integer ticks, 1 tick = 0.01 USDT
qty    : integer lots,  1 lot  = 0.0001 BTC
cash   : integer micro-USDT (1e-6 USDT); notional(price, qty) = price * qty
"""

TICK_USD = 0.01
LOT_BTC = 0.0001
CASH_PER_USD = 1_000_000
LOTS_PER_BTC = 10_000


def usd_to_ticks(usd: float) -> int:
    return int(round(usd / TICK_USD))


def ticks_to_usd(ticks: float) -> float:
    return ticks * TICK_USD


def usd_to_cash(usd: float) -> int:
    return int(round(usd * CASH_PER_USD))


def cash_to_usd(cash: int | float) -> float:
    return cash / CASH_PER_USD


def btc_to_lots(btc: float) -> int:
    return int(round(btc * LOTS_PER_BTC))


def lots_to_btc(lots: int | float) -> float:
    return lots / LOTS_PER_BTC


def notional(price_ticks: int, lots: int) -> int:
    """Cash value (micro-USDT) of `lots` at `price_ticks`. Exact."""
    return price_ticks * lots


def fee_for(notional_cash: int, bps: float) -> int:
    """Fee in micro-USDT, floored so fees are always integer and deterministic."""
    return int(abs(notional_cash) * bps) // 10_000
