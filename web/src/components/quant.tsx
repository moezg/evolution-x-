"use client";
import { useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { niceTicks } from "@/components/charts";
import { TableWrap, TONE_CLS } from "@/components/observatory";
import { Hash } from "@/components/research";
import { EmptyState, ErrorNote, Kpi, Legend, Panel } from "@/components/ui";
import { useWidth } from "@/components/useWidth";
import { ApiError } from "@/lib/api";
import { fmtAny, fmtTime } from "@/lib/format";
import type { Poll } from "@/lib/hooks";
import type { Tone } from "@/lib/observatory";
import {
  ACTION_COLOR,
  CAL_FAMILIES,
  calLabel,
  DIVISION,
  FAMILY_TASK,
  fp,
  fpct,
  fpctU,
  STAGES,
  STATUS_COLOR,
  STATUS_TEXT,
  statusKey,
  type CalendarResp,
  type CalResult,
  type CyclesResp,
  type ElectGroup,
  type ElectionsResp,
  type EventsResp,
  type FomcResp,
  type ForecastLinkResp,
  type Num,
  type QTask,
  type QuantAmendment,
  type QuantProtocol,
  type RankingsResp,
  type RankRow,
  type StatusKey,
  type TestRow,
  type TestsResp,
  type WorkflowResp,
} from "@/lib/quant";

/* ================================================================ primitives */

const GRID = "#2c2c2a";
const AXIS = "#383835";
const MUTED = "#9a9890";

const STATUS_TONE: Record<StatusKey, Tone> = {
  supported: "info",
  candidate: "info",
  inconclusive: "weak",
  exploratory: "neutral",
  descriptive: "neutral",
  not_promoted: "neutral",
  rejected: "neutral",
  other: "neutral",
};

/** Status badge. "supported" renders as "exploratory – survived confirmation", never as verified. */
export function QStatus({ s }: { s: string | null | undefined }) {
  if (!s) return <span className="text-[11px] text-muted">—</span>;
  const k = statusKey(s);
  const text = k === "other" ? s.replace(/_/g, " ") : STATUS_TEXT[k];
  return (
    <span
      title={`registry status: ${s}`}
      className={`inline-block max-w-full whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold ${TONE_CLS[STATUS_TONE[k]]}`}
    >
      {text}
    </span>
  );
}

function StatusLegend({ keys }: { keys: StatusKey[] }) {
  return <Legend items={keys.map((k) => ({ label: STATUS_TEXT[k], color: STATUS_COLOR[k], shape: "dot" as const }))} />;
}

/** Loading / 404 / error wrapper for artifacts under artifacts/quant/. */
export function QState<T>({ poll, what, children }: { poll: Poll<T>; what: string; children: (d: T) => ReactNode }) {
  if (poll.data) return <>{children(poll.data)}</>;
  if (poll.error instanceof ApiError && poll.error.status === 404)
    return (
      <EmptyState title={`${what}: not produced yet`}>
        <p>{poll.error.detail}</p>
        <p className="mt-1">The quant workflow writes this artifact when its run finishes; this page re-checks every minute.</p>
      </EmptyState>
    );
  if (poll.error) return <ErrorNote error={poll.error} what={what} />;
  return <p className="text-xs text-muted">Loading {what}…</p>;
}

function Seg<T extends string>({ options, value, onChange, label }: { options: { v: T; label: ReactNode }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1">
      {options.map((o) => (
        <button
          key={o.v}
          type="button"
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

function Note({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <div className={`rounded-md border px-3 py-2 text-xs leading-relaxed ${TONE_CLS[tone]}`}>{children}</div>;
}

const RATE_METRICS = new Set(["up_rate", "left_tail_rate"]);
/** Calendar effects: return metrics in %, rate metrics in percentage points. */
function fEff(metric: string, v: Num | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const x = v * 100;
  return `${x > 0 ? "+" : ""}${x.toFixed(2)}${RATE_METRICS.has(metric) ? " pp" : "%"}`;
}
function fz(v: Num | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? `${v > 0 ? "+" : ""}${v.toFixed(2)}` : "—";
}

/* ---------------------------------------------------------------- effect + CI chart */

interface EffRow {
  key: string;
  label: string;
  effect: number | null;
  lo: number | null;
  hi: number | null;
  color: string;
  tip: string;
}

/** Vertical bars from zero to the effect with a CI whisker. */
function EffectChart({ rows, label, fmt, height = 220 }: { rows: EffRow[]; label: string; fmt: (v: number) => string; height?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = { l: 52, r: 8, t: 10, b: 22 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = Math.max(10, height - m.t - m.b);
  const vals = rows.flatMap((r) => [r.effect, r.lo, r.hi]).filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  const lo0 = Math.min(0, ...vals);
  const hi0 = Math.max(0, ...vals);
  const pad = (hi0 - lo0) * 0.05 || 1e-6;
  const y0 = lo0 - pad;
  const y1 = hi0 + pad;
  const sy = (v: number) => m.t + ih - ((v - y0) / (y1 - y0 || 1)) * ih;
  const bw = rows.length ? iw / rows.length : iw;
  const every = Math.max(1, Math.ceil(rows.length / Math.max(1, Math.floor(iw / 26))));
  const yt = niceTicks(y0, y1, Math.max(3, Math.floor(ih / 40)));
  return (
    <div ref={ref} className="relative w-full">
      <svg width={width} height={height} role="img" aria-label={label} className="block">
        {yt.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke={GRID} />
            <text x={m.l - 6} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">
              {fmt(t)}
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          const cx = m.l + i * bw + bw / 2;
          const vw = Math.min(Math.max(2, bw * 0.6), 26);
          const e = r.effect;
          return (
            <g key={r.key} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={m.l + i * bw} y={m.t} width={bw} height={ih} fill="transparent" />
              {e !== null && Number.isFinite(e) && (
                <rect
                  x={cx - vw / 2}
                  y={Math.min(sy(e), sy(0))}
                  width={vw}
                  height={Math.max(1, Math.abs(sy(e) - sy(0)))}
                  fill={r.color}
                  opacity={hover === null || hover === i ? 0.9 : 0.5}
                  rx={1}
                />
              )}
              {r.lo !== null && r.hi !== null && Number.isFinite(r.lo) && Number.isFinite(r.hi) && (
                <g stroke="#e4e3dc" strokeWidth={1.2} opacity={0.85}>
                  <line x1={cx} x2={cx} y1={sy(r.lo)} y2={sy(r.hi)} />
                  <line x1={cx - Math.min(4, vw / 2)} x2={cx + Math.min(4, vw / 2)} y1={sy(r.lo)} y2={sy(r.lo)} />
                  <line x1={cx - Math.min(4, vw / 2)} x2={cx + Math.min(4, vw / 2)} y1={sy(r.hi)} y2={sy(r.hi)} />
                </g>
              )}
              <title>{r.tip}</title>
              {i % every === 0 && (
                <text x={cx} y={height - 6} textAnchor="middle" fontSize={10} fill={MUTED} className="tnum">
                  {r.label}
                </text>
              )}
            </g>
          );
        })}
        <line x1={m.l} x2={m.l + iw} y1={sy(0)} y2={sy(0)} stroke="#6a6964" />
      </svg>
      {hover !== null && rows[hover] && (
        <div className="pointer-events-none absolute right-1 top-0 max-w-[90%] rounded-md border border-line2 bg-[#0f0f0e]/95 px-2 py-1 text-[11px] tnum">
          {rows[hover].tip}
        </div>
      )}
    </div>
  );
}

/* ================================================================ 1. header / claims policy */

export function QuantHeader({ protocol, tests }: { protocol: Poll<QuantProtocol>; tests: Poll<TestsResp> }) {
  const p = protocol.data;
  const amendments = p
    ? Object.entries(p)
        .filter(([k]) => k.startsWith("amendment_"))
        .map(([k, v]) => [k, v as QuantAmendment] as const)
    : [];
  const counts = tests.data?.counts;
  const byFamily = useMemo(() => {
    const out: Record<string, { total: number; parts: string[] }> = {};
    for (const r of counts?.by_family_period ?? []) {
      const e = (out[r.family] ??= { total: 0, parts: [] });
      e.total += r.n;
      e.parts.push(`${r.period.toLowerCase()} ${r.n}`);
    }
    return out;
  }, [counts]);
  return (
    <Panel
      id="claims"
      title="Claims policy & testing registry"
      subtitle={p ? `${p.name} · frozen ${fmtTime(p.written_utc)} · ${p.status}` : "pre-registered quantitative discovery protocol"}
    >
      <div className="space-y-3">
        <Note tone="weak">
          <p className="font-semibold">No finding on this page is a verified trading signal.</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            <li>
              <b>Exploratory</b>: every pattern scan, including results that survived Benjamini–Hochberg on the discovery period (
              {p ? `${p.periods.DISCOVERY[0]} … ${p.periods.DISCOVERY[1]}` : "2017-08-17 … 2022-12-31"}).
            </li>
            <li>
              <b>&ldquo;Survived confirmation&rdquo;</b> (registry status <code>supported</code>): additionally passed one-sided Holm on the chronologically later
              confirmation period ({p ? `${p.periods.CONFIRMATION[0]} … ${p.periods.CONFIRMATION[1]}` : "2023-01-01 … 2026-10-31"}). That period was{" "}
              <b>previously exposed</b> to the operator in other project contexts, so it is <b>not independent</b> — these results remain exploratory.
            </li>
            <li>
              <b>Only prospective observations</b> ({p ? p.periods.PROSPECTIVE : "from 2026-11-01"}) can give independent, final predictive evidence.
            </li>
          </ul>
          {p && <p className="mt-1 text-[11px] opacity-90">{p.periods.exposure_note}</p>}
        </Note>
        {protocol.error && <ErrorNote error={protocol.error} what="protocol" />}
        {p && <p className="text-xs text-ink2">{p.principle}</p>}

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Kpi label="Tests in registry" value={counts ? counts.total_tests : "—"} sub="all families, all periods" />
          <Kpi label="Families" value={Object.keys(byFamily).length || "—"} />
          <Kpi label="Amendments" value={amendments.length} sub="written after freeze, disclosed" tone={amendments.length ? "warn" : undefined} />
          <Kpi label="LLM calls budget" value={p?.budget?.llm_calls ?? "—"} sub="all numbers are computed" />
        </div>
        {tests.error && <ErrorNote error={tests.error} what="test registry" />}
        {counts && (
          <TableWrap label="Tests per family">
            <table className="data">
              <thead>
                <tr>
                  <th>Family</th>
                  <th>What</th>
                  <th className="text-right">Registered tests</th>
                  <th className="text-right">Protocol plan</th>
                  <th>By period</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(byFamily).map(([f, v]) => (
                  <tr key={f}>
                    <td className="font-mono">{f}</td>
                    <td className="!whitespace-normal text-ink2">{p?.families[f]?.what ?? "—"}</td>
                    <td className="text-right tnum">{v.total}</td>
                    <td className="text-right tnum">{fmtAny(p?.families[f]?.tests ?? null)}</td>
                    <td className="text-ink2">{v.parts.join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}

        {amendments.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Protocol amendments</h3>
            {amendments.map(([k, a]) => (
              <details key={k} className="rounded-md border border-line bg-panel2 px-3 py-2 text-xs" open={k === "amendment_2"}>
                <summary className="cursor-pointer font-medium text-ink">
                  {k.replace("_", " ")} · {fmtTime(a.written_utc)}
                  {k === "amendment_2" && <span className="ml-2 text-warn">why calendar p-values changed</span>}
                </summary>
                <dl className="mt-2 space-y-1.5 text-ink2">
                  {a.after && <Def k="After">{a.after}</Def>}
                  {a.trigger && <Def k="Trigger">{a.trigger}</Def>}
                  {a.diagnosis && <Def k="Diagnosis">{a.diagnosis}</Def>}
                  {a.change && <Def k="Change">{a.change}</Def>}
                  {a.changes && (
                    <Def k="Changes">
                      <ul className="list-disc space-y-1 pl-4">
                        {a.changes.map((c, i) => (
                          <li key={i}>{c}</li>
                        ))}
                      </ul>
                    </Def>
                  )}
                  {a.disclosure && <Def k="Disclosure">{a.disclosure}</Def>}
                </dl>
              </details>
            ))}
          </div>
        )}
        {p && (
          <details className="text-xs text-ink2">
            <summary className="cursor-pointer text-muted">Data unavailable in this environment</summary>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {Object.entries(p.data.unavailable).map(([k, v]) => (
                <li key={k}>
                  <b>{k}</b>: {v}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Panel>
  );
}

function Def({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div>
      <dt className="font-semibold text-muted">{k}</dt>
      <dd className="[overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

/* ================================================================ 2. calendar scanner */

export function CalendarPanel({ poll }: { poll: Poll<CalendarResp> }) {
  const [family, setFamily] = useState<string>("F-DOM");
  const [metric, setMetric] = useState<string>("");
  return (
    <Panel
      id="calendar"
      title="Calendar Pattern Scanner"
      subtitle="Effect = in-bucket minus out-of-bucket value on DISCOVERY, rotation-null 95% CI. p = normal approximation to the rotation null (amendment 2); BH within family."
    >
      <QState poll={poll} what="calendar scan">
        {(d) => {
          const fam = d.families[family];
          const metrics = fam ? Array.from(new Set(fam.results.map((r) => r.metric))) : [];
          const met = metrics.includes(metric) ? metric : metrics[0] ?? "";
          const rows = fam ? fam.results.filter((r) => r.metric === met).sort((a, b) => a.label - b.label) : [];
          return (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-1.5 text-xs text-muted">
                  Family
                  <select
                    data-testid="family-select"
                    className="input !w-auto !py-1 !text-xs"
                    value={family}
                    onChange={(e) => setFamily(e.target.value)}
                  >
                    {CAL_FAMILIES.filter((f) => d.families[f]).map((f) => (
                      <option key={f} value={f}>
                        {f} ({d.families[f].tests} tests)
                      </option>
                    ))}
                  </select>
                </label>
                <Seg label="Metric" value={met} onChange={setMetric} options={metrics.map((m) => ({ v: m, label: m }))} />
              </div>
              {fam && (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Kpi label="Tests in family" value={fam.tests} sub="BH q = 0.10 across all of them" />
                  <Kpi label="Days" value={`${fam.n_days.DISCOVERY} / ${fam.n_days.CONFIRMATION}`} sub="discovery / confirmation" />
                  <Kpi label="BH survivors (discovery)" value={fam.discovery_survivors_bh.length} sub={fam.discovery_survivors_bh.join(", ") || "none"} />
                  <Kpi
                    label="Survived confirmation"
                    value={fam.supported.length}
                    sub={fam.supported.length ? `${fam.supported.join(", ")} · still exploratory` : "none"}
                    tone={fam.supported.length ? "warn" : undefined}
                  />
                </div>
              )}
              <EffectChart
                label={`${family} ${met} effect by bucket with 95% CI`}
                fmt={(v) => `${(v * 100).toFixed(RATE_METRICS.has(met) ? 0 : 1)}${RATE_METRICS.has(met) ? "pp" : "%"}`}
                rows={rows.map((r) => ({
                  key: String(r.label),
                  label: calLabel(family, r.label),
                  effect: r.effect,
                  lo: r.ci_lo,
                  hi: r.ci_hi,
                  color: STATUS_COLOR[statusKey(r.status)],
                  tip: `${calLabel(family, r.label)} · ${met}: ${fEff(met, r.effect)} [${fEff(met, r.ci_lo)}, ${fEff(met, r.ci_hi)}] · p ${fp(r.p)} · p_BH ${fp(r.p_bh)} · ${STATUS_TEXT[statusKey(r.status)]}`,
                }))}
              />
              <StatusLegend keys={["supported", "inconclusive", "rejected"]} />
              <CalTable family={family} rows={rows} />
              <p className="text-[11px] text-muted">
                Macro-excluded effect = discovery effect recomputed without FOMC and election days. Confirmation p is two-sided; Holm uses the one-sided p in the
                discovery direction, only for BH survivors. run <Hash v={d.run_id} n={22} /> · data_sha <Hash v={d.data_sha} />
              </p>
              <Day14Card d={d} />
            </div>
          );
        }}
      </QState>
    </Panel>
  );
}

function CalTable({ family, rows }: { family: string; rows: CalResult[] }) {
  return (
    <TableWrap label={`${family} results`}>
      <table className="data">
        <thead>
          <tr>
            <th>Bucket</th>
            <th className="text-right">n</th>
            <th className="text-right">Effect</th>
            <th className="text-right">95% CI</th>
            <th className="text-right">z</th>
            <th className="text-right">p</th>
            <th className="text-right">p rot. emp.</th>
            <th className="text-right">p BH</th>
            <th>Status</th>
            <th className="text-right">Conf. effect</th>
            <th className="text-right">Conf. p</th>
            <th className="text-right">Holm p</th>
            <th className="text-right">Excl. macro</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.hypothesis}>
              <td className="font-mono">{calLabel(family, r.label)}</td>
              <td className="text-right tnum">
                {r.n}
                <span className="text-muted">/{r.n_ref}</span>
              </td>
              <td className="text-right tnum">{fEff(r.metric, r.effect)}</td>
              <td className="text-right tnum text-ink2">
                [{fEff(r.metric, r.ci_lo)}, {fEff(r.metric, r.ci_hi)}]
              </td>
              <td className="text-right tnum">{fz(r.z)}</td>
              <td className="text-right tnum">{fp(r.p)}</td>
              <td className="text-right tnum text-ink2">{fp(r.p_rotation_empirical)}</td>
              <td className="text-right tnum">{fp(r.p_bh)}</td>
              <td>
                <QStatus s={r.status} />
              </td>
              <td className="text-right tnum">{fEff(r.metric, r.confirmation?.effect)}</td>
              <td className="text-right tnum">{fp(r.confirmation?.p)}</td>
              <td className="text-right tnum">{r.confirm_holm ? `${fp(r.confirm_holm.p_adj)}${r.confirm_holm.reject ? " ✓" : ""}` : "—"}</td>
              <td className="text-right tnum">{fEff(r.metric, r.excl_macro_effect)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

function Day14Card({ d }: { d: CalendarResp }) {
  const dom = d.families["F-DOM"];
  const byHyp = new Map((dom?.results ?? []).map((r) => [r.hypothesis, r]));
  // day14 rows carry their F-DOM status; fall back to the family row if a field is missing
  const tests = d.day14.tests.map((t) => {
    const f = byHyp.get(t.hypothesis);
    return { ...t, status: t.status ?? f?.status, p_bh: t.p_bh ?? f?.p_bh ?? null, confirmation: t.confirmation ?? f?.confirmation };
  });
  const years = Object.entries(d.day14.by_year).sort(([a], [b]) => a.localeCompare(b));
  const anySurvivor = tests.some((t) => statusKey(t.status) !== "rejected");
  return (
    <section aria-labelledby="day14-h" className="rounded-lg border border-line2 bg-panel2 p-3">
      <h3 id="day14-h" className="text-sm font-semibold">
        Is the 14th unusual?
      </h3>
      <p className="mt-0.5 text-xs text-muted">{d.day14.reference}</p>
      <Note tone={anySurvivor ? "weak" : "neutral"}>
        <b>Multiple testing:</b> {d.day14.multiple_testing}. A named hypothesis (H-DOM-14) does not get its own α: it is judged inside the family, after BH.{" "}
        {anySurvivor ? "At least one metric survived discovery BH — see status." : "None of its 4 metrics survives BH on discovery."}
      </Note>
      <div className="mt-2">
        <TableWrap label="Day 14 tests">
          <table className="data">
            <thead>
              <tr>
                <th>Metric</th>
                <th className="text-right">n</th>
                <th className="text-right">Effect</th>
                <th className="text-right">95% CI</th>
                <th className="text-right">z</th>
                <th className="text-right">p</th>
                <th className="text-right">p BH (124)</th>
                <th>Status</th>
                <th className="text-right">Conf. effect</th>
                <th className="text-right">Conf. p</th>
              </tr>
            </thead>
            <tbody>
              {tests.map((t) => (
                <tr key={t.hypothesis}>
                  <td className="font-mono">{t.metric}</td>
                  <td className="text-right tnum">{t.n}</td>
                  <td className="text-right tnum">{fEff(t.metric, t.effect)}</td>
                  <td className="text-right tnum text-ink2">
                    [{fEff(t.metric, t.ci_lo)}, {fEff(t.metric, t.ci_hi)}]
                  </td>
                  <td className="text-right tnum">{fz(t.z)}</td>
                  <td className="text-right tnum">{fp(t.p)}</td>
                  <td className="text-right tnum">{fp(t.p_bh)}</td>
                  <td>
                    <QStatus s={t.status} />
                  </td>
                  <td className="text-right tnum">{fEff(t.metric, t.confirmation?.effect)}</td>
                  <td className="text-right tnum">{fp(t.confirmation?.p)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </div>
      <h4 className="mt-3 text-xs font-semibold uppercase tracking-wider text-muted">By year (descriptive)</h4>
      <TableWrap label="Day 14 by year">
        <table className="data">
          <thead>
            <tr>
              <th>Year</th>
              <th className="text-right">n (14ths)</th>
              <th className="text-right">Mean ret 14th</th>
              <th className="text-right">Mean ret other</th>
              <th className="text-right">Mean |ret| 14th</th>
              <th className="text-right">Mean |ret| other</th>
            </tr>
          </thead>
          <tbody>
            {years.map(([y, v]) => (
              <tr key={y}>
                <td className="tnum">{y}</td>
                <td className="text-right tnum">{v.n}</td>
                <td className="text-right tnum">{fpct(v.mean_ret_14)}</td>
                <td className="text-right tnum text-ink2">{fpct(v.mean_ret_other)}</td>
                <td className="text-right tnum">{fpctU(v.mean_absret_14)}</td>
                <td className="text-right tnum text-ink2">{fpctU(v.mean_absret_other)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <p className="mt-1 text-[11px] text-muted">Yearly rows hold 4–12 observations each; they are descriptive and carry no inference.</p>
    </section>
  );
}

/* ================================================================ 3. cycles */

function AcfBars({ values, band, label, color }: { values: number[]; band: number; label: string; color: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const height = 150;
  const m = { l: 40, r: 6, t: 8, b: 20 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = height - m.t - m.b;
  const hi = Math.max(band * 1.3, ...values.map((v) => Math.abs(v)));
  const sy = (v: number) => m.t + ih / 2 - (v / hi) * (ih / 2);
  const bw = iw / Math.max(1, values.length);
  const yt = niceTicks(-hi, hi, 4);
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={height} role="img" aria-label={label} className="block">
        {yt.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke={GRID} />
            <text x={m.l - 4} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">
              {t.toFixed(2)}
            </text>
          </g>
        ))}
        <rect x={m.l} y={sy(band)} width={iw} height={sy(-band) - sy(band)} fill="#9085e9" opacity={0.12} />
        <line x1={m.l} x2={m.l + iw} y1={sy(band)} y2={sy(band)} stroke="#9085e9" strokeDasharray="4 3" />
        <line x1={m.l} x2={m.l + iw} y1={sy(-band)} y2={sy(-band)} stroke="#9085e9" strokeDasharray="4 3" />
        <line x1={m.l} x2={m.l + iw} y1={sy(0)} y2={sy(0)} stroke={AXIS} />
        {values.map((v, i) => {
          const w = Math.min(18, bw * 0.6);
          const cx = m.l + i * bw + bw / 2;
          return (
            <g key={i}>
              <rect x={cx - w / 2} y={Math.min(sy(v), sy(0))} width={w} height={Math.max(1, Math.abs(sy(v) - sy(0)))} fill={color} opacity={Math.abs(v) > band ? 1 : 0.55}>
                <title>{`lag ${i + 1}: ${v.toFixed(3)}${Math.abs(v) > band ? " (outside band)" : ""}`}</title>
              </rect>
              <text x={cx} y={height - 6} textAnchor="middle" fontSize={10} fill={MUTED} className="tnum">
                {i + 1}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function CyclesPanel({ poll }: { poll: Poll<CyclesResp> }) {
  return (
    <Panel
      id="cycles"
      title="Cycle Explorer"
      subtitle="Periodogram ordinate at P ranked within the local band [P/2, 2P]; p_rank = share of band ordinates at least as large. Holm over 8 on discovery; stability required in both halves and on confirmation."
    >
      <QState poll={poll} what="cycle scan">
        {(d) => {
          const entries = Object.entries(d.cycles);
          return (
            <div className="space-y-3">
              <TableWrap label="Cycle tests">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Series</th>
                      <th className="text-right">Period</th>
                      <th className="text-right">p disc. H1</th>
                      <th className="text-right">p disc. H2</th>
                      <th className="text-right">p discovery</th>
                      <th className="text-right">Holm p</th>
                      <th className="text-right">p confirmation</th>
                      <th className="text-right">Ratio to band median (disc / conf)</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map(([k, c]) => {
                      const series = k.split(":")[1] ?? k;
                      return (
                        <tr key={k}>
                          <td className="font-mono">{series === "absret" ? "|returns|" : "returns"}</td>
                          <td className="text-right tnum">
                            {c.DISCOVERY.period_days} d<span className="text-muted"> (≈{c.DISCOVERY.nearest_period.toFixed(1)})</span>
                          </td>
                          <PCell p={c.DISC_H1.p_rank} />
                          <PCell p={c.DISC_H2.p_rank} />
                          <PCell p={c.DISCOVERY.p_rank} />
                          <td className="text-right tnum">
                            {fp(c.holm.p_adj)}
                            {c.holm.reject ? " ✓" : ""}
                          </td>
                          <PCell p={c.CONFIRMATION.p_rank} />
                          <td className="text-right tnum">
                            {c.DISCOVERY.ratio_to_band_median.toFixed(2)} / {c.CONFIRMATION.ratio_to_band_median.toFixed(2)}
                          </td>
                          <td>
                            <QStatus s={c.status} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableWrap>
              <p className="text-[11px] text-muted">
                Bands are narrow for long periods (365.25 d: 4–8 ordinates), so p_rank cannot fall below ~0.1–0.2 there: annual cycles are effectively
                untestable on ~5 years. p values ≤ 0.05 are highlighted.
              </p>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="min-w-0">
                  <h3 className="text-xs font-semibold text-ink2">ACF of daily returns (lags 1–{d.diagnostics.acf_ret.length})</h3>
                  <AcfBars values={d.diagnostics.acf_ret} band={d.diagnostics.bartlett_95_band} label="Autocorrelation of daily returns" color="#3987e5" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-xs font-semibold text-ink2">ACF of |daily returns|</h3>
                  <AcfBars values={d.diagnostics.acf_absret} band={d.diagnostics.bartlett_95_band} label="Autocorrelation of absolute daily returns" color="#d95926" />
                </div>
              </div>
              <Legend items={[{ label: `Bartlett 95% band ±${d.diagnostics.bartlett_95_band.toFixed(3)} (n = ${d.diagnostics.n}, ${d.diagnostics.period ?? "DISCOVERY"})`, color: "#9085e9", dashed: true }]} />
              <p className="text-xs text-ink2">{d.diagnostics.note}</p>
            </div>
          );
        }}
      </QState>
    </Panel>
  );
}

function PCell({ p }: { p: number | null | undefined }) {
  const hit = typeof p === "number" && p <= 0.05;
  return <td className={`text-right tnum ${hit ? "font-semibold text-[#9ec5f4]" : ""}`}>{fp(p)}</td>;
}

/* ================================================================ 4. events: FOMC + elections */

const FOMC_METRICS = ["absret_0_4h", "rv_0_4h", "ret_0_1h", "ret_0_4h", "ret_0_24h", "ret_0_7d", "pre_ret_24h", "pre_absret_24h"];

function FomcTimeline({ d, metric }: { d: FomcResp; metric: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const height = 230;
  const m = { l: 52, r: 10, t: 10, b: 22 };
  const iw = Math.max(10, width - m.l - m.r);
  const ih = height - m.t - m.b;
  const pts = d.events
    .map((e) => ({ e, t: Date.parse(e.day + "T00:00:00Z"), v: e[metric] }))
    .filter((p): p is { e: (typeof d.events)[number]; t: number; v: number } => typeof p.v === "number" && Number.isFinite(p.v));
  const [hover, setHover] = useState<number | null>(null);
  if (!pts.length) return <p className="text-xs text-muted">No values for {metric}.</p>;
  const t0 = Math.min(...pts.map((p) => p.t));
  const t1 = Math.max(...pts.map((p) => p.t));
  const vs = pts.map((p) => p.v);
  const placebo = ["DISCOVERY", "CONFIRMATION"].map((k) => d.results[k]?.[metric]?.placebo_mean).filter((v): v is number => typeof v === "number");
  let y0 = Math.min(0, ...vs, ...placebo);
  let y1 = Math.max(0, ...vs, ...placebo);
  const pad = (y1 - y0) * 0.05 || 1e-4;
  y0 -= pad;
  y1 += pad;
  const sx = (t: number) => m.l + ((t - t0) / (t1 - t0 || 1)) * iw;
  const sy = (v: number) => m.t + ih - ((v - y0) / (y1 - y0 || 1)) * ih;
  const split = Date.parse("2023-01-01T00:00:00Z");
  const yt = niceTicks(y0, y1, 4);
  const years: number[] = [];
  for (let y = new Date(t0).getUTCFullYear() + 1; y <= new Date(t1).getUTCFullYear(); y++) years.push(y);
  const step = Math.max(1, Math.ceil(years.length / Math.max(1, Math.floor(iw / 44))));
  const periodLine = (k: string, a: number, b: number) => {
    const v = d.results[k]?.[metric]?.placebo_mean;
    return typeof v === "number" ? <line x1={sx(a)} x2={sx(b)} y1={sy(v)} y2={sy(v)} stroke="#c3c2b7" strokeDasharray="4 3" /> : null;
  };
  const hp = hover !== null ? pts[hover] : null;
  return (
    <div ref={ref} className="relative w-full">
      <svg width={width} height={height} role="img" aria-label={`FOMC ${metric} per event over time, coloured by policy action`} className="block">
        {yt.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} stroke={GRID} />
            <text x={m.l - 6} y={sy(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={MUTED} className="tnum">
              {(t * 100).toFixed(1)}%
            </text>
          </g>
        ))}
        {years.map((y, i) =>
          i % step === 0 ? (
            <text key={y} x={sx(Date.UTC(y, 0, 1))} y={height - 6} textAnchor="middle" fontSize={10} fill={MUTED} className="tnum">
              {y}
            </text>
          ) : null,
        )}
        <line x1={m.l} x2={m.l + iw} y1={sy(0)} y2={sy(0)} stroke={AXIS} />
        {split > t0 && split < t1 && (
          <g>
            <line x1={sx(split)} x2={sx(split)} y1={m.t} y2={m.t + ih} stroke="#fab219" strokeDasharray="2 3" />
            <text x={sx(split) + 3} y={m.t + 10} fontSize={10} fill="#fab219">
              confirmation →
            </text>
          </g>
        )}
        {periodLine("DISCOVERY", t0, Math.min(split, t1))}
        {periodLine("CONFIRMATION", Math.max(split, t0), t1)}
        {pts.map((p, i) => (
          <circle
            key={p.e.event_id}
            cx={sx(p.t)}
            cy={sy(p.v)}
            r={hover === i ? 5.5 : p.e.sep ? 4.5 : 3.5}
            fill={ACTION_COLOR[p.e.action ?? ""] ?? "#6a6964"}
            stroke={p.e.sep ? "#f0efec" : "#161615"}
            strokeWidth={p.e.sep ? 1.2 : 1}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <title>{`${p.e.day} · ${p.e.action ?? "action n/a"}${p.e.sep ? " · SEP" : ""} · ${metric} ${fpct(p.v)}`}</title>
          </circle>
        ))}
      </svg>
      {hp && (
        <div className="pointer-events-none absolute right-1 top-0 rounded-md border border-line2 bg-[#0f0f0e]/95 px-2 py-1 text-[11px] tnum">
          {hp.e.day} · {hp.e.action ?? "n/a"}
          {hp.e.sep ? " · SEP" : ""} · {fpct(hp.v)}
        </div>
      )}
    </div>
  );
}

export function FomcPanel({ poll }: { poll: Poll<FomcResp> }) {
  const [metric, setMetric] = useState("absret_0_4h");
  return (
    <QState poll={poll} what="FOMC event study">
      {(d) => {
        const metrics = FOMC_METRICS.filter((k) => d.status[k] !== undefined || d.results.DISCOVERY?.[k]);
        const counts = d.events.reduce<Record<string, number>>((a, e) => ((a[e.action ?? "n/a"] = (a[e.action ?? "n/a"] ?? 0) + 1), a), {});
        return (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold">FOMC statements · hourly BTC</h3>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Kpi label="Events (discovery)" value={d.periods.DISCOVERY?.n_events ?? "—"} sub={`${d.periods.DISCOVERY?.n_placebo ?? "—"} placebo times`} />
              <Kpi label="Events (confirmation)" value={d.periods.CONFIRMATION?.n_events ?? "—"} sub={`${d.periods.CONFIRMATION?.n_placebo ?? "—"} placebo times`} />
              <Kpi label="Actions" value={Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(" · ")} />
              <Kpi label="Primary metrics" value="absret_0_4h, rv_0_4h" sub="pre-registered" />
            </div>
            <Seg label="FOMC metric" value={metric} onChange={setMetric} options={metrics.map((k) => ({ v: k, label: k }))} />
            <FomcTimeline d={d} metric={metric} />
            <Legend
              items={[
                ...Object.entries(ACTION_COLOR).map(([k, c]) => ({ label: k, color: c, shape: "dot" as const })),
                { label: "white ring = SEP meeting", color: "#f0efec", shape: "dot" as const },
                { label: "placebo mean (per period)", color: "#c3c2b7", dashed: true },
              ]}
            />
            <TableWrap label="FOMC discovery vs confirmation">
              <table className="data">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Period</th>
                    <th className="text-right">n</th>
                    <th className="text-right">Event mean</th>
                    <th className="text-right">Event-mean 95% CI</th>
                    <th className="text-right">Placebo mean</th>
                    <th className="text-right">Effect (vs placebo median)</th>
                    <th className="text-right">Percentile</th>
                    <th className="text-right">p</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.map((k) =>
                    ["DISCOVERY", "CONFIRMATION"].map((per, j) => {
                      const r = d.results[per]?.[k];
                      return (
                        <tr key={k + per} className={k === metric ? "bg-accent/5" : undefined}>
                          {j === 0 && (
                            <td rowSpan={2} className="align-top font-mono">
                              {k}
                            </td>
                          )}
                          <td className="text-ink2">{per.toLowerCase()}</td>
                          <td className="text-right tnum">{r?.n ?? "—"}</td>
                          <td className="text-right tnum">{fpct(r?.event_mean)}</td>
                          <td className="text-right tnum text-ink2">{r?.event_mean_ci ? `[${fpct(r.event_mean_ci[0])}, ${fpct(r.event_mean_ci[1])}]` : "—"}</td>
                          <td className="text-right tnum text-ink2">{fpct(r?.placebo_mean)}</td>
                          <td className="text-right tnum">{fpct(r?.effect)}</td>
                          <td className="text-right tnum">{typeof r?.percentile === "number" ? `${(r.percentile * 100).toFixed(1)}` : "—"}</td>
                          <td className="text-right tnum">{fp(r?.p)}</td>
                          {j === 0 && (
                            <td rowSpan={2} className="align-top">
                              <QStatus s={d.status[k]} />
                            </td>
                          )}
                        </tr>
                      );
                    }),
                  )}
                </tbody>
              </table>
            </TableWrap>
            <p className="text-[11px] text-muted">
              The CI is a bootstrap interval for the <b>event mean</b>, not for the effect. Effects are event mean minus the median of placebo means (same weekday
              and clock time, non-event days). Status = BH within F-FOMC on discovery, then one-sided Holm over survivors on confirmation.
            </p>
            <XEventTable d={d} />
          </div>
        );
      }}
    </QState>
  );
}

function XEventTable({ d }: { d: FomcResp }) {
  const per = (["DISCOVERY", "CONFIRMATION"] as const).filter((k) => d.xevent[k]);
  const split: Record<string, string> = {
    high_vol: "pre-event 30-day vol high vs low",
    changed: "target changed (hike/cut) vs hold",
  };
  return (
    <div className="space-y-1.5">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-muted">Interactions (F-XEVENT, metric absret_0_4h)</h4>
      <TableWrap label="FOMC interactions">
        <table className="data">
          <thead>
            <tr>
              <th>Split</th>
              <th>Period</th>
              <th className="text-right">n true / false</th>
              <th className="text-right">Diff (true − false)</th>
              <th className="text-right">p</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {per.flatMap((p) =>
              Object.entries(d.xevent[p] ?? {}).map(([k, c]) => {
                const notTested = c.status.startsWith("not tested");
                return (
                  <tr key={p + k} className={notTested ? "opacity-80" : undefined}>
                    <td>{split[k] ?? k}</td>
                    <td className="text-ink2">{p.toLowerCase()}</td>
                    <td className="text-right tnum">
                      {c.n_true} / {c.n_false}
                    </td>
                    <td className="text-right tnum">{fpct(c.diff)}</td>
                    <td className={`text-right tnum ${notTested ? "text-muted line-through" : ""}`} title={notTested ? "computed but not a test: a cell has n < 15" : undefined}>
                      {fp(c.p)}
                    </td>
                    <td>
                      <span className={`inline-block whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold ${TONE_CLS[notTested ? "weak" : "neutral"]}`}>
                        {c.status}
                      </span>
                    </td>
                  </tr>
                );
              }),
            )}
          </tbody>
        </table>
      </TableWrap>
      <p className="text-[11px] text-muted">
        Interaction tests require ≥ 15 events per cell; below that the p value is struck through and not interpreted. Discovery interactions are registered as
        exploratory (no multiple-testing correction applied).
      </p>
      {d.xevent.note && (
        <Note tone="weak">
          <b>Missing data:</b> {d.xevent.note}
        </Note>
      )}
    </div>
  );
}

const WINDOWS = ["pre_30", "post_1", "post_7", "post_30", "post_90"];

export function ElectionsPanel({ poll }: { poll: Poll<ElectionsResp> }) {
  const [asset, setAsset] = useState("");
  const [kind, setKind] = useState<"midterm" | "presidential">("midterm");
  return (
    <QState poll={poll} what="election study">
      {(d) => {
        const names = Object.keys(d.assets);
        const a = names.includes(asset) ? asset : names[0] ?? "";
        const g = d.assets[a]?.[kind];
        return (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold">U.S. elections · per asset (conclusions are not transferred between assets)</h3>
            <Note tone="bad">
              <b>Sample-size warning:</b> inference requires n ≥ 20 events; every election cell here is <b>descriptive only</b>. BTC has only 2–3 events per type
              (2018/2022/2026 midterms, 2020/2024 presidential), the S&amp;P 500 series ~3; even DGS10 since 1962 has 16–17. Placebo percentiles describe where
              each event sits among non-election Tuesdays (Oct–Dec, odd years) — they are not tests.
            </Note>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-1.5 text-xs text-muted">
                Asset
                <select className="input !w-auto !max-w-[16rem] !py-1 !text-xs" value={a} onChange={(e) => setAsset(e.target.value)}>
                  {names.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <Seg
                label="Election type"
                value={kind}
                onChange={setKind}
                options={[
                  { v: "midterm", label: "midterm" },
                  { v: "presidential", label: "presidential" },
                ]}
              />
            </div>
            {g ? <ElectionGroup g={g} asset={a} pending={d.pending} /> : <p className="text-xs text-muted">No data.</p>}
            <Note tone="info">
              <b>Prospective:</b> {d.pending_note}. Pending: {d.pending.join(", ") || "none"}.
            </Note>
          </div>
        );
      }}
    </QState>
  );
}

function ElectionGroup({ g, asset, pending }: { g: ElectGroup; asset: string; pending: string[] }) {
  const isLevel = asset.startsWith("DGS10");
  const f = (v: Num | undefined) => (isLevel ? (typeof v === "number" && Number.isFinite(v) ? `${v > 0 ? "+" : ""}${v.toFixed(2)} pp` : "—") : fpct(v));
  // percentiles align with the events that have a finite value in that window (same order)
  const pctFor = (w: string) => {
    const out = new Map<string, number>();
    const win = g.windows[w];
    if (!win) return out;
    let j = 0;
    for (const e of g.events) {
      const v = e[w as keyof typeof e];
      if (typeof v === "number" && Number.isFinite(v)) {
        if (j < win.event_percentiles_in_placebo.length) out.set(e.event_id, win.event_percentiles_in_placebo[j]);
        j++;
      }
    }
    return out;
  };
  const pcts = Object.fromEntries(WINDOWS.map((w) => [w, pctFor(w)]));
  return (
    <div className="space-y-2">
      <p className="text-xs text-ink2">
        {g.n_events} events · inference: <b>{g.inference}</b>
      </p>
      <TableWrap label="Election event values">
        <table className="data">
          <thead>
            <tr>
              <th>Event</th>
              {WINDOWS.map((w) => (
                <th key={w} className="text-right">
                  {w}
                  <span className="block text-[10px] font-normal normal-case text-muted">value · placebo pct</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {g.events.map((e) => (
              <tr key={e.event_id}>
                <td className="whitespace-nowrap">
                  {e.date}
                  {pending.includes(e.event_id) && <span className="ml-1 rounded border border-accent/60 px-1 text-[10px] text-[#9ec5f4]">prospective</span>}
                  {!e.complete && !pending.includes(e.event_id) && <span className="ml-1 text-[10px] text-muted">incomplete</span>}
                </td>
                {WINDOWS.map((w) => {
                  const v = e[w as keyof typeof e] as Num;
                  const p = pcts[w].get(e.event_id);
                  return (
                    <td key={w} className="text-right tnum">
                      {f(v)}
                      {p !== undefined && <span className="ml-1 text-[11px] text-muted">· {(p * 100).toFixed(0)}</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr className="border-t border-line2">
              <td className="text-muted">mean (n) / placebo mean</td>
              {WINDOWS.map((w) => {
                const win = g.windows[w];
                return (
                  <td key={w} className="text-right tnum text-ink2">
                    {win ? (
                      <>
                        {f(win.mean)} <span className="text-muted">({win.n})</span>
                        <span className="block text-[11px] text-muted">
                          {f(win.placebo_mean)} (n={win.placebo_n})
                        </span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </TableWrap>
      <PercentileStrips g={g} pcts={pcts} />
    </div>
  );
}

function PercentileStrips({ g, pcts }: { g: ElectGroup; pcts: Record<string, Map<string, number>> }) {
  const years = g.events.map((e) => e.event_id);
  const colors = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9", "#e66767", "#2f9e2f"];
  const colorOf = (id: string) => colors[years.indexOf(id) % colors.length];
  const recent = years.length > 8;
  return (
    <div className="space-y-1">
      <p className="text-[11px] text-muted">Placebo percentile per event and window (0 = lowest of the placebo pool, 100 = highest; 25–75 shaded).</p>
      <ul className="space-y-1.5">
        {WINDOWS.map((w) => (
          <li key={w} className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-2 text-[11px]">
            <span className="font-mono text-ink2">{w}</span>
            <span className="relative h-4 rounded-sm bg-[#1f1f1d]" role="img" aria-label={`placebo percentiles for ${w}`}>
              <span className="absolute inset-y-0 bg-line2/40" style={{ left: "25%", width: "50%" }} />
              <span className="absolute inset-y-0 w-px bg-line2" style={{ left: "50%" }} />
              {Array.from(pcts[w].entries()).map(([id, p]) => (
                <span
                  key={id}
                  title={`${id}: ${(p * 100).toFixed(0)}th percentile`}
                  className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-[#161615]"
                  style={{ left: `${p * 100}%`, background: recent ? "#3987e5" : colorOf(id), opacity: recent ? 0.6 : 1 }}
                />
              ))}
            </span>
          </li>
        ))}
      </ul>
      {!recent && <Legend items={years.map((id) => ({ label: id.replace("us_election_", ""), color: colorOf(id), shape: "dot" as const }))} />}
    </div>
  );
}

/* ================================================================ 5. correlation & dependency */

export function DependencyPanel({ cycles, fomc, fcast }: { cycles: Poll<CyclesResp>; fomc: Poll<FomcResp>; fcast: Poll<ForecastLinkResp> }) {
  const diag = cycles.data?.diagnostics;
  const fomcD = fomc.data;
  const nFcast = fcast.data ? Object.keys(fcast.data.results).length : null;
  return (
    <Panel
      id="dependency"
      title="Correlation & Dependency Explorer"
      subtitle="What exists today: serial dependence of daily BTC returns, and FOMC × regime interactions. No cross-asset lead-lag study has been run."
    >
      <div className="space-y-3">
        <Note tone="weak">
          <b>Correlation is not predictive skill.</b> An autocorrelation or a conditional difference in means describes the sample; only an out-of-sample forecast
          comparison (F-FCAST, below in the Forward Prediction Monitor) measures whether a variable improves predictions — and only prospective data can confirm it.
        </Note>
        {cycles.error && !diag && <ErrorNote error={cycles.error} what="diagnostics" />}
        {diag && (
          <TableWrap label="Autocorrelation diagnostics">
            <table className="data">
              <thead>
                <tr>
                  <th>Lag (days)</th>
                  {diag.acf_ret.map((_, i) => (
                    <th key={i} className="text-right">
                      {i + 1}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["ACF returns", diag.acf_ret],
                    ["ACF |returns|", diag.acf_absret],
                  ] as const
                ).map(([lab, vals]) => (
                  <tr key={lab}>
                    <td className="whitespace-nowrap">{lab}</td>
                    {vals.map((v, i) => (
                      <td key={i} className={`text-right tnum ${Math.abs(v) > diag.bartlett_95_band ? "font-semibold text-[#9ec5f4]" : "text-ink2"}`}>
                        {v.toFixed(3)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
        {diag && (
          <p className="text-xs text-ink2">
            Highlighted = outside the Bartlett ±{diag.bartlett_95_band.toFixed(3)} band (n = {diag.n}). {diag.note}. Bars are shown in the Cycle Explorer.
          </p>
        )}
        {fomcD && (
          <div className="grid gap-2 sm:grid-cols-2">
            {(["DISCOVERY", "CONFIRMATION"] as const).map((p) => {
              const x = fomcD.xevent[p];
              if (!x) return null;
              return (
                <div key={p} className="rounded-md border border-line bg-panel2 p-2 text-xs">
                  <p className="font-semibold text-ink2">FOMC × regime · {p.toLowerCase()}</p>
                  <ul className="mt-1 space-y-0.5">
                    {Object.entries(x).map(([k, c]) => (
                      <li key={k} className="flex flex-wrap justify-between gap-2">
                        <span className="text-muted">{k}</span>
                        <span className="tnum">
                          diff {fpct(c.diff)} · n {c.n_true}/{c.n_false} ·{" "}
                          <span className={c.status.startsWith("not tested") ? "text-warn" : "text-ink2"}>{c.status}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        )}
        <p className="text-xs text-muted">
          Predictive evaluation: {nFcast === null ? "F-FCAST results not produced yet" : `${nFcast} F-FCAST feature × target comparisons`} — see{" "}
          <a href="#forward" className="text-[#9ec5f4] underline">
            Forward Prediction Monitor
          </a>
          .
        </p>
      </div>
    </Panel>
  );
}

/* ================================================================ 6. rankings */

export function RankingsPanel({ poll, onSelect, selected }: { poll: Poll<RankingsResp>; onSelect: (h: string) => void; selected: string }) {
  const [fam, setFam] = useState("all");
  const [st, setSt] = useState("noteworthy");
  const [limit, setLimit] = useState(25);
  return (
    <Panel id="rankings" title="Discovery Rankings" subtitle="Hypotheses ranked by evidence: survived confirmation › inconclusive › exploratory › descriptive › not promoted › rejected; then smallest p.">
      <QState poll={poll} what="rankings">
        {(d) => {
          const fams = Array.from(new Set(d.ranking.map((r) => r.family))).sort();
          const rows = d.ranking.filter(
            (r) => (fam === "all" || r.family === fam) && (st === "all" || (st === "noteworthy" ? !["rejected", "descriptive"].includes(statusKey(r.status)) : statusKey(r.status) === st)),
          );
          const counts = d.ranking.reduce<Record<string, number>>((a, r) => ((a[statusKey(r.status)] = (a[statusKey(r.status)] ?? 0) + 1), a), {});
          return (
            <div className="space-y-3">
              <Note tone="info">{d.legend}</Note>
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <label className="flex items-center gap-1.5 text-muted">
                  Family
                  <select className="input !w-auto !py-1 !text-xs" value={fam} onChange={(e) => setFam(e.target.value)}>
                    <option value="all">all ({d.ranking.length})</option>
                    {fams.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex min-w-0 items-center gap-1.5 text-muted">
                  Status
                  <select className="input !w-auto !max-w-[13rem] !py-1 !text-xs" value={st} onChange={(e) => setSt(e.target.value)}>
                    <option value="noteworthy">not rejected / not descriptive</option>
                    <option value="all">all</option>
                    {(Object.keys(STATUS_TEXT) as StatusKey[])
                      .filter((k) => counts[k])
                      .map((k) => (
                        <option key={k} value={k}>
                          {STATUS_TEXT[k]} ({counts[k]})
                        </option>
                      ))}
                  </select>
                </label>
              </div>
              <TableWrap label="Ranked hypotheses">
                <table className="data">
                  <thead>
                    <tr>
                      <th className="text-right">#</th>
                      <th>Hypothesis</th>
                      <th>Family</th>
                      <th>Role</th>
                      <th>Status</th>
                      <th>Period</th>
                      <th className="text-right">n</th>
                      <th className="text-right">Effect</th>
                      <th className="text-right">CI</th>
                      <th className="text-right">p</th>
                      <th className="text-right">p adj</th>
                      <th>Lineage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(0, limit).map((r) => (
                      <RankRows key={r.hypothesis} r={r} rank={d.ranking.indexOf(r) + 1} onSelect={onSelect} selected={selected === r.hypothesis} />
                    ))}
                  </tbody>
                </table>
              </TableWrap>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                showing {Math.min(limit, rows.length)} of {rows.length}
                {rows.length > limit && (
                  <button type="button" className="btn btn-sm" onClick={() => setLimit((l) => l + 50)}>
                    Show more
                  </button>
                )}
              </div>
              <p className="text-[11px] text-muted">
                Effects are in the family&apos;s native units (log-return fractions, rate differences, loss differences, periodogram ratio). For F-FOMC the CI is the
                bootstrap CI of the event mean, not of the effect.
              </p>
            </div>
          );
        }}
      </QState>
    </Panel>
  );
}

function RankRows({ r, rank, onSelect, selected }: { r: RankRow; rank: number; onSelect: (h: string) => void; selected: boolean }) {
  const tests = [...r.tests].sort((a, b) => (a.period === "DISCOVERY" ? -1 : b.period === "DISCOVERY" ? 1 : a.period.localeCompare(b.period)));
  return (
    <>
      {tests.map((t, i) => (
        <tr key={t.id} className={selected ? "bg-accent/10" : undefined}>
          {i === 0 && (
            <>
              <td rowSpan={tests.length} className="text-right align-top tnum text-muted">
                {rank}
              </td>
              <td rowSpan={tests.length} className="align-top font-mono text-[11px]">
                {r.hypothesis}
              </td>
              <td rowSpan={tests.length} className="align-top">
                {r.family}
              </td>
              <td rowSpan={tests.length} className="align-top" title={DIVISION[r.role[0]]}>
                {r.role}
              </td>
              <td rowSpan={tests.length} className="align-top">
                <QStatus s={r.status} />
              </td>
            </>
          )}
          <td className="text-ink2">{t.period.toLowerCase()}</td>
          <td className="text-right tnum">{fmtAny(t.n)}</td>
          <td className="text-right tnum">{num(t.effect)}</td>
          <td className="text-right tnum text-ink2">{t.ci_lo !== null || t.ci_hi !== null ? `[${num(t.ci_lo)}, ${num(t.ci_hi)}]` : "—"}</td>
          <td className="text-right tnum">{fp(t.p)}</td>
          <td className="text-right tnum" title={t.adj_method ?? undefined}>
            {fp(t.p_adj)}
          </td>
          {i === 0 && (
            <td rowSpan={tests.length} className="align-top">
              <button
                type="button"
                className="text-[11px] text-[#9ec5f4] underline"
                onClick={() => {
                  onSelect(r.hypothesis);
                  document.getElementById("lineage")?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
              >
                trace
              </button>
            </td>
          )}
        </tr>
      ))}
    </>
  );
}

function num(v: Num | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a < 1e-3) return v.toExponential(2);
  if (a < 1) return v.toFixed(4);
  return v.toFixed(2);
}

/* ================================================================ 7. lineage */

export function LineagePanel({ poll, tests, hypothesis, setHypothesis }: { poll: Poll<WorkflowResp>; tests: Poll<TestsResp>; hypothesis: string; setHypothesis: (h: string) => void }) {
  return (
    <Panel id="lineage" title="Research Lineage" subtitle="The quant workflow run: tasks by stage with the division role that ran them, and the registry provenance of each test.">
      <QState poll={poll} what="quant workflow">
        {(w) => (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Kpi label="Run" value={<span className="text-sm">{w.cycle.id}</span>} sub={fmtTime(w.cycle.created)} />
              <Kpi label="Status" value={w.cycle.status} tone={w.cycle.status === "completed" ? undefined : "warn"} />
              <Kpi label="Tasks" value={w.tasks.length} sub={Object.entries(w.cycle.summary?.counts ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")} />
              <Kpi label="Wall time" value={w.cycle.summary?.wall_s !== undefined ? `${w.cycle.summary.wall_s} s` : "—"} sub={`LLM calls ${w.tasks.reduce((a, t) => a + (t.llm_calls ?? 0), 0)}`} />
            </div>
            <ol className="space-y-2">
              {STAGES.filter((s) => w.tasks.some((t) => t.stage === s))
                .concat(Array.from(new Set(w.tasks.map((t) => t.stage))).filter((s) => !STAGES.includes(s)))
                .map((s) => (
                  <li key={s} className="rounded-md border border-line bg-panel2 p-2">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">{s}</p>
                    <ul className="mt-1 space-y-1.5">
                      {w.tasks
                        .filter((t) => t.stage === s)
                        .map((t) => (
                          <TaskRow key={t.id} t={t} />
                        ))}
                    </ul>
                  </li>
                ))}
            </ol>
            {w.runs.length > 1 && (
              <p className="text-[11px] text-muted">
                Earlier quant runs: {w.runs.slice(1).map((r) => `${r.id} (${r.status})`).join(", ")}
              </p>
            )}
            <TestProvenance tests={tests} hypothesis={hypothesis} setHypothesis={setHypothesis} tasks={w.tasks} />
          </div>
        )}
      </QState>
    </Panel>
  );
}

function summarize(t: QTask): ReactNode {
  const r = t.result ?? {};
  if (t.kind === "q_gap") return `${String(r.status ?? "")}: ${String(r.why ?? "")}`;
  if (t.kind === "q_events") {
    const v = r.verify as { ok?: boolean; entries?: number } | undefined;
    return `registry ${JSON.stringify(r.counts ?? {})} · journal verify ${v?.ok ? "ok" : "FAILED"} (${v?.entries ?? "?"} entries) · policy actions ${JSON.stringify(r.policy_actions ?? {})}`;
  }
  if (t.kind === "q_reassess")
    return (
      <>
        {String(r.claims ?? "")}
        {Array.isArray(r.next) && (
          <ul className="mt-1 list-disc pl-4">
            {(r.next as { id: string; why: string }[]).map((n) => (
              <li key={n.id}>
                <b>{n.id}</b>: {n.why}
              </li>
            ))}
          </ul>
        )}
      </>
    );
  if (t.kind === "q_adversarial" && Array.isArray(r.reviews))
    return (
      <ul className="list-disc pl-4">
        {(r.reviews as { hypothesis: string; practical?: string; years_same_sign?: string; effect_without_fomc_election_days?: number }[]).map((x) => (
          <li key={x.hypothesis}>
            <b>{x.hypothesis}</b>
            {x.years_same_sign ? ` · same sign ${x.years_same_sign} years` : ""}
            {typeof x.effect_without_fomc_election_days === "number" ? ` · without FOMC/election days ${num(x.effect_without_fomc_election_days)}` : ""}
            {x.practical ? ` · ${x.practical}` : ""}
          </li>
        ))}
      </ul>
    );
  if (t.kind === "q_calendar")
    return Object.entries(r)
      .filter(([k]) => k.startsWith("F-"))
      .map(([k, v]) => {
        const f = v as { tests?: number; discovery_survivors_bh?: string[]; supported?: string[] };
        return `${k}: ${f.tests ?? "?"} tests, ${f.discovery_survivors_bh?.length ?? 0} BH survivors, ${f.supported?.length ?? 0} survived confirmation`;
      })
      .join(" · ");
  if (t.kind === "q_xevent") {
    const x = (r.xevent ?? {}) as Record<string, Record<string, { n_true: number; n_false: number; p: number; status: string } | string>>;
    return Object.entries(x)
      .filter(([, v]) => v && typeof v === "object")
      .flatMap(([per, cells]) =>
        Object.entries(cells)
          .filter(([, c]) => c && typeof c === "object")
          .map(([k, c]) => {
            const cc = c as { n_true: number; n_false: number; p: number; status: string };
            return `${per.toLowerCase()} ${k}: n ${cc.n_true}/${cc.n_false}, p ${fp(cc.p)} (${cc.status})`;
          }),
      )
      .join(" · ");
  }
  if (t.kind === "q_elections") {
    const n = (r.n_events ?? {}) as Record<string, Record<string, number>>;
    return (
      Object.entries(n)
        .map(([a, v]) => `${a.split(" ")[0]} ${Object.entries(v).map(([k, x]) => `${k} ${x}`).join("/")}`)
        .join(" · ") + ` · pending ${JSON.stringify(r.pending ?? [])} · all descriptive (n < 20)`
    );
  }
  if (t.kind === "q_diagnostics") {
    const a = (r.acf_ret_1_5 as number[] | undefined) ?? [];
    const b = (r.acf_absret_1_5 as number[] | undefined) ?? [];
    return `n ${String(r.n)} · ACF returns lags 1–5 [${a.map((v) => v.toFixed(3)).join(", ")}] · ACF |returns| [${b.map((v) => v.toFixed(3)).join(", ")}] · Bartlett band ±${typeof r.band === "number" ? r.band.toFixed(3) : "?"}`;
  }
  if (t.kind === "q_memory") {
    const reg = r.registry as { total_tests?: number } | undefined;
    return `${String(r.memory_records ?? "?")} memory records written · registry total ${reg?.total_tests ?? "?"} tests`;
  }
  if (r.status && typeof r.status === "object")
    return Object.entries(r.status as Record<string, string>)
      .map(([k, v]) => `${k.split(":").slice(1).join(":") || k} ${v}`)
      .join(" · ");
  const keys = Object.keys(r).filter((k) => k !== "artifact");
  return keys.length ? JSON.stringify(Object.fromEntries(keys.slice(0, 4).map((k) => [k, r[k]]))).slice(0, 300) : "—";
}

function TaskRow({ t }: { t: QTask }) {
  const tone = t.status === "done" ? "text-up" : t.status === "failed" ? "text-down" : "text-warn";
  return (
    <li className="grid gap-1 text-xs sm:grid-cols-[9rem_minmax(0,1fr)]">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="rounded border border-line2 px-1.5 font-mono text-[11px]" title={DIVISION[t.role[0]] ?? t.role}>
          {t.role}
        </span>
        <span className="font-mono text-[11px] text-ink2">{t.kind}</span>
        <span className={`text-[11px] ${tone}`}>{t.status}</span>
      </div>
      <div className="min-w-0 text-ink2 [overflow-wrap:anywhere]">
        {summarize(t)}
        <span className="ml-1 text-[11px] text-muted">
          · {typeof t.wall_s === "number" ? `${t.wall_s.toFixed(2)} s` : "—"} · llm {t.llm_calls ?? 0}
          {t.deps?.deps?.length ? ` · after ${t.deps.deps.map((x) => x.split(":")[1]).join(", ")}` : ""}
        </span>
        {t.error && <p className="mt-0.5 font-mono text-[11px] text-down">{t.error}</p>}
      </div>
    </li>
  );
}

function TestProvenance({ tests, hypothesis, setHypothesis, tasks }: { tests: Poll<TestsResp>; hypothesis: string; setHypothesis: (h: string) => void; tasks: QTask[] }) {
  const rows: TestRow[] = useMemo(() => (tests.data?.tests ?? []).filter((t) => t.hypothesis === hypothesis), [tests.data, hypothesis]);
  const hyps = useMemo(() => Array.from(new Set((tests.data?.tests ?? []).map((t) => t.hypothesis))).sort(), [tests.data]);
  const fam = rows[0]?.family;
  const task = fam ? tasks.find((t) => t.kind === FAMILY_TASK[fam]) : undefined;
  return (
    <section aria-labelledby="prov-h" className="rounded-lg border border-line2 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="prov-h" className="text-sm font-semibold">
          Test provenance
        </h3>
        <label className="flex min-w-0 items-center gap-1.5 text-xs text-muted">
          Hypothesis
          <select className="input !w-auto !max-w-[14rem] !py-1 !text-xs sm:!max-w-[22rem]" value={hypothesis} onChange={(e) => setHypothesis(e.target.value)}>
            {!hyps.includes(hypothesis) && <option value={hypothesis}>{hypothesis || "—"}</option>}
            {hyps.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
        </label>
      </div>
      {tests.error && <ErrorNote error={tests.error} what="test registry" />}
      {task && (
        <p className="mt-1 text-xs text-ink2">
          Produced by task <code className="text-[11px]">{task.kind}</code> (role {task.role}, {DIVISION[task.role[0]] ?? ""}, stage {task.stage}).
        </p>
      )}
      {rows.length === 0 ? (
        <p className="mt-2 text-xs text-muted">Pick a hypothesis (or use &ldquo;trace&rdquo; in the rankings).</p>
      ) : (
        <div className="mt-2">
          <TableWrap label="Test provenance">
            <table className="data">
              <thead>
                <tr>
                  <th>Test id</th>
                  <th>Period</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Method</th>
                  <th>Adjustment</th>
                  <th>run_id</th>
                  <th>data_sha</th>
                  <th>protocol_sha</th>
                  <th>Created</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id}>
                    <td className="font-mono text-[11px]">{t.id}</td>
                    <td>{t.period.toLowerCase()}</td>
                    <td title={DIVISION[t.role[0]]}>{t.role}</td>
                    <td>
                      <QStatus s={t.status} />
                    </td>
                    <td className="!whitespace-normal min-w-[12rem] text-ink2">{t.method}</td>
                    <td className="text-ink2">{t.adj_method ?? "none"}</td>
                    <td>
                      <Hash v={t.run_id} n={22} />
                    </td>
                    <td>{t.data_sha ? <Hash v={t.data_sha} /> : <span className="text-warn">missing</span>}</td>
                    <td>
                      <Hash v={t.protocol_sha} />
                    </td>
                    <td className="tnum text-ink2">{fmtTime(t.created)}</td>
                    <td className="!whitespace-normal min-w-[18rem] font-mono text-[11px] text-ink2 [overflow-wrap:anywhere]">
                      {t.details && Object.keys(t.details).length ? JSON.stringify(t.details).slice(0, 240) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </div>
      )}
    </section>
  );
}

/* ================================================================ 8. forward monitor */

export function ForwardPanel({ fcast, fomcEvents, elections }: { fcast: Poll<ForecastLinkResp>; fomcEvents: Poll<EventsResp>; elections: Poll<ElectionsResp> }) {
  const upcoming = (fomcEvents.data?.events ?? []).filter((e) => e.attributes?.future).sort((a, b) => a.event_time_utc.localeCompare(b.event_time_utc));
  return (
    <Panel
      id="forward"
      title="Forward Prediction Monitor"
      subtitle="Does a calendar/event feature improve the frozen forecasting baseline? Loss difference H1 − M1 (negative = the feature helps), block-bootstrap CI, Holm over the F-FCAST family."
    >
      <div className="space-y-3">
        <QState poll={fcast} what="forecast link (F-FCAST)">
          {(d) => (
            <div className="space-y-2">
              <TableWrap label="F-FCAST results">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Feature</th>
                      <th>Target</th>
                      <th className="text-right">Feature rate</th>
                      <th className="text-right">SCREEN Δloss [CI] (n)</th>
                      <th className="text-right">SCREEN p</th>
                      <th className="text-right">DEV Δloss [CI] (n)</th>
                      <th className="text-right">DEV p</th>
                      <th className="text-right">Holm p</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(d.results).map(([k, r]) => {
                      const [, feat, target] = k.split(":");
                      return (
                        <tr key={k}>
                          <td className="font-mono text-[11px]">{feat}</td>
                          <td className="font-mono text-[11px]">{target}</td>
                          <td className="text-right tnum">{fpctU(r.feature_rate, 1)}</td>
                          <td className="text-right tnum">
                            <Delta v={r.SCREEN.mean} /> <span className="text-ink2">[{num(r.SCREEN.lo)}, {num(r.SCREEN.hi)}]</span>{" "}
                            <span className="text-muted">({r.SCREEN.n})</span>
                          </td>
                          <td className="text-right tnum">{fp(r.SCREEN.p_better)}</td>
                          <td className="text-right tnum">
                            <Delta v={r.DEV.mean} /> <span className="text-ink2">[{num(r.DEV.lo)}, {num(r.DEV.hi)}]</span> <span className="text-muted">({r.DEV.n})</span>
                          </td>
                          <td className="text-right tnum">{fp(r.DEV.p_better)}</td>
                          <td className="text-right tnum">
                            {fp(r.holm.p_adj)}
                            {r.holm.reject ? " ✓" : ""}
                          </td>
                          <td>
                            <QStatus s={r.status} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableWrap>
              <p className="text-[11px] text-muted">
                {d.note}. SCREEN and DEV are previously exposed data (selection evidence only). &ldquo;Candidate feature&rdquo; means at most a prospective
                challenger — never an automatic promotion. saturday_target_day was added by amendment 1 <i>because</i> F-DOW Saturday survived confirmation; its
                forecast test is a pipeline step, not independent confirmation.
              </p>
            </div>
          )}
        </QState>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="min-w-0 rounded-md border border-line bg-panel2 p-3">
            <h3 className="text-sm font-semibold">Upcoming FOMC statements (registry, future = true)</h3>
            {fomcEvents.error && <ErrorNote error={fomcEvents.error} what="event registry" />}
            {fomcEvents.data && (
              <>
                <ul className="mt-2 space-y-1 text-xs">
                  {upcoming.length === 0 && <li className="text-muted">none registered</li>}
                  {upcoming.map((e) => (
                    <li key={e.event_id} className="flex flex-wrap justify-between gap-2">
                      <span className="tnum">{fmtTime(e.event_time_utc).slice(0, 16)}Z</span>
                      <span className="text-ink2">
                        {e.subcategory}
                        {e.attributes?.sep ? " · SEP" : ""} · v{e.version}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[11px] text-muted">
                  Each statement is a prospective observation for F-FOMC absret_0_4h. Registry journal{" "}
                  {fomcEvents.data.verify.ok ? <span className="text-up">verified</span> : <span className="text-down">FAILED verification</span>} ·{" "}
                  {fomcEvents.data.verify.entries} entries · head <Hash v={fomcEvents.data.verify.head} />
                </p>
                {upcoming[0]?.source_url && (
                  <p className="text-[11px] text-muted [overflow-wrap:anywhere]">
                    source: {upcoming[0].source_url} · sha256 <Hash v={upcoming[0].source_sha256} />
                  </p>
                )}
              </>
            )}
          </div>
          <div className="min-w-0 rounded-md border border-line bg-panel2 p-3">
            <h3 className="text-sm font-semibold">Pending events</h3>
            {elections.error && !(elections.error instanceof ApiError && elections.error.status === 404) && <ErrorNote error={elections.error} what="elections" />}
            {elections.data ? (
              <ul className="mt-2 space-y-1 text-xs">
                {elections.data.pending.map((p) => (
                  <li key={p}>
                    <span className="font-mono">{p}</span> — {elections.data?.pending_note}
                  </li>
                ))}
                {elections.data.pending.length === 0 && <li className="text-muted">none</li>}
              </ul>
            ) : (
              <p className="mt-2 text-xs text-muted">election study not produced yet</p>
            )}
            <p className="mt-2 text-xs text-ink2">
              The prospective forecast ledger (the only independent evidence) lives in the{" "}
              <Link href="/forecast#prospective" prefetch={false} className="text-[#9ec5f4] underline">
                Forecasting Laboratory
              </Link>
              . No quant feature enters it unless a human approves a prospective challenger.
            </p>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function Delta({ v }: { v: number }) {
  return <span className={v < 0 ? "text-[#9ec5f4]" : "text-ink"}>{num(v)}</span>;
}

/* ================================================================ event explorer wrapper */

export function EventExplorer({ fomc, elections }: { fomc: Poll<FomcResp>; elections: Poll<ElectionsResp> }) {
  return (
    <Panel id="events" title="Political & Macro Event Explorer" subtitle="Event studies against matched placebo times. Only registered events (versioned Event Registry) are used.">
      <div className="space-y-6">
        <FomcPanel poll={fomc} />
        <div className="border-t border-line pt-4">
          <ElectionsPanel poll={elections} />
        </div>
      </div>
    </Panel>
  );
}

