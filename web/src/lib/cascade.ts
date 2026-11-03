/** Types + helpers for the Liquidation Cascade Laboratory (/api/observatory/cascade*, /api/observatory/knowledge). SYNTHETIC research output. */
import type { Paired, Tone } from "./observatory";

/* ---------------------------------------------------------------- protocol */

export interface CascadeAmendment {
  written_utc?: string;
  before?: string;
  finding?: string;
  pilot_feasibility_findings?: string[];
  change?: string;
  exploratory_followup_declared_now?: string;
}

export interface CascadeProtocol {
  name: string;
  written_utc?: string;
  status?: string;
  question: string;
  valid_outcomes?: string[];
  data_policy?: string;
  inspection_facts_before_design?: Record<string, string>;
  design?: {
    duration_s?: number;
    shock_at_s?: number;
    whale_btc?: number[];
    leverage_use?: number[];
    arms?: Record<string, string>;
    pilot?: { seeds?: number[]; runs?: number; role?: string };
    confirmatory?: { seeds?: number[]; runs?: number };
    pairing?: string;
    population?: string;
    [k: string]: unknown;
  };
  causal_definitions?: Record<string, string>;
  hypotheses?: Record<string, { claim?: string; supported_if?: string; null_H0?: string; report?: string }>;
  classification_per_configuration?: string[];
  classification_rule?: string;
  statistics?: string;
  stopping_rule?: string;
  amendment_1?: CascadeAmendment;
  amendment_2?: CascadeAmendment;
}

export interface CascadeProtocolX {
  name: string;
  written_utc?: string;
  status?: string;
  motivation?: string;
  explanation_under_test?: string;
  X1_positioning?: { design?: string; conditions?: Record<string, Record<string, unknown>>; measure?: string; prediction?: string; refuted_if?: string };
  X2_cascade_with_channel_removed?: { design?: string; nature?: string; measure_and_rules?: string; prediction?: string; refuted_if?: string };
}

/* ---------------------------------------------------------------- reports */

export type Classification = "no_secondary_liquidations" | "secondary_without_amplification" | "amplification_without_chain" | "cascade" | string;

export interface CascadePair {
  seed: number;
  secondary_liquidations_A?: number;
  secondary_breaches_A?: number;
  secondary_breaches_B?: number;
  induced_breaches?: number[];
  chain_observed?: boolean;
  drop_A?: number;
  drop_B?: number;
  incremental_drop?: number;
  incremental_at?: Record<string, number>;
  direct_impact_A?: number;
  direct_impact_B?: number;
  first_divergence_s?: number | null;
  pre_shock_identical?: boolean;
  stop_losses_A?: number;
  stop_losses_B?: number;
}

export interface CascadeConfig {
  whale_btc: number;
  leverage_use: number;
  n_seeds: number;
  seeds_with_secondary_liquidation: number;
  wilson95?: [number, number];
  seeds_with_chain: number;
  incremental_drop?: Paired;
  incremental_at?: Record<string, Paired>;
  /** NB: despite the name this is the mean arm-B maximum adverse move (drop_B), the causal baseline. */
  armB_max_drop_mean?: number;
  direct_impact_mean?: number;
  secondary_liquidations_mean?: number;
  secondary_breaches_A_mean?: number;
  secondary_breaches_B_mean?: number;
  stop_losses_A_mean?: number;
  min_margin_distance_leveraged_down?: (number | null)[];
  whale_position_btc_at_shock?: number[];
  all_pre_shock_identical?: boolean;
  classification?: { label: Classification; criteria?: Record<string, boolean> };
  pairs?: CascadePair[];
}

export interface CascadeThreshold {
  seeds_with_secondary_by_size?: Record<string, number>;
  onset_bracket_btc?: [number | null, number | null] | number[] | null;
  statement?: string;
  monotone_in_size?: boolean;
  shape?: string;
}

export interface RunIndexRow {
  config: string;
  arm: string;
  seed: number;
  role: string;
  whale_btc: number;
  leverage_use: number;
  run_fingerprint: string;
  config_fingerprint: string;
}

export interface CascadeCost {
  runs?: number;
  wall_s?: number;
  cpu_s_sum?: number;
  llm_calls?: number;
}

