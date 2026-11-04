"""Market data for quantitative / calendar / event research (protocol: evals/frozen/quant_protocol_v1.json).

* Binance spot BTCUSDT 1h and 1d, official monthly archives with published checksums (data/quant/binance/).
* FRED daily series (DGS10, SP500, DFEDTARU) as CSV, stored with retrieval time and sha256 (data/quant/fred/).
Nothing here reads the reserved SOL/BNB vault or the strategy-research splits.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from ..data.datasets import _fetch, _ms, _rows

ROOT = Path("data/quant")
SPOT = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/{iv}/BTCUSDT-{iv}-{m}.zip"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
START, END = "2017-08", "2026-10"
HOUR, DAY = 3_600_000, 86_400_000


def _months(a: str, b: str) -> list[str]:
    y, m = map(int, a.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fetch_btc(interval: str = "1d") -> dict[str, Any]:
    files = []
    with httpx.Client(timeout=60) as c:
        for m in _months(START, END):
            dest = ROOT / "binance" / interval / f"BTCUSDT-{interval}-{m}.zip"
            files.append({"month": m, **_fetch(c, SPOT.format(iv=interval, m=m), dest)})
    man = {"interval": interval, "fetched_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "files": files}
    (ROOT / "binance" / f"manifest_{interval}.json").write_text(json.dumps(man, indent=1))
    return {
        "interval": interval,
        "files": len(files),
        "all_checksums_verified": all(f["checksum_verified"] for f in files),
    }


def fetch_fred(series: tuple[str, ...] = ("DGS10", "SP500", "DFEDTARU")) -> dict[str, Any]:
    out = {}
    (ROOT / "fred").mkdir(parents=True, exist_ok=True)
    man = ROOT / "fred" / "manifest.json"
    prev = json.loads(man.read_text()) if man.exists() else {}  # keep provenance of series not re-fetched
    with httpx.Client(timeout=60) as c:  # FRED drops connections for some custom User-Agents; default works
        for sid in series:
            r = _get_retry(c, FRED.format(sid=sid))
            (ROOT / "fred" / f"{sid}.csv").write_bytes(r.content)
            out[sid] = {
                "url": FRED.format(sid=sid),
                "sha256": hashlib.sha256(r.content).hexdigest(),
                "bytes": len(r.content),
                "retrieved_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            }
    man.write_text(json.dumps({**prev, **out}, indent=1))
    return out


def _get_retry(c: httpx.Client, url: str, tries: int = 4) -> httpx.Response:
    import time

    for k in range(tries):
        try:
            r = c.get(url)
            r.raise_for_status()
            return r
        except (httpx.TransportError, httpx.HTTPStatusError):
            if k == tries - 1:
                raise
            time.sleep(2 * 2**k)
    raise RuntimeError("unreachable")


@dataclass(frozen=True)
class Series:
    t: np.ndarray  # ms (open time for bars, date 00:00 UTC for daily observations)
    close: np.ndarray
    high: np.ndarray | None = None
    low: np.ndarray | None = None
    volume: np.ndarray | None = None


def load_btc(interval: str = "1d") -> Series:
    rows = []
    for p in sorted((ROOT / "binance" / interval).glob("*.zip")):
        rows += [(_ms(r[0]), float(r[4]), float(r[2]), float(r[3]), float(r[5])) for r in _rows(p)]
    a = np.array(sorted(set(rows)))
    if np.any(np.diff(a[:, 0]) <= 0):
        raise ValueError("duplicate timestamps in spot archives")
    return Series(a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4])


def load_fred(sid: str) -> Series:
    txt = (ROOT / "fred" / f"{sid}.csv").read_text()
    t, v = [], []
    for row in csv.reader(io.StringIO(txt)):
        if not row or not row[0][:1].isdigit() or row[1] in (".", ""):
            continue  # FRED marks missing observations with "."; they stay missing (no filling)
        d = dt.datetime.fromisoformat(row[0]).replace(tzinfo=dt.UTC)
        t.append(int(d.timestamp() * 1000))
        v.append(float(row[1]))
    return Series(np.array(t, dtype=np.int64), np.array(v))


def provenance() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in ("binance/manifest_1d.json", "binance/manifest_1h.json", "fred/manifest.json"):
        p = ROOT / f
        if p.exists():
            d = json.loads(p.read_text())
            out[f] = {k: v for k, v in d.items() if k != "files"} | ({"files": len(d["files"])} if "files" in d else {})
    return out
