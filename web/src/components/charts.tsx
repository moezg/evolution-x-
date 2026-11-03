"use client";
import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { useWidth } from "./useWidth";

const GRID = "#2c2c2a";
const AXIS = "#383835";
const MUTED = "#9a9890";

export function niceTicks(lo: number, hi: number, n = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (lo === hi) {
    const d = Math.abs(lo) * 0.01 || 1;
    lo -= d;
    hi += d;
  }
  const span = hi - lo;
  const step0 = span / Math.max(1, n);
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

function extent(vals: number[], padFrac = 0.05): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of vals) {
    if (v === null || v === undefined || !Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!Number.isFinite(lo)) return [0, 1];
  if (lo === hi) {
    const d = Math.abs(lo) * 0.001 || 1;
    return [lo - d, hi + d];
  }
  const p = (hi - lo) * padFrac;
  return [lo - p, hi + p];
}

export function defaultFmt(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (a >= 1e4) return (v / 1e3).toFixed(1) + "k";
  if (a >= 100) return v.toFixed(0);
  if (a >= 1) return v.toFixed(2);
  if (a === 0) return "0";
  if (a >= 0.01) return v.toFixed(3);
  return v.toExponential(1);
}

/** Round time ticks (seconds) at 10s … 1h steps. */
export function timeTicks(lo: number, hi: number, n = 5): number[] {
  const steps = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400];
  const span = Math.max(1, hi - lo);
  const step = steps.find((s) => span / s <= n) ?? 14400;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(v);
  return out;
}

