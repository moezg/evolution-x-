"use client";
import { useEffect, useState } from "react";
import { CIStrip } from "@/components/labs";
import { EmptyState, ErrorNote, JobProgress, JsonTable, PageTitle, Panel, ProvenanceBadge } from "@/components/ui";
import { SCALES } from "@/components/sim";
import { apiPost, apiText, errorMessage } from "@/lib/api";
import { useJob, usePoll } from "@/lib/hooks";
import { fmtAny, fmtTime, hms, humanize } from "@/lib/format";
import type { Experiment, ExperimentListItem, ExperimentSummaryMetric, Job, Scenario, StatBlock } from "@/lib/types";

const METRIC_LABELS: Record<string, string> = {
  "shock.min_after_pct": "Min price after shock (%)",
  "shock.ret_window_pct": "Return over shock window (%)",
  "shock.ret_end_pct": "Return at end of run (%)",
  "shock.realized_vol_bps": "Realized vol in window (bps)",
  "shock.spread_bps_window": "Spread in window (bps)",
  "shock.liquidations_window": "Liquidations in window",
  max_drawdown_pct: "Max drawdown (%)",
  liquidations: "Liquidations (run)",
  spread_bps_median: "Median spread (bps)",
  volume_btc: "Volume (BTC)",
  influence_events: "Influence events",
};

function LaunchForm({ onDone }: { onDone: (j: Job) => void }) {
  const scen = usePoll<Scenario[]>("/api/scenarios", 0);
  const [f, setF] = useState({ scenario: "btc_drop_5pct", replicates: 6, base_seed: 1000, duration_s: 1800, scale: 1 });
  const [jobId, setJobId] = useState<string | null>(null);
  const [err, setErr] = useState<string>();
  const job = useJob(jobId, onDone);
  const s = scen.data?.find((x) => x.name === f.scenario);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(undefined);
    try {
      const j = await apiPost<Job>("/api/experiments", f);
      setJobId(j.id);
    } catch (e) {
      setErr(errorMessage(e));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Launch experiment">
      <div className="grid grid-cols-2 gap-3">
        <label className="field col-span-2">
          Scenario (treatment)
          <select className="input" value={f.scenario} onChange={(e) => setF({ ...f, scenario: e.target.value })}>
            {(scen.data ?? []).map((x) => <option key={x.name}>{x.name}</option>)}
          </select>
        </label>
        <label className="field">
          Replicates (paired seeds)
          <input className="input tnum" type="number" min={2} max={64} value={f.replicates} onChange={(e) => setF({ ...f, replicates: Number(e.target.value) })} />
        </label>
        <label className="field">
          Base seed
          <input className="input tnum" type="number" value={f.base_seed} onChange={(e) => setF({ ...f, base_seed: Number(e.target.value) })} />
        </label>
        <label className="field">
          Duration (s)
          <input className="input tnum" type="number" min={300} max={14400} step={60} value={f.duration_s} onChange={(e) => setF({ ...f, duration_s: Number(e.target.value) })} />
        </label>
        <label className="field">
          Population
          <select className="input" value={f.scale} onChange={(e) => setF({ ...f, scale: Number(e.target.value) })}>
            {SCALES.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
          </select>
        </label>
      </div>
      {s && (
        <div className="rounded border border-line bg-panel2 p-2 text-xs">
          <p className="text-ink2">{s.description}</p>
          {s.shocks.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-muted tnum">
              {s.shocks.map((sh, i) => <li key={i}>• {sh.type} at T+{hms(sh.at_s)} for {sh.duration_s}s, magnitude {sh.magnitude}{sh.note ? ` — ${sh.note}` : ""}</li>)}
            </ul>
          )}
          <p className="mt-1 text-muted">Each replicate runs treatment and a no-intervention baseline on the same seed (common random numbers).</p>
        </div>
      )}
      <button className="btn btn-primary" type="submit" disabled={job?.status === "running" || job?.status === "queued"}>▶ Launch replicates</button>
      {err && <p role="alert" className="text-xs text-down">{err}</p>}
      <JobProgress job={job} label="Experiment" />
    </form>
  );
}

function MetricCard({ name, m }: { name: string; m: ExperimentSummaryMetric }) {
  const pd = m.paired_diff;
  const sig = pd && pd.t_lo !== undefined && pd.t_hi !== undefined && (pd.t_lo > 0 || pd.t_hi < 0);
  return (
    <article className="rounded-md border border-line bg-panel2 p-3">
      <header className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{METRIC_LABELS[name] ?? humanize(name)}</h3>
        <code className="text-[10px] text-muted">{name}</code>
      </header>
      <CIStrip
        label={`${name}: treatment vs baseline replicate values with mean and 95% CI`}
        rows={[
          { label: "treatment", color: "#d95926", values: m.treatment_values, stat: m.treatment },
          { label: "baseline", color: "#3987e5", values: m.baseline_values, stat: m.baseline },
        ]}
      />
      {pd && (
        <>
          <CIStrip zero label={`${name}: paired difference with 95% CI`} rows={[{ label: "paired Δ", color: "#c3c2b7", stat: pd }]} />
          <p className="text-[11px] text-ink2 tnum">
            Δ mean {fmtAny(pd.mean)} · 95% CI [{fmtAny(pd.t_lo)}, {fmtAny(pd.t_hi)}] · frac&gt;0 {fmtAny(pd.frac_positive)} · d<sub>z</sub> {fmtAny(pd.effect_size_dz)} ·{" "}
            <span className={sig ? "font-semibold text-warn" : "text-muted"}>{sig ? "CI excludes 0" : "CI includes 0"}</span>
          </p>
        </>
      )}
    </article>
  );
}

