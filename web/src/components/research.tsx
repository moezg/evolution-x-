"use client";
import type { ReactNode } from "react";
import { useWidth } from "./useWidth";
import { defaultFmt, niceTicks } from "./charts";
import { SERIES } from "@/lib/colors";
import { fmtAny } from "@/lib/format";
import type { Checks, DataFile, PerWindow, RateCI } from "@/lib/research";

const MUTED = "#9a9890";
const GRID = "#2c2c2a";

/* ---------------------------------------------------------------- provenance */

export type Provenance = "HISTORICAL BACKTEST" | "SYNTHETIC" | "HYPOTHESIS" | "MECHANISM TEST" | "HISTORICAL TARGETS" | "NOT BLIND ANYMORE" | "PILOT";

const PROV_CLS: Record<Provenance, string> = {
  "HISTORICAL BACKTEST": "border-[#c98500] bg-[#c98500]/15 text-[#f2c14e]",
  "HISTORICAL TARGETS": "border-[#c98500] bg-[#c98500]/15 text-[#f2c14e]",
  SYNTHETIC: "border-[#3987e5] bg-[#3987e5]/15 text-[#9ec5f4]",
  HYPOTHESIS: "border-[#9085e9] bg-[#9085e9]/15 text-[#c3bdf5]",
  "MECHANISM TEST": "border-[#199e70] bg-[#199e70]/15 text-[#7fe0b5]",
  "NOT BLIND ANYMORE": "border-down bg-down/15 text-[#f3a7a7]",
  PILOT: "border-warn bg-warn/15 text-warn",
};

const PROV_TITLE: Record<Provenance, string> = {
  "HISTORICAL BACKTEST": "Backtest on real Binance USDⓈ-M perpetual hourly bars. Past performance, simulated execution, no live trading.",
  "HISTORICAL TARGETS": "Statistics measured on real historical market data, used as calibration targets.",
  SYNTHETIC: "Produced by the market simulator; not real market data.",
  HYPOTHESIS: "Pre-registered statement that has not been confirmed by a test.",
  "MECHANISM TEST": "Controlled example isolating one mechanism; not evidence about real markets.",
  "NOT BLIND ANYMORE": "The final vault split has been revealed at least once; any later evaluation on it is not blind.",
  PILOT: "Small pilot run to check mechanisms and cost; sample size too small for any inferential claim.",
};