export interface CascadeReport {
  protocol?: string;
  protocol_sha256?: string;
  role?: string;
  label?: string;
  created_utc?: string;
  cost?: CascadeCost;
  configs: Record<string, CascadeConfig>;
  threshold?: Record<string, CascadeThreshold>;
  run_index: RunIndexRow[];
}

export interface X1Run {
  condition: string;
  seed: number;
  leveraged_long: number;
  leveraged_short: number;
  leveraged_flat?: number;
  min_down_distance_longs?: number | null;
  eff_leverage_longs?: number[];
  funding_path?: number[];
}

export interface DeleveragingPoint {
  t_s: number;
  mid_rel?: number;
  leveraged_longs?: number;
  long_gross_usd_m?: number;
  min_down_distance?: number | null;
}

export interface DeleveragingTrace {
  condition: string;
  seed: number;
  path: DeleveragingPoint[];
  leveraged_equity_usd_m_end?: number;
}

export interface ExploratoryReport {
  protocol?: string;
  protocol_sha256?: string;
  label?: string;
  created_utc?: string;
  cost?: CascadeCost;
  X1?: { runs: X1Run[]; mean_leveraged_long?: Record<string, number>; selected_for_X2?: string };
  X2?: {
    configs?: Record<string, CascadeConfig>;
    threshold?: Record<string, CascadeThreshold>;
    deleveraging_traces?: DeleveragingTrace[];
    scale_check?: { leveraged_max_gross_usd_m_at_initial_capital?: number[]; primary_forced_notional_usd_m?: number[] };
  };
  run_index: RunIndexRow[];
}

export interface CascadeResp {
  protocol: CascadeProtocol;
  protocol_exploratory: CascadeProtocolX;
  confirmatory: CascadeReport | null;
  pilot: CascadeReport | null;
  exploratory: ExploratoryReport | null;
}

/* ---------------------------------------------------------------- one run (pair endpoint) */

export interface TraceEvent {
  t: number;
  type: "primary_liquidation" | "secondary_liquidation" | "breach" | "stop_loss" | string;
  agent: number;
  kind?: string;
  generation?: number;
  executed?: boolean;
  mid_rel?: number;
}

export interface LeveragedMargin {
  agent: number;
  distance: number;
  direction: "up" | "down" | string;
  eff_leverage: number;
}

export interface CascadeRun {
  config: string;
  arm: string;
  seed: number;
  role: string;
  whale_btc: number;
  leverage_use: number;
  whale_position_btc_at_shock?: number;
  pre_mid?: number;
  primary_liquidation_t: number;
  primary_forced_notional_usd?: number;
  primary_closed_btc?: number;
  primary_selling?: { first_t?: number | null; last_t?: number | null; duration_s?: number | null; btc?: number; mid_rel_at_end?: number | null; btc_per_10s?: number[] };
  direct_impact?: number;
  mid_rel_at?: Record<string, number>;
  max_adverse_move?: number;
  trough_t?: number;
  half_recovery_s?: number | null;
  half_recovery_censored?: boolean;
  secondary_breaches?: number;
  secondary_breach_agents?: number[];
  secondary_liquidations?: number;
  secondary_liquidated_agents?: number[];
  secondary_forced_notional_usd?: number;
  first_secondary_breach_s?: number | null;
  first_secondary_liquidation_s?: number | null;
  max_breach_generation?: number;
  propagation_10s?: { breaches?: number[]; secondary_liquidations?: number[] };
  margin_pre?: {
    n_accounts_with_positions?: number;
    min_distance_all?: number | null;
    quantiles_all?: number[] | null;
    leveraged?: LeveragedMargin[];
    min_distance_leveraged_down?: number | null;
    histogram_edges?: number[];
    histogram_all?: number[];
  };
  depth?: Record<string, unknown>;
  volatility_1m_bps?: { pre?: number | null; window?: number | null };
  spread_median_bps?: { pre?: number | null; window?: number | null };
  circuit_breakers_window?: number;
  stop_losses_leveraged?: number;
  panic_sales?: number;
  trace?: TraceEvent[];
  trajectory?: { t0_ms: number; mid_rel: number[] };
  run_fingerprint?: string;
  config_fingerprint?: string;
}

