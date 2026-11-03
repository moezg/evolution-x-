"""Code executed INSIDE the sandbox (it may be subverted by the candidate it hosts; nothing it outputs is trusted
beyond 'decision arrays', which the trusted evaluator validates and re-checks independently).

Input (/in): candidate.py, job.json, and only the data files permitted for this run.
Output (/out): dec_<i>.npy (float64 target exposures) + done.json.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np


def main(in_dir: str, out_dir: str) -> None:
    from evolutionx.backtest.interface import decisions_for, load_module_strategy

    job = json.loads((Path(in_dir) / "job.json").read_text())
    spec = importlib.util.spec_from_file_location("candidate", Path(in_dir) / "candidate.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    timings = []
    for i, item in enumerate(job["items"]):
        z = np.load(Path(in_dir) / item["data"], allow_pickle=False)
        data = {k: z[k] for k in z.files}
        t = time.perf_counter()
        dec = decisions_for(load_module_strategy(mod, item["params"]), data)
        timings.append(time.perf_counter() - t)
        np.save(Path(out_dir) / f"dec_{i}.npy", dec.astype(np.float64), allow_pickle=False)
    (Path(out_dir) / "done.json").write_text(json.dumps({"n": len(job["items"]), "timings": timings}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
