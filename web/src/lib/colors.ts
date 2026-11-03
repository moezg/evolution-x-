/** Fixed categorical order (dark-surface steps). Color follows the agent kind, never its rank. */
export const KINDS = [
  "noise", "momentum", "value", "market_maker", "arbitrage",
  "execution", "whale", "leveraged", "news", "adaptive",
] as const;

const KIND_COLORS: Record<string, string> = {
  momentum: "#3987e5",
  value: "#d95926",
  market_maker: "#199e70",
  arbitrage: "#c98500",
  execution: "#d55181",
  whale: "#2f9e2f",
  leveraged: "#9085e9",
  news: "#e66767",
  noise: "#898781",
  adaptive: "#c3c2b7",
};

export function kindColor(kind: string): string {
  return KIND_COLORS[kind] ?? "#6f6e69";
}

export function kindLabel(kind: string): string {
  return kind.replace(/_/g, " ");
}

/** Diverging blue (bullish, +) ↔ red (bearish, −) with neutral gray midpoint. */
export function stanceColor(s: number): string {
  const v = Math.max(-1, Math.min(1, s || 0));
  const mid = [0x6a, 0x69, 0x64];
  const pos = [0x39, 0x87, 0xe5];
  const neg = [0xe6, 0x67, 0x67];
  const t = Math.abs(v);
  const tgt = v >= 0 ? pos : neg;
  const c = mid.map((m, i) => Math.round(m + (tgt[i] - m) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

/** Sequential blue ramp for ordered values (e.g. generation). */
const SEQ = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95"];
export function seqColor(i: number, n: number): string {
  if (n <= 1) return SEQ[3];
  const idx = Math.round((i / (n - 1)) * (SEQ.length - 1));
  return SEQ[Math.max(0, Math.min(SEQ.length - 1, idx))];
}

export const UP = "#1baf7a";
export const DOWN = "#e66767";
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#2f9e2f", "#9085e9", "#e66767"];
