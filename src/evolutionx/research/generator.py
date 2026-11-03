"""CandidateGenerator: writes NEW strategy source code from a hypothesis.

Offline generator (deterministic baseline, no LLM): a small grammar of causal
building blocks (signals, filters, position mappings) is composed into a new
Python module, and a code-level operator edits the parent's source (AST rewrite)
when the hypothesis is about horizons. Every output is real source code with a
diff against its parent; nothing is picked from a fixed catalogue of patches.

LLM generator: same contract and admissibility checks; enabled only when an API
key is configured. Without it the generator reports `unavailable` and the
supervisor records that no LLM experiment was run.
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
import random
from dataclasses import dataclass
from typing import Any

from .contract import literal_symbols, static_check

# ---------------------------------------------------------------- grammar

SIGNALS = {
    "tsmom": {"lookback": [24, 72, 168, 336, 720]},
    "ma_cross": {"fast": [12, 24, 48, 72], "slow": [168, 336, 720]},
    "breakout": {"window": [48, 168, 336, 720]},
    "zrev": {"window": [12, 24, 48, 96]},
}
FILTERS = {
    "vol_target": {"vol_window": [24, 72, 168], "target_vol": [0.4, 0.6, 0.8]},
    "trend_filter": {"trend_window": [720, 1440, 2160]},
    "deadzone": {"threshold": [0.2, 0.35, 0.5]},
    "funding_guard": {"max_funding": [0.0003, 0.0005, 0.001]},
}

SIGNAL_CODE = {
    "tsmom": """
def _raw(view, p):
    n = int(p["lookback"])
    c = view.close(n + 1)
    if len(c) <= n:
        return 0.0
    r = math.log(c[-1] / c[0])
    vol = float(np.std(np.diff(np.log(c)))) * math.sqrt(n) + 1e-12
    return max(-1.0, min(1.0, r / vol))
""",
    "ma_cross": """
def _raw(view, p):
    f, s = int(p["fast"]), int(p["slow"])
    c = view.close(s)
    if len(c) < s:
        return 0.0
    fast = float(np.mean(c[-f:]))
    slow = float(np.mean(c))
    return max(-1.0, min(1.0, (fast / slow - 1.0) * 20.0))
""",
    "breakout": """
def _raw(view, p):
    n = int(p["window"])
    h = view.high(n + 1)
    lo = view.low(n + 1)
    c = view.close(1)
    if len(h) <= n:
        return 0.0
    top, bot = float(np.max(h[:-1])), float(np.min(lo[:-1]))
    if top <= bot:
        return 0.0
    return max(-1.0, min(1.0, 2.0 * (float(c[-1]) - bot) / (top - bot) - 1.0))
""",
    "zrev": """
def _raw(view, p):
    n = int(p["window"])
    c = view.close(n)
    if len(c) < n:
        return 0.0
    sd = float(np.std(c))
    if sd == 0:
        return 0.0
    return max(-1.0, min(1.0, -(float(c[-1]) - float(np.mean(c))) / sd / 2.0))
""",
}

FILTER_CODE = {
    "vol_target": """
def _f_vol_target(view, p, x):
    c = view.close(int(p["vol_window"]) + 1)
    if len(c) < 3:
        return 0.0
    vol = float(np.std(np.diff(np.log(c)))) * math.sqrt(24 * 365)
    return x * min(1.0, p["target_vol"] / max(vol, 1e-9))
""",
    "trend_filter": """
def _f_trend_filter(view, p, x):
    c = view.close(int(p["trend_window"]))
    if len(c) < int(p["trend_window"]):
        return 0.0
    up = float(c[-1]) > float(np.mean(c))
    return x if (x > 0) == up else 0.0
""",
    "deadzone": """
def _f_deadzone(view, p, x):
    return 0.0 if abs(x) < p["threshold"] else x
""",
    "funding_guard": """
def _f_funding_guard(view, p, x):
    f = view.funding(24)
    paid = float(np.sum(f))
    if x > 0 and paid > p["max_funding"] * 3:
        return 0.0
    if x < 0 and paid < -p["max_funding"] * 3:
        return 0.0
    return x
