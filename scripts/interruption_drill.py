"""Real interruption drill for one prospective issuance (no synthetic data, no backfill).

Runs `evox ops tick` every 60 s (cron mode) from an unrelated directory. When a tick starts writing forecasts for
the target origin, the tick is killed with SIGKILL after the first new ledger line(s) and before completion. The
containerised daemon is then restarted and must finish the issuance after the lease expires, without duplicates
and without altering the lines already written. If the origin's deadline passes first, that failure is recorded.
Evidence: docs/evidence/ops/interruption_drill.json
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "artifacts/forecast/ledger.jsonl"
OUT = REPO / "docs/evidence/ops/interruption_drill.json"
EVOX = str(REPO / ".venv/bin/evox")
ORIGIN = sys.argv[1] if len(sys.argv) > 1 else "2026-11-05"
EXPECTED_NEW = int(sys.argv[2]) if len(sys.argv) > 2 else 37  # 32 champion-family + 5 activated challenger targets
log: list[dict] = []


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def lines() -> list[str]:
    return LEDGER.read_text().splitlines()


def note(**kw) -> None:
    log.append({"utc": now(), **kw})
    OUT.write_text(json.dumps({"origin": ORIGIN, "expected_new_forecasts": EXPECTED_NEW, "log": log}, indent=1))
    print(json.dumps(log[-1]), flush=True)


def docker(*a: str) -> str:
    return subprocess.run(["docker", *a], capture_output=True, text=True).stdout.strip()


deadline = dt.datetime.fromisoformat(ORIGIN).replace(tzinfo=dt.UTC)
base = lines()
note(event="drill_start", ledger_lines=len(base), container=docker("stop", "-t", "90", "evox-scheduler") or "stopped")
killed_at = None
while dt.datetime.now(dt.UTC) < deadline and killed_at is None:
    p = subprocess.Popen([EVOX, "ops", "tick"], cwd="/tmp", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # noqa: S108 - deliberately an unrelated cwd
    while p.poll() is None:
        n = len(lines())
        if len(base) < n < len(base) + EXPECTED_NEW:
            os.kill(p.pid, signal.SIGKILL)
            p.wait()
            killed_at = n
            break
        time.sleep(0.05)
    out = (p.stdout.read() if p.stdout else "")[-2000:]
    if killed_at is None and len(lines()) >= len(base) + EXPECTED_NEW:
        note(event="issuance_completed_without_interruption", tick_output=out, ledger_lines=len(lines()))
        break
    if killed_at is None:
        time.sleep(60)
if killed_at is not None:
    partial = lines()
    note(event="tick_killed_sigkill_mid_issuance", ledger_lines=killed_at, new_lines_before_kill=killed_at - len(base),
         partial_sha256=hashlib.sha256("\n".join(partial).encode()).hexdigest())  # fmt: skip
    note(event="daemon_restarted", container=docker("start", "evox-scheduler"))
    t0 = time.time()
    while len(lines()) < len(base) + EXPECTED_NEW and dt.datetime.now(dt.UTC) < deadline:
        time.sleep(20)
    final = lines()
    ids = [json.loads(x)["data"].get("id") for x in final if json.loads(x)["event"] == "forecast"]
    keys = [
        (json.loads(x)["data"]["origin_ms"], json.loads(x)["data"]["target"], json.loads(x)["data"]["model"])
        for x in final
        if json.loads(x)["event"] == "forecast"
    ]
    verify = subprocess.run([str(REPO / ".venv/bin/python"), "-c", "from evolutionx.forecast.ledger import ForecastLedger; import json; print(json.dumps(ForecastLedger().verify()))"], cwd=str(REPO), capture_output=True, text=True).stdout.strip()  # fmt: skip
    note(event="resume_result", seconds_to_complete_after_restart=round(time.time() - t0), ledger_lines=len(final),
         new_forecasts=len(final) - len(base), duplicates_by_id=len(ids) - len(set(ids)), duplicates_by_key=len(keys) - len(set(keys)),
         prefix_unchanged=final[:killed_at] == partial[:killed_at], verify=verify,
         completed_before_deadline=len(final) >= len(base) + EXPECTED_NEW)  # fmt: skip
elif dt.datetime.now(dt.UTC) >= deadline:
    note(
        event="deadline_passed_without_issuance", ledger_lines=len(lines()), container=docker("start", "evox-scheduler")
    )
else:
    note(event="drill_end", container=docker("start", "evox-scheduler"))
