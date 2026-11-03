"""Process + filesystem isolation for untrusted candidate code (TRUSTED, protected).

Each run is a fresh process in new user/mount/network namespaces, chrooted into
a tmpfs root that contains ONLY:
  /usr /lib /lib64 /bin /sbin /etc   read-only binds (system + interpreter)
  /venv                               read-only bind of the project virtualenv
  /proj                               read-only bind of src/ (no data/, artifacts/, tests, vault)
  /in                                 read-only bind of the per-run input dir (candidate + permitted data)
  /out                                writable bind of the per-run output dir
  /tmp                                fresh 32 MiB tmpfs
No network interfaces (empty net namespace). RLIMIT_CPU/AS/FSIZE/NOFILE + wall
timeout with process-group kill. Environment scrubbed (no keys/tokens/proxies).

If namespaces/chroot are unavailable, `SandboxUnavailable` is raised and the
supervisor refuses to execute untrusted code (generation and review still work).
"""

from __future__ import annotations

import os
import resource
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]


class SandboxUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Limits:
    cpu_s: int = 300
    mem_bytes: int = 2 * 1024**3
    fsize_bytes: int = 256 * 1024**2
    nofile: int = 256
    wall_s: int = 600


SCRIPT = r"""
set -e
NR="$1"; IN="$2"; OUT="$3"; SRC="$4"; VENV="$5"; shift 5
mount -t tmpfs -o size=64m,mode=0755 tmpfs "$NR"
for d in usr lib lib64 bin sbin etc; do
  [ -e "/$d" ] || continue
  if [ -L "/$d" ]; then ln -s "$(readlink /$d)" "$NR/$d"; continue; fi
  mkdir -p "$NR/$d"; mount --rbind "/$d" "$NR/$d"; mount -o remount,bind,ro "$NR/$d"
done
mkdir -p "$NR/proj" "$NR/in" "$NR/out" "$NR/tmp" "$NR/dev" "$NR/venv"
mount --bind "$SRC" "$NR/proj"; mount -o remount,bind,ro "$NR/proj"
mount --bind "$VENV" "$NR/venv"; mount -o remount,bind,ro "$NR/venv"
mount --bind "$IN" "$NR/in"; mount -o remount,bind,ro "$NR/in"
mount --bind "$OUT" "$NR/out"
mount -t tmpfs -o size=32m tmpfs "$NR/tmp"
for n in null zero urandom random; do touch "$NR/dev/$n"; mount --bind "/dev/$n" "$NR/dev/$n"; done
exec chroot "$NR" "$@"
"""


def _probe() -> bool:
    if not (shutil.which("unshare") and shutil.which("chroot")):
        return False
    with tempfile.TemporaryDirectory() as d:
        nr = Path(d) / "nr"
        nr.mkdir()
        try:
            r = subprocess.run(
                ["unshare", "-rmn", "sh", "-c", f"mount -t tmpfs tmpfs {nr} && chroot / true"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False


AVAILABLE = _probe()


def isolation_report(limits: Limits) -> dict[str, Any]:
    return {
        "available": AVAILABLE,
        "namespaces": ["user", "mount", "network"],
        "chroot": True,
        "readonly": ["/usr", "/lib", "/etc", "/venv", "/proj (src only)", "/in"],
        "writable": ["/out", "chroot-private tmpfs (32 MiB)"],
        "hidden": ["data/", "data/vault/", "artifacts/", "tests/", "home"],
        "network": "none",
        "rlimits": {
            "cpu_s": limits.cpu_s,
            "as_bytes": limits.mem_bytes,
            "fsize_bytes": limits.fsize_bytes,
            "nofile": limits.nofile,
        },
        "wall_timeout_s": limits.wall_s,
        "env": "scrubbed",
    }


def run(module: str, args: list[str], in_dir: Path, out_dir: Path, limits: Limits = Limits()) -> dict[str, Any]:
    if not AVAILABLE:
        raise SandboxUnavailable("user/mount/network namespaces or chroot unavailable: untrusted execution disabled")
    in_dir, out_dir = in_dir.resolve(), out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    venv = Path(sys.prefix).resolve()
    py_rel = Path(sys.executable).resolve()
    pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_rel = Path(sysconfig.get_paths()["purelib"]).resolve().relative_to(venv)
    nr = Path(tempfile.mkdtemp(prefix="evox-root-"))

    def preexec() -> None:
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_s, limits.cpu_s))
        resource.setrlimit(resource.RLIMIT_AS, (limits.mem_bytes, limits.mem_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.fsize_bytes, limits.fsize_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (limits.nofile, limits.nofile))

    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": "/tmp",  # noqa: S108  # nosec B108 - private tmpfs inside the chroot
        "PYTHONHASHSEED": "0",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "PYTHONPATH": f"/proj:/venv/{site_rel}",
    }
    cmd = [
        "unshare",
        "-rmn",
        "sh",
        "-c",
        SCRIPT,
        "sbx",
        str(nr),
        str(in_dir),
        str(out_dir),
        str(REPO / "src"),
        str(venv),
        str(py_rel),
        "-S",
        "-m",
        module,
        *args,
    ]
    _ = pyver
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=preexec)
    try:
        out, err = p.communicate(timeout=limits.wall_s)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        out, err = p.communicate()
        rc, err = -9, (err or "") + "\nWALL TIMEOUT"
    finally:
        shutil.rmtree(nr, ignore_errors=True)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "returncode": rc,
        "stdout": out[-4000:],
        "stderr": err[-4000:],
        "wall_s": round(time.perf_counter() - t0, 3),
        "children_cpu_s_total": round(usage.ru_utime + usage.ru_stime, 2),
    }
