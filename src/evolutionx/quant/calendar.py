"""Systematic calendar-pattern scanner (H1) - families F-DOM, F-DOW, F-MOY, F-TOM of quant_protocol_v1.

Daily BTC close-to-close returns (Binance spot, UTC candles). For every label of a family (e.g. each day 1..31) and
every metric, the in-label value is compared with all other days. Dependence-preserving rotation tests give the
null; BH (q 0.10) on DISCOVERY selects exploratory survivors; survivors are re-tested once on CONFIRMATION,
one-sided in the discovery direction, with Holm (alpha 0.05). The 14th is always reported in full.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .data import DAY, load_btc
from .events import Registry
from .stats import TestRegistry, bh, holm

PROTOCOL = Path("evals/frozen/quant_protocol_v1.json")
METRICS = ("mean_ret", "mean_absret", "up_rate", "left_tail_rate")
N_ROT = 999


def protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL.read_text())


def protocol_sha() -> str:
    return hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()


def daily_frame() -> dict[str, np.ndarray]:
    s = load_btc("1d")
    r = np.r_[np.nan, np.diff(np.log(s.close))]
    r[np.r_[False, np.diff(s.t) != DAY]] = np.nan  # a gap breaks the return; it is not filled
    days = [dt.datetime.fromtimestamp(t / 1000, dt.UTC).date() for t in s.t]
    nxt = [d + dt.timedelta(days=1) for d in days]
    return {
        "t": s.t,
        "date": np.array([d.isoformat() for d in days]),
        "ret": r,
        "dom": np.array([d.day for d in days]),
        "dow": np.array([d.weekday() for d in days]),
        "moy": np.array([d.month for d in days]),
        "tom": np.array([int(d.day <= 3 or n.month != d.month) for d, n in zip(days, nxt, strict=True)]),
    }


def _period(f: dict[str, np.ndarray], name: str) -> np.ndarray:
    a, b = protocol()["periods"][name]
    return (f["date"] >= a) & (f["date"] <= b) & np.isfinite(f["ret"])


def _stats(x: np.ndarray, lab: np.ndarray, values: np.ndarray, q05: float) -> np.ndarray:
    """matrix [label, metric] of (in-label - out-of-label) for all labels at once."""
    out = np.empty((len(values), len(METRICS)))
    cols = (x, np.abs(x), (x > 0).astype(float), (x < q05).astype(float))
    for j, c in enumerate(cols):
        tot, n = c.sum(), len(c)
        for i, v in enumerate(values):
            m = lab == v
            k = m.sum()
            out[i, j] = c[m].mean() - (tot - c[m].sum()) / (n - k) if 0 < k < n else np.nan
    return out


def scan(
    f: dict[str, np.ndarray],
    family: str,
    period: str,
    adjust_weekday: bool,
    seed: int = 0,
    exclude: np.ndarray | None = None,
) -> dict[str, Any]:
    key = {"F-DOM": "dom", "F-DOW": "dow", "F-MOY": "moy", "F-TOM": "tom"}[family]
    m = _period(f, period) & (np.ones(len(f["ret"]), bool) if exclude is None else ~exclude)
    x, lab = f["ret"][m].copy(), f[key][m]
    if (
        adjust_weekday
    ):  # remove weekday means estimated in the same period (weekend effects are not day-of-month effects)
        wd = f["dow"][m]
        for d in range(7):
            x[wd == d] -= x[wd == d].mean()
    values = np.unique(lab) if key != "tom" else np.array([1])
    q05 = float(np.quantile(x, 0.05))
    obs = _stats(x, lab, values, q05)
    rng = np.random.default_rng(seed)
    bad = {"dow": 7, "moy": 365, "dom": 0, "tom": 0}[key]
    shifts = []
    while len(shifts) < N_ROT:
        k = int(rng.integers(31, len(x) - 31))
        if bad and min(k % bad, bad - k % bad) <= (0 if bad == 7 else 3):
            continue
        shifts.append(k)
    null = np.stack([_stats(np.roll(x, k), lab, values, q05) for k in shifts])
    p_emp = (1 + np.sum(np.abs(null) >= np.abs(obs)[None] - 1e-15, axis=0)) / (N_ROT + 1)
    # amendment 2: continuous p from the rotation null's mean/sd (the empirical p cannot go below 1/(N+1))
    mu, sd = null.mean(0), null.std(0)
    z = (obs - mu) / np.where(sd > 0, sd, np.nan)
    p_two, p_up, p_dn = (
        _erfc_arr(np.abs(z) / np.sqrt(2)),
        0.5 * _erfc_arr(z / np.sqrt(2)),
        0.5 * _erfc_arr(-z / np.sqrt(2)),
    )
    counts = {int(v): int((lab == v).sum()) for v in values}
    rows = []
    for i, v in enumerate(values):
        for j, met in enumerate(METRICS):
            sd = float(np.std(null[:, i, j]))
            rows.append(
                {
                    "label": int(v),
                    "metric": met + ("_wd_adj" if adjust_weekday and met == "mean_ret" else ""),
                    "n": counts[int(v)],
                    "n_ref": int(len(x) - counts[int(v)]),
                    "effect": float(obs[i, j]),
                    "null_sd": sd,
                    "ci_lo": float(obs[i, j] - 1.96 * sd),
                    "ci_hi": float(obs[i, j] + 1.96 * sd),
                    "p": float(p_two[i, j]),
                    "p_rotation_empirical": float(p_emp[i, j]),
                    "z": float(z[i, j]),
                    "p_up": float(p_up[i, j]),
                    "p_down": float(p_dn[i, j]),
                }
            )
    return {"family": family, "period": period, "n_days": int(len(x)), "rows": rows, "q05": q05}


_erfc = np.frompyfunc(math.erfc, 1, 1)


def _erfc_arr(x: np.ndarray) -> np.ndarray:
    return np.asarray(_erfc(x), dtype=float)


def macro_exclusion_mask(f: dict[str, np.ndarray]) -> np.ndarray:
    """FOMC final days (+1) and U.S. election days (+1) - for sensitivity checks."""
    reg = Registry()
    days: set[str] = set()
    for e in reg.current("fomc") + reg.current("us_election"):
        d = dt.date.fromisoformat(e["event_time_utc"][:10])
        days |= {d.isoformat(), (d + dt.timedelta(days=1)).isoformat()}
    return np.isin(f["date"], sorted(days))


def run(
    run_id: str, families: tuple[str, ...] = ("F-DOM", "F-DOW", "F-MOY", "F-TOM"), reg: TestRegistry | None = None
) -> dict[str, Any]:
    reg = reg or TestRegistry()
    f = daily_frame()
    sha = hashlib.sha256(f["ret"][np.isfinite(f["ret"])].tobytes()).hexdigest()[:16]
    psha = protocol_sha()
    out: dict[str, Any] = {"run_id": run_id, "data_sha": sha, "families": {}}
    excl = macro_exclusion_mask(f)
    for fam in families:
        adj = fam != "F-DOW"
        disc = scan(f, fam, "DISCOVERY", adj)

        def name(r: dict[str, Any], fam: str = fam) -> str:
            return f"{fam}:{r['label']}:{r['metric']}"

        b = bh({name(r): r["p"] for r in disc["rows"]}, 0.10)
        survivors = [r for r in disc["rows"] if b[name(r)]["reject"]]
        conf = scan(f, fam, "CONFIRMATION", adj)
        cmap = {name(r): r for r in conf["rows"]}
        one_sided = {
            name(r): (cmap[name(r)]["p_up"] if r["effect"] > 0 else cmap[name(r)]["p_down"]) for r in survivors
        }
        h = holm(one_sided, 0.05)
        sens = scan(f, fam, "DISCOVERY", adj, exclude=excl)
        smap = {name(r): r for r in sens["rows"]}
        results = []
        for r in disc["rows"]:
            k = name(r)
            c = cmap[k]  # the confirmation scan covers the same labels and metrics
            st = "rejected"
            if b[k]["reject"]:
                ok = h.get(k, {}).get("reject") and np.sign(c["effect"]) == np.sign(r["effect"]) and c["n"] >= 20
                st = "supported" if ok else "inconclusive"
            res = {
                **r,
                "hypothesis": k,
                "p_bh": b[k]["p_adj"],
                "status": st,
                "confirmation": c,
                "confirm_p_one_sided": one_sided.get(k),
                "confirm_holm": h.get(k),
                "excl_macro_effect": smap[k]["effect"],
            }
            results.append(res)
            reg.record(
                {
                    "family": fam,
                    "hypothesis": k,
                    "role": "H1",
                    "method": "rotation null (999 circular shifts), normal-approx p (amendment 2) + BH(0.10)",
                    "period": "DISCOVERY",
                    "n": r["n"],
                    "n_ref": r["n_ref"],
                    "effect": r["effect"],
                    "ci_lo": r["ci_lo"],
                    "ci_hi": r["ci_hi"],
                    "p": r["p"],
                    "p_adj": b[k]["p_adj"],
                    "adj_method": f"BH within {fam} ({len(disc['rows'])} tests)",
                    "status": st,
                    "direction": int(np.sign(r["effect"])),
                    "data_sha": sha,
                    "protocol_sha": psha,
                    "run_id": run_id,
                }
            )
            if k in one_sided:
                reg.record(
                    {
                        "family": fam,
                        "hypothesis": k,
                        "role": "E2",
                        "method": "rotation test one-sided + Holm(0.05) over survivors",
                        "period": "CONFIRMATION",
                        "n": c["n"],
                        "n_ref": c["n_ref"],
                        "effect": c["effect"],
                        "ci_lo": c["ci_lo"],
                        "ci_hi": c["ci_hi"],
                        "p": one_sided[k],
                        "p_adj": h[k]["p_adj"],
                        "adj_method": f"Holm over {len(one_sided)} survivors",
                        "status": st,
                        "direction": int(np.sign(r["effect"])),
                        "data_sha": sha,
                        "protocol_sha": psha,
                        "run_id": run_id,
                    }
                )
        out["families"][fam] = {
            "tests": len(disc["rows"]),
            "n_days": {"DISCOVERY": disc["n_days"], "CONFIRMATION": conf["n_days"]},
            "discovery_survivors_bh": [x["hypothesis"] for x in results if x["status"] != "rejected"],
            "supported": [x["hypothesis"] for x in results if x["status"] == "supported"],
            "results": results,
        }
    out["day14"] = day14_report(f, out["families"].get("F-DOM", {}).get("results", []))
    return out


def day14_report(f: dict[str, np.ndarray], dom_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The named question 'is the 14th unusual?' with yearly stability (descriptive)."""
    rows = [r for r in dom_rows if r["label"] == 14]
    m = (f["dom"] == 14) & np.isfinite(f["ret"])
    years = {}
    for y in sorted({d[:4] for d in f["date"][m]}):
        ym = m & np.char.startswith(f["date"].astype(str), y)
        oth = (f["dom"] != 14) & np.isfinite(f["ret"]) & np.char.startswith(f["date"].astype(str), y)
        years[y] = {
            "n": int(ym.sum()),
            "mean_ret_14": float(f["ret"][ym].mean()),
            "mean_ret_other": float(f["ret"][oth].mean()),
            "mean_absret_14": float(np.abs(f["ret"][ym]).mean()),
            "mean_absret_other": float(np.abs(f["ret"][oth]).mean()),
        }
    return {
        "reference": "BTCUSDT spot daily candle of the 14th (00:00-24:00 UTC), close-to-close log return; weekday-adjusted for the mean metric",
        "tests": rows,
        "by_year": years,
        "multiple_testing": "the 14th is one of 31 days x 4 metrics = 124 tests in F-DOM",
    }


