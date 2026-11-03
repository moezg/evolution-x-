"""Reserved confirmation vault v2 (never used for generation, selection or diagnostics).

Instruments and period chosen BEFORE looking at any of their data: Binance USD-M perpetual SOLUSDT and BNBUSDT,
1h, 2024-01-01 .. 2026-10-31. Only quality-control counts are computed when building it (no returns, no prices
summarised). Caveat: the period overlaps the 2024-2026 BTC/ETH validation+final periods whose results this session
has seen, and crypto assets are correlated, so this set is reserved but not independent of market-regime knowledge.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import httpx
import numpy as np

from .datasets import build_instrument

VAULT2 = Path("data/vault_v2")
SPEC = {
    "instruments": ["SOLUSDT", "BNBUSDT"],
    "start": "2024-01-01",
    "end_exclusive": "2026-11-01",
    "chosen_utc": "2026-11-03T16:30:00Z",
    "selection_rule": "liquid USD-M perps not used anywhere in this project",
}


def build() -> dict:
    import evolutionx.data.datasets as D

    VAULT2.mkdir(parents=True, exist_ok=True)
    orig = D.protocol
    proto = orig()
    proto["coverage"] = {"start": SPEC["start"], "end_exclusive": SPEC["end_exclusive"]}
    D.protocol = lambda: proto  # coverage for this build only
    manifest = {"spec": SPEC, "built_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "instruments": {}}
    try:
        with httpx.Client(timeout=60) as c:
            for s in SPEC["instruments"]:
                res = build_instrument(s, c)
                out = VAULT2 / f"{s}_1h_reserved.npz"
                np.savez(out, **res["data"])
                manifest["instruments"][s] = {
                    "qc": res["qc"],
                    "bars": int(len(res["data"]["close"])),
                    "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                    "checksums_verified": all(x["checksum_verified"] for x in res["sources"]),
                }
    finally:
        D.protocol = orig
    (VAULT2 / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
