"""LLM candidate authors (construction role) behind the same admissibility/evaluation pipeline.

ClaudeCLIGenerator: calls the official `claude -p` CLI already authenticated in this environment (it may consume
the user's Claude plan quota). It runs with no tools (`--tools ""`), one turn, a per-call budget cap, in an empty
temporary directory, so it can only return text. The supervisor builds the prompt from DEVELOPMENT-only
information: parent source, development diagnostics, and previously tested ideas with their development screen
results (never validation or final results). The returned source is untrusted and goes through the normal gates.

Session import: a candidate written inside an interactive Claude Code session is imported with declared provenance
and a declared list of what its author had seen (generator exposure). It is evaluated exactly like any candidate.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from typing import Any

from pydantic import BaseModel, Field

from .contract import static_check
from .generator import Proposal, code_hash, diff

CONTRACT = (
    "Write ONE self-contained Python module for a trading strategy on 1-hour perpetual-futures bars.\n"
    "Contract: NAME (str), PARAMS (dict of literals), PARAM_GRID (dict param -> list; at most 4 combinations in total),"
    " def signal(view, p) -> float in [-1, 1] (target exposure; 1 = max allowed leverage long).\n"
    "Allowed imports: math, numpy only. No file, network, os/sys, eval/exec, globals, private/dunder attributes.\n"
    "`view` exposes ONLY past closed bars: view.close(n), view.open(n), view.high(n), view.low(n), view.volume(n),"
    " view.funding(n) return numpy arrays of the last n values (fewer at the start), view.t is the bar index.\n"
    "The decision is executed at the next bar's open with fees (5 bps), spread, sqrt impact and funding.\n"
)
SYSTEM = (
    "You are the construction role of a falsifiable research process. Propose ONE testable hypothesis and the code "
    "that tests it. Prefer a single, attributable change versus the parent. Do not claim results. "
    "Answer with a single JSON object and nothing else."
)


class LLMOut(BaseModel):
    hypothesis: str = Field(min_length=10, max_length=1500)
    mechanism: str = Field(min_length=10, max_length=3000)
    alternatives: list[str] = Field(min_length=1, max_length=8)
    prediction: str = Field(min_length=10, max_length=1500)
    change_summary: str = Field(min_length=5, max_length=1500)
    source: str = Field(min_length=50, max_length=20_000)


class LLMBudgetExceeded(RuntimeError):
    pass


class LLMOutputInvalid(ValueError):
    """The call happened (quota consumed) but its output failed validation; carries usage for accounting."""

    def __init__(self, msg: str, call: dict[str, Any]) -> None:
        super().__init__(msg)
        self.call = call


class ClaudeCLIGenerator:
    kind = "llm"
    formulates_hypothesis = True

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.name = "claude-cli"

    def available(self) -> tuple[bool, str]:
        if not shutil.which(self.cfg.get("binary", "claude")):
            return False, "claude CLI not found"
        return True, "official claude CLI present (uses the environment's existing authentication)"

    def call(self, prompt: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="evox-llm-") as d:
            cmd = [
                self.cfg.get("binary", "claude"),
                "-p",
                prompt,
                "--output-format",
                "json",
                "--tools",
                "",
                "--max-turns",
                str(self.cfg["max_turns"]),
                "--max-budget-usd",
                str(self.cfg["max_budget_usd_per_call"]),
                "--system-prompt",
                SYSTEM,
                "--no-session-persistence",
            ]
            t = time.perf_counter()
            r = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=self.cfg["timeout_s"], check=False)
            wall = time.perf_counter() - t
        if r.returncode != 0:
            raise RuntimeError(f"claude CLI rc={r.returncode}: {r.stderr[-500:]}")
        meta = json.loads(r.stdout)
        usage = meta.get("usage") or {}
        tokens = sum(
            int(usage.get(k, 0) or 0)
            for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        return {
            "text": meta.get("result", ""),
            "cost_usd_equiv": float(meta.get("total_cost_usd") or 0.0),
            "tokens": tokens,
            "models": list((meta.get("modelUsage") or {}).keys()),
            "session_id": meta.get("session_id"),
            "wall_s": round(wall, 2),
            "is_error": meta.get("is_error"),
            "stop_reason": meta.get("stop_reason"),
        }

    def propose_with_dossier(
        self, parent: dict[str, Any], dossier: dict[str, Any], budget: dict[str, Any], require_motivation: bool
    ) -> tuple[Proposal, dict[str, Any]]:
        """One call. The model sees the verified technical dossier (and lessons if present), never validation/final
        data, and must answer with checkable premises and a mechanism test."""
        from .context import render

        fields = (
            '"current_behavior","premises":[{"id","claim","check":{...}}],"change","mechanism_effect",'
            '"refutation_observation","mechanism_test":{"metric","symbol","direction","min_relative_change"},'
            '"hypothesis","mechanism","alternatives":[...],"prediction","change_summary","source"'
        )
        if require_motivation:
            fields += ',"motivated_by":["<lab>/<task id> from lessons_from_memory"],"new_information"'
        prompt = (
            CONTRACT
            + "\nTECHNICAL DOSSIER generated from the repository at commit "
            + str(dossier.get("git_commit"))
            + " (dossier sha256 "
            + str(dossier.get("dossier_sha256"))[:16]
            + "). Treat it as ground truth about "
            "the engine, interface and measured behaviour; do NOT assume features or problems that it contradicts."
            "\n"
            + render(dossier)
            + "\nRULES:\n- Propose ONE identifiable change to the parent (a new rule or composition is allowed;"
            " you are not limited to existing building blocks).\n- State the current behaviour you claim to improve"
            " and back it with premises written in premise_language; at least one must be verifiable (engine_feature,"
            " view_api or parent_metric). A falsified premise rejects the proposal before any backtest.\n"
            "- Give a mechanism_test the evaluator will measure on development (candidate vs parent).\n"
            "- State the observation that would refute the hypothesis.\n"
            + (
                "- Cite in motivated_by the lessons (task ids) that motivate this proposal and explain in"
                " new_information what this experiment will teach that previous ones did not. Do not repeat a"
                " change already tested with other parameters unless you name the new evidence.\n"
                if require_motivation
                else ""
            )
            + "Return ONE JSON object with fields: {"
            + fields
            + "}"
        )
        call = self.call(prompt)
        txt = call["text"].strip()
        if txt.startswith("```"):
            txt = txt.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            out = LLMOutV2.model_validate(json.loads(txt[txt.find("{") : txt.rfind("}") + 1]))
            if require_motivation and (not out.motivated_by or not out.new_information):
                raise ValueError("motivated_by and new_information are required in memory mode")
        except ValueError as e:
            raise LLMOutputInvalid(str(e)[:600], call) from e
        src = out.source
        if "```" in src:
            src = src.split("```python")[-1].split("```")[0]
        cid = "llm-" + code_hash(src)[:10]
        h = {
            "statement": out.hypothesis,
            "mechanism": out.mechanism,
            "alternatives": out.alternatives,
            "prediction": out.prediction,
            "current_behavior": out.current_behavior,
            "change": out.change,
            "mechanism_effect": out.mechanism_effect,
            "refutation_observation": out.refutation_observation,
            "motivated_by": out.motivated_by,
            "new_information": out.new_information,
        }
        prop = Proposal(
            cid,
            parent["id"],
            "llm_free_form",
            h,
            {
                "llm": True,
                "change_summary": out.change_summary,
                "premises": out.premises,
                "mechanism_test": out.mechanism_test.model_dump(),
            },
            src,
            diff(parent["source"], src, parent["id"], cid),
            [f"src/evolutionx/evolvable/generated/{cid}.py"],
            "standard contract",
            out.prediction,
            "LLM output may be invalid, non-causal or overfit",
            budget,
            "premise check, then same gates and frozen promotion rule as every candidate",
            f"claude-cli:{','.join(call['models'])}",
            code_hash(src),
            static_check(src),
        )
        return prop, call


class MechanismTest(BaseModel):
    metric: str
    symbol: str = "ALL"
    direction: str
    min_relative_change: float = Field(ge=0.0, le=1.0)

    def model_post_init(self, _ctx: Any) -> None:
        from .context import MECH_METRICS

        if (
            self.metric not in MECH_METRICS
            or self.direction not in ("decrease", "increase")
            or self.symbol not in ("BTCUSDT", "ETHUSDT", "ALL")
        ):
            raise ValueError(f"invalid mechanism_test {self.metric}/{self.direction}/{self.symbol}")


class LLMOutV2(LLMOut):
    current_behavior: str = Field(min_length=10, max_length=1500)
    premises: list[dict[str, Any]] = Field(min_length=1, max_length=8)
    change: str = Field(min_length=5, max_length=1500)
    mechanism_effect: str = Field(min_length=5, max_length=1500)
    refutation_observation: str = Field(min_length=5, max_length=1500)
    mechanism_test: MechanismTest
    motivated_by: list[str] = Field(default_factory=list, max_length=10)
    new_information: str = Field(default="", max_length=1500)
