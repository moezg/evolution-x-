"use client";
import { useEffect, useState, type ReactNode } from "react";
import { EmptyState, ErrorNote, Panel } from "./ui";
import { ClassBar, ClassChip, ClassLegend, Hash, PremiseChip, Prov, RateBar, Verdict } from "./research";
import { EngineFeatureTable, ParentBehaviourTable, PremiseTable, relPct } from "./researchEvidence";
import { usePoll } from "@/lib/hooks";
import { fmtAny, fmtTime, num } from "@/lib/format";
import type { Comparison, ComparisonArm, Exposure, Lessons, PremiseAudit, RateCI } from "@/lib/research";

/* Research-method comparison (generator arms), memory lessons, premise audit and evaluation independence.
   All numbers are read from /api/research/{comparisons,lessons,premise-audit,exposure}. */

function H3({ children }: { children: ReactNode }) {
  return <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">{children}</h3>;
}

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Static description of the pre-registered arms (protocol generator-comparison-v1). */
const ARM_DESC: Record<string, string> = {
  A: "offline grammar",
  B: "LLM + verified dossier",
  C: "LLM + dossier + memory",
};
const ARM_COLOR: Record<string, string> = { A: "#898781", B: "#3987e5", C: "#9085e9" };

const RATES: [keyof ComparisonArm, string][] = [
  ["premise_correct_rate", "Premises correct"],
  ["executable_rate", "Executable"],
  ["duplicate_rate", "Exact duplicate"],
  ["behavioural_duplicate_rate", "Behavioural duplicate"],
  ["mechanism_observed_rate", "Mechanism observed"],
  ["unstable_share", "Unstable across periods"],
];

function Bool({ v, yes = "yes", no = "no" }: { v: boolean | null | undefined; yes?: string; no?: string }) {
  if (v === null || v === undefined) return <span className="text-muted">—</span>;
  return <span className={v ? "text-ink" : "text-ink2"}>{v ? `✓ ${yes}` : `✗ ${no}`}</span>;
}

/* ================================================================ comparison */

