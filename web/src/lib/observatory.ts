/** Types + small helpers for the Emergent Behavior Observatory (/api/observatory/*). All data is SYNTHETIC research output. */

export interface ObsIndex {
  artifacts: string[];
  frozen_specs_sha256: Record<string, string>;
  label: string;
}

/* ---------------------------------------------------------------- audit */

export interface Capability {
  /** e.g. "IMPLEMENTED", "IMPLEMENTED (with a caveat)", "PARTIAL (implemented, inactive in this run)", "MISSING", "UNVERIFIED" */
  status: string;
  /** a free-text sentence or a dict of measured facts */
  evidence?: string | Record<string, unknown>;
  code?: string[];
}

export interface Audit {
  created_utc?: string;
  seed?: number;
  duration_s?: number;
  fingerprint?: string;
  capabilities: Record<string, Capability>;
  trade_volume_by_kind_pair_btc?: Record<string, number>;
  [k: string]: unknown;
}

/* ---------------------------------------------------------------- shared */

/** Min/mean/max over seeds. NaN in the source JSON arrives as null. */
export interface MinMeanMax {
  mean: number | null;
  min: number | null;
  max: number | null;
}

export interface MedianIqr {
  median: number;
  iqr: number;
}

/** Paired treatment − control statistics over seeds (bootstrap CI lo/hi, t-interval t_lo/t_hi). Some fields may be missing when n = 0. */
export interface Paired {
  n: number;
  mean: number | null;
  std?: number | null;
  lo?: number | null;
  hi?: number | null;
  t_lo?: number | null;
  t_hi?: number | null;
  frac_positive?: number | null;
  effect_size_dz?: number | null;
}

export interface PreregHypothesis {
  claim?: string;
  prediction?: string;
  refuted_if?: string;
  /** used instead of refuted_if for open questions */
  report?: string;
}

/* ---------------------------------------------------------------- volatility */

export interface VolatilityProtocol {
  name: string;
  written_utc?: string;
  question: string;
  design?: string;
  hypotheses: Record<string, PreregHypothesis>;
  properties_compared?: string[];
  historical_reference?: string;
  stopping_rule?: string;
  amendment_v2?: {
    written_utc?: string;
    after_results?: string;
    base?: string;
    question?: string;
    hypotheses: Record<string, PreregHypothesis>;
    seeds?: number[];
    stopping_rule?: string;
  };
}

export interface VolatilityReport {
  protocol: string;
  tag: string;
  created_utc?: string;
  seeds: number[];
  duration_s: number;
  conditions: Record<string, Record<string, unknown>>;
  historical_train_targets: Record<string, MedianIqr>;
  /** condition -> metric key (e.g. "mid_ret_std_bps.1m") -> min/mean/max */
  summary: Record<string, Record<string, MinMeanMax>>;
  label?: string;
}

export interface VolatilityResp {
  protocol: VolatilityProtocol;
  reports: Record<string, VolatilityReport>;
}

/* ---------------------------------------------------------------- experiments */

export interface ExperimentSpec {
  question: string;
  conditions?: Record<string, Record<string, unknown>>;
  hypotheses: Record<string, PreregHypothesis>;
  shock?: Record<string, unknown>;
  control?: string;
  window?: string;
  factors?: Record<string, unknown>;
  caveat?: string;
}

export interface ExperimentsProtocol {
  name: string;
  written_utc?: string;
  status?: string;
  data_policy?: string;
  base_profile?: { name: string; overrides?: Record<string, unknown>; why?: string };
  common: {
    duration_s?: number;
    sampling_step_s?: number;
    seeds?: number[];
    shock_at_s?: number;
    pairing?: string;
    detector_constants?: string;
    labels: Record<string, string>;
  };
  A_stable: ExperimentSpec;
  B_liquidity_crisis: ExperimentSpec;
  C_liquidation_cascade: ExperimentSpec;
  stopping_rule?: string;
  amendment_1?: { written_utc?: string; before_results?: string; change?: string; reason?: string };
}

/** A hypothesis result is a loose bag: verdict* strings, Paired objects, per-seed arrays, notes, and nested sub-results (e.g. "f=0.5"). */
export type HypResult = Record<string, unknown>;

export interface ExperimentsReport {
  A: {
    hypotheses: Record<string, HypResult>;
    /** detector -> comparison ("full_vs_no_social", "full_vs_zero_intelligence") -> paired */
    detector_ablation?: Record<string, Record<string, Paired>>;
    /** condition -> metric -> stats */
    summary?: Record<string, Record<string, Paired>>;
  };
  B: {
    hypotheses: Record<string, HypResult>;
    /** "f=0.5" -> metric -> paired */
    effects?: Record<string, Record<string, Paired>>;
  };
  C: {
    hypotheses: Record<string, HypResult>;
    /** "1000btc|lev_present" -> metric -> per-seed values */
    cells?: Record<string, Record<string, (number | null)[]>>;
  };
  protocol?: string;
  protocol_sha256?: string;
  created_utc?: string;
  label?: string;
  cost?: { runs?: number; wall_s_total?: number; cpu_s_sum?: number; llm_calls?: number };
}

