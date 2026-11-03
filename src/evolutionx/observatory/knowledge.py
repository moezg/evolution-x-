"""Simulator-research memory: mechanisms, experiment dedup, next-experiment choice, gaps and proposals.

Reuses the research lab's SQLite `Memory` schema (research/memory.py) in a separate store
(artifacts/observatory/knowledge.db):
  * hypotheses  -> mechanisms (status: supported / not_supported / not_observed / exploratory_supported / open)
  * experiments -> registered experiments, keyed by hypothesis + conditions (+ seeds); identical repeats refused
  * candidates  -> simulator change proposals; status is only ever 'proposed' or 'evaluated:<verdict>'.
    Nothing in this module applies a proposal; promotion needs a human change to the code or defaults.

Proposals are judged only by the frozen realism rules (evals/frozen/realism_track_v2.json). Cascade size is
deliberately not a criterion.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from ..research.memory import Memory, now

DB = Path("artifacts/observatory/knowledge.db")
STATUSES = ("supported", "not_supported", "not_observed", "exploratory_supported", "open")


class DuplicateExperiment(RuntimeError):
    pass


def _canon(o: Any) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)


def condition_key(hypothesis_id: str, conditions: dict[str, Any]) -> str:
    return hashlib.sha256(_canon({"h": hypothesis_id, "c": conditions}).encode()).hexdigest()[:20]


def open_memory(path: Path = DB) -> Memory:
    return Memory(path)


# ----------------------------------------------------------------------------- experiments
def register_experiment(
    mem: Memory,
    hypothesis_id: str,
    conditions: dict[str, Any],
    seeds: list[int],
    protocol_sha: str,
    result: dict[str, Any],
    replication_of: str | None = None,
) -> str:
    """Store an experiment. Same hypothesis + conditions is refused unless it is a declared replication
    with seeds disjoint from every earlier run of that condition."""
    ck = condition_key(hypothesis_id, conditions)
    prior = mem.q("SELECT key, result FROM experiments WHERE key LIKE ?", (ck + ":%",))
    if prior:
        if replication_of != ck:
            raise DuplicateExperiment(f"{hypothesis_id}: identical conditions already run ({prior[0]['key']})")
        used = {s for p in prior for s in (p["result"] or {}).get("seeds", [])}
        if used & set(seeds):
            raise DuplicateExperiment("a replication must use seeds not used before for these conditions")
    key = f"{ck}:{hashlib.sha256(_canon(sorted(seeds)).encode()).hexdigest()[:8]}"
    mem.put_experiment(key, hypothesis_id, "observatory", protocol_sha, "synthetic", {**result, "seeds": seeds})
    return key


def guard_new(mem: Memory, hypothesis_id: str, conditions: dict[str, Any]) -> None:
    ck = condition_key(hypothesis_id, conditions)
    if mem.q("SELECT key FROM experiments WHERE key LIKE ?", (ck + ":%",)):
        raise DuplicateExperiment(f"{hypothesis_id}: identical conditions already run")


# ----------------------------------------------------------------------------- mechanisms
def record_mechanism(mem: Memory, mid: str, statement: str, status: str, evidence: dict[str, Any], kind: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status}")
    mem.x(
        "INSERT OR REPLACE INTO hypotheses (id, signature, statement, operator, parent_id, candidate_id, status, "
        "evidence, novelty, created, updated, classification, premises) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, kind, statement, "observatory", None, None, status, _canon(evidence), None, now(), now(), kind, None),
    )


def mechanisms(mem: Memory) -> list[dict[str, Any]]:
    return mem.q("SELECT id, statement, status, evidence, classification, updated FROM hypotheses ORDER BY id")


# ----------------------------------------------------------------------------- gaps and proposals
def record_gap(mem: Memory, gid: str, description: str, evidence: dict[str, Any]) -> None:
    record_mechanism(mem, f"gap:{gid}", description, "open", evidence, "simulator_gap")


def propose(
    mem: Memory, pid: str, gap_id: str, overrides: dict[str, Any], rationale: str, in_track_space: bool
) -> dict[str, Any]:
    spec = {"overrides": overrides, "rationale": rationale, "gap": gap_id, "in_track_space": in_track_space}
    mem.x(
        "INSERT OR REPLACE INTO candidates (id, parent_id, code_sha256, generator, operator, spec, path, status, created) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            pid,
            None,
            None,
            "rule:knowledge",
            gap_id,
            _canon(spec),
            None,
            "proposed" if in_track_space else "needs_human_rules_review",
            now(),
        ),
    )
    return spec


def proposals(mem: Memory) -> list[dict[str, Any]]:
    return mem.q("SELECT id, operator AS gap, spec, status, created FROM candidates WHERE generator='rule:knowledge'")


def evaluate_proposal(mem: Memory, pid: str, workers: int = 4) -> dict[str, Any]:
    """Judge a proposal with the frozen realism rules. Records the verdict; never applies anything."""
    from . import realism

    row = next(p for p in proposals(mem) if p["id"] == pid)
    spec = row["spec"]
    if not spec["in_track_space"]:
        raise ValueError("proposal lies outside the frozen candidate space; it needs a human rules review")
    rules, _ = realism.rules()
    cands = {i: realism.CANDIDATES_V2[i] for i in rules["incumbents"]}
    cands[pid] = spec["overrides"]
    rep = realism.evaluate(cands, workers=workers, tag=pid)
    verdicts = rep["results"][pid]["verdict_vs"]
    mem.x("UPDATE candidates SET status=? WHERE id=?", ("evaluated:" + _canon(verdicts), pid))
    return {
        "proposal": pid,
        "verdict_vs": verdicts,
        "objectives_mean": rep["results"][pid]["objectives_mean"],
        "applied": False,
    }


# ----------------------------------------------------------------------------- next experiment
def _entropy(p: float) -> float:
    return 0.0 if p <= 0 or p >= 1 else -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def rank_next(mem: Memory, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expected information per cost = H(p) / runs, with p = stated prior probability of the positive outcome.

    Candidates whose hypothesis + conditions were already run are excluded (dedup). Priors are explicit
    judgement inputs written next to each candidate, not estimates produced by this function."""
    out = []
    for c in candidates:
        ck = condition_key(c["hypothesis_id"], c["conditions"])
        done = bool(mem.q("SELECT key FROM experiments WHERE key LIKE ?", (ck + ":%",)))
        bits = _entropy(c["prior_positive"])
        out.append(
            {**c, "already_run": done, "bits": round(bits, 3), "bits_per_100_runs": round(100 * bits / c["runs"], 3)}
        )
    return sorted(out, key=lambda c: (c["already_run"], -c["bits_per_100_runs"]))
