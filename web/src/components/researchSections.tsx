"use client";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { DiffView } from "./labs";
import { EmptyState, ErrorNote, JsonTable, Panel } from "./ui";
import { CheckChips, Hash, IntervalPlot, Prov, SplitTimeline, SPLIT_COLORS, Verdict, WindowBars } from "./research";
import { usePoll } from "@/lib/hooks";
import { fmtAny, fmtTime, humanize, num, signed } from "@/lib/format";
import type {
  Calibration,
  CiStat,
  DataStatus,
  FinalReport,
  Hypothesis,
  Journal,
  Registry,
  SymbolDiag,
  TaskDetail,
  TaskRow,
} from "@/lib/research";

/** Re-read a poll whenever `rev` changes (after a control action). */
export function useRefreshOn(rev: number, refresh: () => void) {
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev]);
}

function H3({ children }: { children: ReactNode }) {
  return <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">{children}</h3>;
}

function Field({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wider text-muted">{k}</dt>
      <dd className="mt-0.5 break-words text-xs text-ink [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/* ================================================================ 3. data coverage */

export function DataCoverage({ rev }: { rev: number }) {
  const p = usePoll<DataStatus>("/api/research/data", 30000);
  useRefreshOn(rev, p.refresh);
  const d = p.data;
  const inst = d?.manifest?.instruments ?? {};
  const syms = Object.keys(inst);
  const [lo, hi] = useMemo(() => {
    const ts: number[] = [];
    syms.forEach((s) => Object.values(inst[s].files).forEach((f) => ts.push(Date.parse(f.first), Date.parse(f.last))));
    const ok = ts.filter(Number.isFinite);
    return ok.length ? [Math.min(...ok), Math.max(...ok)] : [0, 1];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d]);
  const years: number[] = [];
  if (hi > lo) for (let y = new Date(lo).getUTCFullYear() + 1; y <= new Date(hi).getUTCFullYear(); y++) years.push(y);
  return (
    <Panel
      id="data"
      title="Data coverage & split status"
      subtitle="Binance USDⓈ-M perpetual hourly bars. Development is free to explore; every validation access is counted as a trial; the final split lives in the vault."
      actions={
        <>
          <Prov kind="HISTORICAL BACKTEST" />
          {d && (d.final_split_consumed ? <Prov kind="NOT BLIND ANYMORE" /> : <span className="rounded border border-up/60 bg-up/10 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-up">FINAL VAULT SEALED</span>)}
        </>
      }
    >
      <ErrorNote error={p.error} what="data manifest" />
      {d && !d.manifest && <EmptyState title="No data manifest">data/research/manifest.json is missing.</EmptyState>}
      {d?.manifest && (
        <div className="space-y-4">
          <p className="text-xs text-ink2">
            Manifest built {fmtTime(d.manifest.built_utc)} under <code>{d.manifest.protocol}</code>
            {d.manifest.protocol_sha256 && (
              <>
                {" "}(<Hash v={d.manifest.protocol_sha256} label="manifest protocol sha256" />)
              </>
            )}
            {" "}· timezone {d.manifest.timezone} · units: {Object.entries(d.manifest.units ?? {}).map(([k, v]) => `${k} ${v}`).join(", ")}
          </p>
          <p className={`rounded-md border px-3 py-2 text-xs ${d.final_split_consumed ? "border-down/50 bg-down/10 text-[#f3a7a7]" : "border-line bg-panel2 text-ink2"}`} role="status">
            {d.final_split_consumed
              ? `Final split has been revealed (${d.vault_ledger.length} ledger entr${d.vault_ledger.length === 1 ? "y" : "ies"}). NOT BLIND ANYMORE — any later evaluation on it is not a blind test.`
              : "Final split not revealed: the vault ledger is empty, so the final test is still blind."}
            {d.note ? ` (${d.note})` : ""}
          </p>
          {syms.map((s) => {
            const it = inst[s];
            const qc = it.qc ?? {};
            return (
              <article key={s} className="space-y-2 rounded-md border border-line bg-panel2 p-3">
                <header className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-semibold text-ink">{s}</span>
                  <span className="text-muted">
                    {it.market} · {it.resolution}
                    {it.n_sources !== undefined ? ` · ${it.n_sources} source files` : ""}
                  </span>
                  <span className={`ml-auto rounded border px-1.5 py-0.5 text-[10px] font-bold ${it.all_checksums_verified ? "border-up/60 text-up" : "border-down/60 text-down"}`}>
                    {it.all_checksums_verified ? "✓ checksums verified" : "✗ checksum mismatch"}
                  </span>
                </header>
                <SplitTimeline files={it.files} lo={lo} hi={hi} finalConsumed={d.final_split_consumed} />
                <div className="relative h-3 text-[9px] text-muted" aria-hidden>
                  {years.map((y) => (
                    <span key={y} className="absolute -translate-x-1/2" style={{ left: `${((Date.UTC(y, 0, 1) - lo) / (hi - lo)) * 100}%` }}>
                      {y}
                    </span>
                  ))}
                </div>
                <div className="relative overflow-x-auto">
                  <table className="data">
                    <thead>
                      <tr>
                        <th scope="col">Split</th>
                        <th scope="col" className="num">Bars</th>
                        <th scope="col">First</th>
                        <th scope="col">Last</th>
                        <th scope="col">sha256</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(it.files).map(([k, f]) => (
                        <tr key={k}>
                          <td>
                            <span aria-hidden className="mr-1.5 inline-block h-2 w-2 rounded-sm" style={{ background: SPLIT_COLORS[k] ?? "#888" }} />
                            {k}
                          </td>
                          <td className="num">{f.bars.toLocaleString()}</td>
                          <td className="text-ink2">{f.first.slice(0, 16).replace("T", " ")}</td>
                          <td className="text-ink2">{f.last.slice(0, 16).replace("T", " ")}</td>
                          <td>
                            <Hash v={f.sha256} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3 lg:grid-cols-6">
                  {Object.entries(qc).map(([k, v]) => {
                    const warn = isNum(v) && v > 0 && !["rows_raw", "funding_events", "header_files"].includes(k);
                    return (
                      <div key={k} className="flex min-w-0 justify-between gap-2 border-b border-line py-0.5">
                        <dt className="truncate text-muted" title={k}>
                          {k.replace(/_/g, " ")}
                        </dt>
                        <dd className={`tnum ${warn ? "text-warn" : "text-ink"}`}>{fmtAny(v)}</dd>
                      </div>
                    );
                  })}
                </dl>
                {!!it.gaps_sample?.length && (
                  <p className="text-[11px] text-muted">
                    Gap sample: {it.gaps_sample.map(([a, b]) => `${fmtTime(a)} → ${fmtTime(b)}`).join("; ")}
                  </p>
                )}
              </article>
            );
          })}
          {d.vault_ledger.length > 0 && (
            <div>
              <H3>Vault ledger</H3>
              <JsonTable value={d.vault_ledger} />
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

/* ================================================================ 4. tasks table */

const GROUPS: { key: string; label: string; match: (t: TaskRow) => boolean }[] = [
  { key: "pending", label: "Pending (open, not started)", match: (t) => t.status === "open" && t.stage === "OBSERVE" },
  { key: "running", label: "Running (open)", match: (t) => t.status === "open" && t.stage !== "OBSERVE" },
  { key: "failed", label: "Failed", match: (t) => t.status === "failed" },
  { key: "done", label: "Done", match: (t) => t.status === "done" },
  { key: "other", label: "Other status", match: (t) => !["open", "failed", "done"].includes(t.status) },
];

export function TasksTable({ lab, rev, onOpen, selected }: { lab: string; rev: number; onOpen: (id: string) => void; selected: string | null }) {
  const p = usePoll<TaskRow[]>(`/api/research/${lab}/tasks`, 5000);
  useRefreshOn(rev, p.refresh);
  const rows = p.data ?? [];
  return (
    <Panel
      id="tasks"
      title="Experiments"
      subtitle="One pre-registered hypothesis and one candidate per task. Dev screen = walk-forward OOS Sharpe on development; Δ / P(Δ>0) = paired stationary-block bootstrap on validation."
      actions={<Prov kind="HISTORICAL BACKTEST" />}
    >
      <ErrorNote error={p.error} what="tasks" />
      {!rows.length && !p.loading && <EmptyState title="No tasks in this lab yet">Run a bounded campaign to create tasks.</EmptyState>}
      <div className="space-y-4">
        {GROUPS.map((g) => {
          const items = rows.filter(g.match).sort((a, b) => b.seq - a.seq);
          if (!items.length) return null;
          return (
            <section key={g.key} aria-label={`${g.label} tasks`}>
              <H3>
                {g.label} · {items.length}
              </H3>
              <div className="relative max-h-[520px] overflow-auto">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Task</th>
                      <th scope="col">Stage</th>
                      <th scope="col">Operator</th>
                      <th scope="col">Verdict</th>
                      <th scope="col" className="num" title="Candidate vs champion walk-forward OOS Sharpe on development">
                        Dev screen
                      </th>
                      <th scope="col" className="num" title="Validation paired Δ Sharpe (candidate − champion)">
                        Val Δ Sharpe
                      </th>
                      <th scope="col" className="num">P(Δ&gt;0)</th>
                      <th scope="col">Promotion checks</th>
                      <th scope="col">Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((t) => (
                      <tr key={t.id} className={selected === t.id ? "!bg-accent/15" : ""}>
                        <td>
                          <button className="text-left font-mono text-accent hover:underline" onClick={() => onOpen(t.id)} aria-label={`Open task ${t.id}`}>
                            {t.id}
                          </button>
                        </td>
                        <td className="text-ink2">{t.stage}</td>
                        <td className="text-ink2">
                          {t.operator ?? "—"}
                          {t.design_parent ? <span className="text-muted"> ← {t.design_parent}</span> : null}
                        </td>
                        <td>
                          <Verdict v={t.verdict ?? (t.status === "failed" ? "failed" : null)} />
                        </td>
                        <td className="num">
                          {t.screen ? (
                            <span title={`candidate ${t.screen.candidate_dev_oos_sharpe} vs champion ${t.screen.champion_dev_oos_sharpe}`}>
                              {num(t.screen.candidate_dev_oos_sharpe, 3)} <span className="text-muted">vs {num(t.screen.champion_dev_oos_sharpe, 3)}</span>{" "}
                              <span className={t.screen.passed ? "text-up" : "text-down"}>{t.screen.passed ? "✓" : "✗"}</span>
                              <span className="sr-only">{t.screen.passed ? "screen passed" : "screen failed"}</span>
                            </span>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                        <td className={`num ${isNum(t.delta_sharpe) ? (t.delta_sharpe > 0 ? "text-up" : "text-down") : ""}`}>{signed(t.delta_sharpe, 3)}</td>
                        <td className="num">{isNum(t.prob_positive) ? num(t.prob_positive, 3) : "—"}</td>
                        <td>
                          <CheckChips checks={t.checks} compact />
                        </td>
                        <td className="!whitespace-normal text-[11px] text-ink2">
                          {t.error && <span className="text-down">{t.error.slice(0, 120)}</span>}
                          {t.rejection && (
                            <span>
                              rejected at <b>{t.rejection.gate ?? "?"}</b>
                            </span>
                          )}
                          {t.duplicate_of && <span>duplicate of <code>{t.duplicate_of}</code></span>}
                          {t.activation && (
                            <span className={t.activation.activated ? "text-up" : ""}>
                              {t.activation.activated ? `activated v${t.activation.version ?? "?"}` : "not activated"}
                              {t.activation.rolled_back_to !== undefined ? ` · rolled back to v${t.activation.rolled_back_to}` : ""}
                              {t.activation.reason ? ` · ${t.activation.reason}` : ""}
                            </span>
                          )}
                          {!t.error && !t.rejection && !t.duplicate_of && !t.activation && <span className="text-muted">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          );
        })}
      </div>
      <p className="mt-2 text-[11px] text-muted">
        Check chips: ES effect size · PI probability of improvement · D drawdown · CR cost robustness (2× costs) · DS deflated Sharpe.
      </p>
    </Panel>
  );
}

/* ================================================================ 5. task drawer */

const DIAG_COLS: (keyof SymbolDiag)[] = [
  "net_sharpe",
  "gross_sharpe",
  "max_drawdown",
  "turnover_per_year",
  "avg_holding_bars",
  "trading_cost_share",
  "funding_cost_share",
  "sharpe_low_vol_tercile",
  "sharpe_high_vol_tercile",
];

function DiagTable({ diag, caption }: { diag: Record<string, SymbolDiag>; caption: string }) {
  const syms = Object.keys(diag);
  return (
    <div className="relative overflow-x-auto">
      <table className="data">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            {syms.map((s) => (
              <th key={s} scope="col" className="num">
                {s}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {DIAG_COLS.map((c) => (
            <tr key={c}>
              <th scope="row" className="!static !normal-case !tracking-normal text-ink2">
                {c.replace(/_/g, " ")}
              </th>
              {syms.map((s) => (
                <td key={s} className="num">
                  {fmtAny(diag[s]?.[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const SEV_CLS: Record<string, string> = {
  high: "border-down/60 bg-down/10 text-[#f3a7a7]",
  medium: "border-warn/60 bg-warn/10 text-warn",
  low: "border-line2 bg-panel2 text-ink2",
  info: "border-accent/50 bg-accent/10 text-[#9ec5f4]",
};

export function TaskDrawer({ lab, id, onClose }: { lab: string; id: string; onClose: () => void }) {
  const p = usePoll<TaskDetail>(`/api/research/${lab}/tasks/${id}`, 5000);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const d = p.data;
  const t = d?.task;
  const pre = t?.task ?? null;
  const ck = t?.checkpoint ?? {};
  const dec = ck.decision;
  const bs = dec?.bootstrap;
  const exp = d?.experiment ?? null;
  const verdict = (ck.archived as { verdict?: string } | undefined)?.verdict ?? ck.verdict ?? dec?.verdict ?? null;
  const prop = d?.candidate?.proposal;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/60" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="task-drawer-title"
        className="relative h-full w-full max-w-[920px] overflow-y-auto border-l border-line2 bg-page p-3 shadow-2xl sm:p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="sticky -top-3 z-10 -mx-3 mb-3 flex flex-wrap items-center gap-2 border-b border-line bg-page/95 px-3 py-2 backdrop-blur sm:-top-5 sm:-mx-5 sm:px-5">
          <h2 id="task-drawer-title" className="font-mono text-sm font-semibold">
            {id}
          </h2>
          {t && <Verdict v={t.status} />}
          {t && <span className="text-xs text-muted">stage {t.stage}</span>}
          {verdict && <Verdict v={verdict} />}
          <button ref={closeRef} className="btn btn-sm ml-auto" onClick={onClose}>
            Close <span className="sr-only">task detail</span>
            <span aria-hidden>✕</span>
          </button>
        </header>
        <ErrorNote error={p.error} what="task detail" />
        {!d && !p.error && <p className="text-xs text-muted">Loading…</p>}
        {d && t && (
          <div className="space-y-5">
            {t.error && (
              <p role="alert" className="whitespace-pre-wrap break-all rounded-md border border-down/40 bg-down/10 px-3 py-2 font-mono text-[11px] text-[#f3a7a7]">
                {t.error}
              </p>
            )}

            {/* ---- pre-registration */}
            <section aria-labelledby="pre-h" className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <h3 id="pre-h" className="text-sm font-semibold">
                  Pre-registered protocol
                </h3>
                {verdict ? (
                  <span className="text-xs text-ink2">
                    tested → <Verdict v={verdict} />
                  </span>
                ) : (
                  <Prov kind="HYPOTHESIS" />
                )}
              </div>
              {!pre ? (
                <EmptyState title="No pre-registration recorded for this task">
                  The task stopped before (or without) formulating a protocol — e.g. a duplicate candidate or an exhausted search space. Stage reached: {t.stage}
                  {ck.duplicate_of ? `; duplicate of ${String(ck.duplicate_of)}` : ""}.
                </EmptyState>
              ) : (
                <>
                  <p className="rounded-md border border-[#9085e9]/40 bg-[#9085e9]/10 px-3 py-2 text-sm text-ink">{pre.hypothesis ?? "—"}</p>
                  <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <Field k="Mechanism">{pre.mechanism ?? "—"}</Field>
                    <Field k="Testable prediction">{pre.testable_prediction ?? "—"}</Field>
                    <Field k="Alternatives considered">
                      {pre.alternatives?.length ? (
                        <ul className="list-disc pl-4">
                          {pre.alternatives.map((a, i) => (
                            <li key={i}>{a}</li>
                          ))}
                        </ul>
                      ) : (
                        "—"
                      )}
                    </Field>
                    <Field k="Refutation criteria">
                      {pre.refutation_criteria?.length ? (
                        <ul className="list-disc pl-4">
                          {pre.refutation_criteria.map((a, i) => (
                            <li key={i}>{a}</li>
                          ))}
                        </ul>
                      ) : (
                        "—"
                      )}
                    </Field>
                    <Field k="Primary metric">{pre.primary_metric ?? "—"}</Field>
                    <Field k="Minimal useful effect">
                      {pre.minimal_useful_effect ? Object.entries(pre.minimal_useful_effect).map(([k, v]) => `${k} = ${fmtAny(v)}`).join(", ") : "—"}
                    </Field>
                    <Field k="Secondary measures">{pre.secondary_measures?.join(" · ") || "—"}</Field>
                    <Field k="Stopping rule">{pre.stopping_rule ?? "—"}</Field>
                    <Field k="Pre-registration sha256">
                      <Hash v={pre.preregistration_sha256} n={64} />
                    </Field>
                    {pre.objective && <Field k="Objective">{pre.objective}</Field>}
                  </dl>
                  <details className="rounded-md border border-line bg-panel p-2 text-xs">
                    <summary className="cursor-pointer text-ink2">Allowed data, time split, statistical plan, sources</summary>
                    <div className="mt-2 space-y-2">
                      <JsonTable value={{ allowed_data: pre.allowed_data, time_split: pre.time_split, statistical_plan: pre.statistical_plan, sources: pre.sources }} />
                    </div>
                  </details>
                  {pre.initial_observation && (
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <H3>Initial observation (development split only)</H3>
                        <Prov kind="HISTORICAL BACKTEST" />
                      </div>
                      {pre.initial_observation.diagnostics_development_only && (
                        <DiagTable diag={pre.initial_observation.diagnostics_development_only} caption="Champion diagnostics on development" />
                      )}
                      <p className="text-xs text-ink2">
                        Selection reason: <span className="text-ink">{pre.initial_observation.selection_reason ?? "—"}</span>
                      </p>
                      {!!pre.initial_observation.operator_ranking?.length && (
                        <div className="relative overflow-x-auto">
                          <table className="data">
                            <thead>
                              <tr>
                                <th scope="col">Operator</th>
                                <th scope="col" className="num">Score</th>
                                <th scope="col">Evidence</th>
                              </tr>
                            </thead>
                            <tbody>
                              {pre.initial_observation.operator_ranking.map((r) => (
                                <tr key={r.operator}>
                                  <td>{r.operator}</td>
                                  <td className="num">{fmtAny(r.score)}</td>
                                  <td className="!whitespace-normal text-ink2">{r.evidence}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </section>

            {/* ---- candidate */}
            {(prop || d.candidate?.diff) && (
              <section aria-labelledby="cand-h" className="space-y-2">
                <h3 id="cand-h" className="text-sm font-semibold">
                  Candidate <code className="text-xs text-ink2">{ck.candidate_id ?? "—"}</code>
                </h3>
                {prop && (
                  <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <Field k="Generator">{prop.generator ?? "—"}</Field>
                    <Field k="Operator">{prop.operator ?? "—"}</Field>
                    <Field k="Design parent">
                      {prop.design_parent ?? "—"} (parent version v{fmtAny(prop.parent_version)})
                    </Field>
                    <Field k="Expected benefit">{prop.expected_benefit ?? "—"}</Field>
                    <Field k="Risk">{prop.risk ?? "—"}</Field>
                    <Field k="Code sha256">
                      <Hash v={prop.code_sha256} />
                    </Field>
                    <Field k="Base commit">
                      <Hash v={prop.base_commit} />
                    </Field>
                    <Field k="Contract">{prop.contract ?? "—"}</Field>
                    <Field k="Evaluation plan">{prop.eval_plan ?? "—"}</Field>
                  </dl>
                )}
                <DiffView diff={d.candidate?.diff} />
              </section>
            )}

            {/* ---- gates */}
            <section aria-labelledby="gates-h" className="space-y-2">
              <h3 id="gates-h" className="text-sm font-semibold">
                Gates
              </h3>
              <ul className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
                <li className="rounded-md border border-line bg-panel p-2">
                  <div className="text-[11px] uppercase tracking-wider text-muted">Causality spot checks</div>
                  {exp?.causality ? (
                    <div className={exp.causality.causal ? "text-up" : "text-down"}>
                      {exp.causality.causal ? "✓ causal" : "✗ look-ahead detected"} · {fmtAny(exp.causality.checked)} checked · {exp.causality.violations?.length ?? 0} violations
                    </div>
                  ) : (
                    <div className="text-muted">not run</div>
                  )}
                </li>
                <li className="rounded-md border border-line bg-panel p-2">
                  <div className="text-[11px] uppercase tracking-wider text-muted">Determinism</div>
                  {exp && typeof exp.deterministic === "boolean" ? (
                    <div className={exp.deterministic ? "text-up" : "text-down"}>{exp.deterministic ? "✓ deterministic re-run" : "✗ non-deterministic"}</div>
                  ) : (
                    <div className="text-muted">not run</div>
                  )}
                </li>
                <li className="rounded-md border border-line bg-panel p-2">
                  <div className="text-[11px] uppercase tracking-wider text-muted">Development screen</div>
                  {ck.screen ? (
                    <div className={ck.screen.passed ? "text-up" : "text-down"}>
                      {ck.screen.passed ? "✓ passed" : "✗ failed"} · OOS Sharpe {num(ck.screen.candidate_dev_oos_sharpe, 3)} vs champion {num(ck.screen.champion_dev_oos_sharpe, 3)}
                    </div>
                  ) : (
                    <div className="text-muted">not reached</div>
                  )}
                </li>
              </ul>
              {exp?.causality?.violations && exp.causality.violations.length > 0 && <JsonTable value={exp.causality.violations} />}
              {ck.rejection && (
                <p className="rounded-md border border-[#d55181]/50 bg-[#d55181]/10 px-3 py-2 text-xs">
                  Rejected at gate <b>{ck.rejection.gate ?? "?"}</b>: {typeof ck.rejection.detail === "string" ? ck.rejection.detail : JSON.stringify(ck.rejection.detail)}
                </p>
              )}
            </section>

            {/* ---- walk-forward */}
            {exp?.development?.per_symbol && (
              <section aria-labelledby="wf-h" className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 id="wf-h" className="text-sm font-semibold">
                    Walk-forward test windows (development)
                  </h3>
                  <Prov kind="HISTORICAL BACKTEST" />
                </div>
                <p className="text-xs text-ink2">
                  Portfolio OOS Sharpe {num(exp.development.portfolio_oos_sharpe, 3)} over {fmtAny(exp.development.days)} days.{" "}
                  {Object.entries(exp.development.per_symbol)
                    .map(([s, v]) => `${s}: ${fmtAny(v.n_windows)} windows, ${fmtAny(v.n_trials)} in-window trials`)
                    .join(" · ")}
                </p>
                <WindowBars perSymbol={exp.development.per_symbol} />
              </section>
            )}
            {exp?.diagnostics && (
              <details className="rounded-md border border-line bg-panel p-2 text-xs">
                <summary className="cursor-pointer text-ink2">Candidate diagnostics on development</summary>
                <div className="mt-2">
                  <DiagTable diag={exp.diagnostics} caption="Candidate diagnostics on development" />
                </div>
              </details>
            )}

            {/* ---- validation decision */}
            {dec && (
              <section aria-labelledby="val-h" className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 id="val-h" className="text-sm font-semibold">
                    Validation: candidate vs champion (paired)
                  </h3>
                  <Prov kind="HISTORICAL BACKTEST" />
                </div>
                <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                  <Field k="Champion Sharpe">{num(dec.champion_sharpe, 3)}</Field>
                  <Field k="Candidate Sharpe">{num(dec.candidate_sharpe, 3)}</Field>
                  <Field k="Δ Sharpe">{signed(bs?.delta_sharpe, 3)}</Field>
                  <Field k="P(Δ > 0)">{num(bs?.prob_positive, 3)}</Field>
                  <Field k="Common days">{fmtAny(dec.common_days)}</Field>
                  <Field k="Deflated Sharpe (DSR)">
                    {num(dec.dsr?.dsr, 3)} <span className="text-muted">(SR₀ {num(dec.dsr?.sr0, 3)})</span>
                  </Field>
                  <Field k="Validation trials (N for DSR)">{fmtAny(dec.n_validation_trials)}</Field>
                  {ck.validation_summary && (
                    <Field k="Max drawdown cand / champ">
                      {num(ck.validation_summary.candidate_mdd, 3)} / {num(ck.validation_summary.champion_mdd, 3)}
                    </Field>
                  )}
                </dl>
                {bs && (
                  <div>
                    <p className="mb-1 text-[11px] text-muted">
                      Δ Sharpe (candidate − champion): diamond = point estimate, whiskers = 95% CI, band = 90% CI. Stationary block bootstrap, {fmtAny(bs.resamples)} resamples, mean block {fmtAny(bs.mean_block)} days. Dashed: 0 and the minimal useful effect.
                    </p>
                    <IntervalPlot
                      label="Bootstrap confidence interval of validation delta Sharpe"
                      rows={[
                        {
                          label: "Δ Sharpe",
                          point: bs.delta_sharpe,
                          lo: bs.ci95_lo,
                          hi: bs.ci95_hi,
                          lo2: bs.ci90_lo,
                          hi2: bs.ci90_hi,
                          color: isNum(bs.delta_sharpe) && bs.delta_sharpe > 0 ? "#1baf7a" : "#e66767",
                          title: `Δ ${signed(bs.delta_sharpe, 3)} · 90% [${num(bs.ci90_lo, 3)}, ${num(bs.ci90_hi, 3)}] · 95% [${num(bs.ci95_lo, 3)}, ${num(bs.ci95_hi, 3)}]`,
                        },
                      ]}
                      refs={[
                        { at: 0, label: "0" },
                        ...(isNum((pre?.minimal_useful_effect as { delta_sharpe?: number } | undefined)?.delta_sharpe)
                          ? [{ at: (pre!.minimal_useful_effect as { delta_sharpe: number }).delta_sharpe, label: "MUE", color: "#fab219" }]
                          : []),
                      ]}
                    />
                    <p className="mt-1 text-xs text-ink2 tnum">
                      90% CI [{num(bs.ci90_lo, 3)}, {num(bs.ci90_hi, 3)}] · 95% CI [{num(bs.ci95_lo, 3)}, {num(bs.ci95_hi, 3)}]
                    </p>
                  </div>
                )}
                <div>
                  <H3>Promotion checks</H3>
                  <CheckChips checks={dec.checks} />
                </div>
              </section>
            )}

            {/* ---- critique */}
            {!!ck.critique?.length && (
              <section aria-labelledby="crit-h" className="space-y-2">
                <h3 id="crit-h" className="text-sm font-semibold">
                  Critique
                </h3>
                <ul className="space-y-1.5">
                  {ck.critique.map((c, i) => (
                    <li key={i} className="flex flex-wrap items-start gap-2 rounded-md border border-line bg-panel p-2 text-xs">
                      <span className={`rounded border px-1.5 py-px text-[10px] font-bold uppercase ${SEV_CLS[c.severity] ?? SEV_CLS.low}`}>{c.severity}</span>
                      <span className="min-w-0 flex-1 text-ink">{c.claim}</span>
                      <span className="w-full text-[11px] text-muted">
                        <code>{c.metric_ref}</code> = <code className="break-all">{typeof c.value === "object" ? JSON.stringify(c.value) : fmtAny(c.value)}</code>
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* ---- decision / activation */}
            <section aria-labelledby="dec-h" className="space-y-2">
              <h3 id="dec-h" className="text-sm font-semibold">
                Decision & activation
              </h3>
              <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <Field k="Verdict">
                  <Verdict v={verdict} />
                </Field>
                <Field k="Activation">
                  {ck.activation ? (
                    <span>
                      {ck.activation.activated ? `activated as v${fmtAny(ck.activation.version)}` : "not activated"}
                      {ck.activation.rolled_back_to !== undefined ? ` · rolled back to v${ck.activation.rolled_back_to}` : ""}
                      {ck.activation.reason ? ` · ${ck.activation.reason}` : ""}
                    </span>
                  ) : (
                    "none (no promotion)"
                  )}
                </Field>
                <Field k="Novelty">{ck.novelty ?? "—"}</Field>
              </dl>
            </section>
            <details className="rounded-md border border-line bg-panel p-2 text-xs">
              <summary className="cursor-pointer text-ink2">Raw checkpoint</summary>
              <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-ink2">{JSON.stringify(ck, null, 2)}</pre>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

/* ================================================================ 6. lineage */

export function LineagePanel({ lab, rev }: { lab: string; rev: number }) {
  const p = usePoll<Registry>(`/api/research/${lab}/registry`, 10000);
  useRefreshOn(rev, p.refresh);
  const r = p.data;
  const versions = (r?.versions ?? []).slice().sort((a, b) => a.version - b.version);
  return (
    <Panel id="lineage" title="Version lineage & rollbacks" subtitle="Champion versions in the lab registry (local experimental branch only). Highlighted = active.">
      <ErrorNote error={p.error} what="registry" />
      {r && (
        <div className="space-y-4">
          <ol className="flex flex-wrap items-stretch gap-2" aria-label="Version chain">
            {versions.map((v, i) => {
              const active = r.active?.version === v.version;
              return (
                <li key={v.version} className="flex items-center gap-2">
                  {i > 0 && (
                    <span aria-hidden className="text-muted">
                      →
                    </span>
                  )}
                  <div
                    className={`min-w-[150px] max-w-[260px] rounded-md border p-2 text-xs ${active ? "border-up bg-up/10 ring-1 ring-up/60" : "border-line bg-panel2"}`}
                    aria-current={active ? "true" : undefined}
                  >
                    <div className="flex items-center gap-2">
                      <b className="font-mono">v{v.version}</b>
                      {active && <span className="font-semibold text-up">● active</span>}
                    </div>
                    <div className="truncate text-ink2" title={v.candidate_id}>
                      {v.candidate_id}
                    </div>
                    <div className="text-muted">parent {v.parent_version === null ? "—" : `v${v.parent_version}`}</div>
                    <div className="break-words text-ink2">{v.reason}</div>
                    <div className="text-muted">{fmtTime(v.created)}</div>
                    <div>
                      sha <Hash v={v.sha256} n={10} />
                    </div>
                    {v.git_commit && (
                      <div>
                        commit <Hash v={v.git_commit} n={10} />
                      </div>
                    )}
                    {v.evidence && (
                      <details>
                        <summary className="cursor-pointer text-ink2">evidence</summary>
                        <JsonTable value={v.evidence} />
                      </details>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
          <div>
            <H3>Activation / rollback history</H3>
            <div className="relative max-h-64 overflow-auto">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Time</th>
                    <th scope="col" className="num">Active</th>
                    <th scope="col">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {r.history
                    .slice()
                    .reverse()
                    .map((h, i) => (
                      <tr key={i} className={/rollback/i.test(h.reason) ? "text-warn" : ""}>
                        <td className="text-muted">{fmtTime(h.ts)}</td>
                        <td className="num font-mono">v{h.active}</td>
                        <td className="!whitespace-normal">{h.reason}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}

/* ================================================================ 7. hypotheses */

const HSTATUSES = ["pending", "confirmed", "refuted", "inconclusive", "failed"];

export function HypothesesPanel({ lab, rev }: { lab: string; rev: number }) {
  const p = usePoll<Hypothesis[]>(`/api/research/${lab}/hypotheses`, 10000);
  useRefreshOn(rev, p.refresh);
  const [tab, setTab] = useState("all");
  const all = p.data ?? [];
  const statuses = Array.from(new Set([...HSTATUSES, ...all.map((h) => h.status)]));
  const shown = (tab === "all" ? all : all.filter((h) => h.status === tab)).slice().reverse();
  return (
    <Panel
      id="hypotheses"
      title="Hypothesis memory"
      subtitle="Every tested statement is kept — refuted and inconclusive results are evidence too, and block re-testing of duplicates."
      actions={<Prov kind="HYPOTHESIS" />}
    >
      <ErrorNote error={p.error} what="hypotheses" />
      <div role="tablist" aria-label="Hypothesis status" className="mb-3 flex flex-wrap gap-1">
        {["all", ...statuses].map((s) => {
          const n = s === "all" ? all.length : all.filter((h) => h.status === s).length;
          return (
            <button
              key={s}
              role="tab"
              aria-selected={tab === s}
              onClick={() => setTab(s)}
              className={`rounded-md px-2.5 py-1 text-xs ${tab === s ? "bg-panel2 font-semibold text-ink ring-1 ring-line2" : "text-ink2 hover:bg-panel2"}`}
            >
              {s} <span className="tnum text-muted">{n}</span>
            </button>
          );
        })}
      </div>
      <div role="tabpanel" className="relative max-h-[560px] space-y-2 overflow-y-auto pr-1">
        {!shown.length && <EmptyState title={`No ${tab === "all" ? "" : tab + " "}hypotheses`} />}
        {shown.map((h) => {
          const ev = (h.evidence ?? {}) as {
            screen?: { candidate_dev_oos_sharpe?: number; champion_dev_oos_sharpe?: number; passed?: boolean };
            validation_summary?: { candidate?: number; champion?: number };
            decision_checks?: Record<string, unknown>;
            duplicate_of?: string | null;
            rejection?: { gate?: string } | null;
          };
          return (
            <article key={h.id} className="rounded-md border border-line bg-panel2 p-2.5 text-xs">
              <header className="flex flex-wrap items-center gap-2">
                <Verdict v={h.status} />
                <code className="text-muted">{h.id}</code>
                <span className="text-ink2">
                  {h.operator} on {h.parent_id ?? "—"}
                </span>
                <span className="ml-auto text-muted">{fmtTime(h.updated)}</span>
              </header>
              <p className="mt-1.5 text-sm text-ink">{h.statement}</p>
              <p className="mt-1 text-ink2">
                {ev.screen && (
                  <span>
                    dev OOS Sharpe {num(ev.screen.candidate_dev_oos_sharpe, 3)} vs {num(ev.screen.champion_dev_oos_sharpe, 3)} ·{" "}
                  </span>
                )}
                {ev.validation_summary && (
                  <span>
                    validation Sharpe {num(ev.validation_summary.candidate, 3)} vs {num(ev.validation_summary.champion, 3)} ·{" "}
                  </span>
                )}
                {ev.duplicate_of && <span>duplicate of {ev.duplicate_of} · </span>}
                {ev.rejection?.gate && <span>rejected at {ev.rejection.gate} · </span>}
                <span className="text-muted">{h.novelty}</span>
              </p>
              {ev.decision_checks && (
                <div className="mt-1.5">
                  <CheckChips checks={ev.decision_checks} />
                </div>
              )}
              {h.evidence && (
                <details className="mt-1.5">
                  <summary className="cursor-pointer text-muted">evidence (signature {h.signature})</summary>
                  <div className="mt-1">
                    <JsonTable value={h.evidence} />
                  </div>
                </details>
              )}
            </article>
          );
        })}
      </div>
    </Panel>
  );
}

/* ================================================================ 9. journal */

export function JournalPanel({ lab, rev }: { lab: string; rev: number }) {
  const p = usePoll<Journal>(`/api/research/${lab}/journal?n=200`, 10000);
  useRefreshOn(rev, p.refresh);
  const j = p.data;
  const v = j?.verify;
  return (
    <Panel
      id="journal"
      title="Journal"
      subtitle="Append-only, hash-chained log of every decision (newest first, last 200)."
      actions={
        v ? (
          v.ok ? (
            <span className="rounded border border-up/60 bg-up/10 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-up" title={`head ${v.head}`}>
              ✓ CHAIN INTACT · {fmtAny(v.entries)} entries
            </span>
          ) : (
            <span role="alert" className="rounded border border-down bg-down/15 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-[#f3a7a7]">
              ✗ CHAIN BROKEN at {fmtAny(v.broken_at)}: {v.reason}
            </span>
          )
        ) : null
      }
    >
      <ErrorNote error={p.error} what="journal" />
      {v?.head && (
        <p className="mb-2 text-[11px] text-muted">
          head <Hash v={v.head} n={64} />
        </p>
      )}
      {j && (
        <div className="relative max-h-[420px] overflow-auto">
          <table className="data">
            <thead>
              <tr>
                <th scope="col" className="num">Seq</th>
                <th scope="col">Time</th>
                <th scope="col">Actor</th>
                <th scope="col">Event</th>
                <th scope="col">Data</th>
                <th scope="col">Hash</th>
              </tr>
            </thead>
            <tbody>
              {j.entries.map((e) => (
                <tr key={e.seq}>
                  <td className="num">{e.seq}</td>
                  <td className="text-muted">{fmtTime(e.ts)}</td>
                  <td className="text-ink2">{e.actor}</td>
                  <td className={/stop|rollback|activat/.test(e.event) ? "font-semibold text-warn" : ""}>{e.event}</td>
                  <td className="!whitespace-normal">
                    <code className="block max-w-[420px] break-all text-[11px] text-ink2">{JSON.stringify(e.data).slice(0, 240)}</code>
                  </td>
                  <td>
                    <Hash v={e.hash} n={8} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/* ================================================================ 10. final */

export function FinalPanel({ rev }: { rev: number }) {
  const p = usePoll<FinalReport[]>("/api/research/final", 30000);
  useRefreshOn(rev, p.refresh);
  const all = p.data ?? [];
  // /api/research/final returns every *.json in the final dir: comparison reports (with `strategies`) and
  // pre-registration documents (no `strategies`). Render them separately.
  const reports = all.filter((r) => r && typeof r === "object" && "strategies" in r);
  const plans = all.filter((r) => !(r && typeof r === "object" && "strategies" in r)) as unknown as Record<string, unknown>[];
  const prevN = (v: unknown) => (Array.isArray(v) ? v.length : isNum(v) ? v : 0);
  const dsrOf = (v: unknown): { dsr?: number; sr0?: number } | undefined =>
    isNum(v) ? { dsr: v } : v && typeof v === "object" ? (v as { dsr?: number; sr0?: number }) : undefined;
  return (
    <Panel
      id="final"
      title="Final comparison (question C)"
      subtitle="Frozen v0 vs evolved arms on the sealed final split, revealed once. Holm-corrected one-sided tests at α = 0.05."
      actions={<Prov kind="HISTORICAL BACKTEST" />}
    >
      <ErrorNote error={p.error} what="final reports" />
      {p.data && !reports.length && (
        <EmptyState title="Final vault not revealed yet">
          No final report exists. The final split stays blind until the trusted supervisor reveals it once at the end of the comparison.
        </EmptyState>
      )}
      <div className="space-y-5">
        {reports.map((r, i) => {
          const notBlind = r.blind === false || prevN(r.previous_reveals) > 0;
          const strat = r.strategies ?? {};
          const paired = r.paired_vs_frozen_v0 ?? {};
          const holm = r["holm_one_sided_alpha_0.05"] ?? {};
          const primary = new Set(r.primary_comparisons ?? []);
          const explor = new Set(r.exploratory_comparisons ?? []);
          const role = (k: string) => (primary.has(k) ? "primary" : explor.has(k) ? "exploratory" : k === "frozen_v0" ? "baseline" : k.startsWith("benchmark") ? "benchmark" : "—");
          const syms = Array.from(new Set(Object.values(strat).flatMap((s) => Object.keys(s.per_symbol ?? {}))));
          return (
            <article key={i} className="space-y-3 rounded-md border border-line bg-panel2 p-3">
              <header className="flex flex-wrap items-center gap-2 text-xs">
                <b>{r.label ?? `report ${i + 1}`}</b>
                <span className="text-muted">{fmtTime(r.created_utc)}</span>
                {notBlind ? <Prov kind="NOT BLIND ANYMORE" /> : <span className="rounded border border-up/60 px-1.5 py-0.5 text-[10px] font-bold text-up">BLIND (first reveal)</span>}
                <span className="text-muted">
                  previous reveals {prevN(r.previous_reveals)} · validation trials across arms {fmtAny(r.validation_trials_across_arms)}
                </span>
              </header>
              {r.final_split && (
                <p className="text-[11px] text-muted">
                  final split {String((r.final_split as { start?: string }).start ?? "?")} → {String((r.final_split as { end_exclusive?: string }).end_exclusive ?? "?")} (exclusive)
                </p>
              )}
              <div className="relative overflow-x-auto">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Strategy</th>
                      <th scope="col">Role</th>
                      <th scope="col" className="num">Sharpe</th>
                      <th scope="col" className="num">Sharpe @2× costs</th>
                      <th scope="col" className="num">Return</th>
                      <th scope="col" className="num">Max DD</th>
                      <th scope="col" className="num" title="Deflated Sharpe ratio vs all validation trials (SR₀ in brackets)">DSR [SR₀]</th>
                      {syms.map((s) => (
                        <th key={s} scope="col" className="num">
                          {s} Sharpe
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(strat).map(([k, s]) => {
                      const d = dsrOf(s.dsr_vs_all_trials);
                      const ps = (s.per_symbol ?? {}) as Record<string, { sharpe?: number }>;
                      return (
                        <tr key={k} className={role(k) === "exploratory" ? "text-ink2" : ""}>
                          <td>{k}</td>
                          <td className={role(k) === "primary" ? "font-semibold" : "text-muted"}>{role(k)}</td>
                          <td className="num">{num(s.sharpe, 3)}</td>
                          <td className="num">{num(s.sharpe_2x_costs, 3)}</td>
                          <td className="num">{isNum(s.return) ? `${(s.return * 100).toFixed(2)}%` : "—"}</td>
                          <td className="num">{num(s.max_drawdown, 3)}</td>
                          <td className="num">{d ? `${num(d.dsr, 3)} [${num(d.sr0, 3)}]` : "—"}</td>
                          {syms.map((sy) => (
                            <td key={sy} className="num">
                              {num(ps[sy]?.sharpe, 3)}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="text-[11px] text-muted">Exploratory rows are reported but, per the pre-registration, not used for any claim of progress.</p>
              {Object.keys(paired).length > 0 && (
                <div>
                  <H3>Paired Δ Sharpe vs frozen v0 (95% CI)</H3>
                  <IntervalPlot
                    label="Paired delta Sharpe versus frozen v0 with 95% confidence intervals"
                    rows={Object.entries(paired).map(([k, v]) => ({
                      label: k,
                      point: v.delta_sharpe,
                      lo: v.ci95_lo,
                      hi: v.ci95_hi,
                      color: isNum(v.delta_sharpe) && v.delta_sharpe > 0 ? "#1baf7a" : isNum(v.delta_sharpe) && v.delta_sharpe < 0 ? "#e66767" : "#898781",
                      title: `${k}: Δ ${signed(v.delta_sharpe, 3)} [${num(v.ci95_lo, 3)}, ${num(v.ci95_hi, 3)}] · P(Δ>0) ${num(v.prob_positive, 3)}`,
                    }))}
                    refs={[{ at: 0, label: "0" }]}
                    labelWidth={200}
                  />
                  <ul className="mt-1 space-y-0.5 break-words text-xs text-ink2 [overflow-wrap:anywhere]">
                    {Object.entries(paired).map(([k, v]) => (
                      <li key={k}>
                        {k} ({role(k)}): Δ {signed(v.delta_sharpe, 3)} · 95% CI [{num(v.ci95_lo, 3)}, {num(v.ci95_hi, 3)}] · P(Δ&gt;0) {num(v.prob_positive, 3)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {Object.keys(holm).length > 0 && (
                <div className="relative overflow-x-auto">
                  <H3>Holm one-sided tests (α = 0.05)</H3>
                  <table className="data">
                    <thead>
                      <tr>
                        <th scope="col">Hypothesis</th>
                        <th scope="col" className="num">p</th>
                        <th scope="col" className="num">Holm threshold</th>
                        <th scope="col">Reject H₀</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(holm).map(([k, v]) => (
                        <tr key={k}>
                          <td>{k}</td>
                          <td className="num">{fmtAny(v.p)}</td>
                          <td className="num">{fmtAny(v.threshold)}</td>
                          <td className={v.reject_null ? "font-semibold text-up" : "text-ink2"}>{v.reject_null === undefined ? "—" : v.reject_null ? "yes" : "no"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {r.note && <p className="text-xs text-ink2">{r.note}</p>}
            </article>
          );
        })}
        {plans.map((pl, i) => (
          <article key={`plan-${i}`} className="space-y-2 rounded-md border border-[#9085e9]/40 bg-panel2 p-3 text-xs">
            <header className="flex flex-wrap items-center gap-2">
              <b>Pre-registered comparison plan</b>
              <Prov kind="HYPOTHESIS" />
              <span className="text-muted">
                {String(pl.campaign ?? "")} · written {fmtTime(pl.written_utc)}
              </span>
              {typeof pl.sha256 === "string" && (
                <span className="text-muted">
                  sha256 <Hash v={pl.sha256} />
                </span>
              )}
            </header>
            <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {Object.entries(pl)
                .filter(([k]) => !["campaign", "written_utc", "sha256"].includes(k))
                .map(([k, v]) => (
                  <Field key={k} k={humanize(k)}>
                    {Array.isArray(v) ? v.map((x) => fmtAny(x)).join(", ") : typeof v === "object" && v !== null ? JSON.stringify(v) : fmtAny(v)}
                  </Field>
                ))}
            </dl>
          </article>
        ))}
      </div>
    </Panel>
  );
}

/* ================================================================ 11. calibration */

function ciTxt(s?: CiStat): string {
  if (!s || !isNum(s.mean)) return "—";
  return `${num(s.mean, 3)} [${num(s.lo, 3)}, ${num(s.hi, 3)}]`;
}

export function CalibrationPanel({ rev }: { rev: number }) {
  const p = usePoll<Calibration>("/api/research/calibration", 0);
  useRefreshOn(rev, p.refresh);
  const c = p.data;
  const ev = c?.evaluation;
  const facts = Object.keys(c?.targets?.train ?? {});
  const splits: ["train" | "validation" | "heldout", string][] = [
    ["train", "train"],
    ["validation", "validation"],
    ["heldout", "held-out"],
  ];
  const sens = Object.entries(c?.sensitivity_dlog_vol_dlog_knob ?? {}).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const sensMax = Math.max(1e-9, ...sens.map(([, v]) => Math.abs(v)));
  const liq = c?.liquidity_supply ?? null;
  return (
    <Panel
      id="calibration"
      title="Simulator realism (question A)"
      subtitle={c?.question ?? "Does calibrating the simulator on train days improve its fit on validation / held-out days?"}
      actions={
        <>
          <Prov kind="HISTORICAL TARGETS" />
          <Prov kind="SYNTHETIC" />
        </>
      }
    >
      {p.error && (p.error as { status?: number }).status === 404 ? (
        <EmptyState title="No calibration report">The backend reports none yet ({(p.error as Error).message}).</EmptyState>
      ) : (
        <ErrorNote error={p.error} what="calibration" />
      )}
      {c && (
        <div className="space-y-5">
          {c.created_utc && <p className="text-[11px] text-muted">report {fmtTime(c.created_utc)}</p>}
          {ev && (
            <section aria-labelledby="dist-h" className="space-y-2">
              <h3 id="dist-h" className="text-sm font-semibold">
                Distance to historical stylised facts (lower = closer)
              </h3>
              <p className="text-[11px] text-muted">
                Mean over {ev.seeds?.length ?? "?"} simulator seeds; whiskers = 95% percentile-bootstrap CI of the mean. Grey = default simulator, blue = calibrated
                knobs.
              </p>
              <IntervalPlot
                label="Calibration distance by split, default vs calibrated, with 95% bootstrap CI"
                rows={splits.flatMap(([k, lbl]) => {
                  const dd = ev.default?.[`${k}_distance` as const];
                  const cc = ev.calibrated?.[`${k}_distance` as const];
                  return [
                    { label: `${lbl} · default`, point: dd?.mean, lo: dd?.lo, hi: dd?.hi, color: "#898781" },
                    { label: `${lbl} · calibrated`, point: cc?.mean, lo: cc?.lo, hi: cc?.hi, color: "#3987e5" },
                  ];
                })}
                labelWidth={140}
              />
              <div className="relative overflow-x-auto">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Split</th>
                      <th scope="col" className="num">Default · mean [95% boot CI]</th>
                      <th scope="col" className="num">Calibrated · mean [95% boot CI]</th>
                      <th scope="col" className="num">95% t-CI (default / calibrated)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {splits.map(([k, lbl]) => {
                      const dd = ev.default?.[`${k}_distance` as const];
                      const cc = ev.calibrated?.[`${k}_distance` as const];
                      return (
                        <tr key={k}>
                          <td>{lbl}</td>
                          <td className="num">{ciTxt(dd)}</td>
                          <td className="num">{ciTxt(cc)}</td>
                          <td className="num text-ink2">
                            [{num(dd?.t_lo, 2)}, {num(dd?.t_hi, 2)}] / [{num(cc?.t_lo, 2)}, {num(cc?.t_hi, 2)}]
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="text-[11px] text-muted">
                n = {ev.default?.train_distance?.n ?? "?"} seeds per arm. Bootstrap CIs of default and calibrated{" "}
                {splits
                  .map(([k, lbl]) => {
                    const dd = ev.default?.[`${k}_distance` as const];
                    const cc = ev.calibrated?.[`${k}_distance` as const];
                    if (!isNum(dd?.lo) || !isNum(dd?.hi) || !isNum(cc?.lo) || !isNum(cc?.hi)) return `${lbl}: n/a`;
                    return `${lbl}: ${dd.lo <= cc.hi && cc.lo <= dd.hi ? "overlap" : "do not overlap"}`;
                  })
                  .join(" · ")}
                .
              </p>
            </section>
          )}

          {facts.length > 0 && (
            <section aria-labelledby="facts-h" className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <h3 id="facts-h" className="text-sm font-semibold">
                  Stylised facts
                </h3>
                <Prov kind="HISTORICAL TARGETS" />
                <span className="text-[11px] text-muted">median [IQR] over 60-min windows ({Object.entries(c.targets?.windows ?? {}).map(([k, v]) => `${k} ${v}`).join(", ")})</span>
                <Prov kind="SYNTHETIC" />
                <span className="text-[11px] text-muted">mean [95% boot CI]</span>
              </div>
              <div className="relative overflow-x-auto">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Fact</th>
                      <th scope="col" className="num">Hist. train</th>
                      <th scope="col" className="num">Hist. validation</th>
                      <th scope="col" className="num">Hist. held-out</th>
                      <th scope="col" className="num">Sim default</th>
                      <th scope="col" className="num">Sim calibrated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {facts.map((f) => {
                      const t = (k: "train" | "validation" | "heldout") => {
                        const v = c.targets?.[k]?.[f];
                        return v ? `${num(v[0], 3)} [${num(v[1], 3)}]` : "—";
                      };
                      return (
                        <tr key={f}>
                          <td>{f}</td>
                          <td className="num">{t("train")}</td>
                          <td className="num">{t("validation")}</td>
                          <td className="num">{t("heldout")}</td>
                          <td className="num">{ciTxt(ev?.default?.facts?.[f])}</td>
                          <td className="num">{ciTxt(ev?.calibrated?.facts?.[f])}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {c.selected_knobs && (
              <section aria-labelledby="knobs-h">
                <h3 id="knobs-h" className="mb-1 text-sm font-semibold">
                  Selected knobs
                </h3>
                <p className="mb-1 text-[11px] text-muted">
                  Chosen by train distance among {fmtAny(c.search?.n_configs)} configs × {fmtAny(c.search?.seeds_per_config)} seeds ({fmtAny(c.search?.duration_s)} s each).
                </p>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs">
                  {Object.entries(c.selected_knobs).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-2 border-b border-line py-0.5">
                      <dt className="text-muted">{k}</dt>
                      <dd className="tnum">{num(v, 3)}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}
            {sens.length > 0 && (
              <section aria-labelledby="sens-h">
                <h3 id="sens-h" className="mb-1 text-sm font-semibold">
                  Sensitivity d log(vol) / d log(knob)
                </h3>
                <ul className="space-y-1 text-xs">
                  {sens.map(([k, v]) => (
                    <li key={k} className="grid grid-cols-[110px_minmax(0,1fr)_60px] items-center gap-2">
                      <span className="truncate text-ink2">{k}</span>
                      <span className="relative h-2.5 rounded bg-line" aria-hidden>
                        <span className="absolute top-0 h-full w-px bg-muted" style={{ left: "50%" }} />
                        <span
                          className={`absolute top-0 h-full ${v >= 0 ? "bg-accent" : "bg-down"}`}
                          style={v >= 0 ? { left: "50%", width: `${(v / sensMax) * 50}%` } : { right: "50%", width: `${(-v / sensMax) * 50}%` }}
                        />
                      </span>
                      <span className="text-right tnum">{signed(v, 3)}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>

          {!!c.caveats?.length && (
            <section aria-labelledby="cav-h" className="rounded-md border border-warn/40 bg-warn/5 p-3">
              <h3 id="cav-h" className="mb-1 text-sm font-semibold text-warn">
                Caveats (verbatim)
              </h3>
              <ul className="list-disc space-y-0.5 pl-5 text-xs text-ink2">
                {c.caveats.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </section>
          )}

          {liq && (
            <section aria-labelledby="liq-h" className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <h3 id="liq-h" className="text-sm font-semibold">
                  Liquidity supply by agent kind
                </h3>
                <Prov kind="SYNTHETIC" />
                <Prov kind="MECHANISM TEST" />
              </div>
              <p className="text-[11px] text-muted">Share of resting depth within 20 bps of mid by owner kind, sampled inside the shock window (_total_btc = total depth in BTC); mean [min, max] across seeds.</p>
              <div className="relative overflow-x-auto">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Kind</th>
                      {Object.keys(liq).map((sc) => (
                        <th key={sc} scope="col" className="num">
                          {humanize(sc)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from(new Set(Object.values(liq).flatMap((x) => Object.keys(x)))).map((kind) => (
                      <tr key={kind}>
                        <td>{kind}</td>
                        {Object.keys(liq).map((sc) => {
                          const s = liq[sc]?.[kind];
                          return (
                            <td key={sc} className="num">
                              {s ? `${num(s.mean, 3)} [${num(s.min, 3)}, ${num(s.max, 3)}]` : "—"}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}
    </Panel>
  );
}
