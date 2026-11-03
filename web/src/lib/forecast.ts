/** Types + pure helpers for the Forecasting laboratory (/api/forecast/*). Everything shown comes from the API. */
import { SERIES } from "./colors";

/* ================================================================ protocol */

export interface ForecastProtocol {
  name: string;
  written_utc?: string;
  status?: string;
  objective?: string;
  domain?: string;
  information_lag?: { publication_lag_h?: number; rule?: string; training_labels?: string };
  origins?: string;
  horizons_h?: number[];
  targets?: Record<string, string>;
  features?: string;
  models?: Record<string, string>;
  training?: string;
  simulator_features?: string;
  periods?: Record<string, string>;
  scoring?: Record<string, string>;
  pre_registered_comparisons?: Record<string, string>;
  simulator_inclusion_rule?: string;
  abstention?: { rules?: string[]; scoring?: string };
  ledger?: string;
  evolution?: Record<string, string>;
  claims_policy?: string;
  [k: string]: unknown;
}

export interface Amendment {
  written_utc?: string;
  before?: string;
  finding?: string;
  change?: string;
}

/* ================================================================ backtest report */

export interface Reliability {
  bins: { bin: [number, number]; n: number; mean_p: number; freq: number }[];
  ece: number;
}

export interface BinaryScore {
  n: number;
  base_rate: number;
  brier: number;
  logloss: number;
  brier_skill_vs_B0: number;
  reliability: Reliability;
  coverage: number;
  abstentions: Record<string, number>;
}

export interface RvScore {
  n: number;
  mse_log_rv: number;
  qlike: number;
  mse_skill_vs_B0: number;
  error_quantiles: number[];
  coverage: number;
  abstentions: Record<string, number>;
}

export type ModelScore = BinaryScore | RvScore;

/** scores[period] = { label, n, <model>: ModelScore } */
export type PeriodScores = { label: string; n: number } & Record<string, unknown>;

export interface TargetReport {
  kind: "binary" | "rv" | string;
  horizon_h: number;
  scores: Record<string, PeriodScores>;
}

export interface PairedDiff {
  n: number;
  mean: number;
  lo: number;
  hi: number;
  p_better: number;
}

export interface HolmRow {
  p: number;
  threshold: number;
  reject_null: boolean;
}

export interface BacktestReport {
  targets: Record<string, TargetReport>;
  comparisons: Record<string, Record<string, PairedDiff>>;
  holm_binary_SCREEN: Record<string, HolmRow>;
  holm_rv_SCREEN: Record<string, HolmRow>;
  simulator_inclusion: { rule?: string; targets_where_sim_helps?: string[]; decision?: string };
  protocol?: string;
  protocol_sha256?: string;
  code_version?: string;
  created_utc?: string;
  lag_h?: number;
  data_end_utc?: string;
  simulator?: Record<string, unknown>;
  label?: string;
  cost?: Record<string, unknown>;
}

export interface SeriesResp {
  target: string;
  label?: string;
  origins: number[];
  y: (number | null)[];
  forecast: Record<string, (number | null)[]>;
  abstained: Record<string, (string | null)[]>;
}

/* ================================================================ ledger / prospective / evolution */

export interface LedgerVerify {
  ok: boolean;
  entries: number;
  head?: string;
  forecasts?: number;
  resolved?: number;
  error?: string;
  [k: string]: unknown;
}

export interface ForecastRecord {
  id: string;
  domain?: string;
  target: string;
  kind: string;
  horizon_h: number;
  model: string;
  experimental: boolean;
  model_version: string;
  origin_ms: number;
  window_end_ms: number;
  as_of_ms: number;
  lag_h: number;
  value: number | null;
  abstained: boolean;
  abstain_reason: string | null;
  fallback_B0: number | null;
  scored_value: number | null;
  training_n: number;
  inputs?: {
    bars_digest?: string;
    n_bars?: number;
    last_bar_open_ms?: number;
    fresh_archives?: string[];
    features?: Record<string, number>;
    sim_features?: number[] | null;
  };
  issued_ms: number;
  label?: string;
}

export interface ResolutionRecord {
  forecast_id: string;
  outcome: number;
  evidence?: unknown;
  resolved_ms: number;
}

export interface LedgerEntry {
  seq: number;
  ts: string;
  actor?: string;
  event: "forecast" | "resolution" | string;
  data: ForecastRecord | ResolutionRecord;
  hash: string;
  prev: string;
}

export interface LedgerResp {
  verify: LedgerVerify;
  open: number;
  entries: LedgerEntry[];
}

export type ProspectiveScore = Partial<BinaryScore & RvScore> & { n: number; promotion_evidence_sufficient?: boolean };

export interface ProspectiveResp {
  resolved: number;
  open: number;
  scores: Record<string, ProspectiveScore>;
  verify: LedgerVerify;
  label?: string;
}

export interface EvolutionResult {
  target: string;
  spec: Record<string, unknown>;
  screen_vs_champion?: PairedDiff;
  dev_vs_champion?: PairedDiff;
  trials_for_target?: number;
  p_threshold?: number;
  status: string;
  replaces_champion?: boolean;
}

export interface EvolutionResp {
  created_utc?: string;
  champion: string;
  rule: string;
  results: EvolutionResult[];
  trials_by_target: Record<string, number>;
  label?: string;
}

