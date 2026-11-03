/** Types + helpers for the Quantitative Intelligence API (/api/quant/*). Read-only; shapes follow api/quant_routes.py. */

export type Num = number | null;

export interface QuantAmendment {
  written_utc: string;
  after?: string;
  trigger?: string;
  diagnosis?: string;
  change?: string;
  changes?: string[];
  disclosure?: string;
}

export interface QuantProtocol {
  name: string;
  written_utc: string;
  status: string;
  principle: string;
  data: { btc_spot: string; fred: Record<string, string>; unavailable: Record<string, string> };
  time_conventions: Record<string, string>;
  periods: { DISCOVERY: [string, string]; CONFIRMATION: [string, string]; PROSPECTIVE: string; exposure_note: string };
  families: Record<string, { what: string; tests?: number; metrics?: string[]; [k: string]: unknown }>;
  methods: Record<string, unknown>;
  status_rules: Record<string, string>;
  validation_of_the_method?: string;
  budget?: Record<string, string>;
  [k: string]: unknown;
}

export interface RegEvent {
  event_id: string;
  category: string;
  subcategory: string;
  event_time_utc: string;
  time_precision?: string;
  source_url?: string;
  source_sha256?: string | null;
  source_retrieved_utc?: string;
  derivation?: string;
  market_reference?: string;
  attributes?: {
    final_meeting_day?: string;
    sep?: boolean;
    future?: boolean;
    action?: string;
    action_source?: string;
    target_upper_change_pp?: number;
    year?: number;
  };
  version: number;
  supersedes: number | null;
  registered_utc: string;
}
export interface EventsResp {
  events: RegEvent[];
  verify: { ok: boolean; entries: number; head: string };
  versions: number;
}

export interface TestRow {
  id: string;
  family: string;
  hypothesis: string;
  role: string;
  method: string;
  period: string;
  n: Num;
  n_ref: Num;
  effect: Num;
  ci_lo: Num;
  ci_hi: Num;
  p: Num;
  p_adj: Num;
  adj_method: string | null;
  status: string;
  direction: Num;
  data_sha: string | null;
  protocol_sha: string | null;
  run_id: string;
  details: Record<string, unknown> | null;
  created: string;
}
export interface TestsResp {
  tests: TestRow[];
  counts: { total_tests: number; by_family_period: { family: string; period: string; n: number }[] };
}

export interface CalStat {
  label: number;
  metric: string;
  n: number;
  n_ref: number;
  effect: Num;
  null_sd: Num;
  ci_lo: Num;
  ci_hi: Num;
  p: Num;
  p_rotation_empirical: Num;
  z: Num;
  p_up: Num;
  p_down: Num;
}
export interface CalResult extends CalStat {
  hypothesis: string;
  p_bh: Num;
  status: string;
  confirmation?: CalStat | null;
  confirm_p_one_sided: Num;
  confirm_holm: { p: number; p_adj: number; reject: boolean } | null;
  excl_macro_effect: Num;
}
export interface CalFamily {
  tests: number;
  n_days: { DISCOVERY: number; CONFIRMATION: number };
  discovery_survivors_bh: string[];
  supported: string[];
  results: CalResult[];
}
export interface Day14Year {
  n: number;
  mean_ret_14: Num;
  mean_ret_other: Num;
  mean_absret_14: Num;
  mean_absret_other: Num;
}
export interface CalendarResp {
  cycle: string;
  run_id: string;
  data_sha: string;
  families: Record<string, CalFamily>;
  day14: { reference: string; tests: CalResult[]; by_year: Record<string, Day14Year>; multiple_testing: string };
}

export interface FomcEvent {
  event_id: string;
  day: string;
  action: string | null;
  sep: boolean;
  [metric: string]: string | number | boolean | null;
}
export interface FomcMetricResult {
  n: number;
  n_placebo_pool: number;
  event_mean: Num;
  placebo_median_of_means: Num;
  effect: Num;
  p: Num;
  percentile: Num;
  event_mean_ci: [number, number] | null;
  placebo_mean: Num;
}
export interface XCell {
  n_true: number;
  n_false: number;
  diff: Num;
  p: Num;
  status: string;
}
export interface FomcResp {
  cycle: string;
  events: FomcEvent[];
  placebo_pool: number;
  periods: Record<string, { n_events: number; n_placebo: number }>;
  results: Record<string, Record<string, FomcMetricResult>>;
  status: Record<string, string>;
  xevent: { DISCOVERY?: Record<string, XCell>; CONFIRMATION?: Record<string, XCell>; note?: string; [k: string]: unknown };
  note?: string;
}

export interface ElectEvent {
  event_id: string;
  date: string;
  reference_date?: string;
  pre_30: Num;
  post_1: Num;
  post_7: Num;
  post_30: Num;
  post_90: Num;
  complete: boolean;
}
export interface ElectWindow {
  n: number;
  event_values: number[];
  placebo_n: number;
  event_percentiles_in_placebo: number[];
  mean: Num;
  placebo_mean: Num;
  placebo_test?: Record<string, number>;
}
export interface ElectGroup {
  events: ElectEvent[];
  windows: Record<string, ElectWindow>;
  n_events: number;
  inference: string;
}
export interface ElectionsResp {
  cycle?: string;
  note: string;
  assets: Record<string, Record<string, ElectGroup>>;
  pending: string[];
  pending_note: string;
}

export interface CycleStat {
  period_days: number;
  nearest_period: number;
  power: number;
  band_median: number;
  ratio_to_band_median: number;
  band_size: number;
  p_rank: number;
}
export interface CycleEntry {
  DISCOVERY: CycleStat;
  CONFIRMATION: CycleStat;
  DISC_H1: CycleStat;
  DISC_H2: CycleStat;
  holm: { p: number; p_adj: number; reject: boolean };
  status: string;
}
export interface CyclesResp {
  cycle: string;
  cycles: Record<string, CycleEntry>;
  diagnostics: { period?: string; n: number; acf_ret: number[]; acf_absret: number[]; bartlett_95_band: number; note: string };
}

