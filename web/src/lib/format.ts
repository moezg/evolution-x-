export function hms(totalSeconds: number): string {
  if (!Number.isFinite(totalSeconds)) return "--:--:--";
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

export function num(v: unknown, digits = 2): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function compact(v: unknown, digits = 1): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: digits }).format(v);
}

export function usd(v: unknown, digits = 2): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const r = Number(v.toFixed(digits));
  return (r < 0 ? "−$" : "$") + num(Math.abs(r) || 0, digits);
}

export function pct(v: unknown, digits = 2): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

export function signed(v: unknown, digits = 3): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

export function fmtAny(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return v.toLocaleString("en-US");
    const a = Math.abs(v);
    if (a !== 0 && (a < 1e-3 || a >= 1e7)) return v.toExponential(3);
    return v.toLocaleString("en-US", { maximumFractionDigits: 4 });
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

export function fmtTime(ts: unknown): string {
  if (ts === null || ts === undefined || ts === "") return "—";
  let d: Date;
  if (typeof ts === "number") d = new Date(ts < 1e12 ? ts * 1000 : ts);
  else d = new Date(String(ts));
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toISOString().replace("T", " ").slice(0, 19) + "Z";
}

export function humanize(key: string): string {
  return key.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
