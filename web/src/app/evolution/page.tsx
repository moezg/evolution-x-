"use client";
import { useMemo, useState } from "react";
import { CIStrip, LineageTree, ObjectiveScatter, ORIGIN_COLORS, PairedRunBars } from "@/components/labs";
import { ProposalsSection } from "@/components/Proposals";
import { EmptyState, ErrorNote, JobProgress, JsonTable, KeyValue, PageTitle, Panel, StatusPill } from "@/components/ui";
import { apiPost, errorMessage } from "@/lib/api";
import { useJob, usePoll } from "@/lib/hooks";
import { KINDS, kindLabel } from "@/lib/colors";
import { fmtAny, fmtTime } from "@/lib/format";
import type { Candidate, Challenge, Job, Lineage } from "@/lib/types";

const OBJECTIVES = ["ret", "neg_dd", "cvar", "robust", "realism", "neg_cost", "novelty"];

function RunForm({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({
    family: "momentum", generations: 3, pop: 6, train_seeds: 2, val_seeds: 3, heldout_seeds: 2, duration_s: 900, seed: 0, use_llm_synthesis: true,
  });
  const [jobId, setJobId] = useState<string | null>(null);
  const [err, setErr] = useState<string>();
  const job = useJob(jobId, onDone);
  const set = (k: keyof typeof f, v: unknown) => setF((x) => ({ ...x, [k]: v }));
  const numField = (k: keyof typeof f, label: string, min: number, max: number, step = 1) => (
    <label className="field">
      {label}
      <input className="input tnum" type="number" min={min} max={max} step={step} value={f[k] as number} onChange={(e) => set(k, Number(e.target.value))} />
    </label>
  );
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(undefined);
    try {
      const j = await apiPost<Job>("/api/evolution/run", f);
      setJobId(j.id);
    } catch (e) {
      setErr(errorMessage(e));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Run evolution">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <label className="field col-span-2 sm:col-span-1">
          Strategy family
          <select className="input" value={f.family} onChange={(e) => set("family", e.target.value)}>
            {KINDS.map((k) => <option key={k} value={k}>{kindLabel(k)}</option>)}
          </select>
        </label>
        {numField("generations", "Generations", 1, 20)}
        {numField("pop", "Population", 3, 24)}
        {numField("train_seeds", "Train seeds", 1, 8)}
        {numField("val_seeds", "Validation seeds", 2, 12)}
        {numField("heldout_seeds", "Held-out seeds", 1, 8)}
        {numField("duration_s", "Duration / run (s)", 300, 7200, 60)}
        {numField("seed", "Seed", 0, 1e9)}
        <label className="flex items-center gap-2 self-end pb-2 text-xs text-ink2">
          <input type="checkbox" checked={f.use_llm_synthesis} onChange={(e) => set("use_llm_synthesis", e.target.checked)} />
          LLM genome synthesis
        </label>
      </div>
      <button className="btn btn-primary" type="submit" disabled={job?.status === "running" || job?.status === "queued"}>▶ Run evolution</button>
      {err && <p role="alert" className="text-xs text-down">{err}</p>}
      <JobProgress job={job} label="Evolution" />
    </form>
  );
}

function ChallengeCard({ c }: { c: Challenge }) {
  const ev = c.evidence ?? {};
  const pd = ev.paired_diff;
  return (
    <article className="space-y-3 rounded-md border border-line bg-panel2 p-3">
      <header className="flex flex-wrap items-center gap-2 text-xs">
        <StatusPill status={c.decision} />
        <span>challenger <code>{c.challenger}</code> vs champion <code>{c.champion}</code></span>
        <span className="ml-auto text-muted">{fmtTime(c.created)}</span>
      </header>
      {pd && (
        <div>
          <h4 className="text-[11px] uppercase tracking-wider text-muted">Paired utility difference (challenger − champion), 95% CI, n={pd.n ?? "?"}</h4>
          <CIStrip zero label="Paired utility difference with confidence interval" rows={[{ label: "Δ utility", color: "#3987e5", stat: pd }]} />
        </div>
      )}
      <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div><dt className="text-muted">Δ mean</dt><dd className="tnum">{fmtAny(pd?.mean)}</dd></div>
        <div><dt className="text-muted">CI</dt><dd className="tnum">[{fmtAny(pd?.t_lo)}, {fmtAny(pd?.t_hi)}]</dd></div>
        <div><dt className="text-muted">Realism gap</dt><dd className="tnum">{fmtAny(ev.realism_gap)}</dd></div>
        <div><dt className="text-muted">Drawdown gap</dt><dd className="tnum">{fmtAny(ev.drawdown_gap)}</dd></div>
      </dl>
      {!!ev.reasons?.length && (
        <div>
          <h4 className="text-[11px] uppercase tracking-wider text-muted">{c.decision === "rejected" ? "Rejection reasons" : "Reasons"}</h4>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-ink2">
            {ev.reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}
      {!!ev.per_run?.length && (
        <div>
          <h4 className="text-[11px] uppercase tracking-wider text-muted">Per-run utility on paired validation seeds</h4>
          <PairedRunBars perRun={ev.per_run} />
        </div>
      )}
    </article>
  );
}

export default function EvolutionPage() {
  const [family, setFamily] = useState("");
  const lin = usePoll<Lineage>(`/api/evolution/lineage${family ? `?family=${family}` : ""}`, 5000);
  const [runId, setRunId] = useState("");
  const [xKey, setXKey] = useState("ret");
  const [yKey, setYKey] = useState("neg_dd");
  const [sel, setSel] = useState<Candidate | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [rbMsg, setRbMsg] = useState<{ ok: boolean; text: string }>();

  const runs = lin.data?.runs ?? [];
  const activeRun = runId || runs[0]?.run_id || "";
  const cands = useMemo(() => (lin.data?.candidates ?? []).filter((c) => !activeRun || c.run_id === activeRun || c.origin === "default"), [lin.data, activeRun]);
  const runCands = useMemo(() => {
    // keep candidates from the selected run plus any parents they reference
    const inRun = (lin.data?.candidates ?? []).filter((c) => c.run_id === activeRun);
    const ids = new Set(inRun.map((c) => c.id));
    const parents = (lin.data?.candidates ?? []).filter((c) => !ids.has(c.id) && inRun.some((x) => (x.parents ?? []).includes(c.id)));
    return activeRun ? [...parents, ...inRun] : cands;
  }, [lin.data, activeRun, cands]);
  const champions = lin.data?.champions ?? [];
  const challenges = (lin.data?.challenges ?? []).slice().reverse();

  const rollback = async (fam: string) => {
    if (!reviewer.trim()) {
      setRbMsg({ ok: false, text: "Enter a reviewer name before rolling back." });
      return;
    }
    setRbMsg(undefined);
    try {
      const r = await apiPost<{ active: unknown }>("/api/evolution/rollback", { family: fam, reviewer: reviewer.trim() });
      setRbMsg({ ok: true, text: `Rolled back ${fam}. Active: ${JSON.stringify(r.active).slice(0, 160)}` });
      lin.refresh();
    } catch (e) {
      setRbMsg({ ok: false, text: errorMessage(e) });
    }
  };
  const champFamilies = Array.from(new Set(champions.map((c) => c.family)));

  return (
    <div className="space-y-4">
      <PageTitle title="Evolution lab">
        <label className="field !flex-row items-center gap-2">
          <span>Family</span>
          <select className="input w-auto" value={family} onChange={(e) => { setFamily(e.target.value); setRunId(""); setSel(null); }}>
            <option value="">all families</option>
            {KINDS.map((k) => <option key={k} value={k}>{kindLabel(k)}</option>)}
          </select>
        </label>
      </PageTitle>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <Panel title="Run evolution" subtitle="Multi-objective search with train / validation / held-out seeds. Champions change only via a significant paired challenge.">
          <RunForm onDone={lin.refresh} />
        </Panel>
        <Panel title="Evolution runs" subtitle="Select a run to inspect its generations.">
          <ErrorNote error={lin.error} what="lineage" />
          {runs.length ? (
            <div className="max-h-72 overflow-auto">
              <table className="data">
                <thead><tr><th scope="col">Run</th><th scope="col">Family</th><th scope="col">Status</th><th scope="col">Created</th><th scope="col">Finished</th></tr></thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.run_id} className={r.run_id === activeRun ? "!bg-accent/15" : ""}>
                      <td>
                        <button className="text-left text-accent hover:underline" onClick={() => { setRunId(r.run_id); setSel(null); }} aria-pressed={r.run_id === activeRun}>
                          {r.run_id}
                        </button>
                      </td>
                      <td>{kindLabel(r.family)}</td>
                      <td><StatusPill status={r.status} /></td>
                      <td className="text-muted">{fmtTime(r.created)}</td>
                      <td className="text-muted">{fmtTime(r.finished)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No evolution runs yet">Start a run to populate generations, lineage and champion challenges.</EmptyState>
          )}
        </Panel>
      </div>

      {runCands.length > 0 && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Panel
            title="Generational comparison"
            subtitle="Each dot is a candidate (validation objectives, higher is better on both axes). Color = generation; dashed line = 2-D Pareto front."
            actions={
              <>
                <label className="field !flex-row items-center gap-1">
                  <span>x</span>
                  <select className="input w-auto" value={xKey} onChange={(e) => setXKey(e.target.value)}>
                    {OBJECTIVES.map((o) => <option key={o}>{o}</option>)}
                  </select>
                </label>
                <label className="field !flex-row items-center gap-1">
                  <span>y</span>
                  <select className="input w-auto" value={yKey} onChange={(e) => setYKey(e.target.value)}>
                    {OBJECTIVES.map((o) => <option key={o}>{o}</option>)}
                  </select>
                </label>
              </>
            }
          >
            <ObjectiveScatter candidates={runCands} xKey={xKey} yKey={yKey} />
          </Panel>
          <Panel title="Lineage tree" subtitle="Generations left → right; curves connect parents to children. Click a node for its genome.">
            <LineageTree candidates={runCands} onSelect={setSel} selected={sel?.id} />
            <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink2" aria-label="Origin legend">
              {Object.entries(ORIGIN_COLORS).map(([k, c]) => (
                <li key={k} className="flex items-center gap-1"><span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: c }} />origin: {k.replace("_", " ")}</li>
              ))}
              <li className="flex items-center gap-1"><span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full border-2 border-[#f2c14e]" />status: champion</li>
              <li className="flex items-center gap-1"><span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full border-2 border-dashed border-down" />rejected / failed</li>
            </ul>
            {sel && (
              <div className="mt-3 rounded-md border border-line bg-panel2 p-3 text-xs">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <code className="font-semibold">{sel.id}</code>
                  <StatusPill status={sel.status} />
                  <span className="text-muted">gen {sel.generation} · {sel.origin.replace("_", " ")}{sel.parents?.length ? ` · parents ${sel.parents.join(", ")}` : ""}</span>
                  <button className="btn btn-sm ml-auto" onClick={() => setSel(null)}>Close</button>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div><h4 className="mb-1 text-[11px] uppercase text-muted">Genome</h4><KeyValue data={sel.genome} /></div>
                  <div>
                    <h4 className="mb-1 text-[11px] uppercase text-muted">Objectives</h4>
                    <KeyValue data={sel.objectives ?? {}} />
                    {sel.train && Object.keys(sel.train).length > 0 && (<><h4 className="mb-1 mt-2 text-[11px] uppercase text-muted">Train</h4><KeyValue data={sel.train} /></>)}
                  </div>
                </div>
              </div>
            )}
          </Panel>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel
          title="Champion history"
          subtitle="Every promotion is versioned and can be rolled back."
          actions={
            <label className="field !flex-row items-center gap-2">
              <span>Reviewer</span>
              <input className="input w-36" value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="your name" />
            </label>
          }
        >
          {champions.length ? (
            <>
              <div className="overflow-x-auto">
                <table className="data">
                  <thead><tr><th scope="col">Family</th><th scope="col" className="num">Ver</th><th scope="col">Candidate</th><th scope="col">Promoted</th><th scope="col">Reason</th><th scope="col">Active</th></tr></thead>
                  <tbody>
                    {champions.map((c) => (
                      <tr key={`${c.family}-${c.version}`}>
                        <td>{kindLabel(c.family)}</td>
                        <td className="num">v{c.version}</td>
                        <td><code>{c.candidate_id}</code></td>
                        <td className="text-muted">{fmtTime(c.promoted_at)}</td>
                        <td className="!whitespace-normal">{c.reason}</td>
                        <td>{c.active ? <span className="font-semibold text-up">● active</span> : <span className="text-muted">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {champFamilies.map((fam) => (
                  <button key={fam} className="btn btn-sm border-warn/60 text-warn" onClick={() => rollback(fam)}>
                    ↶ Roll back {kindLabel(fam)}
                  </button>
                ))}
              </div>
              {rbMsg && <p role="status" className={`mt-2 break-all text-xs ${rbMsg.ok ? "text-up" : "text-down"}`}>{rbMsg.text}</p>}
            </>
          ) : (
            <EmptyState title="No champions recorded" />
          )}
        </Panel>
        <Panel title="Champion / challenger decisions" subtitle="Promotion requires a significant paired improvement on validation seeds without realism or drawdown regressions.">
          {challenges.length ? (
            <div className="max-h-[720px] space-y-3 overflow-y-auto pr-1">
              {challenges.map((c) => <ChallengeCard key={String(c.id)} c={c} />)}
            </div>
          ) : (
            <EmptyState title="No challenges yet" />
          )}
        </Panel>
      </div>

      {runs.find((r) => r.run_id === activeRun)?.config ? (
        <Panel title="Run configuration">
          <div className="text-xs"><JsonTable value={runs.find((r) => r.run_id === activeRun)?.config} /></div>
        </Panel>
      ) : null}

      <ProposalsSection />
    </div>
  );
}