export interface PairResp {
  config: string;
  seed: number;
  role: string;
  arms: { A?: CascadeRun; B?: CascadeRun };
}

/* ---------------------------------------------------------------- knowledge */

export interface Mechanism {
  id: string;
  statement: string;
  status: string;
  evidence?: unknown;
  classification?: string;
  updated?: string;
}

export interface Proposal {
  id: string;
  gap?: string;
  spec?: { gap?: string; in_track_space?: boolean; overrides?: Record<string, unknown>; rationale?: string };
  status: string;
  created?: string;
}

export interface ProposalEvaluation {
  proposal?: string;
  verdict_vs?: Record<string, string>;
  objectives_mean?: Record<string, number>;
  applied?: boolean;
  [k: string]: unknown;
}

export interface RankedExperiment {
  id: string;
  hypothesis_id?: string;
  conditions?: Record<string, unknown>;
  runs?: number;
  prior_positive?: number;
  why?: string;
  already_run?: boolean;
  bits?: number;
  bits_per_100_runs?: number;
}

export interface Knowledge {
  created_utc?: string;
  mechanisms: Mechanism[];
  proposals: Proposal[];
  proposal_evaluations?: ProposalEvaluation[];
  next_experiment_ranking?: RankedExperiment[];
  log?: string[];
  note?: string;
}

/* ---------------------------------------------------------------- helpers */

export const CLASS_TONE: Record<string, Tone> = {
  no_secondary_liquidations: "neutral",
  secondary_without_amplification: "weak",
  amplification_without_chain: "weak",
  cascade: "bad",
};

export const CRITERIA_LABEL: Record<string, string> = {
  a_secondary_in_2of8: "(a) secondary liquidations in ≥ 2/8 seeds",
  b_t_interval_below_0: "(b) incremental-drop t-interval entirely < 0",
  c_ge_10pct_of_armB_drop: "(c) |mean incremental drop| ≥ 10% of mean arm-B drop",
  d_chain_in_2of8: "(d) chain observed in ≥ 2/8 seeds",
};

/** Memory status -> tone. */
export function memoryTone(status: string): Tone {
  const s = status.toLowerCase();
  if (s.startsWith("needs_human")) return "weak";
  if (s === "open") return "weak";
  if (s.startsWith("supported") || s === "confirmed") return "good";
  if (s.includes("supported")) return "info";
  if (s.startsWith("refuted")) return "bad";
  if (s === "proposed") return "info";
  return "neutral";
}

/** Fraction -> percent string, e.g. -0.0329 -> "−3.29%". */
export function pctOf(v: unknown, d = 2): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const s = (v * 100).toFixed(d);
  return `${v > 0 ? "+" : ""}${s}%`;
}

/** Unsigned fraction -> percent (distances). */
export function pctAbs(v: unknown, d = 2): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(d)}%`;
}

/** Fraction difference -> percentage points. */
export function ppOf(v: unknown, d = 2): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(d)} pp`;
}

export function stats(xs: (number | null | undefined)[] | undefined): { n: number; mean: number; min: number; max: number } | null {
  const v = (xs ?? []).filter((x): x is number => typeof x === "number" && Number.isFinite(x));
  if (!v.length) return null;
  return { n: v.length, mean: v.reduce((a, b) => a + b, 0) / v.length, min: Math.min(...v), max: Math.max(...v) };
}

/** Saturation: reached mean below this fraction of the nominal size is highlighted. */
export const SATURATION_FRAC = 0.9;

export function uniq<T>(xs: T[]): T[] {
  return Array.from(new Set(xs));
}

/** Label of a histogram bin from consecutive edges (fractions); the open last bin becomes ">x%". */
export function binLabel(edges: number[], i: number): string {
  const lo = edges[i];
  const hi = edges[i + 1];
  const p = (x: number) => `${+(x * 100).toFixed(1)}%`;
  if (i === edges.length - 2 && hi >= 10) return `>${p(lo)}`;
  return `${p(lo)}–${p(hi)}`;
}
