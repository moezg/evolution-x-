"""Point-in-time BTC hourly bars for forecasting.

Sources (all Binance USD-M BTCUSDT 1 h, official archives with checksums):
  * data/research/BTCUSDT_1h_{development,validation}.npz and data/vault/BTCUSDT_1h_final.npz (already on disk;
    exposure status in evals/frozen/exposure_registry.json; the final split is CONSUMED and used here only for
    training and labelled retrospective scoring),
  * data/fresh/BTCUSDT-1h-YYYY-MM-DD.zip daily archives from 2026-11-01 (never loaded before this mission).
The reserved SOL/BNB vault is never read by this module.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from ..data.datasets import DataQualityError, _fetch, _ms, _rows

HOUR = 3_600_000
SPLITS = (
    Path("data/research/BTCUSDT_1h_development.npz"),
    Path("data/research/BTCUSDT_1h_validation.npz"),
    Path("data/vault/BTCUSDT_1h_final.npz"),
)
FRESH = Path("data/fresh")
FRESH_START = "2026-11-01"
DAILY = "https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1h/BTCUSDT-1h-{d}.zip"
# same instrument, same file format: verified row-identical to the daily files (144/144 rows, Oct 2026)
MONTHLY = "https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-{m}.zip"
PUBLICATION_LAG_MS = 24 * HOUR  # archive for day D is assumed available at D+1 24:00 at the latest


@dataclass(frozen=True)
class Bars:
    open_time: np.ndarray  # ms, hour aligned
    close: np.ndarray
    high: np.ndarray
    low: np.ndarray
    volume: np.ndarray
    source: np.ndarray  # 0 dev, 1 validation, 2 consumed final, 3 fresh

    def __len__(self) -> int:
        return len(self.open_time)

    def digest(self, lo: int, hi: int) -> str:
        """sha256 of the bars in [lo, hi) - recorded with every forecast as its input fingerprint."""
        h = hashlib.sha256()
        for arr in (self.open_time[lo:hi], self.close[lo:hi], self.high[lo:hi], self.low[lo:hi], self.volume[lo:hi]):
            h.update(np.ascontiguousarray(arr).tobytes())
        return h.hexdigest()[:16]


def fetch_fresh(until: dt.date | None = None) -> dict[str, Any]:
    """Download fresh daily archives (checksum verified) from FRESH_START up to `until` (default: yesterday UTC).

    Days whose daily file is missing are looked up once their month is complete in the official MONTHLY archive of
    the same instrument (identical rows). Publication times (Last-Modified) of newly fetched days are recorded.
    """
    until = until or (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1))
    d = dt.date.fromisoformat(FRESH_START)
    got, missing, published = [], [], {}
    old = json.loads((FRESH / "manifest.json").read_text()) if (FRESH / "manifest.json").exists() else {}
    with httpx.Client(timeout=60) as client:
        while d <= until:
            url = DAILY.format(d=d.isoformat())
            dest = FRESH / f"BTCUSDT-1h-{d.isoformat()}.zip"
            new = not dest.exists()
            try:
                got.append({"day": d.isoformat(), **_fetch(client, url, dest)})
                if new:
                    lm = client.head(url).headers.get("last-modified")
                    published[d.isoformat()] = lm
            except httpx.HTTPStatusError:
                missing.append(d.isoformat())  # not yet published
            d += dt.timedelta(days=1)
        filled = []
        today = dt.datetime.now(dt.UTC).date()
        for m in sorted({x[:7] for x in missing}):
            y, mo = int(m[:4]), int(m[5:])
            month_end = dt.date(y + mo // 12, mo % 12 + 1, 1) - dt.timedelta(days=1)
            if month_end >= today:
                continue  # monthly archive only exists after the month is complete
            dest = FRESH / "monthly" / f"BTCUSDT-1h-{m}.zip"
            try:
                info = _fetch(client, MONTHLY.format(m=m), dest)
            except httpx.HTTPStatusError:
                continue
            days_in = {dt.datetime.fromtimestamp(_ms(r[0]) / 1000, dt.UTC).date().isoformat() for r in _rows(dest)}
            cover = [x for x in missing if x.startswith(m) and x in days_in]
            if cover:
                filled.append({"month": m, **info, "fills_days": cover})
    FRESH.mkdir(parents=True, exist_ok=True)
    manifest = {
        "fetched_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "files": got,
        "not_published": missing,
        "filled_from_monthly": filled,
        "publication_last_modified": {**old.get("publication_last_modified", {}), **published},
    }
    (FRESH / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def _fresh_rows() -> list[tuple[int, float, float, float, float]]:
    """Daily files plus monthly fallback files; overlapping rows must be identical (else DataQualityError)."""
    seen: dict[int, tuple[int, float, float, float, float]] = {}
    for p in sorted(FRESH.glob("BTCUSDT-1h-*.zip")) + sorted((FRESH / "monthly").glob("BTCUSDT-1h-*.zip")):
        for r in _rows(p):
            row = (_ms(r[0]), float(r[4]), float(r[2]), float(r[3]), float(r[5]))
            if row[0] in seen and seen[row[0]] != row:
                raise DataQualityError(f"daily and monthly archives disagree at {row[0]}")
            seen[row[0]] = row
    return [seen[k] for k in sorted(seen)]


def load_bars(include_fresh: bool = True) -> Bars:
    cols: dict[str, list[np.ndarray]] = {k: [] for k in ("open_time", "close", "high", "low", "volume", "source")}
    for i, p in enumerate(SPLITS):
        z = np.load(p)
        for k in ("open_time", "close", "high", "low", "volume"):
            cols[k].append(z[k])
        cols["source"].append(np.full(len(z["open_time"]), i))
    if include_fresh:
        rows = _fresh_rows()
        if rows:
            a = np.array(rows)
            last = cols["open_time"][-1][-1]
            keep = a[:, 0] > last
            for j, k in enumerate(("open_time", "close", "high", "low", "volume")):
                cols[k].append(a[keep, j].astype(np.int64) if k == "open_time" else a[keep, j])
            cols["source"].append(np.full(int(keep.sum()), 3))
    t = np.concatenate(cols["open_time"]).astype(np.int64)
    order = np.argsort(t, kind="stable")
    t = t[order]
    if np.any(np.diff(t) <= 0):
        raise ValueError("duplicate or unordered bars")
    return Bars(
        t,
        np.concatenate(cols["close"])[order].astype(float),
        np.concatenate(cols["high"])[order].astype(float),
        np.concatenate(cols["low"])[order].astype(float),
        np.concatenate(cols["volume"])[order].astype(float),
        np.concatenate(cols["source"])[order],
    )
