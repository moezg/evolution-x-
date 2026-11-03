"use client";
import { useMemo, useState, type ReactNode } from "react";
import { niceTicks } from "@/components/charts";
import { Kv, SectionState, TableWrap, TONE_CLS, VerdictBadge } from "@/components/observatory";
import { Hash, Prov } from "@/components/research";
import { EmptyState, ErrorNote, Legend, Panel } from "@/components/ui";
import { useWidth } from "@/components/useWidth";
import { fmtAny, fmtTime, usd } from "@/lib/format";
import { usePoll, type Poll } from "@/lib/hooks";
import { fx, type Paired, type Tone } from "@/lib/observatory";
import {
  binLabel,
  CLASS_TONE,
  CRITERIA_LABEL,
  memoryTone,
  pctAbs,
  pctOf,
  ppOf,
  SATURATION_FRAC,
  stats,
  uniq,
  type CascadeConfig,
  type CascadeCost,
  type CascadeReport,
  type CascadeResp,
  type CascadeRun,
  type CascadeThreshold,
  type DeleveragingTrace,
  type Knowledge,
  type PairResp,
  type RunIndexRow,
  type TraceEvent,
} from "@/lib/cascade";

/* ================================================================ primitives */

const COL_A = "#3987e5";
const COL_B = "#9085e9";
const COL_PRIMARY = "#fab219";
const COL_SECONDARY = "#e66767";
const GRID = "#2c2c2a";
const MUTED = "#9a9890";

export type Role = "confirmatory" | "pilot" | "exploratory";
export interface PairSel {
  role: Role;
  config: string;
  seed: number;
}

function Tag({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-bold tracking-wider ${TONE_CLS[tone]}`}>
      {children}
    </span>
  );
}

function ClassBadge({ label }: { label?: string }) {
  if (!label) return <span className="text-[11px] text-muted">—</span>;
  const tone = CLASS_TONE[label] ?? "neutral";
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold ${TONE_CLS[tone]} ${label === "cascade" ? "ring-1 ring-down" : ""}`}
    >
      {label.replace(/_/g, " ")}
    </span>
  );
}

function RoleTag({ role }: { role: Role | string }) {
  if (role === "pilot") return <Tag tone="weak">EXPLORATORY PILOT</Tag>;
  if (role === "exploratory") return <Tag tone="weak">EXPLORATORY</Tag>;
  return <Tag tone="good">CONFIRMATORY</Tag>;
}

function Check({ v }: { v: boolean | undefined | null }) {
  if (v === undefined || v === null) return <span className="text-muted">—</span>;
  return v ? <span className="text-up">✓ yes</span> : <span className="text-muted">✗ no</span>;
}

function Dl({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words text-right text-ink tnum [overflow-wrap:anywhere]">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function costLine(c: CascadeCost | undefined): string {
  if (!c) return "—";
  const parts = [`${fmtAny(c.runs)} runs`];
  if (c.wall_s !== undefined) parts.push(`${fx(c.wall_s)} s wall`);
  if (c.cpu_s_sum !== undefined) parts.push(`${fx(c.cpu_s_sum)} CPU-s`);
  parts.push(`${fmtAny(c.llm_calls ?? 0)} LLM calls`);
  return parts.join(" · ");
}

function pctInterval(lo: unknown, hi: unknown): string {
  if (typeof lo !== "number" || typeof hi !== "number") return "—";
  return `[${(lo * 100).toFixed(0)}%, ${(hi * 100).toFixed(0)}%]`;
}

function ppInterval(lo: unknown, hi: unknown): string {
  if (typeof lo !== "number" && typeof hi !== "number") return "—";
  const f = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? (v * 100).toFixed(2) : "—");
  return `[${f(lo)}, ${f(hi)}] pp`;
}

/* ================================================================ 1. header */

