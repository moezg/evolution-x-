"""Minimal background job manager with quotas (no external queue needed for v1)."""

from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..evolution.archive import now


class JobManager:
    def __init__(self, max_concurrent: int = 2) -> None:
        self.pool = ThreadPoolExecutor(max_workers=max_concurrent)
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.max_queued = 8  # resource quota

    def submit(self, kind: str, fn: Callable[..., Any], params: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            active = [j for j in self.jobs.values() if j["status"] in ("queued", "running")]
            if len(active) >= self.max_queued:
                raise RuntimeError("job quota exceeded; wait for running jobs to finish")
            jid = f"{kind}-{uuid.uuid4().hex[:8]}"
            job = {"id": jid, "kind": kind, "params": params, "status": "queued", "created": now(),
                   "progress": [], "result": None, "error": None}
            self.jobs[jid] = job

        def progress(msg: str) -> None:
            job["progress"].append(msg)
            job["progress"] = job["progress"][-50:]

        def run() -> None:
            job["status"] = "running"
            try:
                job["result"] = fn(progress=progress, **params)
                job["status"] = "finished"
            except Exception as e:  # noqa: BLE001 - surface any failure to the UI
                job["status"] = "failed"
                job["error"] = f"{e}\n{traceback.format_exc()[-1500:]}"
            job["finished"] = now()

        self.pool.submit(run)
        return job

    def list(self) -> list[dict[str, Any]]:
        return [{k: v for k, v in j.items() if k != "result"} for j in sorted(self.jobs.values(), key=lambda j: j["created"],
                                                                                reverse=True)]
