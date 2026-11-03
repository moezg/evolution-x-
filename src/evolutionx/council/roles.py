"""Council roles: versioned system prompts + deterministic offline reasoning rules.

The offline rules only state observations backed by metric keys present in the
context, and phrase anything causal as a hypothesis. They are the MockLLM's
"model" so the full workflow runs without network access.
"""

from __future__ import annotations

from typing import Any

PROMPTS_V1: dict[str, str] = {
    "research_scientist": "You are the Research Scientist. Frame the research question, state falsifiable hypotheses "
    "and design controlled experiments (paired seeds, replicates).",
    "microstructure_analyst": "You are the Market Microstructure Analyst. Analyse spreads, depth, order flow, "
    "cross-venue gaps and liquidity provision.",
    "behavioral_scientist": "You are the Behavioral Scientist. Analyse herding, contagion, panic, imitation and "
    "heterogeneous beliefs across agent populations.",
    "macro_scenario_designer": "You are the Macro Scenario Designer. Propose exogenous shock scenarios that have not "
    "yet been tested and explain what mechanism each probes.",
    "adversarial_researcher": "You are the Adversarial Researcher. Attack the other roles' conclusions: sample size, "
    "confounders, unrealistic assumptions, look-ahead, overfitting.",
    "risk_researcher": "You are the Risk Researcher. Investigate fragility: liquidations, leverage, tail losses, "
    "insurance fund usage, cascade dynamics.",
    "evaluation_scientist": "You are the Evaluation Scientist. Assess realism against historical stylized facts and "
    "the validity of the experimental design.",
    "evolution_engineer": "You are the Evolution Engineer. Recommend which strategy family to evolve next and which "
    "constrained code change to propose; never touch protected code.",
}
COMMON = (
    " Separate OBSERVATIONS (directly measured, cite metric keys in `evidence`), HYPOTHESES (testable), "
    "ASSUMPTIONS and CONCLUSIONS (only what evidence supports). Never claim real-world probabilities from synthetic "
    "replicates. Output JSON matching RoleReport."
)
ROLE_TITLES = {
    "research_scientist": "Research Scientist",
    "microstructure_analyst": "Market Microstructure Analyst",
    "behavioral_scientist": "Behavioral Scientist",
    "macro_scenario_designer": "Macro Scenario Designer",
    "adversarial_researcher": "Adversarial Researcher",
    "risk_researcher": "Risk Researcher",
    "evaluation_scientist": "Evaluation Scientist",
    "evolution_engineer": "Evolution Engineer",
}


def _c(text: str, *ev: str) -> dict[str, Any]:
    return {"text": text, "evidence": list(ev)}


def _g(ctx: dict[str, Any], path: str, default: float = float("nan")) -> float:
    cur: Any = ctx
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur or cur[k] is None:
            return default
        cur = cur[k]
    return float(cur)


def _exp_line(ctx: dict[str, Any], key: str) -> tuple[float, float, float] | None:
    s = (ctx.get("experiment") or {}).get("summary", {}).get(key)
    if not s:
        return None
    d = s["paired_diff"]
    return d["mean"], d["lo"], d["hi"]


def research_scientist(ctx: dict[str, Any]) -> dict[str, Any]:
    exp = ctx.get("experiment") or {}
    obs = [
        _c(f"Market return over the observed run: {_g(ctx, 'market.return_pct'):+.2f}%", "market.return_pct"),
        _c(f"Max drawdown: {_g(ctx, 'market.max_drawdown_pct'):.2f}%", "market.max_drawdown_pct"),
    ]
    hyps = [_c("Shock responses are mediated by liquidity provision more than by the shock size itself.")]
    recs = [{"scenario": "liquidity_drought_70", "replicates": 12, "rationale": "Isolate the liquidity channel."}]
    if exp:
        line = _exp_line(ctx, "shock.min_after_pct")
        if line:
            obs.append(
                _c(
                    f"In '{exp['scenario']}' the paired difference in post-shock minimum is {line[0]:+.2f}% "
                    f"[{line[1]:+.2f}, {line[2]:+.2f}] over {exp['replicates']} replicates",
                    "experiment.summary.shock.min_after_pct",
                )
            )
        recs.append(
            {"scenario": exp["scenario"], "replicates": min(64, 2 * exp["replicates"]), "rationale": "Tighten CI."}
        )
    return {
        "role": "research_scientist",
        "observations": obs,
        "hypotheses": hyps,
        "assumptions": [_c("Agent behaviour rules are stationary within a run except for logged adaptations.")],
        "conclusions": [],
        "confidence": 0.5,
        "recommended_experiments": recs,
        "risks": ["Single-asset synthetic market; external validity limited."],
    }


