"""Statistical machinery for calendar / cycle / event research and the statistical-testing registry.

Methods (frozen in evals/frozen/quant_protocol_v1.json):
  rotation_test      calendar labels vs returns circularly shifted by random offsets (keeps dependence intact)
  placebo_test       event mean vs means of equally many matched placebo times (same weekday and clock time)
  bootstrap_ci       percentile CI of a mean over events (events are the unit of replication)
  bh / holm          multiple-comparison control within a family
Every test result is written to the registry (army research.db, table stat_tests) with family and lineage.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections.abc import Callable
from typing import Any

import numpy as np

from ..army.store import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS stat_tests (id TEXT PRIMARY KEY, family TEXT, hypothesis TEXT, role TEXT, method TEXT,
  period TEXT, n INTEGER, n_ref INTEGER, effect REAL, ci_lo REAL, ci_hi REAL, p REAL, p_adj REAL, adj_method TEXT,
  status TEXT, direction INTEGER, data_sha TEXT, protocol_sha TEXT, run_id TEXT, details TEXT, created TEXT);
"""


def rotation_test(
    x: np.ndarray,
    label: np.ndarray,
    stat: Callable[[np.ndarray, np.ndarray], float],
    n: int = 999,
    seed: int = 0,
    min_shift: int = 31,
    label_period: int | None = None,
) -> tuple[float, float, np.ndarray]:
    """Two-sided p for stat(x, label) under circular shifts of x relative to the labels.

    Shifts that re-align a periodic label (multiples of label_period) are excluded - they would put the effect
    back into the null. p uses the null's mean/sd (normal approximation; protocol amendment 2)."""
    obs = stat(x, label)
    rng = np.random.default_rng(seed)
    shifts: list[int] = []
    while len(shifts) < n:
        k = int(rng.integers(min_shift, len(x) - min_shift))
        if label_period and k % label_period == 0:
            continue
        shifts.append(k)
    null = np.array([stat(np.roll(x, k), label) for k in shifts])
    z = (obs - null.mean()) / null.std() if null.std() > 0 else 0.0
    return float(obs), float(math.erfc(abs(z) / math.sqrt(2))), null


def placebo_test(event_vals: np.ndarray, placebo_vals: np.ndarray, n: int = 2000, seed: int = 0) -> dict[str, float]:
    """Event mean vs the distribution of means of len(event_vals) placebo values drawn without replacement."""
    ev = event_vals[np.isfinite(event_vals)]
    pl = placebo_vals[np.isfinite(placebo_vals)]
    if len(ev) == 0 or len(pl) < len(ev):
        return {"n": len(ev), "p": float("nan"), "effect": float("nan"), "percentile": float("nan")}
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(pl, len(ev), replace=False).mean() for _ in range(n)])
    m = float(ev.mean())
    center = float(np.median(means))
    p = (1 + np.sum(np.abs(means - center) >= abs(m - center) - 1e-15)) / (n + 1)
    return {
        "n": len(ev),
        "n_placebo_pool": len(pl),
        "event_mean": m,
        "placebo_median_of_means": center,
        "effect": m - center,
        "p": float(p),
        "p_greater": float((1 + np.sum(means >= m)) / (n + 1)),  # one-sided, never 0
        "p_less": float((1 + np.sum(means <= m)) / (n + 1)),
        "percentile": float(np.mean(means < m)),
    }


def bootstrap_ci(v: np.ndarray, n: int = 2000, seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    v = v[np.isfinite(v)]
    if len(v) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(v, len(v)).mean() for _ in range(n)])
    a = (1 - level) / 2
    return (float(np.quantile(means, a)), float(np.quantile(means, 1 - a)))


def bh(p: dict[str, float], q: float = 0.10) -> dict[str, dict[str, Any]]:
    items = sorted(((k, v) for k, v in p.items() if np.isfinite(v)), key=lambda kv: kv[1])
    m = len(items)
    k_max = max((i + 1 for i, (_, v) in enumerate(items) if v <= q * (i + 1) / m), default=0)
    out = {}
    prev = 1.0
    adj = {}
    for i in range(m - 1, -1, -1):  # BH-adjusted p (monotone)
        k, v = items[i]
        prev = min(prev, v * m / (i + 1))
        adj[k] = prev
    for i, (k, v) in enumerate(items):
        out[k] = {"p": v, "p_adj": adj[k], "reject": i < k_max}
    return out


def holm(p: dict[str, float], alpha: float = 0.05) -> dict[str, dict[str, Any]]:
    items = sorted(((k, v) for k, v in p.items() if np.isfinite(v)), key=lambda kv: kv[1])
    m = len(items)
    out, still, run = {}, True, 0.0
    for i, (k, v) in enumerate(items):
        run = max(run, min(1.0, v * (m - i)))
        rej = still and v <= alpha / (m - i)
        still = rej
        out[k] = {"p": v, "p_adj": run, "reject": rej}
    return out


# ----------------------------------------------------------------------------- registry
class TestRegistry:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()
        with self.store.mem._c() as c:
            c.executescript(SCHEMA)

    def record(self, rec: dict[str, Any]) -> str:
        key = json.dumps(
            {k: rec.get(k) for k in ("family", "hypothesis", "period", "method", "run_id")}, sort_keys=True
        )
        tid = "T-" + hashlib.sha256(key.encode()).hexdigest()[:12]
        cols = [
            "id",
            "family",
            "hypothesis",
            "role",
            "method",
            "period",
            "n",
            "n_ref",
            "effect",
            "ci_lo",
            "ci_hi",
            "p",
            "p_adj",
            "adj_method",
            "status",
            "direction",
            "data_sha",
            "protocol_sha",
            "run_id",
            "details",
            "created",
        ]
        vals = {
            **{c: None for c in cols},
            **rec,
            "id": tid,
            "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }
        vals["details"] = json.dumps(vals.get("details") or {}, default=float)
        sql = f"INSERT OR REPLACE INTO stat_tests ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"  # noqa: S608  # nosec B608 - fixed column list
        self.store.x(sql, tuple(_num(vals[c]) for c in cols))
        return tid

    def rows(self, family: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
        q, a = "SELECT * FROM stat_tests WHERE 1=1", []
        if family:
            q, a = q + " AND family=?", [*a, family]
        if run_id:
            q, a = q + " AND run_id=?", [*a, run_id]
        return self.store.q(q + " ORDER BY family, hypothesis, period", tuple(a))

    def counts(self) -> dict[str, Any]:
        r = self.store.q("SELECT family, period, COUNT(*) n FROM stat_tests GROUP BY family, period")
        d = self.store.q("SELECT COUNT(DISTINCT hypothesis) h, COUNT(DISTINCT run_id) runs FROM stat_tests")[0]
        return {
            "total_tests": sum(x["n"] for x in r),
            "distinct_hypotheses": d["h"],
            "runs": d["runs"],
            "note": "re-runs of the same pre-registered test are reproductions, not new hypotheses",
            "by_family_period": r,
        }


def _num(v: Any) -> Any:
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not np.isfinite(v):
        return None
    return v
