"""Development-only behaviour diagnostics (TRUSTED), single source for the evaluator, premise checks and dossier.

Full-period backtests can be dominated by an early ruin (e.g. ETHUSDT v0 is liquidated on 2020-03-13 at 2x
leverage and stays at zero equity), which makes every later statistic meaningless. Diagnostics are therefore
computed on calendar-year segments, each starting with fresh equity, and pooled; ruined segments are reported.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np

from ..backtest.engine import CostModel, run_backtest
from ..backtest.metrics import daily_returns, max_drawdown, sharpe

VERSION = "behaviour-v2-yearly-segments"


def yearly_segments(open_time: np.ndarray) -> list[tuple[int, int, int]]:
    years = np.array([dt.datetime.fromtimestamp(t / 1000, dt.UTC).year for t in open_time[::24]])
    idx = np.arange(0, len(open_time), 24)
    out = []
    for y in sorted(set(years.tolist())):
        sel = idx[years == y]
        a, b = int(sel[0]), int(min(len(open_time), sel[-1] + 24))
        if b - a > 24 * 30:
            out.append((y, a, b))
    return out


def behaviour(data: dict[str, np.ndarray], dec: np.ndarray, cost: CostModel) -> dict[str, Any]:
    segs = yearly_segments(data["open_time"])
    rets, gross_rets, per_year = [], [], {}
    tot = {"fees": 0.0, "spread": 0.0, "impact": 0.0, "funding": 0.0, "liquidation": 0.0}
    gross_abs = traded = fills = bars = 0.0
    small = small_exec = changed = 0
    hold, lv_hv = [], ([], [])
    mdd = 0.0
    ruined = []
    for y, a, b in segs:
        seg = {k: v[a:b] for k, v in data.items()}
        d = dec[a:b]
        r = run_backtest(seg, d, cost)
        days, rr = daily_returns(r.equity, r.open_time)
        geq = r.equity + r.cum_cost
        _, rg = daily_returns(geq, r.open_time)
        rets.append(rr)
        gross_rets.append(rg)
        for k in tot:
            tot[k] += r.costs[k]
        gross_abs += abs(r.gross_pnl)
        traded += r.traded_notional / max(np.mean(r.equity), 1e-9)
        fills += r.n_fills
        bars += b - a
        dd = np.abs(np.diff(d))
        ch = dd > 1e-12
        sm = ch & (dd < cost.rebalance_band)
        changed += int(ch.sum())
        small += int(sm.sum())
        small_exec += int((r.fill_notional[1:] > 0)[sm].sum())
        sgn = np.sign(r.position)
        cuts = np.flatnonzero(np.diff(sgn) != 0)
        runs = np.diff(np.r_[0, cuts + 1, len(sgn)])
        hold += list(runs[sgn[np.r_[0, cuts + 1]] != 0])
        m = max_drawdown(r.equity)
        mdd = max(mdd, m)
        if r.equity.min() < 0.05 * r.equity[0]:
            ruined.append(y)
        # volatility-tercile split on this segment's daily closes (trailing 30d vol, no look-ahead)
        c = seg["close"][np.r_[np.where(np.diff(seg["open_time"] // 86_400_000) != 0)[0], len(seg["close"]) - 1]][1:]
        lr = np.diff(np.log(np.r_[seg["close"][0], c]))
        vol = np.array([np.std(lr[max(0, i - 30) : i]) if i > 5 else np.nan for i in range(len(lr))])
        n = min(len(vol), len(rr))
        lv_hv[0].append((vol[:n], rr[:n]))
        per_year[str(y)] = {"net_sharpe": sharpe(rr), "max_drawdown": m, "liquidations": r.n_liquidations}
    allr, allg = np.concatenate(rets), np.concatenate(gross_rets)
    vols = np.concatenate([v for v, _ in lv_hv[0]])
    rs = np.concatenate([r for _, r in lv_hv[0]])
    ok = np.isfinite(vols)
    lo_q, hi_q = np.nanquantile(vols, [1 / 3, 2 / 3]) if ok.any() else (0, 0)
    years = len(segs)
    return {
        "method": VERSION,
        "segments": [y for y, _, _ in segs],
        "ruined_segments": ruined,
        "net_sharpe": sharpe(allr),
        "gross_sharpe": sharpe(allg),
        "max_drawdown": mdd,
        "turnover_per_year": traded / max(years, 1),
        "avg_holding_bars": float(np.mean(hold)) if hold else 0.0,
        "trading_cost_share": (tot["fees"] + tot["spread"] + tot["impact"]) / (gross_abs + 1e-9),
        "funding_cost_share": tot["funding"] / (gross_abs + 1e-9),
        "exposure_frac": float(np.mean(np.abs(dec) > 1e-12)),
        "mean_abs_exposure": float(np.mean(np.abs(dec))),
        "decision_change_rate": changed / max(len(dec) - 1, 1),
        "small_change_rate": small / max(len(dec) - 1, 1),
        "small_change_execution_ratio": small_exec / small if small else 0.0,
        "fills_per_day": fills / max(bars / 24, 1),
        "sharpe_low_vol_tercile": sharpe(rs[ok & (vols <= lo_q)]),
        "sharpe_high_vol_tercile": sharpe(rs[ok & (vols >= hi_q)]),
        "per_year": per_year,
    }
