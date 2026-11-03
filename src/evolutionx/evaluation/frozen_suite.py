"""Frozen evaluation suite runner (PROTECTED). Prints a JSON result to stdout.

Executed inside the sandbox against either the candidate worktree or the
trusted baseline by pointing PYTHONPATH at the respective `src/` directory.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np


def main(suite_path: str, mode: str = "suite") -> None:
    import evolutionx
    from evolutionx.evaluation.metrics import run_metrics
    from evolutionx.sim.config import SimConfig
    from evolutionx.sim.scenarios import scenario_at
    from evolutionx.sim.simulation import Simulation

    suite = json.loads(Path(suite_path).read_text())
    if mode == "replay":  # deterministic replay test: same seed twice -> identical fingerprint
        cfg = SimConfig(seed=4242, duration_s=300)
        a, b = Simulation(cfg).run(), Simulation(cfg).run()
        print(json.dumps({"fingerprint_a": a.fingerprint(), "fingerprint_b": b.fingerprint(),
                          "identical": a.fingerprint() == b.fingerprint(), "module": evolutionx.__file__}))
        return
    if mode == "bench":
        rates = []
        for seed in (11, 12):
            t = time.perf_counter()
            s = Simulation(SimConfig(seed=seed, duration_s=600)).run()
            rates.append(s.events_processed / (time.perf_counter() - t))
        print(json.dumps({"events_per_s": float(np.median(rates)), "module": evolutionx.__file__}))
        return
    cases = []
    for case in suite["cases"]:
        d = suite["duration_s"]
        cfg = scenario_at(case["scenario"], d // 2).apply(SimConfig(seed=case["seed"], duration_s=d))
        sim = Simulation(cfg).run()
        sim.exchange.check_invariants()
        m = run_metrics(sim)
        cases.append({"seed": case["seed"], "scenario": case["scenario"], "realism": 1 - m["realism"]["distance"],
                      "market_dd_pct": m["max_drawdown_pct"], "spread_bps": m["spread_bps_median"],
                      "liquidations": m["liquidations"], "by_kind": m["by_kind"], "fingerprint": sim.fingerprint()})
    print(json.dumps({"suite": suite["name"], "cases": cases, "module": evolutionx.__file__}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "suite")
