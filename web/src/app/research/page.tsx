"use client";
import { useCallback, useEffect, useState } from "react";
import { EmptyState, ErrorNote, JobProgress, JsonTable, PageTitle, Panel } from "@/components/ui";
import { Hash, Meter, Prov, Verdict } from "@/components/research";
import {
  CalibrationPanel,
  DataCoverage,
  FinalPanel,
  HypothesesPanel,
  JournalPanel,
  LineagePanel,
  TaskDrawer,
  TasksTable,
  useRefreshOn,
} from "@/components/researchSections";
import { apiPost, errorMessage } from "@/lib/api";
import { useJob, usePoll } from "@/lib/hooks";
import { fmtAny, fmtTime, humanize } from "@/lib/format";
import type { Job } from "@/lib/types";
import type { Campaign, LabSummary, Overview } from "@/lib/research";

const LAB_RE = /^[a-z0-9_]+$/;

/* ---------------------------------------------------------------- questions + protocol */

function QuestionsProtocol({ ov }: { ov: Overview }) {
  const pr = ov.protocol;
  const rule = pr.promotion_rule;
  return (
    <Panel
      id="protocol"
      title="Research questions & frozen protocol"
      subtitle="The protocol is hashed and frozen before any candidate is evaluated; changes are only possible as recorded amendments."
    >
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <article className="rounded-md border border-line bg-panel2 p-3 text-xs">
          <h3 className="mb-1 text-sm font-semibold">
            A · Simulator realism <Prov kind="SYNTHETIC" />
          </h3>
          <p className="text-ink2">
            Does calibrating the synthetic market on historical train days bring its stylised facts closer to <em>unseen</em> validation and held-out days? See{" "}
            <a className="text-accent hover:underline" href="#calibration">
              Simulator realism
            </a>
            .
          </p>
        </article>
        <article className="rounded-md border border-line bg-panel2 p-3 text-xs">
          <h3 className="mb-1 text-sm font-semibold">
            B · Strategy robustness <Prov kind="HISTORICAL BACKTEST" />
          </h3>
          <p className="text-ink2">
            Does a candidate strategy beat the active champion out-of-sample in historical backtests on real Binance perpetual data — after costs, at 2× costs, under
            drawdown limits and after deflating for the number of trials? See{" "}
            <a className="text-accent hover:underline" href="#tasks">
              Experiments
            </a>
            .
          </p>
        </article>
        <article className="rounded-md border border-line bg-panel2 p-3 text-xs">
          <h3 className="mb-1 text-sm font-semibold">
            C · Value of self-evolution <Prov kind="HYPOTHESIS" />
          </h3>
          <p className="text-ink2">
            At equal budget, does the self-evolving system (guided vs random selector) end up better than the frozen v0 system on the sealed final split? See{" "}
            <a className="text-accent hover:underline" href="#final">
              Final comparison
            </a>
            .
          </p>
        </article>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section aria-labelledby="pr-h" className="space-y-2 text-xs">
          <h3 id="pr-h" className="text-sm font-semibold">
            {pr.name}
          </h3>
          <p>
            protocol sha256 <Hash v={pr.sha256} n={64} />
          </p>
          <div className="overflow-x-auto">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Split</th>
                  <th scope="col">Start</th>
                  <th scope="col">End (excl.)</th>
                  <th scope="col">Use</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(pr.splits).map(([k, s]) => (
                  <tr key={k}>
                    <td className="font-semibold">{k}</td>
                    <td>{s.start}</td>
                    <td>{s.end_exclusive}</td>
                    <td className="!whitespace-normal text-ink2">{s.use}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-ink2">
            Trials so far in this lab: development <b className="tnum text-ink">{fmtAny(ov.trials.development)}</b> · validation{" "}
            <b className="tnum text-ink">{fmtAny(ov.trials.validation)}</b> (each validation access lowers its evidential value).
          </p>
        </section>
        <section aria-labelledby="rule-h" className="space-y-2 text-xs">
          <h3 id="rule-h" className="text-sm font-semibold">
            Promotion rule
          </h3>
          <dl className="space-y-1.5">
            <div>
              <dt className="text-muted">Primary metric</dt>
              <dd>{rule.primary_metric}</dd>
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-1">
              <div>
                <dt className="text-muted">Minimal useful effect (Δ Sharpe)</dt>
                <dd className="tnum">{fmtAny(rule.minimal_useful_effect_sharpe)}</dd>
              </div>
              <div>
                <dt className="text-muted">Required P(improvement)</dt>
                <dd className="tnum">{fmtAny(rule.required_prob_improvement)}</dd>
              </div>
            </div>
            <div>
              <dt className="text-muted">Bootstrap</dt>
              <dd>
                {Object.entries(rule.bootstrap)
                  .map(([k, v]) => `${humanize(k)}: ${fmtAny(v)}`)
                  .join(" · ")}
              </dd>
            </div>
            <div>
              <dt className="text-muted">Secondary constraints</dt>
              <dd>
                <ul className="list-disc pl-4">
                  {Object.entries(rule.secondary_constraints).map(([k, v]) => (
                    <li key={k}>
                      {k.replace(/_/g, " ")}: <span className="tnum">{fmtAny(v)}</span>
                    </li>
                  ))}
                </ul>
              </dd>
            </div>
          </dl>
        </section>
      </div>

      <section aria-labelledby="am-h" className="mt-4">
        <h3 id="am-h" className="mb-1 text-sm font-semibold">
          Amendments ({pr.amendments.length})
        </h3>
        {pr.amendments.length ? (
          <ol className="space-y-2">
            {pr.amendments.map((a, i) => (
              <li key={i} className="rounded-md border border-warn/40 bg-warn/5 p-2 text-xs">
                <div className="flex flex-wrap gap-2">
                  <b>
                    {a.from} → {a.to}
                  </b>
                  <span className="text-muted">{fmtTime(a.utc)}</span>
                </div>
                <p className="mt-1">
                  <span className="text-muted">Change: </span>
                  {a.change}
                </p>
                <p className="mt-0.5 text-ink2">
                  <span className="text-muted">Reason: </span>
                  {a.reason}
                </p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-xs text-muted">No amendments.</p>
        )}
      </section>
    </Panel>
  );
}

/* ---------------------------------------------------------------- budget */

function CampaignBudget({ c }: { c: Campaign }) {
  const b = c.budget ?? ({} as Campaign["budget"]);
  const u = c.consumed ?? ({} as Campaign["consumed"]);
  const sb = b.sandbox ?? {};
  return (
    <article className="space-y-2 rounded-md border border-line bg-panel2 p-3 text-xs">
      <header className="flex flex-wrap items-center gap-2">
        <b className="font-mono">{c.id}</b>
        <Verdict v={c.status} />
        <span className="text-muted">
          {c.mode} · selector {c.selector}
        </span>
        <span className="ml-auto text-muted">updated {fmtTime(c.updated)}</span>
      </header>
      {c.stop_reason && <p className="text-warn">stop reason: {c.stop_reason}</p>}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Meter label="Tasks" used={u.tasks ?? 0} max={b.max_tasks} />
        <Meter label="Wall clock" used={u.wall_s ?? 0} max={b.max_wall_s} unit=" s" note="accumulated when a run segment ends" />
        <Meter
          label="Sandbox runs"
          used={u.sandbox_runs ?? 0}
          note={`no count cap; per run ≤ ${fmtAny(sb.cpu_s)} s CPU, ${sb.mem_bytes ? (sb.mem_bytes / 2 ** 30).toFixed(1) + " GiB" : "—"} memory, ${fmtAny(sb.wall_s)} s wall`}
        />
        {b.max_llm_tokens === 0 ? (
          <div className="text-xs">
            <div className="flex justify-between">
              <span className="text-ink2">LLM tokens</span>
              <span className="tnum">{fmtAny(u.llm_tokens)}</span>
            </div>
            <p className="mt-0.5 text-[11px] text-muted">LLM: none configured (0 tokens){c.config?.llm_status ? ` — ${c.config.llm_status}` : ""}</p>
          </div>
        ) : (
          <Meter label="LLM tokens" used={u.llm_tokens ?? 0} max={b.max_llm_tokens} />
        )}
      </div>
      {c.config?.generator && <p className="text-muted">generator {c.config.generator}</p>}
    </article>
  );
}

/* ---------------------------------------------------------------- controls */

type Msg = { ok: boolean; text: string } | undefined;

function Controls({ lab, ov, superseded, onChanged }: { lab: string; ov: Overview; superseded: boolean; onChanged: (newLab?: string) => void }) {
  const [stopReason, setStopReason] = useState("stopped from dashboard");
  const [confirmResume, setConfirmResume] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [rbReason, setRbReason] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<Record<string, Msg>>({});
  const lastCamp = ov.campaigns[ov.campaigns.length - 1];
  const [run, setRun] = useState({ lab, campaign: "", mode: "smoke", selector: "guided", tasks: 1, wall_s: 600 });
  const [jobId, setJobId] = useState<string | null>(null);
  useEffect(() => {
    setRun((r) => ({ ...r, lab, campaign: r.campaign || "" }));
    setMsg({});
    setConfirmResume(false);
  }, [lab]);
  const job = useJob(jobId, () => onChanged(run.lab !== lab ? run.lab : undefined));
  const jobActive = job?.status === "queued" || job?.status === "running";

  const activeMeta = ov.versions.find((v) => v.version === ov.active?.version);
  const canRollback = !!ov.active && activeMeta?.parent_version !== null && activeMeta?.parent_version !== undefined;
  const existing = ov.campaigns.find((c) => c.id === run.campaign);
  const runningHere = ov.campaigns.filter((c) => c.status === "running");

  const act = async (key: string, fn: () => Promise<unknown>, ok: (r: unknown) => string) => {
    setBusy(key);
    setMsg((m) => ({ ...m, [key]: undefined }));
    try {
      const r = await fn();
      setMsg((m) => ({ ...m, [key]: { ok: true, text: ok(r) } }));
      onChanged();
    } catch (e) {
      setMsg((m) => ({ ...m, [key]: { ok: false, text: errorMessage(e) } }));
    } finally {
      setBusy(null);
    }
  };

  const note = (k: string) =>
    msg[k] && (
      <p role="status" className={`break-words text-xs ${msg[k]!.ok ? "text-up" : "text-down"}`}>
        {msg[k]!.text}
      </p>
    );

  const submitRun = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!LAB_RE.test(run.lab)) {
      setMsg((m) => ({ ...m, run: { ok: false, text: "Lab name must match [a-z0-9_]+" } }));
      return;
    }
    if (!/^[a-z0-9_-]{2,40}$/.test(run.campaign)) {
      setMsg((m) => ({ ...m, run: { ok: false, text: "Campaign id must be 2–40 chars of [a-z0-9_-]" } }));
      return;
    }
    setMsg((m) => ({ ...m, run: undefined }));
    try {
      const j = await apiPost<Job>(`/api/research/${run.lab}/run`, {
        campaign: run.campaign,
        mode: run.mode,
        selector: run.selector,
        tasks: run.tasks,
        wall_s: run.wall_s,
      });
      setJobId(j.id);
      setMsg((m) => ({ ...m, run: { ok: true, text: `Job ${j.id} submitted.` } }));
    } catch (err) {
      setMsg((m) => ({ ...m, run: { ok: false, text: errorMessage(err) } }));
    }
  };

  const disabled = superseded;
  return (
    <div className="space-y-4">
      {superseded && (
        <p className="rounded-md border border-warn/50 bg-warn/10 px-3 py-2 text-xs text-warn">
          Superseded run — kept for audit. Controls are disabled for this lab.
        </p>
      )}
      <div
        role="status"
        className={`rounded-md border px-3 py-2 text-xs ${ov.stop_requested ? "border-warn/60 bg-warn/10 text-warn" : "border-line bg-panel2 text-ink2"}`}
      >
        {ov.stop_requested
          ? "STOP requested — the supervisor halts before the next stage and will not continue until a human resumes."
          : "No stop requested."}
        {runningHere.length > 0 && ` Campaign status "running": ${runningHere.map((c) => c.id).join(", ")}.`}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <fieldset className="space-y-2 rounded-md border border-line p-3" disabled={disabled}>
          <legend className="px-1 text-xs font-semibold">Stop</legend>
          <label className="field">
            Reason
            <input className="input" value={stopReason} onChange={(e) => setStopReason(e.target.value)} />
          </label>
          <button
            className="btn btn-danger"
            disabled={disabled || ov.stop_requested || busy !== null}
            onClick={() => act("stop", () => apiPost(`/api/research/${lab}/stop`, { reason: stopReason || "stopped from dashboard" }), () => "Stop requested.")}
          >
            ■ Stop
          </button>
          {note("stop")}
        </fieldset>

        <fieldset className="space-y-2 rounded-md border border-line p-3" disabled={disabled}>
          <legend className="px-1 text-xs font-semibold">Resume</legend>
          <label className="flex items-start gap-2 text-xs text-ink2">
            <input type="checkbox" className="mt-0.5" checked={confirmResume} onChange={(e) => setConfirmResume(e.target.checked)} />
            I confirm restarting after an explicit stop
          </label>
          <button
            className="btn"
            disabled={disabled || !ov.stop_requested || !confirmResume || busy !== null}
            onClick={() =>
              act("resume", () => apiPost(`/api/research/${lab}/resume`, { confirm: confirmResume }), () => {
                setConfirmResume(false);
                return "Stop flag cleared. Run the campaign again (same id) to continue it.";
              })
            }
          >
            ▶ Resume
          </button>
          <p className="text-[11px] text-muted">Resume only clears the stop flag; it does not start work by itself.</p>
          {note("resume")}
        </fieldset>

        <fieldset className="space-y-2 rounded-md border border-line p-3" disabled={disabled}>
          <legend className="px-1 text-xs font-semibold">Roll back champion</legend>
          <label className="field">
            Reviewer (required)
            <input className="input" value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="your name" maxLength={80} />
          </label>
          <label className="field">
            Reason
            <input className="input" value={rbReason} onChange={(e) => setRbReason(e.target.value)} />
          </label>
          <button
            className="btn border-warn/60 text-warn"
            disabled={disabled || !reviewer.trim() || !canRollback || busy !== null}
            onClick={() =>
              act(
                "rollback",
                () => apiPost<{ active: number; from: number }>(`/api/research/${lab}/rollback`, { reviewer: reviewer.trim(), reason: rbReason }),
                (r) => {
                  const x = r as { active?: number; from?: number };
                  return `Rolled back v${x.from} → v${x.active}.`;
                },
              )
            }
          >
            ↶ Roll back
          </button>
          {!canRollback && <p className="text-[11px] text-muted">Active version v{fmtAny(ov.active?.version)} has no parent to roll back to.</p>}
          {note("rollback")}
        </fieldset>
      </div>

      <form onSubmit={submitRun} aria-label="Run bounded campaign" className="space-y-3 rounded-md border border-line p-3">
        <fieldset disabled={disabled} className="space-y-3">
          <legend className="text-xs font-semibold">Run bounded campaign</legend>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <label className="field">
              Lab
              <input className="input" value={run.lab} onChange={(e) => setRun({ ...run, lab: e.target.value.trim() })} pattern="[a-z0-9_]+" required />
            </label>
            <label className="field">
              Campaign id
              <input
                className="input"
                value={run.campaign}
                onChange={(e) => setRun({ ...run, campaign: e.target.value.trim() })}
                placeholder={lastCamp ? `e.g. ${lastCamp.id}` : "e.g. c1"}
                pattern="[a-z0-9_\-]{2,40}"
                required
              />
            </label>
            <label className="field">
              Mode
              <select className="input" value={run.mode} onChange={(e) => setRun({ ...run, mode: e.target.value })}>
                <option value="smoke">smoke</option>
                <option value="research">research</option>
                <option value="autonomous-experimental">autonomous-experimental</option>
              </select>
            </label>
            <label className="field">
              Selector
              <select className="input" value={run.selector} onChange={(e) => setRun({ ...run, selector: e.target.value })}>
                <option value="guided">guided</option>
                <option value="random">random</option>
              </select>
            </label>
            <label className="field">
              Tasks (1–60)
              <input className="input tnum" type="number" min={1} max={60} value={run.tasks} onChange={(e) => setRun({ ...run, tasks: Number(e.target.value) })} />
            </label>
            <label className="field">
              Wall budget s (60–14400)
              <input className="input tnum" type="number" min={60} max={14400} step={60} value={run.wall_s} onChange={(e) => setRun({ ...run, wall_s: Number(e.target.value) })} />
            </label>
          </div>
          <p className="text-[11px] text-ink2">
            <b className="text-warn">autonomous-experimental</b> may activate a new experimental champion automatically; main branch and deployments are never touched.
            smoke and research never auto-activate. Requests are clipped to the trusted policy caps.
          </p>
          {run.lab !== lab && LAB_RE.test(run.lab) && <p className="text-[11px] text-warn">This will run in lab “{run.lab}” (created if it does not exist).</p>}
          {existing && run.lab === lab && (
            <p className="text-[11px] text-warn">
              Campaign “{existing.id}” already exists ({existing.mode}, {existing.selector}, max {existing.budget.max_tasks} tasks): running it continues that campaign with its
              original mode, selector and budget — the values above are ignored by the backend.
            </p>
          )}
          {ov.stop_requested && run.lab === lab && <p className="text-[11px] text-warn">A stop is requested in this lab: the run will halt immediately until you resume.</p>}
          <button className="btn btn-primary" type="submit" disabled={disabled || jobActive}>
            ▶ Run campaign
          </button>
        </fieldset>
        {note("run")}
        <JobProgress job={job} label="Research campaign" />
        {job?.status === "finished" && job.result != null && (
          <details className="text-xs">
            <summary className="cursor-pointer text-ink2">Job result</summary>
            <JsonTable value={job.result} />
          </details>
        )}
      </form>
    </div>
  );
}

/* ---------------------------------------------------------------- page */

const SECTIONS = [
  ["protocol", "Protocol"],
  ["data", "Data"],
  ["tasks", "Experiments"],
  ["lineage", "Lineage"],
  ["hypotheses", "Hypotheses"],
  ["budget", "Budget & controls"],
  ["journal", "Journal"],
  ["final", "Final"],
  ["calibration", "Simulator realism"],
] as const;

export default function ResearchPage() {
  const labs = usePoll<LabSummary[]>("/api/research/labs", 10000);
  const [lab, setLab] = useState<string>("");
  const [rev, setRev] = useState(0);
  const [openTask, setOpenTask] = useState<string | null>(null);

  // initial lab: ?lab= query param, else arm_guided, else first non-superseded lab
  useEffect(() => {
    if (lab || !labs.data) return;
    const q = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("lab") : null;
    const names = labs.data.map((l) => l.name);
    const pick =
      (q && names.includes(q) && q) ||
      (names.includes("arm_guided") ? "arm_guided" : labs.data.find((l) => !l.superseded)?.name ?? names[0] ?? "");
    if (pick) setLab(pick);
  }, [labs.data, lab]);

  const selectLab = useCallback((name: string) => {
    setLab(name);
    setOpenTask(null);
    try {
      const u = new URL(window.location.href);
      u.searchParams.set("lab", name);
      window.history.replaceState(null, "", u.toString());
    } catch {
      /* ignore */
    }
  }, []);

  const ov = usePoll<Overview>(lab ? `/api/research/${lab}/overview` : null, 5000);
  useRefreshOn(rev, ov.refresh);
  const onChanged = useCallback(
    (newLab?: string) => {
      labs.refresh();
      setRev((r) => r + 1);
      if (newLab) selectLab(newLab);
    },
    [labs, selectLab],
  );
  const closeTask = useCallback(() => setOpenTask(null), []);

  const cur = labs.data?.find((l) => l.name === lab);
  const superseded = !!cur?.superseded;
  const o = ov.data && ov.data.name === lab ? ov.data : undefined;

  return (
    <div className="space-y-4">
      <PageTitle title="Research lab">
        <label className="field !flex-row items-center gap-2">
          <span>Lab</span>
          <select className="input w-auto max-w-[260px]" value={lab} onChange={(e) => selectLab(e.target.value)} aria-label="Select research lab">
            {!lab && <option value="">—</option>}
            {(labs.data ?? []).map((l) => (
              <option key={l.name} value={l.name}>
                {l.name}
                {l.superseded ? " — superseded run, kept for audit" : ""}
              </option>
            ))}
          </select>
        </label>
      </PageTitle>

      <ErrorNote error={labs.error} what="labs" />
      {labs.data && labs.data.length === 0 && (
        <EmptyState title="No research labs yet">Run a bounded campaign (CLI or API) to create one.</EmptyState>
      )}

      {labs.data && labs.data.length > 0 && (
        <section aria-label="Labs" className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
          {labs.data.map((l) => {
            const sel = l.name === lab;
            const last = l.campaigns[l.campaigns.length - 1];
            return (
              <button
                key={l.name}
                onClick={() => selectLab(l.name)}
                aria-pressed={sel}
                className={`min-w-[180px] shrink-0 rounded-md border p-2 text-left text-xs ${
                  sel ? "border-accent bg-accent/10" : l.superseded ? "border-dashed border-line2 bg-panel opacity-70" : "border-line bg-panel hover:bg-panel2"
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <b className={l.superseded ? "text-ink2 line-through decoration-muted" : ""}>{l.name}</b>
                  {l.stop_requested && <span className="text-warn" title="stop requested">■</span>}
                </div>
                {l.superseded && <div className="text-[10px] font-semibold uppercase tracking-wider text-warn">superseded run — kept for audit</div>}
                <div className="text-muted">
                  active v{fmtAny(l.active?.version)} · {l.campaigns.length} campaign{l.campaigns.length === 1 ? "" : "s"}
                </div>
                {last && (
                  <div className="mt-0.5">
                    <Verdict v={last.status} />
                  </div>
                )}
              </button>
            );
          })}
        </section>
      )}

      {superseded && (
        <p className="rounded-md border border-warn/60 bg-warn/10 px-3 py-2 text-sm text-warn" role="note">
          <b>{lab}</b> is a superseded run — kept for audit. Its results are not part of the current comparison.
        </p>
      )}

      <nav aria-label="Sections" className="-mx-1 flex gap-1 overflow-x-auto px-1 text-xs">
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#${id}`} className="whitespace-nowrap rounded border border-line px-2 py-1 text-ink2 hover:bg-panel2 hover:text-ink">
            {label}
          </a>
        ))}
      </nav>

      <ErrorNote error={ov.error} what={`overview of ${lab}`} />

      {o && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
            <Stat label="Active champion" value={o.active ? `v${o.active.version}` : "—"} sub={o.active?.candidate_id} />
            <Stat label="Tasks" value={Object.values(o.tasks).reduce((a, b) => a + b, 0)} sub={Object.entries(o.tasks).map(([k, v]) => `${k} ${v}`).join(" · ")} />
            <Stat label="Hypotheses" value={Object.values(o.hypotheses).reduce((a, b) => a + b, 0)} sub={Object.entries(o.hypotheses).map(([k, v]) => `${k} ${v}`).join(" · ")} />
            <Stat label="Validation trials" value={o.trials.validation} sub={`development ${o.trials.development}`} />
            <Stat label="Journal" value={o.journal.ok ? "intact" : "BROKEN"} sub={`${fmtAny(o.journal.entries)} entries`} tone={o.journal.ok ? undefined : "down"} />
            <Stat label="Stop flag" value={o.stop_requested ? "STOP" : "clear"} tone={o.stop_requested ? "warn" : undefined} />
          </div>
          <QuestionsProtocol ov={o} />
        </>
      )}

      <DataCoverage rev={rev} />

      {lab && <TasksTable lab={lab} rev={rev} onOpen={setOpenTask} selected={openTask} />}

      {lab && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <LineagePanel lab={lab} rev={rev} />
          <HypothesesPanel lab={lab} rev={rev} />
        </div>
      )}

      {o && (
        <Panel id="budget" title="Budget & controls" subtitle="Every control calls the backend and then re-reads the persisted lab state.">
          <div className="space-y-4">
            {o.campaigns.length ? (
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {o.campaigns
                  .slice()
                  .reverse()
                  .map((c) => (
                    <CampaignBudget key={c.id} c={c} />
                  ))}
              </div>
            ) : (
              <EmptyState title="No campaigns in this lab" />
            )}
            <Controls lab={lab} ov={o} superseded={superseded} onChanged={onChanged} />
          </div>
        </Panel>
      )}

      {lab && <JournalPanel lab={lab} rev={rev} />}
      <FinalPanel rev={rev} />
      <CalibrationPanel rev={rev} />

      {openTask && lab && <TaskDrawer lab={lab} id={openTask} onClose={closeTask} />}
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "down" | "warn" }) {
  return (
    <div className="min-w-0 rounded-md border border-line bg-panel px-3 py-2">
      <div className="truncate text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`truncate text-lg font-semibold tnum ${tone === "down" ? "text-down" : tone === "warn" ? "text-warn" : "text-ink"}`}>{value}</div>
      {sub && (
        <div className="truncate text-[11px] text-muted" title={typeof sub === "string" ? sub : undefined}>
          {sub}
        </div>
      )}
    </div>
  );
}
