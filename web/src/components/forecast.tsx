"use client";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { niceTicks } from "@/components/charts";
import { Kv, TableWrap, TONE_CLS } from "@/components/observatory";
import { Hash } from "@/components/research";
import { EmptyState, ErrorNote, Kpi, Legend, Panel } from "@/components/ui";
import { useWidth } from "@/components/useWidth";
import { ApiError } from "@/lib/api";
import { fmtAny, fmtTime } from "@/lib/format";
import type { Poll } from "@/lib/hooks";
import { fx, fxSigned, interval, type Tone } from "@/lib/observatory";
import {
  brierContributions,
  day,
  dayHour,
  isBinaryScore,
  isForecast,
  isResolution,
  isRvScore,
  mean,
  modelColorMap,
  modelScore,
  parseComparisonKey,
  parsePeriods,
  periodColor,
  periodModels,
  promotionMin,
  reportPeriods,
  sumCounts,
  type Amendment,
  type BacktestReport,
  type EvolutionResp,
  type ForecastProtocol,
  type ForecastRecord,
  type HolmRow,
  type LedgerResp,
  type PairedDiff,
  type ProspectiveResp,
  type ResolutionRecord,
  type SeriesResp,
} from "@/lib/forecast";

/* ================================================================ primitives */

const GRID = "#2c2c2a";
const AXIS = "#383835";
const MUTED = "#9a9890";
const OUTCOME = "#c3c2b7";

function Tag({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-bold tracking-wider ${TONE_CLS[tone]}`}>
      {children}
    </span>
  );
}

/** Loading / 404 / error wrapper (artifacts live under artifacts/forecast/). */
export function FState<T>({ poll, what, children }: { poll: Poll<T>; what: string; children: (d: T) => ReactNode }) {
  if (poll.data) return <>{children(poll.data)}</>;
  if (poll.error instanceof ApiError && poll.error.status === 404)
    return (
      <EmptyState title={`${what}: not produced yet`}>
        <p>{poll.error.detail}</p>
        <p className="mt-1">The backend returns 404 until the corresponding artifact exists under artifacts/forecast/.</p>
      </EmptyState>
    );
  if (poll.error) return <ErrorNote error={poll.error} what={what} />;
  return <p className="text-xs text-muted">Loading {what}…</p>;
}

function Seg<T extends string>({ options, value, onChange, label }: { options: { v: T; label: ReactNode; title?: string }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1">
      {options.map((o) => (
        <button
          key={o.v}
          type="button"
          title={o.title}
          aria-pressed={value === o.v}
          onClick={() => onChange(o.v)}
          className={`rounded border px-2 py-0.5 text-[11px] ${value === o.v ? "border-accent bg-accent/20 text-ink" : "border-line2 text-ink2 hover:bg-panel2"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function TargetPicker({ report, value, onChange, filter, id }: { report: BacktestReport; value: string; onChange: (t: string) => void; filter?: (kind: string) => boolean; id: string }) {
  const names = Object.keys(report.targets).filter((t) => !filter || filter(report.targets[t].kind));
  return (
    <label className="flex items-center gap-1.5 text-xs text-ink2" htmlFor={id}>
      Target
      <select id={id} className="input !w-auto !py-1 !text-xs" value={names.includes(value) ? value : ""} onChange={(e) => onChange(e.target.value)}>
        {!names.includes(value) && <option value="">—</option>}
        {names.map((t) => (
          <option key={t} value={t}>
            {t} · {report.targets[t].kind} · {report.targets[t].horizon_h} h
          </option>
        ))}
      </select>
    </label>
  );
}

function ModelToggles({ models, colors, selected, onToggle }: { models: string[]; colors: Record<string, string>; selected: string[]; onToggle: (m: string) => void }) {
  return (
    <div role="group" aria-label="Models" className="flex flex-wrap gap-1">
      {models.map((m) => {
        const on = selected.includes(m);
        return (
          <button
            key={m}
            type="button"
            aria-pressed={on}
            onClick={() => onToggle(m)}
            className={`flex items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] ${on ? "border-line2 bg-panel2 text-ink" : "border-line text-muted"}`}
          >
            <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: on ? colors[m] : "transparent", border: `1px solid ${colors[m]}` }} />
            {m}
          </button>
        );
      })}
    </div>
  );
}

function fmtValue(v: number | null | undefined, kind: string): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return kind === "binary" ? v.toFixed(3) : v.toFixed(3); // probability or log RV
}

/** Target description from the frozen protocol ("move3_24" -> targets.move3). */
function targetDesc(protocol: ForecastProtocol | undefined, target: string): string | undefined {
  const base = target.replace(/_\d+$/, "");
  return protocol?.targets?.[base];
}

/* ================================================================ 1. header */