export function clockFmt(t: number): string {
  const s = Math.max(0, Math.round(t));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}${sec ? ":" + String(sec).padStart(2, "0") : ""}` : `${m}:${String(sec).padStart(2, "0")}`;
}

/** Formatter whose precision follows the tick step, so narrow ranges stay distinguishable. */
export function stepFormatter(ticks: number[]): (v: number) => string {
  const step = ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : 0;
  const maxAbs = Math.max(0, ...ticks.map(Math.abs));
  if (maxAbs >= 1e6 && step >= 1e5) return (v) => (v / 1e6).toFixed(step >= 1e6 ? 0 : 1) + "M";
  if (maxAbs >= 1e4 && step >= 1e3) return (v) => (v / 1e3).toFixed(step >= 1e4 ? 0 : step >= 1e3 ? 0 : 1) + "k";
  if (step >= 1 || step === 0) return (v) => (maxAbs >= 1e4 ? v.toLocaleString("en-US", { maximumFractionDigits: 0 }) : defaultFmt(v));
  const d = Math.min(8, Math.max(0, -Math.floor(Math.log10(step))));
  return (v) => v.toFixed(d);
}

export interface LineSeries {
  name: string;
  color: string;
  values: (number | null)[];
  dashed?: boolean;
  width?: number;
}

/** Multi-series line chart on a single y-axis with crosshair tooltip + keyboard navigation. */
export function LineChart({
  x,
  series,
  height = 200,
  xFormat = (v) => String(v),
  yFormat: yFormatProp,
  label,
  zeroLine = false,
  yDomain,
  markers,
  timeAxis = false,
}: {
  timeAxis?: boolean;
  x: number[];
  series: LineSeries[];
  height?: number;
  xFormat?: (v: number) => string;
  yFormat?: (v: number) => string;
  label: string;
  zeroLine?: boolean;
  yDomain?: [number, number];
  markers?: { x: number; label: string }[];
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = { l: 56, r: 12, t: 8, b: 22 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = Math.max(10, height - m.t - m.b);
  const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null && Number.isFinite(v)));
  const [y0, y1] = yDomain ?? extent(zeroLine ? [...all, 0] : all);
  const xs = x.length ? [x[0], x[x.length - 1]] : [0, 1];
  const xspan = xs[1] - xs[0] || 1;
  const sx = (v: number) => m.l + ((v - xs[0]) / xspan) * iw;
  const sy = (v: number) => m.t + ih - ((v - y0) / (y1 - y0 || 1)) * ih;
  const yt = niceTicks(y0, y1, Math.max(3, Math.floor(ih / 36)));
  const yFormat = yFormatProp ?? stepFormatter(yt);
  const tipFormat = yFormatProp ?? ((v: number) => v.toLocaleString("en-US", { maximumFractionDigits: Math.abs(v) >= 100 ? 2 : 5 }));
  const xt = (timeAxis ? timeTicks : niceTicks)(xs[0], xs[1], Math.max(2, Math.floor(iw / 90)));

  const paths = useMemo(
    () =>
      series.map((s) => {
        let d = "";
        let pen = false;
        s.values.forEach((v, i) => {
          if (v === null || !Number.isFinite(v) || i >= x.length) {
            pen = false;
            return;
          }
          d += `${pen ? "L" : "M"}${sx(x[i]).toFixed(1)},${sy(v).toFixed(1)}`;
          pen = true;
        });
        return d;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [series, x, width, height, y0, y1],
  );

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!x.length) return;
    const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    const xv = xs[0] + ((px - m.l) / iw) * xspan;
    let lo = 0;
    let hi = x.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (x[mid] < xv) lo = mid;
      else hi = mid;
    }
    setHover(Math.abs(x[lo] - xv) < Math.abs(x[hi] - xv) ? lo : hi);
  };
  const onKey = (e: KeyboardEvent) => {
    if (!x.length) return;
    if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? x.length) - 1));
    else if (e.key === "ArrowRight") setHover((h) => Math.min(x.length - 1, (h ?? -1) + 1));
    else if (e.key === "Escape") setHover(null);
    else return;
    e.preventDefault();
  };

  const hx = hover !== null && hover < x.length ? sx(x[hover]) : null;
  return (
    <div ref={ref} className="relative w-full">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={label}
        tabIndex={0}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        onKeyDown={onKey}
        onBlur={() => setHover(null)}
        className="block"
      >
        {yt.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke={GRID} strokeWidth={1} />
            <text x={m.l - 6} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">
              {yFormat(t)}
            </text>
          </g>
        ))}
        {xt.map((t) => (
          <text key={t} x={sx(t)} y={height - 6} textAnchor="middle" fontSize={10} fill={MUTED} className="tnum">
            {xFormat(t)}
          </text>
        ))}
        <line x1={m.l} x2={m.l + iw} y1={m.t + ih} y2={m.t + ih} stroke={AXIS} />
        {zeroLine && y0 < 0 && y1 > 0 && <line x1={m.l} x2={m.l + iw} y1={sy(0)} y2={sy(0)} stroke="#6a6964" strokeDasharray="3 3" />}
        {markers?.map((mk, i) =>
          mk.x >= xs[0] && mk.x <= xs[1] ? (
            <g key={i}>
              <line x1={sx(mk.x)} x2={sx(mk.x)} y1={m.t} y2={m.t + ih} stroke="#fab219" strokeDasharray="2 3" />
              <text x={sx(mk.x) + 3} y={m.t + 10} fontSize={10} fill="#fab219">
                {mk.label}
              </text>
            </g>
          ) : null,
        )}
        {paths.map((d, i) => (
          <path
            key={series[i].name}
            d={d}
            fill="none"
            stroke={series[i].color}
            strokeWidth={series[i].width ?? 2}
            strokeDasharray={series[i].dashed ? "5 4" : undefined}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
        {hx !== null && hover !== null && (
          <g pointerEvents="none">
            <line x1={hx} x2={hx} y1={m.t} y2={m.t + ih} stroke="#6a6964" />
            {series.map((s) => {
              const v = s.values[hover];
              return v !== null && v !== undefined && Number.isFinite(v) ? (
                <circle key={s.name} cx={hx} cy={sy(v)} r={4} fill={s.color} stroke="#161615" strokeWidth={2} />
              ) : null;
            })}
          </g>
        )}
      </svg>
      {hx !== null && hover !== null && (
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-md border border-line2 bg-[#0f0f0e]/95 px-2 py-1.5 text-[11px] shadow-lg"
          style={hx > width / 2 ? { right: width - hx + 8 } : { left: hx + 8 }}
        >
          <div className="mb-0.5 text-muted tnum">{xFormat(x[hover])}</div>
          {series.map((s) => (
            <div key={s.name} className="flex items-center gap-2 whitespace-nowrap">
              <span aria-hidden className="inline-block h-0.5 w-3" style={{ background: s.color }} />
              <span className="text-ink2">{s.name}</span>
              <span className="ml-auto pl-2 text-ink tnum">
                {s.values[hover] === null || s.values[hover] === undefined ? "—" : tipFormat(s.values[hover] as number)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Vertical bar chart (histograms, per-minute counts). */
export function BarChart({
  bars,
  height = 160,
  color = "#3987e5",
  label,
  yFormat = defaultFmt,
  xLabelEvery,
}: {
  bars: { label: string; value: number; color?: string; tip?: string }[];
  height?: number;
  color?: string;
  label: string;
  yFormat?: (v: number) => string;
  xLabelEvery?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = { l: 44, r: 8, t: 8, b: 22 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = Math.max(10, height - m.t - m.b);
  const maxV = Math.max(1e-9, ...bars.map((b) => b.value));
  const minV = Math.min(0, ...bars.map((b) => b.value));
  const sy = (v: number) => m.t + ih - ((v - minV) / (maxV - minV || 1)) * ih;
  const bw = bars.length ? iw / bars.length : iw;
  const gap = bw > 6 ? 2 : bw > 3 ? 1 : 0;
  const every = xLabelEvery ?? Math.max(1, Math.ceil(bars.length / Math.max(1, Math.floor(iw / 48))));
  const yt = niceTicks(minV, maxV, 3);
  return (
    <div ref={ref} className="relative w-full">
      <svg width={width} height={height} role="img" aria-label={label} className="block">
        {yt.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke={GRID} />
            <text x={m.l - 6} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">
              {yFormat(t)}
            </text>
          </g>
        ))}
        {bars.map((b, i) => {
          const x = m.l + i * bw + gap / 2;
          const y = sy(Math.max(0, b.value));
          const h = Math.abs(sy(b.value) - sy(0));
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={m.l + i * bw} y={m.t} width={bw} height={ih} fill="transparent" />
              <rect
                x={x}
                y={b.value >= 0 ? y : sy(0)}
                width={Math.max(0.5, bw - gap)}
                height={Math.max(b.value !== 0 ? 1 : 0, h)}
                rx={bw > 8 ? 2 : 0}
                fill={b.color ?? color}
                opacity={hover === null || hover === i ? 1 : 0.6}
              >
                <title>{b.tip ?? `${b.label}: ${yFormat(b.value)}`}</title>
              </rect>
              {i % every === 0 && (
                <text x={m.l + i * bw + bw / 2} y={height - 6} textAnchor="middle" fontSize={10} fill={MUTED} className="tnum">
                  {b.label}
                </text>
              )}
            </g>
          );
        })}
        <line x1={m.l} x2={m.l + iw} y1={sy(0)} y2={sy(0)} stroke={AXIS} />
      </svg>
      {hover !== null && bars[hover] && (
        <div className="pointer-events-none absolute right-1 top-1 rounded-md border border-line2 bg-[#0f0f0e]/95 px-2 py-1 text-[11px] tnum">
          {bars[hover].tip ?? `${bars[hover].label}: ${yFormat(bars[hover].value)}`}
        </div>
      )}
    </div>
  );
}

/** Horizontal bar rows with a zero baseline, for signed per-category values (e.g. stance by kind). */
export function HBars({
  rows,
  format = (v: number) => v.toFixed(2),
  label,
  domain,
}: {
  rows: { label: ReactNode; key: string; value: number; color: string }[];
  format?: (v: number) => string;
  label: string;
  domain?: [number, number];
}) {
  const lo = domain ? domain[0] : Math.min(0, ...rows.map((r) => r.value));
  const hi = domain ? domain[1] : Math.max(0, ...rows.map((r) => r.value));
  const span = hi - lo || 1;
  const zero = ((0 - lo) / span) * 100;
  return (
    <ul className="space-y-1.5" aria-label={label}>
      {rows.map((r) => {
        const pos = ((r.value - lo) / span) * 100;
        const left = Math.min(pos, zero);
        const w = Math.abs(pos - zero);
        return (
          <li key={r.key} className="grid grid-cols-[7.5rem_minmax(0,1fr)_3.5rem] items-center gap-2 text-xs">
            <span className="truncate text-ink2">{r.label}</span>
            <span className="relative h-3 rounded-sm bg-[#1f1f1d]">
              <span className="absolute inset-y-0 w-px bg-line2" style={{ left: `${zero}%` }} />
              <span
                className="absolute inset-y-0.5 rounded-sm"
                style={{ left: `${left}%`, width: `${Math.max(0.5, w)}%`, background: r.color }}
              />
            </span>
            <span className="text-right tnum text-ink">{format(r.value)}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Stacked composition bar with a 2px surface gap between segments. */
export function CompositionBar({ parts, label }: { parts: { key: string; value: number; color: string; label: string }[]; label: string }) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  return (
    <div className="flex h-3 w-full gap-[2px] overflow-hidden rounded-sm" role="img" aria-label={label}>
      {parts
        .filter((p) => p.value > 0)
        .map((p) => (
          <span key={p.key} title={`${p.label}: ${p.value}`} style={{ width: `${(p.value / total) * 100}%`, background: p.color }} />
        ))}
    </div>
  );
}
