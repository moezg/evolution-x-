"""Hand-written candidate sources for mechanism tests (not research results)."""

GOOD = """from __future__ import annotations

NAME = "good_trend"
PARAMS = {"n": 24}
PARAM_GRID = {"n": [24]}


def signal(view, p):
    c = view.close(int(p["n"]) + 1)
    if len(c) <= int(p["n"]):
        return 0.0
    return 0.5 if c[-1] > c[0] else -0.5
"""

ANTI = GOOD.replace("good_trend", "anti_trend").replace(
    "return 0.5 if c[-1] > c[0] else -0.5", "return -0.5 if c[-1] > c[0] else 0.5"
)

FRAGILE = """from __future__ import annotations

import numpy as np

NAME = "fragile_trend"
PARAMS = {"n": 24}
PARAM_GRID = {"n": [24]}


def signal(view, p):
    c = view.close(int(p["n"]) + 1)
    if len(c) <= int(p["n"]):
        return 0.0
    z = (c[-1] - c[0]) / float(np.std(c))  # no guard: NaN on constant prices
    return float(np.clip(z, -0.5, 0.5))
"""

LEAKY_PROBE = """from __future__ import annotations

NAME = "probe"
PARAMS = {"n": 1}
PARAM_GRID = {"n": [1]}


def signal(view, p):
    return 0.0
"""

ESCAPE = r"""
import json, os, socket, glob
NAME = "escape"; PARAMS = {{"n": 1}}; PARAM_GRID = {{"n": [1]}}
_probe = {{}}
def _try(name, fn):
    try:
        _probe[name] = ("ALLOWED", str(fn())[:200])
    except Exception as e:
        _probe[name] = ("blocked", type(e).__name__)
_try("write_registry", lambda: open(os.environ.get("TARGET_REGISTRY", "{registry}"), "w").write("{{}}"))
_try("read_vault", lambda: open("{vault}", "rb").read(10))
_try("list_data", lambda: os.listdir("{data_dir}"))
_try("write_src", lambda: open("/proj/evolutionx/research/evaluator.py", "a").write("#x"))
_try("write_tests", lambda: open("{tests}", "a").write("#x"))
_try("network", lambda: socket.create_connection(("1.1.1.1", 80), timeout=2))
_try("secret_env", lambda: os.environ["EVOX_FAKE_SECRET"])
_try("home", lambda: os.listdir("/home"))
_try("symlink_out", lambda: os.symlink("{registry}", "/out/dec_0.npy"))
open("/out/forged_report.json", "w").write(json.dumps({{"net_sharpe": 99.0, "verdict": "promote"}}))
open("/out/probe.json", "w").write(json.dumps(_probe))
def signal(view, p):
    return 0.0
"""
