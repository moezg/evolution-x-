"""Read-only historical market data adapter (Binance public archive, 1-minute klines).

External data is UNTRUSTED input: every row is validated (monotonic timestamps,
positive prices, high>=max(open,close), low<=min(open,close), non-negative
volume) and each file's SHA-256 is recorded in a manifest. Rows are never
modified; invalid files are rejected wholesale.

Dataset splits are by calendar date to avoid leakage:
  train      -> used to derive realism reference bands
  validation -> used for model selection
  heldout    -> only for final reporting
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import numpy as np

BASE_URL = "https://data.binance.vision/data/spot/daily/klines/{sym}/1m/{sym}-1m-{day}.zip"
DATA_DIR = Path("data/historical")

DEFAULT_SPLITS = {
    "train": ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"],
    "validation": ["2026-09-15", "2026-09-16"],
    "heldout": ["2026-10-01", "2026-10-02"],
}


class DataValidationError(ValueError):
    pass


def _parse_rows(raw: bytes) -> np.ndarray:
    rows = []
    for rec in csv.reader(io.StringIO(raw.decode("ascii"))):
        if not rec or not rec[0].strip().isdigit():
            continue
        t = int(rec[0])
        if t > 10**14:  # Binance switched some archives to microseconds
            t //= 1000
        o, h, lo, c, v = (float(x) for x in rec[1:6])
        rows.append((t, o, h, lo, c, v))
    a = np.array(rows, dtype=float)
    if len(a) < 100:
        raise DataValidationError("too few rows")
    t, o, h, lo, c, v = a.T
    if not np.all(np.diff(t) > 0):
        raise DataValidationError("timestamps not strictly increasing")
    if np.any(a[:, 1:5] <= 0) or np.any(v < 0):
        raise DataValidationError("non-positive price or negative volume")
    if np.any(h < np.maximum(o, c) - 1e-9) or np.any(lo > np.minimum(o, c) + 1e-9):
        raise DataValidationError("OHLC inconsistency")
    return a


def fetch_day(day: str, symbol: str = "BTCUSDT", data_dir: Path = DATA_DIR, client: httpx.Client | None = None) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    out = data_dir / f"{symbol}-1m-{day}.npy"
    if out.exists():
        return out
    url = BASE_URL.format(sym=symbol, day=day)
    c = client or httpx.Client(timeout=30)
    r = c.get(url)
    r.raise_for_status()
    if len(r.content) > 20_000_000:
        raise DataValidationError("archive unexpectedly large")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        if len(names) != 1 or not names[0].endswith(".csv"):
            raise DataValidationError(f"unexpected archive contents {names}")
        raw = z.read(names[0])
    arr = _parse_rows(raw)
    np.save(out, arr)
    _update_manifest(data_dir, out.name, {"source": url, "symbol": symbol, "day": day, "rows": int(len(arr)),
                                          "sha256_archive": hashlib.sha256(r.content).hexdigest(),
                                          "fetched_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                                          "kind": "historical"})
    return out


def _update_manifest(data_dir: Path, name: str, meta: dict) -> None:
    mpath = data_dir / "manifest.json"
    m = json.loads(mpath.read_text()) if mpath.exists() else {}
    m[name] = meta
    mpath.write_text(json.dumps(m, indent=2, sort_keys=True))


def fetch_splits(splits: dict[str, list[str]] = DEFAULT_SPLITS, symbol: str = "BTCUSDT") -> dict[str, list[Path]]:
    with httpx.Client(timeout=30) as c:
        return {k: [fetch_day(d, symbol, client=c) for d in days] for k, days in splits.items()}


def load_split(split: str, symbol: str = "BTCUSDT", data_dir: Path = DATA_DIR,
               splits: dict[str, list[str]] = DEFAULT_SPLITS) -> list[np.ndarray]:
    out = []
    for d in splits[split]:
        p = data_dir / f"{symbol}-1m-{d}.npy"
        if p.exists():
            out.append(np.load(p))
    return out


def available() -> bool:
    return any(DATA_DIR.glob("*.npy"))
