"""Deterministic policy enforcement (PROTECTED: code proposals may not touch this file).

Everything that decides status - promotion eligibility, what a researcher may see, which paths a code proposal may
touch - lives here and reads the frozen policy; no LLM output is consulted.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

POLICY = Path("evals/frozen/army_policy_v1.json")


def policy() -> dict[str, Any]:
    return json.loads(POLICY.read_text())


def policy_sha() -> str:
    return hashlib.sha256(POLICY.read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- researcher context
def scrub_context(obj: Any, forbidden: list[str] | None = None) -> Any:
    """Remove any key that names selection/validation/consumed/holdout/prospective-outcome information."""
    bad = [k.lower() for k in (forbidden or policy()["researcher_context"]["forbidden_keys"])]
    if isinstance(obj, dict):
        return {k: scrub_context(v, bad) for k, v in obj.items() if not any(b in str(k).lower() for b in bad)}
    if isinstance(obj, list):
        return [scrub_context(v, bad) for v in obj]
    return obj


def context_is_clean(obj: Any) -> bool:
    bad = [k.lower() for k in policy()["researcher_context"]["forbidden_keys"]]
    text = json.dumps(obj, default=str).lower()
    return not any(f'"{b}' in text or f"_{b}" in text for b in bad)


# ----------------------------------------------------------------------------- promotion
def eligibility(
    lab_verdict: str | None, adversarial: dict[str, Any], prospective: dict[str, Any] | None
) -> dict[str, Any]:
    """Status of a candidate. 'validated' is impossible without prospective evidence and a human approval flag."""
    hard = [k for k, v in (adversarial.get("tests") or {}).items() if v.get("hard_failure")]
    if lab_verdict != "promote" or hard:
        why = []
        if lab_verdict != "promote":
            why.append(f"lab verdict {lab_verdict!r} (needs 'promote' on the selection data)")
        if hard:
            why.append(f"adversarial hard failures: {hard}")
        return {"status": "rejected", "why": why, "validated": False}
    p = prospective or {}
    if p.get("resolved_days", 0) >= 180 and p.get("ci_lo", -1.0) > 0 and p.get("human_approved") is True:
        return {"status": "validated", "why": ["prospective evidence and human approval"], "validated": True}
    return {
        "status": "prospective_challenger",
        "why": ["passed selection on previously exposed data; needs >= 180 resolved prospective paper days"],
        "validated": False,
    }


# ----------------------------------------------------------------------------- code proposals
def touches_protected(paths: list[str]) -> list[str]:
    prot = policy()["code_proposals"]["protected_paths"]
    return sorted({p for p in paths for q in prot if p == q.rstrip("/") or p.startswith(q)})
