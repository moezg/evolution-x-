"""Mechanism taxonomy, signatures, deduplication and reviewed strategy templates.

An idea (paper, LLM proposal, earlier lab hypothesis) is mapped to a mechanism FAMILY and a SIGNATURE
(family, horizon bucket, direction mode). Two descriptions with the same signature implement substantially the same
mechanism. Implementations are rendered ONLY from the reviewed templates below; an LLM can choose a family and
parameters inside the template's ranges, never code.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

FAMILY_KEYWORDS: dict[str, list[str]] = {
    "tsmom": [r"time[- ]series momentum", r"trend[- ]following", r"\btrend", r"momentum", r"moving average"],
    "breakout": [r"breakout", r"donchian", r"channel"],
    "reversal": [r"mean[- ]reversion", r"reversal", r"overreaction", r"revert"],
    "vol_managed_long": [
        r"volatility[- ]managed",
        r"volatility target",
        r"realized volatility",
        r"volatility forecast",
    ],
    "funding_carry": [r"funding rate", r"perpetual", r"\bbasis\b", r"\bcarry\b"],
    "microstructure": [r"order flow", r"order book", r"limit order", r"market mak", r"bid-ask"],
    "seasonality": [r"intraday", r"seasonal", r"time-of-day", r"day-of-the-week", r"weekend effect"],
}
IMPLEMENTABLE = ("tsmom", "breakout", "reversal", "vol_managed_long", "funding_carry")
INFEASIBLE = {
    "microstructure": "needs order-book / trade data; only 1 h bars are available",
    "seasonality": "needs bar timestamps in the strategy view (BarView exposes none); trusted-interface change required",
}
RESEARCHER = {"tsmom": "C1", "breakout": "C1", "reversal": "C2", "vol_managed_long": "C3", "funding_carry": "C3"}


def classify(title: str, text: str) -> dict[str, Any]:
    t, a = title.lower(), text.lower()
    scores = {
        f: sum(2 * len(re.findall(k, t)) + len(re.findall(k, a)) for k in ks) for f, ks in FAMILY_KEYWORDS.items()
    }
    fam = max(scores, key=lambda f: (scores[f], f in IMPLEMENTABLE))
    return {"family": fam if scores[fam] > 0 else "unclassified", "scores": scores}


def horizon_bucket(h: float) -> str:
    return "short" if h <= 48 else "medium" if h <= 336 else "long"


def signature(family: str, horizon_h: float, long_only: bool) -> str:
    return f"{family}|{horizon_bucket(horizon_h)}|{'long_only' if long_only else 'long_short'}"


def tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", s.lower()))


def jaccard(a: str, b: str) -> float:
    x, y = tokens(a), tokens(b)
    return len(x & y) / max(1, len(x | y))


# ----------------------------------------------------------------------------- memory index of earlier work
def prior_hypotheses(lab_root: Path = Path("artifacts/research")) -> list[dict[str, Any]]:
    """Every hypothesis in every earlier research lab, mapped to a family/signature (development-level info only)."""
    from ..research.memory import Memory

    out = []
    for db in sorted(lab_root.glob("*/research.db")):
        if "superseded" in db.parent.name:
            continue
        for h in Memory(db).q("SELECT id, statement, operator, status FROM hypotheses"):
            text = f"{h.get('statement') or ''} {h.get('operator') or ''}"
            fam = classify("", text)["family"]
            if fam == "unclassified":
                fam = "tsmom"  # every earlier lab mutates the parent v0, a vol-normalised time-series momentum rule
            out.append(
                {
                    "lab": db.parent.name,
                    "id": h["id"],
                    "statement": (h.get("statement") or "")[:300],
                    "family": fam,
                    "status": h.get("status"),
                }
            )
    return out


# ----------------------------------------------------------------------------- templates
TEMPLATES: dict[str, dict[str, Any]] = {
    "tsmom": {
        "params": {"lookback_h": (24, 1440, 336)},
        "long_only": False,
        "body": """
def signal(view, p):
    L = int(p["lookback_h"])
    c = view.close(L + 1)
    if len(c) <= L:
        return 0.0
    lr = np.diff(np.log(c))
    s = float(np.std(lr)) * math.sqrt(L) + 1e-12
    return max(-1.0, min(1.0, float(np.sum(lr)) / s))
