"""Resource-constrained, network-isolated subprocess sandbox (PROTECTED).

Isolation layers (each reported in the proposal's audit record):
  * network: `unshare --user --net` (empty network namespace: no interfaces) when available
  * resources: RLIMIT_CPU, RLIMIT_AS (memory), RLIMIT_FSIZE, wall-clock timeout
  * environment: scrubbed env (no API keys / tokens / proxies), HOME in a temp dir
  * code: candidate code is imported only from the worktree via PYTHONPATH
"""

from __future__ import annotations

import os
import resource
import shutil
import subprocess
import sysconfig
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    cpu_s: int = 900
    mem_bytes: int = 6 * 1024**3
    fsize_bytes: int = 512 * 1024**2
    wall_s: int = 900


def _unshare_ok() -> bool:
    if not shutil.which("unshare"):
        return False
    try:
        return subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


UNSHARE = _unshare_ok()


def isolation_report(limits: Limits) -> dict[str, object]:
    return {
        "network_namespace": UNSHARE,
        "rlimit_cpu_s": limits.cpu_s,
        "rlimit_as_bytes": limits.mem_bytes,
        "rlimit_fsize_bytes": limits.fsize_bytes,
        "wall_timeout_s": limits.wall_s,
        "env": "scrubbed",
        "secrets_exposed": False,
    }


def run(cmd: list[str], cwd: Path, pythonpath: Path | None = None, limits: Limits = Limits()) -> dict[str, object]:
    def preexec() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_s, limits.cpu_s))
        resource.setrlimit(resource.RLIMIT_AS, (limits.mem_bytes, limits.mem_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.fsize_bytes, limits.fsize_bytes))
        os.setsid()

    home = tempfile.mkdtemp(prefix="evox-sbx-")
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": home,
        "PYTHONHASHSEED": "0",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "RUFF_CACHE_DIR": f"{home}/ruff",
        "XDG_CACHE_HOME": home,
    }
    if pythonpath is not None:
        # with `python -S` there is no site processing (and no editable-install import hook), so the
        # candidate's src/ is guaranteed to shadow the trusted tree; deps come from an explicit path.
        env["PYTHONPATH"] = f"{pythonpath}:{sysconfig.get_paths()['purelib']}"
    full = (["unshare", "-rn"] if UNSHARE else []) + cmd
    t = time.perf_counter()
    try:
        p = subprocess.run(
            full,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=limits.wall_s,
            preexec_fn=preexec,
            check=False,
        )  # noqa: PLW1509
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = -9, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "TIMEOUT"
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return {
        "cmd": " ".join(cmd),
        "returncode": rc,
        "stdout": out[-20_000:],
        "stderr": err[-8_000:],
        "duration_s": round(time.perf_counter() - t, 2),
    }