# ----------------------------------------------------------------------------- amendment 4: F-DOW within-week permutation
N_WEEKPERM = 4999


def scan_dow_weekperm(f: dict[str, np.ndarray], period: str, seed: int = 0) -> dict[str, Any]:
    """F-DOW with a within-week label permutation null (complete Monday-Sunday weeks only)."""
    m = _period(f, period)
    dates = f["date"][m]
    x_all, dow = f["ret"][m], f["dow"][m]
    ordn = np.array([dt.date.fromisoformat(d).toordinal() for d in dates])
    wk = ordn - dow  # Monday ordinal of each day's week
    keep = np.isin(wk, [w for w, c in zip(*np.unique(wk, return_counts=True), strict=True) if c == 7])
    x, d, w = x_all[keep], dow[keep], wk[keep]
    order = np.lexsort((d, w))
    X = x[order].reshape(-1, 7)  # rows = weeks, columns = Mon..Sun
    q05 = float(np.quantile(X, 0.05))
    mats = np.stack([X, np.abs(X), (X > 0).astype(float), (X < q05).astype(float)])  # noqa: SIM300 - metric, week, weekday

    def eff(M: np.ndarray) -> np.ndarray:  # [metric, weekday]: mean(d) - mean(other six)
        col = M.mean(axis=1)
        tot = col.sum(axis=1, keepdims=True)
        return col - (tot - col) / 6

    obs = eff(mats)
    rng = np.random.default_rng(seed)
    null = np.empty((N_WEEKPERM, *obs.shape))
    rows_idx = np.arange(X.shape[0])[:, None]
    for i in range(N_WEEKPERM):
        p = np.argsort(rng.random(X.shape), axis=1)
        null[i] = eff(mats[:, rows_idx, p])
    mu = null.mean(0)
    p_two = (1 + np.sum(np.abs(null - mu) >= np.abs(obs - mu)[None] - 1e-15, axis=0)) / (N_WEEKPERM + 1)
    p_up = (1 + np.sum(null >= obs[None] - 1e-15, axis=0)) / (N_WEEKPERM + 1)
    p_dn = (1 + np.sum(null <= obs[None] + 1e-15, axis=0)) / (N_WEEKPERM + 1)
    sd = null.std(0)
    rows = []
    for j, met in enumerate(METRICS):
        for lab in range(7):
            rows.append(
                {
                    "label": lab, "metric": met, "n": int(X.shape[0]), "n_ref": int(6 * X.shape[0]),
                    "effect": float(obs[j, lab]), "null_sd": float(sd[j, lab]),
                    "ci_lo": float(obs[j, lab] - 1.96 * sd[j, lab]), "ci_hi": float(obs[j, lab] + 1.96 * sd[j, lab]),
                    "p": float(p_two[j, lab]), "p_up": float(p_up[j, lab]), "p_down": float(p_dn[j, lab]),
                    "z": float((obs[j, lab] - mu[j, lab]) / sd[j, lab]) if sd[j, lab] > 0 else float("nan"),
                }
            )  # fmt: skip
    return {
        "family": "F-DOW",
        "period": period,
        "n_weeks": int(X.shape[0]),
        "rows": rows,
        "q05": q05,
        "method": "within-week permutation (amendment 4)",
    }


