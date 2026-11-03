"use client";
import { useMemo, useState } from "react";
import { useWidth } from "./useWidth";
import { defaultFmt, niceTicks } from "./charts";
import { seqColor } from "@/lib/colors";
import { fmtAny } from "@/lib/format";
import type { Candidate, StatBlock } from "@/lib/types";

const MUTED = "#9a9890";

/* ---------------------------------------------------------------- CI strip plot */

export interface StripRow {
  label: string;
  color: string;
  values?: number[];
  stat?: StatBlock;
}

/** Horizontal strip plot: individual replicate dots + mean with 95% t-CI bar per row. */
export function CIStrip({ rows, label, zero = false, fmt = defaultFmt }: { rows: StripRow[]; label: string; zero?: boolean; fmt?: (v: number) => string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const m = { l: 92, r: 14, t: 6, b: 20 };
  const rowH = 26;
  const height = m.t + m.b + rows.length * rowH;
  const vals: number[] = [];
  rows.forEach((r) => {
    (r.values ?? []).forEach((v) => Number.isFinite(v) && vals.push(v));
    if (r.stat) [r.stat.mean, r.stat.t_lo, r.stat.t_hi].forEach((v) => v !== undefined && Number.isFinite(v) && vals.push(v as number));
  });
  if (zero) vals.push(0);
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  if (!Number.isFinite(lo)) {
    lo = 0;
    hi = 1;
  }
  if (lo === hi) {
    lo -= Math.abs(lo) * 0.1 || 1;
    hi += Math.abs(hi) * 0.1 || 1;
  }
  const pad = (hi - lo) * 0.06;
  lo -= pad;
  hi += pad;
  const iw = Math.max(10, width - m.l - m.r);
  const sx = (v: number) => m.l + ((v - lo) / (hi - lo)) * iw;
  const ticks = niceTicks(lo, hi, Math.max(2, Math.floor(iw / 80)));
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label={label} className="block">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={sx(t)} x2={sx(t)} y1={m.t} y2={height - m.b} stroke="#2c2c2a" />
            <text x={sx(t)} y={height - 5} textAnchor="middle" fontSize={10} fill={MUTED} className="tnum">
              {fmt(t)}
            </text>
          </g>
        ))}
        {zero && lo < 0 && hi > 0 && <line x1={sx(0)} x2={sx(0)} y1={m.t} y2={height - m.b} stroke="#8a8984" strokeDasharray="3 3" />}
        {rows.map((r, i) => {
          const cy = m.t + i * rowH + rowH / 2;
          const s = r.stat;
          return (
            <g key={r.label}>
              <text x={m.l - 8} y={cy} dy="0.32em" textAnchor="end" fontSize={11} fill="#c3c2b7">
                {r.label}
              </text>
              {(r.values ?? []).map((v, j) => (
                <circle key={j} cx={sx(v)} cy={cy + ((j % 3) - 1) * 3} r={3.5} fill={r.color} fillOpacity={0.45} stroke={r.color} strokeWidth={1}>
                  <title>{`${r.label} replicate ${j + 1}: ${fmt(v)}`}</title>
                </circle>
              ))}
              {s && s.t_lo !== undefined && s.t_hi !== undefined && Number.isFinite(s.t_lo) && Number.isFinite(s.t_hi) && (
                <g>
                  <line x1={sx(s.t_lo)} x2={sx(s.t_hi)} y1={cy} y2={cy} stroke="#f0efec" strokeWidth={2} />
                  <line x1={sx(s.t_lo)} x2={sx(s.t_lo)} y1={cy - 6} y2={cy + 6} stroke="#f0efec" strokeWidth={2} />
                  <line x1={sx(s.t_hi)} x2={sx(s.t_hi)} y1={cy - 6} y2={cy + 6} stroke="#f0efec" strokeWidth={2} />
                </g>
              )}
              {s && s.mean !== undefined && Number.isFinite(s.mean) && (
                <rect x={sx(s.mean) - 5} y={cy - 5} width={10} height={10} transform={`rotate(45 ${sx(s.mean)} ${cy})`} fill={r.color} stroke="#161615" strokeWidth={2}>
                  <title>{`${r.label}: mean ${fmt(s.mean)} · 95% CI [${fmt(s.t_lo ?? NaN)}, ${fmt(s.t_hi ?? NaN)}] · n=${s.n ?? "?"}`}</title>
                </rect>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/* ---------------------------------------------------------------- objective scatter */

export function ObjectiveScatter({ candidates, xKey, yKey }: { candidates: Candidate[]; xKey: string; yKey: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<Candidate | null>(null);
  const pts = candidates.filter((c) => c.objectives && Number.isFinite(c.objectives[xKey]) && Number.isFinite(c.objectives[yKey]));
  const gens = Array.from(new Set(candidates.map((c) => c.generation))).sort((a, b) => a - b);
  const height = 300;
  const m = { l: 52, r: 14, t: 10, b: 34 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = height - m.t - m.b;
  const xs = pts.map((p) => p.objectives![xKey]);
  const ys = pts.map((p) => p.objectives![yKey]);
  const ext = (a: number[]) => {
    let lo = Math.min(...a), hi = Math.max(...a);
    if (!Number.isFinite(lo)) return [0, 1];
    if (lo === hi) { lo -= 0.5; hi += 0.5; }
    const p = (hi - lo) * 0.08;
    return [lo - p, hi + p];
  };
  const [x0, x1] = ext(xs);
  const [y0, y1] = ext(ys);
  const sx = (v: number) => m.l + ((v - x0) / (x1 - x0)) * iw;
  const sy = (v: number) => m.t + ih - ((v - y0) / (y1 - y0)) * ih;
  // 2-D Pareto front (maximise both) over the plotted axes
  const front = useMemo(() => {
    const f = pts.filter((p) => !pts.some((q) => q !== p && q.objectives![xKey] >= p.objectives![xKey] && q.objectives![yKey] >= p.objectives![yKey] && (q.objectives![xKey] > p.objectives![xKey] || q.objectives![yKey] > p.objectives![yKey])));
    return f.sort((a, b) => a.objectives![xKey] - b.objectives![xKey]);
  }, [pts, xKey, yKey]);
  const frontSet = new Set(front.map((f) => f.id));
  if (!pts.length) return <p className="text-xs text-muted">No candidates with objectives &ldquo;{xKey}&rdquo; and &ldquo;{yKey}&rdquo; yet.</p>;
  return (
    <div ref={ref} className="relative w-full">
      <svg width={width} height={height} role="img" aria-label={`Scatter of candidates: ${xKey} vs ${yKey}, colored by generation`} className="block">
        {niceTicks(y0, y1, 5).map((t) => (
          <g key={`y${t}`}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke="#2c2c2a" />
            <text x={m.l - 6} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">{defaultFmt(t)}</text>
          </g>
        ))}
        {niceTicks(x0, x1, Math.max(2, Math.floor(iw / 80))).map((t) => (
          <g key={`x${t}`}>
            <line x1={sx(t)} x2={sx(t)} y1={m.t} y2={m.t + ih} stroke="#2c2c2a" />
            <text x={sx(t)} y={m.t + ih + 14} textAnchor="middle" fontSize={10} fill={MUTED} className="tnum">{defaultFmt(t)}</text>
          </g>
        ))}
        <text x={m.l + iw / 2} y={height - 4} textAnchor="middle" fontSize={11} fill="#c3c2b7">{xKey} →</text>
        <text x={12} y={m.t + ih / 2} textAnchor="middle" fontSize={11} fill="#c3c2b7" transform={`rotate(-90 12 ${m.t + ih / 2})`}>{yKey} →</text>
        {front.length > 1 && (
          <polyline points={front.map((p) => `${sx(p.objectives![xKey])},${sy(p.objectives![yKey])}`).join(" ")} fill="none" stroke="#f0efec" strokeDasharray="4 3" strokeWidth={1.5} />
        )}
        {pts.map((p) => {
          const gi = gens.indexOf(p.generation);
          const champ = p.status === "champion";
          return (
            <circle
              key={p.id}
              cx={sx(p.objectives![xKey])}
              cy={sy(p.objectives![yKey])}
              r={frontSet.has(p.id) ? 7 : 5}
              fill={seqColor(gi, gens.length)}
              stroke={champ ? "#f2c14e" : frontSet.has(p.id) ? "#f0efec" : "#161615"}
              strokeWidth={champ || frontSet.has(p.id) ? 2.5 : 1.5}
              onMouseEnter={() => setHover(p)}
              onMouseLeave={() => setHover(null)}
            >
              <title>{`${p.id} · gen ${p.generation} · ${p.origin} · ${xKey} ${fmtAny(p.objectives![xKey])} · ${yKey} ${fmtAny(p.objectives![yKey])}`}</title>
            </circle>
          );
        })}
      </svg>
      {hover && (
        <div className="pointer-events-none absolute right-1 top-1 max-w-[60%] rounded-md border border-line2 bg-[#0f0f0e]/95 px-2 py-1.5 text-[11px] tnum">
          <div className="font-semibold">{hover.id}</div>
          <div className="text-ink2">gen {hover.generation} · {hover.origin} · {hover.status}{hover.pareto_rank !== null && hover.pareto_rank !== undefined ? ` · pareto rank ${hover.pareto_rank}` : ""}</div>
          {hover.objectives && <div className="text-muted">{Object.entries(hover.objectives).map(([k, v]) => `${k} ${defaultFmt(v)}`).join(" · ")}</div>}
        </div>
      )}
      <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink2" aria-label="Legend">
        {gens.map((g, i) => (
          <li key={g} className="flex items-center gap-1">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: seqColor(i, gens.length) }} />
            gen {g}
          </li>
        ))}
        <li className="flex items-center gap-1"><span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full border-2 border-ink" /> Pareto front (dashed)</li>
        <li className="flex items-center gap-1"><span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full border-2 border-[#f2c14e]" /> champion</li>
      </ul>
    </div>
  );
}

/* ---------------------------------------------------------------- lineage tree */

export const ORIGIN_COLORS: Record<string, string> = {
  default: "#898781",
  champion: "#199e70",
  mutation: "#3987e5",
  crossover: "#d95926",
  llm_synthesis: "#9085e9",
};

export function LineageTree({ candidates, onSelect, selected }: { candidates: Candidate[]; onSelect?: (c: Candidate) => void; selected?: string | null }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<string | null>(null);
  const byGen = useMemo(() => {
    const g = new Map<number, Candidate[]>();
    for (const c of candidates) {
      const arr = g.get(c.generation) ?? [];
      arr.push(c);
      g.set(c.generation, arr);
    }
    for (const arr of g.values()) arr.sort((a, b) => String(a.created ?? a.id).localeCompare(String(b.created ?? b.id)));
    return [...g.entries()].sort((a, b) => a[0] - b[0]);
  }, [candidates]);
  if (!candidates.length) return <p className="text-xs text-muted">No candidates.</p>;
  const maxN = Math.max(...byGen.map(([, a]) => a.length));
  const rowH = 30;
  const m = { l: 10, r: 10, t: 24, b: 10 };
  const colW = Math.max(70, (width - m.l - m.r) / Math.max(1, byGen.length));
  const svgW = Math.max(width, m.l + m.r + colW * byGen.length);
  const height = m.t + m.b + maxN * rowH;
  const pos = new Map<string, [number, number]>();
  byGen.forEach(([, arr], gi) => {
    const off = ((maxN - arr.length) * rowH) / 2;
    arr.forEach((c, i) => pos.set(c.id, [m.l + gi * colW + colW / 2, m.t + off + i * rowH + rowH / 2]));
  });
  const hl = hover ?? selected ?? null;
  const related = new Set<string>();
  if (hl) {
    related.add(hl);
    const c = candidates.find((x) => x.id === hl);
    (c?.parents ?? []).forEach((p) => related.add(p));
    candidates.forEach((x) => (x.parents ?? []).includes(hl) && related.add(x.id));
  }
  return (
    <div ref={ref} className="w-full overflow-x-auto">
      <svg width={svgW} height={height} role="img" aria-label="Strategy lineage tree: generations left to right, edges from parents to children" className="block">
        {byGen.map(([g], gi) => (
          <text key={g} x={m.l + gi * colW + colW / 2} y={14} textAnchor="middle" fontSize={11} fill={MUTED}>
            gen {g}
          </text>
        ))}
        {candidates.flatMap((c) =>
          (c.parents ?? []).map((p) => {
            const a = pos.get(p);
            const b = pos.get(c.id);
            if (!a || !b) return null;
            const on = hl && related.has(p) && related.has(c.id) && (p === hl || c.id === hl);
            const mx = (a[0] + b[0]) / 2;
            return (
              <path key={`${p}-${c.id}`} d={`M${a[0]},${a[1]} C${mx},${a[1]} ${mx},${b[1]} ${b[0]},${b[1]}`} fill="none"
                stroke={on ? "#f0efec" : "#4a4a46"} strokeWidth={on ? 1.8 : 1} strokeOpacity={hl && !on ? 0.25 : 0.8} />
            );
          }),
        )}
        {candidates.map((c) => {
          const p = pos.get(c.id)!;
          const champ = c.status === "champion";
          const bad = c.status === "rejected_regression" || c.status === "failed";
          return (
            <g key={c.id} transform={`translate(${p[0]},${p[1]})`} style={{ cursor: onSelect ? "pointer" : undefined }}
              onMouseEnter={() => setHover(c.id)} onMouseLeave={() => setHover(null)} onClick={() => onSelect?.(c)}
              opacity={hl && !related.has(c.id) ? 0.35 : c.status === "retired" ? 0.5 : 1}>
              <circle r={champ ? 9 : 7} fill={ORIGIN_COLORS[c.origin] ?? "#6f6e69"}
                stroke={champ ? "#f2c14e" : bad ? "#e66767" : selected === c.id ? "#f0efec" : "#161615"}
                strokeWidth={champ || bad || selected === c.id ? 2.5 : 1.5} strokeDasharray={bad ? "2 2" : undefined} />
              {c.pareto_rank === 0 && <circle r={2} fill="#f0efec" />}
              <title>{`${c.id}\ngen ${c.generation} · ${c.origin} · ${c.status}${c.parents?.length ? `\nparents: ${c.parents.join(", ")}` : ""}`}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/* ---------------------------------------------------------------- paired per-run bars */

export function PairedRunBars({ perRun }: { perRun: { seed: number; regime: string; u_challenger: number; u_champion: number }[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const height = 190;
  const m = { l: 44, r: 8, t: 8, b: 44 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = height - m.t - m.b;
  const vals = perRun.flatMap((r) => [r.u_challenger, r.u_champion, 0]);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const sy = (v: number) => m.t + ih - ((v - lo) / (hi - lo || 1)) * ih;
  const gw = iw / Math.max(1, perRun.length);
  const bw = Math.max(2, Math.min(18, (gw - 6) / 2));
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label="Per-run utility: challenger vs champion on paired seeds" className="block">
        {niceTicks(lo, hi, 4).map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke="#2c2c2a" />
            <text x={m.l - 6} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">{defaultFmt(t)}</text>
          </g>
        ))}
        {perRun.map((r, i) => {
          const cx = m.l + i * gw + gw / 2;
          const bar = (v: number, x: number, color: string, who: string) => (
            <rect x={x} y={Math.min(sy(v), sy(0))} width={bw} height={Math.max(1, Math.abs(sy(v) - sy(0)))} fill={color} rx={2}>
              <title>{`seed ${r.seed} · ${r.regime} · ${who} ${v.toFixed(4)}`}</title>
            </rect>
          );
          return (
            <g key={i}>
              {bar(r.u_challenger, cx - bw - 1, "#3987e5", "challenger")}
              {bar(r.u_champion, cx + 1, "#898781", "champion")}
              <text x={cx} y={height - 28} textAnchor="middle" fontSize={9} fill={MUTED}>s{r.seed}</text>
              {gw >= 56 && <text x={cx} y={height - 16} textAnchor="middle" fontSize={9} fill={MUTED}>{r.regime.length > 12 ? r.regime.slice(0, 11) + "…" : r.regime}</text>}
            </g>
          );
        })}
        <line x1={m.l} x2={m.l + iw} y1={sy(0)} y2={sy(0)} stroke="#6a6964" />
      </svg>
      <ul className="flex gap-3 text-[11px] text-ink2" aria-label="Legend">
        <li className="flex items-center gap-1"><span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm bg-[#3987e5]" /> challenger</li>
        <li className="flex items-center gap-1"><span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm bg-[#898781]" /> champion</li>
      </ul>
    </div>
  );
}

/* ---------------------------------------------------------------- unified diff */

export function DiffView({ diff }: { diff?: string }) {
  if (!diff) return <p className="text-xs text-muted">No diff.</p>;
  const lines = diff.split("\n");
  return (
    <pre className="max-h-[480px] overflow-auto rounded-md border border-line bg-[#0b0b0a] py-2 text-[12px] leading-5" aria-label="Unified diff">
      {lines.map((l, i) => {
        let cls = "text-ink2";
        let sr = "";
        if (l.startsWith("+++") || l.startsWith("---")) cls = "text-ink font-semibold";
        else if (l.startsWith("@@")) cls = "text-[#9ec5f4] bg-accent/10";
        else if (l.startsWith("+")) { cls = "text-[#7fe0b5] bg-up/10"; sr = "added: "; }
        else if (l.startsWith("-")) { cls = "text-[#f3a7a7] bg-down/10"; sr = "removed: "; }
        else if (l.startsWith("diff ") || l.startsWith("index ")) cls = "text-muted";
        return (
          <div key={i} className={`whitespace-pre px-3 ${cls}`}>
            {sr && <span className="sr-only">{sr}</span>}
            {l || " "}
          </div>
        );
      })}
    </pre>
  );
}
