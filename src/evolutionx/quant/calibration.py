"""P5: calibration of the registered calendar decision rule on synthetic data (protocol quant_calibration_v1).

Synthetic returns with realistic dependence (GARCH volatility clustering, heavy tails) are laid on the REAL calendar
(same labels, same DISCOVERY/CONFIRMATION split). Under a null generator every 'supported' result is false, so the
per-run false-positive rate is measured directly, with Wilson 95% intervals. Planted day-14 effects give power.
Nothing here touches market data, the test registry or any threshold of the discovery rule.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from . import calendar as CAL
from .stats import bh, holm

PROTOCOL = Path("evals/frozen/quant_calibration_v1.json")
OUT = Path("artifacts/quant/calibration_v1.json")
N_DAYS = 3363
START = dt.date(2017, 8, 17)


VERSION = {
    "v1": (PROTOCOL, OUT, False),
    "v2": (Path("evals/frozen/quant_calibration_v2.json"), Path("artifacts/quant/calibration_v2.json"), True),
}
_ACTIVE = {"v": "v1"}


def protocol() -> dict[str, Any]:
    return json.loads(VERSION[_ACTIVE["v"]][0].read_text())


def protocol_sha() -> str:
    return hashlib.sha256(VERSION[_ACTIVE["v"]][0].read_bytes()).hexdigest()


def frame(ret: np.ndarray) -> dict[str, np.ndarray]:
    days = [START + dt.timedelta(days=i) for i in range(len(ret))]
    nxt = [d + dt.timedelta(days=1) for d in days]
    return {
        "date": np.array([d.isoformat() for d in days]),
        "ret": ret,
        "dom": np.array([d.day for d in days]),
        "dow": np.array([d.weekday() for d in days]),
        "moy": np.array([d.month for d in days]),
        "tom": np.array([int(d.day <= 3 or n.month != d.month) for d, n in zip(days, nxt, strict=True)]),
    }


def _std_t(rng: np.random.Generator, df: float, n: int) -> np.ndarray:
    return rng.standard_t(df, n) / math.sqrt(df / (df - 2))


def generate(kind: str, seed: int, n: int = N_DAYS) -> tuple[np.ndarray, np.ndarray]:
    """Returns (returns, conditional sd). Null generators have no calendar structure at all."""
    rng = np.random.default_rng(seed)
    if kind == "iid_t4":
        sd = np.full(n, 0.03)
        return sd * _std_t(rng, 4, n), sd
    a, b, df = {"garch_t5": (0.10, 0.85, 5.0), "garch_t3_persistent": (0.06, 0.93, 3.0)}[kind]
    var_u = 0.035**2
    w = var_u * (1 - a - b)
    z = _std_t(rng, df, n + 500)
    r = np.empty(n + 500)
    s2 = np.empty(n + 500)
    s2[0] = var_u
    r[0] = math.sqrt(var_u) * z[0]
    for t in range(1, n + 500):
        s2[t] = w + a * r[t - 1] ** 2 + b * s2[t - 1]
        r[t] = math.sqrt(s2[t]) * z[t]
    return r[500:], np.sqrt(s2[500:])  # burn-in removed


def decide(
    f: dict[str, np.ndarray],
    families: tuple[str, ...] = ("F-DOM", "F-DOW", "F-MOY", "F-TOM"),
    dow_weekperm: bool = False,
) -> dict[str, Any]:
    """The registered rule, identical to calendar.run() (verified by tests), without writing to any registry."""
    out: dict[str, Any] = {"supported": [], "bh_survivors": [], "tests": 0}
    for fam in families:
        if fam == "F-DOW" and dow_weekperm:  # amendment 4
            out["supported"] += decide_dow_weekperm(f)
            out["tests"] += 28
            continue
        adj = fam != "F-DOW"
        disc = CAL.scan(f, fam, "DISCOVERY", adj)
        name = lambda r, fam=fam: f"{fam}:{r['label']}:{r['metric']}"  # noqa: E731
        b = bh({name(r): r["p"] for r in disc["rows"]}, 0.10)
        surv = [r for r in disc["rows"] if b[name(r)]["reject"]]
        cmap = {name(r): r for r in CAL.scan(f, fam, "CONFIRMATION", adj)["rows"]}
        one = {name(r): (cmap[name(r)]["p_up"] if r["effect"] > 0 else cmap[name(r)]["p_down"]) for r in surv}
        h = holm(one, 0.05)
        out["tests"] += len(disc["rows"])
        out["bh_survivors"] += [name(r) for r in surv]
        out["supported"] += [
            name(r)
            for r in surv
            if h[name(r)]["reject"]
            and np.sign(cmap[name(r)]["effect"]) == np.sign(r["effect"])
            and cmap[name(r)]["n"] >= 20
        ]
    return out


def _metric(h: str) -> str:
    return h.split(":")[-1].replace("_wd_adj", "")


def _null_job(args: tuple[str, int, bool]) -> dict[str, Any]:
    kind, seed, wp = args
    r, _ = generate(kind, seed)
    d = decide(frame(r), dow_weekperm=wp)
    return {"seed": seed, "supported": d["supported"], "bh_survivors": len(d["bh_survivors"]), "tests": d["tests"]}


def _power_job(args: tuple[str, float, int]) -> dict[str, Any]:
    kind, size, seed = args
    r, sd = generate("garch_t5", seed)
    dom = frame(r)["dom"]
    m = dom == 14
    if kind == "mean":
        r = r + size * 0.035 * m
    else:
        r = np.where(m, r * size, r)
    d = decide(frame(r), ("F-DOM",))
    hit = "F-DOM:14:mean_ret_wd_adj" if kind == "mean" else "F-DOM:14:mean_absret"
    return {
        "seed": seed,
        "hit": hit in d["supported"],
        "other_supported": [h for h in d["supported"] if not h.startswith("F-DOM:14:")],
    }


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (0.0 if k == 0 else max(0.0, c - h), 1.0 if k == n else min(1.0, c + h))


def _rate(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": k / n if n else None, "wilson95": [lo, hi]}


def summarize_null(runs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(runs)
    metrics = [m for m in CAL.METRICS]
    fams = ("F-DOM", "F-DOW", "F-MOY", "F-TOM")
    return {
        "runs": n,
        "tests_per_run": runs[0]["tests"] if runs else 0,
        "any_false_supported": _rate(sum(bool(r["supported"]) for r in runs), n),
        "per_metric": {m: _rate(sum(any(_metric(h) == m for h in r["supported"]) for r in runs), n) for m in metrics},
        "per_family": {
            f: _rate(sum(any(h.startswith(f + ":") for h in r["supported"]) for r in runs), n) for f in fams
        },
        "false_supported_total": sum(len(r["supported"]) for r in runs),
        "mean_bh_survivors_per_run": float(np.mean([r["bh_survivors"] for r in runs])) if runs else None,
        "examples": [h for r in runs for h in r["supported"]][:20],
    }


def quarantine(null: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Frozen rule: lower bound > 1.25% or upper bound > 5% under ANY generator."""
    out = {}
    for m in CAL.METRICS:
        why = []
        for g, s in null.items():
            lo, hi = s["per_metric"][m]["wilson95"]
            if lo > 0.0125:
                why.append(f"{g}: Wilson lower bound {lo:.3%} > 1.25%")
            if hi > 0.05:
                why.append(f"{g}: Wilson upper bound {hi:.3%} > 5%")
        out[m] = {"quarantined": bool(why), "reasons": why}
    return out