def run_dow_amendment4(run_id: str, reg: TestRegistry | None = None) -> dict[str, Any]:
    """Registered F-DOW re-run under amendment 4 (only after its synthetic acceptance passed)."""
    acc = Path("artifacts/quant/calibration_dow_weekperm.json")
    if not acc.exists() or not json.loads(acc.read_text()).get("accepted"):
        raise RuntimeError("amendment 4 method has not passed its synthetic acceptance; F-DOW has no valid method")
    reg = reg or TestRegistry()
    f = daily_frame()
    sha = hashlib.sha256(f["ret"][np.isfinite(f["ret"])].tobytes()).hexdigest()[:16]
    disc = scan_dow_weekperm(f, "DISCOVERY")
    conf = scan_dow_weekperm(f, "CONFIRMATION")
    name = lambda r: f"F-DOW:{r['label']}:{r['metric']}"  # noqa: E731
    b = bh({name(r): r["p"] for r in disc["rows"]}, 0.10)
    cmap = {name(r): r for r in conf["rows"]}
    surv = [r for r in disc["rows"] if b[name(r)]["reject"]]
    one = {name(r): (cmap[name(r)]["p_up"] if r["effect"] > 0 else cmap[name(r)]["p_down"]) for r in surv}
    h = holm(one, 0.05)
    results = []
    for r in disc["rows"]:
        k, c = name(r), cmap[name(r)]
        st = "rejected"
        if b[k]["reject"]:
            ok = h[k]["reject"] and np.sign(c["effect"]) == np.sign(r["effect"]) and c["n"] >= 20
            st = "supported" if ok else "inconclusive"
        common = {"family": "F-DOW", "hypothesis": k, "status": st, "direction": int(np.sign(r["effect"])), "data_sha": sha, "protocol_sha": protocol_sha(), "run_id": run_id}  # fmt: skip
        reg.record({**common, "role": "H1", "method": "within-week permutation (4999) + BH(0.10) [amendment 4]", "period": "DISCOVERY", "n": r["n"], "n_ref": r["n_ref"], "effect": r["effect"], "ci_lo": r["ci_lo"], "ci_hi": r["ci_hi"], "p": r["p"], "p_adj": b[k]["p_adj"], "adj_method": "BH within F-DOW (28)", "details": {"unit": "weeks", "supersedes": "rotation-method F-DOW rows (amendment 4)"}})  # fmt: skip
        if k in one:
            reg.record({**common, "role": "E2", "method": "within-week permutation one-sided + Holm(0.05) [amendment 4]", "period": "CONFIRMATION", "n": c["n"], "n_ref": c["n_ref"], "effect": c["effect"], "ci_lo": c["ci_lo"], "ci_hi": c["ci_hi"], "p": one[k], "p_adj": h[k]["p_adj"], "adj_method": f"Holm over {len(one)} survivors"})  # fmt: skip
        results.append({"hypothesis": k, "status": st, "disc_effect": r["effect"], "disc_p": r["p"], "p_bh": b[k]["p_adj"], "conf_effect": c["effect"], "conf_p_one_sided": one.get(k), "conf_holm": h.get(k)})  # fmt: skip
    return {
        "run_id": run_id,
        "data_sha": sha,
        "weeks": {"DISCOVERY": disc["n_weeks"], "CONFIRMATION": conf["n_weeks"]},
        "results": results,
    }


