"use client";
import { useState } from "react";
import { apiPost, errorMessage } from "@/lib/api";
import { useJob, usePoll } from "@/lib/hooks";
import { fmtTime } from "@/lib/format";
import type { CatalogueItem, Job, Proposal } from "@/lib/types";
import { DiffView } from "./labs";
import { EmptyState, ErrorNote, JobProgress, JsonTable, Panel, StatusPill } from "./ui";

export function ProposalsSection() {
  const cat = usePoll<CatalogueItem[]>("/api/proposals/catalogue", 0);
  const props = usePoll<Proposal[]>("/api/proposals", 5000);
  const [key, setKey] = useState<string>("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [err, setErr] = useState<string>();
  const [open, setOpen] = useState<string | null>(null);
  const job = useJob(jobId, () => props.refresh());

  const generate = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(undefined);
    try {
      const j = await apiPost<Job>("/api/proposals/generate", { proposal_key: key || null });
      setJobId(j.id);
    } catch (e) {
      setErr(errorMessage(e));
    }
  };
  const selected = cat.data?.find((c) => c.key === key);
  const list = Array.isArray(props.data) ? props.data : [];

  return (
    <Panel
      id="proposals"
      title="Code proposals · Level 4 (human approval gate)"
      subtitle="The engineer agent proposes source changes on an isolated branch; automated gates run in a sandbox; a human records the decision."
    >
      <div role="note" className="mb-4 rounded-md border border-warn/50 bg-warn/10 px-3 py-2 text-xs text-warn">
        Approval records a decision; merging into main is a manual human step — nothing is auto-merged or deployed.
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <div className="space-y-3">
          <form onSubmit={generate} className="space-y-2" aria-label="Generate code proposal">
            <label className="field">
              Proposal from catalogue
              <select className="input" value={key} onChange={(e) => setKey(e.target.value)}>
                <option value="">next untried (engineer chooses)</option>
                {(cat.data ?? []).map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.title}
                  </option>
                ))}
              </select>
            </label>
            {selected && (
              <div className="rounded border border-line bg-panel2 p-2 text-xs">
                <p className="text-ink2">{selected.rationale}</p>
                <p className="mt-1 text-muted">target: <code>{selected.target_file}</code></p>
              </div>
            )}
            <button className="btn btn-primary w-full" type="submit" disabled={job?.status === "running" || job?.status === "queued"}>
              Generate proposal &amp; run gates
            </button>
            {err && <p role="alert" className="text-xs text-down">{err}</p>}
          </form>
          {cat.error && <ErrorNote error={cat.error} what="catalogue unavailable" />}
          <JobProgress job={job} label="Proposal" />
        </div>
        <div className="min-w-0 space-y-2">
          <ErrorNote error={props.error} what="proposals" />
          {list.length === 0 ? (
            <EmptyState title="No code proposals yet">Generate one from the catalogue to see its diff, gate results and approval form.</EmptyState>
          ) : (
            <ul className="space-y-2">
              {list.map((p) => (
                <li key={p.id} className="rounded-md border border-line bg-panel2">
                  <button
                    className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left"
                    aria-expanded={open === p.id}
                    onClick={() => setOpen(open === p.id ? null : p.id)}
                  >
                    <span aria-hidden className="text-muted">{open === p.id ? "▾" : "▸"}</span>
                    <span className="min-w-0 flex-1 font-medium">{p.title}</span>
                    <StatusPill status={p.status} />
                    <span className="text-[11px] text-muted">{fmtTime(p.created)}</span>
                  </button>
                  {open === p.id && <ProposalDetail p={p} onDecided={props.refresh} />}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Panel>
  );
}

function ProposalDetail({ p, onDecided }: { p: Proposal; onDecided: () => void }) {
  const r = p.report ?? {};
  const gates = r.gates ?? [];
  const [reviewer, setReviewer] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string }>();
  const decide = async (decision: "approve" | "reject") => {
    if (!reviewer.trim()) {
      setMsg({ ok: false, text: "Reviewer name is required." });
      return;
    }
    setBusy(true);
    setMsg(undefined);
    try {
      await apiPost(`/api/proposals/${encodeURIComponent(p.id)}/decision`, { decision, reviewer: reviewer.trim(), comment });
      setMsg({ ok: true, text: `Decision "${decision}" recorded by ${reviewer.trim()}.` });
      onDecided();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-4 border-t border-line px-3 py-3 text-sm">
      <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[auto_minmax(0,1fr)]">
        <dt className="text-muted">ID</dt><dd><code>{p.id}</code></dd>
        <dt className="text-muted">Author</dt><dd>{p.author}</dd>
        <dt className="text-muted">Branch</dt><dd><code>{p.branch}</code></dd>
        <dt className="text-muted">Target files</dt><dd className="break-all">{(p.target_files ?? []).map((f) => <code key={f} className="mr-2">{f}</code>)}</dd>
      </dl>
      {r.summary && <p className="text-ink2">{r.summary}</p>}
      {r.rationale && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-ink2">Rationale</h4>
          <p className="mt-1 whitespace-pre-wrap text-xs text-ink2">{r.rationale}</p>
        </div>
      )}
      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-ink2">Gates ({gates.filter((g) => g.passed).length}/{gates.length} passed)</h4>
        {gates.length ? (
          <ul className="space-y-1 text-xs">
            {gates.map((g) => (
              <li key={g.name} className="flex flex-wrap items-start gap-2 rounded border border-line px-2 py-1">
                <span className={`font-bold ${g.passed ? "text-up" : "text-down"}`} aria-hidden>{g.passed ? "✓" : "✗"}</span>
                <span className="font-medium">{g.name}</span>
                <span className="sr-only">{g.passed ? "passed" : "failed"}</span>
                {g.duration_s !== undefined && <span className="text-muted tnum">{g.duration_s.toFixed(1)} s</span>}
                {g.detail !== undefined && g.detail !== null && g.detail !== "" && (
                  <span className="w-full break-words text-[11px] text-muted">{typeof g.detail === "string" ? g.detail : JSON.stringify(g.detail)}</span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted">{p.status === "gates_running" ? "Gates running…" : "No gate results."}</p>
        )}
      </div>
      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-ink2">Diff</h4>
        <DiffView diff={r.diff} />
      </div>
      {(["sandbox", "frozen_eval", "benchmark"] as const).map((k) =>
        r[k] ? (
          <details key={k}>
            <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-ink2">{k.replace("_", " ")}</summary>
            <div className="mt-2 text-xs"><JsonTable value={r[k]} /></div>
          </details>
        ) : null,
      )}
      {p.decision ? (
        <div className="rounded border border-line bg-panel p-2 text-xs">
          Decision recorded: <StatusPill status={p.decision.decision === "approve" ? "approved" : p.decision.decision === "reject" ? "rejected" : p.decision.decision} /> by{" "}
          <b>{p.decision.reviewer}</b> at {fmtTime(p.decision.ts)}
          {p.decision.comment && <p className="mt-1 text-ink2">“{p.decision.comment}”</p>}
        </div>
      ) : p.status === "awaiting_approval" ? (
        <form className="space-y-2 rounded border border-line bg-panel p-3" onSubmit={(e) => e.preventDefault()} aria-label="Record decision">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <label className="field">
              Reviewer name (required)
              <input className="input" required value={reviewer} onChange={(e) => setReviewer(e.target.value)} autoComplete="name" />
            </label>
            <label className="field">
              Comment
              <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn border-up/60 text-up" disabled={busy || !reviewer.trim()} onClick={() => decide("approve")}>✓ Approve</button>
            <button type="button" className="btn border-down/60 text-down" disabled={busy || !reviewer.trim()} onClick={() => decide("reject")}>✗ Reject</button>
          </div>
          <p className="text-[11px] text-muted">Approval records a decision; merging into main is a manual human step — nothing is auto-merged or deployed.</p>
          {msg && <p role="status" className={`text-xs ${msg.ok ? "text-up" : "text-down"}`}>{msg.text}</p>}
        </form>
      ) : (
        <p className="text-xs text-muted">No decision possible in status “{p.status.replace(/_/g, " ")}”.</p>
      )}
    </div>
  );
}
