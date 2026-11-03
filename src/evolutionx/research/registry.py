"""Version registry for experimental champions (TRUSTED). Only the supervisor calls `promote`/`rollback`.

Layout (artifacts/research/registry, never mounted in sandboxes):
  versions/v<N>/strategy.py   exact accepted source
  versions/v<N>/meta.json     candidate id, sha256, parent version, evidence, git commit on experimental branch
  active.json                 pointer {version, sha256} replaced atomically (os.replace)
Activation takes effect on the next run: `evox backtest --strategy champion` and the next research task both
load the active version (after re-verifying its hash).

Git: each version is also committed (git plumbing, no checkout) to the local branch `experimental/research`.
`main` and any remote are never touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .journal import Journal
from .memory import now

BRANCH = "refs/heads/experimental/research"


class RegistryError(RuntimeError):
    pass


class Registry:
    def __init__(self, root: Path, journal: Journal, repo: Path | None = None) -> None:
        self.root, self.j, self.repo = root, journal, repo
        (root / "versions").mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- reads
    def active(self) -> dict[str, Any] | None:
        p = self.root / "active.json"
        return json.loads(p.read_text()) if p.exists() else None

    def versions(self) -> list[dict[str, Any]]:
        out = []
        for d in sorted(self.root.glob("versions/v*"), key=lambda p: int(p.name[1:])):
            out.append(json.loads((d / "meta.json").read_text()))
        return out

    def load_source(self, version: int | None = None) -> tuple[int, str]:
        act = self.active()
        if act is None:
            raise RegistryError("no active version")
        v = version if version is not None else act["version"]
        d = self.root / "versions" / f"v{v}"
        src = (d / "strategy.py").read_text()
        meta = json.loads((d / "meta.json").read_text())
        if hashlib.sha256(src.encode()).hexdigest() != meta["sha256"]:
            raise RegistryError(f"hash mismatch for v{v}: stored source was modified")
        return v, src

    # ---------------------------------------------------------------- writes (supervisor only)
    def _write_version(self, source: str, meta: dict[str, Any]) -> int:
        existing = [int(p.name[1:]) for p in self.root.glob("versions/v*")]
        v = max(existing, default=-1) + 1
        d = self.root / "versions" / f"v{v}"
        d.mkdir(parents=True)
        (d / "strategy.py").write_text(source)
        meta = {**meta, "version": v, "sha256": hashlib.sha256(source.encode()).hexdigest(), "created": now()}
        meta["git_commit"] = self._git_commit(source, v, meta)
        (d / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
        return v

    def _set_active(self, v: int, reason: str) -> None:
        meta = json.loads((self.root / "versions" / f"v{v}" / "meta.json").read_text())
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".active-")
        with os.fdopen(fd, "w") as f:
            json.dump(
                {
                    "version": v,
                    "sha256": meta["sha256"],
                    "candidate_id": meta.get("candidate_id"),
                    "since": now(),
                    "reason": reason,
                },
                f,
            )
        os.replace(tmp, self.root / "active.json")  # atomic pointer swap
        with (self.root / "history.jsonl").open("a") as f:
            f.write(json.dumps({"ts": now(), "active": v, "reason": reason}) + "\n")

    def bootstrap(self, source: str, candidate_id: str) -> int:
        if self.active() is not None:
            return self.active()["version"]  # type: ignore[index]
        v = self._write_version(
            source, {"candidate_id": candidate_id, "parent_version": None, "reason": "initial frozen champion"}
        )
        self._set_active(v, "bootstrap")
        self.j.append("supervisor", "registry_bootstrap", {"version": v, "candidate_id": candidate_id})
        return v

    def promote(
        self, source: str, candidate_id: str, evidence: dict[str, Any], smoke_check: Callable[[str], dict[str, Any]]
    ) -> dict[str, Any]:
        prev = self.active()
        if prev is None:
            raise RegistryError("bootstrap first")
        v = self._write_version(
            source,
            {
                "candidate_id": candidate_id,
                "parent_version": prev["version"],
                "reason": "won frozen promotion rule",
                "evidence": evidence,
            },
        )
        self._set_active(v, f"promote {candidate_id}")
        self.j.append(
            "supervisor", "activate", {"version": v, "previous": prev["version"], "candidate_id": candidate_id}
        )
        # post-activation control: reload from the registry (hash-verified) and run a short check
        try:
            _, loaded = self.load_source()
            check = smoke_check(loaded)
            ok = bool(check.get("ok"))
        except Exception as e:  # noqa: BLE001 - any failure triggers rollback
            check, ok = {"ok": False, "error": repr(e)[:500]}, False
        if not ok:
            self._set_active(prev["version"], f"automatic rollback: post-activation check failed for v{v}")
            self.j.append("supervisor", "rollback", {"from": v, "to": prev["version"], "cause": check})
            return {"activated": False, "version": v, "rolled_back_to": prev["version"], "check": check}
        return {"activated": True, "version": v, "previous": prev["version"], "check": check}

    def rollback(self, actor: str, reason: str) -> dict[str, Any]:
        act = self.active()
        if act is None:
            raise RegistryError("nothing active")
        meta = json.loads((self.root / "versions" / f"v{act['version']}" / "meta.json").read_text())
        parent = meta.get("parent_version")
        if parent is None:
            raise RegistryError("active version has no parent")
        self._set_active(parent, f"manual rollback by {actor}: {reason}")
        self.j.append(actor, "rollback", {"from": act["version"], "to": parent, "reason": reason})
        return {"active": parent, "from": act["version"]}

    # ---------------------------------------------------------------- git (local experimental branch only)
    def _git_commit(self, source: str, v: int, meta: dict[str, Any]) -> str | None:
        if self.repo is None:
            return None

        def git(*a: str, inp: str | None = None, env: dict[str, str] | None = None) -> str:
            return subprocess.run(
                ["git", *a],
                cwd=self.repo,
                input=inp,
                capture_output=True,
                text=True,
                check=True,
                env={**os.environ, **(env or {})},
                timeout=30,
            ).stdout.strip()

        try:
            blob = git("hash-object", "-w", "--stdin", inp=source)
            parent = subprocess.run(
                ["git", "rev-parse", "--verify", "-q", BRANCH],
                cwd=self.repo,
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            fd, idx = tempfile.mkstemp(prefix="evox-idx-")
            os.close(fd)
            Path(idx).unlink()
            env = {"GIT_INDEX_FILE": idx}
            if parent:
                git("read-tree", parent, env=env)
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},src/evolutionx/evolvable/champion.py", env=env)
            git(
                "update-index",
                "--add",
                "--cacheinfo",
                f"100644,{git('hash-object', '-w', '--stdin', inp=json.dumps(meta, indent=2, default=str))},"
                f"src/evolutionx/evolvable/champion_meta.json",
                env=env,
            )
            tree = git("write-tree", env=env)
            msg = f"experimental champion v{v} ({meta.get('candidate_id')})\n\n{meta.get('reason')}"
            args = ["commit-tree", tree, "-m", msg] + (["-p", parent] if parent else [])
            commit = git(
                *args,
                env={
                    "GIT_AUTHOR_NAME": "evox-supervisor",
                    "GIT_AUTHOR_EMAIL": "supervisor@evox.local",
                    "GIT_COMMITTER_NAME": "evox-supervisor",
                    "GIT_COMMITTER_EMAIL": "supervisor@evox.local",
                },
            )
            git("update-ref", BRANCH, commit, *([parent] if parent else []))
            Path(idx).unlink(missing_ok=True)
            return commit
        except (subprocess.CalledProcessError, OSError):
            return None
