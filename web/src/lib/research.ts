/** Types for the /api/research/* read models. Mirrors evolutionx/api/research_routes.py. */

type Dict = Record<string, unknown>;

export interface Budget {
  max_tasks: number;
  max_wall_s: number;
  max_llm_tokens: number;
  sandbox?: { cpu_s?: number; mem_bytes?: number; wall_s?: number };
}

export interface Consumed {
  tasks: number;
  wall_s: number;
  llm_tokens: number;
  sandbox_runs: number;
}

export interface Campaign {
  id: string;
  mode: string;
  selector: string;
  status: string;
  budget: Budget;
  consumed: Consumed;
  config?: { generator?: string; llm_available?: boolean; llm_status?: string; seed?: number; sandbox?: Dict } & Dict;
  created: string;
  updated: string;
  stop_reason?: string | null;
}

export interface ActiveVersion {
  version: number;
  sha256: string;
  candidate_id: string;
  since: string;
  reason: string;
}

export interface LabSummary {
  name: string;
  superseded: boolean;
  campaigns: Campaign[];
  active: ActiveVersion | null;
  stop_requested: boolean;
}

export interface VersionMeta {
  version: number;
  candidate_id: string;
  parent_version: number | null;
  sha256: string;
  reason: string;
  created: string;
  git_commit?: string | null;
  evidence?: Dict;
}

export interface JournalVerify {
  ok: boolean;
  entries?: number;
  head?: string;
  broken_at?: number;
  reason?: string;
}

export interface Split {
  start: string;
  end_exclusive: string;
  use: string;
}

export interface Protocol {
  name: string;
  sha256: string;
  splits: Record<string, Split>;
  promotion_rule: {
    primary_metric: string;
    minimal_useful_effect_sharpe: number;
    bootstrap: Dict;
    required_prob_improvement: number;
    secondary_constraints: Dict;
  };
  amendments: { from: string; to: string; utc: string; change: string; reason: string }[];
}

export interface Overview {
  name: string;
  campaigns: Campaign[];
  active: ActiveVersion | null;
  versions: VersionMeta[];
  hypotheses: Record<string, number>;
  tasks: Record<string, number>;
  journal: JournalVerify;
  stop_requested: boolean;
  trials: { development: number; validation: number };
  protocol: Protocol;
  policy: {
    name?: string;
    note?: string;
    caps?: Dict;
    modes?: Record<string, { auto_activate?: boolean; causality_checks?: number; dev_tail_bars?: number | null; symbols?: string[] | null }>;
    protected_paths?: string[];
    evolvable_paths?: string[];
  } & Dict;
}

export type Checks = Record<string, unknown>;

export interface Screen {
  candidate_dev_oos_sharpe: number;
  champion_dev_oos_sharpe: number;
  passed: boolean;
}

export interface TaskRow {
  id: string;
  seq: number;
  stage: string;
  status: "open" | "done" | "failed" | string;
  error: string | null;
  operator: string | null;
  design_parent: string | null;
  candidate_id: string | null;
  verdict: string | null;
  screen: Screen | null;
  rejection: { gate?: string; detail?: unknown } | null;
  delta_sharpe: number | null;
  prob_positive: number | null;
  checks: Checks | null;
  activation: { activated?: boolean; version?: number; rolled_back_to?: number; reason?: string } & Dict | null;
  duplicate_of: string | null;
  updated: string;
}

export interface SymbolDiag {
  net_sharpe?: number;
  gross_sharpe?: number;
  max_drawdown?: number;
  turnover_per_year?: number;
  avg_holding_bars?: number;
  trading_cost_share?: number;
  funding_cost_share?: number;
  sharpe_low_vol_tercile?: number;
  sharpe_high_vol_tercile?: number;
}

export interface PreregisteredTask {
  id?: string;
  objective?: string;
  hypothesis?: string;
  mechanism?: string;
  alternatives?: string[];
  testable_prediction?: string;
  primary_metric?: string;
  secondary_measures?: string[];
  minimal_useful_effect?: Dict;
  refutation_criteria?: string[];
  allowed_data?: Dict;
  time_split?: Record<string, Split>;
  statistical_plan?: Dict;
  stopping_rule?: string;
  preregistration_sha256?: string;
  sources?: Dict;
  initial_observation?: {
    diagnostics_development_only?: Record<string, SymbolDiag>;
    selection_reason?: string;
    operator_ranking?: { operator: string; score: number; evidence: string }[];
  };
}

export interface Bootstrap {
  delta_sharpe?: number;
  prob_positive?: number;
  ci90_lo?: number;
  ci90_hi?: number;
  ci95_lo?: number;
  ci95_hi?: number;
  resamples?: number;
  mean_block?: number;
}

export interface Decision {
  verdict?: string;
  checks?: Checks;
  bootstrap?: Bootstrap;
  dsr?: { dsr?: number; sr0?: number; z?: number };
  n_validation_trials?: number;
  candidate_sharpe?: number;
  champion_sharpe?: number;
  common_days?: number;
}

export interface Critique {
  claim: string;
  metric_ref: string;
  value: unknown;
  severity: string;
}

