"use client";
import type { ReactNode } from "react";
import { ClassChip, Hash, PremiseChip, Prov } from "./research";
import { fmtAny, fmtTime, num, signed } from "@/lib/format";
import type { Classification, Dossier, EngineFeature, External, ExternalHypothesis, Mechanism, ParentBehaviour, PremiseCheck, PremiseCheckSpec } from "@/lib/research";

/* Evidence sections of the task drawer: verified premises, mechanism test, descriptive class, technical dossier, LLM motivation.
   Every number shown is read from the API; nothing is derived except formatting. */

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

/** relative change (fraction) → signed percent */
export function relPct(v: unknown, digits = 1): string {
  return isNum(v) ? `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(digits)}%` : "—";
}

/** Human-readable description of a machine-checkable premise. */
export function describeCheck(c: PremiseCheckSpec | undefined): string {
  if (!c) return "—";
  switch (c.type) {
    case "parent_metric":
      return `parent ${c.metric} [${c.symbol ?? "?"}] ${c.op ?? "?"} ${fmtAny(c.value)}`;
    case "engine_feature":
      return `engine feature ${c.feature} expected ${c.expect ?? "?"}`;
    case "view_api":
      return `view API .${c.method} expected ${c.expect ?? "?"}`;
    case "unverifiable":
      return `unverifiable${c.reason ? `: ${c.reason}` : ""}`;
    default: {
      const { type, ...rest } = c;
      return `${type} ${JSON.stringify(rest)}`;
    }
  }
}

/* ---------------------------------------------------------------- premises */