# ----------------------------------------------------------------------------- amendment 6: within-block permutation
N_BLOCKPERM = 4999


def scan_blockperm(
    f: dict[str, np.ndarray], family: str, period: str, adjust_weekday: bool = True, seed: int = 0
) -> dict[str, Any]:
    """F-DOM / F-TOM: day labels permuted within calendar months; F-MOY: month labels permuted within years."""
    key = {"F-DOM": "dom", "F-MOY": "moy", "F-TOM": "tom"}[family]
    m = _period(f, period)
    x, lab, dates = f["ret"][m].copy(), f[key][m], f["date"][m]
    if adjust_weekday:
        wd = f["dow"][m]
        for d in range(7):
            x[wd == d] -= x[wd == d].mean()
    values = np.unique(lab) if key != "tom" else np.array([1])
    q05 = float(np.quantile(x, 0.05))
    cols = np.stack([x, np.abs(x), (x > 0).astype(float), (x < q05).astype(float)])  # noqa: SIM300
    n = len(x)
    tot = cols.sum(axis=1)
    vmax = int(values.max()) + 1

    def stats(lb: np.ndarray) -> np.ndarray:  # [label, metric]
        cnt = np.bincount(lb, minlength=vmax)[values]
        s = np.stack([np.bincount(lb, weights=c, minlength=vmax)[values] for c in cols], axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            return s / cnt[:, None] - (tot[None] - s) / (n - cnt)[:, None]

    lab_i = lab.astype(int)
    obs = stats(lab_i)
    rng = np.random.default_rng(seed)
    month_id = np.unique(np.array([d[:7] for d in dates]), return_inverse=True)[1]
    year = np.array([int(d[:4]) for d in dates])
    null = np.empty((N_BLOCKPERM, *obs.shape))
    if key in ("dom", "tom"):  # dates are sorted, so months are contiguous blocks
        for i in range(N_BLOCKPERM):
            order = np.lexsort((rng.random(n), month_id))
            null[i] = stats(lab_i[order])
    else:
        units = np.unique(month_id)
        unit_year = np.array([year[month_id == u][0] for u in units])
        unit_lab = np.array([lab_i[month_id == u][0] for u in units])
        for i in range(N_BLOCKPERM):
            new = unit_lab.copy()
            for y in np.unique(unit_year):
                idx = np.where(unit_year == y)[0]
                new[idx] = unit_lab[rng.permutation(idx)]
            null[i] = stats(new[month_id])
    mu = np.nanmean(null, axis=0)
    p_two = (1 + np.sum(np.abs(null - mu) >= np.abs(obs - mu)[None] - 1e-15, axis=0)) / (N_BLOCKPERM + 1)
    p_up = (1 + np.sum(null >= obs[None] - 1e-15, axis=0)) / (N_BLOCKPERM + 1)
    p_dn = (1 + np.sum(null <= obs[None] + 1e-15, axis=0)) / (N_BLOCKPERM + 1)
    sd = np.nanstd(null, axis=0)
    counts = {int(v): int((lab_i == v).sum()) for v in values}
    rows = []
    for i, v in enumerate(values):
        for j, met in enumerate(METRICS):
            rows.append(
                {
                    "label": int(v), "metric": met + ("_wd_adj" if adjust_weekday and met == "mean_ret" else ""),
                    "n": counts[int(v)], "n_ref": n - counts[int(v)], "effect": float(obs[i, j]), "null_sd": float(sd[i, j]),
                    "ci_lo": float(obs[i, j] - 1.96 * sd[i, j]), "ci_hi": float(obs[i, j] + 1.96 * sd[i, j]),
                    "p": float(p_two[i, j]), "p_up": float(p_up[i, j]), "p_down": float(p_dn[i, j]),
                }
            )  # fmt: skip
    return {
        "family": family,
        "period": period,
        "n_days": n,
        "rows": rows,
        "q05": q05,
        "method": "within-block permutation (amendment 6)",
    }


def run_blockperm_amendment6(run_id: str, reg: TestRegistry | None = None) -> dict[str, Any]:
    """Registered F-DOM/F-MOY/F-TOM re-run under amendment 6 (only for families that passed acceptance)."""
    acc = Path("artifacts/quant/calibration_blockperm.json")
    ok = json.loads(acc.read_text()).get("accepted_by_family", {}) if acc.exists() else {}
    reg = reg or TestRegistry()
    f = daily_frame()
    sha = hashlib.sha256(f["ret"][np.isfinite(f["ret"])].tobytes()).hexdigest()[:16]
    out: dict[str, Any] = {"run_id": run_id, "data_sha": sha, "families": {}}
    for fam in ("F-DOM", "F-MOY", "F-TOM"):
        if not ok.get(fam):
            out["families"][fam] = "no valid method (acceptance failed)"
            continue
        disc, conf = scan_blockperm(f, fam, "DISCOVERY"), scan_blockperm(f, fam, "CONFIRMATION")
        name = lambda r, fam=fam: f"{fam}:{r['label']}:{r['metric']}"  # noqa: E731
        b = bh({name(r): r["p"] for r in disc["rows"]}, 0.10)
        cmap = {name(r): r for r in conf["rows"]}
        surv = [r for r in disc["rows"] if b[name(r)]["reject"]]
        one = {name(r): (cmap[name(r)]["p_up"] if r["effect"] > 0 else cmap[name(r)]["p_down"]) for r in surv}
        h = holm(one, 0.05)
        res = []
        for r in disc["rows"]:
            k, c = name(r), cmap[name(r)]
            st = "rejected"
            if b[k]["reject"]:
                st = (
                    "supported"
                    if h[k]["reject"] and np.sign(c["effect"]) == np.sign(r["effect"]) and c["n"] >= 20
                    else "inconclusive"
                )
            common = {"family": fam, "hypothesis": k, "status": st, "direction": int(np.sign(r["effect"])), "data_sha": sha, "protocol_sha": protocol_sha(), "run_id": run_id}  # fmt: skip
            reg.record({**common, "role": "H1", "method": "within-block permutation (4999) + BH(0.10) [amendment 6]", "period": "DISCOVERY", "n": r["n"], "n_ref": r["n_ref"], "effect": r["effect"], "ci_lo": r["ci_lo"], "ci_hi": r["ci_hi"], "p": r["p"], "p_adj": b[k]["p_adj"], "adj_method": f"BH within {fam} ({len(disc['rows'])})", "details": {"supersedes": "rotation-method rows (amendment 6)"}})  # fmt: skip
            if k in one:
                reg.record({**common, "role": "E2", "method": "within-block permutation one-sided + Holm(0.05) [amendment 6]", "period": "CONFIRMATION", "n": c["n"], "n_ref": c["n_ref"], "effect": c["effect"], "ci_lo": c["ci_lo"], "ci_hi": c["ci_hi"], "p": one[k], "p_adj": h[k]["p_adj"], "adj_method": f"Holm over {len(one)} survivors"})  # fmt: skip
            res.append({"hypothesis": k, "status": st, "effect": r["effect"], "p": r["p"], "p_bh": b[k]["p_adj"], "conf_effect": c["effect"], "conf_p_one_sided": one.get(k)})  # fmt: skip
        out["families"][fam] = {"tests": len(res), "survivors_bh": [x["hypothesis"] for x in res if x["status"] != "rejected"], "supported": [x["hypothesis"] for x in res if x["status"] == "supported"], "day14": [x for x in res if x["hypothesis"].startswith("F-DOM:14:")], "results": res}  # fmt: skip
    return out
