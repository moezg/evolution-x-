"use client";
import { useMemo, useState } from "react";
import { useWidth } from "./useWidth";
import { KINDS, kindColor, kindLabel, stanceColor } from "@/lib/colors";
import type { Network } from "@/lib/types";

type Layout = "force" | "circular";

function layoutPositions(net: Network, mode: Layout): Map<number, [number, number]> {
  const nodes = [...net.nodes].sort((a, b) => {
    const ka = KINDS.indexOf(a.kind as (typeof KINDS)[number]);
    const kb = KINDS.indexOf(b.kind as (typeof KINDS)[number]);
    return ka - kb || a.id - b.id;
  });
  const n = nodes.length;
  const pos = new Map<number, [number, number]>();
  nodes.forEach((nd, i) => {
    const a = (i / Math.max(1, n)) * Math.PI * 2;
    pos.set(nd.id, [0.5 + 0.45 * Math.cos(a), 0.5 + 0.45 * Math.sin(a)]);
  });
  if (mode === "circular" || n < 3 || n > 1200) return pos; // force layout is O(n²): skip for large populations

  // Fruchterman–Reingold, deterministic start from the grouped circle.
  const ids = nodes.map((d) => d.id);
  const idx = new Map(ids.map((id, i) => [id, i]));
  const X = new Float64Array(n);
  const Y = new Float64Array(n);
  ids.forEach((id, i) => {
    const p = pos.get(id)!;
    X[i] = p[0];
    Y[i] = p[1];
  });
  const E = net.edges.map(([a, b]) => [idx.get(a), idx.get(b)]).filter((e): e is [number, number] => e[0] !== undefined && e[1] !== undefined);
  const k = Math.sqrt(1 / n) * 0.9;
  let temp = 0.08;
  const dx = new Float64Array(n);
  const dy = new Float64Array(n);
  const iters = n > 400 ? 120 : 220;
  for (let it = 0; it < iters; it++) {
    dx.fill(0);
    dy.fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let ddx = X[i] - X[j];
        let ddy = Y[i] - Y[j];
        let d2 = ddx * ddx + ddy * ddy;
        if (d2 < 1e-9) {
          ddx = 1e-3 * ((i % 7) - 3);
          ddy = 1e-3 * ((j % 5) - 2);
          d2 = ddx * ddx + ddy * ddy;
        }
        const f = (k * k) / d2;
        dx[i] += ddx * f;
        dy[i] += ddy * f;
        dx[j] -= ddx * f;
        dy[j] -= ddy * f;
      }
    }
    for (const [a, b] of E) {
      const ddx = X[a] - X[b];
      const ddy = Y[a] - Y[b];
      const d = Math.sqrt(ddx * ddx + ddy * ddy) || 1e-6;
      const f = d / k;
      dx[a] -= ddx * f;
      dy[a] -= ddy * f;
      dx[b] += ddx * f;
      dy[b] += ddy * f;
    }
    for (let i = 0; i < n; i++) {
      // gentle gravity to the centre
      dx[i] += (0.5 - X[i]) * 0.6;
      dy[i] += (0.5 - Y[i]) * 0.6;
      const d = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) || 1e-9;
      const s = Math.min(d, temp) / d;
      X[i] += dx[i] * s;
      Y[i] += dy[i] * s;
    }
    temp *= 0.975;
  }
  // normalise into [0.04, 0.96]
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < n; i++) {
    x0 = Math.min(x0, X[i]); x1 = Math.max(x1, X[i]); y0 = Math.min(y0, Y[i]); y1 = Math.max(y1, Y[i]);
  }
  const sx = x1 - x0 || 1;
  const sy = y1 - y0 || 1;
  ids.forEach((id, i) => pos.set(id, [0.04 + 0.92 * ((X[i] - x0) / sx), 0.04 + 0.92 * ((Y[i] - y0) / sy)]));
  return pos;
}

