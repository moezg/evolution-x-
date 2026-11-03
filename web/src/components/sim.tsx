"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiPost, errorMessage } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { KINDS, kindColor, kindLabel } from "@/lib/colors";
import { hms, num, pct, signed } from "@/lib/format";
import type { AgentRow, Scenario, SimEvent, SimState } from "@/lib/types";
import { EmptyState, ErrorNote, Panel, StatusPill } from "./ui";

export const REPLAY_DAYS = [
  "2026-10-01", "2026-10-02", "2026-09-01", "2026-09-02", "2026-09-03",
  "2026-09-04", "2026-09-05", "2026-09-15", "2026-09-16",
];

export const SCALES = [
  { value: 1, label: "256 agents" },
  { value: 3.90625, label: "≈1,000 agents" },
  { value: 39.0625, label: "≈10,000 agents" },
];

export function StartForm({ onStarted }: { onStarted?: (s: SimState) => void }) {
  const scen = usePoll<Scenario[]>("/api/scenarios", 0);
  const [seed, setSeed] = useState(1);
  const [duration, setDuration] = useState(3600);
  const [scenario, setScenario] = useState("baseline");
  const [speed, setSpeed] = useState(50);
  const [scale, setScale] = useState(1);
  const [mode, setMode] = useState<"synthetic" | "replay">("synthetic");
  const [day, setDay] = useState(REPLAY_DAYS[0]);
  const [shockAt, setShockAt] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const desc = scen.data?.find((s) => s.name === scenario)?.description;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(undefined);
    try {
      const body: Record<string, unknown> = { seed, duration_s: duration, scenario, speed, scale, mode };
      if (mode === "replay") body.replay_day = day;
      if (shockAt.trim() !== "") body.shock_at_s = Number(shockAt);
      const s = await apiPost<SimState>("/api/sim/start", body);
      onStarted?.(s);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Start simulation">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <label className="field">
          Seed
          <input className="input tnum" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
        </label>
        <label className="field">
          Duration (virtual s)
          <input className="input tnum" type="number" min={60} max={86400} step={60} value={duration} onChange={(e) => setDuration(Number(e.target.value))} />
        </label>
        <label className="field col-span-2 sm:col-span-1">
          Scenario
          <select className="input" value={scenario} onChange={(e) => setScenario(e.target.value)}>
            {(scen.data ?? [{ name: "baseline" } as Scenario]).map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Speed (virtual s / wall s, 0 = max)
          <input className="input tnum" type="number" min={0} step="any" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} />
        </label>
        <label className="field">
          Population scale
          <select className="input" value={scale} onChange={(e) => setScale(Number(e.target.value))}>
            {SCALES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="field">
          <legend className="mb-1">Data mode</legend>
          <div className="flex gap-3 text-sm text-ink">
            {(["synthetic", "replay"] as const).map((m) => (
              <label key={m} className="flex items-center gap-1.5">
                <input type="radio" name="mode" value={m} checked={mode === m} onChange={() => setMode(m)} />
                {m}
              </label>
            ))}
          </div>
        </fieldset>
        {mode === "replay" && (
          <label className="field">
            Replay day (historical anchor)
            <select className="input" value={day} onChange={(e) => setDay(e.target.value)}>
              {REPLAY_DAYS.map((d) => (
                <option key={d}>{d}</option>
              ))}
            </select>
          </label>
        )}
        <label className="field">
          Shock at (s, optional)
          <input className="input tnum" type="number" min={0} placeholder="scenario default" value={shockAt} onChange={(e) => setShockAt(e.target.value)} />
        </label>
      </div>
      {desc && <p className="text-xs text-muted">{desc}</p>}
      {mode === "replay" && (
        <p className="text-xs text-muted">
          Replay mode anchors the synthetic market to a recorded day; the recorded series is overlaid as <b className="text-[#f2c14e]">HISTORICAL</b> and the
          simulated path is <b>COUNTERFACTUAL · SYNTHETIC</b>.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Starting…" : "▶ Start simulation"}
        </button>
        {err && <span role="alert" className="text-xs text-down">{err}</span>}
      </div>
    </form>
  );
}

const SPEEDS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 0];
const speedLabel = (v: number) => (v === 0 ? "max" : `${v}×`);

export function SimControls({ state }: { state: SimState }) {
  const [busy, setBusy] = useState<string>();
  const [msg, setMsg] = useState<{ ok: boolean; text: string }>();
  const curIdx = useMemo(() => {
    const s = state.speed ?? 20;
    let best = 0;
    SPEEDS.forEach((v, i) => {
      if (v === s) best = i;
      else if (s !== 0 && v !== 0 && Math.abs(Math.log(v / s)) < Math.abs(Math.log((SPEEDS[best] || 1e9) / s))) best = i;
    });
    return best;
  }, [state.speed]);
  const [idx, setIdx] = useState(curIdx);
  const dragging = useRef(false);
  useEffect(() => {
    if (!dragging.current) setIdx(curIdx);
  }, [curIdx]);

  const act = async (name: string, path: string, body?: unknown) => {
    setBusy(name);
    setMsg(undefined);
    try {
      const r = await apiPost<Record<string, unknown>>(path, body);
      if (name === "save") setMsg({ ok: true, text: `Saved run → ${String(r.path)}` });
      if (name === "stop") setMsg({ ok: true, text: "Emergency stop executed. Event loop halted." });
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy(undefined);
    }
  };
  const live = state.status === "running" || state.status === "paused";

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={state.status} />
        {state.status === "running" && (
          <button className="btn" onClick={() => act("pause", "/api/sim/pause")} disabled={!!busy}>
            ❚❚ Pause
          </button>
        )}
        {state.status === "paused" && (
          <button className="btn" onClick={() => act("resume", "/api/sim/resume")} disabled={!!busy}>
            ▶ Resume
          </button>
        )}
        <label className="flex min-w-[220px] flex-1 items-center gap-2 text-xs text-ink2 sm:flex-none">
          <span className="whitespace-nowrap">Speed</span>
          <input
            type="range"
            min={0}
            max={SPEEDS.length - 1}
            step={1}
            value={idx}
            aria-valuetext={speedLabel(SPEEDS[idx])}
            onChange={(e) => {
              dragging.current = true;
              setIdx(Number(e.target.value));
            }}
            onPointerUp={() => {
              dragging.current = false;
              act("speed", "/api/sim/speed", { speed: SPEEDS[idx] });
            }}
            onKeyUp={() => {
              dragging.current = false;
              act("speed", "/api/sim/speed", { speed: SPEEDS[idx] });
            }}
            className="w-32 flex-1"
          />
          <span className="w-12 text-right font-semibold text-ink tnum">{speedLabel(SPEEDS[idx])}</span>
        </label>
        <button className="btn" onClick={() => act("save", "/api/sim/save")} disabled={!!busy}>
          ⤓ Save run
        </button>
        <button
          className="btn btn-danger ml-auto px-4 py-2 text-sm"
          onClick={() => act("stop", "/api/sim/stop")}
          disabled={!live || busy === "stop"}
          aria-label="Emergency stop: halt the simulation event loop immediately"
        >
          ■ EMERGENCY STOP
        </button>
      </div>
      {msg && (
        <p role="status" className={`break-all text-xs ${msg.ok ? "text-up" : "text-down"}`}>
          {msg.text}
        </p>
      )}
    </div>
  );
}

const SHOCKS: Record<string, { mag: number; dur: number; help: string; step: string }> = {
  fundamental_drop: { mag: 0.05, dur: 300, help: "fraction of latent fundamental (0.05 = −5%)", step: "0.01" },
  flash_sell: { mag: 150, dur: 60, help: "BTC market-sold by an external account", step: "10" },
  liquidity_drought: { mag: 0.7, dur: 600, help: "fraction of market-maker size withdrawn", step: "0.05" },
  funding_spike: { mag: 0.0075, dur: 900, help: "funding rate per interval (0.0075 = 0.75%)", step: "0.0005" },
  news_panic: { mag: 4, dur: 300, help: "negative sentiment magnitude", step: "0.5" },
  arb_outage: { mag: 1, dur: 600, help: "1 = arbitrage connectivity down", step: "1" },
};

export function ShockPanel({ disabled }: { disabled?: boolean }) {
  const [type, setType] = useState("fundamental_drop");
  const [mag, setMag] = useState(SHOCKS.fundamental_drop.mag);
  const [dur, setDur] = useState(SHOCKS.fundamental_drop.dur);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string }>();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(undefined);
    try {
      await apiPost("/api/sim/inject", { type, at_s: 0, duration_s: dur, magnitude: mag, note });
      setMsg({ ok: true, text: `Injected ${type} (magnitude ${mag}, ${dur}s).` });
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Inject shock">
      <div className="grid grid-cols-2 gap-3">
        <label className="field col-span-2">
          Shock type
          <select
            className="input"
            value={type}
            onChange={(e) => {
              const t = e.target.value;
              setType(t);
              setMag(SHOCKS[t].mag);
              setDur(SHOCKS[t].dur);
            }}
          >
            {Object.keys(SHOCKS).map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Magnitude
          <input className="input tnum" type="number" step={SHOCKS[type].step} value={mag} onChange={(e) => setMag(Number(e.target.value))} />
        </label>
        <label className="field">
          Duration (s)
          <input className="input tnum" type="number" min={1} value={dur} onChange={(e) => setDur(Number(e.target.value))} />
        </label>
        <label className="field col-span-2">
          Note (optional)
          <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. stress test A" />
        </label>
      </div>
      <p className="text-[11px] text-muted">Magnitude: {SHOCKS[type].help}. Applies immediately at current virtual time.</p>
      <button type="submit" className="btn w-full border-warn/60 text-warn" disabled={busy || disabled}>
        ⚡ Inject shock now
      </button>
      {msg && (
        <p role="status" className={`text-xs ${msg.ok ? "text-up" : "text-down"}`}>
          {msg.text}
        </p>
      )}
    </form>
  );
}

const EVENT_TYPES = ["liquidation", "circuit_breaker", "news", "shock", "funding", "imitation"];
const EVENT_CLS: Record<string, string> = {
  liquidation: "text-down border-down/50",
  circuit_breaker: "text-warn border-warn/50",
  shock: "text-warn border-warn/50",
  news: "text-[#9ec5f4] border-accent/50",
  funding: "text-ink2 border-line2",
  imitation: "text-[#c3bdf5] border-[#9085e9]/50",
};

function describe(e: SimEvent): string {
  const d = e.data || {};
  switch (e.type) {
    case "news":
      return String(d.headline ?? `sentiment ${d.sentiment}`);
    case "imitation":
      return `agent #${e.agent} imitated #${d.source} (${String(d.kind ?? "")})`;
    case "funding":
      return `venue ${e.venue} funding ${typeof d.rate === "number" ? (d.rate * 100).toFixed(4) + "%" : "—"}`;
    case "liquidation":
      return `agent #${e.agent} liquidated${typeof d.equity === "number" ? ` (equity ${num(d.equity as number, 0)})` : ""}`;
    case "shock":
      return `${String(d.type ?? "shock")} ${d.magnitude ?? ""} ${d.note ? `— ${d.note}` : ""}`;
    case "circuit_breaker":
      return `venue ${e.venue} circuit breaker ${d.halted === false ? "lifted" : "triggered"}`;
    default:
      return JSON.stringify(d).slice(0, 120);
  }
}

export function EventsFeed({ enabled }: { enabled: boolean }) {
  const [types, setTypes] = useState<string[]>(EVENT_TYPES);
  const q = types.length ? types.join(",") : "none";
  const ev = usePoll<SimEvent[]>(enabled ? `/api/sim/events?types=${q}&limit=200` : null, 2000);
  const rows = useMemo(() => [...(ev.data ?? [])].sort((a, b) => b.t_ms - a.t_ms).slice(0, 120), [ev.data]);
  return (
    <div className="flex h-full flex-col gap-2">
      <fieldset className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink2">
        <legend className="sr-only">Event types</legend>
        {EVENT_TYPES.map((t) => (
          <label key={t} className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={types.includes(t)}
              onChange={(e) => setTypes((cur) => (e.target.checked ? [...cur, t] : cur.filter((x) => x !== t)))}
            />
            {t.replace("_", " ")}
          </label>
        ))}
      </fieldset>
      <ErrorNote error={ev.error} />
      {rows.length === 0 ? (
        <EmptyState title="No events yet" />
      ) : (
        <ol className="max-h-80 min-h-0 flex-1 space-y-1 overflow-y-auto pr-1 text-xs" aria-live="off">
          {rows.map((e, i) => (
            <li key={`${e.t_ms}-${e.type}-${e.agent}-${i}`} className="flex items-start gap-2 border-b border-line pb-1">
              <span className="shrink-0 text-muted tnum">{hms(e.t_ms / 1000)}</span>
              <span className={`shrink-0 rounded border px-1 text-[10px] uppercase ${EVENT_CLS[e.type] ?? "border-line2 text-ink2"}`}>{e.type.replace("_", " ")}</span>
              <span className="min-w-0 break-words text-ink2">{describe(e)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function PopulationTable({ agents, counts }: { agents?: AgentRow[]; counts?: Record<string, number> }) {
  const rows = useMemo(() => {
    const kinds = Array.from(new Set([...KINDS, ...Object.keys(counts ?? {})])).filter((k) => (counts?.[k] ?? 0) > 0 || agents?.some((a) => a.kind === k));
    return kinds.map((k) => {
      const as = (agents ?? []).filter((a) => a.kind === k);
      const n = as.length || counts?.[k] || 0;
      const mean = (f: (a: AgentRow) => number) => (as.length ? as.reduce((s, a) => s + f(a), 0) / as.length : NaN);
      return {
        kind: k,
        n,
        ret: mean((a) => a.return_pct),
        lev: mean((a) => a.leverage),
        stance: mean((a) => a.stance),
        net: as.reduce((s, a) => s + (a.positions_btc?.reduce((x, y) => x + y, 0) ?? 0), 0),
        liq: as.reduce((s, a) => s + (a.liquidations ?? 0), 0),
      };
    });
  }, [agents, counts]);
  if (!rows.length) return <EmptyState title="No population data" />;
  return (
    <div className="max-w-full overflow-x-auto">
      <table className="data">
        <thead>
          <tr>
            <th scope="col">Kind</th>
            <th scope="col" className="num">N</th>
            <th scope="col" className="num">Mean ret</th>
            <th scope="col" className="num">Mean lev</th>
            <th scope="col" className="num">Net pos BTC</th>
            <th scope="col" className="num">Stance</th>
            <th scope="col" className="num">Liqs</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.kind}>
              <td>
                <span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: kindColor(r.kind) }} aria-hidden />
                {kindLabel(r.kind)}
              </td>
              <td className="num">{r.n}</td>
              <td className={`num ${r.ret > 0 ? "text-up" : r.ret < 0 ? "text-down" : ""}`}>{pct(r.ret)}</td>
              <td className="num">{num(r.lev, 3)}</td>
              <td className="num">{num(r.net, 3)}</td>
              <td className="num">{signed(r.stance, 2)}</td>
              <td className={`num ${r.liq > 0 ? "text-down" : ""}`}>{r.liq}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