""",
    },
    "breakout": {
        "params": {"lookback_h": (24, 1440, 168)},
        "long_only": False,
        "body": """
def signal(view, p):
    L = int(p["lookback_h"])
    h, lo, c = view.high(L), view.low(L), view.close(1)
    if len(h) < L or len(c) < 1:
        return 0.0
    hi, lw = float(np.max(h)), float(np.min(lo))
    if hi <= lw:
        return 0.0
    return max(-1.0, min(1.0, (float(c[-1]) - (hi + lw) / 2) / ((hi - lw) / 2)))
""",
    },
    "reversal": {
        "params": {"lookback_h": (6, 72, 24), "z": (0.5, 3.0, 1.5)},
        "long_only": False,
        "body": """
def signal(view, p):
    L = int(p["lookback_h"])
    c = view.close(10 * L + 1)
    if len(c) <= 10 * L:
        return 0.0
    lr = np.diff(np.log(c))
    s = float(np.std(lr)) * math.sqrt(L) + 1e-12
    zz = float(np.sum(lr[-L:])) / s
    return max(-1.0, min(1.0, -zz / float(p["z"])))
""",
    },
    "vol_managed_long": {
        "params": {"lookback_h": (72, 1440, 336), "target_vol": (0.1, 1.0, 0.4)},
        "long_only": True,
        "body": """
def signal(view, p):
    L = int(p["lookback_h"])
    c = view.close(L + 1)
    if len(c) <= L:
        return 0.0
    ann = float(np.std(np.diff(np.log(c)))) * math.sqrt(8760) + 1e-12
    # exposure 1.0 = engine max leverage (2x); 0.5 = 1x notional; capped at 1x notional
    return max(0.0, min(0.5, 0.5 * float(p["target_vol"]) / ann))
""",
    },
    "funding_carry": {
        "params": {"lookback_h": (24, 720, 168), "scale": (1e-4, 1e-2, 1e-3)},
        "long_only": False,
        "body": """
def signal(view, p):
    L = int(p["lookback_h"])
    f = view.funding(L)
    if len(f) < L:
        return 0.0
    return max(-1.0, min(1.0, -float(np.sum(f)) / float(p["scale"])))
""",
    },
}
PREMISES = {
    "default": [
        {
            "id": "P1",
            "claim": "decisions see only closed bars via the view API",
            "check": {"type": "view_api", "method": "close", "expect": "present"},
        },
        {
            "id": "P2",
            "claim": "decisions are executed at the next bar's open",
            "check": {"type": "engine_feature", "feature": "next_open_execution", "expect": "present"},
        },
    ],
    "funding_carry": [
        {
            "id": "P1",
            "claim": "the view exposes past funding rates",
            "check": {"type": "view_api", "method": "funding", "expect": "present"},
        },
        {
            "id": "P2",
            "claim": "funding is charged on open positions in the backtest",
            "check": {"type": "engine_feature", "feature": "funding_charged", "expect": "present"},
        },
    ],
}


def clamp_params(family: str, params: dict[str, Any] | None) -> dict[str, float]:
    spec = TEMPLATES[family]["params"]
    out = {}
    for k, (lo, hi, default) in spec.items():
        v = (params or {}).get(k, default)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = default
        out[k] = min(max(v, lo), hi)
    return out


def render(family: str, name: str, params: dict[str, float], doc: str) -> str:
    """Build a contract-conforming module (NAME, PARAMS, PARAM_GRID, signal(view, p)) from a reviewed template."""
    tpl = TEMPLATES[family]
    grid = {
        k: sorted({v, *([type(v)(v * 0.5), type(v)(v * 2)] if k.endswith("_h") else [])}) for k, v in params.items()
    }
    first = next(iter(grid))
    grid = {first: [g for g in grid[first] if tpl["params"][first][0] <= g <= tpl["params"][first][1]][:3]}
    safe_doc = re.sub(r'["\\]', "'", doc)[:600]
    return (
        f'"""{safe_doc}\n\nRendered by the research army (role D2) from the reviewed template {family!r}."""\n\n'
        "from __future__ import annotations\n\nimport math\n\nimport numpy as np\n\n"
        f"NAME = {name!r}\nPARAMS = {json.dumps(params)}\nPARAM_GRID = {json.dumps(grid)}\n" + tpl["body"]
    )


def code_sha(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()
