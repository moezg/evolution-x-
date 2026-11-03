"use client";
import { useState } from "react";
import { EmptyState, ErrorNote, JobProgress, JsonTable, PageTitle, Panel, ProvenanceBadge } from "@/components/ui";
import { ApiError, apiPost, errorMessage } from "@/lib/api";
import { useJob, usePoll } from "@/lib/hooks";
import { fmtAny, fmtTime } from "@/lib/format";
import type { CouncilReport, ExperimentListItem, Job, RoleOutput, RunManifest } from "@/lib/types";

type Claim = string | { text?: string; evidence?: string[] };

const SECTIONS: { key: keyof RoleOutput; label: string; cls: string; hint: string }[] = [
  { key: "observations", label: "Observations", cls: "border-l-[#3987e5]", hint: "directly measured" },
  { key: "hypotheses", label: "Hypotheses", cls: "border-l-[#9085e9]", hint: "testable explanations" },
  { key: "assumptions", label: "Assumptions", cls: "border-l-[#c98500]", hint: "taken as given" },
  { key: "conclusions", label: "Conclusions", cls: "border-l-[#199e70]", hint: "supported by evidence" },
];

function ClaimList({ items }: { items: Claim[] }) {
  if (!items.length) return <p className="text-[11px] italic text-muted">none</p>;
  return (
    <ul className="space-y-1">
      {items.map((c, i) => {
        const text = typeof c === "string" ? c : c.text ?? JSON.stringify(c);
        const ev = typeof c === "string" ? [] : c.evidence ?? [];
        return (
          <li key={i} className="text-xs text-ink">
            {text}
            {ev.length > 0 && (
              <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
                {ev.map((e) => <code key={e} className="rounded bg-[#0f0f0e] px-1 text-[10px] text-muted">{e}</code>)}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function RoleCard({ role }: { role: { role: string; title: string; output: RoleOutput; grounding?: number } }) {
  const o = role.output ?? {};
  const conf = typeof o.confidence === "number" ? o.confidence : Number(o.confidence);
  return (
    <article className="flex flex-col gap-3 rounded-md border border-line bg-panel2 p-3">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{role.title ?? role.role}</h3>
        <span className="text-[11px] text-muted tnum">
          confidence {Number.isFinite(conf) ? conf.toFixed(2) : "—"}
          {role.grounding !== undefined ? ` · grounding ${role.grounding.toFixed(2)}` : ""}
        </span>
      </header>
      {Number.isFinite(conf) && (
        <div className="h-1 overflow-hidden rounded bg-line" role="meter" aria-label="Confidence" aria-valuemin={0} aria-valuemax={1} aria-valuenow={conf}>
          <div className="h-full bg-accent" style={{ width: `${Math.max(0, Math.min(1, conf)) * 100}%` }} />
        </div>
      )}
      {SECTIONS.map((s) => (
        <section key={s.key} className={`border-l-4 ${s.cls} pl-2`}>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink2">
            {s.label} <span className="font-normal normal-case tracking-normal text-muted">— {s.hint}</span>
          </h4>
          <ClaimList items={(o[s.key] as Claim[] | undefined) ?? []} />
        </section>
      ))}
      {!!o.recommended_experiments?.length && (
        <section>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink2">Recommended experiments</h4>
          <ul className="space-y-0.5 text-xs text-ink2">
            {o.recommended_experiments.map((e, i) => {
              const x = e as { scenario?: string; replicates?: number; rationale?: string };
              return <li key={i}>• <b className="text-ink">{x.scenario ?? JSON.stringify(e)}</b>{x.replicates ? ` ×${x.replicates}` : ""}{x.rationale ? ` — ${x.rationale}` : ""}</li>;
            })}
          </ul>
        </section>
      )}
      {!!o.risks?.length && (
        <section>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-down">Risks</h4>
          <ul className="space-y-0.5 text-xs text-ink2">{o.risks.map((r, i) => <li key={i}>• {r}</li>)}</ul>
        </section>
      )}
    </article>
  );
}

function Synthesis({ s }: { s: Record<string, unknown> }) {
  const pe = (s.prioritised_experiments as { scenario: string; replicates: number; votes: number; why: string[] }[] | undefined) ?? [];
  const concl = (s.conclusions as { role: string; text: string }[] | undefined) ?? [];
  const hyp = (s.hypotheses_to_test as { role: string; text: string }[] | undefined) ?? [];
  const chall = (s.open_challenges as string[] | undefined) ?? [];
  const known = new Set(["prioritised_experiments", "conclusions", "hypotheses_to_test", "open_challenges", "mean_grounding"]);
  const rest = Object.fromEntries(Object.entries(s).filter(([k]) => !known.has(k)));
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <section className="rounded-md border border-line bg-panel2 p-3">
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink2">Prioritised experiments</h4>
        {pe.length ? (
          <ol className="space-y-1.5 text-xs">
            {pe.map((e) => (
              <li key={e.scenario}>
                <b>{e.scenario}</b> <span className="text-muted">×{e.replicates} · {e.votes} vote{e.votes === 1 ? "" : "s"}</span>
                <ul className="ml-3 text-[11px] text-ink2">{e.why?.map((w, i) => <li key={i}>– {w}</li>)}</ul>
              </li>
            ))}
          </ol>
        ) : <p className="text-xs text-muted">none</p>}
      </section>
      <section className="space-y-3 rounded-md border border-line bg-panel2 p-3">
        <div className="border-l-4 border-l-[#199e70] pl-2">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-ink2">Conclusions</h4>
          {concl.length ? <ul className="space-y-0.5 text-xs">{concl.map((c, i) => <li key={i}><span className="text-muted">{c.role}:</span> {c.text}</li>)}</ul> : <p className="text-[11px] italic text-muted">none — the evidence does not yet support firm conclusions</p>}
        </div>
        <div className="border-l-4 border-l-[#9085e9] pl-2">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-ink2">Hypotheses to test</h4>
          {hyp.length ? <ul className="space-y-0.5 text-xs">{hyp.map((c, i) => <li key={i}><span className="text-muted">{c.role}:</span> {c.text}</li>)}</ul> : <p className="text-[11px] italic text-muted">none</p>}
        </div>
        {chall.length > 0 && (
          <div className="border-l-4 border-l-[#e66767] pl-2">
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-ink2">Open challenges (adversarial)</h4>
            <ul className="space-y-0.5 text-xs">{chall.map((c, i) => <li key={i}>{c}</li>)}</ul>
          </div>
        )}
        {s.mean_grounding !== undefined && <p className="text-[11px] text-muted">Mean grounding: {fmtAny(s.mean_grounding)}</p>}
      </section>
      {Object.keys(rest).length > 0 && <div className="lg:col-span-2 text-xs"><JsonTable value={rest} /></div>}
    </div>
  );
}

function ReportView({ r }: { r: CouncilReport }) {
  const x = r as CouncilReport & { context_source?: string; orchestration?: string; experiment_id?: string | null };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <span>{fmtTime(r.created)}</span>
        {r.llm && <span>LLM: {r.llm.provider}/{r.llm.model} · {r.llm.calls} calls · {r.llm.cache_hits} cache hits · budget {fmtAny(r.llm.budget)}</span>}
        {x.context_source && <span>context: {x.context_source}</span>}
        {x.experiment_id && <span>experiment: <code>{x.experiment_id}</code></span>}
      </div>
      {x.orchestration && <p className="text-[11px] text-muted">{x.orchestration}</p>}
      {r.synthesis && <Synthesis s={r.synthesis} />}
      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {(r.roles ?? []).map((role) => <RoleCard key={role.role} role={role} />)}
      </div>
    </div>
  );
}

export default function CouncilPage() {
  const reports = usePoll<CouncilReport[]>("/api/council/reports", 10000);
  const exps = usePoll<ExperimentListItem[]>("/api/experiments", 0);
  const evalR = usePoll<Record<string, unknown>>("/api/eval/latest", 0);
  const runs = usePoll<RunManifest[]>("/api/runs", 10000);
  const [q, setQ] = useState("What mechanisms drive price dynamics after the last shock, and what should we test next?");
  const [exp, setExp] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [err, setErr] = useState<string>();
  const [sel, setSel] = useState(0);
  const job = useJob(jobId, () => { reports.refresh(); setSel(0); });
  const list = Array.isArray(reports.data) ? reports.data : [];
  const evalMissing = evalR.error instanceof ApiError && evalR.error.status === 404;

  const run = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(undefined);
    try {
      const j = await apiPost<Job>("/api/council/run", { question: q, experiment_id: exp || null });
      setJobId(j.id);
    } catch (e) {
      setErr(errorMessage(e));
    }
  };

  return (
    <div className="space-y-4">
      <PageTitle title="Research council" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <Panel title="Convene the council" subtitle="Eight role agents analyse read-only context; every claim is labelled as observation, hypothesis, assumption or conclusion.">
          <form onSubmit={run} className="space-y-3" aria-label="Run research council">
            <label className="field">
              Research question
              <textarea className="input min-h-24" value={q} onChange={(e) => setQ(e.target.value)} required />
            </label>
            <label className="field">
              Ground in experiment (optional)
              <select className="input" value={exp} onChange={(e) => setExp(e.target.value)}>
                <option value="">live simulation / latest context</option>
                {(exps.data ?? []).map((x) => <option key={x.experiment_id} value={x.experiment_id}>{x.experiment_id}</option>)}
              </select>
            </label>
            <button className="btn btn-primary" type="submit" disabled={job?.status === "running" || job?.status === "queued"}>▶ Run council</button>
            {err && <p role="alert" className="text-xs text-down">{err}</p>}
            <JobProgress job={job} label="Council" />
          </form>
        </Panel>
        <Panel
          title="Council reports"
          actions={
            list.length > 1 ? (
              <label className="field !flex-row items-center gap-2">
                <span>Report</span>
                <select className="input w-auto max-w-[60vw]" value={sel} onChange={(e) => setSel(Number(e.target.value))}>
                  {list.map((r, i) => <option key={r.id} value={i}>{fmtTime(r.created)} — {r.question.slice(0, 50)}</option>)}
                </select>
              </label>
            ) : undefined
          }
          subtitle={list[sel]?.question}
        >
          <ErrorNote error={reports.error} what="council reports" />
          {list[sel] ? <ReportView r={list[sel]} /> : !reports.loading && <EmptyState title="No council reports yet">Run the council to produce structured, role-separated analysis.</EmptyState>}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Latest evaluation" subtitle="Realism / baseline / ablation report produced by `make eval`.">
          {evalMissing ? (
            <EmptyState title="No evaluation yet">Run <code>make eval</code> on the backend to produce realism, baseline and ablation tables.</EmptyState>
          ) : evalR.error ? (
            <ErrorNote error={evalR.error} what="eval" />
          ) : evalR.data ? (
            <div className="max-h-[640px] overflow-auto text-xs"><JsonTable value={evalR.data} /></div>
          ) : (
            <EmptyState title="Loading…" />
          )}
        </Panel>
        <Panel title="Persisted runs" subtitle="Saved simulation runs with event fingerprints for exact reproduction.">
          <ErrorNote error={runs.error} what="runs" />
          {runs.data?.length ? (
            <div className="max-h-[640px] overflow-auto">
              <table className="data">
                <thead><tr><th scope="col">Run</th><th scope="col">Data</th><th scope="col">Created</th><th scope="col" className="num">Agents</th><th scope="col">Fingerprint</th><th scope="col">Return</th></tr></thead>
                <tbody>
                  {runs.data.map((r) => {
                    const perf = (r.performance ?? {}) as Record<string, unknown>;
                    return (
                      <tr key={r.run_id} title={typeof r.reproduce === "string" ? `reproduce: ${r.reproduce}` : undefined}>
                        <td><code>{r.run_id}</code></td>
                        <td><ProvenanceBadge label={r.data_label} /></td>
                        <td className="text-muted">{fmtTime(r.created_utc)}</td>
                        <td className="num">{r.n_agents}</td>
                        <td><code className="text-[11px] text-muted">{String(r.event_fingerprint ?? "").slice(0, 12)}</code></td>
                        <td className="num">{typeof perf.return_pct === "number" ? `${(perf.return_pct as number).toFixed(2)}%` : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No persisted runs">Use “Save run” on the Overview page to persist the live simulation.</EmptyState>
          )}
        </Panel>
      </div>
    </div>
  );
}
