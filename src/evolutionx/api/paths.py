"""Repository-root anchoring for the API.

All artifact paths in the project are relative to the repository root (artifacts/, evals/frozen/, data/). A server
started from another directory used to answer 404 on every artifact route (diagnosed from the /api/forecast/evolution
404 report). The app now anchors its working directory to the repository root (or $EVOX_ROOT) at import time.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_REPO = Path(__file__).resolve().parents[3]


def repo_root() -> Path:
    env = os.environ.get("EVOX_ROOT")
    if env:
        return Path(env).resolve()
    return PACKAGE_REPO


def ensure_repo_cwd() -> dict[str, str | bool]:
    root = repo_root()
    before = Path.cwd()
    changed = False
    if (root / "evals" / "frozen").is_dir() and before.resolve() != root:
        os.chdir(root)
        changed = True
    return {"root": str(root), "cwd_before": str(before), "changed": changed}


def health() -> dict[str, object]:
    cwd = Path.cwd()
    dirs = ("artifacts/forecast", "artifacts/observatory", "artifacts/research", "artifacts/army", "evals/frozen")
    return {"cwd": str(cwd), "root": str(repo_root()), "present": {d: (cwd / d).is_dir() for d in dirs}}