export interface FcastSplit {
  n: number;
  mean: number;
  lo: number;
  hi: number;
  p_better: number;
}
export interface FcastResult {
  SCREEN: FcastSplit;
  DEV: FcastSplit;
  feature_rate: number;
  holm: { p: number; p_adj: number; reject: boolean };
  status: string;
}
export interface ForecastLinkResp {
  cycle: string;
  results: Record<string, FcastResult>;
  note: string;
}

export interface RankTest {
  id: string;
  period: string;
  n: Num;
  effect: Num;
  ci_lo: Num;
  ci_hi: Num;
  p: Num;
  p_adj: Num;
  adj_method: string | null;
  status: string;
  method: string;
  run_id: string;
}
export interface RankRow {
  hypothesis: string;
  family: string;
  role: string;
  status: string;
  tests: RankTest[];
}
export interface RankingsResp {
  ranking: RankRow[];
  legend: string;
}

export interface QTask {
  id: string;
  stage: string;
  role: string;
  kind: string;
  status: string;
  deps: { deps: string[]; barrier?: boolean; spawned_by?: string | null } | null;
  result: Record<string, unknown> | null;
  error: string | null;
  wall_s: Num;
  llm_calls: Num;
}
export interface WorkflowResp {
  cycle: {
    id: string;
    status: string;
    config: Record<string, unknown> | null;
    created: string;
    updated: string;
    summary?: { counts?: Record<string, number>; wall_s?: number; usage?: unknown[] } | null;
  };
  tasks: QTask[];
  runs: { id: string; status: string; created: string }[];
}

/* ---------------------------------------------------------------- helpers */

export const CAL_FAMILIES = ["F-DOM", "F-DOW", "F-MOY", "F-TOM"] as const;
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MOY = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Human label of a calendar bucket. F-DOW uses Python weekday() (0 = Monday, UTC). */
export function calLabel(family: string, label: number): string {
  if (family === "F-DOW") return DOW[label] ?? String(label);
  if (family === "F-MOY") return MOY[label - 1] ?? String(label);
  if (family === "F-TOM") return "TOM";
  return String(label);
}

/** Stage order of the quant workflow (army stages). */
export const STAGES = ["DISCOVER", "UNDERSTAND", "TEST", "EVALUATE", "CHALLENGE", "ARCHIVE", "REASSESS"];

/** Which workflow task produced each test family. */
export const FAMILY_TASK: Record<string, string> = {
  "F-DOM": "q_calendar",
  "F-DOW": "q_calendar",
  "F-MOY": "q_calendar",
  "F-TOM": "q_calendar",
  "F-FOMC": "q_fomc",
  "F-XEVENT": "q_xevent",
  "F-ELECT": "q_elections",
  "F-CYCLE": "q_cycles",
  "F-FCAST": "q_forecast",
};

/** Role divisions (Research Army): G = quantitative, H = pattern/calendar, I = political & macro events. */
export const DIVISION: Record<string, string> = {
  G: "G · quantitative methods",
  H: "H · pattern & calendar",
  I: "I · political & macro events",
  E: "E · validation",
  F: "F · memory & reassessment",
};

export type StatusKey = "supported" | "candidate" | "inconclusive" | "exploratory" | "descriptive" | "not_promoted" | "rejected" | "other";

export function statusKey(s: string | null | undefined): StatusKey {
  const v = (s ?? "").toLowerCase();
  if (v.startsWith("supported")) return "supported";
  if (v.startsWith("candidate")) return "candidate";
  if (v.startsWith("inconclusive")) return "inconclusive";
  if (v.startsWith("exploratory")) return "exploratory";
  if (v.startsWith("descriptive")) return "descriptive";
  if (v.startsWith("not_promoted") || v.startsWith("not promoted")) return "not_promoted";
  if (v.startsWith("rejected")) return "rejected";
  return "other";
}

/**
 * Display text for a status. "supported" is NEVER shown as verified: it means it survived BH on discovery and Holm on the
 * (previously exposed) confirmation period - still exploratory.
 */
export const STATUS_TEXT: Record<StatusKey, string> = {
  supported: "exploratory – survived confirmation",
  candidate: "candidate (prospective challenger only)",
  inconclusive: "inconclusive",
  exploratory: "exploratory",
  descriptive: "descriptive only (n < 20)",
  not_promoted: "not promoted",
  rejected: "rejected",
  other: "—",
};

export const STATUS_COLOR: Record<StatusKey, string> = {
  supported: "#3987e5",
  candidate: "#3987e5",
  inconclusive: "#c98500",
  exploratory: "#9085e9",
  descriptive: "#898781",
  not_promoted: "#6a6964",
  rejected: "#6a6964",
  other: "#6a6964",
};

export const ACTION_COLOR: Record<string, string> = { hike: "#e66767", cut: "#199e70", hold: "#898781" };

export function fp(p: Num | undefined): string {
  if (typeof p !== "number" || !Number.isFinite(p)) return "—";
  if (p === 0) return "0 (reported)";
  if (p < 1e-4) return p.toExponential(1);
  if (p < 0.01) return p.toFixed(4);
  return p.toFixed(3);
}

/** Return-like values (log returns, fractions) as signed percent. */
export function fpct(v: Num | undefined, d = 2): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const x = v * 100;
  return `${x > 0 ? "+" : ""}${x.toFixed(d)}%`;
}
export function fpctU(v: Num | undefined, d = 2): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(d)}%`;
}
