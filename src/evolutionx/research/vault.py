"""Final-evaluation vault with an access ledger (TRUSTED).

Guarantee actually provided: the vault directory is never mounted in candidate sandboxes, and every reveal by the
supervisor is recorded (ledger + journal). Once revealed for a campaign, the final split is marked CONSUMED:
later reports must call it "previously revealed", not blind. Limitation: the trusted supervisor process runs as
the same OS user as the files, so this is an audited procedure, not cryptographic isolation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .journal import Journal
from .memory import Memory, now

VAULT_DIR = Path("data/vault")


class Vault:
    def __init__(self, memory: Memory, journal: Journal, vault_dir: Path = VAULT_DIR) -> None:
        self.m, self.j, self.dir = memory, journal, vault_dir

    def status(self) -> dict:
        led = self.m.q("SELECT * FROM vault_ledger ORDER BY id")
        files = sorted(p.name for p in self.dir.glob("*.npz"))
        return {"files": files, "reveals": led, "consumed": bool(led), "blind_for_next_campaign": not led}

    def reveal(self, campaign_id: str, actor: str, reason: str, symbols: list[str]) -> dict[str, dict[str, np.ndarray]]:
        prior = self.m.q("SELECT campaign_id FROM vault_ledger")
        out, files = {}, []
        for s in symbols:
            p = self.dir / f"{s}_1h_final.npz"
            z = np.load(p, allow_pickle=False)
            out[s] = {k: z[k] for k in z.files}
            files.append({"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
        import json

        self.m.x(
            "INSERT INTO vault_ledger (campaign_id, actor, reason, files, ts) VALUES (?,?,?,?,?)",
            (campaign_id, actor, reason, json.dumps(files), now()),
        )
        self.j.append(
            actor,
            "vault_reveal",
            {
                "campaign": campaign_id,
                "reason": reason,
                "files": files,
                "previously_revealed_by": [r["campaign_id"] for r in prior],
            },
        )
        return out