def run(
    workers: int = 4, null_seeds: int | None = None, power_seeds: int | None = None, version: str = "v1"
) -> dict[str, Any]:
    """Full registered study. `null_seeds`/`power_seeds` below the protocol values are for smoke tests only and are
    labelled as such in the output (never used for the quarantine decision)."""
    _ACTIVE["v"] = version
    _, out_path, wp = VERSION[version]
    p = protocol()
    ns = null_seeds or p["null_seeds_per_generator"]
    ps = power_seeds or p["power_design"]["seeds_per_cell"]
    smoke = ns < p["null_seeds_per_generator"] or ps < p["power_design"]["seeds_per_cell"]
    out: dict[str, Any] = {
        "protocol": p["name"],
        "protocol_sha256": protocol_sha(),
        "n_rotations": CAL.N_ROT,
        "smoke_test_not_registered": smoke,
        "started_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "label": "SYNTHETIC data only (method calibration); no market data",
    }
    with ProcessPoolExecutor(workers) as ex:
        null = {}
        for g in p["null_generators"]:
            base = p["seed_base"][g]
            runs = list(ex.map(_null_job, [(g, base + i, wp) for i in range(ns)]))
            null[g] = summarize_null(runs)
        out["null"] = null
        power: dict[str, Any] = {}
        base = p["seed_base"]["power"]
        cells = [("mean", s) for s in p["power_design"]["mean_shift_on_day14_in_unconditional_sd"]] + [
            ("vol", s) for s in p["power_design"]["vol_scale_on_day14"]
        ]
        for ci, (kind, size) in enumerate(cells):
            res = list(ex.map(_power_job, [(kind, size, base + 1000 * ci + i) for i in range(ps)]))
            power[f"{kind}:{size}"] = {
                **_rate(sum(r["hit"] for r in res), ps),
                "runs_with_other_false_supported": sum(bool(r["other_supported"]) for r in res),
            }
        out["power"] = power
    out["quarantine"] = quarantine(null) if not smoke else "not decided (smoke test)"
    out["finished_utc"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    if not smoke:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=1))
    return out


