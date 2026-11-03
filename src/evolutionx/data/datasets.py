"""Historical research datasets: Binance USD-M perpetual 1h klines + funding, with provenance and QC.

Untrusted external data. Every monthly archive is checked against Binance's
published SHA-256 (.CHECKSUM), parsed with explicit convention detection
(header row, ms vs us timestamps), and quality-controlled. Nothing is filled
in silently: missing hours stay missing (the backtester carries the position
and cannot trade during a gap), invalid rows are excluded and counted.

Splits come from the frozen protocol (evals/frozen/research_protocol.json).
The FINAL split is written to a separate vault directory that is never
mounted inside candidate sandboxes.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np

PROTOCOL = Path("evals/frozen/research_protocol.json")
RAW_DIR = Path("data/raw/binance")
DEV_DIR = Path("data/research")
VAULT_DIR = Path("data/vault")
BASE = "https://data.binance.vision/data/futures/um/monthly"
HOUR = 3_600_000
FIELDS = ("open_time", "open", "high", "low", "close", "volume", "available_at", "funding")


class DataQualityError(ValueError):
    pass


def protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL.read_text())


def _months(start: str, end_excl: str) -> list[str]:
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end_excl[:4]), int(end_excl[5:7])
    out = []
    while (y, m) < (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _ms(x: str) -> int:
    v = int(x)
    return v // 1000 if v > 10**14 else v  # convention change: some archives use microseconds


def _fetch(client: httpx.Client, url: str, dest: Path) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        r = client.get(url)
        r.raise_for_status()
        if len(r.content) > 50_000_000:
            raise DataQualityError(f"archive too large: {url}")
        dest.write_bytes(r.content)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    ck = dest.with_suffix(dest.suffix + ".CHECKSUM")
    if not ck.exists():
        rc = client.get(url + ".CHECKSUM")
        if rc.status_code == 200:
            ck.write_text(rc.text)
    published = ck.read_text().split()[0] if ck.exists() else None
    if published and published != digest:
        dest.unlink()
        raise DataQualityError(f"checksum mismatch for {url}")
    return {"url": url, "sha256": digest, "checksum_verified": published == digest}


def _rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise DataQualityError(f"unexpected archive contents {z.namelist()}")
        txt = z.read(names[0]).decode("ascii")
    return [r for r in csv.reader(io.StringIO(txt)) if r and r[0].strip().lstrip("-").isdigit()]


@dataclass
class QC:
    rows_raw: int = 0
    duplicates_identical: int = 0
    duplicates_conflicting: int = 0
    misaligned: int = 0
    invalid_ohlc: int = 0
    partial_bars: int = 0
    gaps: int = 0
    missing_hours: int = 0
    funding_events: int = 0
    funding_out_of_range: int = 0
    timestamp_us_files: int = 0
    header_files: int = 0


def build_instrument(symbol: str, client: httpx.Client, now_ms: int | None = None) -> dict[str, Any]:
    p = protocol()
    cov = p["coverage"]
    months = _months(cov["start"], cov["end_exclusive"])
    now_ms = now_ms or int(dt.datetime.now(dt.UTC).timestamp() * 1000)
    qc = QC()
    sources = []
    bars: dict[int, tuple[float, float, float, float, float, int]] = {}
    funding: dict[int, float] = {}
    for mo in months:
        for kind, url, dest in (
            ("klines", f"{BASE}/klines/{symbol}/1h/{symbol}-1h-{mo}.zip", RAW_DIR / symbol / f"{symbol}-1h-{mo}.zip"),
            (
                "funding",
                f"{BASE}/fundingRate/{symbol}/{symbol}-fundingRate-{mo}.zip",
                RAW_DIR / symbol / f"{symbol}-fundingRate-{mo}.zip",
            ),
        ):
            meta = _fetch(client, url, dest)
            sources.append({"kind": kind, "month": mo, **meta})
            with zipfile.ZipFile(dest) as z:
                first = z.read(z.namelist()[0])[:20].decode("ascii", "replace")
            qc.header_files += not first[:1].isdigit()
            rows = _rows(dest)
            if kind == "klines":
                if rows and int(rows[0][0]) > 10**14:
                    qc.timestamp_us_files += 1
                for r in rows:
                    qc.rows_raw += 1
                    t = _ms(r[0])
                    o, h, lo, c, v = (float(x) for x in r[1:6])
                    close_t = _ms(r[6])
                    if t % HOUR:
                        qc.misaligned += 1
                        continue
                    if close_t - t != HOUR - 1 or close_t >= now_ms:
                        qc.partial_bars += 1
                        continue
                    if min(o, h, lo, c) <= 0 or v < 0 or h < max(o, c) - 1e-9 or lo > min(o, c) + 1e-9:
                        qc.invalid_ohlc += 1
                        continue
                    rec = (o, h, lo, c, v, close_t + 1)
                    if t in bars:
                        if bars[t] == rec:
                            qc.duplicates_identical += 1
                        else:
                            qc.duplicates_conflicting += 1
                            bars.pop(t)  # conflicting duplicate: exclude both, never pick a favourable one
                        continue
                    bars[t] = rec
            else:
                for r in rows:
                    t = _ms(r[0])
                    rate = float(r[-1])
                    if abs(rate) > 0.03:
                        qc.funding_out_of_range += 1
                        continue
                    funding[t - t % HOUR] = rate  # calc_time can be +1ms; funding applies at the hour boundary
                    qc.funding_events += 1
    ts = np.array(sorted(bars), dtype=np.int64)
    if len(ts) < 1000:
        raise DataQualityError(f"{symbol}: too few bars ({len(ts)})")
    d = np.diff(ts)
    qc.gaps = int((d > HOUR).sum())
    qc.missing_hours = int(((d - HOUR)[d > HOUR] // HOUR).sum())
    arr = np.array([bars[t] for t in ts])
    # funding charged at the END of the bar whose close coincides with the funding timestamp
    fund = np.array([funding.get(int(t) + HOUR, 0.0) for t in ts])
    data = {
        "open_time": ts,
        "open": arr[:, 0],
        "high": arr[:, 1],
        "low": arr[:, 2],
        "close": arr[:, 3],
        "volume": arr[:, 4],
        "available_at": arr[:, 5].astype(np.int64),
        "funding": fund,
    }
    gap_list = [[int(ts[i]), int(ts[i + 1])] for i in np.where(d > HOUR)[0][:200]]
    return {"symbol": symbol, "data": data, "qc": qc.__dict__, "sources": sources, "gaps": gap_list}


def _split_mask(t: np.ndarray, start: str, end_excl: str) -> np.ndarray:
    s = int(dt.datetime.fromisoformat(start).replace(tzinfo=dt.UTC).timestamp() * 1000)
    e = int(dt.datetime.fromisoformat(end_excl).replace(tzinfo=dt.UTC).timestamp() * 1000)
    return (t >= s) & (t < e)


def build_all() -> dict[str, Any]:
    p = protocol()
    DEV_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "protocol": p["name"],
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "built_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "timezone": "UTC",
        "units": {"price": "USDT", "volume": "base asset", "funding": "rate per event", "time": "ms since epoch"},
        "instruments": {},
    }
    with httpx.Client(timeout=60) as client:
        for inst in p["instruments"]:
            res = build_instrument(inst["symbol"], client)
            d = res["data"]
            files = {}
            for split, cfg in p["splits"].items():
                m = _split_mask(d["open_time"], cfg["start"], cfg["end_exclusive"])
                part = {k: v[m] for k, v in d.items()}
                out = (VAULT_DIR if split == "final" else DEV_DIR) / f"{inst['symbol']}_1h_{split}.npz"
                np.savez(out, **part)
                files[split] = {
                    "path": str(out),
                    "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                    "bars": int(m.sum()),
                    "first": _iso(part["open_time"][:1]),
                    "last": _iso(part["open_time"][-1:]),
                }
            manifest["instruments"][inst["symbol"]] = {
                "market": inst["market"],
                "resolution": inst["resolution"],
                "qc": res["qc"],
                "gaps_sample": res["gaps"][:20],
                "files": files,
                "n_sources": len(res["sources"]),
                "all_checksums_verified": all(s["checksum_verified"] for s in res["sources"]),
                "sources_sha256": hashlib.sha256(json.dumps(res["sources"], sort_keys=True).encode()).hexdigest(),
            }
            (DEV_DIR / f"{inst['symbol']}_sources.json").write_text(json.dumps(res["sources"], indent=1))
    (DEV_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _iso(a: np.ndarray) -> str | None:
    return dt.datetime.fromtimestamp(int(a[0]) / 1000, dt.UTC).isoformat() if len(a) else None


def load_split(symbol: str, split: str) -> dict[str, np.ndarray]:
    """Load development/validation data. The final split is NOT loadable here (see research.vault)."""
    if split == "final":
        raise PermissionError("final split is only accessible through research.vault.Vault.reveal()")
    z = np.load(DEV_DIR / f"{symbol}_1h_{split}.npz")
    return {k: z[k] for k in z.files}
