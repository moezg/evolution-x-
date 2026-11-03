"use client";
import { Fragment, type ReactNode } from "react";
import { EmptyState, ErrorNote, Kpi, Panel } from "@/components/ui";
import { Hash, IntervalPlot, Prov } from "@/components/research";
import { ApiError } from "@/lib/api";
import { fmtAny, fmtTime, humanize } from "@/lib/format";
import type { Poll } from "@/lib/hooks";
import {
  fx,
  fxSigned,
  interval,
  isPaired,
  leadingStatus,
  verdictTone,
  type ArchiveHistoryEntry,
  type Audit,
  type ExperimentSpec,
  type ExperimentsResp,
  type HypResult,
  type ObsIndex,
  type Paired,
  type PreregHypothesis,
  type RealismEntry,
  type RealismResp,
  type Tone,
  type VolatilityProtocol,
  type VolatilityReport,
  type VolatilityResp,
} from "@/lib/observatory";

/* ================================================================ primitives */

export const TONE_CLS: Record<Tone, string> = {
  good: "border-up/60 bg-up/15 text-up",
  weak: "border-warn/60 bg-warn/15 text-warn",
  neutral: "border-line2 bg-panel2 text-ink2",
  bad: "border-down/60 bg-down/15 text-[#f3a7a7]",
  info: "border-accent/60 bg-accent/15 text-[#9ec5f4]",
};

export function VerdictBadge({ v, label }: { v: string | null | undefined; label?: string }) {
  if (!v) return <span className="text-[11px] text-muted">—</span>;
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold ${TONE_CLS[verdictTone(v)]}`}>
      {label && <span className="font-normal opacity-80">{label}:</span>}
      {v}
    </span>
  );
}

const STATUS_TONE: Record<string, Tone> = { IMPLEMENTED: "good", PARTIAL: "weak", MISSING: "bad", UNVERIFIED: "neutral" };

function StatusBadge({ status }: { status: string }) {
  const lead = leadingStatus(status);
  return (
    <span className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-bold tracking-wider ${TONE_CLS[STATUS_TONE[lead] ?? "neutral"]}`}>{lead}</span>
  );
}