def microstructure_analyst(ctx: dict[str, Any]) -> dict[str, Any]:
    sp, dp, gap = _g(ctx, "market.spread_bps_median"), _g(ctx, "market.depth_btc_median"), _g(ctx, "market.gap")
    obs = [
        _c(
            f"Median quoted spread {sp:.2f} bps (p95 {_g(ctx, 'market.spread_bps_p95'):.2f})",
            "market.spread_bps_median",
        ),
        _c(f"Median top-5 depth {dp:.1f} BTC", "market.depth_btc_median"),
        _c(f"Mean cross-venue mid gap {gap:.2f} bps", "market.cross_venue_gap_bps"),
        _c(
            f"Market-maker volatility withdrawals: {int(_g(ctx, 'collective.mm_withdrawals', 0))}",
            "collective.mm_withdrawals",
        ),
    ]
    hyps = [_c("Volatility-triggered quote withdrawal by market makers widens spreads exactly when depth is needed.")]
    line = _exp_line(ctx, "shock.spread_bps_window")
    if line:
        obs.append(
            _c(f"Shock-window spread change {line[0]:+.2f} bps [{line[1]:+.2f}, {line[2]:+.2f}]", "experiment.summary")
        )
    return {
        "role": "microstructure_analyst",
        "observations": obs,
        "hypotheses": hyps,
        "assumptions": [_c("Two venues with identical fee schedules; no hidden liquidity.")],
        "conclusions": [_c("Arbitrageurs keep venues aligned within a few bps in normal conditions.", "market.gap")]
        if gap == gap and gap < 10
        else [],
        "confidence": 0.6,
        "recommended_experiments": [
            {"scenario": "arb_outage", "replicates": 8, "rationale": "Measure venue divergence without arbitrage."}
        ],
        "risks": ["Depth is modest relative to real BTC venues; impact may be overstated."],
    }


def behavioral_scientist(ctx: dict[str, Any]) -> dict[str, Any]:
    col = ctx.get("collective", {})
    stance = col.get("stance_by_kind", {})
    spread = (max(stance.values()) - min(stance.values())) if stance else float("nan")
    obs = [
        _c(
            f"Influence (stance-flip-with-neighbours) events: {int(_g(ctx, 'market.influence_events', 0))}",
            "market.influence_events",
        ),
        _c(f"Retail panic events: {int(_g(ctx, 'collective.panic_events', 0))}", "collective.panic_events"),
        _c(
            f"Imitation (strategy copying) events: {int(_g(ctx, 'collective.imitation_events', 0))}",
            "collective.imitation_events",
        ),
        _c(f"Dispersion of mean stance across populations: {spread:.2f}", "collective.stance_by_kind"),
        _c(f"Wealth Gini: {_g(ctx, 'collective.gini'):.3f}", "collective.gini"),
    ]
    return {
        "role": "behavioral_scientist",
        "observations": obs,
        "hypotheses": [
            _c("Social contagion is concentrated in momentum/leveraged populations with high social weight."),
            _c("Imitation reduces strategy diversity over time, increasing correlated positioning."),
        ],
        "assumptions": [_c("The small-world network approximates real information diffusion among traders.")],
        "conclusions": [],
        "confidence": 0.45,
        "recommended_experiments": [
            {"scenario": "news_panic", "replicates": 12, "rationale": "Pure sentiment shock isolates contagion."}
        ],
        "risks": ["Influence events are a proxy, not causal identification of contagion."],
    }


def macro_scenario_designer(ctx: dict[str, Any]) -> dict[str, Any]:
    tried = set(ctx.get("experiments_run", []))
    untested = [s for s in ctx.get("scenarios", []) if s not in tried and s != "baseline"]
    return {
        "role": "macro_scenario_designer",
        "observations": [
            _c(f"Scenarios not yet tested: {', '.join(untested) or 'none'}", "scenarios", "experiments_run")
        ],
        "hypotheses": [_c("Combined shocks (funding spike during liquidity drought) produce non-additive responses.")],
        "assumptions": [_c("Shock magnitudes are stylised, not calibrated to specific historical events.")],
        "conclusions": [],
        "confidence": 0.4,
        "recommended_experiments": [
            {"scenario": s, "replicates": 8, "rationale": "Untested mechanism."} for s in untested[:3]
        ],
        "risks": ["Scenario library is hand-designed; tail scenarios outside it are unexplored."],
    }


def adversarial_researcher(ctx: dict[str, Any]) -> dict[str, Any]:
    exp = ctx.get("experiment") or {}
    attacks = []
    if exp:
        n = exp.get("replicates", 0)
        if n < 10:
            attacks.append(
                _c(
                    f"Only {n} replicates: confidence intervals are wide; effect sizes may be noise.",
                    "experiment.replicates",
                )
            )
        for k, v in exp.get("summary", {}).items():
            d = v["paired_diff"]
            if d["lo"] is not None and d["hi"] is not None and d["lo"] <= 0 <= d["hi"]:
                attacks.append(
                    _c(
                        f"'{k}' paired-difference CI includes zero: no evidence of an effect.",
                        f"experiment.summary.{k}",
                    )
                )
    else:
        attacks.append(_c("No controlled experiment in context: any causal claim is unsupported."))
    real = ctx.get("market", {}).get("realism", {}).get("detail", {})
    for k, v in real.items():
        if not v.get("inside"):
            attacks.append(
                _c(
                    f"Stylized fact '{k}' is outside the reference band: realism claims must be qualified.",
                    f"market.realism.{k}",
                )
            )
    return {
        "role": "adversarial_researcher",
        "observations": attacks[:12],
        "hypotheses": [_c("Some apparent effects stem from parameter choices in the population, not from the shock.")],
        "assumptions": [],
        "conclusions": [_c("All findings are conditional on a synthetic, uncalibrated agent population.")],
        "confidence": 0.7,
        "recommended_experiments": [
            {"scenario": exp.get("scenario", "btc_drop_5pct"), "replicates": 32, "rationale": "Power the test."}
        ],
        "risks": ["Selective reporting of significant metrics across many tested metrics (multiple comparisons)."],
    }