# ----------------------------------------------------------------------------- amendment 4 acceptance (F-DOW)
OUT_DOW = Path("artifacts/quant/calibration_dow_weekperm.json")


def decide_dow_weekperm(f: dict[str, np.ndarray]) -> list[str]:
    disc = CAL.scan_dow_weekperm(f, "DISCOVERY")
    name = lambda r: f"F-DOW:{r['label']}:{r['metric']}"  # noqa: E731
    b = bh({name(r): r["p"] for r in disc["rows"]}, 0.10)
    surv = [r for r in disc["rows"] if b[name(r)]["reject"]]
    if not surv:
        return []
    cmap = {name(r): r for r in CAL.scan_dow_weekperm(f, "CONFIRMATION")["rows"]}
    one = {name(r): (cmap[name(r)]["p_up"] if r["effect"] > 0 else cmap[name(r)]["p_down"]) for r in surv}
    h = holm(one, 0.05)
    return [name(r) for r in surv if h[name(r)]["reject"] and np.sign(cmap[name(r)]["effect"]) == np.sign(r["effect"])]


def _dow_null(args: tuple[str, int]) -> list[str]:
    g, seed = args
    return decide_dow_weekperm(frame(generate(g, seed)[0]))


def _dow_power(args: tuple[float, int]) -> list[str]:
    scale, seed = args
    r, _ = generate("garch_t5", seed)
    f = frame(r)
    f["ret"] = np.where(f["dow"] == 5, r * scale, r)
    return decide_dow_weekperm(f)


def run_dow_acceptance(workers: int = 4) -> dict[str, Any]:
    p = protocol()
    out: dict[str, Any] = {
        "amendment": 4,
        "label": "SYNTHETIC data only (acceptance of the corrected F-DOW method)",
        "n_perm": CAL.N_WEEKPERM,
    }
    with ProcessPoolExecutor(workers) as ex:
        null = {}
        for g in p["null_generators"]:
            runs = list(ex.map(_dow_null, [(g, p["seed_base"][g] + i) for i in range(p["null_seeds_per_generator"])]))
            k = sum(bool(x) for x in runs)
            null[g] = {**_rate(k, len(runs)), "per_metric": {m: _rate(sum(any(_metric(h) == m for h in x) for x in runs), len(runs)) for m in CAL.METRICS}, "examples": [h for x in runs for h in x][:10]}  # fmt: skip
        out["null"] = null
        power = {}
        for i, sc in enumerate((0.9, 0.85, 0.8, 0.7)):
            runs = list(ex.map(_dow_power, [(sc, p["seed_base"]["power"] + 50_000 + 1000 * i + s) for s in range(40)]))
            power[f"saturday_vol_x{sc}"] = {**_rate(sum("F-DOW:5:mean_absret" in x for x in runs), 40), "other_weekday_false": sum(any(not h.startswith("F-DOW:5:") for h in x) for x in runs)}  # fmt: skip
        out["power"] = power
    out["accepted"] = all(v["wilson95"][1] <= 0.03 for v in out["null"].values())
    OUT_DOW.write_text(json.dumps(out, indent=1))
    return out