export function NetworkGraph({ net, onOpen }: { net: Network; onOpen?: (id: number) => void }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [mode, setMode] = useState<Layout>("force");
  const [hover, setHover] = useState<number | null>(null);
  const [focusId, setFocusId] = useState<string>("");
  const topoKey = `${net.nodes.length}:${net.edges.length}:${net.edges.slice(0, 20).flat().join(",")}`;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const pos = useMemo(() => layoutPositions(net, mode), [topoKey, mode]);
  const nodeById = useMemo(() => new Map(net.nodes.map((n) => [n.id, n])), [net.nodes]);
  const active = hover ?? (focusId !== "" && nodeById.has(Number(focusId)) ? Number(focusId) : null);
  const nbrs = useMemo(() => {
    if (active === null) return null;
    const s = new Set<number>([active]);
    for (const [a, b] of net.edges) {
      if (a === active) s.add(b);
      if (b === active) s.add(a);
    }
    return s;
  }, [active, net.edges]);
  const size = Math.max(260, Math.min(width, 640));
  const P = (id: number) => {
    const p = pos.get(id) ?? [0.5, 0.5];
    return [p[0] * size, p[1] * size] as const;
  };
  const scale = size / 640;
  const hn = active !== null ? nodeById.get(active) : undefined;
  const kindsPresent = KINDS.filter((k) => net.nodes.some((n) => n.kind === k));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <fieldset className="flex items-center gap-2 text-ink2">
          <legend className="sr-only">Layout</legend>
          {(["force", "circular"] as const).map((m) => (
            <label key={m} className="flex items-center gap-1">
              <input type="radio" name="netlayout" checked={mode === m} onChange={() => setMode(m)} />
              {m === "force" ? "force-directed" : "circular (grouped by kind)"}
            </label>
          ))}
        </fieldset>
        <label className="field !flex-row items-center gap-2">
          <span>Highlight agent</span>
          <input className="input w-20" type="number" min={0} value={focusId} onChange={(e) => setFocusId(e.target.value)} />
        </label>
        {focusId !== "" && onOpen && nodeById.has(Number(focusId)) && (
          <button className="btn btn-sm" onClick={() => onOpen(Number(focusId))}>Open #{focusId}</button>
        )}
      </div>
      <div ref={ref} className="relative w-full">
        <svg
          width={size}
          height={size}
          role="img"
          aria-label={`Interaction graph: ${net.nodes.length} agents, ${net.edges.length} edges. Color = kind, size = reputation, outline = stance.`}
          className="mx-auto block"
        >
          <g stroke="#4a4a46" strokeWidth={0.6}>
            {net.edges.map(([a, b], i) => {
              const [x1, y1] = P(a);
              const [x2, y2] = P(b);
              const on = nbrs && nbrs.has(a) && nbrs.has(b) && (a === active || b === active);
              return (
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
                  strokeOpacity={nbrs ? (on ? 0.95 : 0.06) : 0.35}
                  stroke={on ? "#f0efec" : undefined} strokeWidth={on ? 1.2 : 0.6} />
              );
            })}
          </g>
          {net.nodes.map((n) => {
            const [x, y] = P(n.id);
            const r = Math.max(2.2, Math.min(9, 2 + 3.2 * (n.reputation ?? 1))) * Math.max(0.7, scale);
            const dim = nbrs && !nbrs.has(n.id);
            return (
              <circle
                key={n.id}
                cx={x}
                cy={y}
                r={n.id === active ? r + 2 : r}
                fill={kindColor(n.kind)}
                stroke={stanceColor(n.stance)}
                strokeWidth={Math.abs(n.stance) > 0.05 ? 2 : 1}
                opacity={dim ? 0.2 : 1}
                onMouseEnter={() => setHover(n.id)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onOpen?.(n.id)}
                style={{ cursor: onOpen ? "pointer" : undefined }}
              >
                <title>{`#${n.id} ${n.kind} · stance ${n.stance.toFixed(2)} · rep ${n.reputation.toFixed(2)}`}</title>
              </circle>
            );
          })}
        </svg>
        {hn && (
          <div className="pointer-events-none absolute left-1 top-1 rounded-md border border-line2 bg-[#0f0f0e]/95 px-2 py-1.5 text-[11px] tnum">
            <div className="font-semibold">#{hn.id} · {kindLabel(hn.kind)}</div>
            <div className="text-ink2">stance {hn.stance.toFixed(3)} · reputation {hn.reputation.toFixed(3)}</div>
            <div className="text-ink2">{(nbrs?.size ?? 1) - 1} neighbors</div>
          </div>
        )}
      </div>
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink2" aria-label="Kind legend">
        {kindsPresent.map((k) => (
          <li key={k} className="flex items-center gap-1">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: kindColor(k) }} />
            {kindLabel(k)}
          </li>
        ))}
        <li className="flex items-center gap-1">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full border-2" style={{ borderColor: stanceColor(1) }} /> bullish outline
        </li>
        <li className="flex items-center gap-1">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full border-2" style={{ borderColor: stanceColor(-1) }} /> bearish outline
        </li>
      </ul>
    </div>
  );
}
