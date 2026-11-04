"""Deribit DVOL (BTC 30-day implied volatility index), hourly, from the public market-data API (no account).

Raw responses are stored per chunk with their sha256 (data/quant/deribit/), so the series is reproducible offline.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np

ROOT = Path("data/quant/deribit")
URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp={a}&end_timestamp={b}&resolution=3600"
HOUR = 3_600_000
CHUNK = 900 * HOUR  # below the API's per-request point limit


def fetch_dvol(start: str = "2021-03-01", end: str | None = None) -> dict[str, Any]:
    a = int(dt.datetime.fromisoformat(start).replace(tzinfo=dt.UTC).timestamp() * 1000)
    b_end = int(
        (dt.datetime.fromisoformat(end).replace(tzinfo=dt.UTC) if end else dt.datetime.now(dt.UTC)).timestamp() * 1000
    )
    ROOT.mkdir(parents=True, exist_ok=True)
    files = []
    with httpx.Client(timeout=60) as c:
        while a < b_end:
            b = min(a + CHUNK, b_end)
            dest = ROOT / f"dvol_{a}_{b}.json"
            if not dest.exists():
                r = c.get(URL.format(a=a, b=b))
                r.raise_for_status()
                dest.write_bytes(r.content)
                time.sleep(0.2)
            files.append({"file": dest.name, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()})
            a = b
    man = {"source": "deribit public get_volatility_index_data (BTC DVOL, 1h)", "files": files, "fetched_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}  # fmt: skip
    (ROOT / "manifest.json").write_text(json.dumps(man, indent=1))
    return {"chunks": len(files)}


def load_dvol() -> dict[str, np.ndarray]:
    rows: dict[int, float] = {}
    for p in sorted(ROOT.glob("dvol_*.json")):
        for t, _o, _h, _l, c in json.loads(p.read_text())["result"]["data"]:
            rows[int(t)] = float(c)
    t = np.array(sorted(rows), dtype=np.int64)
    return {"t": t, "close": np.array([rows[x] for x in t])}