export interface Checkpoint {
  decision?: Decision;
  critique?: Critique[];
  activation?: TaskRow["activation"];
  rejection?: TaskRow["rejection"];
  screen?: Screen;
  novelty?: string;
  verdict?: string;
  validation_summary?: { candidate?: number; champion?: number; candidate_mdd?: number; champion_mdd?: number };
  duplicate_of?: string;
  operator?: string;
  why?: string;
  design_parent?: string;
  candidate_id?: string;
  generator?: string;
  [k: string]: unknown;
}

export interface PerWindow {
  train: [number, number];
  test: [number, number];
  selected: string;
  train_sharpe: number;
  test_sharpe: number;
  test_return: number;
}

export interface TaskDetail {
  task: {
    id: string;
    campaign_id?: string;
    seq: number;
    stage: string;
    status: string;
    attempts?: number;
    max_attempts?: number;
    task: PreregisteredTask | null;
    checkpoint: Checkpoint | null;
    error: string | null;
    created?: string;
    updated?: string;
  };
  candidate: {
    diff?: string;
    proposal?: {
      generator?: string;
      operator?: string;
      hypothesis?: unknown;
      expected_benefit?: string;
      risk?: string;
      contract?: string;
      eval_plan?: string;
      code_sha256?: string;
      base_commit?: string;
      parent_version?: number;
      design_parent?: string;
      static_issues?: unknown[];
    } & Dict;
    source?: string;
  };
  experiment: {
    deterministic?: boolean;
    causality?: { checked?: number; violations?: unknown[]; causal?: boolean };
    development?: {
      portfolio_oos_sharpe?: number;
      days?: number;
      per_symbol?: Record<string, { oos_sharpe?: number; n_windows?: number; n_trials?: number; per_window?: PerWindow[] }>;
    };
    diagnostics?: Record<string, SymbolDiag>;
    timing?: Dict;
  } | null;
}

export interface Hypothesis {
  id: string;
  signature: string;
  statement: string;
  operator: string;
  parent_id: string | null;
  candidate_id: string | null;
  status: string;
  evidence: Dict | null;
  novelty: string | null;
  created: string;
  updated: string;
}

export interface Registry {
  active: ActiveVersion | null;
  versions: VersionMeta[];
  history: { ts: string; active: number; reason: string }[];
}

export interface JournalEntry {
  seq: number;
  ts: string;
  actor: string;
  event: string;
  data: unknown;
  prev: string;
  hash: string;
}

export interface Journal {
  verify: JournalVerify;
  entries: JournalEntry[];
}

export interface DataFile {
  bars: number;
  first: string;
  last: string;
  sha256: string;
  path: string;
}

export interface Instrument {
  market: string;
  resolution: string;
  qc: Record<string, number>;
  gaps_sample?: [number, number][];
  files: Record<string, DataFile>;
  all_checksums_verified: boolean;
  n_sources?: number;
}

export interface DataStatus {
  manifest: {
    protocol: string;
    protocol_sha256?: string;
    built_utc: string;
    timezone: string;
    units: Record<string, string>;
    instruments: Record<string, Instrument>;
  } | null;
  vault_ledger: Dict[];
  final_split_consumed: boolean;
  note?: string;
}

export interface FinalStrategy {
  sharpe?: number;
  sharpe_2x_costs?: number;
  return?: number;
  max_drawdown?: number;
  per_symbol?: Dict;
  /** API returns {dsr, sr0, z} or null (spec said number) */
  dsr_vs_all_trials?: number | { dsr?: number; sr0?: number; z?: number } | null;
}

export interface FinalReport {
  created_utc: string;
  final_split?: Dict;
  label?: string;
  blind?: boolean;
  /** API returns a list of previous reveals (spec said number) */
  previous_reveals?: number | unknown[];
  primary_comparisons?: string[];
  exploratory_comparisons?: string[];
  preregistration?: Record<string, unknown>;
  validation_trials_across_arms?: number;
  strategies?: Record<string, FinalStrategy>;
  paired_vs_frozen_v0?: Record<string, { delta_sharpe?: number; prob_positive?: number; ci95_lo?: number; ci95_hi?: number }>;
  "holm_one_sided_alpha_0.05"?: Record<string, { p?: number; threshold?: number; reject_null?: boolean }>;
  note?: string;
}

export interface CiStat {
  n?: number;
  mean?: number;
  std?: number;
  lo?: number;
  hi?: number;
  t_lo?: number;
  t_hi?: number;
}

export interface CalibrationArm {
  train_distance?: CiStat;
  validation_distance?: CiStat;
  heldout_distance?: CiStat;
  facts?: Record<string, CiStat>;
}

export interface Calibration {
  created_utc?: string;
  question?: string;
  targets?: {
    train?: Record<string, [number, number]>;
    validation?: Record<string, [number, number]>;
    heldout?: Record<string, [number, number]>;
    windows?: Record<string, number>;
  };
  search?: { n_configs?: number; seeds_per_config?: number; duration_s?: number; results?: { knobs: Record<string, number>; train_distance: number; facts_mean?: Dict }[] };
  selected_knobs?: Record<string, number>;
  evaluation?: { seeds?: number[]; default?: CalibrationArm; calibrated?: CalibrationArm };
  sensitivity_dlog_vol_dlog_knob?: Record<string, number>;
  caveats?: string[];
  liquidity_supply?: Record<string, Record<string, { mean?: number; min?: number; max?: number }>> | null;
}