/** Wrapper that keeps wide tables scrollable on narrow screens. */
export function TableWrap({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="max-w-full overflow-x-auto" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

/** Compact "k: v · k: v" rendering of an override/evidence dict. */
export function Kv({ data }: { data: Record<string, unknown> | undefined | null }) {
  if (!data || Object.keys(data).length === 0) return <span className="text-muted">(none)</span>;
  return (
    <span className="break-words font-mono text-[11px] text-ink2 [overflow-wrap:anywhere]">
      {Object.entries(data).map(([k, v], i) => (
        <Fragment key={k}>
          {i > 0 && <span className="text-muted"> · </span>}
          <span className="text-muted">{k}</span>=
          <span className="text-ink">{v !== null && typeof v === "object" ? JSON.stringify(v) : fmtAny(v)}</span>
        </Fragment>
      ))}
    </span>
  );
}

/** Loading / 404 ("not produced yet") / error states shared by every section. */
export function SectionState<T>({ poll, what, children }: { poll: Poll<T>; what: string; children: (d: T) => ReactNode }) {
  if (poll.data) return <>{children(poll.data)}</>;
  if (poll.error instanceof ApiError && poll.error.status === 404)
    return (
      <EmptyState title={`${what}: not produced yet`}>
        <p>{poll.error.detail}</p>
        <p className="mt-1">The backend returns 404 until the corresponding artifact exists under artifacts/observatory/.</p>
      </EmptyState>
    );
  if (poll.error) return <ErrorNote error={poll.error} what={what} />;
  return <p className="text-xs text-muted">Loading {what}…</p>;
}

function PairedCells({ p }: { p: Paired | undefined }) {
  if (!p)
    return (
      <>
        <td className="num text-muted">—</td>
        <td className="num text-muted">—</td>
        <td className="num text-muted">—</td>
        <td className="num text-muted">—</td>
        <td className="num text-muted">—</td>
      </>
    );
  const tExcl = typeof p.t_lo === "number" && typeof p.t_hi === "number" && (p.t_lo > 0 || p.t_hi < 0);
  const bExcl = typeof p.lo === "number" && typeof p.hi === "number" && (p.lo > 0 || p.hi < 0);
  return (
    <>
      <td className="num font-semibold">{fxSigned(p.mean)}</td>
      <td className={`num ${bExcl ? "text-ink" : "text-muted"}`} title={bExcl ? "bootstrap CI excludes 0" : "bootstrap CI includes 0"}>
        {interval(p.lo, p.hi)}
      </td>
      <td className={`num ${tExcl ? "text-ink" : "text-muted"}`} title={tExcl ? "t-interval excludes 0" : "t-interval includes 0 (or missing)"}>
        {interval(p.t_lo, p.t_hi)}
      </td>
      <td className="num">{fx(p.frac_positive)}</td>
      <td className="num text-muted">{fmtAny(p.n)}</td>
    </>
  );
}

const PAIRED_HEAD = (
  <>
    <th className="num">mean Δ</th>
    <th className="num">bootstrap 95% [lo, hi]</th>
    <th className="num">t-interval [t_lo, t_hi]</th>
    <th className="num">frac &gt; 0</th>
    <th className="num">n</th>
  </>
);

function Prereg({ h }: { h: PreregHypothesis }) {
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
      {h.claim && (
        <>
          <dt className="text-muted">claim</dt>
          <dd className="text-ink2">{h.claim}</dd>
        </>
      )}
      {h.prediction && (
        <>
          <dt className="text-muted">prediction</dt>
          <dd className="text-ink">{h.prediction}</dd>
        </>
      )}
      {h.refuted_if && (
        <>
          <dt className="text-muted">refuted if</dt>
          <dd className="text-ink2">{h.refuted_if}</dd>
        </>
      )}
      {h.report && (
        <>
          <dt className="text-muted">report</dt>
          <dd className="text-ink2">{h.report}</dd>
        </>
      )}
    </dl>
  );
}

/* ================================================================ a. banner */

export function Banner({ index }: { index: Poll<ObsIndex> }) {
  const specs = index.data?.frozen_specs_sha256 ?? {};
  return (
    <div className="rounded-lg border border-warn/60 bg-warn/10 px-3 py-2 sm:px-4" role="note">
      <p className="text-sm font-semibold text-warn">SYNTHETIC simulator research — no trading claims, no holdout data, 0 LLM calls</p>
      {index.data?.label && <p className="mt-0.5 text-xs text-ink2">{index.data.label}</p>}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <span>Frozen protocol sha256:</span>
        {Object.entries(specs).map(([f, sha]) => (
          <span key={f} className="whitespace-nowrap">
            {f.replace(/\.json$/, "")} <Hash v={sha} n={10} label={f} />
          </span>
        ))}
        {index.error && <span className="text-down">index unavailable ({index.error.message})</span>}
        {!index.data && !index.error && <span>loading…</span>}
      </div>
      {index.data && (
        <p className="mt-1 text-[11px] text-muted">
          Artifacts: <span className="font-mono">{index.data.artifacts.join(", ") || "none"}</span>
        </p>
      )}
    </div>
  );
}

/* ================================================================ b. capability matrix */

function Evidence({ ev }: { ev: unknown }) {
  if (ev === undefined || ev === null) return <span className="text-muted">—</span>;
  if (typeof ev !== "object") return <span className="text-ink2">{fmtAny(ev)}</span>;
  return (
    <ul className="space-y-0.5">
      {Object.entries(ev as Record<string, unknown>).map(([k, v]) => (
        <li key={k} className="break-words [overflow-wrap:anywhere]">
          <span className="text-muted">{k}:</span>{" "}
          <span className="font-mono text-[11px] text-ink">{v !== null && typeof v === "object" ? JSON.stringify(v) : fmtAny(v)}</span>
        </li>
      ))}
    </ul>
  );
}

export function CapabilityMatrix({ poll }: { poll: Poll<Audit> }) {
  return (
    <Panel
      id="capabilities"
      title="Capability matrix (audit)"
      subtitle="What the simulator actually does, measured in one audit run. Status words come from the audit file; the badge shows the leading word, the full text is next to it."
    >
      <SectionState poll={poll} what="audit">
        {(a) => {
          const caps = Object.entries(a.capabilities ?? {});
          const counts = caps.reduce<Record<string, number>>((m, [, c]) => {
            const k = leadingStatus(c.status);
            m[k] = (m[k] ?? 0) + 1;
            return m;
          }, {});
          const pairs = Object.entries(a.trade_volume_by_kind_pair_btc ?? {});
          return (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                {Object.entries(counts).map(([k, n]) => (
                  <span key={k} className="flex items-center gap-1">
                    <StatusBadge status={k} /> {n}
                  </span>
                ))}
                <span>
                  · audit run seed {fmtAny(a.seed)}, {fmtAny(a.duration_s)} s, fingerprint <Hash v={a.fingerprint} n={16} />, {fmtTime(a.created_utc)}
                </span>
              </div>
              <TableWrap label="Capability matrix">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Capability</th>
                      <th>Status</th>
                      <th>Key evidence</th>
                      <th>Code</th>
                    </tr>
                  </thead>
                  <tbody>
                    {caps.map(([name, c]) => (
                      <tr key={name}>
                        <td className="align-top font-medium">{humanize(name)}</td>
                        <td className="min-w-[10rem] !whitespace-normal align-top">
                          <StatusBadge status={c.status} />
                          {c.status !== leadingStatus(c.status) && <div className="mt-0.5 text-[11px] text-ink2">{c.status}</div>}
                        </td>
                        <td className="min-w-[18rem] max-w-[40rem] !whitespace-normal align-top text-xs">
                          <Evidence ev={c.evidence} />
                        </td>
                        <td className="align-top">
                          {c.code?.length ? (
                            <ul className="font-mono text-[11px] text-ink2">
                              {c.code.map((r) => (
                                <li key={r}>{r}</li>
                              ))}
                            </ul>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
              {pairs.length > 0 && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-ink2">Trade volume by kind pair (BTC, audit run)</summary>
                  <ul className="mt-1 grid grid-cols-1 gap-x-4 font-mono text-[11px] sm:grid-cols-2 lg:grid-cols-3">
                    {pairs.map(([k, v]) => (
                      <li key={k} className="flex justify-between gap-2 border-b border-line py-0.5">
                        <span className="text-ink2">{k}</span>
                        <span className="tnum">{fx(v)}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          );
        }}
      </SectionState>
    </Panel>
  );
}

/* ================================================================ c. volatility */

const MID = "mid_ret_std_bps.1m";

function MmmCell({ s, d }: { s: { mean: number | null; min: number | null; max: number | null } | undefined; d?: number }) {
  if (!s) return <td className="num text-muted">—</td>;
  return (
    <td className="num">
      <span className="font-semibold">{fx(s.mean, d)}</span>{" "}
      <span className="text-[11px] text-muted">
        ({fx(s.min, d)}–{fx(s.max, d)})
      </span>
    </td>
  );
}

function VolReport({ rep, hyps, title }: { rep: VolatilityReport; hyps: Record<string, PreregHypothesis>; title: string }) {
  const target = rep.historical_train_targets?.ret_std_bps;
  const conds = Object.keys(rep.summary ?? {});
  const base = conds[0];
  const baseMid = base ? rep.summary[base]?.[MID]?.mean : null;
  const rows = conds.map((c) => {
    const s = rep.summary[c]?.[MID];
    return { label: c, point: s?.mean ?? undefined, lo: s?.min ?? undefined, hi: s?.max ?? undefined };
  });
  return (
    <section aria-label={title} className="space-y-3 rounded-md border border-line bg-panel2 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <Prov kind="SYNTHETIC" />
        <span className="text-[11px] text-muted">
          seeds {rep.seeds?.join(", ")} · {fmtAny(rep.duration_s)} s per run · {fmtTime(rep.created_utc)}
        </span>
      </div>
      <TableWrap label={`${title} conditions`}>
        <table className="data">
          <thead>
            <tr>
              <th>Condition</th>
              <th>Overrides</th>
              <th className="num" title="mean over seeds (min–max)">
                Mid 1m std bps
              </th>
              <th className="num" title="mid 1m std / historical TRAIN median">
                × hist.
              </th>
              <th className="num" title={`change of the seed-mean vs ${base}; not a paired statistic`}>
                Δ vs {base}
              </th>
              <th className="num">Fundamental 1m std bps</th>
              <th className="num">Corr mid~fund 1m</th>
              <th className="num">Excess kurtosis 1m</th>
              <th className="num">Tracking error bps</th>
            </tr>
          </thead>
          <tbody>
            {target && (
              <tr className="bg-[#c98500]/10">
                <td className="font-medium text-[#f2c14e]">historical TRAIN target</td>
                <td className="text-[11px] text-muted">median (IQR) of 1m BTCUSDT train days</td>
                <td className="num font-semibold text-[#f2c14e]">
                  {fx(target.median)} <span className="text-[11px] font-normal text-muted">(IQR {fx(target.iqr)})</span>
                </td>
                <td className="num text-muted">1.00</td>
                <td className="num text-muted">—</td>
                <td className="num text-muted">—</td>
                <td className="num text-muted">—</td>
                <td className="num text-[#f2c14e]">{fx(rep.historical_train_targets?.excess_kurtosis?.median)}</td>
                <td className="num text-muted">—</td>
              </tr>
            )}
            {conds.map((c) => {
              const s = rep.summary[c] ?? {};
              const mid = s[MID]?.mean;
              const ratio = typeof mid === "number" && target ? mid / target.median : null;
              const delta = c !== base && typeof mid === "number" && typeof baseMid === "number" && baseMid !== 0 ? ((mid - baseMid) / baseMid) * 100 : null;
              return (
                <tr key={c}>
                  <td className="align-top font-medium">{c}</td>
                  <td className="max-w-[22rem] !whitespace-normal align-top">
                    <Kv data={rep.conditions?.[c]} />
                  </td>
                  <MmmCell s={s[MID]} />
                  <td className="num">{ratio === null ? "—" : `${ratio.toFixed(2)}×`}</td>
                  <td className="num">{delta === null ? <span className="text-muted">—</span> : `${delta >= 0 ? "+" : ""}${delta.toFixed(0)}%`}</td>
                  <MmmCell s={s["fundamental_ret_std_bps.1m"]} />
                  <MmmCell s={s["corr_mid_fundamental.1m"]} />
                  <MmmCell s={s["excess_kurtosis_1m"]} />
                  <MmmCell s={s["tracking_error_bps"]} />
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableWrap>
      <div>
        <p className="mb-1 text-[11px] text-muted">Mid 1m return std (bps): seed mean ◆ with min–max whisker; dashed line = historical TRAIN median.</p>
        <IntervalPlot
          rows={rows}
          label={`${title}: mid 1m return std by condition`}
          refs={target ? [{ at: target.median, label: `hist. ${fx(target.median)}`, color: "#f2c14e" }] : []}
          fmt={(v) => fx(v)}
          labelWidth={150}
        />
      </div>
      {Object.keys(hyps).length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">Pre-registered hypotheses (no verdict recorded in the report — compare with the numbers above)</h4>
          <ul className="grid grid-cols-1 gap-2 lg:grid-cols-2">
            {Object.entries(hyps).map(([id, h]) => (
              <li key={id} className="rounded border border-line bg-panel p-2">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <code className="text-xs font-semibold text-ink">{id}</code>
                  <Prov kind="HYPOTHESIS" />
                </div>
                <Prereg h={h} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function hypsForReport(tag: string, p: VolatilityProtocol): Record<string, PreregHypothesis> {
  if (tag === "v1") return p.hypotheses ?? {};
  if (tag.startsWith("v2")) return p.amendment_v2?.hypotheses ?? {};
  return {};
}

export function VolatilitySection({ poll }: { poll: Poll<VolatilityResp> }) {
  return (
    <Panel id="volatility" title="Volatility diagnosis" subtitle="Why is simulated 1-minute volatility above the historical TRAIN-day level? One factor changed at a time, paired seeds.">
      <SectionState poll={poll} what="volatility diagnosis">
        {(d) => {
          const p = d.protocol;
          const reps = Object.entries(d.reports ?? {});
          return (
            <div className="space-y-3">
              <div className="space-y-1 text-xs">
                <p className="text-sm text-ink">{p.question}</p>
                {p.design && (
                  <p className="text-ink2">
                    <span className="text-muted">Design:</span> {p.design}
                  </p>
                )}
                {p.historical_reference && (
                  <p className="text-ink2">
                    <span className="text-muted">Historical reference:</span> {p.historical_reference}
                  </p>
                )}
                {p.stopping_rule && (
                  <p className="text-ink2">
                    <span className="text-muted">Stopping rule:</span> {p.stopping_rule}
                  </p>
                )}
                {p.amendment_v2 && (
                  <p className="text-ink2">
                    <span className="text-muted">Amendment v2 ({fmtTime(p.amendment_v2.written_utc)}, after v1 results):</span> {p.amendment_v2.question}{" "}
                    <span className="text-muted">Base:</span> {p.amendment_v2.base}. <span className="text-muted">v1 summary:</span> {p.amendment_v2.after_results}
                  </p>
                )}
              </div>
              {reps.length === 0 ? (
                <EmptyState title="No volatility reports produced yet" />
              ) : (
                reps.map(([tag, rep]) => <VolReport key={tag} rep={rep} hyps={hypsForReport(rep.tag ?? tag, p)} title={`Report ${tag}`} />)
              )}
            </div>
          );
        }}
      </SectionState>
    </Panel>
  );
}

/* ================================================================ d. experiments */

interface Flat {
  verdicts: { label: string; v: string }[];
  paired: { label: string; p: Paired }[];
  other: { label: string; v: unknown }[];
}

/** Flatten a hypothesis result: verdict* strings, Paired stats and other values, with nested keys joined by " · ". */
function flatten(obj: HypResult, prefix = "", out: Flat = { verdicts: [], paired: [], other: [] }): Flat {
  for (const [k, v] of Object.entries(obj)) {
    const label = prefix ? `${prefix} · ${k}` : k;
    if (k.startsWith("verdict") && typeof v === "string") {
      const sub = k === "verdict" ? "" : k.replace(/^verdict_/, "");
      out.verdicts.push({ label: [prefix, sub].filter(Boolean).join(" · "), v });
    } else if (isPaired(v)) {
      out.paired.push({ label, p: v });
    } else if (v && typeof v === "object" && !Array.isArray(v)) {
      flatten(v as HypResult, label, out);
    } else {
      out.other.push({ label, v });
    }
  }
  return out;
}

function fmtVal(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map((x) => (typeof x === "number" ? fx(x) : fmtAny(x))).join(", ")}]`;
  if (typeof v === "number") return fx(v);
  return fmtAny(v);
}

function HypothesisCard({ id, spec, res }: { id: string; spec: PreregHypothesis; res: HypResult | undefined }) {
  const f = res ? flatten(res) : undefined;
  return (
    <li className="space-y-2 rounded-md border border-line bg-panel2 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <code className="text-xs font-semibold text-ink">{id}</code>
        {f?.verdicts.length ? f.verdicts.map((x) => <VerdictBadge key={x.label + x.v} v={x.v} label={x.label || undefined} />) : <VerdictBadge v={res ? "no verdict field" : "no result"} />}
      </div>
      <Prereg h={spec} />
      {f && f.paired.length > 0 && (
        <TableWrap label={`${id} paired effects`}>
          <table className="data">
            <thead>
              <tr>
                <th>Paired effect (treatment − control)</th>
                {PAIRED_HEAD}
              </tr>
            </thead>
            <tbody>
              {f.paired.map((x) => (
                <tr key={x.label}>
                  <td className="font-mono text-[11px]">{x.label}</td>
                  <PairedCells p={x.p} />
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      {f && f.other.length > 0 && (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
          {f.other.map((x) => (
            <Fragment key={x.label}>
              <dt className="font-mono text-[11px] text-muted">{x.label}</dt>
              <dd className="break-words font-mono text-[11px] text-ink [overflow-wrap:anywhere]">{fmtVal(x.v)}</dd>
            </Fragment>
          ))}
        </dl>
      )}
    </li>
  );
}

function ExperimentBlock({ letter, spec, hyps, children }: { letter: string; spec: ExperimentSpec; hyps: Record<string, HypResult>; children?: ReactNode }) {
  const extra: Record<string, unknown> = {};
  if (spec.shock) extra.shock = spec.shock;
  if (spec.factors) extra.factors = spec.factors;
  if (spec.control) extra.control = spec.control;
  if (spec.window) extra.window = spec.window;
  return (
    <section aria-labelledby={`exp-${letter}`} className="space-y-3 rounded-lg border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={`exp-${letter}`} className="text-sm font-semibold">
          Experiment {letter}
        </h3>
        <Prov kind="SYNTHETIC" />
      </div>
      <p className="text-sm text-ink">{spec.question}</p>
      <div className="space-y-1 text-xs">
        {spec.conditions &&
          Object.entries(spec.conditions).map(([c, o]) => (
            <div key={c}>
              <span className="font-medium text-ink2">{c}</span>: <Kv data={o} />
            </div>
          ))}
        {Object.entries(extra).map(([k, v]) => (
          <div key={k}>
            <span className="text-muted">{k}:</span> {typeof v === "string" ? <span className="text-ink2">{v}</span> : <Kv data={v as Record<string, unknown>} />}
          </div>
        ))}
        {spec.caveat && (
          <p className="text-warn">
            <span className="font-semibold">Caveat:</span> {spec.caveat}
          </p>
        )}
      </div>
      <ul className="space-y-2">
        {Object.entries(spec.hypotheses ?? {}).map(([id, h]) => (
          <HypothesisCard key={id} id={id} spec={h} res={hyps[id]} />
        ))}
        {Object.keys(hyps)
          .filter((id) => !(id in (spec.hypotheses ?? {})))
          .map((id) => (
            <HypothesisCard key={id} id={`${id} (not in protocol)`} spec={{}} res={hyps[id]} />
          ))}
      </ul>
      {children}
    </section>
  );
}

function DetectorAblation({ data }: { data: Record<string, Record<string, Paired>> }) {
  const comps = Array.from(new Set(Object.values(data).flatMap((v) => Object.keys(v))));
  return (
    <details className="text-xs" open>
      <summary className="cursor-pointer font-semibold text-ink2">A · detector ablation (paired full − ablated: mean, t-interval, n)</summary>
      <TableWrap label="Detector ablation">
        <table className="data mt-1">
          <thead>
            <tr>
              <th rowSpan={2}>Detector</th>
              {comps.map((c) => (
                <th key={c} colSpan={3} className="text-center">
                  {c}
                </th>
              ))}
            </tr>
            <tr>
              {comps.map((c) => (
                <Fragment key={c}>
                  <th className="num">mean</th>
                  <th className="num">t-interval</th>
                  <th className="num">n</th>
                </Fragment>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(data).map(([det, v]) => (
              <tr key={det}>
                <td className="font-mono text-[11px]">{det}</td>
                {comps.map((c) => {
                  const p = v[c];
                  const excl = p && typeof p.t_lo === "number" && typeof p.t_hi === "number" && (p.t_lo > 0 || p.t_hi < 0);
                  return (
                    <Fragment key={c}>
                      <td className="num">{fxSigned(p?.mean)}</td>
                      <td className={`num ${excl ? "font-semibold text-ink" : "text-muted"}`} title={excl ? "t-interval excludes 0" : "t-interval includes 0 or missing"}>
                        {interval(p?.t_lo, p?.t_hi)}
                      </td>
                      <td className={`num ${p && p.n < 4 ? "text-warn" : "text-muted"}`} title={p && p.n < 4 ? "fewer seeds than registered (metric undefined in some runs)" : undefined}>
                        {fmtAny(p?.n)}
                      </td>
                    </Fragment>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </details>
  );
}

function ConditionSummary({ data }: { data: Record<string, Record<string, Paired>> }) {
  const conds = Object.keys(data);
  const metrics = Array.from(new Set(conds.flatMap((c) => Object.keys(data[c]))));
  return (
    <details className="text-xs">
      <summary className="cursor-pointer font-semibold text-ink2">A · per-condition summary (mean [t-interval])</summary>
      <TableWrap label="A per-condition summary">
        <table className="data mt-1">
          <thead>
            <tr>
              <th>Metric</th>
              {conds.map((c) => (
                <th key={c} className="num">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metrics.map((m) => (
              <tr key={m}>
                <td className="font-mono text-[11px]">{m}</td>
                {conds.map((c) => {
                  const p = data[c][m];
                  return (
                    <td key={c} className="num">
                      {fx(p?.mean)} <span className="text-[11px] text-muted">{interval(p?.t_lo, p?.t_hi)}</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </details>
  );
}

function BEffects({ data }: { data: Record<string, Record<string, Paired>> }) {
  return (
    <details className="text-xs">
      <summary className="cursor-pointer font-semibold text-ink2">B · all paired effects vs control by withdrawal fraction</summary>
      <TableWrap label="B effects">
        <table className="data mt-1">
          <thead>
            <tr>
              <th>Fraction</th>
              <th>Metric</th>
              {PAIRED_HEAD}
            </tr>
          </thead>
          <tbody>
            {Object.entries(data).flatMap(([f, ms]) =>
              Object.entries(ms).map(([m, p]) => (
                <tr key={f + m}>
                  <td>{f}</td>
                  <td className="font-mono text-[11px]">{m}</td>
                  <PairedCells p={p} />
                </tr>
              )),
            )}
          </tbody>
        </table>
      </TableWrap>
    </details>
  );
}

function CCells({ data }: { data: Record<string, Record<string, (number | null)[]>> }) {
  const metrics = Array.from(new Set(Object.values(data).flatMap((v) => Object.keys(v))));
  return (
    <details className="text-xs" open>
      <summary className="cursor-pointer font-semibold text-ink2">C · cells (per-seed values)</summary>
      <TableWrap label="C cells">
        <table className="data mt-1">
          <thead>
            <tr>
              <th>Cell</th>
              {metrics.map((m) => (
                <th key={m} className="!whitespace-normal">
                  {m.replace(/_/g, " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(data).map(([cell, v]) => (
              <tr key={cell}>
                <td className="font-mono text-[11px]">{cell}</td>
                {metrics.map((m) => (
                  <td key={m} className="font-mono text-[11px]">
                    {v[m] ? fmtVal(v[m]) : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </details>
  );
}

export function ExperimentsSection({ poll }: { poll: Poll<ExperimentsResp> }) {
  return (
    <Panel id="experiments" title="Experiments A / B / C" subtitle="Pre-registered hypotheses, paired by seed (treatment − control). n = 4 seeds: low power, wide intervals by construction.">
      <SectionState poll={poll} what="experiments">
        {({ protocol: p, report: r }) => (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Kpi label="Runs" value={fmtAny(r.cost?.runs)} />
              <Kpi label="Wall time" value={`${fx(r.cost?.wall_s_total)} s`} sub={r.cost?.cpu_s_sum !== undefined ? `CPU sum ${fx(r.cost.cpu_s_sum)} s` : undefined} />
              <Kpi label="LLM calls" value={fmtAny(r.cost?.llm_calls)} tone={r.cost?.llm_calls ? "warn" : undefined} />
              <Kpi label="Seeds" value={p.common?.seeds?.join(", ") ?? "—"} sub={`${fmtAny(p.common?.duration_s)} s per run`} />
            </div>
            <div className="space-y-1 text-xs text-ink2">
              {p.status && <p className="text-ink">{p.status}</p>}
              {p.data_policy && (
                <p>
                  <span className="text-muted">Data policy:</span> {p.data_policy}
                </p>
              )}
              {p.base_profile && (
                <p>
                  <span className="text-muted">Base profile:</span> <b>{p.base_profile.name}</b> <Kv data={p.base_profile.overrides} /> — {p.base_profile.why}
                </p>
              )}
              {p.common?.pairing && (
                <p>
                  <span className="text-muted">Pairing:</span> {p.common.pairing}
                </p>
              )}
              {p.stopping_rule && (
                <p>
                  <span className="text-muted">Stopping rule:</span> {p.stopping_rule}
                </p>
              )}
              <p className="flex flex-wrap items-center gap-1">
                <span className="text-muted">Protocol sha256 (as recorded in the report):</span> <Hash v={r.protocol_sha256} n={16} />
                <span className="text-muted">· report created {fmtTime(r.created_utc)}</span>
              </p>
            </div>
            {p.amendment_1 && (
              <div className="rounded-md border border-[#9085e9]/50 bg-[#9085e9]/10 p-3 text-xs" role="note">
                <p className="mb-1 font-semibold text-[#c3bdf5]">Protocol amendment 1 ({fmtTime(p.amendment_1.written_utc)})</p>
                {p.amendment_1.before_results && (
                  <p className="text-ink2">
                    <span className="text-muted">Timing:</span> {p.amendment_1.before_results}
                  </p>
                )}
                {p.amendment_1.change && (
                  <p className="mt-1 text-ink">
                    <span className="text-muted">Change:</span> {p.amendment_1.change}
                  </p>
                )}
                {p.amendment_1.reason && (
                  <p className="mt-1 text-ink2">
                    <span className="text-muted">Reason:</span> {p.amendment_1.reason}
                  </p>
                )}
              </div>
            )}
            <ExperimentBlock letter="A" spec={p.A_stable} hyps={r.A?.hypotheses ?? {}}>
              {r.A?.detector_ablation && <DetectorAblation data={r.A.detector_ablation} />}
              {r.A?.summary && <ConditionSummary data={r.A.summary} />}
            </ExperimentBlock>
            <ExperimentBlock letter="B" spec={p.B_liquidity_crisis} hyps={r.B?.hypotheses ?? {}}>
              {r.B?.effects && <BEffects data={r.B.effects} />}
            </ExperimentBlock>
            <ExperimentBlock letter="C" spec={p.C_liquidation_cascade} hyps={r.C?.hypotheses ?? {}}>
              {r.C?.cells && <CCells data={r.C.cells} />}
            </ExperimentBlock>
          </div>
        )}
      </SectionState>
    </Panel>
  );
}

/* ================================================================ e. realism */

function verdictsOf(e: RealismEntry, incumbents: string[]): Record<string, string> {
  if (e.verdict_vs) return e.verdict_vs;
  if (e.verdict_vs_incumbent) return { [incumbents[0] ?? "default"]: e.verdict_vs_incumbent };
  return {};
}

function ObjCells({ e }: { e: RealismEntry }) {
  const o = e.objectives_mean ?? ({} as RealismEntry["objectives_mean"]);
  return (
    <>
      <td className="num">{fx(o.scale_error)}</td>
      <td className="num">{fx(o.shape_error)}</td>
      <td className="num">{fx(o.cost_cpu_s_per_sim_hour)}</td>
    </>
  );
}

function ArchiveTable({ rows, history, label }: { rows: ArchiveHistoryEntry[]; history?: boolean; label: string }) {
  if (!rows.length) return <p className="text-xs text-muted">(empty)</p>;
  return (
    <TableWrap label={label}>
      <table className="data">
        <thead>
          <tr>
            <th>Candidate</th>
            <th className="num">scale err</th>
            <th className="num">shape err</th>
            <th className="num">CPU s / sim h</th>
            {history && <th>Admitted</th>}
            {history && <th>Dominated by</th>}
            {history && <th>Behavioural duplicate of</th>}
            <th>Fingerprints</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e, i) => (
            <tr key={e.name + i}>
              <td className="font-medium">{e.name}</td>
              <ObjCells e={e} />
              {history && <td>{e.admitted === undefined ? "—" : e.admitted ? (e.dominated_by ? "yes, later evicted" : "yes") : "no"}</td>}
              {history && <td>{e.dominated_by ?? <span className="text-muted">—</span>}</td>}
              {history && <td>{e.behavioural_duplicate_of ?? <span className="text-muted">—</span>}</td>}
              <td className="font-mono text-[11px] text-muted">{e.fingerprints?.join(" ") ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

export function RealismSection({ poll }: { poll: Poll<RealismResp> }) {
  return (
    <Panel
      id="realism"
      title="Realism track (simulator configurations)"
      subtitle="Multi-objective, paired-by-seed comparison against each incumbent; Pareto archive. The track is allowed to conclude 'not an improvement'."
    >
      <SectionState poll={poll} what="realism track">
        {({ rules, report, archive }) => {
          const incumbents = rules.incumbents ?? [];
          const results = Object.values(report.results ?? {});
          const cols = incumbents.length ? incumbents : ["default"];
          return (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Prov kind="SYNTHETIC" />
                <Prov kind="HISTORICAL TARGETS" />
                <span className="text-xs text-muted">
                  {rules.name} · report {report.protocol ?? "?"} · {fmtTime(report.created_utc)}
                </span>
              </div>
              {report.protocol && rules.name && report.protocol !== rules.name && (
                <ErrorNote error={new Error(`report protocol "${report.protocol}" differs from rules "${rules.name}"`)} what="version mismatch" />
              )}
              {archive.rules_sha256 && report.rules_sha256 && archive.rules_sha256 !== report.rules_sha256 && (
                <ErrorNote error={new Error("archive rules_sha256 differs from report rules_sha256")} what="version mismatch" />
              )}
              <div className="grid grid-cols-1 gap-3 text-xs lg:grid-cols-2">
                <div className="space-y-1">
                  {rules.purpose && <p className="text-ink">{rules.purpose}</p>}
                  <p className="text-ink2">
                    <span className="text-muted">Objectives (all minimised):</span>
                  </p>
                  <ul className="list-disc pl-5 text-ink2">
                    {Object.entries(rules.objectives ?? {}).map(([k, o]) => (
                      <li key={k}>
                        <code className="text-ink">{k}</code>
                        {o.facts && <> — {o.aggregate ?? "mean"} of {o.per_fact} over {o.facts.join(", ")}</>}
                        {rules.dominance?.tolerance?.[k] !== undefined && <span className="text-muted"> (dominance tolerance {fx(rules.dominance.tolerance[k])})</span>}
                      </li>
                    ))}
                  </ul>
                  <p className="text-ink2">
                    <span className="text-muted">Incumbents:</span> {incumbents.join(", ") || "—"} · <span className="text-muted">seeds</span> {rules.seeds?.join(", ")} ·{" "}
                    {fmtAny(rules.duration_s)} s
                  </p>
                  {rules.targets && (
                    <p className="text-ink2">
                      <span className="text-muted">Targets:</span> {rules.targets}
                    </p>
                  )}
                </div>
                <div className="space-y-1">
                  {rules.verdict_rule && (
                    <p className="text-ink2">
                      <span className="text-muted">Verdict rule:</span> {rules.verdict_rule}
                    </p>
                  )}
                  {rules.dominance?.rule && (
                    <p className="text-ink2">
                      <span className="text-muted">Dominance:</span> {rules.dominance.rule}
                    </p>
                  )}
                  {rules.duplicate_rule && (
                    <p className="text-ink2">
                      <span className="text-muted">Duplicates:</span> {rules.duplicate_rule}
                    </p>
                  )}
                  {rules.supersedes?.why?.length ? (
                    <div className="rounded border border-warn/40 bg-warn/5 p-2">
                      <p className="font-semibold text-warn">Supersedes {rules.supersedes.version} because:</p>
                      <ul className="list-disc pl-5 text-ink2">
                        {rules.supersedes.why.map((w) => (
                          <li key={w}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              </div>

              <div>
                <h3 className="mb-1 text-sm font-semibold">Results</h3>
                <TableWrap label="Realism results">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Candidate</th>
                        <th>Overrides</th>
                        <th className="num">scale err</th>
                        <th className="num">shape err</th>
                        <th className="num">CPU s / sim h</th>
                        {cols.map((c) => (
                          <th key={c}>vs {c}</th>
                        ))}
                        <th>Pareto</th>
                      </tr>
                    </thead>
                    <tbody>
                      {results.map((e) => {
                        const vs = verdictsOf(e, incumbents);
                        return (
                          <tr key={e.name}>
                            <td className="font-medium">{e.name}</td>
                            <td className="max-w-[20rem] !whitespace-normal">
                              <Kv data={e.overrides} />
                            </td>
                            <ObjCells e={e} />
                            {cols.map((c) => (
                              <td key={c}>{c === e.name ? <span className="text-[11px] text-muted">(self)</span> : <VerdictBadge v={vs[c]} />}</td>
                            ))}
                            <td>{report.pareto?.includes(e.name) ? <span className="text-up">●</span> : <span className="text-muted">—</span>}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </TableWrap>
                <p className="mt-1 text-[11px] text-muted">
                  Means over seeds; lower is better on every objective. Errors are distances to HISTORICAL TRAIN-day targets in IQR units. Cost: {fmtAny(report.cost?.runs)} runs,{" "}
                  {fx(report.cost?.wall_s)} s wall, {fmtAny(report.cost?.llm_calls)} LLM calls.
                </p>
                <details className="mt-2 text-xs">
                  <summary className="cursor-pointer font-semibold text-ink2">Paired differences per incumbent (candidate − incumbent; negative = better)</summary>
                  <TableWrap label="Realism paired differences">
                    <table className="data mt-1">
                      <thead>
                        <tr>
                          <th>Candidate</th>
                          <th>vs</th>
                          <th>Verdict</th>
                          <th>Better / worse</th>
                          <th>Objective</th>
                          {PAIRED_HEAD}
                        </tr>
                      </thead>
                      <tbody>
                        {results.flatMap((e) =>
                          Object.entries(e.verdict_detail ?? {}).flatMap(([inc, det]) => {
                            if (!det || typeof det !== "object" || !("paired" in det)) return [];
                            const objs = Object.entries(det.paired ?? {});
                            return objs.map(([o, p], i) => (
                              <tr key={`${e.name}|${inc}|${o}`}>
                                {i === 0 && (
                                  <>
                                    <td rowSpan={objs.length} className="align-top font-medium">
                                      {e.name}
                                    </td>
                                    <td rowSpan={objs.length} className="align-top">
                                      {inc}
                                    </td>
                                    <td rowSpan={objs.length} className="align-top">
                                      <VerdictBadge v={det.verdict} />
                                    </td>
                                    <td rowSpan={objs.length} className="align-top text-[11px]">
                                      <span className="text-up">{det.better?.join(", ") || "—"}</span> / <span className="text-down">{det.worse?.join(", ") || "—"}</span>
                                    </td>
                                  </>
                                )}
                                <td className="font-mono text-[11px]">{o}</td>
                                <PairedCells p={p} />
                              </tr>
                            ));
                          }),
                        )}
                      </tbody>
                    </table>
                  </TableWrap>
                </details>
              </div>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <div>
                  <h3 className="mb-1 text-sm font-semibold">Pareto archive ({archive.pareto?.length ?? 0})</h3>
                  <ArchiveTable rows={archive.pareto ?? []} label="Pareto archive" />
                </div>
                <div>
                  <h3 className="mb-1 text-sm font-semibold">History — evicted or not admitted ({archive.history?.length ?? 0})</h3>
                  <ArchiveTable rows={archive.history ?? []} history label="Archive history" />
                </div>
              </div>
              <p className="flex flex-wrap items-center gap-1 text-[11px] text-muted">
                Rules sha256 — report <Hash v={report.rules_sha256} n={12} /> · archive <Hash v={archive.rules_sha256} n={12} />
              </p>
            </div>
          );
        }}
      </SectionState>
    </Panel>
  );
}

/* ================================================================ f. how to read */

const FALLBACK_LABELS: Record<string, string> = {
  "interaction-dependent": "the metric changes when an interaction channel is removed (paired CI excludes 0) while the population is unchanged",
  "programmed/common-input": "the metric is reproduced without the interaction channel, i.e. explained by individual rules reacting to shared inputs",
  association: "observed together but no ablation isolates the channel; no causal claim",
  inconclusive: "CI includes 0 at n=4",
};

export function HowToRead({ labels }: { labels?: Record<string, string> }) {
  const l = labels && Object.keys(labels).length ? labels : FALLBACK_LABELS;
  return (
    <Panel id="how-to-read" title="How to read this">
      <div className="grid grid-cols-1 gap-4 text-xs lg:grid-cols-2">
        <div>
          <h3 className="mb-1 font-semibold text-ink2">Labels for collective properties (from the frozen protocol)</h3>
          <dl className="space-y-1">
            {Object.entries(l).map(([k, v]) => (
              <div key={k}>
                <dt className="inline font-mono font-semibold text-ink">{k}</dt>
                <dd className="inline text-ink2"> — {v}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="space-y-1 text-ink2">
          <h3 className="mb-1 font-semibold">Verdict colours</h3>
          <p className="flex flex-wrap gap-1">
            <VerdictBadge v="supported" /> <VerdictBadge v="weak (bootstrap only)" /> <VerdictBadge v="not supported" /> <VerdictBadge v="refuted" />
          </p>
          <p className="flex flex-wrap gap-1">
            <VerdictBadge v="improvement" /> <VerdictBadge v="trade-off" /> <VerdictBadge v="not an improvement" />
          </p>
          <p>
            Paired effects are treatment − control on the same seed. The bootstrap CI (n = 4) is bounded by the min/max paired difference; per amendment 1, a CI-based hypothesis is
            &quot;supported&quot; only if both the bootstrap CI and the t-interval exclude 0. Intervals shown in muted grey include 0.
          </p>
          <p>Everything here is produced by the synthetic simulator. Historical data enters only as TRAIN-day targets; no holdout data, no trading claims.</p>
        </div>
      </div>
    </Panel>
  );
}
