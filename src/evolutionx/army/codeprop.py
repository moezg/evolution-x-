"""Engineering-division code proposals, checked in isolated git worktrees; never merged automatically.

A proposal is a unified diff plus a rationale. Pipeline:
  1. protected-path guard (frozen policies, kernel, evaluator, sandbox, ledgers, holdouts, approval code) -> blocked
  2. temporary `git worktree` at HEAD (outside the repo), `git apply --check` then apply
  3. ruff check + targeted pytest inside the worktree, with timeouts
  4. status 'pending_human_review' (checks passed) or 'checks_failed'; the worktree is removed
Merging requires a human. Agents cannot change this module's guard (army/policy.py is itself protected).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .policy import touches_protected
from .store import Store

ROOT = Path("artifacts/army/proposals")


def paths_in_diff(diff: str) -> list[str]:
    return sorted(
        {m for m in re.findall(r"^\+\+\+ b/(\S+)", diff, re.M)} | {m for m in re.findall(r"^--- a/(\S+)", diff, re.M)}
    )


def _run(cmd: list[str], cwd: Path, timeout: int = 600, env: dict[str, str] | None = None) -> dict[str, Any]:
    full_env = {**os.environ, **(env or {})}
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False, env=full_env)  # noqa: S603  # nosec B603 - fixed argv, no shell
    return {"cmd": " ".join(cmd[:4]), "rc": r.returncode, "tail": (r.stdout + r.stderr)[-1500:]}


def submit(store: Store, author_role: str, title: str, rationale: str, diff: str, tests: list[str]) -> dict[str, Any]:
    pid = "p" + hashlib.sha256(diff.encode()).hexdigest()[:10]
    d = ROOT / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "patch.diff").write_text(diff)
    touched = paths_in_diff(diff)
    meta: dict[str, Any] = {
        "id": pid,
        "author_role": author_role,
        "title": title,
        "rationale": rationale,
        "files": touched,
        "tests": tests,
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "merged": False,
    }
    blocked = touches_protected(touched)
    if blocked:
        meta.update(
            status="blocked_protected_path",
            blocked_paths=blocked,
            checks=[],
            note="escalated to human: touches protected evaluation/security code",
        )
    else:
        meta.update(_check_in_worktree(diff, tests))
    (d / "proposal.json").write_text(json.dumps(meta, indent=1))
    store.log(author_role, "code_proposal", {k: meta[k] for k in ("id", "title", "status", "files")})
    store.edge(f"proposal:{pid}", "authored_by", f"role:{author_role}", {"status": meta["status"]})
    return meta


def _check_in_worktree(diff: str, tests: list[str]) -> dict[str, Any]:
    repo = Path.cwd()
    wt = Path(tempfile.mkdtemp(prefix="evox-proposal-"))
    shutil.rmtree(wt)
    checks = [_run(["git", "worktree", "add", "--detach", str(wt), "HEAD"], repo, 120)]
    try:
        if checks[-1]["rc"] != 0:
            return {"status": "checks_failed", "checks": checks}
        (wt / "proposal.diff").write_text(diff)
        checks.append(_run(["git", "apply", "--check", "proposal.diff"], wt, 60))
        if checks[-1]["rc"] == 0:
            checks.append(_run(["git", "apply", "proposal.diff"], wt, 60))
            venv = repo / ".venv" / "bin"
            checks.append(_run([str(venv / "ruff"), "check", "src", "tests"], wt, 300))
            if tests:
                # the worktree's own src/ must shadow the editable install that points at the main checkout
                checks.append(
                    _run(
                        [str(venv / "pytest"), "-q", "-p", "no:cacheprovider", *tests],
                        wt,
                        900,
                        {"PYTHONPATH": str(wt / "src")},
                    )
                )
        ok = all(c["rc"] == 0 for c in checks)
        return {"status": "pending_human_review" if ok else "checks_failed", "checks": checks}
    finally:
        _run(["git", "worktree", "remove", "--force", str(wt)], repo, 120)


def proposals() -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(ROOT.glob("*/proposal.json"))]
