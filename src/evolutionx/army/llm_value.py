"""A9 / llm_value_protocol_v1: paired LLM-vs-template measurement on every usable LLM formulation.

Primary endpoint: Sharpe (cost 1x) on ETH development data (outside the LLM's context) of the LLM parameters minus
the template defaults, same family. Recorded per pair in army_llm_ab; analysed after >= 15 pairs. No extra LLM calls.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np

from . import mechanisms as M
from .store import Store

POLICY = Path("evals/frozen/llm_value_protocol_v1.json")
SCHEMA = """CREATE TABLE IF NOT EXISTS army_llm_ab (hypothesis_id TEXT PRIMARY KEY, cycle_id TEXT, role TEXT, family TEXT,
  llm_params TEXT, default_params TEXT, eth_dev_sharpe_llm REAL, eth_dev_sharpe_default REAL, btc_dev_sharpe_llm REAL,
  btc_dev_sharpe_default REAL, created TEXT);"""


def dev_sharpe(symbol: str, family: str, params: dict[str, float], years: int = 4) -> float:
    from ..backtest.interface import decisions_for, load_module_strategy
    from ..data.datasets import load_split
    from .adversarial import _sharpe, load_module

    full = load_split(symbol, "development")
    n = min(len(full["close"]), years * 8760)
    data = {k: v[-n:] for k, v in full.items()}
    src = M.render(family, "ab", params, "llm-value A/B")
    dec = decisions_for(load_module_strategy(load_module(src), params), data)
    return _sharpe(data, dec, 1.0)


def record(store: Store, cycle: str, role: str, hid: str, family: str, llm_params: dict[str, Any]) -> dict[str, Any]:
    with store.mem._c() as c:
        c.executescript(SCHEMA)
    lp, dp = M.clamp_params(family, llm_params), M.clamp_params(family, {})
    row = {
        "eth_l": dev_sharpe("ETHUSDT", family, lp), "eth_d": dev_sharpe("ETHUSDT", family, dp),
        "btc_l": dev_sharpe("BTCUSDT", family, lp), "btc_d": dev_sharpe("BTCUSDT", family, dp),
    }  # fmt: skip
    store.x(
        "INSERT OR REPLACE INTO army_llm_ab VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (hid, cycle, role, family, json.dumps(lp), json.dumps(dp), row["eth_l"], row["eth_d"], row["btc_l"], row["btc_d"], dt.datetime.now(dt.UTC).isoformat(timespec="seconds")),
    )  # fmt: skip
    return row


def analyse(store: Store | None = None) -> dict[str, Any]:
    s = store or Store()
    with s.mem._c() as c:
        c.executescript(SCHEMA)
    rows = s.q("SELECT * FROM army_llm_ab ORDER BY created")
    d = np.array([r["eth_dev_sharpe_llm"] - r["eth_dev_sharpe_default"] for r in rows])
    usage = s.q(
        "SELECT role, SUM(llm_calls) n, SUM(llm_cost_usd) usd FROM army_usage WHERE role IN ('C1','C2','C3') GROUP BY role"
    )
    out: dict[str, Any] = {"pairs": len(d), "llm_formulation_calls": usage, "protocol": POLICY.name}
    if len(d):
        rng = np.random.default_rng(0)
        means = [rng.choice(d, len(d)).mean() for _ in range(2000)]
        out |= {"mean_diff": float(d.mean()), "ci95": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))], "llm_better": int((d > 0).sum())}  # fmt: skip
    out["decision_ready"] = len(d) >= 15
    return out
