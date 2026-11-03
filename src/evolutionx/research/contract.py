"""Candidate contract + static admissibility checks (defence in depth; NOT the isolation boundary).

The isolation boundary is the sandbox process (mount/network namespaces, read-only
inputs, rlimits). These checks reject obviously out-of-scope code early and give
clear diagnostics.
"""

from __future__ import annotations

import ast
import contextlib
import itertools
from typing import Any

ALLOWED_IMPORTS = {"math", "numpy", "__future__"}
FORBIDDEN_NAMES = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "input",
    "breakpoint",
    "exit",
    "quit",
    "memoryview",
    "help",
}
FORBIDDEN_ATTRS = {
    "load",
    "save",
    "savez",
    "savez_compressed",
    "fromfile",
    "tofile",
    "memmap",
    "loadtxt",
    "savetxt",
    "genfromtxt",
    "fromregex",
    "lib",
    "ctypeslib",
    "DataSource",
    "testing",
    "f2py",
}
MAX_SOURCE_BYTES = 20_000
MAX_GRID = 4
EVOLVABLE_PREFIX = "src/evolutionx/evolvable/"


def static_check(source: str) -> list[str]:
    issues: list[str] = []
    if len(source.encode()) > MAX_SOURCE_BYTES:
        issues.append("source too large")
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"syntax error: {e}"]
    names: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            names[node.targets[0].id] = node.value
        elif isinstance(node, ast.FunctionDef):
            names[node.name] = node
    for req in ("NAME", "PARAMS", "PARAM_GRID", "signal"):
        if req not in names:
            issues.append(f"missing required symbol {req}")
    sig = names.get("signal")
    if isinstance(sig, ast.FunctionDef) and [a.arg for a in sig.args.args] != ["view", "p"]:
        issues.append("signal must have signature signal(view, p)")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    issues.append(f"line {node.lineno}: import {a.name} not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                issues.append(f"line {node.lineno}: import from {node.module} not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            issues.append(f"line {node.lineno}: forbidden name {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            issues.append(f"line {node.lineno}: file/system access via .{node.attr} not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            issues.append(f"line {node.lineno}: private/dunder attribute .{node.attr}")
        elif isinstance(node, ast.Global | ast.Nonlocal):
            issues.append(f"line {node.lineno}: global state")
    try:
        grid = ast.literal_eval(names["PARAM_GRID"]) if "PARAM_GRID" in names else {}
        params = ast.literal_eval(names["PARAMS"]) if "PARAMS" in names else {}
        if not isinstance(grid, dict) or not isinstance(params, dict):
            raise ValueError
        if len(param_sets(params, grid)) > MAX_GRID:
            issues.append(f"PARAM_GRID expands to more than {MAX_GRID} configurations")
    except (ValueError, SyntaxError):
        issues.append("PARAMS and PARAM_GRID must be literal dicts")
    return issues


def param_sets(params: dict[str, Any], grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = sorted(grid)
    out = []
    for combo in itertools.product(*(grid[k] for k in keys)) if keys else [()]:
        p = dict(params)
        p.update(dict(zip(keys, combo, strict=True)))
        out.append(p)
    return out


def literal_symbols(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    out: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            with contextlib.suppress(ValueError):
                out[node.targets[0].id] = ast.literal_eval(node.value)
    return out
