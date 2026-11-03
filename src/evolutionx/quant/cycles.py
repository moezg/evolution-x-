"""Cycle discovery (G3) and time-series diagnostics (G2) - family F-CYCLE of quant_protocol_v1.

A candidate cycle at period P is "supported" only if the periodogram ordinate nearest to P is extreme within the
local band [P/2, 2P] (rank p < 0.05 after Holm over the 8 registered tests) in BOTH chronological halves of the
discovery period AND in the confirmation period. A chart that "looks periodic" is not evidence.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .calendar import daily_frame, protocol, protocol_sha
from .stats import TestRegistry, holm

PERIODS = (7.0, 30.44, 91.31, 365.25)


def periodogram(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = x - x.mean()
    n = len(x)
    f = np.fft.rfftfreq(n, d=1.0)[1:]
    p = (np.abs(np.fft.rfft(x)) ** 2 / n)[1:]
    return f, p


def band_rank(x: np.ndarray, period: float) -> dict[str, float]:
    f, p = periodogram(x)
    k = int(np.argmin(np.abs(f - 1 / period)))
    band = (f >= 1 / (2 * period)) & (f <= 2 / period)
    others = p[band]
    rank_p = (1 + np.sum(others >= p[k])) / (1 + len(others))  # includes itself -> conservative
    return {
        "period_days": period,
        "nearest_period": float(1 / f[k]),
        "power": float(p[k]),
        "band_median": float(np.median(others)),
        "ratio_to_band_median": float(p[k] / np.median(others)),
        "band_size": int(len(others)),
        "p_rank": float(rank_p),
    }


def acf(x: np.ndarray, lags: int = 10) -> list[float]:
    x = x - x.mean()
    d = float(np.dot(x, x))
    return [float(np.dot(x[:-k], x[k:]) / d) for k in range(1, lags + 1)]


def run(run_id: str, reg: TestRegistry | None = None) -> dict[str, Any]:
    reg = reg or TestRegistry()
    fr = daily_frame()
    per = protocol()["periods"]
    out: dict[str, Any] = {"cycles": {}, "diagnostics": {}}
    tests = {}
    for series in ("ret", "absret"):
        for P in PERIODS:
            res = {}
            for name, (a, b) in {"DISCOVERY": per["DISCOVERY"], "CONFIRMATION": per["CONFIRMATION"]}.items():
                m = (fr["date"] >= a) & (fr["date"] <= b) & np.isfinite(fr["ret"])
                x = fr["ret"][m] if series == "ret" else np.abs(fr["ret"][m])
                h = len(x) // 2
                res[name] = band_rank(x, P)
                if name == "DISCOVERY":
                    res["DISC_H1"], res["DISC_H2"] = band_rank(x[:h], P), band_rank(x[h:], P)
            key = f"F-CYCLE:{series}:{P}d"
            tests[key] = res
    h = holm({k: v["DISCOVERY"]["p_rank"] for k, v in tests.items()}, 0.05)
    for k, v in tests.items():
        ok = (
            h[k]["reject"]
            and v["DISC_H1"]["p_rank"] < 0.05
            and v["DISC_H2"]["p_rank"] < 0.05
            and v["CONFIRMATION"]["p_rank"] < 0.05
        )
        st = "supported" if ok else ("inconclusive" if h[k]["reject"] else "rejected")
        out["cycles"][k] = {**v, "holm": h[k], "status": st}
        reg.record(
            {
                "family": "F-CYCLE",
                "hypothesis": k,
                "role": "G3",
                "method": "periodogram rank within [P/2, 2P] + Holm(0.05) + stability in halves and confirmation",
                "period": "DISCOVERY",
                "n": int(v["DISCOVERY"]["band_size"]),
                "effect": v["DISCOVERY"]["ratio_to_band_median"],
                "p": v["DISCOVERY"]["p_rank"],
                "p_adj": h[k]["p_adj"],
                "adj_method": "Holm over 8",
                "status": st,
                "protocol_sha": protocol_sha(),
                "run_id": run_id,
                "details": {
                    "halves": [v["DISC_H1"]["p_rank"], v["DISC_H2"]["p_rank"]],
                    "confirmation_p_rank": v["CONFIRMATION"]["p_rank"],
                },
            }
        )
    m = (fr["date"] <= per["DISCOVERY"][1]) & np.isfinite(fr["ret"])
    x = fr["ret"][m]
    band = 1.96 / np.sqrt(len(x))
    out["diagnostics"] = {
        "period": "DISCOVERY",
        "n": int(len(x)),
        "acf_ret": acf(x),
        "acf_absret": acf(np.abs(x)),
        "bartlett_95_band": float(band),
        "note": "ACF of returns near zero and of |returns| strongly positive = volatility clustering without linear predictability (G2)",
    }
    return out
