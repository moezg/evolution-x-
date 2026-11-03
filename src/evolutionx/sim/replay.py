"""Mode B: historical replay + labelled counterfactuals.

The historical close series drives the latent fundamental. The simulated order
book still produces its own (synthetic) prices. The two are ALWAYS kept apart:
`historical` holds the untouched source series and metadata; simulated output
is labelled `counterfactual_synthetic`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def load_replay_path(path: str | None, duration_s: int) -> dict[str, Any]:
    if not path:
        raise ValueError("replay mode requires replay_dataset")
    p = Path(path)
    arr = np.load(p)
    t0 = arr[0, 0]
    # 1-minute closes mapped to simulation milliseconds; step function between minutes
    pts = [(int(r[0] - t0), float(r[4])) for r in arr if (r[0] - t0) <= duration_s * 1000]
    return {"source_file": p.name, "label": "historical", "path": pts, "first_close": pts[0][1], "n_points": len(pts)}
