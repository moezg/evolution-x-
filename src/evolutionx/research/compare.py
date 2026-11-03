"""Pre-registered comparison of research methods (evals/frozen/generator_comparison_v1.json).

Runs one bounded campaign per arm in a fresh lab and computes PROCESS metrics from persistent lab state only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .lessons import CLASSES
from .supervisor import Lab, Supervisor

SPEC = Path("evals/frozen/generator_comparison_v1.json")
ROOT = Path("artifacts/research")
PRIOR = ["arm_guided", "arm_random", "claude_session", "claude_cli"]


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def run_arm(arm: str, tag: str, tasks: int, seed: int = 0) -> Path:
    spec = json.loads(SPEC.read_text())["arms"][arm]
    root = ROOT / f"cmp_{tag}_{arm}"
    lab = Lab(root, repo=Path.cwd())
    sup = Supervisor(lab)
    if spec["generator"].startswith("claude-cli"):
        from .llm_connectors import ClaudeCLIGenerator

        sup.generator = ClaudeCLIGenerator(sup.policy["llm"]["connectors"]["claude-cli"])
    sup.use_dossier = bool(spec["dossier"])
    sup.memory_roots = [ROOT / p for p in PRIOR] if spec["memory"] else None
    sup.inherit_validation_trials([ROOT / p for p in PRIOR if (ROOT / p / "research.db").exists()])
    cid = f"{tag}-{arm}"
    sup.create_campaign(cid, "research", "guided", tasks, 3600, seed)
    sup.run(cid)
    return root


def _all_code_hashes(exclude: Path) -> dict[str, str]:
    out = {}
    for db in ROOT.glob("*/research.db"):
        if db.parent == exclude:
            continue
        lab = Lab(db.parent)
        for r in lab.memory.q("SELECT id, code_sha256, created FROM candidates"):
            out.setdefault(r["code_sha256"], f"{db.parent.name}/{r['id']}")
    return out


def arm_metrics(root: Path) -> dict[str, Any]:
    lab = Lab(root)
    camp = lab.memory.q("SELECT * FROM campaigns")[0]
    tasks = [t for t in lab.memory.q("SELECT * FROM tasks ORDER BY seq")]
    others = _all_code_hashes(root)
    rows = []
    for t in tasks:
        ck = t["checkpoint"] or {}
        rows.append(
            {
                "task": t["id"],
                "status": t["status"],
                "error": (t["error"] or "")[:200],
                "hypothesis": bool(ck.get("premise_check")),
                "premise_verdict": (ck.get("premise_check") or {}).get("verdict"),
                "premise_counts": (ck.get("premise_check") or {}).get("counts"),
                "candidate": ck.get("candidate_id"),
                "executable": "screen" in ck,
                "duplicate": bool(ck.get("duplicate_of")) or (ck.get("code_sha256") in others),
                "duplicate_of": ck.get("duplicate_of") or others.get(ck.get("code_sha256", "")),
                "mechanism_observed": (ck.get("mechanism") or {}).get("observed")
                if (ck.get("mechanism") or {}).get("declared")
                else None,
                "class": (ck.get("classification") or {}).get("class"),
                "verdict": ck.get("verdict"),
                "motivated_by": ((ck.get("external") or {}).get("hypothesis") or {}).get("motivated_by"),
                "change": ((ck.get("external") or {}).get("novelty") or ck.get("operator") or "")[:300],
            }
        )
    hyp = [r for r in rows if r["hypothesis"]]
    cand = [r for r in rows if r["candidate"]]
    inf = [r for r in rows if r["executable"]]
    mech = [r for r in inf if r["mechanism_observed"] is not None]
    c = camp["consumed"]
    n_inf = max(len(inf), 1)

    def rate(k: int, n: int) -> dict[str, Any]:
        return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "wilson95": _wilson(k, n)}

    return {
        "lab": root.name,
        "campaign": camp["id"],
        "status": camp["status"],
        "tasks": len(rows),
        "premise_correct_rate": rate(sum(r["premise_verdict"] == "accepted" for r in hyp), len(hyp)),
        "executable_rate": rate(len(inf), len(cand)),
        "duplicate_rate": rate(sum(r["duplicate"] for r in cand), len(cand)),
        "mechanism_observed_rate": rate(sum(bool(r["mechanism_observed"]) for r in mech), len(mech)),
        "unstable_share": rate(sum(r["class"] == "unstable_across_periods" for r in inf), len(inf)),
        "confirmed": sum(r["verdict"] == "promote" for r in rows),
        "classes": {k: sum(r["class"] == k for r in rows) for k in CLASSES if any(r["class"] == k for r in rows)},
        "cost": {
            "wall_s": c.get("wall_s"),
            "sandbox_runs": c.get("sandbox_runs", 0),
            "llm_calls": c.get("llm_calls", 0),
            "llm_tokens": c.get("llm_tokens", 0),
            "llm_cost_usd_api_equivalent_estimate": c.get("llm_cost_usd_equiv", 0.0),
            "per_informative": {
                "wall_s": round((c.get("wall_s") or 0) / n_inf, 1),
                "llm_usd_api_equivalent": round(c.get("llm_cost_usd_equiv", 0.0) / n_inf, 4),
            },
            "billing_note": "USD values are the CLI's API-equivalent estimates, not observed subscription billing",
        },
        "rows": rows,
    }


def report(tag: str, arms: list[str]) -> dict[str, Any]:
    spec_text = SPEC.read_text()
    rep = {
        "tag": tag,
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "protocol": json.loads(spec_text)["name"],
        "protocol_sha256": hashlib.sha256(spec_text.encode()).hexdigest(),
        "label": "PILOT: mechanism + cost check; no inferential claim",
        "arms": {
            a: arm_metrics(ROOT / f"cmp_{tag}_{a}") for a in arms if (ROOT / f"cmp_{tag}_{a}" / "research.db").exists()
        },
    }
    out = ROOT / "comparisons"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{tag}.json").write_text(json.dumps(rep, indent=2, default=str))
    return rep
