"use client";
import { useState } from "react";
import { useWidth } from "./useWidth";
import { defaultFmt, niceTicks } from "./charts";
import { DOWN, UP } from "@/lib/colors";
import type { Book } from "@/lib/types";

function cumulate(levels: [number, number][]): [number, number][] {
  let c = 0;
  return levels.map(([p, q]) => {
    c += q;
    return [p, c];
  });
}

/** Cumulative depth chart: bids (left, green) / asks (right, red) as step areas. */
export function DepthChart({ book, height = 200 }: { book: Book; height?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<string | null>(null);
  const bids = cumulate(book.bids);
  const asks = cumulate(book.asks);
  if (!bids.length && !asks.length) return <p className="text-xs text-muted">Empty book.</p>;
  const m = { l: 44, r: 10, t: 8, b: 22 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = Math.max(10, height - m.t - m.b);
  const pLo = bids.length ? bids[bids.length - 1][0] : asks[0][0];
  const pHi = asks.length ? asks[asks.length - 1][0] : bids[0][0];
  const qMax = Math.max(bids.length ? bids[bids.length - 1][1] : 0, asks.length ? asks[asks.length - 1][1] : 0) || 1;
  const sx = (p: number) => m.l + ((p - pLo) / (pHi - pLo || 1)) * iw;
  const sy = (q: number) => m.t + ih - (q / qMax) * ih;
  const step = (pts: [number, number][], side: "bid" | "ask") => {
    if (!pts.length) return "";
    const base = sy(0);
    let d = `M${sx(pts[0][0])},${base}`;
    let prevQ = 0;
    for (const [p, q] of pts) {
      d += `L${sx(p)},${sy(prevQ)}L${sx(p)},${sy(q)}`;
      prevQ = q;
    }
    const end = side === "bid" ? sx(pLo) : sx(pHi);
    d += `L${end},${sy(prevQ)}L${end},${base}Z`;
    return d;
  };
  const xt = niceTicks(pLo, pHi, Math.max(2, Math.floor(iw / 90)));
  const yt = niceTicks(0, qMax, 3);
  const mid = bids.length && asks.length ? (book.bids[0][0] + book.asks[0][0]) / 2 : null;
  return (
    <div ref={ref} className="relative w-full">
      <svg width={width} height={height} role="img" aria-label="Order book cumulative depth chart" className="block">
        {yt.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke="#2c2c2a" />
            <text x={m.l - 6} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill="#9a9890" className="tnum">
              {defaultFmt(t)}
            </text>
          </g>
        ))}
        {xt.map((t) => (
          <text key={t} x={sx(t)} y={height - 6} textAnchor="middle" fontSize={10} fill="#9a9890" className="tnum">
            {t.toFixed(0)}
          </text>
        ))}
        <path d={step(bids, "bid")} fill={UP} fillOpacity={hover === "ask" ? 0.12 : 0.25} stroke={UP} strokeWidth={2}
          onMouseEnter={() => setHover("bid")} onMouseLeave={() => setHover(null)} />
        <path d={step(asks, "ask")} fill={DOWN} fillOpacity={hover === "bid" ? 0.12 : 0.25} stroke={DOWN} strokeWidth={2}
          onMouseEnter={() => setHover("ask")} onMouseLeave={() => setHover(null)} />
        {mid !== null && <line x1={sx(mid)} x2={sx(mid)} y1={m.t} y2={m.t + ih} stroke="#6a6964" strokeDasharray="3 3" />}
        <line x1={m.l} x2={m.l + iw} y1={sy(0)} y2={sy(0)} stroke="#383835" />
      </svg>
      <div className="pointer-events-none absolute left-12 top-1 text-[11px] text-ink2">
        cum. BTC · bids <span className="text-up">{bids.length ? bids[bids.length - 1][1].toFixed(2) : "0"}</span> / asks{" "}
        <span className="text-down">{asks.length ? asks[asks.length - 1][1].toFixed(2) : "0"}</span>
      </div>
    </div>
  );
}

/** Price ladder: asks above, bids below, with size bars. */
export function Ladder({ book, rows = 10 }: { book: Book; rows?: number }) {
  const asks = book.asks.slice(0, rows).reverse();
  const bids = book.bids.slice(0, rows);
  const maxQ = Math.max(1e-9, ...asks.map((a) => a[1]), ...bids.map((b) => b[1]));
  const spread = book.asks[0] && book.bids[0] ? book.asks[0][0] - book.bids[0][0] : null;
  const mid = book.asks[0] && book.bids[0] ? (book.asks[0][0] + book.bids[0][0]) / 2 : null;
  const Row = ({ p, q, side }: { p: number; q: number; side: "bid" | "ask" }) => (
    <tr className="relative">
      <td className={`relative py-0.5 pr-2 text-right tnum ${side === "bid" ? "text-up" : "text-down"}`}>{p.toFixed(2)}</td>
      <td className="relative w-1/2 py-0.5 text-right tnum text-ink2">
        <span
          aria-hidden
          className="absolute inset-y-0.5 right-0 rounded-sm"
          style={{ width: `${(q / maxQ) * 100}%`, background: side === "bid" ? "rgba(27,175,122,0.18)" : "rgba(230,103,103,0.18)" }}
        />
        <span className="relative pr-1">{q.toFixed(4)}</span>
      </td>
    </tr>
  );
  return (
    <table className="w-full text-xs" aria-label="Order book ladder">
      <thead>
        <tr className="text-[10px] uppercase tracking-wider text-muted">
          <th className="pb-1 pr-2 text-right font-medium">Price USD</th>
          <th className="pb-1 text-right font-medium">Size BTC</th>
        </tr>
      </thead>
      <tbody>
        {asks.map(([p, q]) => (
          <Row key={`a${p}`} p={p} q={q} side="ask" />
        ))}
        <tr>
          <td colSpan={2} className="border-y border-line py-1 text-center text-[11px] text-muted tnum">
            mid {mid?.toFixed(2) ?? "—"} · spread {spread?.toFixed(2) ?? "—"}
            {spread !== null && mid ? ` (${((spread / mid) * 1e4).toFixed(2)} bps)` : ""}
          </td>
        </tr>
        {bids.map(([p, q]) => (
          <Row key={`b${p}`} p={p} q={q} side="bid" />
        ))}
      </tbody>
    </table>
  );
}
