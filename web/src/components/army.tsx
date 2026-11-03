"use client";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { EmptyState, ErrorNote, JsonTable, Kpi, Panel } from "@/components/ui";
import { Kv, TableWrap, TONE_CLS } from "@/components/observatory";
import { Hash } from "@/components/research";
import { ApiError } from "@/lib/api";
import { fmtAny, fmtTime, num, usd } from "@/lib/format";
import type { Poll } from "@/lib/hooks";
import {
  IMPL_EXPLAIN,
  STAGES,
  armyTone,
  arr,
  numv,
  obj,
  shortTask,
  stageIndex,
  str,
  type ArmyCycle,
  type ArmyForecast,
  type ArmyRole,
  type ArmySource,
  type ArmyTask,
  type ControlIn,
  type ControlResp,
  type CycleResp,
  type Edge,
  type Hypothesis,
  type JournalResp,
  type Json,
  type LineageResp,
  type LineageStep,
  type MemoryResp,
  type Proposal,
  type RolesResp,
} from "@/lib/army";
import type { ProspectiveResp } from "@/lib/forecast";

/* ================================================================ primitives */

export function Badge({ s, label, title }: { s: string | null | undefined; label?: string; title?: string }) {
  if (!s) return <span className="text-[11px] text-muted">—</span>;
  return (
    <span
      title={title}
      className={`inline-block max-w-full rounded-full border px-2 py-0.5 text-[11px] font-semibold [overflow-wrap:anywhere] ${TONE_CLS[armyTone(s)]}`}
    >
      {label && <span className="mr-1 font-normal opacity-80">{label}:</span>}
      {s.replace(/_/g, " ")}
    </span>
  );
}

function YesNo({ v, goodWhen = true, yes = "yes", no = "no" }: { v: unknown; goodWhen?: boolean; yes?: string; no?: string }) {
  if (typeof v !== "boolean") return <span className="text-muted">—</span>;
  const good = v === goodWhen;
  return <span className={`font-semibold ${good ? "text-up" : "text-[#f3a7a7]"}`}>{v ? yes : no}</span>;
}

/** Loading / error wrapper. */
export function AState<T>({ poll, what, children }: { poll: Poll<T>; what: string; children: (d: T) => ReactNode }) {
  if (poll.data) return <>{children(poll.data)}</>;
  if (poll.error instanceof ApiError && poll.error.status === 404)
    return (
      <EmptyState title={`${what}: not found`}>
        <p>{poll.error.detail}</p>
      </EmptyState>
    );
  if (poll.error) return <ErrorNote error={poll.error} what={what} />;
  return <p className="text-xs text-muted">Loading {what}…</p>;
}

function Num({ v, d = 3 }: { v: unknown; d?: number }) {
  const n = numv(v);
  return <span className="tnum">{n === undefined ? "—" : num(n, d)}</span>;
}

/** Plain-text rendering of untrusted retrieved content. React escapes it; no HTML is ever interpreted. */
function Untrusted({ text, label = "Untrusted retrieved content (shown as plain text)" }: { text: string | null | undefined; label?: string }) {
  if (!text) return <span className="text-muted">—</span>;
  return (
    <div className="rounded border border-dashed border-warn/50 bg-warn/5 p-2">
      <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-warn">{label}</div>
      <p className="whitespace-pre-wrap break-words text-xs text-ink2 [overflow-wrap:anywhere]">{text}</p>
    </div>
  );
}

function Sub({ children }: { children: ReactNode }) {
  return <h3 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wider text-ink2 first:mt-0">{children}</h3>;
}

function List({ items, empty = "none" }: { items: unknown[]; empty?: string }) {
  if (!items.length) return <span className="text-muted">{empty}</span>;
  return (
    <ul className="list-disc space-y-0.5 pl-4">
      {items.map((x, i) => (
        <li key={i} className="break-words [overflow-wrap:anywhere]">
          {typeof x === "string" ? x : JSON.stringify(x)}
        </li>
      ))}
    </ul>
  );
}

/* ================================================================ policy banner */

export function PolicyBanner({ roles }: { roles?: RolesResp }) {
  return (
    <section aria-label="Safety and promotion policy" className="grid grid-cols-1 gap-2 text-xs md:grid-cols-3">
      <div className="rounded-md border border-down/50 bg-down/10 p-3">
        <p className="font-bold uppercase tracking-wider text-[#f3a7a7]">No trading · no execution</p>
        <p className="mt-1 text-ink2">
          The research army has no order path. No endpoint can place an order, change a frozen policy, merge code or alter a recorded result. Candidates are evaluated only in
          backtests, an adversarial battery and paper forecasts.
        </p>
      </div>
      <div className="rounded-md border border-accent/50 bg-accent/10 p-3">
        <p className="font-bold uppercase tracking-wider text-[#9ec5f4]">Promotion is deterministic policy code</p>
        <p className="mt-1 text-ink2">
          Status is computed by <code>army/policy.py</code> from the frozen policy. No LLM output is consulted; the Evolution Coordinator (F4) only recommends. Passing selection makes
          a candidate a <em>prospective challenger</em>, not validated.
        </p>
      </div>
      <div className="rounded-md border border-warn/50 bg-warn/10 p-3">
        <p className="font-bold uppercase tracking-wider text-warn">&ldquo;Validated&rdquo; needs prospective evidence + a human</p>
        <p className="mt-1 text-ink2">
          Validation requires resolved prospective paper evidence (the only confirmatory evidence) with a confidence interval above zero <strong>and</strong> explicit human approval.
          {roles && (
            <>
              {" "}
              The 24 research roles are separate from the simulator&rsquo;s market participants ({roles.simulated_market_participants}).
            </>
          )}
        </p>
      </div>
    </section>
  );
}

/* ================================================================ 1 · agent command center */