function ArmCard({ id, a }: { id: string; a: ComparisonArm }) {
  const c = a.cost ?? {};
  const col = ARM_COLOR[id] ?? "#3987e5";
  return (
    <article className="min-w-0 space-y-3 rounded-md border border-line bg-panel2 p-3 text-xs" style={{ borderTopColor: col, borderTopWidth: 3 }}>
      <header className="space-y-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <b className="text-sm">Arm {id}</b>
          <span className="text-ink2">{ARM_DESC[id] ?? "—"}</span>
          <Verdict v={a.status} />
        </div>
        <div className="text-muted">
          lab <code>{a.lab}</code> · campaign <code>{a.campaign}</code> · {fmtAny(a.tasks)} tasks · confirmed <b className="tnum text-ink">{fmtAny(a.confirmed)}</b>
        </div>
      </header>
      <div className="space-y-2">
        {RATES.map(([k, label]) => (
          <RateBar key={k} label={label} r={a[k] as RateCI | undefined} color={col} />
        ))}
      </div>
      <div>
        <H3>Outcome classes</H3>
        <ClassBar classes={a.classes ?? {}} label={`Arm ${id} outcome classes`} total={a.tasks} />
        <ul className="mt-1 flex flex-wrap gap-1">
          {Object.entries(a.classes ?? {}).map(([k, v]) => (
            <li key={k} className="flex items-center gap-1">
              <ClassChip c={k} /> <span className="tnum text-ink2">{v}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <H3>Cost</H3>
        <dl className="grid grid-cols-1 gap-x-4 gap-y-0.5 sm:grid-cols-2">
          {[
            ["Wall clock", isNum(c.wall_s) ? `${num(c.wall_s, 1)} s` : "—"],
            ["Sandbox runs", fmtAny(c.sandbox_runs)],
            ["LLM calls", fmtAny(c.llm_calls)],
            ["LLM tokens", fmtAny(c.llm_tokens)],
            ["LLM USD*", isNum(c.llm_cost_usd_api_equivalent_estimate) ? `$${num(c.llm_cost_usd_api_equivalent_estimate, 4)}` : "—"],
            ["Wall / informative task", isNum(c.per_informative?.wall_s) ? `${num(c.per_informative!.wall_s, 1)} s` : "—"],
            ["LLM USD* / informative", isNum(c.per_informative?.llm_usd_api_equivalent) ? `$${num(c.per_informative!.llm_usd_api_equivalent, 4)}` : "—"],
          ].map(([k, v]) => (
            <div key={k} className="flex min-w-0 justify-between gap-2 border-b border-line py-0.5">
              <dt className="truncate text-muted">{k}</dt>
              <dd className="tnum">{v}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-1 text-[11px] text-muted">* API-equivalent estimate, not billing.{c.billing_note ? ` ${c.billing_note}.` : ""}</p>
      </div>
    </article>
  );
}

export function ComparisonPanel({ onOpenTask }: { onOpenTask?: (lab: string, task: string) => void }) {
  const list = usePoll<Comparison[]>("/api/research/comparisons", 30000);
  const tags = (list.data ?? []).map((c) => c.tag);
  const [tag, setTag] = useState<string>("");
  useEffect(() => {
    if (!tag && tags.length) setTag(tags[tags.length - 1]);
  }, [tag, tags]);
  const det = usePoll<Comparison>(tag ? `/api/research/comparisons/${encodeURIComponent(tag)}` : null, 30000);
  const c = det.data && det.data.tag === tag ? det.data : undefined;
  const arms = c ? Object.keys(c.arms).sort() : [];
  const ns = Array.from(new Set(arms.map((k) => c!.arms[k].tasks)));
  const nTxt = ns.length === 1 ? `n=${ns[0]} per arm` : `n=${arms.map((k) => `${k}:${c!.arms[k].tasks}`).join(", ")}`;
  const allClasses = Array.from(new Set(arms.flatMap((k) => Object.keys(c!.arms[k].classes ?? {}))));
  return (
    <Panel
      id="comparison"
      title="Research-method comparison"
      subtitle="Same parent, same budget, same trusted evaluator; only the candidate generator differs between arms."
      actions={
        <>
          <Prov kind="PILOT" />
          <Prov kind="HISTORICAL BACKTEST" />
          {tags.length > 1 && (
            <select className="input w-auto" value={tag} onChange={(e) => setTag(e.target.value)} aria-label="Comparison tag">
              {tags.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          )}
        </>
      }
    >
      <ErrorNote error={list.error} what="comparisons" />
      <ErrorNote error={det.error} what={`comparison ${tag}`} />
      {list.data && !list.data.length && <EmptyState title="No generator comparison recorded yet" />}
      {c && (
        <div className="space-y-4">
          <p role="note" className="rounded-md border-2 border-warn bg-warn/10 px-3 py-2 text-sm font-semibold text-warn">
            PILOT ({nTxt}): mechanism/cost check, no inferential claim.
            <span className="block text-xs font-normal text-ink2">API label: “{c.label}”. Intervals are Wilson 95% on k/n; at this n they overlap almost entirely.</span>
          </p>
          <p className="text-[11px] text-muted">
            tag <b className="text-ink2">{c.tag}</b> · {fmtTime(c.created_utc)} · protocol {c.protocol} <Hash v={c.protocol_sha256} />
          </p>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            {arms.map((k) => (
              <ArmCard key={k} id={k} a={c.arms[k]} />
            ))}
          </div>
          {allClasses.length > 0 && <ClassLegend classes={allClasses} />}
          <section aria-labelledby="cmp-rows-h">
            <h3 id="cmp-rows-h" className="mb-1 text-sm font-semibold">
              Per task
            </h3>
            <div className="relative max-h-[520px] overflow-auto">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Arm</th>
                    <th scope="col">Task</th>
                    <th scope="col">Premises</th>
                    <th scope="col">Executable</th>
                    <th scope="col">Exact duplicate</th>
                    <th scope="col">Behavioural duplicate of</th>
                    <th scope="col">Mechanism</th>
                    <th scope="col">Class</th>
                    <th scope="col">Verdict</th>
                    <th scope="col">Motivated by</th>
                    <th scope="col">Change</th>
                  </tr>
                </thead>
                <tbody>
                  {arms.flatMap((k) =>
                    (c.arms[k].rows ?? []).map((r) => (
                      <tr key={`${k}-${r.task}`}>
                        <td>
                          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: ARM_COLOR[k] }} aria-hidden /> {k}
                        </td>
                        <td>
                          {onOpenTask ? (
                            <button className="font-mono text-accent hover:underline" onClick={() => onOpenTask(c.arms[k].lab, r.task)} aria-label={`Open task ${r.task} in lab ${c.arms[k].lab}`}>
                              {r.task}
                            </button>
                          ) : (
                            <code>{r.task}</code>
                          )}
                        </td>
                        <td>
                          <PremiseChip v={r.premise_verdict} />
                          {r.premise_counts && (
                            <span className="ml-1 text-[10px] text-muted tnum">
                              {r.premise_counts.verified}✓ {r.premise_counts.falsified}✗ {r.premise_counts.unverifiable}?
                            </span>
                          )}
                        </td>
                        <td className="text-[11px]">
                          <Bool v={r.executable} />
                        </td>
                        <td className="text-[11px]">
                          {r.duplicate ? <span title={r.duplicate_of ?? undefined}>✓ {r.duplicate_of ? <code className="text-ink2">{r.duplicate_of}</code> : "yes"}</span> : <Bool v={r.duplicate} />}
                        </td>
                        <td className="text-[11px]">{r.behavioural_duplicate_of ? <code className="text-ink2">{r.behavioural_duplicate_of}</code> : <span className="text-muted">—</span>}</td>
                        <td className="text-[11px]">
                          {r.mechanism_observed === true ? <span className="text-up">✓ observed</span> : r.mechanism_observed === false ? <span className="text-down">✗ not observed</span> : <span className="text-muted">—</span>}
                        </td>
                        <td>
                          <ClassChip c={r.class} />
                        </td>
                        <td>
                          <Verdict v={r.verdict} />
                        </td>
                        <td className="text-[11px]" title={r.motivated_by?.join("\n")}>
                          {r.motivated_by == null ? <span className="text-muted">n/a</span> : r.motivated_by.length ? `${r.motivated_by.length} tasks` : <span className="text-muted">none</span>}
                        </td>
                        <td className="!whitespace-normal text-[11px] text-ink2">
                          <span className="line-clamp-2 min-w-[220px] max-w-[420px]" title={r.change ?? undefined}>
                            {r.change ?? "—"}
                          </span>
                        </td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </Panel>
  );
}

/* ================================================================ lessons */

export function LessonsPanel() {
  const p = usePoll<Lessons>("/api/research/lessons", 30000);
  const l = p.data;
  const ops = Object.entries(l?.summary_by_change_type ?? {}).sort((a, b) => b[1].n - a[1].n);
  const labs = Object.entries(l?.classes_by_lab ?? {});
  const allClasses = Array.from(new Set([...ops.flatMap(([, v]) => Object.keys(v.classes)), ...labs.flatMap(([, v]) => Object.keys(v))]));
  return (
    <Panel
      id="lessons"
      title="Memory: lessons"
      subtitle="What earlier tasks taught, aggregated by type of change. This is the memory arm C reads."
      actions={<Prov kind="HISTORICAL BACKTEST" />}
    >
      <ErrorNote error={p.error} what="lessons" />
      {l && (
        <div className="space-y-4">
          {l.note && <p className="rounded-md border border-warn/40 bg-warn/5 px-3 py-1.5 text-[11px] text-warn">Note (API): {l.note}</p>}
          <div className="relative overflow-x-auto">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Change type</th>
                  <th scope="col" className="num">n</th>
                  <th scope="col" className="num" title="tasks that declared a mechanism test">Mech. declared</th>
                  <th scope="col" className="num">Mech. observed</th>
                  <th scope="col">Mechanism metric</th>
                  <th scope="col" className="num" title="median relative change of the mechanism metric, candidate vs parent, development">Median rel. change</th>
                  <th scope="col" className="min-w-[180px]">Classes</th>
                </tr>
              </thead>
              <tbody>
                {ops.map(([op, v]) => (
                  <tr key={op}>
                    <td className="font-mono text-[11px]">{op}</td>
                    <td className="num">{v.n}</td>
                    <td className="num">{v.mechanism_declared}</td>
                    <td className="num">
                      {v.mechanism_declared ? `${v.mechanism_observed}/${v.mechanism_declared}` : <span className="text-muted" title={`API value ${v.mechanism_observed}`}>{fmtAny(v.mechanism_observed)}</span>}
                    </td>
                    <td className="text-[11px] text-ink2">{v.metric ?? "—"}</td>
                    <td className="num">{relPct(v.median_relative_change_of_mechanism_metric)}</td>
                    <td className="min-w-[180px]">
                      <ClassBar classes={v.classes} label={`${op} classes`} total={v.n} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <section aria-labelledby="cbl-h" className="space-y-1.5">
            <h3 id="cbl-h" className="text-sm font-semibold">
              Classes by lab
            </h3>
            <ul className="space-y-1.5">
              {labs.map(([lab, cl]) => {
                const n = Object.values(cl).reduce((a, b) => a + b, 0);
                return (
                  <li key={lab} className="grid grid-cols-[minmax(0,110px)_minmax(0,1fr)_32px] items-center gap-2 text-xs sm:grid-cols-[160px_minmax(0,1fr)_40px]">
                    <code className="truncate text-ink2" title={lab}>
                      {lab}
                    </code>
                    <ClassBar classes={cl} label={`${lab} classes`} />
                    <span className="text-right tnum text-muted">{n}</span>
                  </li>
                );
              })}
            </ul>
            <ClassLegend classes={allClasses} />
          </section>
        </div>
      )}
    </Panel>
  );
}

/* ================================================================ premise audit */

export function PremiseAuditPanel() {
  const p = usePoll<PremiseAudit>("/api/research/premise-audit", 0);
  const a = p.data;
  return (
    <Panel
      id="premise-audit"
      title="Premise audit of the earlier claude -p candidate (cli-2)"
      subtitle="Its stated premises, re-checked after the fact with the same verifier now applied before every backtest."
      actions={<Prov kind="HISTORICAL BACKTEST" />}
    >
      {p.error && (p.error as { status?: number }).status === 404 ? <EmptyState title="No premise audit recorded" /> : <ErrorNote error={p.error} what="premise audit" />}
      {a && (
        <div className="space-y-3">
          <dl className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
            <div>
              <dt className="text-[11px] uppercase tracking-wider text-muted">Subject</dt>
              <dd className="break-words">{a.subject}</dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wider text-muted">Parent</dt>
              <dd className="break-words font-mono text-[11px]">{a.parent}</dd>
            </div>
          </dl>
          <PremiseTable pc={a.verification} caption="Premise audit results for the cli-2 candidate" />
          {a.features && (
            <details className="rounded-md border border-line bg-panel2 p-2 text-xs">
              <summary className="cursor-pointer text-ink2">Engine features probed ({Object.keys(a.features).length})</summary>
              <div className="mt-2">
                <EngineFeatureTable features={a.features} caption="Engine features probed for the premise audit" />
              </div>
            </details>
          )}
          {a.parent_behaviour_development && (
            <details className="rounded-md border border-line bg-panel2 p-2 text-xs">
              <summary className="cursor-pointer text-ink2">Parent behaviour on development</summary>
              <div className="mt-2">
                <ParentBehaviourTable pb={a.parent_behaviour_development} caption="Parent behaviour on development used by the premise audit" />
              </div>
            </details>
          )}
        </div>
      )}
    </Panel>
  );
}

/* ================================================================ exposure */

function datasetKind(status: string): { label: string; cls: string } {
  const s = status.toLowerCase();
  if (s.startsWith("consumed")) return { label: "CONSUMED", cls: "border-down/60 bg-down/15 text-[#f3a7a7]" };
  if (s.startsWith("reserved")) return { label: "RESERVED", cls: "border-up/60 bg-up/10 text-up" };
  if (s.includes("reused")) return { label: "REUSED", cls: "border-warn/60 bg-warn/10 text-warn" };
  if (s.includes("free")) return { label: "FREE", cls: "border-line2 bg-panel2 text-ink2" };
  return { label: "USED", cls: "border-line2 bg-panel2 text-ink2" };
}

function Chips({ items, tone }: { items?: string[]; tone: "saw" | "never" }) {
  if (!items?.length) return <span className="text-muted">—</span>;
  return (
    <ul className="flex flex-wrap gap-1">
      {items.map((x) => (
        <li
          key={x}
          className={`rounded border px-1.5 py-px text-[11px] ${tone === "saw" ? "border-warn/50 bg-warn/5 text-ink" : "border-up/50 bg-up/5 text-ink2"}`}
        >
          {tone === "saw" ? "👁 " : "∅ "}
          {x}
        </li>
      ))}
    </ul>
  );
}

export function ExposurePanel() {
  const p = usePoll<Exposure>("/api/research/exposure", 30000);
  const e = p.data;
  const vm = e?.vault_v2_manifest;
  const v2 = Object.entries(e?.datasets ?? {}).find(([k]) => k.startsWith("vault_v2"));
  return (
    <Panel id="exposure" title="Evaluation independence" subtitle="Which data each actor has seen. Data an actor has seen cannot independently confirm that actor's proposals.">
      <ErrorNote error={p.error} what="exposure registry" />
      {e && (
        <div className="space-y-4">
          <blockquote className="border-l-2 border-accent pl-3 text-xs text-ink">
            {e.principle}
            {(e.name || e.written_utc) && (
              <footer className="mt-0.5 text-[11px] text-muted">
                {e.name} · {fmtTime(e.written_utc)}
              </footer>
            )}
          </blockquote>
          <section aria-labelledby="ds-h">
            <h3 id="ds-h" className="mb-1 text-sm font-semibold">
              Datasets
            </h3>
            <ul className="space-y-1.5">
              {Object.entries(e.datasets).map(([name, d]) => {
                const k = datasetKind(d.status);
                const extra = Object.entries(d).filter(([kk]) => kk !== "status");
                return (
                  <li key={name} className="rounded-md border border-line bg-panel2 p-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded border px-1.5 py-px text-[10px] font-bold tracking-wider ${k.cls}`}>{k.label}</span>
                      <b className="break-words">{name}</b>
                    </div>
                    <p className="mt-1 break-words text-ink2">{d.status}</p>
                    {extra.map(([kk, vv]) => (
                      <p key={kk} className="mt-0.5 break-words text-[11px] text-muted">
                        <span className="uppercase tracking-wider">{kk}:</span> <span className="text-ink2">{typeof vv === "string" ? vv : JSON.stringify(vv)}</span>
                      </p>
                    ))}
                  </li>
                );
              })}
            </ul>
          </section>
          <section aria-labelledby="act-h">
            <h3 id="act-h" className="mb-1 text-sm font-semibold">
              Who saw what
            </h3>
            <div className="relative overflow-x-auto">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Actor</th>
                    <th scope="col">Saw</th>
                    <th scope="col">Never saw</th>
                    <th scope="col">Consequence / role</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(e.actors).map(([name, a]) => (
                    <tr key={name}>
                      <td className="min-w-[140px] !whitespace-normal font-semibold">{name}</td>
                      <td className="min-w-[200px] !whitespace-normal">
                        <Chips items={a.saw} tone="saw" />
                      </td>
                      <td className="min-w-[200px] !whitespace-normal">
                        <Chips items={a.never} tone="never" />
                      </td>
                      <td className="min-w-[160px] !whitespace-normal text-[11px]">
                        {a.consequence && <span className="font-semibold text-warn">{a.consequence}</span>}
                        {a.role && <span className="text-ink2">{a.role}</span>}
                        {!a.consequence && !a.role && <span className="text-muted">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          {e.next_confirmation && (
            <p className="rounded-md border border-accent/50 bg-accent/10 px-3 py-2 text-xs text-ink">
              <b>Next confirmation: </b>
              {e.next_confirmation}
            </p>
          )}
          {vm && (
            <section aria-labelledby="v2-h" className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <h3 id="v2-h" className="text-sm font-semibold">
                  Vault v2 manifest
                </h3>
                {v2 && (
                  <span className={`rounded border px-1.5 py-px text-[10px] font-bold tracking-wider ${datasetKind(v2[1].status).cls}`} title={`${v2[0]}: ${v2[1].status}`}>
                    {v2[1].status}
                  </span>
                )}
              </div>
              {vm.spec && (
                <p className="break-words text-[11px] text-ink2">
                  {vm.spec.instruments?.join(", ")} · {vm.spec.start} → {vm.spec.end_exclusive} (excl.) · chosen {fmtTime(vm.spec.chosen_utc)} · rule: {vm.spec.selection_rule}
                  {vm.built_utc ? ` · built ${fmtTime(vm.built_utc)}` : ""}
                </p>
              )}
              <div className="relative overflow-x-auto">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Instrument</th>
                      <th scope="col" className="num">Bars</th>
                      <th scope="col" className="num">Gaps</th>
                      <th scope="col" className="num">Missing h</th>
                      <th scope="col">Checksums</th>
                      <th scope="col">sha256</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(vm.instruments ?? {}).map(([sym, it]) => (
                      <tr key={sym}>
                        <td>{sym}</td>
                        <td className="num">{fmtAny(it.bars)}</td>
                        <td className="num">{fmtAny(it.qc?.gaps)}</td>
                        <td className="num">{fmtAny(it.qc?.missing_hours)}</td>
                        <td className={it.checksums_verified ? "text-up" : "text-down"}>{it.checksums_verified ? "✓ verified" : "✗ not verified"}</td>
                        <td>
                          <Hash v={it.sha256} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-[11px] text-muted">Only quality-control counts are shown; no returns or prices from vault v2.</p>
            </section>
          )}
        </div>
      )}
    </Panel>
  );
}
