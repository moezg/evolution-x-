/* Loose types mirroring the FastAPI contract. Most fields optional: render defensively. */
export type Dict<T = unknown> = Record<string, T>;

export interface Shock {
  type: string;
  at_s: number;
  duration_s: number;
  magnitude: number;
  armed?: boolean;
  note?: string;
}

export interface Scenario {
  name: string;
  description: string;
  shocks: Shock[];
  population_overrides: Dict;
}

export interface Venue {
  name: string;
  mid: number;
  last: number;
  bid: number;
  ask: number;
  volume_btc: number;
  trades: number;
  halted: boolean;
}

export interface SimState {
  status: "idle" | "running" | "paused" | "finished" | "stopped" | string;
  speed?: number;
  t_ms?: number;
  duration_ms?: number;
  seed?: number;
  mode?: string;
  data_label?: string;
  config_fingerprint?: string;
  events_processed?: number;
  wall_time_s?: number;
  events_per_s?: number;
  n_agents?: number;
  counts?: Dict<number>;
  venues?: Venue[];
  funding_rate?: number;
  latent_fundamental?: number;
  n_trades?: number;
  liquidations?: number;
  influence_events?: number;
  insurance_fund_usd?: number;
  fee_pool_usd?: number;
  rejections?: number;
  shocks?: Shock[];
  historical?: null | { source_file?: string; label?: string; first_close?: number; n_points?: number };
}

export interface Candle {
  t: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  trades: number;
}

export interface CandlesResp {
  venue: number;
  data_label: string;
  candles: Candle[];
  historical?: { t: number; close: number }[] | null;
}

export interface Book {
  venue: number;
  t_ms: number;
  bids: [number, number][];
  asks: [number, number][];
}

export interface StreamPayload {
  state: SimState;
  book: Book | null;
  last_candle: Candle | null;
}

export type Series = Dict<number[]> & { t: number[] };

export interface Trade {
  id: number;
  t_ms: number;
  venue: number;
  price: number;
  qty: number;
  buyer: number;
  seller: number;
  aggressor: string;
}

export interface AgentRow {
  id: number;
  kind: string;
  equity: number;
  capital: number;
  return_pct: number;
  positions_btc: number[];
  leverage: number;
  max_drawdown_pct: number;
  reputation: number;
  stance: number;
  strategy_version: number;
  orders_sent: number;
  wakes: number;
  liquidations: number;
  home_venue: number;
  fees_paid_usd: number;
  funding_paid_usd: number;
}

export interface LineageEntry {
  t: number;
  version: number;
  reason: string;
  source_agent?: number | null;
  before?: Dict;
  after?: Dict;
}

export interface AgentDetail extends AgentRow {
  params?: Dict;
  order_latency_ms?: number;
  md_latency_ms?: number;
  wake_ms?: number;
  memory?: Dict;
  lineage?: LineageEntry[];
  equity_curve?: [number, number][];
  recent_decisions?: Dict[];
  observable_inputs?: Dict;
  neighbors?: number[];
  trades?: Trade[];
  open_orders?: { id: number; venue: number; side: string; price: number; qty: number }[];
}

export interface Network {
  nodes: { id: number; kind: string; stance: number; reputation: number }[];
  edges: [number, number][];
  enabled: boolean;
}

export interface KindStats {
  mean_return_pct: number;
  median_return_pct: number;
  cvar5_return_pct: number;
  mean_max_dd_pct: number;
  n: number;
}

export interface Collective {
  clusters: {
    id: number;
    size: number;
    composition: Dict<number>;
    mean_stance: number;
    mean_return_pct: number;
    mean_leverage: number;
    members: number[];
  }[];
  cluster_labels: number[];
  wealth: { gini: number; log10_hist: number[]; log10_edges: number[] };
  by_kind: Dict<KindStats>;
  influence_recent: { t: number; agent: number; kind: string; social: number; prev: number; new: number }[];
  influence_per_minute: { minute: number; count: number }[];
  panic_events: number;
  mm_withdrawals: number;
  imitation_events: number;
  liquidations_recent: { t: number; agent: number; kind: string; equity: number; closed_lots: number; insurance_cover: number }[];
  stance_by_kind: Dict<number>;
}

