"""Code-change proposal -> isolated worktree -> sandboxed gates -> auditable report -> human decision.

Nothing here merges or deploys. An approved proposal leaves a reviewed branch
and a report; merging into `main` is a manual, human action.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...council.engineer import propose_code
from ...council.schemas import CodeProposal
from ..archive import Archive, now
from . import policy, sandbox

REPO = Path.cwd()
WT_DIR = Path("artifacts/worktrees")
PROP_DIR = Path("artifacts/proposals")
SUITE = Path("evals/frozen/suite.json")


def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=60).stdout


def _gate(name: str, passed: bool, detail: Any, duration_s: float = 0.0) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "duration_s": duration_s, "detail": detail}


def propose_and_evaluate(
    proposal_key: str | None = None,
    archive: Archive | None = None,
    progress: Callable[[str], None] = lambda _m: None,
    proposal: CodeProposal | None = None,
) -> dict[str, Any]:
    A = archive or Archive()
    tried = [r["id"].split("--")[0] for r in A.query("SELECT id FROM proposals")]
    prop = proposal or propose_code(proposal_key, tried)
    base_sha = _git("rev-parse", "HEAD").strip()
    pid = f"{prop.key}--{base_sha[:7]}--{now().replace(':', '').replace('-', '')}"
    branch = f"evo/{pid}"
    files = sorted({e.path for e in prop.edits})
    report: dict[str, Any] = {
        "id": pid,
        "key": prop.key,
        "summary": prop.title,
        "rationale": prop.rationale,
        "hypothesis": prop.hypothesis,
        "base_sha": base_sha,
        "gates": [],
        "sandbox": sandbox.isolation_report(sandbox.Limits()),
    }
    A.execute(
        "INSERT INTO proposals (id, created, title, author, target_files, branch, status, report, decision) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            pid,
            now(),
            prop.title,
            "evolution-engineer",
            json.dumps(files),
            branch,
            "gates_running",
            json.dumps(report),
            None,
        ),
    )
    A.audit("evolution-engineer", "propose_code", pid, {"files": files, "title": prop.title})

    def finish(status: str) -> dict[str, Any]:
        # worktree directories are disposable; the candidate branch (and its commit) is kept for review
        for key in ("worktree", "baseline_worktree"):
            if report.get(key):
                subprocess.run(
                    ["git", "worktree", "remove", "--force", report[key]],
                    cwd=REPO,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )
        out = PROP_DIR / pid
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
        (out / "report.md").write_text(render(report, status, branch))
        A.execute(
            "UPDATE proposals SET status=?, report=?, branch=? WHERE id=?",
            (status, json.dumps(report, default=str), branch if status != "policy_rejected" else None, pid),
        )
        A.audit(
            "pipeline",
            f"proposal_{status}",
            pid,
            {"failed_gates": [g["name"] for g in report["gates"] if not g["passed"]]},
        )
        progress(f"finished: {status}")
        return {"id": pid, "status": status, "report": report}

    # Gate 1: protection policy (before any file is touched)
    viol = policy.path_violations(files)
    report["gates"].append(_gate("protection_policy", not viol, viol or "all edits inside evolvable zone"))
    if viol:
        return finish("policy_rejected")

    # Isolated worktree on a fresh branch
    progress("creating isolated worktree")
    wt = (WT_DIR / pid).resolve()
    WT_DIR.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "-q", "-b", branch, str(wt), base_sha)
    report["worktree"] = str(wt)
    try:
        for e in prop.edits:
            f = wt / e.path
            src = f.read_text()
            if src.count(e.search) != 1:
                raise ValueError(f"search text must occur exactly once in {e.path} (found {src.count(e.search)})")
            f.write_text(src.replace(e.search, e.replace, 1))
    except (ValueError, OSError) as err:
        report["gates"].append(_gate("apply_patch", False, str(err)))
        return finish("gates_failed")
    _git("add", "-A", cwd=wt)
    _git(
        "-c",
        "user.name=evolution-engineer",
        "-c",
        "user.email=evolution@evolutionx.local",
        "commit",
        "-q",
        "-m",
        f"[evolution candidate] {prop.title}\n\nHypothesis: {prop.hypothesis}\nProposal-Id: {pid}",
        cwd=wt,
    )
    report["diff"] = _git("diff", f"{base_sha}..HEAD", cwd=wt)
    report["gates"].append(_gate("apply_patch", True, f"{len(prop.edits)} edit(s) applied on branch {branch}"))

    # Trusted baseline = detached worktree at the same base commit (independent of local uncommitted edits)
    base_wt = (WT_DIR / f"{pid}--baseline").resolve()
    _git("worktree", "add", "-q", "--detach", str(base_wt), base_sha)
    report["baseline_worktree"] = str(base_wt)

    # Gate 2: protected-file integrity inside the worktree (vs. the base commit)
    main_m, wt_m = policy.protected_manifest(base_wt), policy.protected_manifest(wt)
    tampered = sorted(k for k in set(main_m) | set(wt_m) if main_m.get(k) != wt_m.get(k))
    report["gates"].append(
        _gate("protected_integrity", not tampered, tampered or f"{len(main_m)} protected files verified")
    )
    if tampered:
        return finish("gates_failed")

    # Gate 3: static security scan (AST, trusted code, outside sandbox) + bandit (sandboxed)
    issues = [i for p in files for i in policy.security_scan((wt / p).read_text(), p)]
    py = sys.executable
    venv_bin = Path(py).parent
    bandit = sandbox.run([str(venv_bin / "bandit"), "-q", "-ll", *files], wt)
    report["gates"].append(
        _gate(
            "security_scan",
            not issues and bandit["returncode"] == 0,
            {"ast_issues": issues, "bandit_rc": bandit["returncode"], "bandit": bandit["stdout"][-2000:]},
            bandit["duration_s"],
        )
    )

    # Gate 4: formatting + lint (sandboxed)
    lint = sandbox.run([str(venv_bin / "ruff"), "check", "--no-cache", *files], wt)
    fmt = sandbox.run([str(venv_bin / "ruff"), "format", "--check", "--no-cache", *files], wt)
    report["gates"].append(
        _gate(
            "lint_format",
            lint["returncode"] == 0 and fmt["returncode"] == 0,
            {"ruff_check": lint["stdout"][-2000:], "ruff_format": fmt["stdout"][-2000:]},
            lint["duration_s"] + fmt["duration_s"],
        )
    )
    if issues:
        return finish("gates_failed")  # never execute code that failed the security scan

    # Gate 5: unit + integration + property tests (frozen tests/ from protected tree)
    progress("running test suite in sandbox")
    tests = sandbox.run(
        [py, "-S", "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "-m", "not slow", "tests"], wt, wt / "src"
    )
    report["gates"].append(_gate("tests", tests["returncode"] == 0, tests["stdout"][-1500:], tests["duration_s"]))

    # Gate 6: deterministic replay
    progress("deterministic replay")
    rp = sandbox.run(
        [py, "-S", "-m", "evolutionx.evaluation.frozen_suite", str(base_wt / SUITE), "replay"], wt, wt / "src"
    )
    rj = _json(rp["stdout"])
    report["gates"].append(
        _gate(
            "deterministic_replay",
            bool(rj and rj["identical"] and str(wt) in rj["module"]),
            rj or rp["stderr"][-1500:],
            rp["duration_s"],
        )
    )

    # Gate 7: performance regression benchmark (candidate vs trusted baseline, same sandbox)
    progress("benchmark")
    suite = json.loads((base_wt / SUITE).read_text())
    tol = suite["tolerances"]
    bc = _json(
        sandbox.run(
            [py, "-S", "-m", "evolutionx.evaluation.frozen_suite", str(base_wt / SUITE), "bench"], wt, wt / "src"
        )["stdout"]
    )
    bb = _json(
        sandbox.run(
            [py, "-S", "-m", "evolutionx.evaluation.frozen_suite", str(base_wt / SUITE), "bench"],
            base_wt,
            base_wt / "src",
        )["stdout"]
    )
    bench_ok = bool(bc and bb and bc["events_per_s"] >= (1 - tol["events_per_s_drop_max"]) * bb["events_per_s"])
    report["benchmark"] = {
        "candidate_events_per_s": bc and bc["events_per_s"],
        "baseline_events_per_s": bb and bb["events_per_s"],
        "max_drop": tol["events_per_s_drop_max"],
    }
    report["gates"].append(_gate("performance_benchmark", bench_ok, report["benchmark"]))

    # Gate 8: frozen evaluation suite vs trusted baseline
    progress("frozen evaluation suite")
    fc = _json(
        sandbox.run([py, "-S", "-m", "evolutionx.evaluation.frozen_suite", str(base_wt / SUITE)], wt, wt / "src")[
            "stdout"
        ]
    )
    fb = _json(
        sandbox.run(
            [py, "-S", "-m", "evolutionx.evaluation.frozen_suite", str(base_wt / SUITE)], base_wt, base_wt / "src"
        )["stdout"]
    )
    frozen_ok, comparison = False, {}
    if fc and fb:
        cr = sum(c["realism"] for c in fc["cases"]) / len(fc["cases"])
        br = sum(c["realism"] for c in fb["cases"]) / len(fb["cases"])
        cdd = max(c["market_dd_pct"] for c in fc["cases"])
        bdd = max(c["market_dd_pct"] for c in fb["cases"])
        comparison = {
            "realism_candidate": cr,
            "realism_baseline": br,
            "market_dd_candidate": cdd,
            "market_dd_baseline": bdd,
            "per_case": [
                {
                    "scenario": a["scenario"],
                    "seed": a["seed"],
                    "candidate": {k: a[k] for k in ("realism", "market_dd_pct", "spread_bps", "liquidations")},
                    "baseline": {k: b[k] for k in ("realism", "market_dd_pct", "spread_bps", "liquidations")},
                    "by_kind_return_pct": {
                        k: {
                            "candidate": a["by_kind"][k]["mean_return_pct"],
                            "baseline": b["by_kind"][k]["mean_return_pct"],
                        }
                        for k in a["by_kind"]
                    },
                }
                for a, b in zip(fc["cases"], fb["cases"], strict=True)
            ],
        }
        frozen_ok = (cr >= br - tol["realism_drop_max"]) and (cdd <= bdd + tol["market_drawdown_increase_max_pct"])
    report["frozen_eval"] = comparison
    report["gates"].append(
        _gate(
            "frozen_eval_suite",
            frozen_ok,
            {"suite": suite["name"], **{k: v for k, v in comparison.items() if k != "per_case"}},
        )
    )
    return finish("awaiting_approval" if all(g["passed"] for g in report["gates"]) else "gates_failed")


def _json(s: str) -> dict[str, Any] | None:
    for line in reversed(s.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def record_decision(pid: str, decision: str, reviewer: str, comment: str, archive: Archive | None = None) -> dict:
    A = archive or Archive()
    rows = A.query("SELECT * FROM proposals WHERE id=?", (pid,))
    if not rows:
        raise KeyError(f"proposal {pid} not found")
    p = rows[0]
    if decision == "approve" and p["status"] != "awaiting_approval":
        raise ValueError(f"cannot approve a proposal in status {p['status']}")
    if p["status"] in ("approved", "rejected"):
        raise ValueError("decision already recorded")
    status = "approved" if decision == "approve" else "rejected"
    d = {
        "decision": decision,
        "reviewer": reviewer,
        "comment": comment,
        "ts": now(),
        "merge_instructions": (
            f"Human action required: review then `git merge --no-ff {p['branch']}` "
            "on a local clone. Nothing has been merged or deployed automatically."
        )
        if status == "approved"
        else None,
    }
    A.execute("UPDATE proposals SET status=?, decision=? WHERE id=?", (status, json.dumps(d), pid))
    A.audit(reviewer, f"proposal_{status}", pid, {"comment": comment})
    return {"id": pid, "status": status, "decision": d}


def render(r: dict[str, Any], status: str, branch: str) -> str:
    lines = [
        f"# Code-evolution proposal `{r['id']}`",
        "",
        f"**{r['summary']}**",
        "",
        f"- Status: **{status}**",
        f"- Branch: `{branch}` (base `{r['base_sha'][:10]}`)",
        f"- Hypothesis: {r['hypothesis']}",
        f"- Rationale: {r['rationale']}",
        "",
        "## Gates",
        "",
        "| gate | result | time (s) |",
        "|---|---|---|",
    ]
    for g in r["gates"]:
        lines.append(f"| {g['name']} | {'PASS' if g['passed'] else 'FAIL'} | {g['duration_s']} |")
    lines += ["", "## Sandbox", "", "```json", json.dumps(r["sandbox"], indent=2), "```", ""]
    if r.get("frozen_eval"):
        fe = r["frozen_eval"]
        lines += [
            "## Frozen evaluation suite",
            "",
            f"- realism: candidate {fe['realism_candidate']:.3f} vs baseline {fe['realism_baseline']:.3f}",
            f"- worst market drawdown: candidate {fe['market_dd_candidate']:.2f}% vs baseline "
            f"{fe['market_dd_baseline']:.2f}%",
            "",
        ]
    if r.get("diff"):
        lines += ["## Diff", "", "```diff", r["diff"], "```", ""]
    lines += ["Approval only records a decision. Merge to `main` is a manual human step; nothing auto-deploys.", ""]
    return "\n".join(lines)
