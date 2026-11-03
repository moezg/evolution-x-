"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { fmtAny, humanize } from "@/lib/format";
import type { Job } from "@/lib/types";

export function Panel({
  title,
  actions,
  children,
  className = "",
  subtitle,
  id,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  subtitle?: ReactNode;
  id?: string;
}) {
  const hid = id ? `${id}-h` : undefined;
  return (
    <section
      id={id}
      aria-labelledby={hid}
      className={`min-w-0 rounded-lg border border-line bg-panel p-3 sm:p-4 ${className}`}
    >
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            {title && (
              <h2 id={hid} className="break-words text-sm font-semibold text-ink [overflow-wrap:anywhere]">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

/** Data provenance badge. Shown on every chart that renders market data. */
export function ProvenanceBadge({ label }: { label?: string | null }) {
  if (label === "historical") {
    return (
      <span className="rounded border border-[#c98500] bg-[#c98500]/15 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-[#f2c14e]">
        HISTORICAL
      </span>
    );
  }
  if (label === "counterfactual_synthetic") {
    return (
      <span className="rounded border border-[#9085e9] bg-[#9085e9]/15 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-[#c3bdf5]">
        COUNTERFACTUAL · SYNTHETIC
      </span>
    );
  }
  return (
    <span className="rounded border border-[#3987e5] bg-[#3987e5]/15 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-[#9ec5f4]">
      SYNTHETIC
    </span>
  );
}

export function Kpi({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "up" | "down" | "warn" }) {
  const toneCls = tone === "up" ? "text-up" : tone === "down" ? "text-down" : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="min-w-0 rounded-md border border-line bg-panel px-3 py-2">
      <div className="truncate text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`truncate text-lg font-semibold tnum ${toneCls}`}>{value}</div>
      {sub && <div className="truncate text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-md border border-dashed border-line2 px-4 py-8 text-center">
      <p className="text-sm font-medium text-ink2">{title}</p>
      {children && <div className="max-w-prose text-xs text-muted">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error, what }: { error: unknown; what?: string }) {
  if (!error) return null;
  const e = error as ApiError;
  const msg = e instanceof ApiError ? (e.status ? `${e.detail} (HTTP ${e.status})` : e.detail) : String((e as Error).message ?? e);
  return (
    <p role="alert" className="rounded-md border border-down/40 bg-down/10 px-3 py-2 text-xs text-[#f3a7a7]">
      {what ? `${what}: ` : ""}
      {msg}
    </p>
  );
}

export function NoSimCta({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`rounded-lg border border-accent/40 bg-accent/10 ${compact ? "p-3" : "p-6"} text-center`}>
      <p className="font-medium">No simulation running</p>
      <p className="mt-1 text-sm text-ink2">Start a synthetic market run to populate live data.</p>
      <Link href="/#start" prefetch={false} className="btn btn-primary mt-3">
        Start a simulation
      </Link>
    </div>
  );
}

const STATUS_CLS: Record<string, string> = {
  running: "bg-up/15 text-up border-up/50",
  paused: "bg-warn/15 text-warn border-warn/50",
  finished: "bg-accent/15 text-[#9ec5f4] border-accent/50",
  stopped: "bg-down/15 text-down border-down/50",
  idle: "bg-panel2 text-ink2 border-line2",
  failed: "bg-down/15 text-down border-down/50",
  queued: "bg-panel2 text-ink2 border-line2",
  approved: "bg-up/15 text-up border-up/50",
  promoted: "bg-up/15 text-up border-up/50",
  champion: "bg-up/15 text-up border-up/50",
  awaiting_approval: "bg-warn/15 text-warn border-warn/50",
  gates_running: "bg-accent/15 text-[#9ec5f4] border-accent/50",
  gates_failed: "bg-down/15 text-down border-down/50",
  rejected: "bg-down/15 text-down border-down/50",
  policy_rejected: "bg-down/15 text-down border-down/50",
  rejected_regression: "bg-down/15 text-down border-down/50",
};

export function StatusPill({ status }: { status?: string }) {
  const s = status ?? "unknown";
  return (
    <span className={`inline-block rounded-full border px-2 py-0.5 text-[11px] font-semibold ${STATUS_CLS[s] ?? "border-line2 bg-panel2 text-ink2"}`}>
      {s.replace(/_/g, " ")}
    </span>
  );
}

export function KeyValue({ data, className = "" }: { data: Record<string, unknown> | null | undefined; className?: string }) {
  if (!data || Object.keys(data).length === 0) return <p className="text-xs text-muted">—</p>;
  return (
    <dl className={`grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs ${className}`}>
      {Object.entries(data).map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="truncate text-muted" title={k}>
            {k}
          </dt>
          <dd className="break-all text-right text-ink tnum">
            {v !== null && typeof v === "object" ? (
              <code className="text-[11px] text-ink2">{JSON.stringify(v)}</code>
            ) : (
              fmtAny(v)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Generic renderer for arbitrary JSON reports (eval, sandbox, benchmark...). */
export function JsonTable({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span className="text-muted">—</span>;
  if (typeof value !== "object") return <span className="tnum">{fmtAny(value)}</span>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted">[]</span>;
    const allObj = value.every((v) => v && typeof v === "object" && !Array.isArray(v));
    if (allObj) {
      const cols = Array.from(new Set(value.flatMap((v) => Object.keys(v as object)))).slice(0, 12);
      return (
        <div className="max-w-full overflow-x-auto">
          <table className="data">
            <thead>
              <tr>
                {cols.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {value.slice(0, 100).map((row, i) => (
                <tr key={i}>
                  {cols.map((c) => {
                    const cell = (row as Record<string, unknown>)[c];
                    return (
                      <td key={c} className="align-top">
                        {cell !== null && typeof cell === "object" ? (
                          <code className="text-[11px] text-ink2">{JSON.stringify(cell).slice(0, 160)}</code>
                        ) : (
                          fmtAny(cell)
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    if (value.every((v) => typeof v !== "object" || v === null)) {
      return <span className="tnum text-ink2">{value.map((v) => fmtAny(v)).join(", ")}</span>;
    }
    return (
      <ol className="list-decimal space-y-1 pl-5">
        {value.map((v, i) => (
          <li key={i}>
            <JsonTable value={v} depth={depth + 1} />
          </li>
        ))}
      </ol>
    );
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return <span className="text-muted">{"{}"}</span>;
  if (depth >= 3) return <code className="break-all text-[11px] text-ink2">{JSON.stringify(value)}</code>;
  return (
    <div className="max-w-full overflow-x-auto">
      <table className="data">
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}>
              <th scope="row" className="!static w-1/4 !normal-case !tracking-normal align-top">
                {humanize(k)}
              </th>
              <td className="!whitespace-normal align-top">
                <JsonTable value={v} depth={depth + 1} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function JobProgress({ job, label }: { job?: Job; label?: string }) {
  if (!job) return null;
  const last = job.progress?.length ? job.progress[job.progress.length - 1] : undefined;
  const m = last?.match(/(\d+)\s*\/\s*(\d+)/);
  const frac = m ? Number(m[1]) / Math.max(1, Number(m[2])) : job.status === "finished" ? 1 : undefined;
  return (
    <div className="rounded-md border border-line bg-panel2 p-3 text-xs" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-ink">
          {label ?? job.kind} job <code className="text-muted">{job.id}</code>
        </span>
        <StatusPill status={job.status} />
      </div>
      {frac !== undefined && (
        <div className="mt-2 h-1.5 overflow-hidden rounded bg-line" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(frac * 100)}>
          <div className="h-full bg-accent transition-all" style={{ width: `${Math.round(frac * 100)}%` }} />
        </div>
      )}
      {!!job.progress?.length && (
        <ul className="mt-2 max-h-28 space-y-0.5 overflow-y-auto font-mono text-[11px] text-ink2">
          {job.progress.slice(-8).map((p, i) => (
            <li key={i}>› {p}</li>
          ))}
        </ul>
      )}
      {job.error && <p className="mt-2 whitespace-pre-wrap break-all font-mono text-[11px] text-down">{job.error}</p>}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string; dashed?: boolean; shape?: "line" | "dot" }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink2" aria-label="Legend">
      {items.map((it) => (
        <li key={it.label} className="flex items-center gap-1.5">
          {it.shape === "dot" ? (
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: it.color }} />
          ) : (
            <svg aria-hidden width="16" height="6">
              <line x1="0" x2="16" y1="3" y2="3" stroke={it.color} strokeWidth="2" strokeDasharray={it.dashed ? "4 3" : undefined} />
            </svg>
          )}
          {it.label}
        </li>
      ))}
    </ul>
  );
}