export function CascadeHeader({ d }: { d: CascadeResp }) {
  const p = d.protocol;
  const px = d.protocol_exploratory;
  const shas: [string, string | undefined, Role][] = [
    ["confirmatory", d.confirmatory?.protocol_sha256, "confirmatory"],
    ["pilot", d.pilot?.protocol_sha256, "pilot"],
    ["exploratory (c2x)", d.exploratory?.protocol_sha256, "exploratory"],
  ];
  const pilotDiffers = d.pilot?.protocol_sha256 && d.confirmatory?.protocol_sha256 && d.pilot.protocol_sha256 !== d.confirmatory.protocol_sha256;
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-warn/60 bg-warn/10 px-3 py-2 sm:px-4" role="note">
        <p className="text-sm font-semibold text-warn">SYNTHETIC simulator research — no historical data, no holdout, 0 LLM calls, no trading claims</p>
        {p.data_policy && <p className="mt-0.5 text-xs text-ink2">{p.data_policy}</p>}
      </div>
      <Panel id="question" title="Question (pre-registered)" subtitle={`${p.name}${p.written_utc ? ` · written ${fmtTime(p.written_utc)}` : ""}`}>
        <div className="space-y-3 text-xs">
          <p className="text-sm text-ink">{p.question}</p>
          {p.status && <p className="text-muted">{p.status}</p>}
          {!!p.valid_outcomes?.length && (
            <div>
              <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Four valid outcomes (all equally reportable)</h3>
              <ol className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                {p.valid_outcomes.map((o, i) => (
                  <li key={o} className="rounded border border-line bg-panel2 px-2 py-1 text-ink2">
                    <span className="mr-1 text-muted">{i + 1}.</span>
                    {o}
                  </li>
                ))}
              </ol>
            </div>
          )}
          {p.design?.arms && (
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              {Object.entries(p.design.arms).map(([arm, txt]) => (
                <div key={arm} className={`rounded border p-2 ${arm === "B" ? "border-[#9085e9]/60 bg-[#9085e9]/10" : "border-line bg-panel2"}`}>
                  <div className="mb-0.5 flex flex-wrap items-center gap-2">
                    <span className="font-semibold" style={{ color: arm === "A" ? COL_A : arm === "B" ? COL_B : undefined }}>
                      Arm {arm}
                    </span>
                    {arm === "B" && <Tag tone="info">NONPHYSICAL COUNTERFACTUAL</Tag>}
                  </div>
                  <p className="text-ink2">{txt}</p>
                </div>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted">
            <span>Protocol sha256 recorded in each report:</span>
            {shas.map(([lbl, sha, role]) => (
              <span key={lbl} className="flex flex-wrap items-center gap-1 whitespace-nowrap">
                <RoleTag role={role} /> {lbl} <Hash v={sha} n={12} label={`${lbl} protocol sha256`} />
              </span>
            ))}
          </div>
          {pilotDiffers && (
            <p className="text-[11px] text-warn">
              The pilot&apos;s protocol sha256 differs from the confirmatory one: the frozen file was amended after the pilot (amendment_2:{" "}
              {p.amendment_2?.before ?? "see below"}).
            </p>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted">
            <span>Cost —</span>
            <span>confirmatory: {costLine(d.confirmatory?.cost)}</span>
            <span>pilot: {costLine(d.pilot?.cost)}</span>
            <span>exploratory: {costLine(d.exploratory?.cost)}</span>
          </div>
          <details>
            <summary className="cursor-pointer text-ink2">Hypotheses, causal definitions, classification rule, amendments</summary>
            <div className="mt-2 space-y-3">
              {p.hypotheses && (
                <ul className="space-y-1">
                  {Object.entries(p.hypotheses).map(([id, h]) => (
                    <li key={id} className="rounded border border-line bg-panel2 p-2">
                      <code className="font-semibold text-ink">{id}</code> <span className="text-ink2">{h.claim}</span>
                      {h.supported_if && <p className="mt-0.5 text-ink2"><span className="text-muted">supported if:</span> {h.supported_if}</p>}
                      {h.null_H0 && <p className="mt-0.5 text-ink2"><span className="text-muted">H0:</span> {h.null_H0}</p>}
                      {h.report && <p className="mt-0.5 text-ink2"><span className="text-muted">report:</span> {h.report}</p>}
                    </li>
                  ))}
                </ul>
              )}
              {p.causal_definitions && (
                <ul className="space-y-0.5">
                  {Object.entries(p.causal_definitions).map(([k, v]) => (
                    <li key={k}>
                      <code className="text-ink">{k}</code>: <span className="text-ink2">{v}</span>
                    </li>
                  ))}
                </ul>
              )}
              {p.classification_rule && <p className="text-ink2"><span className="text-muted">classification rule:</span> {p.classification_rule}</p>}
              {p.statistics && <p className="text-ink2"><span className="text-muted">statistics:</span> {p.statistics}</p>}
              {p.stopping_rule && <p className="text-ink2"><span className="text-muted">stopping rule:</span> {p.stopping_rule}</p>}
              {(["amendment_1", "amendment_2"] as const).map((k) =>
                p[k] ? (
                  <div key={k} className="rounded border border-line bg-panel2 p-2">
                    <div className="mb-1 font-semibold text-ink">
                      {k} <span className="font-normal text-muted">{fmtTime(p[k]?.written_utc)}</span>
                    </div>
                    <Kv data={p[k] as Record<string, unknown>} />
                  </div>
                ) : null,
              )}
              {px && (
                <p className="text-ink2">
                  <span className="text-muted">Exploratory protocol {px.name}:</span> {px.status}
                </p>
              )}
            </div>
          </details>
        </div>
      </Panel>
    </div>
  );
}

/* ================================================================ 2. configuration grid */

function ReachedSize({ c }: { c: CascadeConfig }) {
  const s = stats(c.whale_position_btc_at_shock);
  if (!s) return <span className="text-muted">—</span>;
  const frac = s.mean / c.whale_btc;
  const sat = frac < SATURATION_FRAC;
  return (
    <span className={sat ? "font-semibold text-warn" : undefined} title={(c.whale_position_btc_at_shock ?? []).map((v) => fx(v)).join(", ")}>
      {fx(s.mean, 0)} BTC{s.n > 1 && <span className="font-normal text-muted"> ({fx(s.min, 0)}–{fx(s.max, 0)})</span>}
      {sat && <span className="ml-auto mt-0.5 block w-fit max-w-full rounded border border-warn/60 bg-warn/15 px-1 text-[10px]">SATURATED: {(frac * 100).toFixed(0)}% of nominal</span>}
    </span>
  );
}

function PairedPP({ p }: { p: Paired | undefined }) {
  if (!p) return <span className="text-muted">—</span>;
  return (
    <span>
      <span className="font-semibold">{ppOf(p.mean)}</span>
    </span>
  );
}

export function ConfigCard({ id, c, onExplore }: { id: string; c: CascadeConfig; onExplore?: () => void }) {
  const n = c.n_seeds;
  const inc = c.incremental_drop;
  return (
    <article className="min-w-0 space-y-2 rounded-md border border-line bg-panel2 p-3" aria-label={`configuration ${id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-ink">{fmtAny(c.whale_btc)} BTC nominal</div>
          <div className="font-mono text-[11px] text-muted">{id}</div>
        </div>
        <ClassBadge label={c.classification?.label} />
      </div>
      <Dl
        rows={[
          ["reached whale position", <ReachedSize key="r" c={c} />],
          [
            "seeds w/ secondary liquidation",
            <span key="s">
              <span className="font-semibold">
                {c.seeds_with_secondary_liquidation}/{n}
              </span>{" "}
              <span className="text-muted">Wilson 95% {pctInterval(c.wilson95?.[0], c.wilson95?.[1])}</span>
            </span>,
          ],
          ["seeds with chain", `${c.seeds_with_chain}/${n}`],
          ["incremental drop A−B (mean)", <PairedPP key="i" p={inc} />],
          ["  bootstrap 95%", ppInterval(inc?.lo, inc?.hi)],
          ["  t-interval", ppInterval(inc?.t_lo, inc?.t_hi)],
          ["arm-B drop (mean max adverse)", pctOf(c.armB_max_drop_mean)],
          ["first-tick direct impact (mean)", pctOf(c.direct_impact_mean)],
          ["secondary breaches A / B (mean)", `${fx(c.secondary_breaches_A_mean)} / ${fx(c.secondary_breaches_B_mean)}`],
          ["all pre-shock identical", <Check key="p" v={c.all_pre_shock_identical} />],
        ]}
      />
      {c.classification?.criteria && (
        <details className="text-[11px]">
          <summary className="cursor-pointer text-ink2">Criteria (a)–(d)</summary>
          <ul className="mt-1 space-y-0.5">
            {Object.entries(c.classification.criteria).map(([k, v]) => (
              <li key={k} className="flex justify-between gap-2">
                <span className="text-ink2">{CRITERIA_LABEL[k] ?? k}</span>
                <Check v={v} />
              </li>
            ))}
          </ul>
        </details>
      )}
      {onExplore && (
        <button type="button" className="btn btn-sm w-full" onClick={onExplore}>
          Explore paired runs →
        </button>
      )}
    </article>
  );
}

export function ConfigGrid({ rep, role, onExplore }: { rep: CascadeReport; role: Role; onExplore: (config: string) => void }) {
  const entries = Object.entries(rep.configs ?? {});
  const lus = uniq(entries.map(([, c]) => c.leverage_use)).sort((a, b) => a - b);
  const sizes = uniq(entries.map(([, c]) => c.whale_btc)).sort((a, b) => a - b);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <RoleTag role={role} />
        <Prov kind="SYNTHETIC" />
        <span>{rep.label}</span>
        <span>· {fmtTime(rep.created_utc)}</span>
        <span>· seeds {uniq(rep.run_index.map((r) => r.seed)).join(", ")}</span>
      </div>
      {lus.map((lu) => (
        <section key={lu} aria-label={`leverage_use ${lu}`}>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">leverage_use {lu.toFixed(1)}</h3>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            {sizes.map((sz) => {
              const e = entries.find(([, c]) => c.leverage_use === lu && c.whale_btc === sz);
              return e ? (
                <ConfigCard key={e[0]} id={e[0]} c={e[1]} onExplore={() => onExplore(e[0])} />
              ) : (
                <div key={sz} className="rounded-md border border-dashed border-line2 p-3 text-xs text-muted">
                  {sz} BTC · lu {lu}: not run
                </div>
              );
            })}
          </div>
        </section>
      ))}
      <p className="text-[11px] text-muted">
        Incremental drop = paired A−B difference of the maximum adverse move in percentage points of the pre-shock mid (negative = deeper with secondary
        liquidations). Reached size is the external whale&apos;s position at the shock; highlighted when its mean is below {SATURATION_FRAC * 100}% of nominal.
      </p>
    </div>
  );
}

/* ================================================================ 3. threshold */

export function ThresholdPanel({ th, configs }: { th: Record<string, CascadeThreshold>; configs: Record<string, CascadeConfig> }) {
  return (
    <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
      {Object.entries(th).map(([lu, t]) => {
        const luNum = Number(lu.replace(/^lu/, ""));
        const bySize = Object.entries(t.seeds_with_secondary_by_size ?? {});
        const bracket = t.onset_bracket_btc;
        return (
          <div key={lu} className="min-w-0 space-y-2 rounded-md border border-line bg-panel2 p-3 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-semibold text-ink">leverage_use {Number.isFinite(luNum) ? luNum.toFixed(1) : lu}</span>
              <VerdictBadge v={t.statement} />
            </div>
            <Dl
              rows={[
                ["onset bracket (BTC)", Array.isArray(bracket) ? `(${fmtAny(bracket[0])}, ${fmtAny(bracket[1])})` : "none"],
                ["monotone in size", <Check key="m" v={t.monotone_in_size} />],
                ["shape", t.shape ?? "—"],
              ]}
            />
            <TableWrap label={`seeds with secondary liquidation by size, ${lu}`}>
              <table className="data">
                <thead>
                  <tr>
                    <th>nominal BTC</th>
                    <th>reached BTC (mean, min–max)</th>
                    <th className="num">seeds w/ secondary</th>
                  </tr>
                </thead>
                <tbody>
                  {bySize.map(([sz, k]) => {
                    const c = Object.values(configs).find((x) => String(x.whale_btc) === sz && x.leverage_use === luNum);
                    return (
                      <tr key={sz}>
                        <td className="num">{sz}</td>
                        <td>{c ? <ReachedSize c={c} /> : "—"}</td>
                        <td className="num">
                          {k}
                          {c ? `/${c.n_seeds}` : ""}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </TableWrap>
          </div>
        );
      })}
    </div>
  );
}

/* ================================================================ 4. pair explorer */

interface XY {
  name: string;
  color: string;
  dashed?: boolean;
  x: number[];
  y: number[];
}

/** Synthetic mid trajectory (% vs pre-shock mid) of both arms, x in seconds relative to the primary liquidation. */
function TrajectoryChart({ series, band, events, label }: { series: XY[]; band?: [number, number] | null; events: { x: number; color: string; title: string }[]; label: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const height = 260;
  const m = { l: 50, r: 10, t: 18, b: 34 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = height - m.t - m.b;
  const allX = series.flatMap((s) => s.x);
  const allY = series.flatMap((s) => s.y).concat([0]);
  const x0 = allX.length ? Math.min(...allX) : 0;
  const x1 = allX.length ? Math.max(...allX) : 1;
  let y0 = Math.min(...allY);
  let y1 = Math.max(...allY);
  const pad = (y1 - y0 || 1) * 0.06;
  y0 -= pad;
  y1 += pad;
  const sx = (v: number) => m.l + ((v - x0) / (x1 - x0 || 1)) * iw;
  const sy = (v: number) => m.t + ih - ((v - y0) / (y1 - y0 || 1)) * ih;
  const yt = niceTicks(y0, y1, 5);
  const xt = niceTicks(x0, x1, Math.max(3, Math.floor(iw / 80)));
  const paths = useMemo(
    () => series.map((s) => s.x.map((xv, i) => `${i ? "L" : "M"}${sx(xv).toFixed(1)},${sy(s.y[i]).toFixed(1)}`).join("")),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [series, width, y0, y1, x0, x1],
  );
  const base = series[0];
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!base?.x.length) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const xv = x0 + ((e.clientX - rect.left - m.l) / iw) * (x1 - x0);
    let best = 0;
    for (let i = 1; i < base.x.length; i++) if (Math.abs(base.x[i] - xv) < Math.abs(base.x[best] - xv)) best = i;
    setHover(best);
  };
  const hx = hover !== null && base ? base.x[hover] : null;
  return (
    <div ref={ref} className="relative w-full">
      <svg width={width} height={height} role="img" aria-label={label} className="block" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {band && (
          <g>
            <rect x={sx(band[0])} y={m.t} width={Math.max(1, sx(band[1]) - sx(band[0]))} height={ih} fill={COL_PRIMARY} opacity={0.08} />
            <line x1={sx(band[0])} x2={sx(band[0])} y1={m.t} y2={m.t + ih} stroke={COL_PRIMARY} strokeDasharray="3 3" />
            <line x1={sx(band[1])} x2={sx(band[1])} y1={m.t} y2={m.t + ih} stroke={COL_PRIMARY} strokeDasharray="3 3" />
            <text x={sx(band[0]) + 3} y={m.t - 6} fontSize={10} fill={COL_PRIMARY}>
              primary selling {fx(band[0], 0)}…{fx(band[1], 0)} s
            </text>
          </g>
        )}
        {yt.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke={GRID} />
            <text x={m.l - 5} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">
              {+t.toFixed(3)}%
            </text>
          </g>
        ))}
        {y0 < 0 && y1 > 0 && <line x1={m.l} x2={m.l + iw} y1={sy(0)} y2={sy(0)} stroke="#6a6964" strokeDasharray="3 3" />}
        {xt.map((t) => (
          <text key={t} x={sx(t)} y={m.t + ih + 14} textAnchor="middle" fontSize={10} fill={MUTED} className="tnum">
            {t > 0 ? `+${t}` : t}
          </text>
        ))}
        <text x={m.l + iw} y={height - 3} textAnchor="end" fontSize={10} fill={MUTED}>
          s relative to primary liquidation
        </text>
        {events.map((ev, i) => (
          <g key={i}>
            <line x1={sx(ev.x)} x2={sx(ev.x)} y1={m.t} y2={m.t + ih} stroke={ev.color} strokeWidth={1} opacity={0.6} />
            <path d={`M${sx(ev.x)},${m.t + ih} l-4,7 l8,0 z`} fill={ev.color}>
              <title>{ev.title}</title>
            </path>
          </g>
        ))}
        {paths.map((d, i) => (
          <path key={series[i].name} d={d} fill="none" stroke={series[i].color} strokeWidth={series[i].dashed ? 1.5 : 3} strokeDasharray={series[i].dashed ? "5 4" : undefined} />
        ))}
        {hx !== null && <line x1={sx(hx)} x2={sx(hx)} y1={m.t} y2={m.t + ih} stroke="#6a6964" pointerEvents="none" />}
      </svg>
      {hx !== null && hover !== null && (
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-md border border-line2 bg-[#0f0f0e]/95 px-2 py-1.5 text-[11px] shadow-lg"
          style={sx(hx) > width / 2 ? { right: width - sx(hx) + 8 } : { left: sx(hx) + 8 }}
        >
          <div className="text-muted tnum">{hx > 0 ? `+${hx}` : hx} s</div>
          {series.map((s) => (
            <div key={s.name} className="flex gap-2 whitespace-nowrap">
              <span style={{ color: s.color }}>{s.name}</span>
              <span className="ml-auto tnum">{s.y[hover] !== undefined ? `${s.y[hover].toFixed(3)}%` : "—"}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Grouped bars per bin for several series (e.g. arm A / arm B). */
function GroupedBars({ labels, series, label, height = 150, fmt = (v: number) => fx(v) }: { labels: string[]; series: { name: string; color: string; values: number[] }[]; label: string; height?: number; fmt?: (v: number) => string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const m = { l: 40, r: 6, t: 8, b: 30 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = height - m.t - m.b;
  const maxV = Math.max(1, ...series.flatMap((s) => s.values));
  const sy = (v: number) => m.t + ih - (v / maxV) * ih;
  const bw = labels.length ? iw / labels.length : iw;
  const sub = Math.max(0.5, (bw - 1) / Math.max(1, series.length));
  const every = Math.max(1, Math.ceil(labels.length / Math.max(1, Math.floor(iw / 44))));
  const yt = niceTicks(0, maxV, 3);
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label={label} className="block">
        {yt.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke={GRID} />
            <text x={m.l - 5} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">
              {fmt(t)}
            </text>
          </g>
        ))}
        {labels.map((lb, i) => (
          <g key={i}>
            {series.map((s, j) => {
              const v = s.values[i] ?? 0;
              return (
                <rect key={s.name} x={m.l + i * bw + j * sub} y={sy(v)} width={Math.max(0.5, sub - 0.5)} height={Math.max(0, m.t + ih - sy(v))} fill={s.color} opacity={0.9}>
                  <title>{`${lb}: ${s.name} ${fmt(v)}`}</title>
                </rect>
              );
            })}
            {i % every === 0 && (
              <text x={m.l + i * bw} y={m.t + ih + 13} fontSize={10} fill={MUTED} className="tnum">
                {lb}
              </text>
            )}
          </g>
        ))}
        <line x1={m.l} x2={m.l + iw} y1={m.t + ih} y2={m.t + ih} stroke="#383835" />
        <text x={m.l + iw} y={height - 2} textAnchor="end" fontSize={10} fill={MUTED}>
          10 s bins, s relative to primary liquidation
        </text>
      </svg>
    </div>
  );
}

/** Count histogram with the count printed above each bar (one dominant bin must not hide the small ones). */
function HistBars({ labels, values, label }: { labels: string[]; values: number[]; label: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const height = 170;
  const m = { l: 6, r: 6, t: 16, b: 22 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = height - m.t - m.b;
  const maxV = Math.max(1, ...values);
  const bw = labels.length ? iw / labels.length : iw;
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label={label} className="block">
        {values.map((v, i) => {
          const h = v > 0 ? Math.max(2, (v / maxV) * ih) : 0;
          return (
            <g key={i}>
              <rect x={m.l + i * bw + 2} y={m.t + ih - h} width={Math.max(1, bw - 4)} height={h} rx={2} fill={COL_A}>
                <title>{`${labels[i]}: ${v} accounts`}</title>
              </rect>
              <text x={m.l + i * bw + bw / 2} y={m.t + ih - h - 4} textAnchor="middle" fontSize={10} fill={v ? "#f0efec" : MUTED} className="tnum">
                {v}
              </text>
              <text x={m.l + i * bw + bw / 2} y={height - 6} textAnchor="middle" fontSize={bw < 44 ? 8 : 10} fill={MUTED}>
                {labels[i]}
              </text>
            </g>
          );
        })}
        <line x1={m.l} x2={m.l + iw} y1={m.t + ih} y2={m.t + ih} stroke="#383835" />
      </svg>
    </div>
  );
}

/** Leveraged agents' margin distance on a log axis; reference = |max adverse move| of arm A. */
function LeveragedStrip({ rows, refMove }: { rows: { agent: number; distance: number; direction: string; eff_leverage: number }[]; refMove?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const height = 74;
  const m = { l: 12, r: 12, t: 10, b: 22 };
  const iw = Math.max(10, width - m.l - m.r);
  const ds = rows.map((r) => r.distance).filter((d) => d > 0);
  if (refMove && refMove > 0) ds.push(refMove);
  if (!ds.length) return null;
  const lo = Math.log10(Math.min(...ds)) - 0.1;
  const hi = Math.log10(Math.max(...ds)) + 0.1;
  const sx = (v: number) => m.l + ((Math.log10(v) - lo) / (hi - lo || 1)) * iw;
  const cand = [-3, -2, -1, 0, 1, 2].flatMap((e) => [1, 2, 3, 5].map((k) => ({ v: k * 10 ** e, major: k === 1 || k === 3 })));
  let tk = cand.filter((t) => Math.log10(t.v) >= lo && Math.log10(t.v) <= hi);
  if (tk.length > Math.max(3, Math.floor(iw / 50))) tk = tk.filter((t) => t.major);
  const ticks = tk.map((t) => t.v);
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label="Leveraged agents: margin distance at the last pre-shock tick (log scale)" className="block">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={sx(t)} x2={sx(t)} y1={m.t} y2={height - m.b} stroke={GRID} />
            <text x={sx(t)} y={height - 6} textAnchor="middle" fontSize={10} fill={MUTED}>
              {+(t * 100).toPrecision(2)}%
            </text>
          </g>
        ))}
        {refMove && refMove > 0 && (
          <g>
            <line x1={sx(refMove)} x2={sx(refMove)} y1={m.t - 4} y2={height - m.b} stroke={COL_PRIMARY} strokeDasharray="3 3" />
            <title>|max adverse move| arm A = {(refMove * 100).toFixed(2)}%</title>
          </g>
        )}
        {rows.map((r, i) =>
          r.distance > 0 ? (
            <circle key={r.agent} cx={sx(r.distance)} cy={m.t + 6 + (i % 5) * 7} r={4} fill={r.direction === "down" ? COL_SECONDARY : COL_B} stroke="#161615">
              <title>{`agent ${r.agent}: ${(r.distance * 100).toFixed(2)}% ${r.direction}, eff. leverage ${r.eff_leverage.toFixed(1)}×`}</title>
            </circle>
          ) : null,
        )}
      </svg>
    </div>
  );
}

function relS(t: number | null | undefined, ref: number): number | null {
  return typeof t === "number" ? (t - ref) / 1000 : null;
}

function sec(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : ""}${+v.toFixed(1)} s`;
}

function PairView({ pair, rep, protocolSha, shockAtS }: { pair: PairResp; rep: CascadeReport | null; protocolSha?: string; shockAtS?: number }) {
  const A = pair.arms.A;
  const B = pair.arms.B;
  const arms = [
    ["A", A, COL_A],
    ["B", B, COL_B],
  ] as const;
  const ref = A?.primary_liquidation_t ?? B?.primary_liquidation_t ?? 0;
  const pe = rep?.configs?.[pair.config]?.pairs?.find((p) => p.seed === pair.seed);

  const series: XY[] = arms.flatMap(([k, r, col]) =>
    r?.trajectory
      ? [{ name: `arm ${k}`, color: col, dashed: k === "B", x: r.trajectory.mid_rel.map((_, i) => (r.trajectory!.t0_ms + i * 1000 - r.primary_liquidation_t) / 1000), y: r.trajectory.mid_rel.map((v) => v * 100) }]
      : [],
  );
  const ta = A?.trajectory?.mid_rel;
  const tb = B?.trajectory?.mid_rel;
  let divergeIdx = -1;
  if (ta && tb) {
    const n = Math.max(ta.length, tb.length);
    for (let i = 0; i < n; i++)
      if (ta[i] !== tb[i]) {
        divergeIdx = i;
        break;
      }
  }
  const identical = !!ta && !!tb && divergeIdx === -1;
  const ps = A?.primary_selling;
  const band: [number, number] | null = ps && typeof ps.first_t === "number" && typeof ps.last_t === "number" ? [(ps.first_t - ref) / 1000, (ps.last_t - ref) / 1000] : null;
  const events = arms.flatMap(([k, r, col]) =>
    (r?.trace ?? [])
      .filter((e) => e.type === "secondary_liquidation")
      .map((e) => ({ x: (e.t - ref) / 1000, color: k === "A" ? COL_SECONDARY : col, title: `arm ${k}: secondary liquidation of agent ${e.agent} (${e.kind ?? "?"}) at ${sec((e.t - ref) / 1000)}` })),
  );

  // 10 s bins start at the scheduled shock (protocol shock_at_s); label them relative to the primary liquidation.
  const nBins = Math.max(A?.primary_selling?.btc_per_10s?.length ?? 0, A?.propagation_10s?.breaches?.length ?? 0, B?.propagation_10s?.breaches?.length ?? 0);
  const binStart = typeof shockAtS === "number" ? (shockAtS * 1000 - ref) / 1000 : 0;
  const binLabels = Array.from({ length: nBins }, (_, i) => `${binStart + i * 10 >= 0 ? "+" : ""}${+(binStart + i * 10).toFixed(0)}`);

  const trace: (TraceEvent & { arm: string })[] = arms
    .flatMap(([k, r]) => (r?.trace ?? []).map((e) => ({ ...e, arm: k })))
    .sort((a, b) => a.t - b.t || a.arm.localeCompare(b.arm));

  const prop = (r: CascadeRun | undefined, f: "breaches" | "secondary_liquidations") => r?.propagation_10s?.[f] ?? [];
  const propTotal = arms.reduce((s, [, r]) => s + prop(r, "breaches").reduce((a, b) => a + b, 0) + prop(r, "secondary_liquidations").reduce((a, b) => a + b, 0), 0);

  const mp = A?.margin_pre ?? B?.margin_pre;
  const edges = mp?.histogram_edges ?? [];
  const hist = mp?.histogram_all ?? [];
  const lev = [...(mp?.leveraged ?? [])].sort((a, b) => a.distance - b.distance);
  const marginSame = JSON.stringify(A?.margin_pre) === JSON.stringify(B?.margin_pre);

  const diff = (a: unknown, b: unknown) => (typeof a === "number" && typeof b === "number" ? a - b : undefined);

  return (
    <div className="space-y-4">
      {/* a. trajectory */}
      <section aria-label="Synthetic price trajectory" className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold">a. Synthetic mid trajectory, both arms</h3>
          <Prov kind="SYNTHETIC" />
          <RoleTag role={pair.role} />
        </div>
        <Legend
          items={[
            { label: "arm A (normal mechanics)", color: COL_A },
            { label: "arm B (secondary execution suppressed)", color: COL_B, dashed: true },
            { label: "primary selling start / end", color: COL_PRIMARY, dashed: true },
            { label: "secondary liquidation", color: COL_SECONDARY, shape: "dot" },
          ]}
        />
        {series.length ? (
          <TrajectoryChart series={series} band={band} events={events} label={`Mid relative to pre-shock mid, ${pair.config}, seed ${pair.seed}`} />
        ) : (
          <EmptyState title="No trajectory in this run" />
        )}
        <p className="text-[11px] text-muted">
          y = venue-average mid relative to the last pre-shock mid (%). x = seconds relative to the primary liquidation tick (
          {A ? `t = ${fx(A.primary_liquidation_t / 1000, 0)} s` : "—"}); 1 sample per second.{" "}
          {identical ? (
            <span className="text-ink2">Arms A and B are identical over the whole window — the dashed B line lies exactly on top of A.</span>
          ) : divergeIdx >= 0 && series[0] ? (
            <span className="text-ink2">The arms diverge at {sec(series[0].x[divergeIdx])}.</span>
          ) : null}{" "}
          {events.length === 0 && "No secondary liquidations in either arm."}
        </p>
      </section>

      {/* b. timeline */}
      <section aria-label="Timeline of executions" className="space-y-2">
        <h3 className="text-sm font-semibold">b. Timeline of executions (first {nBins * 10} s after the scheduled shock)</h3>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <div className="min-w-0">
            <p className="mb-1 text-[11px] text-muted">Primary (whale) forced selling, BTC per 10 s</p>
            <GroupedBars
              labels={binLabels}
              series={arms.map(([k, r, col]) => ({ name: `arm ${k}`, color: col, values: r?.primary_selling?.btc_per_10s ?? [] }))}
              label="Primary forced selling BTC per 10 s, arms A and B"
            />
          </div>
          <div className="min-w-0">
            <p className="mb-1 text-[11px] text-muted">Secondary breaches and secondary liquidations per 10 s</p>
            <GroupedBars
              labels={binLabels}
              series={[
                { name: "A breaches", color: COL_A, values: prop(A, "breaches") },
                { name: "A secondary liquidations", color: COL_SECONDARY, values: prop(A, "secondary_liquidations") },
                { name: "B breaches", color: COL_B, values: prop(B, "breaches") },
                { name: "B secondary liquidations", color: "#f0a3c2", values: prop(B, "secondary_liquidations") },
              ]}
              label="Breaches and secondary liquidations per 10 s, arms A and B"
              fmt={(v) => String(+v.toFixed(1))}
            />
            {propTotal === 0 && <p className="text-[11px] text-muted">All bins are 0 in both arms: no breach and no secondary liquidation in this pair.</p>}
          </div>
        </div>
        <Legend
          items={[
            { label: "arm A", color: COL_A, shape: "dot" },
            { label: "arm B", color: COL_B, shape: "dot" },
            { label: "A secondary liquidations", color: COL_SECONDARY, shape: "dot" },
            { label: "B secondary liquidations", color: "#f0a3c2", shape: "dot" },
          ]}
        />
        <details open={trace.length <= 12}>
          <summary className="cursor-pointer text-xs text-ink2">Event trace ({trace.length} events, both arms)</summary>
          <TableWrap label="Event trace">
            <div className="max-h-72 overflow-y-auto">
              <table className="data">
                <thead>
                  <tr>
                    <th>arm</th>
                    <th>type</th>
                    <th className="num">t vs primary</th>
                    <th className="num">agent</th>
                    <th>kind</th>
                    <th className="num">generation</th>
                    <th>executed</th>
                    <th className="num">mid_rel</th>
                  </tr>
                </thead>
                <tbody>
                  {trace.map((e, i) => (
                    <tr key={i}>
                      <td style={{ color: e.arm === "A" ? COL_A : COL_B }}>{e.arm}</td>
                      <td>{e.type.replace(/_/g, " ")}</td>
                      <td className="num">{sec((e.t - ref) / 1000)}</td>
                      <td className="num">{e.agent}</td>
                      <td>{e.kind ?? "—"}</td>
                      <td className="num">{fmtAny(e.generation)}</td>
                      <td>{e.executed === undefined ? "—" : e.executed ? "yes" : "no"}</td>
                      <td className="num">{pctOf(e.mid_rel, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </TableWrap>
        </details>
      </section>

      {/* c + e. counts and impact */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section aria-label="Liquidations and breaches per arm" className="min-w-0 space-y-2">
          <h3 className="text-sm font-semibold">c. Liquidations and breaches per arm</h3>
          <TableWrap label="Liquidations and breaches per arm">
            <table className="data">
              <thead>
                <tr>
                  <th>metric</th>
                  <th className="num" style={{ color: COL_A }}>
                    A
                  </th>
                  <th className="num" style={{ color: COL_B }}>
                    B
                  </th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["whale position at shock (BTC)", (r: CascadeRun) => fx(r.whale_position_btc_at_shock)],
                    ["primary selling: BTC / duration", (r: CascadeRun) => `${fx(r.primary_selling?.btc)} / ${fmtAny(r.primary_selling?.duration_s)} s`],
                    ["primary forced notional", (r: CascadeRun) => (typeof r.primary_forced_notional_usd === "number" ? `${usd(r.primary_forced_notional_usd / 1e6, 1)}M` : "—")],
                    ["secondary breaches", (r: CascadeRun) => fmtAny(r.secondary_breaches)],
                    ["secondary liquidations (agents)", (r: CascadeRun) => `${fmtAny(r.secondary_liquidations)} (${r.secondary_liquidated_agents?.length ?? 0})`],
                    ["secondary forced notional", (r: CascadeRun) => usd(r.secondary_forced_notional_usd, 0)],
                    ["first secondary breach", (r: CascadeRun) => sec(r.first_secondary_breach_s)],
                    ["first secondary liquidation", (r: CascadeRun) => sec(r.first_secondary_liquidation_s)],
                    ["max breach generation", (r: CascadeRun) => fmtAny(r.max_breach_generation)],
                    ["leveraged stop-losses / noise panic sales", (r: CascadeRun) => `${fmtAny(r.stop_losses_leveraged)} / ${fmtAny(r.panic_sales)}`],
                    ["circuit breakers in window", (r: CascadeRun) => fmtAny(r.circuit_breakers_window)],
                    ["half-recovery", (r: CascadeRun) => `${sec(r.half_recovery_s)}${r.half_recovery_censored ? " (censored)" : ""}`],
                    ["1m vol bps: pre → window", (r: CascadeRun) => `${fx(r.volatility_1m_bps?.pre)} → ${fx(r.volatility_1m_bps?.window)}`],
                    ["median spread bps: pre → window", (r: CascadeRun) => `${fx(r.spread_median_bps?.pre)} → ${fx(r.spread_median_bps?.window)}`],
                  ] as [string, (r: CascadeRun) => string][]
                ).map(([lbl, f]) => (
                  <tr key={lbl}>
                    <td>{lbl}</td>
                    <td className="num">{A ? f(A) : "—"}</td>
                    <td className="num">{B ? f(B) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
          {pe ? (
            <Dl
              rows={[
                ["induced breaches (A not in B)", pe.induced_breaches?.length ? pe.induced_breaches.join(", ") : "none"],
                ["chain observed", <Check key="c" v={pe.chain_observed} />],
                ["first divergence A vs B", pe.first_divergence_s === null || pe.first_divergence_s === undefined ? "none (trade hashes identical)" : sec(pe.first_divergence_s)],
                ["pre-shock identical", <Check key="p" v={pe.pre_shock_identical} />],
              ]}
            />
          ) : (
            <p className="text-[11px] text-muted">No pairs entry for seed {pair.seed} in the {pair.role} report.</p>
          )}
        </section>

        <section aria-label="Incremental impact" className="min-w-0 space-y-2">
          <h3 className="text-sm font-semibold">e. Incremental impact attributable to secondary liquidations (A − B)</h3>
          <TableWrap label="Incremental impact">
            <table className="data">
              <thead>
                <tr>
                  <th>mid vs pre-shock</th>
                  <th className="num" style={{ color: COL_A }}>
                    A
                  </th>
                  <th className="num" style={{ color: COL_B }}>
                    B
                  </th>
                  <th className="num">A − B</th>
                  <th className="num" title="value recorded in the report's pairs entry">
                    report
                  </th>
                </tr>
              </thead>
              <tbody>
                {["10", "60", "300"].map((k) => (
                  <tr key={k}>
                    <td>+{k} s after primary</td>
                    <td className="num">{pctOf(A?.mid_rel_at?.[k], 3)}</td>
                    <td className="num">{pctOf(B?.mid_rel_at?.[k], 3)}</td>
                    <td className="num font-semibold">{ppOf(diff(A?.mid_rel_at?.[k], B?.mid_rel_at?.[k]), 3)}</td>
                    <td className="num text-muted">{ppOf(pe?.incremental_at?.[k], 3)}</td>
                  </tr>
                ))}
                <tr>
                  <td>max adverse move</td>
                  <td className="num">{pctOf(A?.max_adverse_move, 3)}</td>
                  <td className="num">{pctOf(B?.max_adverse_move, 3)}</td>
                  <td className="num font-semibold">{ppOf(diff(A?.max_adverse_move, B?.max_adverse_move), 3)}</td>
                  <td className="num text-muted">{ppOf(pe?.incremental_drop, 3)}</td>
                </tr>
                <tr>
                  <td>first-tick direct impact</td>
                  <td className="num">{pctOf(A?.direct_impact, 3)}</td>
                  <td className="num">{pctOf(B?.direct_impact, 3)}</td>
                  <td className="num">{ppOf(diff(A?.direct_impact, B?.direct_impact), 3)}</td>
                  <td className="num text-muted">—</td>
                </tr>
                <tr>
                  <td>mid at end of primary selling</td>
                  <td className="num">{pctOf(A?.primary_selling?.mid_rel_at_end, 3)}</td>
                  <td className="num">{pctOf(B?.primary_selling?.mid_rel_at_end, 3)}</td>
                  <td className="num">{ppOf(diff(A?.primary_selling?.mid_rel_at_end, B?.primary_selling?.mid_rel_at_end), 3)}</td>
                  <td className="num text-muted">—</td>
                </tr>
              </tbody>
            </table>
          </TableWrap>
          <p className="text-[11px] text-muted">
            Negative A − B = deeper with secondary liquidations executed. Arm B already contains the full primary forced sale, so it is the causal baseline;
            the first-tick direct impact is descriptive only (amendment_1).
          </p>
        </section>
      </div>

      {/* d. margin distances */}
      <section aria-label="Margin distances" className="space-y-2">
        <h3 className="text-sm font-semibold">d. Margin distance at the last pre-shock tick{marginSame ? " (identical in both arms)" : " (arm A)"}</h3>
        <p className="text-[11px] text-muted">
          {fmtAny(mp?.n_accounts_with_positions)} accounts with positions · min distance {pctAbs(mp?.min_distance_all)} · 5th / 25th / 50th percentile{" "}
          {(mp?.quantiles_all ?? []).map((q) => pctAbs(q)).join(" / ") || "—"} · closest leveraged long (downward){" "}
          {mp?.min_distance_leveraged_down == null ? "none (no leveraged long)" : pctAbs(mp.min_distance_leveraged_down)}
        </p>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <div className="min-w-0">
            <p className="mb-1 text-[11px] text-muted">All accounts: relative price move to maintenance-margin breach</p>
            {hist.length ? (
              <HistBars labels={hist.map((_, i) => binLabel(edges, i))} values={hist} label="Histogram of margin distances, all accounts" />
            ) : (
              <EmptyState title="No histogram" />
            )}
          </div>
          <div className="min-w-0 space-y-1">
            <p className="text-[11px] text-muted">Leveraged agents (log scale); dashed = |max adverse move| of arm A</p>
            <LeveragedStrip rows={lev} refMove={typeof A?.max_adverse_move === "number" ? Math.abs(A.max_adverse_move) : undefined} />
            <Legend
              items={[
                { label: `short — breached by a rise (${lev.filter((r) => r.direction === "up").length})`, color: COL_B, shape: "dot" },
                { label: `long — breached by a fall (${lev.filter((r) => r.direction === "down").length})`, color: COL_SECONDARY, shape: "dot" },
              ]}
            />
            <TableWrap label="Leveraged agents margin distance">
              <div className="max-h-48 overflow-y-auto">
                <table className="data">
                  <thead>
                    <tr>
                      <th className="num">agent</th>
                      <th className="num">distance</th>
                      <th>direction</th>
                      <th className="num">eff. leverage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lev.map((r) => (
                      <tr key={r.agent}>
                        <td className="num">{r.agent}</td>
                        <td className="num">{pctAbs(r.distance)}</td>
                        <td style={{ color: r.direction === "down" ? COL_SECONDARY : COL_B }}>{r.direction === "down" ? "down (long)" : r.direction === "up" ? "up (short)" : r.direction}</td>
                        <td className="num">{fx(r.eff_leverage)}×</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </TableWrap>
          </div>
        </div>
      </section>

      {/* f. reproducibility */}
      <section aria-label="Reproducibility" className="space-y-2">
        <h3 className="text-sm font-semibold">f. Reproducibility</h3>
        <TableWrap label="Fingerprints">
          <table className="data">
            <thead>
              <tr>
                <th>arm</th>
                <th>config</th>
                <th className="num">seed</th>
                <th>run fingerprint</th>
                <th>config fingerprint</th>
              </tr>
            </thead>
            <tbody>
              {arms.map(([k, r]) => (
                <tr key={k}>
                  <td style={{ color: k === "A" ? COL_A : COL_B }}>{k}</td>
                  <td className="font-mono text-[11px]">{r?.config ?? "—"}</td>
                  <td className="num">{r?.seed ?? "—"}</td>
                  <td>
                    <Hash v={r?.run_fingerprint} n={20} />
                  </td>
                  <td>
                    <Hash v={r?.config_fingerprint} n={20} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        <p className="text-[11px] text-muted">
          Protocol sha256 <Hash v={protocolSha} n={64} />
          {A?.run_fingerprint && A.run_fingerprint === B?.run_fingerprint && " · the two arms have equal run fingerprints and different config fingerprints (the arm switch)."}
        </p>
      </section>
    </div>
  );
}

export function PairExplorer({ d, sel, setSel }: { d: CascadeResp; sel: PairSel | null; setSel: (s: PairSel) => void }) {
  const roles = (["confirmatory", "pilot", "exploratory"] as Role[]).filter((r) => (d[r]?.run_index?.length ?? 0) > 0);
  const role = sel?.role && roles.includes(sel.role) ? sel.role : roles[0];
  const idx: RunIndexRow[] = role ? d[role]?.run_index ?? [] : [];
  const configs = uniq(idx.map((r) => r.config));
  const config = sel?.config && configs.includes(sel.config) ? sel.config : configs[0];
  const seeds = uniq(idx.filter((r) => r.config === config).map((r) => r.seed)).sort((a, b) => a - b);
  const seed = sel?.seed !== undefined && seeds.includes(sel.seed) ? sel.seed : seeds[0];
  const path = role && config && seed !== undefined ? `/api/observatory/cascade/pair?config=${encodeURIComponent(config)}&seed=${seed}&role=${role}` : null;
  const poll = usePoll<PairResp>(path, 0);
  const fresh = poll.data && poll.data.config === config && poll.data.seed === seed && poll.data.role === role ? poll.data : undefined;
  const rep: CascadeReport | null =
    role === "exploratory" ? (d.exploratory?.X2?.configs ? ({ configs: d.exploratory.X2.configs, run_index: d.exploratory.run_index } as CascadeReport) : null) : role ? (d[role] as CascadeReport | null) : null;
  const sha = role ? d[role]?.protocol_sha256 : undefined;

  if (!roles.length) return <EmptyState title="No paired runs available">No cascade report has been produced yet.</EmptyState>;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <label className="field">
          role
          <select className="input" value={role} onChange={(e) => setSel({ role: e.target.value as Role, config: "", seed: NaN })}>
            {roles.map((r) => (
              <option key={r} value={r}>
                {r === "pilot" ? "pilot (EXPLORATORY PILOT)" : r === "exploratory" ? "exploratory (C2x)" : r}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          configuration
          <select className="input" value={config} onChange={(e) => setSel({ role: role!, config: e.target.value, seed: seed ?? NaN })}>
            {configs.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          seed
          <select className="input" value={seed} onChange={(e) => setSel({ role: role!, config: config!, seed: Number(e.target.value) })}>
            {seeds.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>
      {role !== "confirmatory" && (
        <p className="rounded border border-warn/50 bg-warn/10 px-2 py-1 text-[11px] text-warn">
          {role === "pilot" ? "EXPLORATORY PILOT run: feasibility only, not used in any confirmatory statistic." : "EXPLORATORY C2x run: counterfactual model variant on the same seeds as the confirmatory study; not independent evidence."}
        </p>
      )}
      {fresh ? (
        <PairView pair={fresh} rep={rep} protocolSha={sha} shockAtS={d.protocol.design?.shock_at_s} />
      ) : poll.error ? (
        <ErrorNote error={poll.error} what="pair" />
      ) : (
        <p className="text-xs text-muted" aria-live="polite">
          Loading {config} seed {seed}…
        </p>
      )}
    </div>
  );
}

/* ================================================================ 5. exploratory */

function MiniTrace({ t, shockAtS }: { t: DeleveragingTrace; shockAtS: number }) {
  const w = 220;
  const h = 70;
  const m = { l: 4, r: 4, t: 6, b: 14 };
  const pts = t.path.filter((p) => typeof p.long_gross_usd_m === "number");
  if (!pts.length) return null;
  const x0 = pts[0].t_s;
  const x1 = pts[pts.length - 1].t_s;
  const yMax = Math.max(...pts.map((p) => p.long_gross_usd_m as number), 1e-9);
  const sx = (v: number) => m.l + ((v - x0) / (x1 - x0 || 1)) * (w - m.l - m.r);
  const sy = (v: number) => m.t + (h - m.t - m.b) * (1 - v / yMax);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(p.t_s).toFixed(1)},${sy(p.long_gross_usd_m as number).toFixed(1)}`).join("");
  const minP = pts.reduce((a, b) => ((b.long_gross_usd_m as number) < (a.long_gross_usd_m as number) ? b : a));
  const first = pts[0];
  return (
    <figure className="min-w-0 rounded border border-line bg-panel2 p-2">
      <figcaption className="mb-1 flex justify-between text-[11px]">
        <span className="font-semibold text-ink">seed {t.seed}</span>
        <span className="text-muted">
          longs {fmtAny(first.leveraged_longs)} → {fmtAny(minP.leveraged_longs)}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label={`Leveraged long gross exposure, seed ${t.seed}`} className="block">
        <line x1={sx(shockAtS)} x2={sx(shockAtS)} y1={m.t} y2={h - m.b} stroke={COL_PRIMARY} strokeDasharray="2 2" />
        <path d={d} fill="none" stroke={COL_SECONDARY} strokeWidth={1.5} />
        {pts.map((p) => (
          <circle key={p.t_s} cx={sx(p.t_s)} cy={sy(p.long_gross_usd_m as number)} r={1.8} fill={COL_SECONDARY}>
            <title>{`t ${p.t_s} s: ${p.leveraged_longs} longs, $${p.long_gross_usd_m}M gross, min down distance ${pctAbs(p.min_down_distance)}`}</title>
          </circle>
        ))}
        <text x={m.l} y={h - 2} fontSize={9} fill={MUTED}>
          {x0 - shockAtS} s
        </text>
        <text x={w - m.r} y={h - 2} fontSize={9} fill={MUTED} textAnchor="end">
          +{x1 - shockAtS} s
        </text>
      </svg>
      <p className="text-[10px] text-muted">
        long gross ${fx(first.long_gross_usd_m)}M → min ${fx(minP.long_gross_usd_m)}M ({pctOf(((minP.long_gross_usd_m as number) - (first.long_gross_usd_m as number)) / ((first.long_gross_usd_m as number) || 1), 0)})
      </p>
    </figure>
  );
}

export function ExploratoryPanel({ d, onExplore }: { d: CascadeResp; onExplore: (config: string) => void }) {
  const ex = d.exploratory;
  const px = d.protocol_exploratory;
  if (!ex) return <EmptyState title="Exploratory C2x report: not produced yet" />;
  const x1 = ex.X1;
  const conds = uniq((x1?.runs ?? []).map((r) => r.condition));
  const seeds = uniq((x1?.runs ?? []).map((r) => r.seed)).sort((a, b) => a - b);
  const sel = x1?.selected_for_X2;
  const sc = ex.X2?.scale_check;
  const gross = stats(sc?.leveraged_max_gross_usd_m_at_initial_capital);
  const forced = stats(sc?.primary_forced_notional_usd_m);
  const shockAtS = d.protocol.design?.shock_at_s ?? 0;
  const traces = ex.X2?.deleveraging_traces ?? [];
  return (
    <div className="space-y-4">
      <div className="rounded border border-warn/60 bg-warn/10 px-3 py-2 text-xs" role="note">
        <div className="flex flex-wrap items-center gap-2">
          <Tag tone="weak">EXPLORATORY</Tag>
          <span className="font-semibold text-warn">{ex.label}</span>
        </div>
        {px?.status && <p className="mt-1 text-ink2">{px.status}</p>}
        <p className="mt-1 text-muted">
          {px?.name} · sha256 <Hash v={ex.protocol_sha256} n={12} /> · {costLine(ex.cost)} · {fmtTime(ex.created_utc)}
        </p>
        {px?.explanation_under_test && (
          <p className="mt-1 text-ink2">
            <span className="text-muted">explanation under test:</span> {px.explanation_under_test}
          </p>
        )}
      </div>

      <section aria-label="X1 positioning" className="space-y-2">
        <h3 className="text-sm font-semibold">X1 — leveraged positioning just before the shock (leveraged long / short of 16)</h3>
        {px?.X1_positioning && (
          <p className="text-[11px] text-muted">
            {px.X1_positioning.design} · <span className="text-ink2">prediction:</span> {px.X1_positioning.prediction} · <span className="text-ink2">refuted if:</span>{" "}
            {px.X1_positioning.refuted_if}
          </p>
        )}
        <TableWrap label="X1 positioning by condition and seed">
          <table className="data">
            <thead>
              <tr>
                <th>seed</th>
                {conds.map((c) => (
                  <th key={c} className={`num ${c === sel ? "!text-warn" : ""}`}>
                    {c}
                    {c === sel ? " ★" : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {seeds.map((s) => (
                <tr key={s}>
                  <td className="num">{s}</td>
                  {conds.map((c) => {
                    const r = x1?.runs.find((x) => x.seed === s && x.condition === c);
                    return (
                      <td key={c} className={`num ${c === sel ? "bg-warn/5" : ""}`} title={r?.min_down_distance_longs ? `closest long ${pctAbs(r.min_down_distance_longs)} from breach` : undefined}>
                        {r ? (
                          <>
                            <span className={r.leveraged_long ? "text-[#f3a7a7]" : "text-muted"}>{r.leveraged_long}L</span> / <span className="text-[#c3bdf5]">{r.leveraged_short}S</span>
                            {!!r.leveraged_flat && <span className="text-muted"> / {r.leveraged_flat}F</span>}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr className="border-t border-line2">
                <td className="font-semibold">mean longs</td>
                {conds.map((c) => (
                  <td key={c} className={`num font-semibold ${c === sel ? "bg-warn/5 text-warn" : ""}`}>
                    {fx(x1?.mean_leveraged_long?.[c])}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </TableWrap>
        <p className="text-[11px] text-muted">★ = condition selected for X2 by the pre-declared rule (max mean longs): {sel ?? "—"}.</p>
      </section>

      <section aria-label="X2 cascade with channel removed" className="space-y-2">
        <h3 className="text-sm font-semibold">X2 — C2 arms A/B under the selected condition</h3>
        {px?.X2_cascade_with_channel_removed && (
          <p className="text-[11px] text-muted">
            {px.X2_cascade_with_channel_removed.nature} · <span className="text-ink2">prediction:</span> {px.X2_cascade_with_channel_removed.prediction} ·{" "}
            <span className="text-ink2">refuted if:</span> {px.X2_cascade_with_channel_removed.refuted_if}
          </p>
        )}
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {Object.entries(ex.X2?.configs ?? {}).map(([k, c]) => (
            <ConfigCard key={k} id={k} c={c} onExplore={() => onExplore(k)} />
          ))}
        </div>
        {ex.X2?.threshold && <ThresholdPanel th={ex.X2.threshold} configs={ex.X2.configs ?? {}} />}
      </section>

      <section aria-label="Scale check" className="space-y-2">
        <h3 className="text-sm font-semibold">Scale check — leveraged sector capacity vs primary forced sale</h3>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <div className="rounded border border-line bg-panel2 p-2 text-xs">
            <div className="text-[11px] uppercase tracking-wider text-muted">leveraged sector max gross</div>
            <div className="text-lg font-semibold tnum">{gross ? `$${fx(gross.min)}–${fx(gross.max)}M` : "—"}</div>
            <div className="text-[11px] text-muted">at initial capital ({sc?.leveraged_max_gross_usd_m_at_initial_capital?.length ?? 0} values)</div>
          </div>
          <div className="rounded border border-line bg-panel2 p-2 text-xs">
            <div className="text-[11px] uppercase tracking-wider text-muted">primary forced notional</div>
            <div className="text-lg font-semibold tnum">{forced ? `$${fx(forced.min, 1)}–${fx(forced.max, 1)}M` : "—"}</div>
            <div className="text-[11px] text-muted">mean ${fx(forced?.mean, 1)}M over {forced?.n ?? 0} seeds</div>
          </div>
          <div className="rounded border border-line bg-panel2 p-2 text-xs">
            <div className="text-[11px] uppercase tracking-wider text-muted">ratio (max gross / mean forced)</div>
            <div className="text-lg font-semibold tnum">{gross && forced ? `${((gross.max / forced.mean) * 100).toFixed(1)}%` : "—"}</div>
            <div className="text-[11px] text-muted">upper bound of leveraged fuel relative to the shock</div>
          </div>
        </div>
      </section>

      <section aria-label="Deleveraging traces" className="space-y-2">
        <h3 className="text-sm font-semibold">Voluntary deleveraging traces ({traces[0]?.condition ?? "—"}) — leveraged long gross exposure ($M)</h3>
        <p className="text-[11px] text-muted">Dashed line = scheduled shock ({shockAtS} s). Hover points for longs, gross and closest downward margin distance.</p>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {traces.map((t) => (
            <MiniTrace key={t.seed} t={t} shockAtS={shockAtS} />
          ))}
        </div>
        <details>
          <summary className="cursor-pointer text-xs text-ink2">All trace points (table)</summary>
          <TableWrap label="Deleveraging traces">
            <div className="max-h-80 overflow-y-auto">
              <table className="data">
                <thead>
                  <tr>
                    <th className="num">seed</th>
                    <th className="num">t_s</th>
                    <th className="num">t vs shock</th>
                    <th className="num">mid_rel</th>
                    <th className="num">leveraged longs</th>
                    <th className="num">long gross $M</th>
                    <th className="num">min down distance</th>
                  </tr>
                </thead>
                <tbody>
                  {traces.flatMap((t) =>
                    t.path.map((p) => (
                      <tr key={`${t.seed}-${p.t_s}`}>
                        <td className="num">{t.seed}</td>
                        <td className="num">{p.t_s}</td>
                        <td className="num">{sec(p.t_s - shockAtS)}</td>
                        <td className="num">{pctOf(p.mid_rel)}</td>
                        <td className="num">{fmtAny(p.leveraged_longs)}</td>
                        <td className="num">{fx(p.long_gross_usd_m)}</td>
                        <td className="num">{pctAbs(p.min_down_distance)}</td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          </TableWrap>
        </details>
      </section>
    </div>
  );
}

/* ================================================================ 6. research memory */

function StatusTag({ s }: { s: string }) {
  return <Tag tone={memoryTone(s)}>{s.replace(/_/g, " ").toUpperCase()}</Tag>;
}

function Evidence({ ev }: { ev: unknown }) {
  if (ev === undefined || ev === null) return <span className="text-muted">—</span>;
  if (typeof ev !== "object") return <span className="text-ink2">{fmtAny(ev)}</span>;
  return (
    <details>
      <summary className="cursor-pointer text-ink2">{Object.keys(ev as object).join(", ")}</summary>
      <Kv data={ev as Record<string, unknown>} />
    </details>
  );
}

export function MemoryPanel({ poll }: { poll: Poll<Knowledge> }) {
  return (
    <SectionState poll={poll} what="research memory">
      {(k) => {
        const mechs = k.mechanisms.filter((m) => !m.id.startsWith("gap:"));
        const gaps = k.mechanisms.filter((m) => m.id.startsWith("gap:"));
        const evals = k.proposal_evaluations ?? [];
        const ranking = k.next_experiment_ranking ?? [];
        return (
          <div className="space-y-4 text-xs">
            <p className="rounded border border-line2 bg-panel2 px-2 py-1 text-ink2" role="note">
              <span className="font-semibold text-ink">Nothing here is applied to the simulator.</span> {k.note} · updated {fmtTime(k.created_utc)}
            </p>
            {[
              ["Mechanisms", mechs],
              ["Simulator gaps", gaps],
            ].map(([title, rows]) => (
              <section key={title as string} aria-label={title as string} className="space-y-1">
                <h3 className="text-sm font-semibold">{title as string}</h3>
                <TableWrap label={title as string}>
                  <table className="data">
                    <thead>
                      <tr>
                        <th>id</th>
                        <th>status</th>
                        <th>statement</th>
                        <th>evidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(rows as Knowledge["mechanisms"]).map((m) => (
                        <tr key={m.id}>
                          <td className="align-top font-mono text-[11px]">{m.id}</td>
                          <td className="align-top">
                            <StatusTag s={m.status} />
                          </td>
                          <td className="min-w-[16rem] max-w-[34rem] !whitespace-normal align-top text-ink2">{m.statement}</td>
                          <td className="min-w-[12rem] max-w-[28rem] !whitespace-normal align-top">
                            <Evidence ev={m.evidence} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              </section>
            ))}

            <section aria-label="Proposals" className="space-y-1">
              <h3 className="text-sm font-semibold">Proposals (never applied automatically)</h3>
              <TableWrap label="Proposals">
                <table className="data">
                  <thead>
                    <tr>
                      <th>id</th>
                      <th>status</th>
                      <th>gap</th>
                      <th>in frozen candidate space</th>
                      <th>overrides</th>
                      <th>rationale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {k.proposals.map((p) => (
                      <tr key={p.id}>
                        <td className="align-top font-mono text-[11px]">{p.id}</td>
                        <td className="align-top">
                          <StatusTag s={p.status} />
                          <div className="mt-0.5 text-[10px] text-muted">applied: no</div>
                        </td>
                        <td className="align-top">{p.gap ?? p.spec?.gap ?? "—"}</td>
                        <td className="align-top">
                          <Check v={p.spec?.in_track_space} />
                        </td>
                        <td className="min-w-[14rem] max-w-[24rem] !whitespace-normal align-top">
                          <Kv data={p.spec?.overrides} />
                        </td>
                        <td className="min-w-[14rem] max-w-[24rem] !whitespace-normal align-top text-ink2">{p.spec?.rationale ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
              <p className="text-[11px] text-muted">
                &ldquo;needs human rules review&rdquo; = the change lies outside the frozen candidate space; it cannot be evaluated by the realism track until a human
                revises the rules.
              </p>
            </section>

            <section aria-label="Proposal evaluations" className="space-y-1">
              <h3 className="text-sm font-semibold">Proposal evaluations (frozen realism rules)</h3>
              {evals.length ? (
                <TableWrap label="Proposal evaluations">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>proposal</th>
                        <th>verdict vs incumbents</th>
                        <th>objectives (mean)</th>
                        <th>applied</th>
                      </tr>
                    </thead>
                    <tbody>
                      {evals.map((e, i) => (
                        <tr key={e.proposal ?? i}>
                          <td className="font-mono text-[11px]">{e.proposal ?? "—"}</td>
                          <td className="!whitespace-normal">
                            <div className="flex flex-wrap gap-1">
                              {Object.entries(e.verdict_vs ?? {}).map(([inc, v]) => (
                                <VerdictBadge key={inc} v={v} label={inc} />
                              ))}
                            </div>
                          </td>
                          <td className="!whitespace-normal">
                            <Kv data={e.objectives_mean} />
                          </td>
                          <td>{e.applied ? <span className="text-down">yes</span> : "no"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              ) : (
                <p className="text-muted">No proposal evaluation is recorded in the research memory file.</p>
              )}
            </section>

            <section aria-label="Next experiment ranking" className="space-y-1">
              <h3 className="text-sm font-semibold">Next-experiment ranking (expected information per run)</h3>
              <p className="text-[11px] text-warn">Priors (prior_positive) are explicit judgement inputs, not estimates; bits = binary entropy of the prior.</p>
              <TableWrap label="Next experiment ranking">
                <table className="data">
                  <thead>
                    <tr>
                      <th className="num">#</th>
                      <th>id</th>
                      <th>hypothesis</th>
                      <th>conditions</th>
                      <th className="num">runs</th>
                      <th className="num">prior</th>
                      <th className="num">bits</th>
                      <th className="num">bits / 100 runs</th>
                      <th>why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranking.map((r, i) => (
                      <tr key={r.id} className={r.already_run ? "opacity-45" : undefined} title={r.already_run ? "already run (duplicate conditions)" : undefined}>
                        <td className="num">{i + 1}</td>
                        <td className="font-mono text-[11px]">
                          {r.id}
                          {r.already_run && <span className="ml-1 rounded border border-line2 px-1 text-[10px] text-muted">already run</span>}
                        </td>
                        <td className="font-mono text-[11px]">{r.hypothesis_id}</td>
                        <td className="min-w-[12rem] max-w-[22rem] !whitespace-normal">
                          <Kv data={r.conditions} />
                        </td>
                        <td className="num">{fmtAny(r.runs)}</td>
                        <td className="num">{fx(r.prior_positive)}</td>
                        <td className="num">{fx(r.bits)}</td>
                        <td className="num font-semibold">{fx(r.bits_per_100_runs)}</td>
                        <td className="min-w-[14rem] max-w-[26rem] !whitespace-normal text-ink2">{r.why}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            </section>
            {!!k.log?.length && (
              <details>
                <summary className="cursor-pointer text-ink2">Memory log ({k.log.length})</summary>
                <ul className="mt-1 font-mono text-[11px] text-muted">
                  {k.log.map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        );
      }}
    </SectionState>
  );
}