def risk_researcher(ctx: dict[str, Any]) -> dict[str, Any]:
    bk = ctx.get("market", {}).get("by_kind", {})
    lev = bk.get("leveraged", {})
    return {
        "role": "risk_researcher",
        "observations": [
            _c(f"Liquidations in observed run: {int(_g(ctx, 'market.liquidations', 0))}", "market.liquidations"),
            _c(
                f"Leveraged cohort CVaR(5%) return {lev.get('cvar5_return_pct', float('nan')):.2f}%",
                "market.by_kind.leveraged",
            ),
            _c(f"Insurance fund balance ${_g(ctx, 'state.insurance_fund_usd', 0):,.0f}", "state.insurance_fund_usd"),
        ],
        "hypotheses": [
            _c("Liquidation cascades require both high leverage and thin depth; either alone is insufficient.")
        ],
        "assumptions": [_c("Liquidations execute as immediate market orders with no auction or ADL.")],
        "conclusions": [],
        "confidence": 0.5,
        "recommended_experiments": [
            {"scenario": "whale_liquidation", "replicates": 12, "rationale": "Measure cascade propagation."}
        ],
        "risks": ["Insurance fund can go negative (socialised loss is not modelled)."],
    }


def evaluation_scientist(ctx: dict[str, Any]) -> dict[str, Any]:
    real = ctx.get("market", {}).get("realism", {})
    det = real.get("detail", {})
    obs = [_c(f"Realism: {real.get('score', 0):.0%} of stylized facts inside historical bands", "market.realism.score")]
    for k, v in det.items():
        if v.get("value") is not None:
            obs.append(
                _c(f"{k} = {v['value']:.3f} vs band [{v['band'][0]:.3f}, {v['band'][1]:.3f}]", f"market.realism.{k}")
            )
    std = _g(ctx, "market.facts.ret_std_bps")
    hist_std = _g(ctx, "historical_ret_std_bps")
    if std == std and hist_std == hist_std:
        obs.append(
            _c(f"1-min return volatility {std:.1f} bps vs historical {hist_std:.1f} bps", "market.facts.ret_std_bps")
        )
    return {
        "role": "evaluation_scientist",
        "observations": obs[:12],
        "hypotheses": [_c("Excess simulated volatility comes from thin depth relative to order sizes.")],
        "assumptions": [_c("Historical bands from the TRAIN split are representative of normal regimes.")],
        "conclusions": [_c("Realism is partial; volatility level is not yet calibrated.", "market.facts.ret_std_bps")]
        if std == std and hist_std == hist_std and std > 2 * hist_std
        else [],
        "confidence": 0.65,
        "recommended_experiments": [],
        "risks": ["Short runs yield few 1-minute returns; fact estimates are noisy."],
    }


def evolution_engineer(ctx: dict[str, Any]) -> dict[str, Any]:
    bk = ctx.get("market", {}).get("by_kind", {})
    worst = min(bk.items(), key=lambda kv: kv[1].get("cvar5_return_pct", 0))[0] if bk else "momentum"
    evo = ctx.get("evolution", {})
    return {
        "role": "evolution_engineer",
        "observations": [
            _c(f"Population with worst tail outcome (CVaR5): {worst}", "market.by_kind"),
            _c(
                f"Champion/challenger decisions so far: {evo.get('n_challenges', 0)} "
                f"({evo.get('n_promoted', 0)} promoted)",
                "evolution",
            ),
        ],
        "hypotheses": [_c(f"Evolving '{worst}' risk parameters can reduce tail losses without harming realism.")],
        "assumptions": [_c("Bounded parameter ranges contain better-than-default settings.")],
        "conclusions": [],
        "confidence": 0.4,
        "recommended_experiments": [],
        "risks": ["Optimising a cohort can degrade market realism; realism gate must stay enforced."],
    }


RULES = {
    "research_scientist": research_scientist,
    "microstructure_analyst": microstructure_analyst,
    "behavioral_scientist": behavioral_scientist,
    "macro_scenario_designer": macro_scenario_designer,
    "adversarial_researcher": adversarial_researcher,
    "risk_researcher": risk_researcher,
    "evaluation_scientist": evaluation_scientist,
    "evolution_engineer": evolution_engineer,
}
