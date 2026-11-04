/** Types for the Predictive Intelligence Control Center API (/api/control/*). GET only; every field is persisted data. */

export interface LedgerVerify {
  ok: boolean;
  entries?: number;
  head?: string | null;
  forecasts?: number;
  resolved?: number;
  missed?: number;
  error?: string;
  [k: string]: unknown;
}

export interface CForecast {
  id: string;
  target: string;
  model: string;
  role: "champion" | "challenger" | "baseline" | "alternative" | string;
  value: number | null;
  scored_value: number | null;
  abstained: boolean;
  abstain_reason: string | null;
  issued_utc: string;
  window_end_utc: string;
  model_version: string | null;
  feature_version: string | null;
  snapshot_sha256: string | null;
  resolved: boolean;
  outcome: number | null;
}

export interface COrigin {
  origin_utc: string;
  lag_h?: number | null;
  forecasts: CForecast[];
}

export interface CForecastsResp {
  origins: COrigin[];
  missed: { origin_utc: string; reason: string; recorded_utc: string }[];
  verify: LedgerVerify;
  evidence: Record<string, { resolved: number; required_for_promotion: number }>;
  sufficient_prospective_evidence: boolean;
}

export interface WilsonRate {
  k: number;
  n: number;
  rate: number | null;
  wilson95: [number, number];
}

export interface NullSummary {
  runs: number;
  tests_per_run: number;
  any_false_supported: WilsonRate;
  per_metric: Record<string, WilsonRate>;
  per_family: Record<string, WilsonRate>;
  false_supported_total: number;
  mean_bh_survivors_per_run: number | null;
  examples?: string[];
}

export interface CalibrationStudy {
  protocol?: string;
  n_rotations?: number;
  null?: Record<string, NullSummary>;
  power?: Record<string, WilsonRate & { runs_with_other_false_supported?: number }>;
  quarantine?: Record<string, { quarantined: boolean; reasons: string[] }> | string;
  started_utc?: string;
  finished_utc?: string;
  label?: string;
  protocol_sha256?: string;
  smoke_test_not_registered?: boolean;
}

export interface CReliabilityResp {
  prospective_scores: {
    resolved: number;
    open: number;
    scores: Record<string, unknown>;
    verify?: LedgerVerify;
    label?: string;
  } | null;
  drift: {
    resolved: number;
    open: number;
    min_resolved_for_assessment: number;
    status: Record<string, unknown>;
    alerts: unknown[];
    verify?: LedgerVerify;
  } | null;
  calibration_study: CalibrationStudy | null;
  note?: string;
}

export interface RoleClass {
  title?: string;
  class: string;
  llm?: string;
  runs?: string;
}

export interface CRole {
  id: string;
  division: string;
  title: string;
  impl: string;
  class: RoleClass | null;
}

export interface RoleValue {
  role: string;
  title?: string;
  impl?: string;
  tasks: number;
  failed?: number;
  llm_calls: number;
  llm_usd_api_equiv: number;
  wall_s: number;
  external_requests?: number;
  contributions: Record<string, unknown>;
  flag: string | null;
}

export interface SpecialistSession {
  session: string;
  steps: { role: string; used_llm: boolean | null; cost: number | null; valid: boolean | null }[];
  proposals: { by: string; status: string; reasons?: string[] | null }[];
  lineage?: { sources?: string[]; tests_cited?: string[]; journal?: string; [k: string]: unknown } | null;
  revalidations?: {
    utc: string;
    reason: string;
    results: { by: string; original: string; now: { status: string; key?: string; reasons?: string[] } }[];
  }[];
}

export interface CArmyResp {
  roles: CRole[];
  value: {
    roles: RoleValue[];
    flagged: string[];
    dedup_with_without?: {
      duplicates_stopped_with_A4?: number;
      with_A4?: Record<string, unknown>;
      without_A4_estimate?: Record<string, unknown>;
      A4_cost_measured_wall_s?: number;
      measured_chain_wall_s_per_candidate?: number;
      label?: string;
    };
    policy?: string;
  };
  specialist_sessions: SpecialistSession[];
}

export interface PeriodRow {
  id: string;
  n: number;
  effect: number | null;
  p: number | null;
  p_adj: number | null;
  ci_lo?: number | null;
  ci_hi?: number | null;
}

/** One entry per hypothesis; period rows (discovery, confirmation, and possibly others such as screen/all) are keyed by lowercase period. */
export interface CFinding {
  hypothesis: string;
  family: string;
  status: string;
  run_id?: string;
  quarantined_metric: boolean;
  discovery?: PeriodRow;
  confirmation?: PeriodRow;
  [period: string]: unknown;
}

export const FINDING_META_KEYS = ["hypothesis", "family", "status", "run_id", "quarantined_metric"];

export interface EventFollowup {
  event_id?: string;
  series?: string;
  archives?: { day: string; url: string; sha256: string; checksum_verified: boolean }[];
  recorded_utc?: string;
  observed_abs_4h_log_return?: number;
  registered_reference?: string;
  label?: string;
  correction_of?: string;
  reason?: string;
  [k: string]: unknown;
}

export interface CQuantResp {
  counts: {
    total_tests?: number;
    distinct_hypotheses?: number;
    runs?: number;
    note?: string;
    by_family_period?: { family: string; period: string; n: number }[];
    [k: string]: unknown;
  };
  findings: CFinding[];
  quarantined_metrics: string[];
  event_followups: EventFollowup[];
  label?: string;
  note?: string;
}

export interface EvoProposal {
  id: string;
  source: string;
  category: string;
  title: string;
  status: string;
  independent_evidence: string;
  promotable: boolean;
  requires_human_review?: boolean;
}

export interface CEvolutionResp {
  categories: Record<string, string>;
  proposals: EvoProposal[];
  by_category: Record<string, number>;
  promoted: unknown[];
  excluded_test_fixtures?: number;
  errors?: Record<string, unknown>;
  rule?: string;
}

export interface OpsRun {
  job: string;
  slot: string;
  critical: number | boolean;
  status: string;
  attempts: number;
  started_utc: string | null;
  finished_utc: string | null;
  next_attempt_utc: string | null;
  error: string | null;
}

export interface OpsSource {
  name: string;
  last_ok_utc: string | null;
  last_error_utc: string | null;
  last_error: string | null;
  consecutive_failures: number;
  state: string;
}

export interface COpsResp {
  heartbeat: { last_tick_utc?: string | null; last_tick_host?: string | null; [k: string]: unknown };
  runs: OpsRun[];
  counts: { job: string; status: string; n: number }[];
  sources: OpsSource[];
  notifications: unknown[];
  budget_today?: {
    day?: string;
    research_wall_s?: number;
    research_llm_calls?: number;
    limits?: { research_daily_wall_s?: number; research_daily_llm_calls?: number; [k: string]: unknown };
  };
  last_tick_age_s: number | null;
  scheduler_alive: boolean;
  army_state?: string;
}

export const CAPABILITY_CLASSES = ["llm_agent", "deterministic_worker", "tool_worker", "orchestrator", "evaluation_engine"] as const;
