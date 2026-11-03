/** Types + helpers for the Research Army Control Center (/api/army/*). Shapes mirror src/evolutionx/api/army_routes.py. */

export type Json = Record<string, unknown>;

export interface ArmyUsage {
  cycle_id?: string;
  role?: string;
  llm_calls: number;
  llm_cost_usd: number;
  wall_s: number;
  ext_requests: number;
}

export interface ArmyRole {
  id: string;
  division: string;
  title: string;
  capability: string;
  impl: "deterministic" | "llm_optional" | "delegates" | string;
  stage: string;
  tasks: Record<string, number>;
  activity: string;
  last_task: string | null;
  blockers: { task: string; waiting_for: string[] }[];
  errors: string[];
  usage: ArmyUsage;
}

export interface RolesResp {
  cycle: string | null;
  roles: ArmyRole[];
  simulated_market_participants: string;
}

export interface ArmyCycle {
  id: string;
  status: string;
  config: Json | null;
  created: string;
  updated: string;
  summary: { counts?: Record<string, number>; usage?: ArmyUsage[]; wall_s?: number } | null;
}

export interface ArmyTask {
  id: string;
  cycle_id: string;
  stage: string;
  role: string;
  kind: string;
  status: string;
  attempts: number;
  max_attempts: number;
  deps: { deps?: string[]; barrier?: boolean } | null;
  payload: Json | null;
  result: Json | null;
  error: string | null;
  wall_s: number | null;
  llm_calls: number | null;
  created: string;
  updated: string;
}

export interface CycleResp {
  cycle: ArmyCycle;
  tasks: ArmyTask[];
  usage: ArmyUsage[];
}

export interface Evidence {
  grade?: string;
  points?: number;
  peer_reviewed?: boolean;
  flags?: Record<string, boolean>;
  marketing_language?: boolean;
  note?: string;
}

export interface Verification {
  record_refetched?: boolean;
  published?: string;
  updated?: string;
  crossref?: { matched?: boolean; similarity?: number; doi?: string; type?: string; container?: string; publisher?: string; [k: string]: unknown };
  evidence?: Evidence;
  classification?: string;
  claim_status?: string;
  [k: string]: unknown;
}

export interface ArmySource {
  id: string;
  origin: string;
  url: string | null;
  title: string | null;
  authors: string[] | null;
  published: string | null;
  updated: string | null;
  retrieved: string | null;
  abstract: string | null;
  doi: string | null;
  journal_ref: string | null;
  license_note: string | null;
  query: string | null;
  verification: Verification | null;
  mechanism: { family?: string; scores?: Record<string, number> } | null;
  status: string;
}

export interface Hypothesis {
  id: string;
  signature?: string;
  statement?: string;
  operator?: string;
  parent_id?: string | null;
  candidate_id?: string | null;
  status: string;
  evidence?: Json | null;
  novelty?: string;
  classification?: string;
  premises?: { id: string; claim: string; check?: Json }[] | null;
  created?: string;
  updated?: string;
}

export interface Candidate {
  id: string;
  parent_id?: string | null;
  code_sha256: string;
  generator: string;
  operator: string;
  spec: Json | null;
  path: string;
  status: string;
  created?: string;
}

export interface Experiment {
  key: string;
  candidate_id: string;
  stage: string;
  result: Json | null;
  created: string;
}

export interface MemoryResp {
  hypotheses: Hypothesis[];
  candidates: Candidate[];
  experiments: Experiment[];
  earlier_labs: { hypotheses: number; by_family: Record<string, number> };
}

export interface Edge {
  src: string;
  rel: string;
  dst: string;
  data: Json | null;
  created: string;
}

export interface LineageStep {
  id: string;
  stage: string;
  role: string;
  kind: string;
  status: string;
  error: string | null;
  result: Json | null;
  wall_s: number | null;
  llm_calls: number | null;
  updated: string;
}

export interface LineageResp {
  hypothesis: Hypothesis;
  source: ArmySource | null;
  source_steps: ArmyTask[];
  steps: LineageStep[];
  edges: Edge[];
}