export function Prov({ kind }: { kind: Provenance }) {
  return (
    <span title={PROV_TITLE[kind]} className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-bold tracking-wider ${PROV_CLS[kind]}`}>
      {kind}
    </span>
  );
}

/* ---------------------------------------------------------------- verdicts / statuses */

const VERDICT_CLS: Record<string, string> = {
  promote: "border-up/60 bg-up/15 text-up",
  confirmed: "border-up/60 bg-up/15 text-up",
  refuted: "border-down/60 bg-down/15 text-[#f3a7a7]",
  inconclusive: "border-warn/60 bg-warn/15 text-warn",
  rejected: "border-[#d55181]/60 bg-[#d55181]/15 text-[#f0a3c2]",
  duplicate: "border-line2 bg-panel2 text-muted",
  failed: "border-crit/60 bg-crit/15 text-[#f3a7a7]",
  pending: "border-[#9085e9]/60 bg-[#9085e9]/15 text-[#c3bdf5]",
  open: "border-accent/60 bg-accent/15 text-[#9ec5f4]",
  done: "border-line2 bg-panel2 text-ink2",
  running: "border-up/60 bg-up/15 text-up",
  created: "border-line2 bg-panel2 text-ink2",
  completed: "border-accent/60 bg-accent/15 text-[#9ec5f4]",
  budget_exhausted: "border-line2 bg-panel2 text-ink2",
  search_space_exhausted: "border-line2 bg-panel2 text-ink2",
  stopped_by_user: "border-warn/60 bg-warn/15 text-warn",
};

export function Verdict({ v }: { v: string | null | undefined }) {
  if (!v) return <span className="text-[11px] text-muted">—</span>;
  return (
    <span className={`inline-block whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold ${VERDICT_CLS[v] ?? "border-line2 bg-panel2 text-ink2"}`}>
      {v.replace(/_/g, " ")}
    </span>
  );
}

/** Pass/fail chips for the 5 promotion checks. Non-boolean values are surfaced literally, not coerced. */
export const CHECK_ORDER = ["effect_size", "prob_improvement", "drawdown", "cost_robustness", "deflated_sharpe"];

export function CheckChips({ checks, compact = false }: { checks: Checks | null | undefined; compact?: boolean }) {
  if (!checks) return <span className="text-[11px] text-muted">not evaluated</span>;
  const keys = [...CHECK_ORDER.filter((k) => k in checks), ...Object.keys(checks).filter((k) => !CHECK_ORDER.includes(k))];
  return (
    <ul className="flex flex-wrap gap-1" aria-label="Promotion checks">
      {keys.map((k) => {
        const v = checks[k];
        const isBool = typeof v === "boolean";
        const cls = !isBool ? "border-warn/70 bg-warn/10 text-warn" : v ? "border-up/60 bg-up/10 text-up" : "border-down/50 bg-down/10 text-[#f3a7a7]";
        const mark = !isBool ? "?" : v ? "✓" : "✗";
        const label = compact ? k.split("_").map((s) => s[0]).join("").toUpperCase() : k.replace(/_/g, " ");
        const title = isBool
          ? `${k}: ${v ? "pass" : "fail"}`
          : `${k}: API returned non-boolean ${JSON.stringify(v)} (${typeof v}); shown as-is, not interpreted`;
        return (
          <li key={k} title={title} className={`whitespace-nowrap rounded border px-1.5 py-px text-[10px] font-semibold ${cls}`}>
            <span aria-hidden>{mark} </span>
            {label}
            <span className="sr-only">{isBool ? (v ? " pass" : " fail") : ` non-boolean value ${JSON.stringify(v)}`}</span>
            {!isBool && <span className="font-mono"> ={JSON.stringify(v)}</span>}
          </li>
        );
      })}
    </ul>
  );
}

/* ---------------------------------------------------------------- outcome classes / premises */

/** Fixed order + colour per descriptive outcome class (colour follows the class, never its rank). */
export const CLASS_ORDER = [
  "confirmed",
  "mechanism_observed_no_benefit",
  "unstable_across_periods",
  "benefit_absorbed_by_costs",
  "insufficient_evidence",
  "mechanism_not_observed",
  "duplicate",
  "rejected_gate",
  "technically_false_premise",
  "generation_failed",
];

const CLASS_COLORS: Record<string, string> = {
  confirmed: "#1baf7a",
  mechanism_observed_no_benefit: "#199e70",
  unstable_across_periods: "#3987e5",
  benefit_absorbed_by_costs: "#c98500",
  insufficient_evidence: "#8a8984",
  mechanism_not_observed: "#9085e9",
  duplicate: "#5d5c58",
  rejected_gate: "#d95926",
  technically_false_premise: "#d55181",
  generation_failed: "#e66767",
};

export function classColor(c: string): string {
  return CLASS_COLORS[c] ?? "#6f6e69";
}

export function sortClasses(keys: string[]): string[] {
  const idx = (k: string) => (CLASS_ORDER.includes(k) ? CLASS_ORDER.indexOf(k) : CLASS_ORDER.length);
  return [...keys].sort((a, b) => idx(a) - idx(b) || a.localeCompare(b));
}

export function ClassChip({ c }: { c: string | null | undefined }) {
  if (!c) return <span className="text-[11px] text-muted" title="no classification recorded (task written before classification existed)">—</span>;
  const col = classColor(c);
  return (
    <span
      className="inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-px text-[10px] font-semibold text-ink"
      style={{ borderColor: `${col}99`, background: `${col}26` }}
      title={`descriptive outcome class: ${c}`}
    >
      <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: col }} />
      {c.replace(/_/g, " ")}
    </span>
  );
}

const PREMISE_CLS: Record<string, string> = {
  accepted: "border-up/60 bg-up/10 text-up",
  verified: "border-up/60 bg-up/10 text-up",
  falsified: "border-down/60 bg-down/10 text-[#f3a7a7]",
  rejected_false_premise: "border-down/60 bg-down/10 text-[#f3a7a7]",
  unverifiable: "border-warn/60 bg-warn/10 text-warn",
  rejected_unverifiable: "border-warn/60 bg-warn/10 text-warn",
  invalid: "border-[#d55181]/60 bg-[#d55181]/10 text-[#f0a3c2]",
  rejected_malformed: "border-[#d55181]/60 bg-[#d55181]/10 text-[#f0a3c2]",
};
const PREMISE_MARK: Record<string, string> = { accepted: "✓", verified: "✓", falsified: "✗", rejected_false_premise: "✗", unverifiable: "?", rejected_unverifiable: "?", invalid: "!", rejected_malformed: "!" };

/** Premise verdict (accepted / rejected_*) or a single premise status (verified / falsified / unverifiable / invalid). */
export function PremiseChip({ v }: { v: string | null | undefined }) {
  if (!v) return <span className="text-[11px] text-muted" title="no premise check recorded">—</span>;
  return (
    <span className={`inline-block whitespace-nowrap rounded border px-1.5 py-px text-[10px] font-semibold ${PREMISE_CLS[v] ?? "border-line2 bg-panel2 text-ink2"}`}>
      <span aria-hidden>{PREMISE_MARK[v] ?? "·"} </span>
      {v.replace(/_/g, " ")}
    </span>
  );
}

/** k/n with a horizontal 0..1 track, point estimate and Wilson 95% interval. */
export function RateBar({ label, r, color = "#3987e5" }: { label: string; r: RateCI | null | undefined; color?: string }) {
  if (!r) {
    return (
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-ink2">{label}</span>
        <span className="text-muted">not reported</span>
      </div>
    );
  }
  const [lo, hi] = r.wilson95 ?? [NaN, NaN];
  const pct = (v: number) => `${Math.max(0, Math.min(1, v)) * 100}%`;
  const ok = Number.isFinite(lo) && Number.isFinite(hi);
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 text-xs">
        <span className="text-ink2">{label}</span>
        <span className="tnum text-ink">
          {r.k}/{r.n}
          <span className="text-muted">
            {" "}
            · {(r.rate * 100).toFixed(0)}% · 95% [{ok ? `${(lo * 100).toFixed(0)}–${(hi * 100).toFixed(0)}%` : "—"}]
          </span>
        </span>
      </div>
      <div
        className="relative mt-1 h-3 rounded bg-line"
        role="img"
        aria-label={`${label}: ${r.k} of ${r.n}, Wilson 95% interval ${ok ? `${(lo * 100).toFixed(1)} to ${(hi * 100).toFixed(1)} percent` : "not reported"}`}
      >
        {[0.25, 0.5, 0.75].map((t) => (
          <span key={t} aria-hidden className="absolute top-0 h-full w-px bg-[#3a3a37]" style={{ left: pct(t) }} />
        ))}
        {ok && <span aria-hidden className="absolute top-[3px] h-1.5 rounded-sm" style={{ left: pct(lo), width: `calc(${pct(hi)} - ${pct(lo)})`, background: color, opacity: 0.45 }} />}
        {ok && <span aria-hidden className="absolute top-0 h-full w-px" style={{ left: pct(lo), background: color }} />}
        {ok && <span aria-hidden className="absolute top-0 h-full w-px" style={{ left: `calc(${pct(hi)} - 1px)`, background: color }} />}
        <span
          aria-hidden
          className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 border-2 border-[#161615]"
          style={{ left: pct(r.rate), background: color }}
        />
      </div>
    </div>
  );
}

/** Horizontal stacked bar of class counts (fixed class order/colours). */
export function ClassBar({ classes, label, total }: { classes: Record<string, number>; label: string; total?: number }) {
  const keys = sortClasses(Object.keys(classes).filter((k) => classes[k] > 0));
  const sum = keys.reduce((a, k) => a + classes[k], 0);
  const n = total ?? sum;
  if (!sum) return <span className="text-[11px] text-muted">no classified tasks</span>;
  return (
    <div className="flex h-4 w-full overflow-hidden rounded bg-line" role="img" aria-label={`${label}: ${keys.map((k) => `${k.replace(/_/g, " ")} ${classes[k]}`).join(", ")}`}>
      {keys.map((k) => (
        <span
          key={k}
          className="flex h-full items-center justify-center overflow-hidden text-[9px] font-semibold text-white/95"
          style={{ width: `${(classes[k] / n) * 100}%`, background: classColor(k), borderRight: "1px solid #161615" }}
          title={`${k.replace(/_/g, " ")}: ${classes[k]} of ${n}`}
        >
          {classes[k]}
        </span>
      ))}
    </div>
  );
}

export function ClassLegend({ classes }: { classes: string[] }) {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink2" aria-label="Class legend">
      {sortClasses(classes).map((k) => (
        <li key={k} className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: classColor(k) }} />
          {k.replace(/_/g, " ")}
        </li>
      ))}
    </ul>
  );
}

/* ---------------------------------------------------------------- progress */

export function Meter({ label, used, max, unit = "", note }: { label: string; used: number; max?: number | null; unit?: string; note?: ReactNode }) {
  const has = typeof max === "number" && max > 0;
  const frac = has ? Math.min(1, used / (max as number)) : 0;
  const over = has && used > (max as number);
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-ink2">{label}</span>
        <span className="tnum text-ink">
          {fmtAny(used)}
          {unit}
          {has && (
            <span className="text-muted">
              {" "}/ {fmtAny(max)}
              {unit}
            </span>
          )}
        </span>
      </div>
      {has ? (
        <div
          className="mt-1 h-1.5 overflow-hidden rounded bg-line"
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={max as number}
          aria-valuenow={used}
        >
          <div className={`h-full ${over ? "bg-down" : frac >= 0.9 ? "bg-warn" : "bg-accent"}`} style={{ width: `${Math.round(frac * 100)}%` }} />
        </div>
      ) : null}
      {note && <p className="mt-0.5 text-[11px] text-muted">{note}</p>}
    </div>
  );
}

/* ---------------------------------------------------------------- hash */

export function Hash({ v, n = 12, label }: { v?: string | null; n?: number; label?: string }) {
  if (!v) return <span className="text-muted">—</span>;
  return (
    <code className="break-all font-mono text-[11px] text-ink2" title={v} aria-label={label ? `${label} ${v}` : v}>
      {v.length > n ? `${v.slice(0, n)}…` : v}
    </code>
  );
}

/* ---------------------------------------------------------------- interval plot */

export interface IntervalRow {
  label: string;
  point?: number;
  lo?: number;
  hi?: number;
  /** optional inner interval (e.g. 90% inside 95%) */
  lo2?: number;
  hi2?: number;
  color?: string;
  title?: string;
}

/** Horizontal point + interval plot. Outer whisker = lo..hi, thick inner band = lo2..hi2. */
export function IntervalPlot({
  rows,
  label,
  refs = [],
  fmt = defaultFmt,
  labelWidth = 110,
}: {
  rows: IntervalRow[];
  label: string;
  refs?: { at: number; label: string; color?: string }[];
  fmt?: (v: number) => string;
  labelWidth?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const m = { l: Math.min(labelWidth, Math.max(70, width * 0.32)), r: 14, t: refs.length ? 16 : 6, b: 20 };
  const rowH = 26;
  const height = m.t + m.b + rows.length * rowH;
  const vals: number[] = [];
  rows.forEach((r) => [r.point, r.lo, r.hi, r.lo2, r.hi2].forEach((v) => typeof v === "number" && Number.isFinite(v) && vals.push(v)));
  refs.forEach((r) => vals.push(r.at));
  let lo = vals.length ? Math.min(...vals) : 0;
  let hi = vals.length ? Math.max(...vals) : 1;
  if (lo === hi) {
    lo -= Math.abs(lo) * 0.1 || 1;
    hi += Math.abs(hi) * 0.1 || 1;
  }
  const pad = (hi - lo) * 0.06;
  lo -= pad;
  hi += pad;
  const iw = Math.max(10, width - m.l - m.r);
  const sx = (v: number) => m.l + ((v - lo) / (hi - lo)) * iw;
  const ticks = niceTicks(lo, hi, Math.max(2, Math.floor(iw / 70)));
  const ok = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label={label} className="block">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={sx(t)} x2={sx(t)} y1={m.t} y2={height - m.b} stroke={GRID} />
            <text x={sx(t)} y={height - 5} textAnchor="middle" fontSize={10} fill={MUTED} className="tnum">
              {fmt(t)}
            </text>
          </g>
        ))}
        {refs.map((r) => (
          <g key={r.label}>
            <line x1={sx(r.at)} x2={sx(r.at)} y1={m.t - 4} y2={height - m.b} stroke={r.color ?? "#8a8984"} strokeDasharray="3 3" />
            <text x={sx(r.at)} y={m.t - 6} textAnchor="middle" fontSize={9} fill={r.color ?? MUTED}>
              {r.label}
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          const cy = m.t + i * rowH + rowH / 2;
          const c = r.color ?? "#3987e5";
          return (
            <g key={r.label + i}>
              <title>{r.title ?? `${r.label}: ${ok(r.point) ? fmt(r.point) : "—"} [${ok(r.lo) ? fmt(r.lo) : "—"}, ${ok(r.hi) ? fmt(r.hi) : "—"}]`}</title>
              <text x={m.l - 8} y={cy} dy="0.32em" textAnchor="end" fontSize={11} fill="#c3c2b7">
                {fit(r.label, m.l - 12)}
              </text>
              {ok(r.lo) && ok(r.hi) && (
                <g stroke={c}>
                  <line x1={sx(r.lo)} x2={sx(r.hi)} y1={cy} y2={cy} strokeWidth={1.5} />
                  <line x1={sx(r.lo)} x2={sx(r.lo)} y1={cy - 6} y2={cy + 6} strokeWidth={1.5} />
                  <line x1={sx(r.hi)} x2={sx(r.hi)} y1={cy - 6} y2={cy + 6} strokeWidth={1.5} />
                </g>
              )}
              {ok(r.lo2) && ok(r.hi2) && <rect x={sx(r.lo2)} y={cy - 3.5} width={Math.max(1, sx(r.hi2) - sx(r.lo2))} height={7} fill={c} fillOpacity={0.45} />}
              {ok(r.point) && <rect x={sx(r.point) - 5} y={cy - 5} width={10} height={10} transform={`rotate(45 ${sx(r.point)} ${cy})`} fill={c} stroke="#161615" strokeWidth={2} />}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Truncate a label to roughly fit `px` at 11px font (≈6.2px per char); full text stays in <title>. */
function fit(label: string, px: number): string {
  const n = Math.max(4, Math.floor(px / 6.2));
  return label.length > n ? label.slice(0, n - 1) + "…" : label;
}

/* ---------------------------------------------------------------- walk-forward per-window bars */

function ym(ms: number): string {
  const d = new Date(ms);
  return Number.isNaN(d.getTime()) ? "?" : d.toISOString().slice(0, 7);
}

export function WindowBars({ perSymbol }: { perSymbol: Record<string, { per_window?: PerWindow[]; oos_sharpe?: number }> }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const syms = Object.keys(perSymbol).filter((s) => (perSymbol[s].per_window ?? []).length);
  const nWin = Math.max(0, ...syms.map((s) => perSymbol[s].per_window!.length));
  if (!syms.length || !nWin) return <p className="text-xs text-muted">No walk-forward windows recorded.</p>;
  const height = 200;
  const m = { l: 40, r: 8, t: 8, b: 30 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = height - m.t - m.b;
  const vals = syms.flatMap((s) => perSymbol[s].per_window!.map((w) => w.test_sharpe)).filter(Number.isFinite);
  vals.push(0);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const sy = (v: number) => m.t + ih - ((v - lo) / (hi - lo || 1)) * ih;
  const gw = iw / nWin;
  const bw = Math.max(1.5, Math.min(14, (gw - 3) / syms.length));
  const labelEvery = Math.max(1, Math.ceil(nWin / Math.max(1, Math.floor(iw / 52))));
  const first = perSymbol[syms[0]].per_window!;
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label="Walk-forward test-window Sharpe per window and symbol (development split)" className="block">
        {niceTicks(lo, hi, 4).map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke={GRID} />
            <text x={m.l - 6} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">
              {defaultFmt(t)}
            </text>
          </g>
        ))}
        {Array.from({ length: nWin }).map((_, i) => {
          const gx = m.l + i * gw + (gw - bw * syms.length) / 2;
          return (
            <g key={i}>
              {syms.map((s, j) => {
                const w = perSymbol[s].per_window![i];
                if (!w || !Number.isFinite(w.test_sharpe)) return null;
                const y0 = sy(0);
                const y1 = sy(w.test_sharpe);
                return (
                  <rect key={s} x={gx + j * bw} y={Math.min(y0, y1)} width={Math.max(1, bw - 1)} height={Math.max(1, Math.abs(y1 - y0))} fill={SERIES[j % SERIES.length]} rx={1}>
                    <title>{`${s} window ${i + 1}: test ${ym(w.test[0])}→${ym(w.test[1])} · test Sharpe ${w.test_sharpe.toFixed(3)} · test return ${(w.test_return * 100).toFixed(2)}% · train Sharpe ${w.train_sharpe.toFixed(3)} · param set ${w.selected}`}</title>
                  </rect>
                );
              })}
              {i % labelEvery === 0 && first[i] && (
                <text x={m.l + i * gw + gw / 2} y={height - 14} textAnchor="middle" fontSize={9} fill={MUTED}>
                  {ym(first[i].test[0])}
                </text>
              )}
            </g>
          );
        })}
        <line x1={m.l} x2={m.l + iw} y1={sy(0)} y2={sy(0)} stroke="#6a6964" />
      </svg>
      <ul className="flex flex-wrap gap-3 text-[11px] text-ink2" aria-label="Legend">
        {syms.map((s, j) => (
          <li key={s} className="flex items-center gap-1">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[j % SERIES.length] }} />
            {s} (OOS Sharpe {fmtAny(perSymbol[s].oos_sharpe)})
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ---------------------------------------------------------------- data split timeline */

export const SPLIT_COLORS: Record<string, string> = {
  development: "#3987e5",
  validation: "#c98500",
  final: "#d55181",
};

export function SplitTimeline({ files, lo, hi, finalConsumed }: { files: Record<string, DataFile>; lo: number; hi: number; finalConsumed: boolean }) {
  const order = ["development", "validation", "final"].filter((k) => files[k]);
  const span = hi - lo || 1;
  return (
    <div className="relative h-7 w-full overflow-hidden rounded bg-line" role="img" aria-label={`Split coverage: ${order.map((k) => `${k} ${files[k].first.slice(0, 10)} to ${files[k].last.slice(0, 10)}, ${files[k].bars} bars`).join("; ")}`}>
      {order.map((k) => {
        const a = Date.parse(files[k].first);
        const b = Date.parse(files[k].last);
        const left = ((a - lo) / span) * 100;
        const w = ((b - a) / span) * 100;
        const vaultLocked = k === "final" && !finalConsumed;
        return (
          <div
            key={k}
            className="absolute top-0 flex h-full items-center justify-center overflow-hidden text-[10px] font-semibold text-white/95"
            style={{
              left: `${left}%`,
              width: `${w}%`,
              background: vaultLocked
                ? `repeating-linear-gradient(135deg, ${SPLIT_COLORS[k]}55 0 6px, ${SPLIT_COLORS[k]}22 6px 12px)`
                : SPLIT_COLORS[k],
              borderLeft: "1px solid #0d0d0d",
            }}
            title={`${k}: ${files[k].first} → ${files[k].last} · ${files[k].bars.toLocaleString()} bars`}
          >
            <span className="truncate px-1">{k === "final" ? (vaultLocked ? "🔒 final" : "final (revealed)") : k}</span>
          </div>
        );
      })}
    </div>
  );
}
