"""Logically append-only, hash-chained research journal (TRUSTED).

Each line: {"seq", "ts", "actor", "event", "data", "prev", "hash"} with hash = sha256(prev + canonical body).
`verify()` detects any edit, deletion or reordering. The file lives under artifacts/, which is never mounted
inside candidate sandboxes. It is NOT tamper-proof against the machine's owner; it is tamper-EVIDENT.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    def _last(self) -> tuple[int, str]:
        last = None
        with self.path.open("rb") as f:
            for line in f:
                if line.strip():
                    last = line
        if last is None:
            return 0, "genesis"
        d = json.loads(last)
        return d["seq"], d["hash"]

    def append(self, actor: str, event: str, data: dict[str, Any]) -> dict[str, Any]:
        with _lock:
            seq, prev = self._last()
            body = {
                "seq": seq + 1,
                "ts": dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds"),
                "actor": actor,
                "event": event,
                "data": data,
                "prev": prev,
            }
            canon = json.dumps(body, sort_keys=True, default=str)
            body["hash"] = hashlib.sha256((prev + canon).encode()).hexdigest()
            with self.path.open("a") as f:
                f.write(json.dumps(body, sort_keys=True, default=str) + "\n")
            return body

    def verify(self) -> dict[str, Any]:
        prev, n = "genesis", 0
        with self.path.open() as f:
            for i, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                d = json.loads(line)
                h = d.pop("hash")
                if d["prev"] != prev or d["seq"] != i:
                    return {"ok": False, "broken_at": i, "reason": "chain/sequence mismatch"}
                if hashlib.sha256((prev + json.dumps(d, sort_keys=True, default=str)).encode()).hexdigest() != h:
                    return {"ok": False, "broken_at": i, "reason": "hash mismatch"}
                prev, n = h, i
        return {"ok": True, "entries": n, "head": prev}

    def tail(self, n: int = 100) -> list[dict[str, Any]]:
        lines = self.path.read_text().splitlines()
        return [json.loads(x) for x in lines[-n:] if x.strip()]