export interface ExperimentsResp {
  protocol: ExperimentsProtocol;
  report: ExperimentsReport;
}

/* ---------------------------------------------------------------- realism (v2 shape; v1 fields tolerated) */

export type RealismVerdict = "improvement" | "trade-off" | "not an improvement";

export interface RealismObjectives {
  scale_error: number;
  shape_error: number;
  cost_cpu_s_per_sim_hour: number;
}

export interface RealismVerdictDetail {
  verdict: string;
  better?: string[];
  worse?: string[];
  paired?: Record<string, Paired>;
}

export interface RealismEntry {
  name: string;
  overrides: Record<string, unknown>;
  objectives_mean: RealismObjectives;
  fingerprints?: string[];
  /** incumbent name -> verdict (v2) */
  verdict_vs?: Record<string, RealismVerdict | string>;
  /** incumbent name -> detail (v2) */
  verdict_detail?: Record<string, RealismVerdictDetail>;
  /** legacy v1 single-incumbent verdict */
  verdict_vs_incumbent?: string;
  evaluated_utc?: string;
}

export interface ArchiveHistoryEntry extends RealismEntry {
  admitted?: boolean;
  dominated_by?: string;
  behavioural_duplicate_of?: string;
}

export interface RealismRules {
  name: string;
  purpose?: string;
  targets?: string;
  estimator?: string;
  objectives: Record<string, { facts?: string[]; per_fact?: string; aggregate?: string; direction?: string }>;
  seeds?: number[];
  duration_s?: number;
  candidate_space?: string;
  allowed_fields?: string[];
  verdict_rule?: string;
  archive_rule?: string;
  supersedes?: { version?: string; why?: string[]; v1_artifacts_kept?: string[] };
  written_utc?: string;
  incumbents?: string[];
  dominance?: { rule?: string; tolerance?: Record<string, number> };
  duplicate_rule?: string;
}

export interface RealismReport {
  protocol?: string;
  rules_sha256?: string;
  created_utc?: string;
  label?: string;
  targets_train?: Record<string, MedianIqr>;
  results: Record<string, RealismEntry>;
  pareto?: string[];
  cost?: { runs?: number; wall_s?: number; llm_calls?: number };
}

export interface RealismArchive {
  rules_sha256?: string;
  pareto: ArchiveHistoryEntry[];
  history: ArchiveHistoryEntry[];
}

export interface RealismResp {
  rules: RealismRules;
  report: RealismReport;
  archive: RealismArchive;
}

/* ---------------------------------------------------------------- helpers */

export function isPaired(v: unknown): v is Paired {
  return !!v && typeof v === "object" && !Array.isArray(v) && "n" in v && "mean" in v;
}

/** Compact number formatting: 3 significant digits for small values, fixed decimals otherwise. */
export function fx(v: unknown, d?: number): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  if (d !== undefined) return v.toFixed(d);
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 1000) return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (a >= 100) return v.toFixed(1);
  if (a >= 1) return v.toFixed(2);
  if (a >= 1e-3) return v.toPrecision(3);
  return v.toExponential(2);
}

export function fxSigned(v: unknown, d?: number): string {
  const s = fx(v, d);
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? `+${s}` : s;
}

export function interval(lo: unknown, hi: unknown): string {
  if ((typeof lo !== "number" || !Number.isFinite(lo)) && (typeof hi !== "number" || !Number.isFinite(hi))) return "—";
  return `[${fx(lo)}, ${fx(hi)}]`;
}

/** "IMPLEMENTED (with a caveat)" -> "IMPLEMENTED" */
export function leadingStatus(s: string): string {
  return (s.match(/^[A-Za-z_]+/)?.[0] ?? s).toUpperCase();
}

export type Tone = "good" | "weak" | "neutral" | "bad" | "info";

/** Pre-registered verdict -> tone. supported=green, weak=amber, not supported/inconclusive=grey, refuted=red. */
export function verdictTone(v: string): Tone {
  const s = v.toLowerCase().trim();
  if (s.startsWith("refuted")) return "bad";
  if (s.startsWith("not supported") || s.startsWith("inconclusive") || s.startsWith("not an improvement")) return "neutral";
  if (s.startsWith("weak") || s.startsWith("trade-off")) return "weak";
  if (s.startsWith("supported") || s.startsWith("improvement")) return "good";
  if (s.startsWith("incumbent")) return "info";
  return "neutral";
}
