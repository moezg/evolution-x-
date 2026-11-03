"""Protection policy for code-evolution candidates (PROTECTED).

Only strategy policy files are evolvable. The kernel, evaluation, evolution,
council, API, configuration, tests, frozen suites, CI and deployment files are
off-limits. This file itself is protected; the pipeline verifies hashes of all
protected files inside each candidate worktree before running anything.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ALLOWED_PREFIXES = ("src/evolutionx/strategies/",)
ALLOWED_SUFFIX = ".py"
PROTECTED_GLOBS = (
    "src/evolutionx/kernel/**/*.py",
    "src/evolutionx/evaluation/**/*.py",
    "src/evolutionx/evolution/**/*.py",
    "src/evolutionx/council/**/*.py",
    "src/evolutionx/api/**/*.py",
    "src/evolutionx/sim/**/*.py",
    "src/evolutionx/agents/**/*.py",
    "src/evolutionx/data/**/*.py",
    "src/evolutionx/*.py",
    "src/evolutionx/strategies/params.py",
    "tests/**/*.py",
    "evals/frozen/*",
    ".github/**/*",
    "Makefile",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    "docker-compose.yml",
)

FORBIDDEN_MODULES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "ctypes",
    "importlib",
    "http",
    "urllib",
    "requests",
    "httpx",
    "pickle",
    "marshal",
    "multiprocessing",
    "threading",
    "asyncio",
    "builtins",
    "pathlib",
    "io",
    "tempfile",
    "signal",
    "resource",
    "inspect",
    "gc",
    "code",
    "pty",
    "select",
}
FORBIDDEN_CALLS = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "globals",
    "locals",
    "vars",
    "setattr",
    "delattr",
    "getattr",
    "input",
    "breakpoint",
    "exit",
    "quit",
}


def path_violations(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        norm = str(Path(p))
        if ".." in Path(p).parts or norm.startswith("/"):
            out.append(f"{p}: path traversal / absolute path")
        elif not (norm.startswith(ALLOWED_PREFIXES) and norm.endswith(ALLOWED_SUFFIX)):
            out.append(f"{p}: outside evolvable zone {ALLOWED_PREFIXES}")
        elif norm == "src/evolutionx/strategies/params.py":
            out.append(f"{p}: parameter bounds are protected")
    return out


def security_scan(source: str, filename: str) -> list[str]:
    """AST scan for capabilities strategy code must never have."""
    try:
        tree = ast.parse(source, filename)
    except SyntaxError as e:
        return [f"{filename}: syntax error {e}"]
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in FORBIDDEN_MODULES:
                    issues.append(f"{filename}:{node.lineno}: forbidden import {a.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if node.level == 0 and mod in FORBIDDEN_MODULES:
                issues.append(f"{filename}:{node.lineno}: forbidden import from {node.module}")
            if node.level > 1 and (node.module or "").split(".")[0] not in ("agents",):
                issues.append(f"{filename}:{node.lineno}: relative import outside strategies/agents ({node.module})")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            issues.append(f"{filename}:{node.lineno}: forbidden call {node.func.id}()")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            issues.append(f"{filename}:{node.lineno}: dunder attribute access .{node.attr}")
        elif isinstance(node, ast.Global | ast.Nonlocal):
            issues.append(f"{filename}:{node.lineno}: global/nonlocal state mutation")
    return issues


def protected_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    for g in PROTECTED_GLOBS:
        files.update(p for p in root.glob(g) if p.is_file() and "__pycache__" not in p.parts)
    return sorted(files)


def protected_manifest(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected_files(root)}
