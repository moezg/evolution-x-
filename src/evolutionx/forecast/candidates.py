"""Selection history of every forecast-feature candidate ever tested (P4 accountability).

Built from the test registry (all F-FCAST* families, every run), the challenger activation list and the forecast
ledger. Retrospective (exposed-data) and prospective evidence are reported in separate fields and never mixed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path("artifacts/forecast/candidate_history.json")
AMENDMENT = {"F-FCAST": "quant protocol v1 (F-FCAST)", "F-FCAST-2": "amendment 5", "F-FCAST-3": "amendment 7", "F-FCAST-4": "amendment 8", "F-FCAST-5": "amendment 9"}  # fmt: skip


def build() -> dict[str, Any]:
    from ..quant.stats import TestRegistry
    from .challengers import state
    from .ledger import ForecastLedger

    rows = [r for r in TestRegistry().rows() if r["family"].startswith("F-FCAST")]
    st = state()
    active = set(st.get("_active", []))
    led = ForecastLedger()
    fc, rs = led.forecasts(), led.resolutions()
    issued: dict[str, list[int]] = {}
    for fid, e in fc.items():
        d = e["data"]
        if d["model"].startswith("CH:"):
            v = issued.setdefault(f"{d['model']}:{d['target']}", [0, 0])
            v[0] += 1
            v[1] += int(fid in rs)
    cands: dict[str, dict[str, Any]] = {}
    for r in sorted(rows, key=lambda x: x["created"] or ""):
        _, feat, tgt = r["hypothesis"].split(":")
        key = f"CH:{feat}:{tgt}"
        c = cands.setdefault(
            key,
            {
                "feature": feat,
                "target": tgt,
                "family": r["family"],
                "amendment": AMENDMENT.get(r["family"]),
                "runs": [],
            },
        )
        c["runs"].append({"run_id": r["run_id"], "created": r["created"], "screen_effect": r["effect"], "ci": [r["ci_lo"], r["ci_hi"]], "p": r["p"], "p_adj": r["p_adj"], "adj_method": r["adj_method"], "status": r["status"]})  # fmt: skip
    for key, c in cands.items():
        last = c["runs"][-1]
        c["retrospective_status"] = last["status"]
        c["activated"] = key in active
        c["retired_targets"] = st.get(key.rsplit(":", 1)[0], {}).get("retired_targets", [])
        n, nres = issued.get(key, [0, 0])
        c["prospective"] = {
            "issued": n,
            "resolved": nres,
            "label": "independent evidence (separate from the retrospective fields)",
        }
    fams = sorted({c["family"] for c in cands.values()})
    out = {
        "candidates_tested": len(cands),
        "by_family": {f: sum(1 for c in cands.values() if c["family"] == f) for f in fams},
        "passed_retrospective": sorted(
            k for k, c in cands.items() if str(c["retrospective_status"]).startswith("candidate")
        ),
        "activated": sorted(active),
        "search_disclosure": f"{len(cands)} feature-target candidates were searched on previously exposed data; challengers were selected from this search, so their retrospective numbers are optimistic. Only prospective evidence is independent.",
        "candidates": cands,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=str))
    return out