function UsageLine({ u }: { u: ArmyRole["usage"] }) {
  return (
    <dl className="grid grid-cols-4 gap-1 text-[11px]">
      {(
        [
          ["LLM calls", fmtAny(u.llm_calls)],
          ["API-eq. USD", usd(u.llm_cost_usd, 3)],
          ["wall s", num(u.wall_s, 1)],
          ["ext. req.", fmtAny(u.ext_requests)],
        ] as const
      ).map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="truncate text-muted">{k}</dt>
          <dd className="tnum text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function RoleCard({ r }: { r: ArmyRole }) {
  const counts = Object.entries(r.tasks);
  const blocked = r.blockers.filter((b) => b.waiting_for.length > 0);
  return (
    <article className={`min-w-0 rounded-md border bg-panel2 p-2.5 text-xs ${r.activity !== "idle" ? "border-accent/70" : "border-line"}`} aria-label={`${r.id} ${r.title}`}>
      <header className="flex flex-wrap items-start justify-between gap-1">
        <h4 className="min-w-0 font-semibold text-ink">
          <span className="mr-1 font-mono text-accent">{r.id}</span>
          {r.title}
        </h4>
        <span
          className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-bold tracking-wider ${
            r.impl === "llm_optional" ? TONE_CLS.weak : r.impl === "delegates" ? TONE_CLS.info : TONE_CLS.neutral
          }`}
          title={IMPL_EXPLAIN[r.impl] ?? r.impl}
        >
          {r.impl.replace(/_/g, " ")}
        </span>
      </header>
      <p className="mt-1 text-ink2">{r.capability}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <span className="text-muted">stage</span> <code className="text-[11px]">{r.stage}</code>
        <span className="text-muted">· now</span> <Badge s={r.activity} />
        {r.last_task && (
          <>
            <span className="text-muted">· last</span> <code className="text-[11px]">{r.last_task}</code>
          </>
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {counts.length ? counts.map(([s, n]) => <Badge key={s} s={s} label={String(n)} />) : <span className="text-muted">no tasks in this cycle</span>}
      </div>
      {blocked.length > 0 && (
        <div className="mt-1.5 rounded border border-warn/40 bg-warn/5 p-1.5">
          <p className="font-semibold text-warn">Blocked</p>
          {blocked.map((b) => (
            <p key={b.task} className="break-all font-mono text-[11px] text-ink2">
              {shortTask(b.task)} ← {b.waiting_for.map(shortTask).join(", ")}
            </p>
          ))}
        </div>
      )}
      {r.errors.length > 0 && (
        <div className="mt-1.5 rounded border border-down/40 bg-down/5 p-1.5">
          <p className="font-semibold text-[#f3a7a7]">Errors</p>
          {r.errors.map((e, i) => (
            <p key={i} className="whitespace-pre-wrap break-all font-mono text-[11px] text-ink2">
              {e}
            </p>
          ))}
        </div>
      )}
      <div className="mt-2 border-t border-line pt-1.5">
        <UsageLine u={r.usage} />
      </div>
    </article>
  );
}

export function CommandCenter({ roles }: { roles: Poll<RolesResp> }) {
  return (
    <Panel
      id="agents"
      title="Agent Command Center · 24 research roles"
      subtitle="6 divisions × 4 logical roles. Roles are activated per task and never run permanently. Activity, task counts and usage refer to the latest cycle."
    >
      <AState poll={roles} what="army roles">
        {(d) => {
          const divisions = Array.from(new Set(d.roles.map((r) => r.division)));
          const tot = d.roles.reduce(
            (a, r) => ({
              llm: a.llm + (r.usage.llm_calls || 0),
              usd: a.usd + (r.usage.llm_cost_usd || 0),
              wall: a.wall + (r.usage.wall_s || 0),
              ext: a.ext + (r.usage.ext_requests || 0),
              active: a.active + (r.activity !== "idle" ? 1 : 0),
              blocked: a.blocked + r.blockers.filter((b) => b.waiting_for.length).length,
              errors: a.errors + r.errors.length,
            }),
            { llm: 0, usd: 0, wall: 0, ext: 0, active: 0, blocked: 0, errors: 0 },
          );
          return (
            <>
              <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
                <Kpi label="Latest cycle" value={<span className="text-sm">{d.cycle ?? "—"}</span>} />
                <Kpi label="Roles running" value={`${tot.active} / ${d.roles.length}`} />
                <Kpi label="Blocked tasks" value={tot.blocked} tone={tot.blocked ? "warn" : undefined} />
                <Kpi label="Task errors" value={tot.errors} tone={tot.errors ? "down" : undefined} />
                <Kpi label="LLM calls" value={tot.llm} />
                <Kpi label="API-equivalent USD" value={usd(tot.usd, 3)} sub="CLI estimate, not billing" />
                <Kpi label="External requests" value={tot.ext} sub={`${num(tot.wall, 1)} s wall`} />
              </div>
              <dl className="mb-3 grid grid-cols-1 gap-2 text-xs md:grid-cols-3">
                {Object.entries(IMPL_EXPLAIN).map(([k, v]) => (
                  <div key={k} className="rounded border border-line bg-panel2 p-2">
                    <dt className="font-semibold text-ink">
                      {k.replace(/_/g, " ")} <span className="font-normal text-muted">· {d.roles.filter((r) => r.impl === k).length} roles</span>
                    </dt>
                    <dd className="text-ink2">{v}</dd>
                  </div>
                ))}
              </dl>
              <div className="space-y-3">
                {divisions.map((div) => (
                  <section key={div} aria-label={div}>
                    <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-ink2">{div}</h3>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
                      {d.roles
                        .filter((r) => r.division === div)
                        .map((r) => (
                          <RoleCard key={r.id} r={r} />
                        ))}
                    </div>
                  </section>
                ))}
              </div>
            </>
          );
        }}
      </AState>
    </Panel>
  );
}

/* ---------------------------------------------------------------- cycles + task DAG */

function CycleButton({ c, active, onClick }: { c: ArmyCycle; active: boolean; onClick: () => void }) {
  const counts = c.summary?.counts ?? {};
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`min-w-0 rounded-md border p-2 text-left text-xs ${active ? "border-accent bg-accent/15" : "border-line bg-panel2 hover:bg-[#262624]"}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-1">
        <code className="break-all text-[11px] text-ink">{c.id}</code>
        <Badge s={c.status} />
      </div>
      <div className="mt-1 text-muted">{fmtTime(c.created)}</div>
      <div className="mt-1 flex flex-wrap gap-1">
        {Object.entries(counts).map(([s, n]) => (
          <Badge key={s} s={s} label={String(n)} />
        ))}
        <span className="text-ink2">· {c.summary?.wall_s !== undefined ? `${num(c.summary.wall_s, 1)} s` : "running…"}</span>
      </div>
    </button>
  );
}

function TaskRow({ t, open, toggle }: { t: ArmyTask; open: boolean; toggle: () => void }) {
  const deps = t.deps?.deps ?? [];
  return (
    <>
      <tr className={t.status === "running" ? "bg-accent/10" : undefined}>
        <td>
          <button type="button" className="btn btn-sm" aria-expanded={open} onClick={toggle} aria-label={`Details for ${t.id}`}>
            {open ? "−" : "+"}
          </button>
        </td>
        <td className="font-mono text-[11px]">{t.role}</td>
        <td>{t.kind}</td>
        <td>
          <Badge s={t.status} />
        </td>
        <td className="num">
          {t.attempts}/{t.max_attempts}
        </td>
        <td className="!whitespace-normal font-mono text-[11px] text-ink2">
          {deps.length ? deps.map(shortTask).join(", ") : <span className="text-muted">—</span>}
          {t.deps?.barrier && <span className="ml-1 rounded border border-line2 px-1 text-[10px] text-muted">barrier</span>}
        </td>
        <td className="num">{num(t.wall_s ?? NaN, 2)}</td>
        <td className="num">{fmtAny(t.llm_calls)}</td>
        <td className="max-w-[24rem] !whitespace-normal break-all text-[11px] text-[#f3a7a7]">{t.error ?? ""}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={9} className="!whitespace-normal bg-page/60">
            <p className="mb-1 font-mono text-[11px] text-muted">{t.id}</p>
            <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold text-ink2">payload</p>
                <JsonTable value={t.payload} />
              </div>
              <div className="min-w-0">
                <p className="text-[11px] font-semibold text-ink2">result</p>
                <JsonTable value={t.result} />
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export function CyclesPanel({
  cycles,
  selected,
  setSelected,
  detail,
}: {
  cycles: Poll<ArmyCycle[]>;
  selected: string;
  setSelected: (id: string) => void;
  detail: Poll<CycleResp>;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  return (
    <Panel id="cycles" title="Research cycles · task DAG" subtitle="DISCOVER → VERIFY → UNDERSTAND → FORMULATE → IMPLEMENT → TEST → CHALLENGE → EVALUATE → ARCHIVE → REASSESS">
      <AState poll={cycles} what="cycles">
        {(cs) =>
          cs.length === 0 ? (
            <EmptyState title="No research cycle recorded yet">Use the Controls section to run one.</EmptyState>
          ) : (
            <div role="group" aria-label="Select cycle" className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {cs.map((c) => (
                <CycleButton key={c.id} c={c} active={c.id === selected} onClick={() => setSelected(c.id)} />
              ))}
            </div>
          )
        }
      </AState>
      {selected && (
        <div className="mt-3">
          <AState poll={detail} what={`cycle ${selected}`}>
            {(d) => {
              if (d.cycle.id !== selected) return <p className="text-xs text-muted">Loading cycle {selected}…</p>;
              const cfg = d.cycle.config ?? {};
              const stages = Array.from(new Set(d.tasks.map((t) => t.stage))).sort((a, b) => stageIndex(a) - stageIndex(b) || a.localeCompare(b));
              return (
                <>
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                    <Badge s={d.cycle.status} />
                    <span className="text-ink2">{d.tasks.length} tasks</span>
                    <span className="text-muted">· updated {fmtTime(d.cycle.updated)}</span>
                    {str(cfg.note) && <span className="text-ink2">· {str(cfg.note)}</span>}
                    {str(cfg.policy_sha256) && (
                      <span className="text-muted">
                        · policy <Hash v={str(cfg.policy_sha256)} />
                      </span>
                    )}
                  </div>
                  <details className="mb-2 text-xs">
                    <summary className="cursor-pointer text-ink2">Cycle configuration</summary>
                    <div className="mt-1">
                      <JsonTable value={cfg} />
                    </div>
                  </details>
                  <ol aria-label="Stage progress" className="mb-2 flex flex-wrap gap-1 text-[10px]">
                    {STAGES.map((s) => {
                      const ts = d.tasks.filter((t) => t.stage === s);
                      const st = ts.some((t) => t.status === "running")
                        ? "running"
                        : ts.some((t) => t.status === "failed")
                          ? "failed"
                          : ts.some((t) => t.status === "pending")
                            ? "pending"
                            : ts.length
                              ? "done"
                              : "";
                      return (
                        <li key={s} className={`rounded border px-1.5 py-0.5 font-semibold ${st ? TONE_CLS[armyTone(st)] : "border-line text-muted"}`} title={`${ts.length} tasks`}>
                          {s} <span className="font-normal">{ts.length}</span>
                        </li>
                      );
                    })}
                  </ol>
                  <TableWrap label="Cycle tasks grouped by stage">
                    <table className="data">
                      <thead>
                        <tr>
                          <th aria-label="Expand" />
                          <th>Role</th>
                          <th>Kind</th>
                          <th>Status</th>
                          <th className="num">Attempts</th>
                          <th>Deps</th>
                          <th className="num">Wall s</th>
                          <th className="num">LLM</th>
                          <th>Error</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stages.map((s) => (
                          <Fragment key={s}>
                            <tr>
                              <th colSpan={9} scope="colgroup" className="!static bg-panel2 !text-accent">
                                {s}
                              </th>
                            </tr>
                            {d.tasks
                              .filter((t) => t.stage === s)
                              .map((t) => (
                                <TaskRow key={t.id} t={t} open={!!open[t.id]} toggle={() => setOpen((o) => ({ ...o, [t.id]: !o[t.id] }))} />
                              ))}
                          </Fragment>
                        ))}
                      </tbody>
                    </table>
                  </TableWrap>
                  {d.usage.length > 0 && (
                    <details className="mt-2 text-xs">
                      <summary className="cursor-pointer text-ink2">Per-role usage in this cycle</summary>
                      <TableWrap label="Per-role usage">
                        <table className="data mt-1">
                          <thead>
                            <tr>
                              <th>Role</th>
                              <th className="num">LLM calls</th>
                              <th className="num">API-eq. USD</th>
                              <th className="num">Wall s</th>
                              <th className="num">Ext. requests</th>
                            </tr>
                          </thead>
                          <tbody>
                            {d.usage.map((u) => (
                              <tr key={u.role}>
                                <td className="font-mono">{u.role}</td>
                                <td className="num">{u.llm_calls}</td>
                                <td className="num">{usd(u.llm_cost_usd, 3)}</td>
                                <td className="num">{num(u.wall_s, 2)}</td>
                                <td className="num">{u.ext_requests}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </TableWrap>
                    </details>
                  )}
                </>
              );
            }}
          </AState>
        </div>
      )}
    </Panel>
  );
}

/* ================================================================ 2 · research discoveries */

function CrossrefCell({ v }: { v: ArmySource["verification"] }) {
  const c = v?.crossref;
  if (!c) return <span className="text-muted">—</span>;
  return (
    <span>
      <YesNo v={c.matched} yes="matched" no="no match" />
      {numv(c.similarity) !== undefined && <span className="text-muted"> · sim {num(c.similarity, 2)}</span>}
      {c.doi && (
        <>
          {" · "}
          <a className="text-accent hover:underline" href={`https://doi.org/${encodeURIComponent(c.doi).replace(/%2F/g, "/")}`} target="_blank" rel="noopener noreferrer nofollow">
            {c.doi}
          </a>
        </>
      )}
      {c.type && <span className="text-muted"> · {String(c.type)}</span>}
      {c.container && <span className="block text-muted">{String(c.container)}</span>}
    </span>
  );
}

function SourceCard({ s }: { s: ArmySource }) {
  const v = s.verification;
  const ev = v?.evidence;
  const highlight = s.status === "duplicate_mechanism" || s.status.startsWith("infeasible") || s.status === "formulated";
  const safeUrl = s.url && /^https?:\/\//.test(s.url) ? s.url : null;
  return (
    <article className={`min-w-0 rounded-md border bg-panel2 p-3 text-xs ${highlight ? (s.status === "formulated" ? "border-up/50" : s.status === "duplicate_mechanism" ? "border-warn/50" : "border-down/50") : "border-line"}`}>
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="break-words text-sm font-semibold text-ink [overflow-wrap:anywhere]">
            {safeUrl ? (
              <a href={safeUrl} target="_blank" rel="noopener noreferrer nofollow" className="hover:underline">
                {s.title ?? s.id}
              </a>
            ) : (
              (s.title ?? s.id)
            )}
          </h4>
          <p className="mt-0.5 text-ink2">{(s.authors ?? []).join(", ") || "—"}</p>
        </div>
        <div className="flex flex-wrap gap-1">
          <Badge s={s.status} />
          {s.mechanism?.family && <Badge s={s.mechanism.family} label="family" />}
        </div>
      </header>
      <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
        <div className="min-w-0">
          <dt className="text-muted">Provenance</dt>
          <dd className="break-all">
            <code className="text-[11px]">{s.id}</code> · {s.origin}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Published / updated / retrieved</dt>
          <dd className="tnum">
            {fmtTime(s.published).slice(0, 10)} / {fmtTime(s.updated).slice(0, 10)} / {fmtTime(s.retrieved)}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-muted">DOI / journal ref</dt>
          <dd className="break-all">
            {s.doi ?? "—"} / {s.journal_ref ?? "—"}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-muted">Query</dt>
          <dd className="break-all font-mono text-[11px] text-ink2">{s.query ?? "—"}</dd>
        </div>
        <div className="min-w-0 sm:col-span-2">
          <dt className="text-muted">Licence note</dt>
          <dd className="text-ink2">{s.license_note ?? "—"}</dd>
        </div>
      </dl>
      <div className="mt-2 rounded border border-line bg-panel p-2">
        <p className="mb-1 font-semibold text-ink2">Verification (A3)</p>
        {!v ? (
          <p className="text-muted">Not verified yet — discovered only (verification runs on a bounded selection per cycle).</p>
        ) : (
          <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-muted">Record re-fetched</dt>
              <dd>
                <YesNo v={v.record_refetched} />
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-muted">Crossref</dt>
              <dd className="break-words [overflow-wrap:anywhere]">
                <CrossrefCell v={v} />
              </dd>
            </div>
            <div>
              <dt className="text-muted">Evidence grade</dt>
              <dd>
                <span className={`rounded border px-1.5 font-bold ${ev?.grade === "A" || ev?.grade === "B" ? TONE_CLS.good : ev?.grade === "C" ? TONE_CLS.weak : TONE_CLS.bad}`}>
                  {ev?.grade ?? "—"}
                </span>{" "}
                <span className="text-muted">
                  {fmtAny(ev?.points)} pts · peer-reviewed <YesNo v={ev?.peer_reviewed} />
                </span>
              </dd>
            </div>
            <div>
              <dt className="text-muted">Marketing language</dt>
              <dd>
                <YesNo v={ev?.marketing_language} goodWhen={false} yes="flagged" no="not flagged" />
              </dd>
            </div>
            <div className="min-w-0 sm:col-span-2">
              <dt className="text-muted">Rubric flags</dt>
              <dd className="flex flex-wrap gap-1">
                {Object.entries(ev?.flags ?? {}).map(([k, b]) => (
                  <span key={k} className={`rounded border px-1.5 text-[10px] ${b ? TONE_CLS.good : TONE_CLS.neutral}`}>
                    {b ? "✓" : "✗"} {k.replace(/_/g, " ")}
                  </span>
                ))}
              </dd>
            </div>
            <div className="min-w-0 sm:col-span-2">
              <dt className="text-muted">Classification · claim</dt>
              <dd>
                <Badge s={v.classification} /> <span className="text-ink2">{v.claim_status}</span>
              </dd>
            </div>
            {ev?.note && <p className="text-[11px] text-muted sm:col-span-2 lg:col-span-4">{ev.note}</p>}
          </dl>
        )}
      </div>
      {s.mechanism?.scores && (
        <p className="mt-1.5 text-[11px] text-muted">
          Mechanism keyword scores: <Kv data={s.mechanism.scores} />
        </p>
      )}
      <details className="mt-2">
        <summary className="cursor-pointer text-ink2">Abstract (untrusted)</summary>
        <div className="mt-1">
          <Untrusted text={s.abstract} />
        </div>
      </details>
    </article>
  );
}

export function DiscoveriesPanel({ sources }: { sources: Poll<ArmySource[]> }) {
  const [filter, setFilter] = useState("all");
  return (
    <Panel
      id="discoveries"
      title="Research Discoveries"
      subtitle="External research items with provenance and verification. Abstracts are untrusted data: stripped of markup, rendered as plain text, and never able to set status, budgets or code."
    >
      <AState poll={sources} what="sources">
        {(ss) => {
          const counts: Record<string, number> = {};
          for (const s of ss) counts[s.status] = (counts[s.status] ?? 0) + 1;
          const shown = filter === "all" ? ss : ss.filter((s) => s.status === filter);
          return (
            <>
              <div role="group" aria-label="Filter sources by status" className="mb-3 flex flex-wrap gap-1">
                {[["all", ss.length] as const, ...Object.entries(counts)].map(([k, n]) => (
                  <button
                    key={k}
                    type="button"
                    aria-pressed={filter === k}
                    onClick={() => setFilter(k)}
                    className={`rounded border px-2 py-0.5 text-[11px] ${filter === k ? "border-accent bg-accent/20 text-ink" : "border-line2 text-ink2 hover:bg-panel2"}`}
                  >
                    {k.replace(/_/g, " ")} · {n}
                  </button>
                ))}
              </div>
              {shown.length === 0 ? (
                <EmptyState title="No sources" />
              ) : (
                <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
                  {shown.map((s) => (
                    <SourceCard key={s.id} s={s} />
                  ))}
                </div>
              )}
            </>
          );
        }}
      </AState>
    </Panel>
  );
}

/* ================================================================ 3 · strategy evolution + lineage */

function LlmInfo({ info }: { info: unknown }) {
  const i = obj(info);
  if (!i) return <span className="text-muted">—</span>;
  return (
    <div className="text-ink2">
      {i.used_llm ? (
        str(i.reason) ? (
          <span className="font-semibold text-warn">LLM called · output rejected → deterministic fallback</span>
        ) : (
          <span className="font-semibold text-warn">LLM output used (schema-validated)</span>
        )
      ) : (
        <span className="font-semibold text-ink">no LLM call (deterministic)</span>
      )}
      {str(i.reason) && <span className="whitespace-pre-wrap break-words"> · {str(i.reason)}</span>}
      {arr(i.models).length > 0 && <> · models {arr(i.models).join(", ")}</>}
      {numv(i.cost_usd_api_equivalent) !== undefined && <> · {usd(i.cost_usd_api_equivalent, 3)} API-eq.</>}
      {numv(i.wall_s) !== undefined && <> · {num(i.wall_s, 1)} s</>}
      {arr(i.dropped_keys).length > 0 && <> · dropped keys {arr(i.dropped_keys).join(", ")}</>}
      {str(i.billing_note) && <span className="block text-[11px] text-muted">{str(i.billing_note)}</span>}
      {str(i.raw) && (
        <details className="mt-1">
          <summary className="cursor-pointer text-[11px]">Raw LLM output (untrusted)</summary>
          <Untrusted text={str(i.raw)} label="Untrusted LLM output (plain text, not used)" />
        </details>
      )}
    </div>
  );
}

function Checks({ checks }: { checks: unknown }) {
  const c = obj(checks);
  if (!c) return <span className="text-muted">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {Object.entries(c).map(([k, v]) => (
        <span key={k} className={`rounded border px-1.5 text-[10px] ${v === true ? TONE_CLS.good : v === false ? TONE_CLS.bad : TONE_CLS.neutral}`}>
          {v === true ? "✓" : v === false ? "✗" : "?"} {k.replace(/_/g, " ")}
        </span>
      ))}
    </span>
  );
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-muted">{k}</dt>
      <dd className="min-w-0 break-words [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

function Dl({ children }: { children: ReactNode }) {
  return <dl className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">{children}</dl>;
}

function ChallengeView({ r }: { r: Json }) {
  const tests = obj(r.tests) ?? {};
  return (
    <>
      <Dl>
        <Row k="Period">{str(r.period) ?? "—"}</Row>
        <Row k="Verdict">
          <Badge s={str(r.verdict)} />
        </Row>
        <Row k="Hard failures">
          <List items={arr(r.hard_failures)} />
        </Row>
        <Row k="Weaknesses">
          <List items={arr(r.weaknesses)} />
        </Row>
        <Row k="LLM">
          <LlmInfo info={r.llm} />
        </Row>
      </Dl>
      <TableWrap label="Adversarial battery">
        <table className="data mt-2">
          <thead>
            <tr>
              <th>Test</th>
              <th>ok</th>
              <th>hard failure</th>
              <th>Numbers</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(tests).map(([name, tv]) => {
              const t = obj(tv) ?? {};
              const { ok, hard_failure, ...rest } = t;
              return (
                <tr key={name}>
                  <td className="font-mono text-[11px]">{name}</td>
                  <td>
                    <YesNo v={ok} />
                  </td>
                  <td>
                    <YesNo v={hard_failure} goodWhen={false} />
                  </td>
                  <td className="!whitespace-normal">
                    <Kv data={rest} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableWrap>
      {r.llm_critique ? (
        <div className="mt-2">
          <p className="text-[11px] font-semibold text-ink2">LLM critique (advisory only; schema-validated)</p>
          <JsonTable value={r.llm_critique} />
        </div>
      ) : (
        <p className="mt-1 text-[11px] text-muted">No LLM critique recorded.</p>
      )}
    </>
  );
}

function EvaluateView({ r }: { r: Json }) {
  const dec = obj(r.decision) ?? {};
  const bs = obj(dec.bootstrap) ?? {};
  const dsr = obj(dec.dsr) ?? {};
  const scr = obj(r.screen) ?? {};
  return (
    <Dl>
      <Row k="Lab verdict">
        <Badge s={str(r.verdict)} /> <Badge s={str(r.classification)} />
      </Row>
      <Row k="Lab · campaign">
        <code className="text-[11px]">{str(r.lab)}</code> · <code className="text-[11px]">{str(r.campaign)}</code> · task <Badge s={str(r.task_status)} />
      </Row>
      <Row k="Premise check">{fmtAny(r.premise_check)}</Row>
      <Row k="Dev screen">
        cand. <Num v={scr.candidate_dev_oos_sharpe} /> vs champion <Num v={scr.champion_dev_oos_sharpe} /> · passed <YesNo v={scr.passed} />
      </Row>
      {!obj(r.decision) && (
        <Row k="Validation">
          <span className="text-warn">
            not run{scr.passed === false ? " — the development screen failed, so the candidate never reached the selection (validation) walk-forward" : ""}
          </span>
        </Row>
      )}
      <Row k="Decision checks">
        <Checks checks={dec.checks} />
      </Row>
      <Row k="Sharpe (validation)">
        cand. <Num v={dec.candidate_sharpe} /> vs champion <Num v={dec.champion_sharpe} /> · {fmtAny(dec.common_days)} common days
      </Row>
      <Row k="Bootstrap ΔSharpe">
        <Num v={bs.delta_sharpe} /> · P(Δ&gt;0) <Num v={bs.prob_positive} /> · 90% CI [<Num v={bs.ci90_lo} />, <Num v={bs.ci90_hi} />] · 95% CI [<Num v={bs.ci95_lo} />,{" "}
        <Num v={bs.ci95_hi} />] · {fmtAny(bs.resamples)} resamples, block {fmtAny(bs.mean_block)}
      </Row>
      <Row k="Deflated Sharpe">
        DSR <Num v={dsr.dsr} /> · SR₀ <Num v={dsr.sr0} /> · z <Num v={dsr.z} />
      </Row>
      <Row k="Trials counted">{fmtAny(dec.n_validation_trials)}</Row>
      <Row k="Data labels">
        <Kv data={obj(r.data_labels)} />
      </Row>
      {str(r.error) && <Row k="Error">{str(r.error)}</Row>}
    </Dl>
  );
}

function StatsView({ r }: { r: Json }) {
  const el = obj(r.eligibility) ?? {};
  return (
    <Dl>
      <Row k="Eligibility (policy)">
        <Badge s={str(el.status)} /> validated <YesNo v={el.validated} />
      </Row>
      <Row k="Why">
        <List items={arr(el.why)} />
      </Row>
      <Row k="Selection rule">
        {obj(r.selection_rule_checks) ? <Checks checks={r.selection_rule_checks} /> : <span className="text-warn">not evaluated (no selection-period result from E1)</span>}
      </Row>
      <Row k="Dev screen">
        cand. <Num v={obj(r.dev_screen)?.candidate_dev_oos_sharpe} /> vs champion <Num v={obj(r.dev_screen)?.champion_dev_oos_sharpe} /> · passed{" "}
        <YesNo v={obj(r.dev_screen)?.passed} />
      </Row>
      <Row k="ΔSharpe vs champion">
        <Num v={r.delta_sharpe_vs_champion} /> · P(Δ&gt;0) <Num v={r.prob_delta_positive} /> · DSR <Num v={r.deflated_sharpe} /> · {fmtAny(r.n_validation_trials_counted)} trials
      </Row>
      <Row k="Baselines">
        <JsonTable value={r.baselines} />
      </Row>
      <Row k="Adversarial">
        <Badge s={str(r.adversarial_verdict)} /> {arr(r.adversarial_weaknesses).join(", ")}
      </Row>
      {str(r.exposure_note) && <Row k="Exposure">{str(r.exposure_note)}</Row>}
    </Dl>
  );
}

function FormulateView({ r }: { r: Json }) {
  const h = obj(r.hypothesis) ?? {};
  return (
    <Dl>
      <Row k="Decision">
        <Badge s={str(r.decision)} />
      </Row>
      <Row k="Generator">
        <code className="text-[11px]">{str(h.generator) ?? "—"}</code>
      </Row>
      <Row k="LLM">
        <LlmInfo info={h.llm} />
      </Row>
      <Row k="Statement">{str(h.statement) ?? "—"}</Row>
      <Row k="Claimed mechanism">
        <Untrusted text={str(h.claimed_mechanism)} label="Derived from untrusted source text" />
      </Row>
      <Row k="Family · horizon">
        {str(h.family)} · {fmtAny(h.horizon_h)} h · <Kv data={obj(h.params)} />
      </Row>
      <Row k="Alternatives">
        <List items={arr(h.alternatives)} />
      </Row>
      <Row k="Falsification">{str(h.prediction) ?? "—"}</Row>
      <Row k="Premises">
        <List items={arr(h.premises).map((p) => `${str(obj(p)?.id)}: ${str(obj(p)?.claim)}`)} />
      </Row>
      <Row k="Information">{str(h.information_availability) ?? "—"}</Row>
      <Row k="Costs · risk">
        {str(h.costs)} · {str(h.risk)}
      </Row>
      <Row k="Limitations">{str(h.limitations) ?? "—"}</Row>
    </Dl>
  );
}

function StepBody({ kind, r }: { kind: string; r: Json }) {
  switch (kind) {
    case "verify": {
      const ev = obj(r.evidence) ?? {};
      const cr = obj(r.crossref) ?? {};
      return (
        <Dl>
          <Row k="Record re-fetched">
            <YesNo v={r.record_refetched} />
          </Row>
          <Row k="Crossref">
            <YesNo v={cr.matched} yes="matched" no="no match" /> {numv(cr.similarity) !== undefined && <>· sim {num(cr.similarity, 2)}</>} {str(cr.doi)}
          </Row>
          <Row k="Evidence">
            grade <b>{str(ev.grade) ?? "—"}</b> · {fmtAny(ev.points)} pts · marketing language{" "}
            <YesNo v={ev.marketing_language} goodWhen={false} yes="flagged" no="not flagged" />
          </Row>
          <Row k="Flags">
            <Checks checks={ev.flags} />
          </Row>
          <Row k="Classification">
            <Badge s={str(r.classification)} /> {str(r.claim_status)}
          </Row>
        </Dl>
      );
    }
    case "novelty":
      return (
        <Dl>
          <Row k="Decision">
            <Badge s={str(r.decision)} /> family {str(r.family)}
          </Row>
          {r.duplicate_of !== undefined && <Row k="Duplicate of">{fmtAny(r.duplicate_of)}</Row>}
          {r.earlier_investigations !== undefined && <Row k="Earlier investigations">{fmtAny(r.earlier_investigations)}</Row>}
          {str(r.reexamination_rule) && <Row k="Re-examination">{str(r.reexamination_rule)}</Row>}
          <Row k="Near duplicates">
            <List items={arr(r.near_duplicate_sources)} />
          </Row>
        </Dl>
      );
    case "formulate":
      return <FormulateView r={r} />;
    case "contract":
      return (
        <Dl>
          <Row k="Typed contract">
            <YesNo v={r.ok} yes="conforms" no="violations" />
          </Row>
        </Dl>
      );
    case "render":
      return (
        <Dl>
          <Row k="Candidate">
            <code className="text-[11px]">{str(r.candidate_id)}</code>
          </Row>
          <Row k="Code sha256">
            <Hash v={str(r.code_sha256)} n={16} />
          </Row>
          <Row k="Path">
            <code className="break-all text-[11px]">{str(r.path)}</code>
          </Row>
        </Dl>
      );
    case "test":
      return (
        <Dl>
          <Row k="Verdict (D3)">
            <Badge s={str(r.verdict)} />
          </Row>
          <Row k="Static issues">
            <List items={arr(r.static_issues)} />
          </Row>
          <Row k="Deterministic replay">
            <YesNo v={r.deterministic_replay} />
          </Row>
          <Row k="Truncation mismatches">
            <List items={arr(r.truncation_mismatch_bars)} />
          </Row>
        </Dl>
      );
    case "security":
      return (
        <Dl>
          <Row k="Sandbox available">
            <YesNo v={r.sandbox_available} />
          </Row>
          <Row k="Source bytes">{fmtAny(r.source_bytes)}</Row>
          <Row k="ms / 1000 bars">{fmtAny(r.decision_ms_per_1000_bars)}</Row>
          <Row k="Imports">{arr(r.imports).join(", ") || "—"}</Row>
          {str(r.note) && <Row k="Note">{str(r.note)}</Row>}
        </Dl>
      );
    case "challenge":
      return <ChallengeView r={r} />;
    case "evaluate":
      return <EvaluateView r={r} />;
    case "stats":
      return <StatsView r={r} />;
    case "simulate":
      return (
        <Dl>
          <Row k="Applicable (E4)">
            <YesNo v={r.applicable} />
          </Row>
          {str(r.mechanism) && <Row k="Mechanism">{str(r.mechanism)}</Row>}
          {str(r.why) && <Row k="Why">{str(r.why)}</Row>}
          {str(r.linked_evidence) && (
            <Row k="Linked evidence">
              <code className="break-all text-[11px]">{str(r.linked_evidence)}</code>
            </Row>
          )}
          <Row k="Simulator runs">{fmtAny(r.sim_runs)}</Row>
          {str(r.note) && <Row k="Note">{str(r.note)}</Row>}
        </Dl>
      );
    case "risk":
      return (
        <Dl>
          <Row k="Period">{str(r.period)}</Row>
          <Row k="Max drawdown">
            <Num v={r.max_drawdown} />
          </Row>
          <Row k="Daily VaR95 / CVaR95">
            <Num v={r.daily_var95} /> / <Num v={r.daily_cvar95} />
          </Row>
          <Row k="Worst day">
            <Num v={r.worst_day} />
          </Row>
          <Row k="Liquidations">{fmtAny(r.liquidations)}</Row>
        </Dl>
      );
    case "archive":
      return (
        <Dl>
          <Row k="Candidate status">
            <Badge s={str(r.status)} />
          </Row>
          <Row k="Hypothesis status">
            <Badge s={str(r.hypothesis_status)} />
          </Row>
        </Dl>
      );
    case "test_proposal":
      return (
        <Dl>
          <Row k="Code proposal">
            <code className="text-[11px]">{str(r.proposal)}</code> <Badge s={str(r.status)} />
          </Row>
          <Row k="Files">
            <List items={arr(r.files)} />
          </Row>
        </Dl>
      );
    default:
      return <JsonTable value={r} />;
  }
}

function StepCard({ step, n }: { step: Pick<LineageStep, "id" | "stage" | "role" | "kind" | "status" | "error" | "result" | "wall_s" | "llm_calls">; n: number }) {
  return (
    <li className="relative min-w-0 rounded-md border border-line bg-panel2 p-2.5">
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-xs">
        <span className="rounded-full bg-accent/20 px-1.5 font-mono text-[10px] text-[#9ec5f4]">{n}</span>
        <span className="font-semibold uppercase tracking-wider text-ink">{step.kind.replace(/_/g, " ")}</span>
        <code className="text-[11px] text-accent">{step.role}</code>
        <span className="text-muted">{step.stage}</span>
        <Badge s={step.status} />
        <span className="ml-auto text-[11px] text-muted">
          {num(step.wall_s ?? NaN, 2)} s · {fmtAny(step.llm_calls)} LLM
        </span>
        <code className="w-full break-all text-[10px] text-muted">{step.id}</code>
      </div>
      {step.error && <p className="mb-1 whitespace-pre-wrap break-all font-mono text-[11px] text-[#f3a7a7]">{step.error}</p>}
      {step.result ? <StepBody kind={step.kind} r={step.result} /> : <p className="text-xs text-muted">No result recorded.</p>}
    </li>
  );
}

function edgeKey(e: Edge) {
  return `${e.src}|${e.rel}|${e.dst}`;
}

export function EdgesTable({ edges, onNode }: { edges: Edge[]; onNode?: (n: string) => void }) {
  if (!edges.length) return <p className="text-xs text-muted">No edges.</p>;
  const node = (n: string) =>
    onNode ? (
      <button type="button" className="break-all text-left font-mono text-[11px] text-accent hover:underline" onClick={() => onNode(n)}>
        {n}
      </button>
    ) : (
      <code className="break-all text-[11px]">{n}</code>
    );
  return (
    <TableWrap label="Knowledge-graph edges">
      <table className="data">
        <thead>
          <tr>
            <th>Source node</th>
            <th>Relation</th>
            <th>Target node</th>
            <th>Data</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {edges.map((e, i) => (
            <tr key={`${edgeKey(e)}-${i}`}>
              <td className="!whitespace-normal">{node(e.src)}</td>
              <td>
                <span className="rounded border border-line2 px-1 text-[11px]">{e.rel}</span>
              </td>
              <td className="!whitespace-normal">{node(e.dst)}</td>
              <td className="min-w-[14rem] !whitespace-normal">
                <Kv data={e.data} />
              </td>
              <td className="text-[11px] text-muted">{fmtTime(e.created)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

function LineageView({ lin }: { lin: LineageResp }) {
  const h = lin.hypothesis;
  const s = lin.source;
  const uniq = useMemo(() => {
    const seen = new Set<string>();
    return lin.edges.filter((e) => (seen.has(edgeKey(e)) ? false : (seen.add(edgeKey(e)), true)));
  }, [lin.edges]);
  const dupes = lin.edges.length - uniq.length;
  const pre = [...lin.source_steps].sort((a, b) => a.created.localeCompare(b.created));
  let n = 1;
  return (
    <div className="space-y-2">
      <div className="rounded-md border border-line bg-panel2 p-3 text-xs">
        <div className="flex flex-wrap items-center gap-1.5">
          <code className="text-[11px] text-accent">{h.id}</code>
          <Badge s={h.status} />
          {h.classification && <Badge s={h.classification} label="class" />}
          {h.novelty && <Badge s={h.novelty} label="novelty" />}
          <span className="text-muted">signature</span> <code className="text-[11px]">{h.signature}</code>
        </div>
        <p className="mt-1 text-ink">{h.statement}</p>
      </div>
      <ol className="space-y-2" aria-label="Lineage chain">
        <li className="min-w-0 rounded-md border border-line bg-panel2 p-2.5 text-xs">
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <span className="rounded-full bg-accent/20 px-1.5 font-mono text-[10px] text-[#9ec5f4]">{n++}</span>
            <span className="font-semibold uppercase tracking-wider text-ink">source</span>
            {s && <Badge s={s.status} />}
          </div>
          {s ? (
            <Dl>
              <Row k="Title">
                {s.url && /^https?:\/\//.test(s.url) ? (
                  <a className="text-accent hover:underline" href={s.url} target="_blank" rel="noopener noreferrer nofollow">
                    {s.title ?? s.id}
                  </a>
                ) : (
                  (s.title ?? s.id)
                )}
              </Row>
              <Row k="Id · authors">
                <code className="text-[11px]">{s.id}</code> · {(s.authors ?? []).join(", ")}
              </Row>
              <Row k="Published · retrieved">
                {fmtTime(s.published)} · {fmtTime(s.retrieved)}
              </Row>
              <Row k="Query">
                <code className="text-[11px]">{s.query}</code>
              </Row>
              <Row k="Mechanism">{s.mechanism?.family ?? "—"}</Row>
            </Dl>
          ) : (
            <p className="text-muted">No source linked (e.g. a re-examination or a template hypothesis).</p>
          )}
        </li>
        {pre.map((t) => (
          <StepCard key={t.id} step={t} n={n++} />
        ))}
        {lin.steps.map((t) => (
          <StepCard key={t.id} step={t} n={n++} />
        ))}
      </ol>
      <Sub>Graph edges of this hypothesis and its candidate</Sub>
      {dupes > 0 && (
        <p className="mb-1 text-[11px] text-warn">
          The API returned {lin.edges.length} edges; {dupes} exact duplicate(s) (hypothesis and candidate queries both match the same edge) are shown once.
        </p>
      )}
      <EdgesTable edges={uniq} />
    </div>
  );
}

function HypothesesTable({ hs, selected, onSelect }: { hs: Hypothesis[]; selected: string; onSelect: (id: string) => void }) {
  return (
    <TableWrap label="Hypotheses">
      <table className="data">
        <thead>
          <tr>
            <th>Lineage</th>
            <th>Hypothesis</th>
            <th>Status</th>
            <th>Operator</th>
            <th>Candidate</th>
            <th>Statement</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {hs.map((h) => (
            <tr key={h.id} className={h.id === selected ? "bg-accent/10" : undefined}>
              <td>
                <button type="button" className="btn btn-sm" aria-pressed={h.id === selected} onClick={() => onSelect(h.id)}>
                  {h.id === selected ? "Shown" : "Trace"}
                </button>
              </td>
              <td className="font-mono text-[11px]">{h.id}</td>
              <td>
                <Badge s={h.status} />
              </td>
              <td>{h.operator}</td>
              <td className="font-mono text-[11px]">{h.candidate_id ?? "—"}</td>
              <td className="min-w-[18rem] !whitespace-normal text-ink2">{h.statement}</td>
              <td className="text-[11px] text-muted">{fmtTime(h.updated)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

function ReassessView({ detail }: { detail: Poll<CycleResp> }) {
  const d = detail.data;
  if (!d) return <p className="text-xs text-muted">Select a cycle above.</p>;
  const t = d.tasks.find((x) => x.kind === "reassess");
  if (!t) return <p className="text-xs text-muted">Cycle {d.cycle.id} has no REASSESS task yet.</p>;
  if (!t.result) return <p className="text-xs text-muted">REASSESS task is {t.status}; no result yet.</p>;
  const r = t.result;
  const rec = obj(r.recommendation);
  const ranking = arr(r.ranking).map((x) => obj(x) ?? {});
  const outcomes = arr(r.cycle_outcomes).map((x) => obj(x) ?? {});
  const fm = obj(r.forecast_monitor);
  return (
    <div className="space-y-2 text-xs">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Kpi label="Cycle" value={<span className="text-sm">{d.cycle.id}</span>} />
        <Kpi label="Promotions" value={fmtAny(r.promotions)} sub="decided by policy code" />
        <Kpi label="Duplicates detected" value={arr(r.duplicates_detected).length} />
        <Kpi label="Infeasible" value={arr(r.infeasible).length} />
      </div>
      {rec && (
        <div className="rounded-md border border-accent/50 bg-accent/10 p-2">
          <p className="font-semibold text-ink">
            Recommendation (F4, advisory): <code>{str(rec.id)}</code>
          </p>
          <p className="text-ink2">{str(rec.why)}</p>
        </div>
      )}
      {ranking.length > 0 && (
        <TableWrap label="Ranking of next experiments">
          <table className="data">
            <thead>
              <tr>
                <th>#</th>
                <th>Next experiment</th>
                <th>Why</th>
                <th className="num">Prior +</th>
                <th className="num">Cost (runs)</th>
                <th className="num">Bits</th>
                <th className="num">Bits / run</th>
              </tr>
            </thead>
            <tbody>
              {ranking.map((x, i) => (
                <tr key={`${str(x.id)}-${i}`}>
                  <td className="num">{i + 1}</td>
                  <td className="font-mono text-[11px]">{str(x.id)}</td>
                  <td className="!whitespace-normal text-ink2">{str(x.why)}</td>
                  <td className="num">{fmtAny(x.prior_positive)}</td>
                  <td className="num">{fmtAny(x.cost_runs)}</td>
                  <td className="num">
                    <Num v={x.bits} />
                  </td>
                  <td className="num">
                    <Num v={x.bits_per_run} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      <div>
        <p className="font-semibold text-ink2">Cycle outcomes</p>
        {outcomes.length ? (
          <ul className="space-y-0.5">
            {outcomes.map((o, i) => (
              <li key={i}>
                <code className="text-[11px]">{str(o.hypothesis_id)}</code> → <code className="text-[11px]">{str(o.candidate_id)}</code> <Badge s={str(o.status)} />{" "}
                <Badge s={str(o.hypothesis_status)} label="hypothesis" />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">No candidate reached ARCHIVE in this cycle.</p>
        )}
      </div>
      {fm && (
        <p className="text-ink2">
          Forecast monitor at reassessment: {fmtAny(fm.resolved)} resolved · {fmtAny(fm.open)} open · alerts {arr(fm.alerts).length}
        </p>
      )}
      {str(r.note) && <p className="text-muted">{str(r.note)}</p>}
    </div>
  );
}

export function EvolutionPanel({
  memory,
  sources,
  graph,
  detail,
  selectedHyp,
  setSelectedHyp,
  lineage,
}: {
  memory: Poll<MemoryResp>;
  sources: Poll<ArmySource[]>;
  graph: Poll<Edge[]>;
  detail: Poll<CycleResp>;
  selectedHyp: string;
  setSelectedHyp: (id: string) => void;
  lineage: Poll<LineageResp>;
}) {
  return (
    <Panel
      id="evolution"
      title="Strategy Evolution"
      subtitle="Hypotheses and candidates with their policy status. Select a hypothesis to trace its complete lineage from source to archive."
    >
      <AState poll={memory} what="scientific memory">
        {(m) => {
          const planted = m.candidates.filter((c) => c.generator === "planted-control");
          const real = m.candidates.filter((c) => c.generator !== "planted-control");
          const why = (cid: string) => m.experiments.find((e) => e.candidate_id === cid)?.result?.why;
          return (
            <>
              <Sub>Hypotheses</Sub>
              {m.hypotheses.length ? (
                <HypothesesTable hs={m.hypotheses} selected={selectedHyp} onSelect={setSelectedHyp} />
              ) : (
                <EmptyState title="No hypotheses yet">FORMULATE produces hypotheses from verified, non-duplicate sources.</EmptyState>
              )}
              <Sub>Candidates</Sub>
              <TableWrap label="Candidates">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Candidate</th>
                      <th>Status</th>
                      <th>Generator</th>
                      <th>Operator</th>
                      <th>Spec</th>
                      <th>Code sha256</th>
                    </tr>
                  </thead>
                  <tbody>
                    {real.map((c) => (
                      <tr key={c.id}>
                        <td className="font-mono text-[11px]">{c.id}</td>
                        <td>
                          <Badge s={c.status} />
                        </td>
                        <td className="font-mono text-[11px]">{c.generator}</td>
                        <td>{c.operator}</td>
                        <td className="!whitespace-normal">
                          <Kv data={c.spec} />
                        </td>
                        <td>
                          <Hash v={c.code_sha256} />
                        </td>
                      </tr>
                    ))}
                    {real.length === 0 && (
                      <tr>
                        <td colSpan={6} className="text-muted">
                          No research candidates yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </TableWrap>
              <Sub>Planted controls (must be rejected)</Sub>
              <p className="mb-1 text-xs text-ink2">Each cycle plants deliberately broken strategies; a healthy pipeline rejects every one of them.</p>
              {planted.length ? (
                <TableWrap label="Planted controls">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Control</th>
                        <th>Kind</th>
                        <th>Status</th>
                        <th>Rejection reason</th>
                        <th>Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {planted.map((c) => (
                        <tr key={c.id}>
                          <td className="font-mono text-[11px]">{c.id}</td>
                          <td>{c.operator}</td>
                          <td>
                            <Badge s={c.status} />
                            {!c.status.startsWith("rejected") && <span className="ml-1 font-bold text-down">NOT REJECTED</span>}
                          </td>
                          <td className="!whitespace-normal font-mono text-[11px] text-ink2">{fmtAny(why(c.id))}</td>
                          <td className="text-[11px] text-muted">{fmtTime(c.created)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              ) : (
                <p className="text-xs text-muted">No planted controls recorded.</p>
              )}
            </>
          );
        }}
      </AState>

      <Sub>Duplicate detections</Sub>
      <DuplicatesView sources={sources} graph={graph} />

      <Sub>Lineage {selectedHyp && <code className="normal-case text-accent">{selectedHyp}</code>}</Sub>
      {selectedHyp ? (
        <AState poll={lineage} what={`lineage of ${selectedHyp}`}>
          {(l) => (l.hypothesis.id === selectedHyp ? <LineageView lin={l} /> : <p className="text-xs text-muted">Loading lineage…</p>)}
        </AState>
      ) : (
        <p className="text-xs text-muted">Select a hypothesis above.</p>
      )}

      <Sub>REASSESS result of the selected cycle</Sub>
      <ReassessView detail={detail} />
    </Panel>
  );
}

function DuplicatesView({ sources, graph }: { sources: Poll<ArmySource[]>; graph: Poll<Edge[]> }) {
  const dupSources = (sources.data ?? []).filter((s) => s.status === "duplicate_mechanism");
  const dupEdges = (graph.data ?? []).filter((e) => e.rel.includes("duplicate"));
  const bySrc = new Map<string, Edge>();
  for (const e of dupEdges) bySrc.set(e.src.replace(/^source:/, ""), e);
  if (!sources.data && !graph.data) return <p className="text-xs text-muted">Loading…</p>;
  if (!dupSources.length && !dupEdges.length) return <p className="text-xs text-muted">No duplicate mechanisms detected.</p>;
  return (
    <TableWrap label="Duplicate detections">
      <table className="data">
        <thead>
          <tr>
            <th>Source</th>
            <th>Title</th>
            <th>Family</th>
            <th>Graph edge</th>
            <th>Duplicate of</th>
            <th className="num">Prior count</th>
          </tr>
        </thead>
        <tbody>
          {dupSources.map((s) => {
            const e = bySrc.get(s.id);
            return (
              <tr key={s.id}>
                <td className="font-mono text-[11px]">{s.id}</td>
                <td className="min-w-[14rem] !whitespace-normal text-ink2">{s.title}</td>
                <td>{s.mechanism?.family ?? fmtAny(e?.data?.family)}</td>
                <td className="text-[11px]">{e?.rel ?? <span className="text-warn">no edge</span>}</td>
                <td className="font-mono text-[11px]">{e?.dst ?? "—"}</td>
                <td className="num">{fmtAny(e?.data?.prior_count)}</td>
              </tr>
            );
          })}
          {dupEdges
            .filter((e) => !dupSources.some((s) => s.id === e.src.replace(/^source:/, "")))
            .map((e) => (
              <tr key={edgeKey(e)}>
                <td className="font-mono text-[11px]">{e.src}</td>
                <td className="text-muted">(source status is not duplicate_mechanism)</td>
                <td>{fmtAny(e.data?.family)}</td>
                <td className="text-[11px]">{e.rel}</td>
                <td className="font-mono text-[11px]">{e.dst}</td>
                <td className="num">{fmtAny(e.data?.prior_count)}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

/* ================================================================ 4 · predictive performance */

export function PredictivePanel({ army, prospective }: { army: Poll<ArmyForecast>; prospective: Poll<ProspectiveResp> }) {
  return (
    <Panel
      id="predictive"
      title="Predictive Performance"
      subtitle="Prospective paper forecasts are the only independent evidence. Outcomes resolve only after each forecast's window closes; unresolved forecasts never enter a statistic."
    >
      <AState poll={army} what="army forecast monitor">
        {(f) => {
          const rows = Object.entries(f.status);
          return (
            <>
              <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Kpi label="Resolved" value={f.resolved} sub={`assessment needs ≥ ${f.min_resolved_for_assessment} per model`} tone={f.resolved >= f.min_resolved_for_assessment ? "up" : "warn"} />
                <Kpi label="Open (awaiting outcome)" value={f.open} />
                <Kpi label="Drift alerts" value={f.alerts.length} tone={f.alerts.length ? "down" : undefined} />
                <Kpi
                  label="Ledger hash chain"
                  value={f.verify.ok ? "verified" : "BROKEN"}
                  tone={f.verify.ok ? "up" : "down"}
                  sub={`${f.verify.entries} entries · head ${(f.verify.head ?? "").slice(0, 10)}`}
                />
              </div>
              {f.alerts.length > 0 && (
                <p role="alert" className="mb-2 rounded border border-down/50 bg-down/10 p-2 text-xs text-[#f3a7a7]">
                  Degraded vs retrospective expectation: {f.alerts.join(", ")} (triggers a re-evaluation task; never a trade)
                </p>
              )}
              {rows.length === 0 ? (
                <EmptyState title="No resolved binary forecasts yet">
                  Per target:model state appears once outcomes resolve. Each stays <code>insufficient_data</code> until it has ≥ {f.min_resolved_for_assessment} resolved forecasts.
                </EmptyState>
              ) : (
                <TableWrap label="Per target and model drift state">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>target:model</th>
                        <th>State</th>
                        <th className="num">n</th>
                        <th className="num">Brier skill</th>
                        <th className="num">Expected (screen)</th>
                        <th className="num">ECE</th>
                        <th className="num">Bias</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(([k, v]) => (
                        <tr key={k}>
                          <td className="font-mono text-[11px]">{k}</td>
                          <td>
                            <Badge s={v.state} />
                          </td>
                          <td className="num">
                            {v.n}
                            {v.state === "insufficient_data" && <span className="text-muted"> / {f.min_resolved_for_assessment}</span>}
                          </td>
                          <td className="num">
                            <Num v={v.skill} />
                          </td>
                          <td className="num">
                            <Num v={v.expected} />
                          </td>
                          <td className="num">
                            <Num v={v.ece} />
                          </td>
                          <td className="num">
                            <Num v={v.bias} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              )}
            </>
          );
        }}
      </AState>
      <Sub>Forecasting engine · prospective scores</Sub>
      <AState poll={prospective} what="prospective forecasts">
        {(p) => {
          const rows = Object.entries(p.scores ?? {});
          return (
            <div className="text-xs">
              <p className="mb-1 text-ink2">
                {p.label ?? "prospective"} · {p.resolved} resolved · {p.open} open · ledger{" "}
                <span className={p.verify.ok ? "text-up" : "text-down"}>{p.verify.ok ? "verified" : `broken${p.verify.error ? `: ${p.verify.error}` : ""}`}</span> ({p.verify.entries} entries)
              </p>
              {rows.length === 0 ? (
                <p className="text-muted">No prospective scores yet — no forecast window has closed and resolved.</p>
              ) : (
                <JsonTable value={Object.fromEntries(rows)} />
              )}
            </div>
          );
        }}
      </AState>
    </Panel>
  );
}

/* ================================================================ 5 · scientific memory */

export function MemoryPanel({
  memory,
  edges,
  node,
  setNode,
  allEdges,
}: {
  memory: Poll<MemoryResp>;
  edges: Poll<Edge[]>;
  node: string;
  setNode: (n: string) => void;
  allEdges?: Edge[];
}) {
  const [draft, setDraft] = useState(node);
  const nodes = useMemo(() => Array.from(new Set((allEdges ?? []).flatMap((e) => [e.src, e.dst]))).sort(), [allEdges]);
  const apply = (n: string) => {
    setDraft(n);
    setNode(n);
  };
  return (
    <Panel id="memory" title="Scientific Memory" subtitle="Everything the army has learned, including why ideas failed and under which conditions they may be re-examined.">
      <AState poll={memory} what="memory">
        {(m) => {
          const fam = Object.entries(m.earlier_labs.by_family).sort((a, b) => b[1] - a[1]);
          const max = Math.max(1, ...fam.map((x) => x[1]));
          return (
            <>
              <Sub>Earlier labs · {m.earlier_labs.hypotheses} prior hypotheses by mechanism family</Sub>
              <ul className="space-y-1 text-xs" aria-label="Earlier lab hypotheses by family">
                {fam.map(([k, v]) => (
                  <li key={k} className="grid grid-cols-[8rem_minmax(0,1fr)_3rem] items-center gap-2">
                    <span className="truncate font-mono text-[11px]">{k}</span>
                    <span className="h-2.5 rounded-sm bg-line">
                      <span className="block h-full rounded-sm bg-accent" style={{ width: `${(v / max) * 100}%` }} />
                    </span>
                    <span className="num tnum text-right">{v}</span>
                  </li>
                ))}
              </ul>
              <Sub>Hypotheses · evidence</Sub>
              {m.hypotheses.length === 0 ? (
                <p className="text-xs text-muted">No army hypotheses yet.</p>
              ) : (
                <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
                  {m.hypotheses.map((h) => {
                    const ev = h.evidence ?? {};
                    return (
                      <article key={h.id} className="min-w-0 rounded-md border border-line bg-panel2 p-2.5 text-xs">
                        <div className="mb-1 flex flex-wrap items-center gap-1.5">
                          <code className="text-[11px] text-accent">{h.id}</code>
                          <Badge s={h.status} />
                          <span className="text-muted">{h.signature}</span>
                        </div>
                        <p className="mb-1.5 text-ink">{h.statement}</p>
                        <Dl>
                          <Row k="Lab verdict">
                            <Badge s={str(ev.lab_verdict)} />
                          </Row>
                          <Row k="Why it failed">
                            <List items={arr(ev.why)} empty="—" />
                          </Row>
                          <Row k="Adversarial weaknesses">{arr(ev.adversarial_weaknesses).join(", ") || "—"}</Row>
                          <Row k="Conditions">
                            <Kv data={obj(ev.conditions)} />
                          </Row>
                          <Row k="Re-examine if">
                            <List items={arr(ev.reexamine_if)} empty="—" />
                          </Row>
                          <Row k="Premises">
                            <List items={(h.premises ?? []).map((p) => `${p.id}: ${p.claim}`)} empty="—" />
                          </Row>
                        </Dl>
                      </article>
                    );
                  })}
                </div>
              )}
              <Sub>Experiments</Sub>
              <TableWrap label="Experiments">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Key</th>
                      <th>Candidate</th>
                      <th>Stage</th>
                      <th>Cycle</th>
                      <th>Status</th>
                      <th>Why</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.experiments.map((e) => {
                      const r = e.result ?? {};
                      return (
                        <tr key={e.key}>
                          <td className="font-mono text-[11px]">{e.key}</td>
                          <td className="font-mono text-[11px]">{e.candidate_id}</td>
                          <td className="text-[11px]">{e.stage}</td>
                          <td className="font-mono text-[11px]">{str(r.cycle) ?? "—"}</td>
                          <td>
                            <Badge s={str(r.status) ?? (e.stage.includes("reject") ? "rejected" : undefined)} />
                          </td>
                          <td className="min-w-[16rem] !whitespace-normal font-mono text-[11px] text-ink2">{fmtAny(r.why)}</td>
                          <td className="text-[11px] text-muted">{fmtTime(e.created)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableWrap>
            </>
          );
        }}
      </AState>
      <Sub>Knowledge graph</Sub>
      <form
        className="mb-2 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setNode(draft.trim());
        }}
      >
        <label className="field min-w-[14rem] flex-1">
          Filter by node (exact id, e.g. <code>hypothesis:H-…</code>)
          <input className="input font-mono" list="army-nodes" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="all edges" />
          <datalist id="army-nodes">
            {nodes.map((n) => (
              <option key={n} value={n} />
            ))}
          </datalist>
        </label>
        <button type="submit" className="btn btn-sm">
          Filter
        </button>
        <button type="button" className="btn btn-sm" onClick={() => apply("")} disabled={!node}>
          Clear
        </button>
      </form>
      <AState poll={edges} what="graph edges">
        {(es) => (
          <>
            <p className="mb-1 text-[11px] text-muted">
              {es.length} edge(s){node ? ` touching ${node}` : ""}. Click a node to filter on it.
            </p>
            <EdgesTable edges={es} onNode={apply} />
          </>
        )}
      </AState>
    </Panel>
  );
}

/* ================================================================ 6 · controls */

export function ControlsPanel({
  control,
  proposals,
  journal,
  send,
  busy,
  msg,
}: {
  control: Poll<ControlResp>;
  proposals: Poll<Proposal[]>;
  journal: Poll<JournalResp>;
  send: (body: ControlIn, confirmText?: string) => void;
  busy: boolean;
  msg: { ok: boolean; text: string } | null;
}) {
  const [calls, setCalls] = useState<string>("");
  const [showN, setShowN] = useState(40);
  return (
    <Panel
      id="controls"
      title="Controls"
      subtitle="Human controls are recorded in the immutable journal. They can pause or stop research, lower budgets and switch sources; they cannot trade, merge code or change frozen policy."
    >
      <AState poll={control} what="control state">
        {(c) => {
          const max = c.policy_llm_calls_per_cycle_max;
          const n = calls === "" ? c.llm_calls_per_cycle : Number(calls);
          const valid = Number.isInteger(n) && n >= 0 && n <= max;
          return (
            <div className="space-y-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-ink2">State</span> <Badge s={c.state} />
                {c.running ? <Badge s="running" label="cycle" /> : <span className="text-muted">no cycle executing in this API process</span>}
                <span className="ml-auto flex flex-wrap gap-2">
                  <button type="button" className="btn btn-sm" disabled={busy || c.state === "running"} onClick={() => send({ action: "start" })}>
                    Start
                  </button>
                  <button type="button" className="btn btn-sm" disabled={busy || c.state === "paused"} onClick={() => send({ action: "pause" })}>
                    Pause
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    disabled={busy || c.state === "stopped"}
                    onClick={() => send({ action: "stop" }, "Stop the research army? Pending tasks will not be scheduled until it is started again.")}
                  >
                    Stop
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={busy || c.running}
                    title={c.running ? "A cycle is already running" : c.state !== "running" ? `State is ${c.state}; the orchestrator may refuse to schedule tasks` : undefined}
                    onClick={() => send({ action: "run_cycle" }, "Launch a full research cycle now? It makes external requests (arXiv, Crossref) and may use the LLM budget.")}
                  >
                    Run cycle
                  </button>
                </span>
              </div>
              {msg && (
                <p role="status" className={`rounded border p-2 ${msg.ok ? "border-up/40 bg-up/10 text-up" : "border-down/40 bg-down/10 text-[#f3a7a7]"}`}>
                  {msg.text}
                </p>
              )}
              <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                <label className="flex items-center gap-2 rounded border border-line bg-panel2 p-2">
                  <input type="checkbox" checked={c.llm_enabled} disabled={busy} onChange={(e) => send({ action: "set", key: "llm_enabled", value: e.target.checked })} />
                  <span>
                    LLM roles enabled <span className="block text-muted">off → every llm_optional role uses its deterministic template</span>
                  </span>
                </label>
                <label className="flex items-center gap-2 rounded border border-line bg-panel2 p-2">
                  <input
                    type="checkbox"
                    checked={c.source_arxiv_enabled}
                    disabled={busy}
                    onChange={(e) => send({ action: "set", key: "source_arxiv_enabled", value: e.target.checked })}
                  />
                  <span>
                    arXiv source enabled <span className="block text-muted">off → DISCOVER makes no arXiv requests</span>
                  </span>
                </label>
                <form
                  className="flex flex-wrap items-end gap-2 rounded border border-line bg-panel2 p-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (valid) send({ action: "set", key: "llm_calls_per_cycle", value: n });
                  }}
                >
                  <label className="field flex-1">
                    LLM calls per cycle (policy max {max})
                    <input
                      className="input"
                      type="number"
                      min={0}
                      max={max}
                      step={1}
                      value={calls === "" ? String(c.llm_calls_per_cycle) : calls}
                      onChange={(e) => setCalls(e.target.value)}
                      aria-invalid={!valid}
                    />
                  </label>
                  <button type="submit" className="btn btn-sm" disabled={busy || !valid || n === c.llm_calls_per_cycle}>
                    Apply
                  </button>
                  {!valid && <span className="w-full text-[#f3a7a7]">Must be an integer 0–{max}; the frozen policy cap cannot be raised.</span>}
                </form>
              </div>
              {Object.keys(c.last_run ?? {}).length > 0 && (
                <details>
                  <summary className="cursor-pointer text-ink2">Last dashboard-launched run</summary>
                  <JsonTable value={c.last_run} />
                </details>
              )}
              <Sub>External sources</Sub>
              <TableWrap label="External sources">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Policy</th>
                      <th>Reason / use</th>
                      <th>Endpoint</th>
                      <th>Terms</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(c.sources).map(([name, s]) => {
                      const off = name === "arxiv" && !c.source_arxiv_enabled;
                      return (
                        <tr key={name}>
                          <td className="font-mono">{name}</td>
                          <td>
                            <Badge s={s.enabled ? (off ? "disabled_by_human" : "enabled") : "disabled"} />
                          </td>
                          <td className="!whitespace-normal text-ink2">{s.reason ?? s.use ?? "—"}</td>
                          <td className="break-all font-mono text-[11px]">{s.endpoint ?? "—"}</td>
                          <td className="min-w-[14rem] !whitespace-normal text-[11px] text-muted">
                            {s.terms ?? "—"}
                            {s.min_interval_s !== undefined && ` · ≥ ${s.min_interval_s} s between requests`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableWrap>
            </div>
          );
        }}
      </AState>

      <Sub>Code proposals · human review required (never merged automatically)</Sub>
      <AState poll={proposals} what="code proposals">
        {(ps) =>
          ps.length === 0 ? (
            <p className="text-xs text-muted">No code proposals.</p>
          ) : (
            <div className="space-y-2">
              {ps.map((p) => (
                <article key={p.id} className="min-w-0 rounded-md border border-line bg-panel2 p-2.5 text-xs">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <code className="text-[11px] text-accent">{p.id}</code>
                    <span className="font-semibold text-ink">{p.title}</span>
                    <Badge s={p.status} />
                    <span className="text-muted">by {p.author_role}</span>
                    <span className={`rounded border px-1.5 text-[10px] font-bold ${p.merged ? TONE_CLS.bad : TONE_CLS.neutral}`}>{p.merged ? "MERGED" : "not merged"}</span>
                    {p.created_utc && <span className="text-muted">{fmtTime(p.created_utc)}</span>}
                  </div>
                  <p className="mt-1 text-ink2">{p.rationale}</p>
                  <p className="mt-1 break-all">
                    <span className="text-muted">files</span> <code className="text-[11px]">{p.files.join(", ") || "—"}</code>
                    <span className="ml-2 text-muted">tests</span> <code className="text-[11px]">{p.tests.join(", ") || "—"}</code>
                  </p>
                  {p.blocked_paths && p.blocked_paths.length > 0 && (
                    <p className="mt-1 text-[#f3a7a7]">
                      Touches protected paths: <code>{p.blocked_paths.join(", ")}</code> {p.note && `— ${p.note}`}
                    </p>
                  )}
                  {p.checks.length > 0 && (
                    <ol className="mt-1.5 space-y-1">
                      {p.checks.map((ch, i) => (
                        <li key={i}>
                          <details>
                            <summary className="cursor-pointer">
                              <span className={`mr-1 rounded border px-1 font-mono text-[10px] ${ch.rc === 0 ? TONE_CLS.good : TONE_CLS.bad}`}>rc {ch.rc}</span>
                              <code className="break-all text-[11px]">{ch.cmd}</code>
                            </summary>
                            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded bg-page p-2 font-mono text-[11px] text-ink2">{ch.tail || "(no output)"}</pre>
                          </details>
                        </li>
                      ))}
                    </ol>
                  )}
                </article>
              ))}
            </div>
          )
        }
      </AState>

      <Sub>Immutable journal</Sub>
      <AState poll={journal} what="journal">
        {(j) => {
          const entries = [...j.entries].sort((a, b) => b.seq - a.seq);
          return (
            <>
              <p className="mb-2 text-xs">
                Hash chain{" "}
                <span className={`font-semibold ${j.verify.ok ? "text-up" : "text-down"}`}>{j.verify.ok ? "verified" : `BROKEN${j.verify.error ? `: ${String(j.verify.error)}` : ""}`}</span> ·{" "}
                {fmtAny(j.verify.entries)} entries · head <Hash v={str(j.verify.head)} n={16} /> · showing latest {Math.min(showN, entries.length)} of {entries.length} fetched
              </p>
              <TableWrap label="Journal entries">
                <table className="data">
                  <thead>
                    <tr>
                      <th className="num">Seq</th>
                      <th>Time</th>
                      <th>Actor</th>
                      <th>Event</th>
                      <th>Data</th>
                      <th>Hash</th>
                      <th>Prev</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.slice(0, showN).map((e) => (
                      <tr key={e.seq}>
                        <td className="num">{e.seq}</td>
                        <td className="text-[11px] text-muted">{fmtTime(e.ts)}</td>
                        <td className="font-mono text-[11px]">{e.actor}</td>
                        <td>{e.event}</td>
                        <td className="min-w-[16rem] max-w-[36rem] !whitespace-normal">
                          <span className="line-clamp-3 break-all font-mono text-[11px] text-ink2">{JSON.stringify(e.data)}</span>
                        </td>
                        <td>
                          <Hash v={e.hash} n={10} />
                        </td>
                        <td>
                          <Hash v={e.prev} n={10} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
              {entries.length > showN && (
                <button type="button" className="btn btn-sm mt-2" onClick={() => setShowN((x) => x + 60)}>
                  Show more
                </button>
              )}
            </>
          );
        }}
      </AState>
    </Panel>
  );
}

