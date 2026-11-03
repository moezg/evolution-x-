"""Trusted research supervisor: persistent state machine, budgets, stop/resume, promotion.

Stages per task (persisted after each one, resumable, idempotent):
  OBSERVE -> HYPOTHESIZE -> PROTOCOL -> DESIGN -> ADMISSIBILITY -> EXPERIMENT -> EVALUATE -> CRITIQUE -> DECIDE
  -> ARCHIVE -> DONE

Trust boundary:
  * the generator only returns source text; it cannot write the registry, memory, journal or data
  * candidate code runs only inside research.sandbox (no data/, artifacts/, network; read-only inputs)
  * every number used in a decision is recomputed here from validated decision arrays
  * policy caps (evals/frozen/research_policy.json) bound every campaign; the supervisor never raises them
  * a STOP file halts the loop before the next stage; only an explicit human `resume --confirm` removes it
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import secrets
import time
from pathlib import Path
from typing import Any

import numpy as np

from . import sandbox
from .contract import static_check
from .critic import critique
from .evaluator import (
    CandidateFailure,
    DataSource,
    EvalConfig,
    RealData,
    data_sha,
    decide,
    evaluate,
    strip_private,
    validate_stage,
)
from .generator import LLMGenerator, OfflineGenerator, default_spec_from_v0
from .hypothesizer import build_task, choose, signature
from .journal import Journal
from .memory import Memory, now
from .registry import Registry

STAGES = [
    "OBSERVE",
    "HYPOTHESIZE",
    "PROTOCOL",
    "DESIGN",
    "ADMISSIBILITY",
    "EXPERIMENT",
    "EVALUATE",
    "CRITIQUE",
    "DECIDE",
    "ARCHIVE",
    "DONE",
]
POLICY = Path("evals/frozen/research_policy.json")
PROTOCOL = Path("evals/frozen/research_protocol.json")
V0 = Path("src/evolutionx/evolvable/tsmom_v0.py")


class Stopped(RuntimeError):
    pass


class BudgetExhausted(RuntimeError):
    pass


class Lab:
    """All persistent state of one research arm, rooted in one directory."""

    def __init__(self, root: Path, repo: Path | None = None) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.journal = Journal(root / "journal.jsonl")
        self.memory = Memory(root / "research.db")
        self.registry = Registry(root / "registry", self.journal, repo)
        self.stop_file = root / "STOP"
        (root / "candidates").mkdir(exist_ok=True)
        (root / "experiments").mkdir(exist_ok=True)


def _sha(b: bytes | str) -> str:
    return hashlib.sha256(b.encode() if isinstance(b, str) else b).hexdigest()


class Supervisor:
    def __init__(
        self,
        lab: Lab,
        data: DataSource | None = None,
        protocol: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
        generator: Any = None,
    ) -> None:
        self.lab = lab
        self.policy = policy or json.loads(POLICY.read_text())
        self.protocol = protocol or json.loads(PROTOCOL.read_text())
        self.protocol_sha = _sha(json.dumps(self.protocol, sort_keys=True))
        self._data = data
        self.generator: Any = generator or OfflineGenerator()

    # ---------------------------------------------------------------- campaign lifecycle
    def create_campaign(
        self, campaign_id: str, mode: str, selector: str, max_tasks: int, max_wall_s: int, seed: int = 0
    ) -> dict[str, Any]:
        if mode not in self.policy["modes"]:
            raise ValueError(f"unknown mode {mode}")
        caps = self.policy["caps"]
        budget = {
            "max_tasks": min(max_tasks, caps["max_tasks"]),
            "max_wall_s": min(max_wall_s, caps["max_wall_s"]),
            "max_llm_tokens": caps["max_llm_tokens"],
            "sandbox": caps["sandbox"],
        }
        llm_ok, llm_why = LLMGenerator().available()
        cfg = {
            "seed": seed,
            "generator": self.generator.name,
            "llm_available": llm_ok,
            "llm_status": llm_why,
            "sandbox": sandbox.isolation_report(self._limits()),
        }
        existing = self.lab.memory.q("SELECT * FROM campaigns WHERE id=?", (campaign_id,))
        if existing:
            return existing[0]
        self.lab.memory.x(
            "INSERT INTO campaigns VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                campaign_id,
                mode,
                selector,
                "created",
                json.dumps(budget),
                json.dumps({"tasks": 0, "wall_s": 0.0, "llm_tokens": 0, "sandbox_runs": 0}),
                json.dumps(cfg),
                now(),
                now(),
                None,
            ),
        )
        self.lab.journal.append(
            "human",
            "campaign_created",
            {"id": campaign_id, "mode": mode, "selector": selector, "budget": budget, "config": cfg},
        )
        return self.lab.memory.q("SELECT * FROM campaigns WHERE id=?", (campaign_id,))[0]

    def _limits(self) -> sandbox.Limits:
        c = self.policy["caps"]["sandbox"]
        return sandbox.Limits(cpu_s=c["cpu_s"], mem_bytes=c["mem_bytes"], wall_s=c["wall_s"])

    def _campaign(self, cid: str) -> dict[str, Any]:
        return self.lab.memory.q("SELECT * FROM campaigns WHERE id=?", (cid,))[0]

    def _data_for(self, mode: str) -> DataSource:
        if self._data is None:
            m = self.policy["modes"][mode]
            self._data = RealData(m["symbols"], m["dev_tail_bars"])
        return self._data

    def request_stop(self, actor: str, reason: str) -> None:
        self.lab.stop_file.write_text(json.dumps({"actor": actor, "reason": reason, "ts": now()}))
        self.lab.journal.append(actor, "stop_requested", {"reason": reason})

    def human_resume(self, actor: str, confirm: bool) -> None:
        if not confirm:
            raise PermissionError("resume after an explicit stop requires confirm=True from a human")
        self.lab.stop_file.unlink(missing_ok=True)
        self.lab.journal.append(actor, "stop_cleared", {})

    # ---------------------------------------------------------------- main loop
    def run(self, cid: str, max_steps: int = 10_000) -> dict[str, Any]:
        camp = self._campaign(cid)
        mode = camp["mode"]
        data = self._data_for(mode)
        self._ensure_champion()
        if camp["status"] not in ("search_space_exhausted",):
            self.lab.memory.x("UPDATE campaigns SET status='running', updated=? WHERE id=?", (now(), cid))
        steps = 0
        t_start = time.time()
        try:
            while steps < max_steps:
                self._check_stop()
                camp = self._campaign(cid)
                if camp["status"] == "search_space_exhausted":
                    break
                task = self._next_task(camp)
                if task is None:
                    self._finish(
                        cid,
                        "budget_exhausted" if camp["consumed"]["tasks"] >= camp["budget"]["max_tasks"] else "completed",
                    )
                    break
                self._check_budget(camp, t_start)
                self._step(camp, task, data)
                steps += 1
        except Stopped as e:
            self.lab.memory.x(
                "UPDATE campaigns SET status='stopped_by_user', stop_reason=?, updated=? WHERE id=?",
                (str(e), now(), cid),
            )
        except BudgetExhausted as e:
            self._finish(cid, "budget_exhausted", str(e))
        finally:
            c = self._campaign(cid)
            c["consumed"]["wall_s"] = round(c["consumed"]["wall_s"] + (time.time() - t_start), 2)
            self.lab.memory.x(
                "UPDATE campaigns SET consumed=?, updated=? WHERE id=?", (json.dumps(c["consumed"]), now(), cid)
            )
        return self.status(cid)

    def _finish(self, cid: str, status: str, reason: str | None = None) -> None:
        self.lab.memory.x(
            "UPDATE campaigns SET status=?, stop_reason=?, updated=? WHERE id=?", (status, reason, now(), cid)
        )
        self.lab.journal.append("supervisor", "campaign_end", {"id": cid, "status": status, "reason": reason})

    def _check_stop(self) -> None:
        if self.lab.stop_file.exists():
            raise Stopped(self.lab.stop_file.read_text())

    def _check_budget(self, camp: dict[str, Any], t_start: float) -> None:
        b, c = camp["budget"], camp["consumed"]
        if c["wall_s"] + (time.time() - t_start) > b["max_wall_s"]:
            raise BudgetExhausted("wall-clock budget exhausted")
        used_mb = sum(p.stat().st_size for p in self.lab.root.rglob("*") if p.is_file()) / 1e6
        if used_mb > self.policy["caps"]["max_disk_mb"]:
            raise BudgetExhausted(f"disk budget exhausted ({used_mb:.0f} MB)")

    def _next_task(self, camp: dict[str, Any]) -> dict[str, Any] | None:
        open_ = self.lab.memory.q(
            "SELECT * FROM tasks WHERE campaign_id=? AND status='open' ORDER BY seq LIMIT 1", (camp["id"],)
        )
        if open_:
            return open_[0]
        n = self.lab.memory.q("SELECT COUNT(*) n FROM tasks WHERE campaign_id=?", (camp["id"],))[0]["n"]
        if n >= camp["budget"]["max_tasks"]:
            return None
        tid = f"{camp['id']}-t{n + 1:03d}"
        pol = self.policy["task"]
        self.lab.memory.x(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                camp["id"],
                n + 1,
                "OBSERVE",
                "open",
                0,
                pol["max_attempts"],
                pol["deadline_s"],
                None,
                json.dumps({"started": time.time()}),
                None,
                now(),
                now(),
            ),
        )
        c = camp["consumed"]
        c["tasks"] = n + 1
        self.lab.memory.x("UPDATE campaigns SET consumed=? WHERE id=?", (json.dumps(c), camp["id"]))
        return self.lab.memory.q("SELECT * FROM tasks WHERE id=?", (tid,))[0]

    def _step(self, camp: dict[str, Any], task: dict[str, Any], data: DataSource) -> None:
        stage = task["stage"]
        ck = task["checkpoint"] or {}
        if time.time() - ck.get("started", time.time()) > task["deadline_s"]:
            self._close(task, ck, "failed", f"deadline {task['deadline_s']}s exceeded at {stage}")
            return
        try:
            ck = getattr(self, f"_s_{stage.lower()}")(camp, task, ck, data)
        except CandidateFailure as e:
            ck["rejection"] = {"gate": e.gate, "detail": e.detail}
            self._persist(task, "CRITIQUE", ck)
            self.lab.journal.append("evaluator", "candidate_rejected", {"task": task["id"], "gate": e.gate})
            return
        except (Stopped, BudgetExhausted, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:  # noqa: BLE001 - bounded retries, then fail the task (never loop forever)
            att = task["attempts"] + 1
            if att >= task["max_attempts"]:
                self._close(task, ck, "failed", f"{stage}: {e!r}"[:800])
            else:
                self.lab.memory.x(
                    "UPDATE tasks SET attempts=?, error=?, updated=? WHERE id=?",
                    (att, f"{stage}: {e!r}"[:800], now(), task["id"]),
                )
            return
        nxt = ck.pop("_next", STAGES[STAGES.index(stage) + 1])
        self._persist(task, nxt, ck)
        if os.environ.get("EVOX_TEST_CRASH_AFTER_STAGE") == stage:  # test hook: simulate a crash after a checkpoint
            raise SystemExit(f"simulated crash after {stage}")
        if nxt == "DONE":
            self.lab.memory.x("UPDATE tasks SET status='done', updated=? WHERE id=?", (now(), task["id"]))

    def _persist(self, task: dict[str, Any], stage: str, ck: dict[str, Any]) -> None:
        self.lab.memory.x(
            "UPDATE tasks SET stage=?, checkpoint=?, attempts=0, updated=? WHERE id=?",
            (stage, json.dumps(ck, default=str), now(), task["id"]),
        )

    def _close(self, task: dict[str, Any], ck: dict[str, Any], status: str, error: str) -> None:
        self.lab.memory.x(
            "UPDATE tasks SET status=?, stage='DONE', error=?, checkpoint=?, updated=? WHERE id=?",
            (status, error, json.dumps(ck, default=str), now(), task["id"]),
        )
        if ck.get("hypothesis_id"):
            self.lab.memory.x(
                "UPDATE hypotheses SET status=?, updated=? WHERE id=?", ("failed", now(), ck["hypothesis_id"])
            )
        self.lab.journal.append("supervisor", "task_failed", {"task": task["id"], "error": error})

    # ---------------------------------------------------------------- champion handling
    def _ensure_champion(self) -> None:
        if self.lab.registry.active() is None:
            self.lab.registry.bootstrap(V0.read_text(), "tsmom_v0")

    def _eval_cfg(self, mode: str) -> EvalConfig:
        return EvalConfig(self.protocol, self.policy["modes"][mode]["causality_checks"], self._limits())

    def _experiment_key(self, code_sha: str, data: DataSource, stage: str) -> str:
        return _sha(f"{code_sha}|{self.protocol_sha}|{data_sha(data)}|{','.join(data.symbols)}|{stage}")

    def _evaluate_cached(self, source: str, cid: str, data: DataSource, mode: str) -> dict[str, Any]:
        """Idempotent: identical (code, protocol, data) -> stored result, never re-run."""
        key = self._experiment_key(_sha(source), data, "eval")
        hit = self.lab.memory.get_experiment(key)
        dpath = self.lab.root / "experiments" / key[:24]
        if hit and (dpath / "decisions.npz").exists():
            z = np.load(dpath / "decisions.npz")
            hit["_dec"] = {(k.split("|")[0], int(k.split("|")[1])): z[k] for k in z.files}
            hit["_n_dev"] = {s: len(data.get(s, "development")["close"]) for s in data.symbols}
            hit["_full"] = {
                s: {
                    k: np.concatenate([data.get(s, "development")[k], data.get(s, "validation")[k]])
                    for k in data.get(s, "development")
                }
                for s in data.symbols
            }
            hit["_cached"] = True
            return hit
        rep = evaluate(source, cid, data, self._eval_cfg(mode), secret_seed=secrets.randbits(32))
        dpath.mkdir(parents=True, exist_ok=True)
        np.savez(dpath / "decisions.npz", **{f"{s}|{i}": v for (s, i), v in rep["_dec"].items()})
        self.lab.memory.put_experiment(key, cid, "eval", self.protocol_sha, data_sha(data), strip_private(rep))
        self.lab.journal.append(
            "evaluator",
            "experiment",
            {"key": key, "candidate": cid, "dev_oos_sharpe": rep["development"]["portfolio_oos_sharpe"]},
        )
        return rep

    def _champion(self, data: DataSource, mode: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        v, src = self.lab.registry.load_source()
        act = self.lab.registry.active()
        assert act is not None
        rep = self._evaluate_cached(src, f"champion-v{v}", data, mode)
        vkey = self._experiment_key(_sha(src), data, "validation")
        val = self.lab.memory.get_experiment(vkey)
        if val is None:
            val = validate_stage(rep, data, self._eval_cfg(mode))
            self.lab.memory.put_experiment(vkey, f"champion-v{v}", "validation", self.protocol_sha, data_sha(data), val)
        return {"version": v, "sha256": act["sha256"], "source": src}, rep, val

    # ---------------------------------------------------------------- stages
    def _s_observe(self, camp, task, ck, data):  # noqa: ANN001, ANN202
        parent, rep, _ = self._champion(data, camp["mode"])
        ck.update(
            parent_version=parent["version"],
            parent_sha=parent["sha256"],
            diagnostics=rep["diagnostics"],
            champion_dev_sharpe=rep["development"]["portfolio_oos_sharpe"],
        )
        return ck

    def _exploration_parents(self, data: DataSource, mode: str, champ: dict[str, Any]) -> list[dict[str, Any]]:
        """Champion first, then evaluated non-rejected candidates ranked by DEVELOPMENT OOS Sharpe only
        (validation results never feed back into generation)."""
        out = [{"id": f"v{champ['version']}", "kind": "champion", "sha": champ["sha256"], "dev_sharpe": None}]
        rows = self.lab.memory.q(
            "SELECT id, code_sha256, path, status FROM candidates WHERE status IN "
            "('refuted','inconclusive','promote','promoted')"
        )
        ranked = []
        for r in rows:
            key = self._experiment_key(r["code_sha256"], data, "eval")
            res = self.lab.memory.get_experiment(key)
            if res and r["code_sha256"] != champ["sha256"]:
                ranked.append(
                    {
                        "id": r["id"],
                        "kind": "candidate",
                        "sha": r["code_sha256"],
                        "path": r["path"],
                        "dev_sharpe": res["development"]["portfolio_oos_sharpe"],
                        "diagnostics": res["diagnostics"],
                    }
                )
        ranked.sort(key=lambda x: (-x["dev_sharpe"], x["id"]))
        return out + ranked

    def _s_hypothesize(self, camp, task, ck, data):  # noqa: ANN001, ANN202
        from .hypothesizer import ALL_OPS

        ext = ck.get("external")
        if ext is None and getattr(self.generator, "formulates_hypothesis", False):
            ext = self._llm_propose(camp, task, ck, data)
            ck["external"] = ext
        if ext is not None:
            ck.update(
                operator=ext["operator"],
                why=ext["why"],
                ranking=[],
                signature=signature(ck["parent_sha"], "external:" + ext["code_sha256"]),
                design_parent=f"v{ck['parent_version']}",
                design_parent_kind="champion",
                design_parent_sha=ck["parent_sha"],
                novelty=ext["novelty"],
            )
            return ck

        tested = {h["signature"] for h in self.lab.memory.q("SELECT signature FROM hypotheses")}
        rng = random.Random(f"{camp['config']['seed']}|{task['id']}")
        act = self.lab.registry.active()
        assert act is not None
        parents = self._exploration_parents(data, camp["mode"], {"version": act["version"], "sha256": act["sha256"]})
        open_parents = [p for p in parents if any(signature(p["sha"], op) not in tested for op in ALL_OPS)]
        if not open_parents:
            ck["_next"] = "DONE"
            ck["search_space_exhausted"] = True
            self.lab.journal.append("formulator", "search_space_exhausted", {"task": task["id"]})
            self._finish(camp["id"], "search_space_exhausted")
            return ck
        if camp["selector"] == "guided":
            parent = open_parents[0]
        else:
            parent = open_parents[rng.randrange(len(open_parents))]
        diag = ck["diagnostics"] if parent["kind"] == "champion" else parent["diagnostics"]
        op, why, ranking = choose(camp["selector"], diag, tested, parent["sha"], rng)
        sig = signature(parent["sha"], op)
        ck.update(
            operator=op,
            why=why,
            ranking=ranking,
            signature=sig,
            design_parent=parent["id"],
            design_parent_kind=parent["kind"],
            design_parent_sha=parent["sha"],
            design_parent_dev_sharpe=parent["dev_sharpe"],
            novelty=f"first test of operator {op} on parent {parent['id']} "
            f"({'active champion' if parent['kind'] == 'champion' else 'exploration parent ranked by development OOS Sharpe'})",
        )
        return ck

    def _s_protocol(self, camp, task, ck, data):  # noqa: ANN001, ANN202
        parent = {"version": ck["parent_version"], "sha256": ck["parent_sha"]}
        t = build_task(
            task["id"],
            camp["id"],
            ck["operator"],
            ck["why"],
            ck["ranking"],
            parent,
            ck["diagnostics"],
            self.protocol,
            self.protocol_sha,
            data_sha(data),
            camp["budget"],
            f"experiment:{self._experiment_key(ck['parent_sha'], data, 'eval')[:16]}",
            hypothesis=(ck.get("external") or {}).get("hypothesis"),
            extra={"provenance": {k: v for k, v in (ck.get("external") or {}).items() if k not in ("source",)}}
            if ck.get("external")
            else None,
        )
        hid = f"h-{task['id']}"
        self.lab.memory.x("UPDATE tasks SET task=? WHERE id=?", (json.dumps(t, default=str), task["id"]))
        self.lab.memory.x(
            "INSERT OR REPLACE INTO hypotheses VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                hid,
                ck["signature"],
                t["hypothesis"],
                ck["operator"],
                ck.get("design_parent", f"v{ck['parent_version']}"),
                None,
                "pending",
                json.dumps({}),
                ck["novelty"],
                now(),
                now(),
            ),
        )
        self.lab.journal.append(
            "formulator", "preregistered", {"task": task["id"], "sha256": t["preregistration_sha256"]}
        )
        ck.update(hypothesis_id=hid, preregistration_sha256=t["preregistration_sha256"])
        return ck

    def _s_design(self, camp, task, ck, data):  # noqa: ANN001, ANN202
        if ck.get("design_parent_kind", "champion") == "champion":
            _, src = self.lab.registry.load_source(ck["parent_version"])
            parent_id = f"v{ck['parent_version']}"
        else:
            src = (self.lab.root / "candidates" / ck["design_parent"] / "strategy.py").read_text()
            parent_id = ck["design_parent"]
        if _sha(src) != ck.get("design_parent_sha", ck["parent_sha"]):
            raise CandidateFailure("integrity", "design parent source does not match its recorded hash")
        ext = ck.get("external")
        if ext is not None:
            from .contract import static_check as _sc
            from .generator import Proposal, code_hash, diff

            esrc = ext["source"]
            if code_hash(esrc) != ext["code_sha256"]:
                raise CandidateFailure("integrity", "external source changed after pre-registration")
            cid = ext["candidate_id"]
            prop = Proposal(
                cid,
                parent_id,
                ext["operator"],
                ext["hypothesis"],
                {"external": True},
                esrc,
                diff(src, esrc, parent_id, cid),
                [f"src/evolutionx/evolvable/generated/{cid}.py"],
                "standard contract",
                ext["hypothesis"]["prediction"],
                ext.get("risk", "n/a"),
                {"sandbox": camp["budget"]["sandbox"]},
                "standard gates + frozen promotion rule",
                ext["generator"],
                ext["code_sha256"],
                _sc(esrc),
            )
        else:
            spec = self._spec_of(src)
            rng = random.Random(f"{camp['config']['seed']}|{task['id']}|design")
            prop = self.generator.propose(
                ck["operator"],
                {"id": parent_id, "spec": spec, "source": src},
                rng,
                {"sandbox": camp["budget"]["sandbox"]},
            )
        d = self.lab.root / "candidates" / prop.candidate_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "strategy.py").write_text(prop.source)
        (d / "patch.diff").write_text(prop.diff)
        pd = prop.as_dict()
        pd.pop("source")
        (d / "proposal.json").write_text(
            json.dumps(
                {**pd, "base_commit": _head(), "parent_version": ck["parent_version"], "design_parent": parent_id},
                indent=2,
            )
        )
        self.lab.memory.x(
            "INSERT OR IGNORE INTO candidates VALUES (?,?,?,?,?,?,?,?,?)",
            (
                prop.candidate_id,
                parent_id,
                prop.code_sha256,
                prop.generator,
                prop.operator,
                json.dumps(prop.spec),
                str(d / "strategy.py"),
                "designed",
                now(),
            ),
        )
        self.lab.memory.x("UPDATE hypotheses SET candidate_id=? WHERE id=?", (prop.candidate_id, ck["hypothesis_id"]))
        ck.update(
            candidate_id=prop.candidate_id, code_sha256=prop.code_sha256, files=prop.files, generator=prop.generator
        )
        return ck

    @staticmethod
    def _spec_of(src: str) -> dict[str, Any]:
        from .contract import literal_symbols

        return literal_symbols(src).get("SPEC") or default_spec_from_v0()

    def _s_admissibility(self, camp, task, ck, data):  # noqa: ANN001, ANN202
        d = self.lab.root / "candidates" / ck["candidate_id"]
        src = (d / "strategy.py").read_text()
        if _sha(src) != ck["code_sha256"]:
            raise CandidateFailure("integrity", "candidate source changed after design")
        act = self.lab.registry.active()
        assert act is not None
        if act["sha256"] != ck["parent_sha"]:
            raise CandidateFailure("stale_parent", "the champion changed after this task was designed; re-plan")
        bad = [f for f in ck["files"] if not any(f.startswith(p) for p in self.policy["evolvable_paths"])]
        if bad:
            raise CandidateFailure("scope", bad)
        issues = static_check(src)
        if issues:
            raise CandidateFailure("static_admissibility", issues)
        dup = self.lab.memory.q(
            "SELECT id, status FROM candidates WHERE code_sha256=? AND status!='designed'", (ck["code_sha256"],)
        )
        if dup:
            ck["duplicate_of"] = dup[0]["id"]
            ck["_next"] = "ARCHIVE"
        return ck

    def _s_experiment(self, camp, task, ck, data):  # noqa: ANN001, ANN202
        src = (self.lab.root / "candidates" / ck["candidate_id"] / "strategy.py").read_text()
        rep = self._evaluate_cached(src, ck["candidate_id"], data, camp["mode"])
        ck["experiment_key"] = self._experiment_key(ck["code_sha256"], data, "eval")
        ck["cached"] = bool(rep.get("_cached"))
        c = self._campaign(camp["id"])["consumed"]
        c["sandbox_runs"] = c.get("sandbox_runs", 0) + (
            0 if ck["cached"] else 2 + self._eval_cfg(camp["mode"]).causality_checks
        )
        self.lab.memory.x("UPDATE campaigns SET consumed=? WHERE id=?", (json.dumps(c), camp["id"]))
        for s, v in rep["development"]["per_symbol"].items():
            self.lab.memory.add_trial(ck["candidate_id"], "development", {"symbol": s}, "oos_sharpe", v["oos_sharpe"])
        return ck

    def _s_evaluate(self, camp, task, ck, data):  # noqa: ANN001, ANN202
        src = (self.lab.root / "candidates" / ck["candidate_id"] / "strategy.py").read_text()
        rep = self._evaluate_cached(src, ck["candidate_id"], data, camp["mode"])
        _, champ_rep, champ_val = self._champion(data, camp["mode"])
        cs, hs = rep["development"]["portfolio_oos_sharpe"], champ_rep["development"]["portfolio_oos_sharpe"]
        ck["screen"] = {"candidate_dev_oos_sharpe": cs, "champion_dev_oos_sharpe": hs, "passed": cs > hs}
        if not ck["screen"]["passed"]:
            ck["verdict"] = "refuted"
            ck["verdict_reason"] = "development walk-forward screen: candidate OOS Sharpe not above champion's"
            return ck
        vkey = self._experiment_key(ck["code_sha256"], data, "validation")
        val = self.lab.memory.get_experiment(vkey)
        if val is None:
            val = validate_stage(rep, data, self._eval_cfg(camp["mode"]))
            self.lab.memory.put_experiment(
                vkey, ck["candidate_id"], "validation", self.protocol_sha, data_sha(data), val
            )
            self.lab.memory.add_trial(ck["candidate_id"], "validation", {}, "portfolio_sharpe", val["portfolio_sharpe"])
        n_val = self.lab.memory.n_trials("validation")
        dec = decide(
            val, champ_val, n_val, self.lab.memory.trial_values("validation", "portfolio_sharpe"), self.protocol
        )
        ck["decision"] = dec
        ck["verdict"] = dec["verdict"]
        ck["validation_summary"] = {
            "candidate": val["portfolio_sharpe"],
            "champion": champ_val["portfolio_sharpe"],
            "candidate_mdd": val["portfolio_max_drawdown"],
            "champion_mdd": champ_val["portfolio_max_drawdown"],
        }
        return ck

    def _s_critique(self, camp, task, ck, data):  # noqa: ANN001, ANN202
        if "rejection" in ck:
            ck["verdict"] = "rejected"
            ck["critique"] = [
                {
                    "claim": f"Gate failed: {ck['rejection']['gate']}",
                    "metric_ref": "gates",
                    "value": str(ck["rejection"]["detail"])[:500],
                    "severity": "high",
                }
            ]
            ck["_next"] = "ARCHIVE"
            return ck
        src = (self.lab.root / "candidates" / ck["candidate_id"] / "strategy.py").read_text()
        rep = self._evaluate_cached(src, ck["candidate_id"], data, camp["mode"])
        _, champ_rep, _ = self._champion(data, camp["mode"])
        ck["critique"] = critique({}, rep, champ_rep, ck.get("decision"), self.lab.memory.n_trials("validation"))
        return ck

    def _s_decide(self, camp, task, ck, data):  # noqa: ANN001, ANN202
        auto = self.policy["modes"][camp["mode"]]["auto_activate"]
        if ck.get("verdict") == "promote":
            if auto:
                src = (self.lab.root / "candidates" / ck["candidate_id"] / "strategy.py").read_text()
                res = self.lab.registry.promote(
                    src,
                    ck["candidate_id"],
                    {"task": task["id"], "decision": ck["decision"]},
                    lambda s: self.smoke_check(s, data),
                )
                ck["activation"] = res
            else:
                ck["activation"] = {"activated": False, "reason": f"mode {camp['mode']} requires a human to activate"}
        return ck

    def _s_archive(self, camp, task, ck, data):  # noqa: ANN001, ANN202
        verdict = ck.get("verdict") or ("duplicate" if ck.get("duplicate_of") else "failed")
        hstatus = {
            "promote": "confirmed",
            "refuted": "refuted",
            "inconclusive": "inconclusive",
            "rejected": "failed",
            "duplicate": "inconclusive",
        }.get(verdict, "failed")
        ev = {
            k: ck.get(k)
            for k in ("experiment_key", "screen", "validation_summary", "rejection", "duplicate_of", "activation")
        }
        ev["decision_checks"] = (ck.get("decision") or {}).get("checks")
        self.lab.memory.x(
            "UPDATE hypotheses SET status=?, evidence=?, updated=? WHERE id=?",
            (hstatus, json.dumps(ev, default=str), now(), ck.get("hypothesis_id")),
        )
        cstatus = "promoted" if (ck.get("activation") or {}).get("activated") else verdict
        self.lab.memory.x("UPDATE candidates SET status=? WHERE id=?", (cstatus, ck.get("candidate_id")))
        self.lab.journal.append(
            "supervisor",
            "task_archived",
            {"task": task["id"], "verdict": verdict, "hypothesis_status": hstatus, "candidate": ck.get("candidate_id")},
        )
        ck["archived"] = {"verdict": verdict, "hypothesis_status": hstatus}
        return ck

    # ---------------------------------------------------------------- external authors (LLM, session import)
    def _llm_propose(self, camp, task, ck, data) -> dict[str, Any]:  # noqa: ANN001
        """One bounded call to the configured LLM connector. Caps come from the frozen policy."""
        cap = self.policy["llm"]["connectors"]["claude-cli"]
        c = self._campaign(camp["id"])["consumed"]
        if c.get("llm_calls", 0) >= cap["max_calls_per_campaign"]:
            raise BudgetExhausted("LLM call budget exhausted")
        if c.get("llm_cost_usd_equiv", 0.0) >= cap["max_cost_usd_equiv_per_campaign"]:
            raise BudgetExhausted("LLM cost budget exhausted")
        if c.get("llm_tokens", 0) >= camp["budget"]["max_llm_tokens"]:
            raise BudgetExhausted("LLM token budget exhausted")
        _, src = self.lab.registry.load_source(ck["parent_version"])
        tested = []
        for h in self.lab.memory.q("SELECT statement, operator, candidate_id FROM hypotheses"):
            exp = (
                self.lab.memory.q(
                    "SELECT result FROM experiments WHERE candidate_id=? AND stage='eval'", (h["candidate_id"],)
                )
                if h["candidate_id"]
                else []
            )
            dev = exp[0]["result"]["development"]["portfolio_oos_sharpe"] if exp else None
            tested.append({"idea": h["statement"], "operator": h["operator"], "development_oos_sharpe": dev})
        c["llm_calls"] = c.get("llm_calls", 0) + 1  # counted BEFORE the call: failed calls still consume quota
        self.lab.memory.x("UPDATE campaigns SET consumed=? WHERE id=?", (json.dumps(c), camp["id"]))
        prop, call = self.generator.propose_free(
            {"id": f"v{ck['parent_version']}", "source": src},
            ck["diagnostics"],
            tested[-30:],
            {"sandbox": camp["budget"]["sandbox"]},
        )
        c = self._campaign(camp["id"])["consumed"]
        c["llm_tokens"] = c.get("llm_tokens", 0) + call["tokens"]
        c["llm_cost_usd_equiv"] = round(c.get("llm_cost_usd_equiv", 0.0) + call["cost_usd_equiv"], 4)
        self.lab.memory.x("UPDATE campaigns SET consumed=? WHERE id=?", (json.dumps(c), camp["id"]))
        self.lab.journal.append(
            "generator",
            "llm_call",
            {k: call[k] for k in ("models", "tokens", "cost_usd_equiv", "wall_s", "session_id", "stop_reason")},
        )
        return {
            "candidate_id": prop.candidate_id,
            "source": prop.source,
            "code_sha256": prop.code_sha256,
            "hypothesis": prop.hypothesis,
            "operator": "llm_free_form",
            "generator": prop.generator,
            "why": "hypothesis formulated by the LLM from development-only diagnostics",
            "novelty": prop.spec.get("change_summary", ""),
            "llm_call": {k: v for k, v in call.items() if k != "text"},
            "exposure": ["parent source", "development diagnostics", "tested ideas with development screen results"],
            "provenance": "claude -p (official CLI, environment's existing authentication; may use plan quota)",
        }

    def import_candidate(
        self,
        campaign_id: str,
        mode: str,
        source: str,
        hypothesis: dict[str, Any],
        generator: str,
        provenance: str,
        exposure: list[str],
        risk: str = "",
    ) -> dict[str, Any]:
        """Queue a candidate written outside the lab (e.g. in an interactive Claude Code session) as one task."""
        from .generator import code_hash

        for k in ("statement", "mechanism", "alternatives", "prediction"):
            if not hypothesis.get(k):
                raise ValueError(f"hypothesis.{k} is required (pre-registration)")
        self.create_campaign(campaign_id, mode, "import", 1, self.policy["caps"]["max_wall_s"])
        camp = self._campaign(campaign_id)
        n = self.lab.memory.q("SELECT COUNT(*) n FROM tasks WHERE campaign_id=?", (campaign_id,))[0]["n"]
        if n:
            raise ValueError("campaign already has its imported task")
        sha = code_hash(source)
        ext = {
            "candidate_id": "sess-" + sha[:10],
            "source": source,
            "code_sha256": sha,
            "hypothesis": hypothesis,
            "operator": "session_import",
            "generator": generator,
            "why": "imported from an interactive session",
            "novelty": hypothesis.get("novelty", ""),
            "provenance": provenance,
            "exposure": exposure,
            "risk": risk,
        }
        pol = self.policy["task"]
        tid = f"{campaign_id}-t001"
        self.lab.memory.x(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                campaign_id,
                1,
                "OBSERVE",
                "open",
                0,
                pol["max_attempts"],
                pol["deadline_s"],
                None,
                json.dumps({"started": time.time(), "external": ext}),
                None,
                now(),
                now(),
            ),
        )
        c = camp["consumed"]
        c["tasks"] = 1
        self.lab.memory.x("UPDATE campaigns SET consumed=? WHERE id=?", (json.dumps(c), campaign_id))
        self.lab.journal.append(
            "human",
            "candidate_imported",
            {"task": tid, "code_sha256": sha, "generator": generator, "provenance": provenance, "exposure": exposure},
        )
        return {"task": tid, "candidate_id": ext["candidate_id"], "code_sha256": sha}

    def inherit_validation_trials(self, other_roots: list[Path]) -> int:
        """Count validation trials run in other labs on the same split, so the DSR's N is honest."""
        n = 0
        for r in other_roots:
            other = Memory(r / "research.db")
            for t in other.q("SELECT candidate_id, params, metric, value FROM trials WHERE split='validation'"):
                cid = f"inherited:{r.name}:{t['candidate_id']}"
                if not self.lab.memory.q("SELECT id FROM trials WHERE candidate_id=?", (cid,)):
                    self.lab.memory.add_trial(
                        cid, "validation", t["params"] if isinstance(t["params"], dict) else {}, t["metric"], t["value"]
                    )
                    n += 1
        self.lab.journal.append(
            "supervisor", "inherited_validation_trials", {"from": [str(r) for r in other_roots], "n": n}
        )
        return n

    # ---------------------------------------------------------------- post-activation control
    def smoke_check(self, source: str, data: DataSource) -> dict[str, Any]:
        """Post-activation technical control of the NEWLY ACTIVE version (re-loaded, hash-verified, by the registry):
        sandboxed decisions on (a) the last 2000 validation bars and (b) a canary of edge cases never used for
        evaluation (constant prices, +/-15-20% spikes, zero volume); decisions must be valid and the accounting
        identity must hold. Any failure -> automatic rollback."""
        from ..backtest.engine import CostModel, run_backtest
        from .contract import literal_symbols
        from .evaluator import sandbox_decisions
        from .synthetic import canary

        s = data.symbols[0]
        seg = {k: v[-2000:] for k, v in data.get(s, "validation").items()}
        lit = literal_symbols(source)
        decs, _ = sandbox_decisions(
            source,
            [("smoke", seg, lit["PARAMS"]), ("canary", canary(), lit["PARAMS"])],
            EvalConfig(self.protocol, 0, self._limits()),
            "smoke",
        )
        r1 = run_backtest(seg, decs[0], CostModel())
        r2 = run_backtest(canary(), decs[1], CostModel())
        return {
            "ok": True,
            "bars": len(seg["close"]),
            "canary_bars": len(r2.equity),
            "final_equity": float(r1.equity[-1]),
        }

    # ---------------------------------------------------------------- reporting
    def status(self, cid: str) -> dict[str, Any]:
        camp = self._campaign(cid)
        tasks = self.lab.memory.q(
            "SELECT id, seq, stage, status, error FROM tasks WHERE campaign_id=? ORDER BY seq", (cid,)
        )
        hyps = self.lab.memory.q("SELECT status, COUNT(*) n FROM hypotheses GROUP BY status")
        return {
            "campaign": camp,
            "tasks": tasks,
            "hypotheses": {h["status"]: h["n"] for h in hyps},
            "active": self.lab.registry.active(),
            "journal": self.lab.journal.verify(),
            "stop_requested": self.lab.stop_file.exists(),
        }


def _head() -> str:
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        return "unknown"