export function PremiseTable({ pc, caption }: { pc: PremiseCheck; caption: string }) {
  const c = pc.counts;
  return (
    <div className="space-y-2">
      <p className="flex flex-wrap items-center gap-2 text-xs text-ink2">
        Verdict <PremiseChip v={pc.verdict} />
        {c && (
          <span className="tnum">
            {c.verified} verified · {c.falsified} falsified · {c.unverifiable} unverifiable · {c.invalid} invalid
          </span>
        )}
      </p>
      <div className="relative overflow-x-auto">
        <table className="data">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Claim</th>
              <th scope="col">Check</th>
              <th scope="col">Status</th>
              <th scope="col">Evidence</th>
            </tr>
          </thead>
          <tbody>
            {pc.results.map((r) => (
              <tr key={r.id}>
                <td className="font-mono text-muted">{r.id}</td>
                <td className="min-w-[200px] !whitespace-normal">{r.claim}</td>
                <td className="min-w-[160px] !whitespace-normal font-mono text-[11px] text-ink2">{describeCheck(r.check)}</td>
                <td>
                  <PremiseChip v={r.status} />
                </td>
                <td className="min-w-[220px] !whitespace-normal break-words text-[11px] text-ink2 [overflow-wrap:anywhere]">{r.evidence ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function PremisesSection({ pc }: { pc: PremiseCheck | null | undefined }) {
  return (
    <section aria-labelledby="prem-h" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="prem-h" className="text-sm font-semibold">
          Verified premises
        </h3>
        <Prov kind="HISTORICAL BACKTEST" />
      </div>
      <p className="text-[11px] text-muted">
        Factual claims the proposal relies on, checked by the trusted evaluator against the parent&apos;s development behaviour and engine probes before any backtest.
      </p>
      {pc ? <PremiseTable pc={pc} caption="Premise checks for this task" /> : <p className="text-xs text-muted">No premise check recorded for this task (generator did not declare premises, or the task predates premise checking).</p>}
    </section>
  );
}

/* ---------------------------------------------------------------- mechanism */

export function MechanismSection({ m }: { m: Mechanism | null | undefined }) {
  return (
    <section aria-labelledby="mech-h" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="mech-h" className="text-sm font-semibold">
          Mechanism test
        </h3>
        <Prov kind="MECHANISM TEST" />
        <Prov kind="HISTORICAL BACKTEST" />
      </div>
      {!m || !m.declared ? (
        <p className="text-xs text-muted">No mechanism test declared for this candidate — nothing to observe.</p>
      ) : (
        <>
          {m.test && (
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Field k="Metric">
                <code>{m.test.metric}</code>
              </Field>
              <Field k="Symbol">{m.test.symbol}</Field>
              <Field k="Direction">{m.test.direction}</Field>
              <Field k="Threshold">≥ {isNum(m.test.min_relative_change) ? `${(m.test.min_relative_change * 100).toFixed(0)}%` : "—"} relative change</Field>
            </dl>
          )}
          {m.per_symbol && Object.keys(m.per_symbol).length > 0 && (
            <div className="relative overflow-x-auto">
              <table className="data">
                <caption className="sr-only">Mechanism metric per symbol, candidate versus parent on development</caption>
                <thead>
                  <tr>
                    <th scope="col">Symbol</th>
                    <th scope="col" className="num">Parent</th>
                    <th scope="col" className="num">Candidate</th>
                    <th scope="col" className="num">Relative change</th>
                    <th scope="col">Meets threshold</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(m.per_symbol).map(([sym, v]) => (
                    <tr key={sym}>
                      <td>{sym}</td>
                      <td className="num">{fmtAny(v.parent)}</td>
                      <td className="num">{fmtAny(v.candidate)}</td>
                      <td className="num">{relPct(v.relative_change)}</td>
                      <td className={v.ok ? "text-up" : v.ok === false ? "text-down" : "text-muted"}>{v.ok === undefined ? "—" : v.ok ? "✓ yes" : "✗ no"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs">
            Mechanism{" "}
            {m.observed === true ? (
              <b className="text-up">observed</b>
            ) : m.observed === false ? (
              <b className="text-down">not observed</b>
            ) : (
              <b className="text-muted">not evaluated</b>
            )}{" "}
            on development.
          </p>
        </>
      )}
    </section>
  );
}

/* ---------------------------------------------------------------- classification */

export function ClassificationSection({ c }: { c: Classification | null | undefined }) {
  const d = c?.detail;
  const deltas = d?.dev_deltas_vs_parent ?? {};
  return (
    <section aria-labelledby="cls-h" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="cls-h" className="text-sm font-semibold">
          Classification
        </h3>
        <ClassChip c={c?.class} />
      </div>
      <p className="rounded-md border border-warn/40 bg-warn/5 px-3 py-1.5 text-[11px] text-warn">
        Descriptive, does not prove cause.{c?.note ? <span className="text-ink2"> API note: “{c.note}”</span> : null}
      </p>
      {!c ? (
        <p className="text-xs text-muted">No classification recorded.</p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Field k="Validation verdict">{d?.validation_verdict ?? "—"}</Field>
            <Field k="Dev OOS gain vs champion">{signed(d?.dev_oos_gain_vs_champion, 3)}</Field>
            {d?.dev_screen_passed !== undefined && <Field k="Dev screen passed">{fmtAny(d.dev_screen_passed)}</Field>}
            {d?.instruments_disagree !== undefined && <Field k="Instruments disagree">{fmtAny(d.instruments_disagree)}</Field>}
          </dl>
          {Object.keys(deltas).length > 0 && (
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <H3>Development deltas vs parent (candidate − parent)</H3>
                <Prov kind="HISTORICAL BACKTEST" />
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs sm:grid-cols-3">
                {Object.entries(deltas).map(([k, v]) => (
                  <div key={k} className="flex min-w-0 justify-between gap-2 border-b border-line py-0.5">
                    <dt className="truncate text-muted" title={k}>
                      {k.replace(/_/g, " ")}
                    </dt>
                    <dd className="tnum">{isNum(v) ? signed(v, Math.abs(v) >= 10 ? 1 : 3) : fmtAny(v)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
          {(c.method || c.reclassified_utc) && (
            <p className="text-[11px] text-muted">
              {c.method}
              {c.reclassified_utc ? ` · reclassified ${fmtTime(c.reclassified_utc)}` : ""}
            </p>
          )}
        </>
      )}
    </section>
  );
}

/* ---------------------------------------------------------------- engine features / dossier */

export function EngineFeatureTable({ features, caption }: { features: Record<string, EngineFeature>; caption: string }) {
  return (
    <div className="relative overflow-x-auto">
      <table className="data">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Feature</th>
            <th scope="col">Present</th>
            <th scope="col">Description</th>
            <th scope="col">Probe evidence</th>
            <th scope="col">Code</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(features).map(([k, f]) => (
            <tr key={k}>
              <td className="font-mono text-[11px]">{k}</td>
              <td className={f.present ? "text-up" : "text-down"}>{f.present ? "✓ yes" : "✗ no"}</td>
              <td className="min-w-[180px] !whitespace-normal text-[11px] text-ink2">{f.description ?? "—"}</td>
              <td className="min-w-[180px] !whitespace-normal break-words font-mono text-[11px] text-ink2 [overflow-wrap:anywhere]">{f.probe_evidence ?? "—"}</td>
              <td className="text-[11px]">
                {f.code ? (
                  <span title={`${f.code.file}:${f.code.line} · sha256 ${f.code.sha256}`}>
                    <code className="text-ink2">
                      {f.code.file.replace(/^src\/evolutionx\//, "")}:{f.code.line}
                    </code>{" "}
                    <Hash v={f.code.sha256} n={8} label="file sha256" />
                  </span>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const PB_COLS = ["net_sharpe", "gross_sharpe", "max_drawdown", "turnover_per_year", "trading_cost_share", "funding_cost_share", "decision_change_rate", "small_change_execution_ratio", "fills_per_day"];

export function ParentBehaviourTable({ pb, caption }: { pb: Record<string, ParentBehaviour>; caption: string }) {
  const syms = Object.keys(pb);
  const cols = PB_COLS.filter((c) => syms.some((s) => c in pb[s]));
  const years = Array.from(new Set(syms.flatMap((s) => Object.keys(pb[s].per_year ?? {})))).sort();
  return (
    <div className="space-y-2">
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
            {cols.map((c) => (
              <tr key={c}>
                <th scope="row" className="!static !normal-case !tracking-normal text-ink2">
                  {c.replace(/_/g, " ")}
                </th>
                {syms.map((s) => (
                  <td key={s} className="num">
                    {isNum(pb[s][c]) ? num(pb[s][c], 3) : fmtAny(pb[s][c])}
                  </td>
                ))}
              </tr>
            ))}
            {years.map((y) => (
              <tr key={y}>
                <th scope="row" className="!static !normal-case !tracking-normal text-ink2">
                  {y} net Sharpe / max DD / liq.
                </th>
                {syms.map((s) => {
                  const py = pb[s].per_year?.[y];
                  const ruined = pb[s].ruined_segments?.map(String).includes(y);
                  return (
                    <td key={s} className={`num ${ruined ? "text-down" : ""}`} title={ruined ? "ruined segment" : undefined}>
                      {py ? `${num(py.net_sharpe, 2)} / ${num(py.max_drawdown, 2)} / ${fmtAny(py.liquidations)}` : "—"}
                      {ruined ? " ☠" : ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-muted">
        Ruined segments (☠, red): {syms.map((s) => `${s} ${pb[s].ruined_segments?.length ? pb[s].ruined_segments!.join(", ") : "none"}`).join(" · ")}. Method{" "}
        {Array.from(new Set(syms.map((s) => pb[s].method).filter(Boolean))).join(", ") || "—"}.
      </p>
    </div>
  );
}

export function DossierSection({ dz, taskDossierSha }: { dz: Dossier | null | undefined; taskDossierSha?: string }) {
  return (
    <section aria-labelledby="dz-h" className="space-y-2">
      <h3 id="dz-h" className="text-sm font-semibold">
        Technical dossier
      </h3>
      {!dz ? (
        <p className="text-xs text-muted">
          No dossier for this task{taskDossierSha ? ` (checkpoint references ${taskDossierSha.slice(0, 12)}…, but the API returned none)` : " (offline generator, or task predates dossiers)"}.
        </p>
      ) : (
        <>
          <p className="text-[11px] text-muted">The verified, hashed context given to the generator: code excerpts, engine probes and the parent&apos;s development behaviour.</p>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Field k="Dossier sha256">
              <Hash v={dz.dossier_sha256} n={16} />
            </Field>
            <Field k="Git commit">
              <Hash v={dz.git_commit} />
            </Field>
            <Field k="Generated">{fmtTime(dz.generated_utc)}</Field>
            <Field k="Size / lessons">
              {fmtAny(dz.size_chars)} chars · {dz.has_lessons ? "includes lessons (memory)" : "no lessons"}
            </Field>
          </dl>
          {taskDossierSha && taskDossierSha !== dz.dossier_sha256 && (
            <p role="alert" className="text-xs text-down">
              Checkpoint dossier sha {taskDossierSha.slice(0, 12)}… differs from the served dossier {dz.dossier_sha256.slice(0, 12)}….
            </p>
          )}
          {dz.rebalance_rule && (
            <div>
              <H3>Rebalance rule</H3>
              <p className="rounded-md border border-line bg-panel p-2 text-xs text-ink">{dz.rebalance_rule}</p>
            </div>
          )}
          {dz.engine_features && (
            <div>
              <H3>Engine features (probed)</H3>
              <EngineFeatureTable features={dz.engine_features} caption="Engine features with probe evidence" />
            </div>
          )}
          {dz.parent_behaviour && (
            <details className="rounded-md border border-line bg-panel p-2 text-xs">
              <summary className="cursor-pointer text-ink2">
                Parent behaviour on development <Prov kind="HISTORICAL BACKTEST" />
              </summary>
              <div className="mt-2">
                <ParentBehaviourTable pb={dz.parent_behaviour} caption="Parent behaviour on development, per symbol" />
              </div>
            </details>
          )}
          {dz.sources && (
            <details className="rounded-md border border-line bg-panel p-2 text-xs">
              <summary className="cursor-pointer text-ink2">Source files ({Object.keys(dz.sources).length})</summary>
              <ul className="mt-1 space-y-0.5">
                {Object.entries(dz.sources).map(([f, h]) => (
                  <li key={f} className="flex flex-wrap gap-2">
                    <code className="text-ink2">{f}</code> <Hash v={h} n={16} />
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}

/* ---------------------------------------------------------------- LLM motivation */

export function externalHypothesis(ext: External | undefined): ExternalHypothesis | null {
  const h = ext?.hypothesis;
  return h && typeof h === "object" ? h : null;
}

export function hasMotivation(h: ExternalHypothesis | null): boolean {
  return !!h && (h.motivated_by !== undefined || !!h.new_information || !!h.current_behavior || !!h.refutation_observation);
}

export function MotivationSection({ ext }: { ext: External }) {
  const h = externalHypothesis(ext)!;
  const call = ext.llm_call;
  return (
    <section aria-labelledby="mot-h" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="mot-h" className="text-sm font-semibold">
          Motivation
        </h3>
        <Prov kind="HYPOTHESIS" />
        {ext.generator && <span className="text-[11px] text-muted">{ext.generator}</span>}
      </div>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field k="Motivated by (earlier tasks)">
          {h.motivated_by?.length ? (
            <ul className="flex flex-wrap gap-1">
              {h.motivated_by.map((m) => (
                <li key={m}>
                  <code className="rounded border border-line bg-panel2 px-1 text-[11px]">{m}</code>
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-muted">none listed</span>
          )}
        </Field>
        <Field k="Current behaviour (as described)">{h.current_behavior ?? "—"}</Field>
        <Field k="New information">{h.new_information ?? "—"}</Field>
        <Field k="Refutation observation">{h.refutation_observation ?? "—"}</Field>
        {h.change && <Field k="Change">{h.change}</Field>}
        {h.mechanism_effect && <Field k="Expected mechanism effect">{h.mechanism_effect}</Field>}
        {!!ext.exposure?.length && <Field k="Generator was shown">{ext.exposure.join(" · ")}</Field>}
        {call && (
          <Field k="LLM call">
            {fmtAny(call.tokens)} tokens · {fmtAny(call.wall_s)} s{call.models?.length ? ` · ${call.models.join(", ")}` : ""}
            {isNum(call.cost_usd_equiv) && (
              <>
                {" "}
                · ${num(call.cost_usd_equiv, 4)} <span className="text-muted">(API-equivalent estimate, not billing)</span>
              </>
            )}
          </Field>
        )}
      </dl>
      {ext.provenance && <p className="text-[11px] text-muted">{ext.provenance}</p>}
    </section>
  );
}
