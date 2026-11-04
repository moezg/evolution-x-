"""Binance USDT-M BTCUSDT derivatives data from the official public archive (data.binance.vision), checksum verified.

metrics (daily files, 5-min rows from 2020-09): open interest, top-trader and global long/short ratios, taker
long/short volume ratio. premiumIndexKlines 1h (monthly files from 2020-01, daily for the current month).
Published with the same daily cadence as the price archive (day D available on D+1), so a feature built from rows
before the forecast's information cutoff is point-in-time.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from ..data.datasets import _fetch

ROOT = Path("data/quant/binance_futures")
B = "https://data.binance.vision/data/futures/um"


def fetch_metrics(start: str = "2020-09-01", end: str | None = None) -> dict[str, Any]:
    d = dt.date.fromisoformat(start)
    last = dt.date.fromisoformat(end) if end else dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1)
    got, missing = 0, []
    with httpx.Client(timeout=60) as c:
        while d <= last:
            dest = ROOT / "metrics" / f"BTCUSDT-metrics-{d.isoformat()}.zip"
            try:
                _fetch(c, f"{B}/daily/metrics/BTCUSDT/BTCUSDT-metrics-{d.isoformat()}.zip", dest)
                got += 1
            except httpx.HTTPStatusError:
                missing.append(d.isoformat())
            d += dt.timedelta(days=1)
    out = {"files": got, "missing": missing, "fetched_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    (ROOT / "metrics_manifest.json").write_text(json.dumps(out, indent=1))
    return out


def fetch_premium(start: str = "2020-01", end: str = "2026-10") -> dict[str, Any]:
    y, m = int(start[:4]), int(start[5:])
    got, missing = 0, []
    with httpx.Client(timeout=60) as c:
        while f"{y:04d}-{m:02d}" <= end:
            ym = f"{y:04d}-{m:02d}"
            try:
                _fetch(
                    c,
                    f"{B}/monthly/premiumIndexKlines/BTCUSDT/1h/BTCUSDT-1h-{ym}.zip",
                    ROOT / "premium" / f"BTCUSDT-1h-{ym}.zip",
                )
                got += 1
            except httpx.HTTPStatusError:
                missing.append(ym)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    out = {"files": got, "missing": missing}
    (ROOT / "premium_manifest.json").write_text(json.dumps(out, indent=1))
    return out


def _ms(s: str) -> int:
    return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.UTC).timestamp() * 1000)


def load_metrics() -> dict[str, np.ndarray]:
    rows = []
    for p in sorted((ROOT / "metrics").glob("*.zip")):
        with zipfile.ZipFile(p) as z:
            for r in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
                try:
                    rows.append(
                        (
                            _ms(r["create_time"]),
                            float(r["sum_open_interest"]),
                            float(r["sum_taker_long_short_vol_ratio"] or "nan"),
                            float(r["count_long_short_ratio"] or "nan"),
                        )
                    )
                except (ValueError, KeyError):
                    continue
    a = np.array(sorted(set(rows)))
    return {"t": a[:, 0].astype(np.int64), "oi": a[:, 1], "taker_ratio": a[:, 2], "ls_ratio": a[:, 3]}


def load_premium() -> dict[str, np.ndarray]:
    rows = []
    for p in sorted((ROOT / "premium").glob("*.zip")):
        with zipfile.ZipFile(p) as z:
            for r in csv.reader(io.StringIO(z.read(z.namelist()[0]).decode())):
                if r and r[0][:1].isdigit():
                    rows.append((int(r[0]), float(r[4])))  # open time, close premium index
    a = np.array(sorted(set(rows)))
    return {"t": a[:, 0].astype(np.int64), "premium": a[:, 1]}