function StatLine({ label, s }: { label: string; s?: StatBlock }) {
  if (!s) return null;
  return <span className="tnum">{label}: {fmtAny(s.mean)} [{fmtAny(s.t_lo)}, {fmtAny(s.t_hi)}]</span>;
}

function ExperimentDetail({ id }: { id: string }) {
  const ex = usePoll<Experiment>(`/api/experiments/${encodeURIComponent(id)}`, 0);
  const [dlErr, setDlErr] = useState<string>();
  const exportMd = async () => {
    setDlErr(undefined);
    try {
      const md = await apiText(`/api/experiments/${encodeURIComponent(id)}/report.md`);
      const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${id}-report.md`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setDlErr(errorMessage(e));
    }
  };
  const e = ex.data;
  const realism = e?.realism as { treatment?: StatBlock; baseline?: StatBlock } | undefined;
  return (
    <Panel
      title={<span className="flex flex-wrap items-center gap-2">Experiment {id} <ProvenanceBadge label={e?.data_label} /></span>}
      subtitle={e?.description}
      actions={<button className="btn" onClick={exportMd}>⤓ Export report (.md)</button>}
    >
      <ErrorNote error={ex.error} what="experiment" />
      {dlErr && <p role="alert" className="mb-2 text-xs text-down">{dlErr}</p>}
      {!e ? (
        <EmptyState title="Loading…" />
      ) : (
        <div className="space-y-4">
          {e.caveat && (
            <p role="note" className="rounded-md border border-warn/50 bg-warn/10 px-3 py-2 text-xs text-warn">⚠ {e.caveat}</p>
          )}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
            <div><dt className="text-muted">Scenario</dt><dd>{e.scenario}</dd></div>
            <div><dt className="text-muted">Design</dt><dd>{typeof e.design === "string" ? e.design : JSON.stringify(e.design)}</dd></div>
            <div><dt className="text-muted">Replicates</dt><dd className="tnum">{e.replicates} (seeds {e.seeds?.join(", ")})</dd></div>
            <div><dt className="text-muted">Agents · duration</dt><dd className="tnum">{e.n_agents} · {hms(e.duration_s)}{e.shock_at_s ? ` · shock at T+${hms(e.shock_at_s)}` : ""}</dd></div>
            <div className="col-span-2 sm:col-span-4"><dt className="text-muted">Reproduce</dt><dd><code className="break-all text-ink2">{typeof e.reproduce === "string" ? e.reproduce : JSON.stringify(e.reproduce)}</code></dd></div>
            {realism?.treatment && (
              <div className="col-span-2 sm:col-span-4"><dt className="text-muted">Realism score (stylized-facts fraction inside bands)</dt>
                <dd className="flex flex-wrap gap-x-4"><StatLine label="treatment" s={realism.treatment} /><StatLine label="baseline" s={realism.baseline} /></dd></div>
            )}
          </dl>
          <p className="text-[11px] text-muted">
            Dots = individual replicates; ◆ = mean; bars = 95% t-interval. Treatment and baseline share seeds, so the paired Δ row is the primary comparison.
          </p>
          {e.summary && Object.keys(e.summary).length ? (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {Object.entries(e.summary).map(([k, m]) => <MetricCard key={k} name={k} m={m} />)}
            </div>
          ) : (
            <EmptyState title="No summary metrics" />
          )}
          {realism && !realism.treatment && <JsonTable value={realism} />}
        </div>
      )}
    </Panel>
  );
}

export default function ScenariosPage() {
  const list = usePoll<ExperimentListItem[]>("/api/experiments", 10000);
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => {
    if (!sel && list.data?.length) setSel(list.data[0].experiment_id);
  }, [list.data, sel]);
  return (
    <div className="space-y-4">
      <PageTitle title="Scenario lab" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <Panel title="Configure & launch" subtitle="Run paired treatment/baseline replicates of a scenario.">
          <LaunchForm onDone={(j) => {
            list.refresh();
            const r = j.result as { experiment_id?: string } | null;
            if (r?.experiment_id) setSel(r.experiment_id);
          }} />
        </Panel>
        <Panel title="Experiments">
          <ErrorNote error={list.error} what="experiments" />
          {list.data?.length ? (
            <div className="max-h-80 overflow-auto">
              <table className="data">
                <thead><tr><th scope="col">Experiment</th><th scope="col">Scenario</th><th scope="col" className="num">Reps</th><th scope="col" className="num">Agents</th><th scope="col" className="num">Duration</th><th scope="col">Data</th><th scope="col">Created</th></tr></thead>
                <tbody>
                  {list.data.map((x) => (
                    <tr key={x.experiment_id} className={sel === x.experiment_id ? "!bg-accent/15" : ""}>
                      <td><button className="text-left text-accent hover:underline" aria-pressed={sel === x.experiment_id} onClick={() => setSel(x.experiment_id)}>{x.experiment_id}</button></td>
                      <td>{x.scenario}</td>
                      <td className="num">{x.replicates}</td>
                      <td className="num">{x.n_agents}</td>
                      <td className="num">{hms(x.duration_s)}</td>
                      <td><ProvenanceBadge label={x.data_label} /></td>
                      <td className="text-muted">{fmtTime(x.created_utc)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No experiments yet">Launch replicates to compare a scenario against its paired baseline.</EmptyState>
          )}
        </Panel>
      </div>
      {sel && <ExperimentDetail key={sel} id={sel} />}
    </div>
  );
}