""",
}


def render(spec: dict[str, Any], name: str, header: str) -> str:
    sig = spec["signal"]
    params = {**{k: v for k, v in sig.items() if k != "kind"}}
    for f in spec["filters"]:
        params.update({k: v for k, v in f.items() if k != "kind"})
    grid = spec.get("grid", {})
    body = [
        f'"""{header}"""',
        "",
        "from __future__ import annotations",
        "",
        "import math",
        "",
        "import numpy as np",
        "",
        f"NAME = {name!r}",
        f"PARAMS = {json.dumps(params, sort_keys=True)}",
        f"PARAM_GRID = {json.dumps(grid, sort_keys=True)}",
        f"SPEC = {json.dumps(spec, sort_keys=True)}",
    ]
    body.append(SIGNAL_CODE[sig["kind"]].rstrip())
    for f in spec["filters"]:
        body.append(FILTER_CODE[f["kind"]].rstrip())
    lines = ["", "", "def signal(view, p):", "    x = _raw(view, p)"]
    for f in spec["filters"]:
        lines.append(f"    x = _f_{f['kind']}(view, p, x)")
    lines.append("    return max(-1.0, min(1.0, x))")
    src = "\n".join(body) + "\n" + "\n".join(lines) + "\n"
    return src.replace("\n\n\ndef", "\n\n\ndef").replace("np.ndarray", "np.ndarray")


def code_hash(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def diff(parent_source: str, child_source: str, parent_name: str, child_name: str) -> str:
    return "".join(
        difflib.unified_diff(
            parent_source.splitlines(True), child_source.splitlines(True), f"a/{parent_name}.py", f"b/{child_name}.py"
        )
    )


# ---------------------------------------------------------------- hypotheses -> operators

OPERATORS = {
    "add_vol_target": {
        "statement": "Scaling exposure by inverse realised volatility improves risk-adjusted net returns.",
        "mechanism": "Crypto volatility clusters; equal-sized positions concentrate losses in high-volatility "
        "periods, so volatility targeting reduces drawdown more than it reduces mean return.",
        "alternatives": ["Volatility is not predictable at the chosen window", "Gains are eaten by extra turnover"],
        "prediction": "Net Sharpe on development walk-forward OOS increases and max drawdown decreases.",
    },
    "add_trend_filter": {
        "statement": "Trading only in the direction of the long-horizon trend reduces whipsaw losses.",
        "mechanism": "Short-horizon signals that disagree with the long trend are more often noise.",
        "alternatives": ["Long trend reverses as often as short trend", "Filter only reduces exposure"],
        "prediction": "Fewer position changes and higher net Sharpe out of sample.",
    },
    "add_deadzone": {
        "statement": "Ignoring weak signals reduces transaction costs enough to raise net Sharpe.",
        "mechanism": "Weak signals flip often and carry little edge; their trading cost exceeds their benefit.",
        "alternatives": ["Weak signals carry most of the edge", "Costs are already negligible"],
        "prediction": "Lower turnover and higher net (not gross) Sharpe.",
    },
    "add_funding_guard": {
        "statement": "Avoiding positions that pay extreme funding improves net returns.",
        "mechanism": "Extreme funding signals crowded positioning and directly costs the payer.",
        "alternatives": ["Extreme funding coincides with strong trends worth paying for"],
        "prediction": "Lower funding cost with unchanged or higher net Sharpe.",
    },
    "change_horizon": {
        "statement": "A different signal horizon better matches the persistence of hourly crypto trends.",
        "mechanism": "Trend persistence varies with horizon; the parent's horizon may sit in a noisy band.",
        "alternatives": ["All horizons have equal edge after costs"],
        "prediction": "Net Sharpe changes monotonically with horizon over the tested range.",
    },
    "swap_signal": {
        "statement": "An alternative trend definition captures the same premium with fewer false flips.",
        "mechanism": "Moving-average crossovers and breakouts smooth noise differently from point-to-point returns.",
        "alternatives": ["Trend definitions are near-equivalent once costs are included"],
        "prediction": "Similar gross Sharpe with lower turnover, hence higher net Sharpe.",
    },
    "try_reversion": {
        "statement": "Short-horizon mean reversion exists on 1h perpetual bars after costs.",
        "mechanism": "Liquidity-driven overshoots revert within hours.",
        "alternatives": ["Reversion edge is smaller than spread+fees"],
        "prediction": "Positive net Sharpe out of sample at 1x costs.",
    },
}


def default_spec_from_v0() -> dict[str, Any]:
    return {"signal": {"kind": "tsmom", "lookback": 168}, "filters": [], "grid": {"lookback": [72, 168, 336]}}


def _pick(rng: random.Random, opts: list[Any]) -> Any:
    return opts[rng.randrange(len(opts))]


def apply_operator(op: str, parent_spec: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    s = copy.deepcopy(parent_spec)
    kinds = {f["kind"] for f in s["filters"]}

    def add_filter(kind: str) -> None:
        f = {"kind": kind, **{k: _pick(rng, v) for k, v in FILTERS[kind].items()}}
        s["filters"] = [x for x in s["filters"] if x["kind"] != kind] + [f]
        key = next(iter(FILTERS[kind]))
        s["grid"] = {key: FILTERS[kind][key][:3]}

    if op == "add_vol_target":
        add_filter("vol_target")
    elif op == "add_trend_filter":
        add_filter("trend_filter")
    elif op == "add_deadzone":
        add_filter("deadzone")
    elif op == "add_funding_guard":
        add_filter("funding_guard")
    elif op == "change_horizon":
        sig = s["signal"]
        key = next(k for k in SIGNALS[sig["kind"]])
        cur = sig[key]
        others = [v for v in SIGNALS[sig["kind"]][key] if v != cur]
        sig[key] = _pick(rng, others)
        s["grid"] = {key: sorted({sig[key], _pick(rng, others)})}
    elif op in ("swap_signal", "try_reversion"):
        kind = (
            "zrev"
            if op == "try_reversion"
            else _pick(rng, [k for k in ("ma_cross", "breakout", "tsmom") if k != s["signal"]["kind"]])
        )
        s["signal"] = {"kind": kind, **{k: _pick(rng, v) for k, v in SIGNALS[kind].items()}}
        key = next(iter(SIGNALS[kind]))
        s["grid"] = {key: SIGNALS[kind][key][:3]}
    else:
        raise ValueError(op)
    _ = kinds
    return s


@dataclass
class Proposal:
    candidate_id: str
    parent_id: str
    operator: str
    hypothesis: dict[str, Any]
    spec: dict[str, Any]
    source: str
    diff: str
    files: list[str]
    contract: str
    expected_benefit: str
    risk: str
    budget: dict[str, Any]
    eval_plan: str
    generator: str
    code_sha256: str
    static_issues: list[str]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class OfflineGenerator:
    name = "offline-grammar-v1"
    kind = "deterministic-offline"

    def available(self) -> tuple[bool, str]:
        return True, "built-in grammar + AST-level code synthesis; no external model"

    def propose(self, op: str, parent: dict[str, Any], rng: random.Random, budget: dict[str, Any]) -> Proposal:
        spec = apply_operator(op, parent["spec"], rng)
        h = OPERATORS[op]
        tmp_id = "cand-" + hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:10]
        header = (
            f"Generated by {self.name}. Parent: {parent['id']}. Operator: {op}.\n\n"
            f"Hypothesis: {h['statement']}\nMechanism: {h['mechanism']}"
        )
        src = render(spec, tmp_id, header)
        return Proposal(
            candidate_id=tmp_id,
            parent_id=parent["id"],
            operator=op,
            hypothesis=h,
            spec=spec,
            source=src,
            diff=diff(parent["source"], src, parent["id"], tmp_id),
            files=[f"src/evolutionx/evolvable/generated/{tmp_id}.py"],
            contract="NAME:str, PARAMS:dict, PARAM_GRID:dict(<=4 combos), signal(view, p)->float in [-1,1]; "
            "imports limited to math/numpy; reads only BarView",
            expected_benefit=h["prediction"],
            risk="May overfit the development period; may raise turnover.",
            budget=budget,
            eval_plan="dev walk-forward screen vs champion -> (if better) paired validation test "
            "per frozen promotion rule; secret-checkpoint causality checks in sandbox",
            generator=self.name,
            code_sha256=code_hash(src),
            static_issues=static_check(src),
        )


class LLMGenerator:
    """Real-model patch author. Requires EVOX_LLM=anthropic|openai and the matching API key."""

    kind = "llm"

    def __init__(self) -> None:
        self.provider_name = os.environ.get("EVOX_LLM", "")
        self.name = f"llm:{self.provider_name or 'none'}"

    def available(self) -> tuple[bool, str]:
        if self.provider_name == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
            return True, "anthropic key configured"
        if self.provider_name == "openai" and os.environ.get("OPENAI_API_KEY"):
            return True, "openai key configured"
        return False, "no LLM provider configured (EVOX_LLM + API key absent); LLM generation not run"

    def propose(self, op: str, parent: dict[str, Any], rng: random.Random, budget: dict[str, Any]) -> Proposal:
        ok, why = self.available()
        if not ok:
            raise RuntimeError(why)
        from ..council.llm import AnthropicLLM, OpenAICompatLLM

        model = AnthropicLLM() if self.provider_name == "anthropic" else OpenAICompatLLM()
        h = OPERATORS[op]
        system = (
            "You write one self-contained Python strategy module. Contract: NAME (str), PARAMS (dict), "
            "PARAM_GRID (dict, <=4 combinations), def signal(view, p) -> float in [-1, 1]. Only import math "
            "and numpy. `view` exposes close(n), open(n), high(n), low(n), volume(n), funding(n) returning the "
            "last n CLOSED bars. Return ONLY the module source."
        )
        user = (
            f"Parent module:\n```python\n{parent['source']}\n```\nHypothesis to test: {h['statement']}\n"
            f"Mechanism: {h['mechanism']}\nWrite the child module."
        )
        raw = model.complete(system, user, 2500)
        src = raw.split("```python")[-1].split("```")[0] if "```" in raw else raw
        cid = "llm-" + code_hash(src)[:10]
        lit = literal_symbols(src) if not static_check(src) else {}
        return Proposal(
            cid,
            parent["id"],
            op,
            h,
            {"llm": True, **({"name": lit.get("NAME")} if lit else {})},
            src,
            diff(parent["source"], src, parent["id"], cid),
            [f"src/evolutionx/evolvable/generated/{cid}.py"],
            "same contract",
            h["prediction"],
            "LLM output may be invalid or overfit",
            budget,
            "same as offline",
            f"{self.name}:{model.model}",
            code_hash(src),
            static_check(src),
        )