# ----------------------------------------------------------------------------- amendment 6 acceptance (F-DOM/MOY/TOM)
OUT_BLOCK = Path("artifacts/quant/calibration_blockperm.json")
BLOCK_FAMS = ("F-DOM", "F-MOY", "F-TOM")


def decide_blockperm(f: dict[str, np.ndarray], fam: str) -> list[str]:
    disc = CAL.scan_blockperm(f, fam, "DISCOVERY")
    name = lambda r: f"{fam}:{r['label']}:{r['metric']}"  # noqa: E731
    b = bh({name(r): r["p"] for r in disc["rows"]}, 0.10)
    surv = [r for r in disc["rows"] if b[name(r)]["reject"]]
    if not surv:
        return []
    cmap = {name(r): r for r in CAL.scan_blockperm(f, fam, "CONFIRMATION")["rows"]}
    one = {name(r): (cmap[name(r)]["p_up"] if r["effect"] > 0 else cmap[name(r)]["p_down"]) for r in surv}
    h = holm(one, 0.05)
    return [
        name(r)
        for r in surv
        if h[name(r)]["reject"]
        and np.sign(cmap[name(r)]["effect"]) == np.sign(r["effect"])
        and cmap[name(r)]["n"] >= 20
    ]


def _block_null(args: tuple[str, int]) -> list[str]:
    g, seed = args
    f = frame(generate(g, seed)[0])
    return [h for fam in BLOCK_FAMS for h in decide_blockperm(f, fam)]


def _block_power(args: tuple[float, int]) -> bool:
    size, seed = args
    r, _ = generate("garch_t5", seed)
    f = frame(r)
    f["ret"] = r + size * 0.035 * (f["dom"] == 14)
    return "F-DOM:14:mean_ret_wd_adj" in decide_blockperm(f, "F-DOM")


def run_blockperm_acceptance(workers: int = 4) -> dict[str, Any]:
    _ACTIVE["v"] = "v2"  # amendment 6: quant_calibration_v2 generators and seeds
    p = protocol()
    out: dict[str, Any] = {"amendment": 6, "label": "SYNTHETIC data only (acceptance of the F-DOM/F-MOY/F-TOM block-permutation nulls)", "n_perm": CAL.N_BLOCKPERM, "seeds": "quant_calibration_v2"}  # fmt: skip
    with ProcessPoolExecutor(workers) as ex:
        null = {}
        for g in p["null_generators"]:
            runs = list(ex.map(_block_null, [(g, p["seed_base"][g] + i) for i in range(p["null_seeds_per_generator"])]))
            null[g] = {
                "any": _rate(sum(bool(x) for x in runs), len(runs)),
                "per_family": {fam: _rate(sum(any(h.startswith(fam + ":") for h in x) for x in runs), len(runs)) for fam in BLOCK_FAMS},
                "examples": [h for x in runs for h in x][:10],
            }  # fmt: skip
        out["null"] = null
        out["power_day14_mean_shift"] = {
            str(sz): _rate(sum(ex.map(_block_power, [(sz, p["seed_base"]["power"] + 70_000 + 1000 * i + s) for s in range(40)])), 40)
            for i, sz in enumerate((0.33, 0.5, 0.67, 1.0))
        }  # fmt: skip
    out["accepted_by_family"] = {
        fam: all(v["per_family"][fam]["wilson95"][1] <= 0.03 for v in null.values()) for fam in BLOCK_FAMS
    }
    OUT_BLOCK.write_text(json.dumps(out, indent=1))
    return out