export interface Proposal {
  id: string;
  author_role: string;
  title: string;
  rationale: string;
  files: string[];
  tests: string[];
  status: string;
  blocked_paths?: string[];
  note?: string;
  checks: { cmd: string; rc: number; tail: string }[];
  merged: boolean;
  created_utc?: string;
}

export interface ArmyForecast {
  resolved: number;
  open: number;
  min_resolved_for_assessment: number;
  status: Record<string, { n: number; state: string; skill?: number; expected?: number | null; ece?: number; bias?: number }>;
  alerts: string[];
  verify: { ok: boolean; entries: number; head?: string; forecasts?: number; resolved?: number; error?: string };
}

export interface JournalEntry {
  seq: number;
  ts: string;
  actor: string;
  event: string;
  data: Json;
  prev: string;
  hash: string;
}

export interface JournalResp {
  verify: { ok: boolean; entries?: number; head?: string; error?: string; [k: string]: unknown };
  entries: JournalEntry[];
}

export interface SourcePolicy {
  enabled: boolean;
  reason?: string;
  endpoint?: string;
  terms?: string;
  use?: string;
  min_interval_s?: number;
}

export interface ControlResp {
  state: string;
  llm_enabled: boolean;
  source_arxiv_enabled: boolean;
  llm_calls_per_cycle: number;
  policy_llm_calls_per_cycle_max: number;
  sources: Record<string, SourcePolicy>;
  last_run: Json;
  running: boolean;
}

export interface ControlIn {
  action: "start" | "pause" | "stop" | "set" | "run_cycle";
  key?: "llm_enabled" | "source_arxiv_enabled" | "llm_calls_per_cycle" | "schedule_every_hours";
  value?: unknown;
}

/** Pipeline order of the research cycle. Unknown stages sort after these. */
export const STAGES = [
  "DISCOVER",
  "VERIFY",
  "UNDERSTAND",
  "FORMULATE",
  "IMPLEMENT",
  "TEST",
  "CHALLENGE",
  "EVALUATE",
  "ARCHIVE",
  "REASSESS",
] as const;

export function stageIndex(s: string): number {
  const i = (STAGES as readonly string[]).indexOf(s);
  return i < 0 ? STAGES.length : i;
}

/** Honest description of each implementation kind (from army/roles.py). */
export const IMPL_EXPLAIN: Record<string, string> = {
  deterministic: "Code only. No language model is involved.",
  llm_optional:
    "Code, plus at most one budgeted LLM call when enabled and available; a deterministic template is used otherwise. LLM output is schema-validated and can never set status, promotion or budgets.",
  delegates: "Wraps an existing subsystem (research lab, forecasting engine or simulator).",
};

/** Drop the "<cycle>:" prefix from task ids for compact display. */
export function shortTask(id: string): string {
  const i = id.indexOf(":");
  return i >= 0 ? id.slice(i + 1) : id;
}

/* ---------------------------------------------------------------- tolerant accessors for task results */

export function obj(v: unknown): Json | undefined {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Json) : undefined;
}
export function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}
export function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}
export function numv(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

export type ArmyTone = "good" | "weak" | "neutral" | "bad" | "info";

/** Colour family for any army status / verdict string. */
export function armyTone(s: string | null | undefined): ArmyTone {
  const v = (s ?? "").toLowerCase();
  if (!v) return "neutral";
  if (["validated", "done", "passed", "ok", "formulated", "promote", "verified_source", "novel", "accepted", "pending_human_review", "running"].includes(v))
    return v === "running" || v === "verified_source" || v === "pending_human_review" ? "info" : "good";
  if (v.startsWith("reject") || v.startsWith("refuted") || v.startsWith("not_supported") || v.includes("fail") || v.startsWith("blocked") || v.startsWith("infeasible") || v.startsWith("unverifiable") || v === "stopped" || v === "degraded")
    return "bad";
  if (v.includes("duplicate") || v === "prospective_challenger" || v === "fragile" || v === "paused" || v === "insufficient_data" || v === "inconclusive" || v.startsWith("unstable"))
    return "weak";
  if (v === "pending" || v === "idle" || v === "discovered" || v === "completed") return v === "completed" ? "info" : "neutral";
  return "neutral";
}
