"""Re-read archived tasks and attach development-layer diagnostics + outcome classes (append-only enrichment).

Uses the decision arrays already cached for each experiment (no new sandbox runs, no validation/final access).
Existing fields are never modified; `classification` and `behaviour_v2` are added and the action is journaled.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ..backtest.engine import CostModel
from ..data.datasets import protocol
from .behaviour import behaviour
from .contract import literal_symbols, param_sets
from .evaluator import RealData
from .lessons import classify, mechanism_result
from .memory import now
from .supervisor import DEFAULT_MECHANISM_TESTS, Lab


def _diag(lab: Lab, key: str, source: str, ds: RealData) -> dict[str, Any] | None:
    p = lab.root / "experiments" / key[:24] / "decisions.npz"
    if not p.exists():
        return None
    z = np.load(p)
    lit = literal_symbols(source)
    ps = param_sets(lit["PARAMS"], lit["PARAM_GRID"])
    idx = next((i for i, x in enumerate(ps) if x == lit["PARAMS"]), 0)
    out = {}
    for s in ds.symbols:
        dev = ds.get(s, "development")
        out[s] = behaviour(dev, z[f"{s}|{idx}"][: len(dev["close"])], CostModel.from_protocol(protocol(), s))
        out[s]["param_index"] = idx
    return out


def reclassify(root: Path) -> list[dict[str, Any]]:
    lab = Lab(root)
    ds = RealData()
    champ = lab.memory.q(
        "SELECT key, candidate_id FROM experiments WHERE candidate_id LIKE 'champion-v0' AND stage='eval'"
    )
    _, v0 = lab.registry.load_source(0)
    parent_diag = _diag(lab, champ[0]["key"], v0, ds) if champ else None
    cache: dict[str, Any] = {}
    rows = []
    for t in lab.memory.q("SELECT * FROM tasks WHERE status IN ('done','failed') ORDER BY seq"):
        ck = t["checkpoint"] or {}
        cand_diag = None
        dev = None
        if ck.get("experiment_key") and ck.get("candidate_id"):
            src_p = lab.root / "candidates" / ck["candidate_id"] / "strategy.py"
            if src_p.exists():
                cand_diag = cache.get(ck["experiment_key"]) or _diag(lab, ck["experiment_key"], src_p.read_text(), ds)
                cache[ck["experiment_key"]] = cand_diag
            exp = lab.memory.get_experiment(ck["experiment_key"])
            dev = (exp or {}).get("development")
        parent = parent_diag
        if ck.get("design_parent_kind") == "candidate":
            # the comparison that defines the mechanism is against the design parent
            prow = lab.memory.q(
                "SELECT key FROM experiments WHERE candidate_id=? AND stage='eval'", (ck["design_parent"],)
            )
            psrc = lab.root / "candidates" / ck["design_parent"] / "strategy.py"
            if prow and psrc.exists():
                parent = cache.get(prow[0]["key"]) or _diag(lab, prow[0]["key"], psrc.read_text(), ds)
                cache[prow[0]["key"]] = parent
        test = (ck.get("external") or {}).get("mechanism_test") or DEFAULT_MECHANISM_TESTS.get(ck.get("operator", ""))
        ck2 = dict(ck)
        if cand_diag and parent:
            ck2["mechanism"] = mechanism_result(test, cand_diag, parent)
        cl = classify(ck2, cand_diag, parent, dev)
        cl["reclassified_utc"] = now()
        cl["method"] = "reclassify-v1 (cached decisions, yearly-segment behaviour, development only)"
        ck["classification"] = cl
        if cand_diag:
            ck["behaviour_v2"] = {"candidate": cand_diag, "parent": parent}
            ck["mechanism_v2"] = ck2.get("mechanism")
        lab.memory.x("UPDATE tasks SET checkpoint=? WHERE id=?", (json.dumps(ck, default=str), t["id"]))
        if ck.get("hypothesis_id"):
            lab.memory.x(
                "UPDATE hypotheses SET classification=? WHERE id=?", (json.dumps(cl, default=str), ck["hypothesis_id"])
            )
        rows.append(
            {
                "task": t["id"],
                "operator": ck.get("operator"),
                "class": cl["class"],
                "validation_verdict": ck.get("verdict"),
            }
        )
    lab.journal.append("human:operator", "reclassified", {"n": len(rows), "method": "reclassify-v1"})
    return rows