/* ================================================================ helpers */

export function isBinaryScore(s: unknown): s is BinaryScore {
  return !!s && typeof s === "object" && "brier" in (s as object);
}
export function isRvScore(s: unknown): s is RvScore {
  return !!s && typeof s === "object" && "mse_log_rv" in (s as object);
}

/** Period names in the order the report lists them (e.g. DEV, SCREEN, CONSUMED). */
export function reportPeriods(rep: BacktestReport): string[] {
  const first = Object.values(rep.targets)[0];
  return first ? Object.keys(first.scores) : [];
}

/** Models present in a target's period scores (keys that hold an object score). */
export function periodModels(ps: PeriodScores | undefined): string[] {
  if (!ps) return [];
  return Object.keys(ps).filter((k) => k !== "label" && k !== "n" && ps[k] && typeof ps[k] === "object");
}

export function modelScore(ps: PeriodScores | undefined, model: string): ModelScore | undefined {
  const v = ps?.[model];
  return v && typeof v === "object" ? (v as ModelScore) : undefined;
}

export interface PeriodRange {
  name: string;
  start: number; // ms, inclusive (00:00 UTC)
  end: number; // ms, inclusive day -> end of that day
  text: string;
}

const DAY_MS = 86_400_000;

/** Parse "origins 2021-01-01 .. 2023-12-31 (…)" period strings from the frozen protocol. */
export function parsePeriods(periods: Record<string, string> | undefined): PeriodRange[] {
  if (!periods) return [];
  const out: PeriodRange[] = [];
  for (const [name, text] of Object.entries(periods)) {
    const m = text.match(/(\d{4}-\d{2}-\d{2})\s*\.\.\s*(\d{4}-\d{2}-\d{2})/);
    if (!m) continue;
    const a = Date.parse(`${m[1]}T00:00:00Z`);
    const b = Date.parse(`${m[2]}T00:00:00Z`);
    if (Number.isFinite(a) && Number.isFinite(b)) out.push({ name, start: a, end: b + DAY_MS - 1, text });
  }
  return out;
}

/** Number of resolved prospective forecasts required for promotion, read from the protocol text. */
export function promotionMin(protocol: ForecastProtocol | undefined): number | null {
  const t = protocol?.evolution?.promotion;
  const m = typeof t === "string" ? t.match(/(\d+)\s+resolved/) : null;
  return m ? Number(m[1]) : null;
}

/** Stable color per model, following the order the report lists models. */
export function modelColorMap(models: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  models.forEach((m, i) => (out[m] = SERIES[i % SERIES.length]));
  return out;
}

export const PERIOD_FILL: Record<string, string> = {
  warmup: "#6a6964",
  DEV: "#3987e5",
  SCREEN: "#c98500",
  CONSUMED: "#d55181",
};
export function periodColor(p: string): string {
  return PERIOD_FILL[p] ?? "#6a6964";
}

export function day(ms: number | null | undefined): string {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "—";
  return new Date(ms).toISOString().slice(0, 10);
}
export function dayHour(ms: number | null | undefined): string {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "—";
  return new Date(ms).toISOString().replace("T", " ").slice(0, 16) + "Z";
}

/**
 * Value scored for model m at origin i, mirroring the backtest: abstained (or missing) forecasts are scored as the
 * B0 climatology forecast at that origin.
 */
export function scoredAt(s: SeriesResp, model: string, i: number, b0: string): number | null {
  const f = s.forecast[model]?.[i];
  const r = s.abstained[model]?.[i];
  const base = s.forecast[b0]?.[i];
  if (r || f === null || f === undefined) return base ?? null;
  return f;
}

/** Per-origin Brier contributions (client-side) of a model within [start, end], using the backtest fallback rule. */
export function brierContributions(s: SeriesResp, model: string, b0: string, range?: { start: number; end: number }): number[] {
  const out: number[] = [];
  for (let i = 0; i < s.origins.length; i++) {
    const o = s.origins[i];
    if (range && (o < range.start || o > range.end)) continue;
    const y = s.y[i];
    const base = s.forecast[b0]?.[i];
    if (y === null || y === undefined || base === null || base === undefined) continue;
    const v = scoredAt(s, model, i, b0);
    if (v === null) continue;
    out.push((v - y) ** 2);
  }
  return out;
}

export function mean(a: number[]): number {
  return a.length ? a.reduce((x, y) => x + y, 0) / a.length : NaN;
}

/** "move3_24:M1_logistic-vs-B0_climatology" -> { target, a, b } */
export function parseComparisonKey(k: string): { target: string; a: string; b: string } {
  const [target, rest = ""] = k.split(":");
  const [a, b = ""] = rest.split("-vs-");
  return { target, a, b };
}

export function isForecast(e: LedgerEntry): e is LedgerEntry & { data: ForecastRecord } {
  return e.event === "forecast";
}
export function isResolution(e: LedgerEntry): e is LedgerEntry & { data: ResolutionRecord } {
  return e.event === "resolution";
}

export function sumCounts(c: Record<string, number> | undefined): number {
  return c ? Object.values(c).reduce((a, b) => a + (b || 0), 0) : 0;
}
