"""Reproducible baseline capture: commit, environment, test results, deterministic fingerprints, timing."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

BASELINE_DIR = Path("artifacts/baseline")


def _run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def capture_baseline(run_tests: bool = True) -> dict[str, Any]:
    from ..sim.config import SimConfig
    from ..sim.scenarios import scenario_at
    from ..sim.simulation import Simulation

    sha = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    dirty = bool(_run(["git", "status", "--porcelain"]).stdout.strip())
    out: dict[str, Any] = {
        "commit": sha,
        "dirty_worktree": dirty,
        "captured_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "uv_lock_sha256": sha256_file(Path("uv.lock")) if Path("uv.lock").exists() else None,
        "historical_files": sorted(p.name for p in Path("data/historical").glob("*.npy")),
    }
    if run_tests:
        r = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", "-o", "addopts="], timeout=3600)
        tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]
        m = re.search(r"(\d+) passed", tail)
        f = re.search(r"(\d+) failed", tail)
        out["tests"] = {
            "returncode": r.returncode,
            "summary": tail,
            "passed": int(m.group(1)) if m else 0,
            "failed": int(f.group(1)) if f else 0,
        }
    fps = {}
    for name in ("baseline", "btc_drop_5pct"):
        cfg = scenario_at(name, 300).apply(SimConfig(seed=42, duration_s=600))
        s = Simulation(cfg).run()
        s.exchange.check_invariants()
        fps[name] = {
            "fingerprint": s.fingerprint(),
            "trades": len(s.exchange.trades),
            "events": s.events_processed,
            "events_per_s": round(s.events_processed / s.wall_time_s),
        }
    out["sim_fingerprints_seed42_600s"] = fps
    d = BASELINE_DIR / (sha[:12] or "unknown")
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(out, indent=2))
    out["path"] = str(d / "manifest.json")
    return out


def verify_baseline(path: Path) -> dict[str, Any]:
    """Re-run the deterministic part of a baseline and compare fingerprints."""
    from ..sim.config import SimConfig
    from ..sim.scenarios import scenario_at
    from ..sim.simulation import Simulation

    ref = json.loads(path.read_text())
    res = {}
    for name, v in ref["sim_fingerprints_seed42_600s"].items():
        s = Simulation(scenario_at(name, 300).apply(SimConfig(seed=42, duration_s=600))).run()
        res[name] = {
            "expected": v["fingerprint"][:16],
            "actual": s.fingerprint()[:16],
            "match": s.fingerprint() == v["fingerprint"],
        }
    return res