export function ForecastHeader({ protocol, report }: { protocol: Poll<ForecastProtocol>; report: Poll<BacktestReport> }) {
  const p = protocol.data;
  const r = report.data;
  const amendments = p ? (Object.entries(p).filter(([k]) => k.startsWith("amendment_")) as [string, Amendment][]) : [];
  const periodRanges = parsePeriods(p?.periods);
  const periods = r ? reportPeriods(r) : [];
  const firstTarget = r ? Object.values(r.targets)[0] : undefined;
  return (
    <Panel id="protocol" title="Protocol, claims policy and exposure" subtitle={p ? `${p.name} · ${p.status ?? ""}` : undefined}>
      {protocol.error && <ErrorNote error={protocol.error} what="protocol" />}
      {report.error && <ErrorNote error={report.error} what="backtest report" />}
      {p && (
        <div className="space-y-3 text-xs">
          <p className="text-sm text-ink">
            <span className="text-muted">Objective: </span>
            {p.objective}
          </p>
          {p.domain && (
            <p className="text-ink2">
              <span className="text-muted">Domain: </span>
              {p.domain}
            </p>
          )}
          <blockquote className="rounded-md border border-warn/50 bg-warn/10 px-3 py-2 text-ink">
            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-warn">Claims policy (verbatim)</div>
            {p.claims_policy}
          </blockquote>
        </div>
      )}
      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Information lag" value={r?.lag_h !== undefined ? `${r.lag_h} h` : p?.information_lag?.publication_lag_h !== undefined ? `${p.information_lag.publication_lag_h} h` : "—"} sub="publication lag" />
        <Kpi label="Data end" value={r?.data_end_utc ? r.data_end_utc.slice(0, 10) : "—"} sub={r?.data_end_utc ? fmtTime(r.data_end_utc) : undefined} />
        <Kpi label="Protocol sha256" value={<Hash v={r?.protocol_sha256} n={12} label="protocol sha256" />} sub={r?.protocol} />
        <Kpi label="Code version" value={<Hash v={r?.code_version} n={16} label="code version" />} sub="sha256 of forecast/*.py" />
        <Kpi label="Report created" value={r?.created_utc ? r.created_utc.slice(0, 10) : "—"} sub={r?.created_utc ? fmtTime(r.created_utc) : undefined} />
        <Kpi
          label="Simulator features"
          value={r?.simulator_inclusion?.decision?.split(" ")[0] ?? "—"}
          sub={r?.simulator_inclusion?.decision}
          tone={r?.simulator_inclusion?.decision?.startsWith("EXCLUDE") ? "warn" : undefined}
        />
      </div>
      {p?.information_lag?.rule && (
        <p className="mt-2 text-xs text-ink2">
          <span className="text-muted">Lag rule: </span>
          {p.information_lag.rule}
          {p.information_lag.training_labels && <span className="text-muted"> · Training labels: {p.information_lag.training_labels}</span>}
        </p>
      )}

      <div className="mt-3 rounded-md border border-down/50 bg-down/10 p-3 text-xs" role="note" aria-label="Exposure of evaluation periods">
        <p className="text-sm font-semibold text-[#f3a7a7]">Retrospective periods are previously exposed. Only PROSPECTIVE resolved forecasts are independent evidence.</p>
        {r?.label && <p className="mt-1 text-ink2">Backtest report label: “{r.label}”.</p>}
        <TableWrap label="Period exposure labels">
          <table className="data mt-2">
            <thead>
              <tr>
                <th>Period</th>
                <th>Origins (protocol)</th>
                <th>Exposure label (report)</th>
                <th className="num">n origins{firstTarget ? ` (${Object.keys(r!.targets)[0]})` : ""}</th>
              </tr>
            </thead>
            <tbody>
              {periods.map((name) => {
                const pr = periodRanges.find((x) => x.name === name);
                return (
                  <tr key={name}>
                    <td>
                      <span className="inline-flex items-center gap-1.5 font-semibold">
                        <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: periodColor(name) }} />
                        {name}
                      </span>
                    </td>
                    <td className="!whitespace-normal text-ink2">{pr ? `${day(pr.start)} … ${day(pr.end)}` : "—"}</td>
                    <td className="!whitespace-normal">{firstTarget?.scores[name]?.label ?? "—"}</td>
                    <td className="num">{fmtAny(firstTarget?.scores[name]?.n)}</td>
                  </tr>
                );
              })}
              {p?.periods &&
                Object.entries(p.periods)
                  .filter(([k]) => !periods.includes(k))
                  .map(([k, v]) => (
                    <tr key={k}>
                      <td className="font-semibold">{k}</td>
                      <td colSpan={3} className="!whitespace-normal text-ink2">
                        {v}
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </TableWrap>
      </div>

      {amendments.map(([k, a]) => (
        <div key={k} className="mt-3 rounded-md border border-line2 bg-panel2 p-3 text-xs">
          <div className="mb-1 font-semibold text-ink">
            {k.replace("_", " ")} <span className="font-normal text-muted">· {a.written_utc} · {a.before}</span>
          </div>
          <p className="text-ink2">
            <span className="text-muted">Finding: </span>
            {a.finding}
          </p>
          <p className="mt-1 text-ink2">
            <span className="text-muted">Change: </span>
            {a.change}
          </p>
        </div>
      ))}
    </Panel>
  );
}

/* ================================================================ 2. prospective ledger */

function ProgressBar({ n, of }: { n: number; of: number | null }) {
  const frac = of ? Math.min(1, n / of) : 0;
  return (
    <div className="flex min-w-[140px] items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded bg-line" role="progressbar" aria-valuemin={0} aria-valuemax={of ?? 0} aria-valuenow={n} aria-label="resolved forecasts toward promotion minimum">
        <div className={`h-full ${frac >= 1 ? "bg-up" : "bg-accent"}`} style={{ width: `${Math.round(frac * 100)}%` }} />
      </div>
      <span className="whitespace-nowrap text-[11px] tnum text-ink2">
        {n} / {of ?? "—"}
      </span>
    </div>
  );
}

function ResolutionCell({ f, res, now }: { f: ForecastRecord; res: ResolutionRecord | undefined; now: number }) {
  if (res)
    return (
      <span className="flex flex-col">
        <span>
          <Tag tone="good">resolved</Tag> <span className="tnum">outcome {fmtValue(res.outcome, f.kind)}</span>
        </span>
        <span className="text-[10px] text-muted">{dayHour(res.resolved_ms)}</span>
      </span>
    );
  if (now < f.window_end_ms)
    return (
      <span title={`target window (${dayHour(f.origin_ms)}, ${dayHour(f.window_end_ms)}]`}>
        <Tag tone="neutral">pending</Tag> <span className="text-[10px] text-muted">{now < f.origin_ms ? "window not started" : "window open"}</span>
      </span>
    );
  return (
    <span>
      <Tag tone="weak">pending</Tag> <span className="text-[10px] text-muted">window ended, awaiting published data</span>
    </span>
  );
}

export function ProspectivePanel({ ledger, prospective, protocol }: { ledger: Poll<LedgerResp>; prospective: Poll<ProspectiveResp>; protocol?: ForecastProtocol }) {
  const [targetF, setTargetF] = useState("all");
  const [originF, setOriginF] = useState("latest");
  const L = ledger.data;
  const P = prospective.data;
  const need = promotionMin(protocol);
  const now = Date.now();

  const { forecasts, resMap } = useMemo(() => {
    const fs: { f: ForecastRecord; seq: number; hash: string }[] = [];
    const rm = new Map<string, ResolutionRecord>();
    for (const e of L?.entries ?? []) {
      if (isForecast(e)) fs.push({ f: e.data, seq: e.seq, hash: e.hash });
      else if (isResolution(e)) rm.set(e.data.forecast_id, e.data);
    }
    return { forecasts: fs, resMap: rm };
  }, [L]);

  const origins = useMemo(() => Array.from(new Set(forecasts.map((x) => x.f.origin_ms))).sort((a, b) => b - a), [forecasts]);
  const targets = useMemo(() => Array.from(new Set(forecasts.map((x) => x.f.target))), [forecasts]);
  const rows = forecasts
    .filter((x) => targetF === "all" || x.f.target === targetF)
    .filter((x) => originF === "all" || (originF === "latest" ? x.f.origin_ms === origins[0] : String(x.f.origin_ms) === originF))
    .sort((a, b) => b.f.origin_ms - a.f.origin_ms || a.seq - b.seq);

  // target:model groups: union of prospective score keys and what the ledger shows.
  const groups = useMemo(() => {
    const keys = new Set<string>(Object.keys(P?.scores ?? {}));
    const exp = new Map<string, boolean>();
    for (const x of forecasts) {
      const k = `${x.f.target}:${x.f.model}`;
      keys.add(k);
      exp.set(k, x.f.experimental);
    }
    const resolvedInWindow = new Map<string, number>();
    for (const x of forecasts) if (resMap.has(x.f.id)) resolvedInWindow.set(`${x.f.target}:${x.f.model}`, (resolvedInWindow.get(`${x.f.target}:${x.f.model}`) ?? 0) + 1);
    return Array.from(keys)
      .sort()
      .map((k) => ({ key: k, score: P?.scores?.[k], n: P?.scores?.[k]?.n ?? resolvedInWindow.get(k) ?? 0, experimental: exp.get(k) ?? false }));
  }, [P, forecasts, resMap]);

  const verify = L?.verify ?? P?.verify;
  const truncated = L && verify && L.entries.length < verify.entries;

  return (
    <Panel
      id="prospective"
      title="Prospective ledger — the only independent evidence"
      subtitle={P?.label ?? "forecasts written to the append-only ledger before their target window starts"}
      actions={verify ? <Tag tone={verify.ok ? "good" : "bad"}>{verify.ok ? "HASH CHAIN OK" : "HASH CHAIN BROKEN"}</Tag> : undefined}
    >
      {ledger.error && <ErrorNote error={ledger.error} what="ledger" />}
      {prospective.error && <ErrorNote error={prospective.error} what="prospective scores" />}
      {!L && !ledger.error && <p className="text-xs text-muted">Loading ledger…</p>}
      {verify && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
          <Kpi label="Chain verify" value={verify.ok ? "ok" : "FAILED"} tone={verify.ok ? "up" : "down"} sub={verify.error ? String(verify.error) : "hash-chained JSONL"} />
          <Kpi label="Entries" value={fmtAny(verify.entries)} />
          <Kpi label="Forecasts" value={fmtAny(verify.forecasts)} />
          <Kpi label="Resolved" value={fmtAny(verify.resolved ?? P?.resolved)} tone={(verify.resolved ?? 0) > 0 ? "up" : undefined} />
          <Kpi label="Open" value={fmtAny(L?.open ?? P?.open)} />
          <Kpi label="Chain head" value={<Hash v={verify.head} n={12} label="chain head" />} />
        </div>
      )}
      {protocol?.ledger && <p className="mt-2 text-[11px] text-muted">Protocol: {protocol.ledger}</p>}

      <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wider text-ink2">Prospective scores · progress toward promotion</h3>
      {protocol?.evolution?.promotion && <p className="mb-2 text-[11px] text-muted">Promotion rule (protocol): {protocol.evolution.promotion}</p>}
      {groups.length === 0 ? (
        <EmptyState title="No prospective forecasts yet" />
      ) : (
        <TableWrap label="Prospective scores per target and model">
          <table className="data">
            <thead>
              <tr>
                <th>target:model</th>
                <th>resolved / needed</th>
                <th className="num">Brier / MSE</th>
                <th className="num">skill vs B0</th>
                <th className="num">log loss / QLIKE</th>
                <th>evidence sufficient</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => {
                const s = g.score;
                return (
                  <tr key={g.key}>
                    <td>
                      {g.key} {g.experimental && <Tag tone="info">EXPERIMENTAL</Tag>}
                    </td>
                    <td>
                      <ProgressBar n={g.n} of={need} />
                    </td>
                    <td className="num">{fx(s?.brier ?? s?.mse_log_rv)}</td>
                    <td className="num">{fxSigned(s?.brier_skill_vs_B0 ?? s?.mse_skill_vs_B0)}</td>
                    <td className="num">{fx(s?.logloss ?? s?.qlike)}</td>
                    <td>{s ? (s.promotion_evidence_sufficient ? <Tag tone="good">yes</Tag> : <Tag tone="neutral">no</Tag>) : <span className="text-[11px] text-muted">no resolved forecasts</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
      )}

      <div className="mb-2 mt-4 flex flex-wrap items-end justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-ink2">Forecasts in the ledger</h3>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-ink2">
            Origin
            <select className="input !w-auto !py-1 !text-xs" value={originF} onChange={(e) => setOriginF(e.target.value)}>
              <option value="latest">latest ({day(origins[0])})</option>
              <option value="all">all</option>
              {origins.map((o) => (
                <option key={o} value={String(o)}>
                  {day(o)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-xs text-ink2">
            Target
            <select className="input !w-auto !py-1 !text-xs" value={targetF} onChange={(e) => setTargetF(e.target.value)}>
              <option value="all">all</option>
              {targets.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      {truncated && (
        <p className="mb-2 text-[11px] text-warn">
          Showing the last {L!.entries.length} of {verify!.entries} ledger entries (API limit); verify counts cover the whole ledger.
        </p>
      )}
      {rows.length === 0 ? (
        <EmptyState title="No forecasts match the filter" />
      ) : (
        <TableWrap label="Prospective forecasts">
          <table className="data">
            <thead>
              <tr>
                <th>#</th>
                <th>origin</th>
                <th>window end</th>
                <th>target</th>
                <th>model</th>
                <th className="num">value</th>
                <th>abstained</th>
                <th className="num">scored</th>
                <th>resolution</th>
                <th>issued</th>
                <th>as of</th>
                <th className="num">lag h</th>
                <th className="num">train n</th>
                <th>inputs</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ f, seq, hash }) => (
                <tr key={f.id}>
                  <td className="text-muted">{seq}</td>
                  <td>{dayHour(f.origin_ms)}</td>
                  <td>{dayHour(f.window_end_ms)}</td>
                  <td title={f.kind === "binary" ? "value = probability" : "value = forecast log realized volatility"}>
                    {f.target} <span className="text-[10px] text-muted">{f.kind === "binary" ? "P" : "log RV"}</span>
                  </td>
                  <td>
                    {f.model} {f.experimental && <Tag tone="info">EXP</Tag>}
                  </td>
                  <td className="num">{fmtValue(f.value, f.kind)}</td>
                  <td>{f.abstained ? <Tag tone="weak">{f.abstain_reason ?? "abstained"}</Tag> : <span className="text-muted">no</span>}</td>
                  <td className="num" title={f.abstained ? `abstained: scored as B0 fallback ${fmtValue(f.fallback_B0, f.kind)}` : undefined}>
                    {fmtValue(f.scored_value, f.kind)}
                    {f.abstained && <span className="text-[10px] text-muted"> (B0)</span>}
                  </td>
                  <td>
                    <ResolutionCell f={f} res={resMap.get(f.id)} now={now} />
                  </td>
                  <td>{dayHour(f.issued_ms)}</td>
                  <td>{dayHour(f.as_of_ms)}</td>
                  <td className="num">{fx(f.lag_h, 1)}</td>
                  <td className="num">{fmtAny(f.training_n)}</td>
                  <td className="!whitespace-normal">
                    <details>
                      <summary className="cursor-pointer text-[11px] text-[#9ec5f4]">
                        <Hash v={f.inputs?.bars_digest} n={8} label="bars digest" />
                      </summary>
                      <div className="mt-1 w-[320px] max-w-[70vw] space-y-1 text-[11px]">
                        <div>
                          <span className="text-muted">id</span> <code>{f.id}</code> · <span className="text-muted">version</span> <code className="break-all">{f.model_version}</code>
                        </div>
                        <div>
                          <span className="text-muted">bars</span> {fmtAny(f.inputs?.n_bars)} · <span className="text-muted">last bar open</span> {dayHour(f.inputs?.last_bar_open_ms)}
                        </div>
                        <div>
                          <span className="text-muted">fresh archives</span> {(f.inputs?.fresh_archives ?? []).join(", ") || "—"}
                        </div>
                        <div>
                          <span className="text-muted">entry hash</span> <Hash v={hash} n={16} />
                        </div>
                        <Kv data={f.inputs?.features} />
                      </div>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </Panel>
  );
}

/* ================================================================ 3. time series */

interface Band {
  name: string;
  start: number;
  end: number;
  label: string;
}

function lowerBound(a: number[], x: number): number {
  let lo = 0;
  let hi = a.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (a[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function SeriesChart({
  s,
  kind,
  models,
  colors,
  bands,
  win,
}: {
  s: SeriesResp;
  kind: string;
  models: string[];
  colors: Record<string, string>;
  bands: Band[];
  win: [number, number];
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const binary = kind === "binary";
  const stripH = 7;
  const m = { l: 44, r: 10, t: 10, b: 26 + models.length * stripH + 6 };
  const ph = width < 500 ? 200 : 260;
  const height = m.t + ph + m.b;
  const iw = Math.max(10, width - m.l - m.r);
  const i0 = lowerBound(s.origins, win[0]);
  const i1 = Math.max(i0, lowerBound(s.origins, win[1] + 1) - 1);
  const x0 = s.origins[i0] ?? win[0];
  const x1 = s.origins[i1] ?? win[1];
  let y0 = 0;
  let y1 = 1;
  if (!binary) {
    let lo = Infinity;
    let hi = -Infinity;
    const take = (v: number | null | undefined) => {
      if (typeof v === "number" && Number.isFinite(v)) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    };
    for (let i = i0; i <= i1; i++) {
      take(s.y[i]);
      for (const md of models) take(s.forecast[md]?.[i]);
    }
    if (!Number.isFinite(lo)) [lo, hi] = [0, 1];
    const pad = (hi - lo || 1) * 0.05;
    y0 = lo - pad;
    y1 = hi + pad;
  }
  const sx = (v: number) => m.l + ((v - x0) / (x1 - x0 || 1)) * iw;
  const sy = (v: number) => m.t + ph - ((v - y0) / (y1 - y0 || 1)) * ph;
  const yt = binary ? [0, 0.25, 0.5, 0.75, 1] : niceTicks(y0, y1, 5);

  const paths = useMemo(() => {
    const mk = (vals: (number | null)[] | undefined) => {
      if (!vals) return "";
      let d = "";
      let pen = false;
      for (let i = i0; i <= i1; i++) {
        const v = vals[i];
        if (typeof v !== "number" || !Number.isFinite(v)) {
          pen = false;
          continue;
        }
        d += `${pen ? "L" : "M"}${sx(s.origins[i]).toFixed(1)},${sy(v).toFixed(1)}`;
        pen = true;
      }
      return d;
    };
    return { models: models.map((md) => mk(s.forecast[md])), realized: binary ? "" : mk(s.y) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s, models.join(","), i0, i1, width, y0, y1, binary]);

  const outcomeTicks = useMemo(() => {
    if (!binary) return "";
    let d = "";
    for (let i = i0; i <= i1; i++) {
      const v = s.y[i];
      if (v === 1) d += `M${sx(s.origins[i]).toFixed(1)},${m.t}v7`;
      else if (v === 0) d += `M${sx(s.origins[i]).toFixed(1)},${m.t + ph}v-7`;
    }
    return d;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s, i0, i1, width, binary]);

  const abstPaths = useMemo(
    () =>
      models.map((md, k) => {
        const r = s.abstained[md];
        if (!r) return "";
        const yy = m.t + ph + 22 + k * stripH;
        let d = "";
        for (let i = i0; i <= i1; i++) if (r[i]) d += `M${sx(s.origins[i]).toFixed(1)},${yy}v${stripH - 2}`;
        return d;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [s, models.join(","), i0, i1, width],
  );

  // x ticks: years (or months for short windows)
  const xt = useMemo(() => {
    const out: { x: number; label: string }[] = [];
    const span = x1 - x0;
    const d0 = new Date(x0);
    const monthly = span < 400 * 86_400_000;
    const stepM = monthly ? (iw < 400 ? 6 : 3) : iw < 400 ? 24 : 12;
    let y = d0.getUTCFullYear();
    let mo = monthly ? d0.getUTCMonth() + 1 : 0;
    if (!monthly) y += 1;
    for (let guard = 0; guard < 200; guard++) {
      const t = Date.UTC(y, mo, 1);
      if (t > x1) break;
      if (t >= x0) out.push({ x: t, label: monthly ? new Date(t).toISOString().slice(0, 7) : String(y) });
      mo += stepM;
      while (mo >= 12) {
        mo -= 12;
        y += 1;
      }
    }
    return out;
  }, [x0, x1, iw]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const xv = x0 + ((e.clientX - rect.left - m.l) / iw) * (x1 - x0);
    let k = lowerBound(s.origins, xv);
    if (k > i1) k = i1;
    if (k > i0 && Math.abs(s.origins[k - 1] - xv) < Math.abs(s.origins[k] - xv)) k -= 1;
    setHover(Math.max(i0, k));
  };
  const hx = hover !== null ? s.origins[hover] : null;

  return (
    <div ref={ref} className="relative w-full">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`${s.target}: ${binary ? "forecast probabilities and outcomes" : "forecast vs realized log RV"} by origin`}
        className="block"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {bands.map((b) => {
          const a = Math.max(x0, b.start);
          const z = Math.min(x1, b.end);
          if (z <= a) return null;
          return (
            <g key={b.name}>
              <rect x={sx(a)} y={m.t} width={Math.max(1, sx(z) - sx(a))} height={ph} fill={periodColor(b.name)} opacity={0.1}>
                <title>{`${b.name}: ${b.label}`}</title>
              </rect>
              <text x={sx(a) + 3} y={m.t + 11} fontSize={10} fill={periodColor(b.name)} fontWeight={600}>
                {sx(z) - sx(a) > 46 ? b.name : ""}
              </text>
            </g>
          );
        })}
        {yt.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke={GRID} />
            <text x={m.l - 5} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">
              {binary ? t.toFixed(2) : +t.toFixed(2)}
            </text>
          </g>
        ))}
        {xt.map((t) => (
          <g key={t.x}>
            <line x1={sx(t.x)} x2={sx(t.x)} y1={m.t + ph} y2={m.t + ph + 4} stroke={AXIS} />
            <text x={sx(t.x)} y={m.t + ph + 15} textAnchor="middle" fontSize={10} fill={MUTED} className="tnum">
              {t.label}
            </text>
          </g>
        ))}
        <line x1={m.l} x2={m.l + iw} y1={m.t + ph} y2={m.t + ph} stroke={AXIS} />
        {binary && <path d={outcomeTicks} stroke={OUTCOME} strokeWidth={1} opacity={0.55} />}
        {!binary && <path d={paths.realized} fill="none" stroke={OUTCOME} strokeWidth={1} opacity={0.75} />}
        {paths.models.map((d, k) => (
          <path key={models[k]} d={d} fill="none" stroke={colors[models[k]]} strokeWidth={1.4} opacity={0.95} />
        ))}
        {models.map((md, k) => (
          <g key={md}>
            <text x={m.l - 4} y={m.t + ph + 22 + k * stripH + stripH / 2} dy="0.32em" textAnchor="end" fontSize={8} fill={MUTED}>
              {md.split("_")[0]}
            </text>
            <line x1={m.l} x2={m.l + iw} y1={m.t + ph + 22 + k * stripH + stripH / 2} y2={m.t + ph + 22 + k * stripH + stripH / 2} stroke={GRID} />
            <path d={abstPaths[k]} stroke={colors[md]} strokeWidth={1} />
          </g>
        ))}
        {hx !== null && <line x1={sx(hx)} x2={sx(hx)} y1={m.t} y2={m.t + ph} stroke="#6a6964" pointerEvents="none" />}
      </svg>
      {hx !== null && hover !== null && (
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-md border border-line2 bg-[#0f0f0e]/95 px-2 py-1.5 text-[11px] shadow-lg"
          style={sx(hx) > width / 2 ? { right: width - sx(hx) + 8 } : { left: sx(hx) + 8 }}
        >
          <div className="text-muted tnum">origin {day(hx)}</div>
          <div className="flex gap-2 whitespace-nowrap">
            <span style={{ color: OUTCOME }}>{binary ? "outcome" : "realized log RV"}</span>
            <span className="ml-auto tnum">{fmtValue(s.y[hover], kind)}</span>
          </div>
          {models.map((md) => (
            <div key={md} className="flex gap-2 whitespace-nowrap">
              <span style={{ color: colors[md] }}>{md}</span>
              <span className="ml-auto tnum">
                {fmtValue(s.forecast[md]?.[hover], kind)}
                {s.abstained[md]?.[hover] && <span className="text-warn"> · abstained ({s.abstained[md]?.[hover]}) → B0 fallback</span>}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function SeriesPanel({
  report,
  protocol,
  series,
  target,
  setTarget,
}: {
  report: BacktestReport;
  protocol?: ForecastProtocol;
  series: Poll<SeriesResp>;
  target: string;
  setTarget: (t: string) => void;
}) {
  const tr = report.targets[target];
  const allModels = useMemo(() => periodModels(Object.values(tr?.scores ?? {})[0]), [tr]);
  const colors = useMemo(() => modelColorMap(allModels), [allModels]);
  const [sel, setSel] = useState<string[] | null>(null);
  const selected = (sel ?? allModels.filter((m) => /^(B0|M1)/.test(m) || allModels.indexOf(m) === 0)).filter((m) => allModels.includes(m));
  const toggle = (m: string) => setSel((cur) => {
    const c = cur ?? selected;
    return c.includes(m) ? c.filter((x) => x !== m) : allModels.filter((x) => c.includes(x) || x === m);
  });
  const ranges = parsePeriods(protocol?.periods);
  const periods = reportPeriods(report);
  const bands: Band[] = ranges.map((r) => ({ name: r.name, start: r.start, end: r.end, label: tr?.scores[r.name]?.label ?? r.text }));
  const [winName, setWinName] = useState("all");
  const s = series.data && series.data.target === target ? series.data : undefined;
  const full: [number, number] = s && s.origins.length ? [s.origins[0], s.origins[s.origins.length - 1]] : [0, 1];
  const wr = ranges.find((r) => r.name === winName);
  const win: [number, number] = wr ? [wr.start, wr.end] : full;
  const binary = tr?.kind === "binary";
  const abstCounts = s
    ? selected.map((md) => {
        let n = 0;
        let tot = 0;
        for (let i = 0; i < s.origins.length; i++) {
          if (s.origins[i] < win[0] || s.origins[i] > win[1]) continue;
          tot++;
          if (s.abstained[md]?.[i]) n++;
        }
        return { md, n, tot };
      })
    : [];

  return (
    <Panel
      id="series"
      title="Predictions vs realized outcomes (retrospective backtest)"
      subtitle={s?.label ?? report.label}
      actions={<TargetPicker report={report} value={target} onChange={setTarget} id="tp-series" />}
    >
      {tr && (
        <p className="mb-2 text-xs text-ink2">
          <span className="font-semibold text-ink">{target}</span> · {tr.kind} · horizon {tr.horizon_h} h
          {targetDesc(protocol, target) && <span className="text-muted"> · {targetDesc(protocol, target)}</span>}
        </p>
      )}
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-2">
        <ModelToggles models={allModels} colors={colors} selected={selected} onToggle={toggle} />
        <Seg
          label="Window"
          value={winName}
          onChange={setWinName}
          options={[{ v: "all", label: "all origins" }, ...ranges.map((r) => ({ v: r.name, label: r.name, title: r.text }))]}
        />
      </div>
      {series.error && <ErrorNote error={series.error} what={`series ${target}`} />}
      {!s && !series.error && <p className="text-xs text-muted">Loading series…</p>}
      {s && <SeriesChart s={s} kind={tr?.kind ?? "binary"} models={selected} colors={colors} bands={bands} win={win} />}
      <div className="mt-2 space-y-1">
        <Legend
          items={[
            ...selected.map((md) => ({ label: md, color: colors[md] })),
            binary ? { label: "outcome ticks: top = 1, bottom = 0", color: OUTCOME } : { label: "realized log RV", color: OUTCOME },
          ]}
        />
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink2" aria-label="Period bands">
          {bands
            .filter((b) => periods.includes(b.name) || b.name === "warmup")
            .map((b) => (
              <li key={b.name} className="flex items-center gap-1.5">
                <span aria-hidden className="inline-block h-2.5 w-3 rounded-sm" style={{ background: periodColor(b.name), opacity: 0.6 }} />
                <span className="font-semibold">{b.name}</span> <span className="text-muted">{b.label}</span>
              </li>
            ))}
        </ul>
        <p className="text-[11px] text-muted">
          Lines are the models’ <em>scored</em> forecasts {binary ? "(probability)" : "(log realized volatility)"} as served by <code>/api/forecast/series</code>: at origins where a
          model abstained the series already holds the B0 fallback, so the line coincides with B0 there; the raw abstained forecast is not part of the payload. The strips
          under the axis mark those abstentions{protocol?.abstention?.scoring ? ` (protocol: “${protocol.abstention.scoring}”)` : ""}.
          {abstCounts.length > 0 && (
            <>
              {" "}
              Abstentions in window: {abstCounts.map((a) => `${a.md} ${a.n}/${a.tot}`).join(" · ")}.
            </>
          )}
        </p>
      </div>
    </Panel>
  );
}

/* ================================================================ 4. calibration */

function ReliabilityChart({ bins, color, label }: { bins: { bin: [number, number]; n: number; mean_p: number; freq: number }[]; color: string; label: string }) {
  const [ref, width] = useWidth<HTMLDivElement>(260);
  const size = Math.max(160, Math.min(width, 300));
  const m = { l: 34, r: 8, t: 8, b: 28 };
  const iw = size - m.l - m.r;
  const ih = size - m.t - m.b;
  const sx = (v: number) => m.l + v * iw;
  const sy = (v: number) => m.t + ih - v * ih;
  const maxN = Math.max(1, ...bins.map((b) => b.n));
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const line = bins.map((b, i) => `${i ? "L" : "M"}${sx(b.mean_p).toFixed(1)},${sy(b.freq).toFixed(1)}`).join("");
  return (
    <div ref={ref} className="w-full">
      <svg width={size} height={size} role="img" aria-label={label} className="mx-auto block">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke={GRID} />
            <line x1={sx(t)} x2={sx(t)} y1={m.t} y2={m.t + ih} stroke={GRID} />
            <text x={m.l - 4} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={9} fill={MUTED}>
              {t}
            </text>
            <text x={sx(t)} y={m.t + ih + 12} textAnchor="middle" fontSize={9} fill={MUTED}>
              {t}
            </text>
          </g>
        ))}
        <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} stroke="#6a6964" strokeDasharray="4 3" />
        <text x={m.l + iw} y={size - 3} textAnchor="end" fontSize={9} fill={MUTED}>
          mean forecast p
        </text>
        <text x={4} y={m.t + 8} fontSize={9} fill={MUTED}>
          freq
        </text>
        <path d={line} fill="none" stroke={color} strokeWidth={1.5} />
        {bins.map((b, i) => (
          <g key={i}>
            <circle cx={sx(b.mean_p)} cy={sy(b.freq)} r={2.5 + 6 * Math.sqrt(b.n / maxN)} fill={color} fillOpacity={0.35} stroke={color}>
              <title>{`bin [${b.bin[0].toFixed(1)}, ${b.bin[1].toFixed(1)}): n=${b.n}, mean p=${b.mean_p.toFixed(3)}, observed freq=${b.freq.toFixed(3)}`}</title>
            </circle>
            <text x={sx(b.mean_p) + 6} y={sy(b.freq) - 6} fontSize={9} fill="#f0efec" className="tnum">
              {b.n}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

export function CalibrationPanel({ report, target, setTarget, protocol }: { report: BacktestReport; target: string; setTarget: (t: string) => void; protocol?: ForecastProtocol }) {
  const periods = reportPeriods(report);
  const [period, setPeriod] = useState<string>("SCREEN");
  const per = periods.includes(period) ? period : periods[0];
  const binaryTargets = Object.keys(report.targets).filter((t) => report.targets[t].kind === "binary");
  const tr = report.targets[target];
  const isBin = tr?.kind === "binary";
  const ps = tr?.scores[per];
  const models = periodModels(ps);
  const colors = modelColorMap(periodModels(Object.values(tr?.scores ?? {})[0]));
  return (
    <Panel
      id="calibration"
      title="Calibration — reliability diagrams"
      subtitle={ps ? `${target} · ${per}: ${ps.label} · n=${ps.n}` : undefined}
      actions={
        <>
          <TargetPicker report={report} value={target} onChange={setTarget} id="tp-cal" />
          <Seg label="Period" value={per} onChange={setPeriod} options={periods.map((p) => ({ v: p, label: p, title: tr?.scores[p]?.label }))} />
        </>
      }
    >
      {protocol?.scoring?.binary && <p className="mb-2 text-[11px] text-muted">Scoring (protocol): {protocol.scoring.binary}</p>}
      {!isBin ? (
        <EmptyState title={`${target} is a volatility (rv) target — reliability diagrams apply to binary targets`}>
          <div className="mt-2 flex flex-wrap justify-center gap-1">
            {binaryTargets.map((t) => (
              <button key={t} type="button" className="btn btn-sm" onClick={() => setTarget(t)}>
                {t}
              </button>
            ))}
          </div>
        </EmptyState>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {models.map((md) => {
            const sc = modelScore(ps, md);
            if (!isBinaryScore(sc)) return null;
            return (
              <div key={md} className="min-w-0 rounded-md border border-line bg-panel2 p-2">
                <div className="mb-1 flex flex-wrap items-baseline justify-between gap-1 text-xs">
                  <span className="font-semibold" style={{ color: colors[md] }}>
                    {md}
                  </span>
                  <span className="tnum text-ink2">
                    ECE <span className="font-semibold text-ink">{fx(sc.reliability.ece)}</span> · Brier {fx(sc.brier)} · base rate {fx(sc.base_rate)}
                  </span>
                </div>
                <ReliabilityChart bins={sc.reliability.bins} color={colors[md]} label={`Reliability diagram ${target} ${md} ${per}`} />
                <details className="mt-1 text-[11px]">
                  <summary className="cursor-pointer text-muted">bins ({sc.reliability.bins.length} non-empty)</summary>
                  <TableWrap label={`Reliability bins ${md}`}>
                    <table className="data">
                      <thead>
                        <tr>
                          <th>bin</th>
                          <th className="num">n</th>
                          <th className="num">mean p</th>
                          <th className="num">freq</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sc.reliability.bins.map((b, i) => (
                          <tr key={i}>
                            <td>
                              [{b.bin[0].toFixed(1)}, {b.bin[1].toFixed(1)})
                            </td>
                            <td className="num">{b.n}</td>
                            <td className="num">{b.mean_p.toFixed(3)}</td>
                            <td className="num">{b.freq.toFixed(3)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableWrap>
                </details>
              </div>
            );
          })}
        </div>
      )}
      {isBin && <p className="mt-2 text-[11px] text-muted">Point = (mean forecast probability, observed frequency) per non-empty bin; area ∝ bin count (printed). Dashed diagonal = perfect calibration. Scored values (abstentions → B0 fallback).</p>}
    </Panel>
  );
}

/* ================================================================ 5. error distributions */

function QuantileRows({ rows, colors }: { rows: { model: string; q: number[] }[]; colors: Record<string, string> }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const rowH = 26;
  const m = { l: width < 500 ? 70 : 110, r: 12, t: 6, b: 24 };
  const height = m.t + rows.length * rowH + m.b;
  const iw = Math.max(10, width - m.l - m.r);
  const all = rows.flatMap((r) => r.q).concat([0]);
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const pad = (hi - lo || 1) * 0.05;
  const x0 = lo - pad;
  const x1 = hi + pad;
  const sx = (v: number) => m.l + ((v - x0) / (x1 - x0)) * iw;
  const ticks = niceTicks(x0, x1, Math.max(3, Math.floor(iw / 70)));
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label="Error quantiles of forecast minus realized log RV per model" className="block">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={sx(t)} x2={sx(t)} y1={m.t} y2={m.t + rows.length * rowH} stroke={GRID} />
            <text x={sx(t)} y={height - 8} textAnchor="middle" fontSize={10} fill={MUTED} className="tnum">
              {+t.toFixed(2)}
            </text>
          </g>
        ))}
        <line x1={sx(0)} x2={sx(0)} y1={m.t} y2={m.t + rows.length * rowH} stroke="#6a6964" strokeDasharray="3 3" />
        {rows.map((r, i) => {
          const cy = m.t + i * rowH + rowH / 2;
          const q = r.q;
          const c = colors[r.model] ?? "#9a9890";
          return (
            <g key={r.model}>
              <text x={m.l - 6} y={cy} dy="0.32em" textAnchor="end" fontSize={10} fill={c}>
                {width < 500 ? r.model.split("_")[0] : r.model}
              </text>
              {q.length >= 5 && (
                <>
                  <line x1={sx(q[0])} x2={sx(q[4])} y1={cy} y2={cy} stroke={c} />
                  <line x1={sx(q[0])} x2={sx(q[0])} y1={cy - 4} y2={cy + 4} stroke={c} />
                  <line x1={sx(q[4])} x2={sx(q[4])} y1={cy - 4} y2={cy + 4} stroke={c} />
                  <rect x={sx(q[1])} y={cy - 7} width={Math.max(1, sx(q[3]) - sx(q[1]))} height={14} fill={c} fillOpacity={0.3} stroke={c} />
                  <line x1={sx(q[2])} x2={sx(q[2])} y1={cy - 7} y2={cy + 7} stroke="#f0efec" strokeWidth={2} />
                </>
              )}
              <title>{`${r.model}: ${q.map((v) => v.toFixed(3)).join(" · ")}`}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function HistChart({ edges, series, label }: { edges: number[]; series: { name: string; color: string; counts: number[] }[]; label: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const height = 200;
  const m = { l: 40, r: 8, t: 8, b: 30 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = height - m.t - m.b;
  const nb = edges.length - 1;
  // share of origins (so models with equal n are directly comparable)
  const shares = series.map((s) => {
    const tot = s.counts.reduce((a, b) => a + b, 0) || 1;
    return s.counts.map((c) => c / tot);
  });
  const maxV = Math.max(0.01, ...shares.flat());
  const sy = (v: number) => m.t + ih - (v / maxV) * ih;
  const bw = iw / nb;
  const sub = (bw - 1) / Math.max(1, series.length);
  const yt = niceTicks(0, maxV, 3);
  const every = Math.max(1, Math.ceil(nb / Math.max(2, Math.floor(iw / 40))));
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label={label} className="block">
        {yt.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke={GRID} />
            <text x={m.l - 4} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        {Array.from({ length: nb }, (_, i) => (
          <g key={i}>
            {series.map((s, j) => (
              <rect key={s.name} x={m.l + i * bw + j * sub} y={sy(shares[j][i])} width={Math.max(0.5, sub - 0.5)} height={Math.max(0, m.t + ih - sy(shares[j][i]))} fill={s.color}>
                <title>{`${s.name}: Brier in [${edges[i].toFixed(2)}, ${edges[i + 1].toFixed(2)}): ${s.counts[i]} origins (${(shares[j][i] * 100).toFixed(1)}%)`}</title>
              </rect>
            ))}
            {i % every === 0 && (
              <text x={m.l + i * bw} y={m.t + ih + 13} fontSize={10} fill={MUTED} className="tnum">
                {edges[i].toFixed(2)}
              </text>
            )}
          </g>
        ))}
        <line x1={m.l} x2={m.l + iw} y1={m.t + ih} y2={m.t + ih} stroke={AXIS} />
        <text x={m.l + iw} y={height - 3} textAnchor="end" fontSize={10} fill={MUTED}>
          per-origin Brier contribution (p − y)²
        </text>
      </svg>
    </div>
  );
}

export function ErrorPanel({
  report,
  protocol,
  series,
  target,
  setTarget,
}: {
  report: BacktestReport;
  protocol?: ForecastProtocol;
  series: Poll<SeriesResp>;
  target: string;
  setTarget: (t: string) => void;
}) {
  const periods = reportPeriods(report);
  const [period, setPeriod] = useState<string>("SCREEN");
  const per = periods.includes(period) ? period : periods[0];
  const tr = report.targets[target];
  const ps = tr?.scores[per];
  const models = periodModels(ps);
  const colors = modelColorMap(periodModels(Object.values(tr?.scores ?? {})[0]));
  const b0 = models.find((md) => md.startsWith("B0")) ?? models[0];
  const [pick, setPick] = useState<string | null>(null);
  const [cmp, setCmp] = useState<string | null>(null);
  const modelA = pick && models.includes(pick) ? pick : models.find((md) => md.startsWith("M1")) ?? models[0];
  const modelB = cmp !== null ? (models.includes(cmp) ? cmp : "") : b0;
  const ranges = parsePeriods(protocol?.periods);
  const range = ranges.find((r) => r.name === per);
  const s = series.data && series.data.target === target ? series.data : undefined;

  const hist = useMemo(() => {
    if (!s || tr?.kind !== "binary" || !b0) return null;
    const edges = Array.from({ length: 21 }, (_, i) => i / 20);
    const mk = (md: string) => {
      const c = brierContributions(s, md, b0, range);
      const counts = new Array(20).fill(0);
      for (const v of c) counts[Math.min(19, Math.floor(v * 20))]++;
      return { md, contrib: c, counts };
    };
    return { edges, rows: [modelA, modelB].filter((x, i, a) => x && a.indexOf(x) === i).map((md) => mk(md as string)) };
  }, [s, tr, b0, modelA, modelB, range]);

  return (
    <Panel
      id="errors"
      title="Error distributions"
      subtitle={ps ? `${target} · ${per}: ${ps.label}` : undefined}
      actions={
        <>
          <TargetPicker report={report} value={target} onChange={setTarget} id="tp-err" />
          <Seg label="Period" value={per} onChange={setPeriod} options={periods.map((p) => ({ v: p, label: p, title: tr?.scores[p]?.label }))} />
        </>
      }
    >
      {tr?.kind === "rv" && (
        <>
          <p className="mb-2 text-xs text-ink2">
            Error quantiles of (forecast − realized) log RV per model, as reported (<code>error_quantiles</code>, 5 values). Box = 2nd–4th value, whiskers = 1st/5th, white tick = middle value.
            The report does not state the quantile levels.
          </p>
          <QuantileRows rows={models.map((md) => ({ model: md, q: (modelScore(ps, md) as { error_quantiles?: number[] })?.error_quantiles ?? [] }))} colors={colors} />
          <TableWrap label="Error quantiles table">
            <table className="data mt-2">
              <thead>
                <tr>
                  <th>model</th>
                  <th className="num">q1</th>
                  <th className="num">q2</th>
                  <th className="num">q3</th>
                  <th className="num">q4</th>
                  <th className="num">q5</th>
                  <th className="num">MSE log RV</th>
                </tr>
              </thead>
              <tbody>
                {models.map((md) => {
                  const sc = modelScore(ps, md);
                  if (!isRvScore(sc)) return null;
                  return (
                    <tr key={md}>
                      <td style={{ color: colors[md] }}>{md}</td>
                      {sc.error_quantiles.map((q, i) => (
                        <td key={i} className="num">
                          {fxSigned(q, 3)}
                        </td>
                      ))}
                      <td className="num">{fx(sc.mse_log_rv)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
        </>
      )}
      {tr?.kind === "binary" && (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-3 text-xs">
            <label className="flex items-center gap-1.5 text-ink2">
              Model
              <select className="input !w-auto !py-1 !text-xs" value={modelA} onChange={(e) => setPick(e.target.value)}>
                {models.map((md) => (
                  <option key={md}>{md}</option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-ink2">
              compare with
              <select className="input !w-auto !py-1 !text-xs" value={modelB} onChange={(e) => setCmp(e.target.value)}>
                <option value="">(none)</option>
                {models.map((md) => (
                  <option key={md}>{md}</option>
                ))}
              </select>
            </label>
          </div>
          <p className="mb-2 rounded border border-accent/40 bg-accent/10 px-2 py-1 text-[11px] text-ink2">
            Computed client-side from <code>/api/forecast/series</code>: per-origin Brier contribution (p − y)² of the scored forecast over the {per} origins (the series
            already substitutes the B0 fallback where a model abstained). The mean is cross-checked against the report’s Brier.
          </p>
          {series.error && <ErrorNote error={series.error} what={`series ${target}`} />}
          {!hist && !series.error && <p className="text-xs text-muted">Loading series…</p>}
          {hist && (
            <>
              <HistChart edges={hist.edges} series={hist.rows.map((r) => ({ name: r.md, color: colors[r.md], counts: r.counts }))} label={`Histogram of per-origin Brier contributions, ${target} ${per}`} />
              <TableWrap label="Client-side Brier check">
                <table className="data mt-2">
                  <thead>
                    <tr>
                      <th>model</th>
                      <th className="num">n (client)</th>
                      <th className="num">mean Brier (client)</th>
                      <th className="num">Brier (report)</th>
                      <th className="num">n (report)</th>
                      <th>match</th>
                    </tr>
                  </thead>
                  <tbody>
                    {hist.rows.map((r) => {
                      const sc = modelScore(ps, r.md);
                      const rb = isBinaryScore(sc) ? sc.brier : NaN;
                      const mc = mean(r.contrib);
                      const ok = Number.isFinite(rb) && Math.abs(mc - rb) < 1e-4 && r.contrib.length === sc?.n;
                      return (
                        <tr key={r.md}>
                          <td style={{ color: colors[r.md] }}>{r.md}</td>
                          <td className="num">{r.contrib.length}</td>
                          <td className="num">{fx(mc, 5)}</td>
                          <td className="num">{fx(rb, 5)}</td>
                          <td className="num">{fmtAny(sc?.n)}</td>
                          <td>{ok ? <Tag tone="good">✓ within 1e-4</Tag> : <Tag tone="weak">differs</Tag>}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableWrap>
              <p className="mt-1 text-[11px] text-muted">Series values are rounded in the API payload, so tiny differences (&lt;1e-4) are expected.</p>
            </>
          )}
        </>
      )}
    </Panel>
  );
}

/* ================================================================ 6. model comparison */

function SimInclusion({ report, protocol }: { report: BacktestReport; protocol?: ForecastProtocol }) {
  const si = report.simulator_inclusion;
  const excl = si?.decision?.startsWith("EXCLUDE");
  return (
    <div className={`rounded-md border p-3 ${excl ? "border-warn/60 bg-warn/10" : "border-up/60 bg-up/10"}`} role="note" aria-label="Simulator inclusion decision">
      <div className="text-[10px] font-bold uppercase tracking-wider text-muted">Simulator inclusion decision</div>
      <p className={`mt-0.5 text-base font-bold ${excl ? "text-warn" : "text-up"}`}>{si?.decision ?? "—"}</p>
      <p className="mt-1 text-xs text-ink2">
        Targets where simulator features help: {si?.targets_where_sim_helps?.length ? si.targets_where_sim_helps.join(", ") : <span className="font-semibold">none</span>}
      </p>
      {si?.rule && <p className="mt-1 text-[11px] text-muted">Rule (report): {si.rule}</p>}
      {protocol?.simulator_inclusion_rule && <p className="mt-1 text-[11px] text-muted">Rule (protocol): {protocol.simulator_inclusion_rule}</p>}
    </div>
  );
}

function holmFor(report: BacktestReport, key: string): { row: HolmRow; family: string } | undefined {
  if (report.holm_binary_SCREEN?.[key]) return { row: report.holm_binary_SCREEN[key], family: "binary" };
  if (report.holm_rv_SCREEN?.[key]) return { row: report.holm_rv_SCREEN[key], family: "rv" };
  return undefined;
}

function HolmCells({ h }: { h: { row: HolmRow; family: string } | undefined }) {
  if (!h)
    return (
      <>
        <td className="num text-muted">—</td>
        <td className="num text-muted">—</td>
        <td className="text-muted">not in a Holm family</td>
      </>
    );
  return (
    <>
      <td className="num">{fx(h.row.p, 4)}</td>
      <td className="num">{fx(h.row.threshold, 5)}</td>
      <td>{h.row.reject_null ? <Tag tone="good">REJECT H0 (Holm)</Tag> : <Tag tone="neutral">not rejected</Tag>}</td>
    </>
  );
}

function PairedRow({ d }: { d: PairedDiff | undefined }) {
  return (
    <>
      <td className="num">{fmtAny(d?.n)}</td>
      <td className="num font-semibold">{fxSigned(d?.mean, 5)}</td>
      <td className="num text-ink2">{d ? interval(d.lo, d.hi) : "—"}</td>
      <td className="num">{fx(d?.p_better, 4)}</td>
    </>
  );
}

function HolmFamilyTable({ title, fam, highlight }: { title: string; fam: Record<string, HolmRow>; highlight: string }) {
  const rows = Object.entries(fam ?? {}).sort((a, b) => a[1].p - b[1].p);
  return (
    <div className="min-w-0">
      <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink2">
        {title} · {rows.length} tests
      </h4>
      <TableWrap label={title}>
        <table className="data">
          <thead>
            <tr>
              <th className="num">rank</th>
              <th>comparison (A − B)</th>
              <th className="num">p</th>
              <th className="num">Holm threshold</th>
              <th>decision</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([k, h], i) => (
              <tr key={k} className={k.startsWith(highlight + ":") ? "bg-accent/10" : undefined}>
                <td className="num text-muted">{i + 1}</td>
                <td>{k.replace(":", " · ").replace("-vs-", " vs ")}</td>
                <td className="num">{fx(h.p, 4)}</td>
                <td className="num">{fx(h.threshold, 5)}</td>
                <td>{h.reject_null ? <Tag tone="good">REJECT H0</Tag> : <Tag tone="neutral">not rejected</Tag>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </div>
  );
}

export function ComparisonPanel({ report, protocol, target, setTarget }: { report: BacktestReport; protocol?: ForecastProtocol; target: string; setTarget: (t: string) => void }) {
  const periods = reportPeriods(report);
  const tr = report.targets[target];
  const isBin = tr?.kind === "binary";
  const comps = Object.entries(report.comparisons ?? {}).filter(([k]) => parseComparisonKey(k).target === target);
  return (
    <Panel id="comparison" title="Model comparison" subtitle={`${target} · retrospective, previously exposed`} actions={<TargetPicker report={report} value={target} onChange={setTarget} id="tp-cmp" />}>
      <SimInclusion report={report} protocol={protocol} />

      <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wider text-ink2">Scores per model and period</h3>
      <TableWrap label="Scores per model and period">
        <table className="data">
          <thead>
            <tr>
              <th>period / model</th>
              <th className="num">n</th>
              {isBin ? (
                <>
                  <th className="num">Brier</th>
                  <th className="num">log loss</th>
                  <th className="num">BSS vs B0</th>
                  <th className="num">base rate</th>
                  <th className="num">ECE</th>
                </>
              ) : (
                <>
                  <th className="num">MSE log RV</th>
                  <th className="num">QLIKE</th>
                  <th className="num">MSE skill vs B0</th>
                </>
              )}
              <th className="num">coverage</th>
              <th>abstentions</th>
            </tr>
          </thead>
          <tbody>
            {periods.map((p) => {
              const ps = tr?.scores[p];
              return (
                <Fragment key={p}>
                  <tr>
                    <td colSpan={isBin ? 9 : 7} className="!whitespace-normal bg-panel2 text-[11px]">
                      <span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: periodColor(p) }} aria-hidden />
                      <span className="font-semibold text-ink">{p}</span> <span className="text-muted">· {ps?.label} · n={fmtAny(ps?.n)}</span>
                    </td>
                  </tr>
                  {periodModels(ps).map((md) => {
                    const sc = modelScore(ps, md);
                    return (
                      <tr key={md}>
                        <td className="pl-4">{md}</td>
                        <td className="num">{fmtAny(sc?.n)}</td>
                        {isBinaryScore(sc) ? (
                          <>
                            <td className="num">{fx(sc.brier, 4)}</td>
                            <td className="num">{fx(sc.logloss, 4)}</td>
                            <td className={`num ${sc.brier_skill_vs_B0 > 0 ? "text-ink" : "text-muted"}`}>{fxSigned(sc.brier_skill_vs_B0, 4)}</td>
                            <td className="num">{fx(sc.base_rate, 3)}</td>
                            <td className="num">{fx(sc.reliability?.ece, 4)}</td>
                          </>
                        ) : isRvScore(sc) ? (
                          <>
                            <td className="num">{fx(sc.mse_log_rv, 4)}</td>
                            <td className="num">{fx(sc.qlike, 4)}</td>
                            <td className={`num ${sc.mse_skill_vs_B0 > 0 ? "text-ink" : "text-muted"}`}>{fxSigned(sc.mse_skill_vs_B0, 4)}</td>
                          </>
                        ) : (
                          <td colSpan={isBin ? 5 : 3} className="text-muted">
                            —
                          </td>
                        )}
                        <td className="num">{sc ? `${(sc.coverage * 100).toFixed(1)}%` : "—"}</td>
                        <td className="!whitespace-normal text-[11px]">
                          {sc && sumCounts(sc.abstentions) > 0 ? <Kv data={sc.abstentions} /> : <span className="text-muted">none</span>}
                        </td>
                      </tr>
                    );
                  })}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </TableWrap>
      <p className="mt-1 text-[11px] text-muted">Coverage = share of origins where the model did not abstain. Skill scores are relative to B0 climatology on the same origins. Descriptive only — no colour implies significance.</p>

      <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wider text-ink2">Pre-registered paired comparisons · {target}</h3>
      {protocol?.scoring?.comparison && <p className="mb-1 text-[11px] text-muted">Method (protocol): {protocol.scoring.comparison}</p>}
      {protocol?.pre_registered_comparisons && (
        <p className="mb-2 text-[11px] text-muted">
          Families (protocol): {protocol.pre_registered_comparisons.family} · {protocol.pre_registered_comparisons.multiple_testing} · {protocol.pre_registered_comparisons.rv_family}
        </p>
      )}
      {comps.length === 0 ? (
        <EmptyState title={`No pre-registered comparisons for ${target}`} />
      ) : (
        <TableWrap label="Paired comparisons">
          <table className="data">
            <thead>
              <tr>
                <th>comparison (loss A − loss B)</th>
                <th>period</th>
                <th className="num">n</th>
                <th className="num">mean Δ</th>
                <th className="num">95% CI</th>
                <th className="num">p_better</th>
                <th className="num">Holm p</th>
                <th className="num">threshold</th>
                <th>Holm decision (SCREEN)</th>
              </tr>
            </thead>
            <tbody>
              {comps.map(([k, byP]) => {
                const { a, b } = parseComparisonKey(k);
                const h = holmFor(report, k);
                return periods.map((p, i) => (
                  <tr key={`${k}-${p}`} className={i === 0 ? "border-t-2 border-line2" : undefined}>
                    {i === 0 && (
                      <td rowSpan={periods.length} className="align-top">
                        <span className="font-semibold">{a}</span>
                        <br />
                        <span className="text-muted">vs</span> {b}
                      </td>
                    )}
                    <td>
                      <span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: periodColor(p) }} aria-hidden />
                      {p}
                    </td>
                    <PairedRow d={byP[p]} />
                    {p === "SCREEN" ? (
                      <HolmCells h={h} />
                    ) : (
                      <>
                        <td className="num text-muted">—</td>
                        <td className="num text-muted">—</td>
                        <td className="text-[11px] text-muted">descriptive only</td>
                      </>
                    )}
                  </tr>
                ));
              })}
            </tbody>
          </table>
        </TableWrap>
      )}
      <p className="mt-1 text-[11px] text-muted">Negative mean Δ = model A has lower loss. Green appears only where the Holm-corrected SCREEN test rejects H0; DEV and CONSUMED rows are descriptive.</p>

      <details className="mt-4">
        <summary className="cursor-pointer text-xs font-semibold text-ink2">Full Holm families on SCREEN (current target highlighted)</summary>
        <div className="mt-2 grid grid-cols-1 gap-4 xl:grid-cols-2">
          <HolmFamilyTable title="Binary family" fam={report.holm_binary_SCREEN} highlight={target} />
          <HolmFamilyTable title="RV family" fam={report.holm_rv_SCREEN} highlight={target} />
        </div>
      </details>

      {protocol?.models && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-semibold text-ink2">Model definitions (frozen protocol)</summary>
          <dl className="mt-2 space-y-1 text-[11px]">
            {Object.entries(protocol.models).map(([k, v]) => (
              <div key={k}>
                <dt className="inline font-semibold text-ink">{k}: </dt>
                <dd className="inline text-ink2">{v}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </Panel>
  );
}

/* ================================================================ 7. evolution */

function evoTone(status: string): Tone {
  const s = status.toLowerCase();
  if (s.startsWith("challenger")) return "info";
  if (s.startsWith("rejected")) return "bad";
  return "neutral";
}

export function EvolutionPanel({ poll, protocol }: { poll: Poll<EvolutionResp>; protocol?: ForecastProtocol }) {
  const ev = protocol?.evolution;
  return (
    <Panel id="evolution" title="Controlled model evolution" subtitle={poll.data?.label}>
      {ev && (
        <div className="mb-3 space-y-1 rounded-md border border-line2 bg-panel2 p-3 text-xs">
          {ev.outcome_of_acceptance && (
            <p className="font-semibold text-ink">
              <span className="text-warn">Challengers never replace the champion automatically.</span> <span className="font-normal text-ink2">Protocol: {ev.outcome_of_acceptance}</span>
            </p>
          )}
          {ev.candidate_space && (
            <p className="text-ink2">
              <span className="text-muted">Candidate space: </span>
              {ev.candidate_space}
            </p>
          )}
          {ev.trial_accounting && (
            <p className="text-ink2">
              <span className="text-muted">Trial accounting: </span>
              {ev.trial_accounting}
            </p>
          )}
          {ev.promotion && (
            <p className="text-ink2">
              <span className="text-muted">Promotion: </span>
              {ev.promotion}
            </p>
          )}
        </div>
      )}
      <FState poll={poll} what="evolution report">
        {(d) => (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <Kpi label="Champion (frozen)" value={d.champion} />
              <Kpi label="Candidates" value={d.results.length} />
              <Kpi label="Challengers" value={d.results.filter((r) => r.status.startsWith("challenger")).length} tone="up" />
              <Kpi label="Replaced champion" value={d.results.filter((r) => r.replaces_champion).length} sub="always 0 by rule" />
            </div>
            <p className="text-[11px] text-muted">Rule (report): {d.rule}</p>
            {d.trials_by_target && (
              <div className="flex flex-wrap gap-2 text-xs">
                {Object.entries(d.trials_by_target).map(([t, n]) => (
                  <span key={t} className="rounded border border-line2 px-2 py-0.5">
                    {t}: <span className="font-semibold tnum">{n}</span> trials
                  </span>
                ))}
              </div>
            )}
            <TableWrap label="Evolution candidates">
              <table className="data">
                <thead>
                  <tr>
                    <th>target</th>
                    <th>spec</th>
                    <th className="num">SCREEN Δ vs champion</th>
                    <th className="num">SCREEN 95% CI</th>
                    <th className="num">p_better</th>
                    <th className="num">p threshold</th>
                    <th className="num">DEV Δ</th>
                    <th className="num">trial #</th>
                    <th>status</th>
                    <th>replaces champion</th>
                  </tr>
                </thead>
                <tbody>
                  {d.results.map((r, i) => (
                    <tr key={i}>
                      <td>{r.target}</td>
                      <td className="max-w-[340px] !whitespace-normal">
                        <Kv data={r.spec} />
                      </td>
                      <td className="num">{fxSigned(r.screen_vs_champion?.mean, 5)}</td>
                      <td className="num text-ink2">{r.screen_vs_champion ? interval(r.screen_vs_champion.lo, r.screen_vs_champion.hi) : "—"}</td>
                      <td className="num">{fx(r.screen_vs_champion?.p_better, 4)}</td>
                      <td className="num">{fx(r.p_threshold, 5)}</td>
                      <td className="num">{fxSigned(r.dev_vs_champion?.mean, 5)}</td>
                      <td className="num">{fmtAny(r.trials_for_target)}</td>
                      <td className="!whitespace-normal">
                        <Tag tone={evoTone(r.status)}>{r.status}</Tag>
                      </td>
                      <td>{r.replaces_champion ? <Tag tone="bad">yes</Tag> : <span className="text-muted">no</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          </div>
        )}
      </FState>
    </Panel>
  );
}