export interface SimEvent {
  t_ms: number;
  type: string;
  agent: number;
  venue: number;
  data: Dict;
}

export interface Job {
  id: string;
  kind: string;
  params: Dict;
  status: "queued" | "running" | "finished" | "failed" | string;
  progress: string[];
  result: unknown;
  error: string | null;
  created?: number | string;
}

export interface StatBlock {
  n?: number;
  mean?: number;
  std?: number;
  lo?: number;
  hi?: number;
  t_lo?: number;
  t_hi?: number;
  frac_positive?: number;
  effect_size_dz?: number;
}

export interface ExperimentSummaryMetric {
  treatment?: StatBlock;
  baseline?: StatBlock;
  paired_diff?: StatBlock;
  treatment_values?: number[];
  baseline_values?: number[];
}

export interface ExperimentListItem {
  experiment_id: string;
  scenario: string;
  replicates: number;
  duration_s: number;
  scale: number;
  n_agents: number;
  created_utc: string;
  data_label: string;
}

export interface Experiment extends ExperimentListItem {
  description?: string;
  seeds?: number[];
  shock_at_s?: number | null;
  design?: unknown;
  summary?: Dict<ExperimentSummaryMetric>;
  realism?: unknown;
  caveat?: string;
  reproduce?: unknown;
}

export interface Candidate {
  id: string;
  family: string;
  run_id: string;
  generation: number;
  parents: string[] | null;
  origin: string;
  genome: Dict;
  status: string;
  objectives: Dict<number> | null;
  train?: Dict | null;
  behavior?: number[] | null;
  pareto_rank?: number | null;
  created?: string | number;
}

export interface Champion {
  version: number;
  family: string;
  candidate_id: string;
  promoted_at: string | number;
  reason: string;
  evidence: unknown;
  active: boolean | number;
}

export interface Challenge {
  id: number | string;
  family: string;
  run_id: string;
  challenger: string;
  champion: string;
  decision: string;
  evidence: {
    paired_diff?: { mean?: number; t_lo?: number; t_hi?: number; n?: number };
    realism_gap?: number;
    drawdown_gap?: number;
    reasons?: string[];
    per_run?: { seed: number; regime: string; u_challenger: number; u_champion: number }[];
  } | null;
  created?: string | number;
}

export interface EvoRun {
  run_id: string;
  family: string;
  config: unknown;
  status: string;
  summary: unknown;
  created: string | number;
  finished: string | number | null;
}

export interface Lineage {
  candidates: Candidate[];
  champions: Champion[];
  challenges: Challenge[];
  runs: EvoRun[];
}

export interface Gate {
  name: string;
  passed: boolean;
  duration_s?: number;
  detail?: unknown;
}

export interface Proposal {
  id: string;
  created: string | number;
  title: string;
  author: string;
  target_files: string[] | null;
  branch: string;
  status: string;
  report: {
    summary?: string;
    rationale?: string;
    diff?: string;
    gates?: Gate[];
    sandbox?: unknown;
    frozen_eval?: unknown;
    benchmark?: unknown;
  } | null;
  decision: null | { decision: string; reviewer: string; comment: string; ts: string | number };
}

export interface CatalogueItem {
  key: string;
  title: string;
  target_file: string;
  rationale: string;
}

export interface RoleOutput {
  observations?: string[];
  hypotheses?: string[];
  assumptions?: string[];
  conclusions?: string[];
  confidence?: number | string;
  recommended_experiments?: unknown[];
  risks?: string[];
}

export interface CouncilReport {
  id: string;
  created: string | number;
  question: string;
  llm?: { provider?: string; model?: string; calls?: number; cache_hits?: number; budget?: unknown };
  roles?: { role: string; title: string; output: RoleOutput }[];
  synthesis?: Dict;
}

export interface RunManifest {
  run_id: string;
  data_label: string;
  created_utc: string;
  event_fingerprint: string;
  n_agents: number;
  performance: Dict | null;
  reproduce: unknown;
}
