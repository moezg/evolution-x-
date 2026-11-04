"use client";
import { Fragment, type ReactNode } from "react";
import { EmptyState, ErrorNote, JsonTable, Kpi, Panel } from "@/components/ui";
import { Kv, TableWrap, TONE_CLS } from "@/components/observatory";
import { Hash } from "@/components/research";
import { ApiError } from "@/lib/api";
import { fmtAny, fmtTime, num, usd } from "@/lib/format";
import type { Poll } from "@/lib/hooks";
import {
  CAPABILITY_CLASSES,
  type CArmyResp,
  type CEvolutionResp,
  FINDING_META_KEYS,
  type CFinding,
  type PeriodRow,
  type CForecast,
  type CForecastsResp,
  type COpsResp,
  type COrigin,
  type CQuantResp,
  type CReliabilityResp,
  type CalibrationStudy,
  type EventFollowup,
  type LedgerVerify,
  type SpecialistSession,
  type WilsonRate,
} from "@/lib/control";

/* ================================================================ primitives */

type Tone = keyof typeof TONE_CLS;

const GOOD = /^(ok|up|succeeded|success|running|passed|gates_passed|valid|true)$/;
const BAD = /(fail|down|rejected|refuted|not_supported|error|broken|dead|quarantin)/;
const WARN = /(pending|degraded|inconclusive|review|retry|stale|paused|warn|challenger|queued)/;

function toneOf(s: string): Tone {
  const k = s.toLowerCase();
  if (BAD.test(k)) return "bad";
  if (GOOD.test(k)) return "good";
  if (WARN.test(k)) return "weak";
  return "neutral";
}

/** Status pill. Text is the persisted status verbatim (underscores as spaces); colour is a reading aid only. */
export function Tag({ s, tone, title }: { s: string | null | undefined; tone?: Tone; title?: string }) {
  if (!s) return <span className="text-[11px] text-muted">—</span>;
  return (
    <span
      title={title}
      className={`inline-block max-w-full rounded-full border px-2 py-0.5 text-[11px] font-semibold [overflow-wrap:anywhere] ${TONE_CLS[tone ?? toneOf(s)]}`}
    >
      {s.replace(/_/g, " ")}
    </span>
  );
}

function Banner({ tone, title, children }: { tone: Tone; title: ReactNode; children?: ReactNode }) {
  const head = tone === "bad" ? "text-[#f3a7a7]" : tone === "weak" ? "text-warn" : tone === "good" ? "text-up" : tone === "info" ? "text-[#9ec5f4]" : "text-ink2";
  const box =
    tone === "bad"
      ? "border-down/50 bg-down/10"
      : tone === "weak"
        ? "border-warn/50 bg-warn/10"
        : tone === "good"
          ? "border-up/50 bg-up/10"
          : tone === "info"
            ? "border-accent/50 bg-accent/10"
            : "border-line2 bg-panel2";
  return (
    <div className={`rounded-md border p-3 text-xs ${box}`}>
      <p className={`font-bold uppercase tracking-wider ${head}`}>{title}</p>
      {children && <div className="mt-1 text-ink2 [overflow-wrap:anywhere]">{children}</div>}
    </div>
  );
}

function Sub({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2 mt-5 flex flex-wrap items-baseline justify-between gap-2 first:mt-0">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-ink2">{children}</h3>
      {right}
    </div>
  );
}

function Na({ children = "not available" }: { children?: ReactNode }) {
  return <span className="text-muted italic">{children}</span>;
}

function N({ v, d = 4 }: { v: unknown; d?: number }) {
  if (typeof v !== "number" || !Number.isFinite(v)) return <Na>—</Na>;
  return <span className="tnum">{num(v, d)}</span>;
}

/** p-values span many orders of magnitude; never round them to 0. */
function P({ v }: { v: unknown }) {
  if (typeof v !== "number" || !Number.isFinite(v)) return <Na>—</Na>;
  return <span className="tnum">{v < 1e-3 ? v.toExponential(2) : v.toFixed(4)}</span>;
}

function pct1(v: number | null | undefined, d = 1): string {
  return typeof v === "number" && Number.isFinite(v) ? `${(v * 100).toFixed(d)}%` : "—";
}

/** "rate [lo, hi] (k/n)" with the Wilson 95% interval exactly as persisted. */
function Rate({ r }: { r: WilsonRate | undefined }) {
  if (!r) return <Na>—</Na>;
  return (
    <span className="tnum">
      <span className="font-semibold text-ink">{pct1(r.rate)}</span>{" "}
      <span className="text-muted">
        [{pct1(r.wilson95?.[0])}, {pct1(r.wilson95?.[1])}]
      </span>{" "}
      <span className="text-[11px] text-muted">
        ({r.k}/{r.n})
      </span>
    </span>
  );
}

function Progress({ value, max, tone = "info", label }: { value: number; max: number; tone?: "info" | "weak" | "good" | "bad"; label: string }) {
  const frac = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const bar = tone === "good" ? "bg-up" : tone === "weak" ? "bg-warn" : tone === "bad" ? "bg-down" : "bg-accent";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-line" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
      <div className={`h-full ${bar}`} style={{ width: `${frac * 100}%` }} />
    </div>
  );
}

function Details({ summary, children, open = false }: { summary: ReactNode; children: ReactNode; open?: boolean }) {
  return (
    <details open={open} className="group mt-2 rounded-md border border-line">
      <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-ink2 hover:text-ink">{summary}</summary>
      <div className="border-t border-line p-2">{children}</div>
    </details>
  );
}

/** Loading / error wrapper; an error only affects its own section. */
export function CState<T>({ poll, what, children }: { poll: Poll<T>; what: string; children: (d: T) => ReactNode }) {
  if (poll.data)
    return (
      <>
        {poll.error && <ErrorNote error={poll.error} what={`${what} (showing last good data)`} />}
        {children(poll.data)}
      </>
    );
  if (poll.error instanceof ApiError && poll.error.status === 404)
    return (
      <EmptyState title={`${what}: not available`}>
        <p>{poll.error.detail}</p>
      </EmptyState>
    );
  if (poll.error) return <ErrorNote error={poll.error} what={what} />;
  return <p className="text-xs text-muted">Loading {what}…</p>;
}

function ageText(s: number | null | undefined): string {
  if (typeof s !== "number" || !Number.isFinite(s)) return "unknown";
  if (s < 90) return `${Math.round(s)} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${(s / 3600).toFixed(1)} h ago`;
  return `${(s / 86400).toFixed(1)} d ago`;
}

function VerifyLine({ v }: { v: LedgerVerify | undefined | null }) {
  if (!v) return <Na>ledger verification not available</Na>;
  return (
    <span className="flex flex-wrap items-center gap-2 text-xs">
      <Tag s={v.ok ? "hash chain verified" : "hash chain BROKEN"} tone={v.ok ? "good" : "bad"} />
      <span className="text-muted">
        {fmtAny(v.entries)} entries · head <Hash v={v.head ?? undefined} n={12} label="ledger head" />
      </span>
      {v.error ? <span className="text-[#f3a7a7]">{String(v.error)}</span> : null}
    </span>
  );
}

/* ================================================================ 1 · live forecasts */

function ForecastCell({ f }: { f: CForecast | undefined }) {
  if (!f) return <span className="text-muted">—</span>;
  const tip = `id ${f.id} · issued ${fmtTime(f.issued_utc)} · model_version ${f.model_version ?? "—"}`;
  return (
    <div title={tip} className="min-w-[7rem]">
      {f.abstained ? (
        <>
          <Tag s="abstained" tone="weak" />
          <div className="mt-0.5 text-[11px] text-ink2">{f.abstain_reason ? f.abstain_reason.replace(/_/g, " ") : "no reason recorded"}</div>
          <div className="text-[11px] text-muted">
            model value <N v={f.value} /> · scored as <N v={f.scored_value} />
          </div>
        </>
      ) : (
        <span className="font-semibold text-ink">
          <N v={f.value} />
        </span>
      )}
      <div className="text-[11px] text-muted">{f.resolved ? <>resolved · outcome {fmtAny(f.outcome)}</> : "open"}</div>
    </div>
  );
}

const ROLE_ORDER = ["champion", "challenger", "baseline", "alternative"];
function roleRank(r: string): number {
  const i = ROLE_ORDER.indexOf(r);
  return i < 0 ? ROLE_ORDER.length : i;
}
function isRef(r: string): boolean {
  return r === "baseline" || r === "alternative";
}

function RoleTag({ role }: { role: string }) {
  if (role === "champion") return <Tag s="champion" tone="info" />;
  if (role === "challenger") return <Tag s="challenger (not promoted)" tone="weak" />;
  if (isRef(role)) return <Tag s={`${role} · reference`} tone="neutral" />;
  return <Tag s={role} tone="neutral" />;
}

function OriginTable({ o }: { o: COrigin }) {
  const models = Array.from(new Map(o.forecasts.map((f) => [f.model, f.role])).entries()).sort(
    (a, b) => roleRank(a[1]) - roleRank(b[1]) || a[0].localeCompare(b[0]),
  );
  const targets = Array.from(new Set(o.forecasts.map((f) => f.target))).sort();
  const cell = (t: string, m: string) => o.forecasts.find((f) => f.target === t && f.model === m);
  const issued = Array.from(new Set(o.forecasts.map((f) => `${f.role}|${f.issued_utc}`)))
    .map((x) => x.split("|"))
    .sort((a, b) => roleRank(a[0]) - roleRank(b[0]) || a[1].localeCompare(b[1]));
  return (
    <>
      <TableWrap label={`Forecasts for origin ${o.origin_utc}`}>
        <table className="data">
          <thead>
            <tr>
              <th>Target</th>
              {models.map(([m, role]) => (
                <th key={m} className={`!align-bottom ${isRef(role) ? "opacity-75" : ""}`}>
                  <div className="!normal-case">{m}</div>
                  <div className="mt-0.5 font-normal !normal-case">
                    <RoleTag role={role} />
                  </div>
                </th>
              ))}
              <th>Window end</th>
              <th className="num">Resolved</th>
            </tr>
          </thead>
          <tbody>
            {targets.map((t) => {
              const rows = o.forecasts.filter((f) => f.target === t);
              const ends = Array.from(new Set(rows.map((f) => f.window_end_utc)));
              const res = rows.filter((f) => f.resolved).length;
              return (
                <tr key={t}>
                  <td className="align-top font-mono text-xs font-semibold">{t}</td>
                  {models.map(([m, role]) => (
                    <td key={m} className={`align-top ${isRef(role) ? "opacity-75" : ""}`}>
                      <ForecastCell f={cell(t, m)} />
                    </td>
                  ))}
                  <td className="align-top text-xs">{ends.map((e) => fmtTime(e)).join(", ")}</td>
                  <td className="num align-top text-xs">
                    {res}/{rows.length}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableWrap>
      <p className="mt-2 text-[11px] text-muted">
        Issued:{" "}
        {issued.map(([role, t], i) => (
          <Fragment key={i}>
            {i > 0 && " · "}
            {role} {fmtTime(t)}
          </Fragment>
        ))}
        . Champion and challenger first; baselines and alternatives are shown for reference. Values are the persisted forecast values (probabilities for move/up targets, forecast realized volatility for rv targets). An abstained forecast is scored with
        the recorded fallback value.
      </p>
      <Details summary={`All ${o.forecasts.length} ledger rows for this origin (versions, snapshots)`}>
        <TableWrap label="Ledger rows">
          <table className="data">
            <thead>
              <tr>
                <th>Target</th>
                <th>Model</th>
                <th>Role</th>
                <th className="num">Value</th>
                <th className="num">Scored</th>
                <th>Abstained</th>
                <th>Issued</th>
                <th>Model version</th>
                <th>Feature version</th>
                <th>Snapshot</th>
                <th>Outcome</th>
                <th>ID</th>
              </tr>
            </thead>
            <tbody>
              {o.forecasts.map((f) => (
                <tr key={f.id}>
                  <td className="font-mono text-xs">{f.target}</td>
                  <td className="font-mono text-xs">{f.model}</td>
                  <td>
                    <RoleTag role={f.role} />
                  </td>
                  <td className="num">
                    <N v={f.value} />
                  </td>
                  <td className="num">
                    <N v={f.scored_value} />
                  </td>
                  <td className="text-xs">{f.abstained ? `yes · ${f.abstain_reason ?? "no reason recorded"}` : "no"}</td>
                  <td className="text-xs">{fmtTime(f.issued_utc)}</td>
                  <td>
                    <Hash v={f.model_version} n={18} />
                  </td>
                  <td>{f.feature_version ? <Hash v={f.feature_version} n={14} /> : <Na>not recorded</Na>}</td>
                  <td>{f.snapshot_sha256 ? <Hash v={f.snapshot_sha256} n={12} /> : <Na>not recorded</Na>}</td>
                  <td className="text-xs">{f.resolved ? fmtAny(f.outcome) : <Na>open</Na>}</td>
                  <td>
                    <Hash v={f.id} n={16} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </Details>
    </>
  );
}

export function LiveForecasts({ poll }: { poll: Poll<CForecastsResp> }) {
  return (
    <Panel id="forecasts" title="1 · Live Forecasts" subtitle="Prospective forecasts from the append-only, hash-chained ledger (GET /api/control/forecasts)">
      <CState poll={poll} what="forecast ledger">
        {(d) => {
          const latest = d.origins[0];
          const older = d.origins.slice(1);
          const ev = Object.entries(d.evidence ?? {});
          const all = d.origins.flatMap((o) => o.forecasts);
          return (
            <div className="space-y-3">
              {!d.sufficient_prospective_evidence && (
                <Banner tone="weak" title="Insufficient prospective evidence">
                  No target has reached the {ev[0]?.[1].required_for_promotion ?? 180} resolved prospective forecasts required for promotion. No skill or accuracy is
                  claimed for any model below.
                </Banner>
              )}
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Kpi label="Ledger" value={d.verify?.ok ? "verified" : "BROKEN"} tone={d.verify?.ok ? "up" : "down"} sub={`${fmtAny(d.verify?.entries)} entries`} />
                <Kpi label="Forecasts issued" value={fmtAny(d.verify?.forecasts ?? all.length)} sub={`${d.origins.length} origin(s)`} />
                <Kpi label="Resolved" value={fmtAny(d.verify?.resolved ?? all.filter((f) => f.resolved).length)} sub="from official data" />
                <Kpi label="Missed windows" value={fmtAny(d.missed.length)} tone={d.missed.length ? "warn" : undefined} />
              </div>
              <VerifyLine v={d.verify} />

              <Sub right={latest && <span className="text-[11px] text-muted">lag {latest.lag_h != null ? `${latest.lag_h} h` : "not recorded"}</span>}>
                {latest ? `Latest origin · ${fmtTime(latest.origin_utc)}` : "Latest origin"}
              </Sub>
              {latest ? <OriginTable o={latest} /> : <EmptyState title="No forecasts in the ledger yet" />}
              {older.length > 0 && (
                <Details summary={`${older.length} earlier origin(s)`}>
                  <div className="space-y-4">
                    {older.map((o) => (
                      <div key={o.origin_utc}>
                        <p className="mb-1 text-xs font-semibold text-ink2">
                          Origin {fmtTime(o.origin_utc)} · lag {o.lag_h != null ? `${o.lag_h} h` : "not recorded"}
                        </p>
                        <OriginTable o={o} />
                      </div>
                    ))}
                  </div>
                </Details>
              )}

              <Sub>Missed windows</Sub>
              {d.missed.length === 0 ? (
                <p className="text-xs text-ink2">None recorded.</p>
              ) : (
                <TableWrap label="Missed windows">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Origin</th>
                        <th>Reason</th>
                        <th>Recorded</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.missed.map((m, i) => (
                        <tr key={i}>
                          <td className="text-xs">{fmtTime(m.origin_utc)}</td>
                          <td className="!whitespace-normal text-xs">{m.reason}</td>
                          <td className="text-xs">{fmtTime(m.recorded_utc)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              )}

              <Sub>Prospective evidence per target</Sub>
              {ev.length === 0 ? (
                <p className="text-xs text-muted">No targets in the ledger.</p>
              ) : (
                <ul className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
                  {ev.map(([t, e]) => {
                    const ok = e.resolved >= e.required_for_promotion;
                    return (
                      <li key={t} className="min-w-0">
                        <div className="flex items-baseline justify-between gap-2 text-xs">
                          <span className="font-mono font-semibold">{t}</span>
                          <span className="tnum text-ink2">
                            resolved {e.resolved} / {e.required_for_promotion} required
                          </span>
                        </div>
                        <Progress value={e.resolved} max={e.required_for_promotion} tone={ok ? "good" : "weak"} label={`${t} resolved forecasts`} />
                        {!ok && <p className="mt-0.5 text-[11px] text-warn">insufficient prospective evidence</p>}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        }}
      </CState>
    </Panel>
  );
}

/* ================================================================ 2 · reliability */

function CalibrationView({ c }: { c: CalibrationStudy }) {
  const gens = Object.keys(c.null ?? {});
  const metrics = Array.from(new Set(gens.flatMap((g) => Object.keys(c.null?.[g]?.per_metric ?? {}))));
  const fams = Array.from(new Set(gens.flatMap((g) => Object.keys(c.null?.[g]?.per_family ?? {}))));
  const q = c.quarantine;
  const qObj = q && typeof q === "object" ? q : undefined;
  const power = Object.entries(c.power ?? {});
  return (
    <div className="space-y-3">
      <p className="text-xs text-ink2">
        Protocol <code>{c.protocol ?? "—"}</code> · {fmtAny(c.n_rotations)} rotations · started {fmtTime(c.started_utc)} · finished{" "}
        {c.finished_utc ? fmtTime(c.finished_utc) : <Na>not finished</Na>} · protocol sha256 <Hash v={c.protocol_sha256} n={16} label="protocol sha256" />
      </p>
      {c.label && <Banner tone="info" title={c.label} />}
      {c.smoke_test_not_registered && (
        <Banner tone="bad" title="Smoke test — not the registered study">
          This record was produced with fewer seeds than the protocol requires and is not used for quarantine decisions.
        </Banner>
      )}
      <p className="text-[11px] text-muted">Rates show Wilson 95% intervals [lower, upper] and (k/n runs).</p>
      {gens.length === 0 ? (
        <p className="text-xs text-muted">No null-generator results in the study record.</p>
      ) : (
        <>
          <TableWrap label="False-positive rate per generator">
            <table className="data">
              <thead>
                <tr>
                  <th>Null generator</th>
                  <th className="num">Runs</th>
                  <th className="num">Tests / run</th>
                  <th>Any false &lsquo;supported&rsquo; per run</th>
                  <th className="num">False supported (total)</th>
                  <th className="num">Mean BH survivors / run</th>
                </tr>
              </thead>
              <tbody>
                {gens.map((g) => {
                  const s = c.null![g];
                  return (
                    <tr key={g}>
                      <td className="font-mono text-xs">{g}</td>
                      <td className="num">{fmtAny(s.runs)}</td>
                      <td className="num">{fmtAny(s.tests_per_run)}</td>
                      <td>
                        <Rate r={s.any_false_supported} />
                      </td>
                      <td className="num">{fmtAny(s.false_supported_total)}</td>
                      <td className="num">
                        <N v={s.mean_bh_survivors_per_run} d={2} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
          <Sub>False-positive rate per metric (runs with ≥1 false &lsquo;supported&rsquo; on that metric)</Sub>
          <TableWrap label="False-positive rate per metric">
            <table className="data">
              <thead>
                <tr>
                  <th>Metric</th>
                  {gens.map((g) => (
                    <th key={g} className="!normal-case">
                      {g}
                    </th>
                  ))}
                  <th>Quarantine</th>
                </tr>
              </thead>
              <tbody>
                {metrics.map((m) => {
                  const qm = qObj?.[m];
                  return (
                    <tr key={m} className={qm?.quarantined ? "bg-down/10" : undefined}>
                      <td className="font-mono text-xs">{m}</td>
                      {gens.map((g) => (
                        <td key={g}>
                          <Rate r={c.null![g].per_metric?.[m]} />
                        </td>
                      ))}
                      <td className="!whitespace-normal min-w-[12rem]">
                        {qm ? (
                          <>
                            <Tag s={qm.quarantined ? "quarantined" : "not quarantined"} tone={qm.quarantined ? "bad" : "good"} />
                            {qm.reasons?.length > 0 && (
                              <ul className="mt-1 list-disc pl-4 text-[11px] text-ink2">
                                {qm.reasons.map((r, i) => (
                                  <li key={i}>{r}</li>
                                ))}
                              </ul>
                            )}
                          </>
                        ) : (
                          <Na>{typeof q === "string" ? q : "no decision recorded"}</Na>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
          {fams.length > 0 && (
            <>
              <Sub>False-positive rate per family</Sub>
              <TableWrap label="False-positive rate per family">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Family</th>
                      {gens.map((g) => (
                        <th key={g} className="!normal-case">
                          {g}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {fams.map((f) => (
                      <tr key={f}>
                        <td className="font-mono text-xs">{f}</td>
                        {gens.map((g) => (
                          <td key={g}>
                            <Rate r={c.null![g].per_family?.[f]} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            </>
          )}
        </>
      )}
      <Sub>Power on planted day-14 effects (detection rate)</Sub>
      {power.length === 0 ? (
        <p className="text-xs text-muted">No power results in the study record.</p>
      ) : (
        <TableWrap label="Power per planted effect size">
          <table className="data">
            <thead>
              <tr>
                <th>Planted effect</th>
                <th>Size</th>
                <th>Detection rate [Wilson 95%] (k/n)</th>
                <th className="num">Runs with other false &lsquo;supported&rsquo;</th>
              </tr>
            </thead>
            <tbody>
              {power.map(([k, r]) => {
                const [kind, size] = k.split(":");
                return (
                  <tr key={k}>
                    <td className="text-xs">{kind === "mean" ? "mean shift (× unconditional sd)" : kind === "vol" ? "volatility scale" : kind}</td>
                    <td className="tnum">{size ?? "—"}</td>
                    <td>
                      <Rate r={r} />
                    </td>
                    <td className="num">{fmtAny(r.runs_with_other_false_supported)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
      )}
    </div>
  );
}

export function Reliability({ poll }: { poll: Poll<CReliabilityResp> }) {
  return (
    <Panel id="reliability" title="2 · Prediction Reliability" subtitle="Prospective scores, drift and the decision-rule calibration study (GET /api/control/reliability)">
      <CState poll={poll} what="reliability">
        {(d) => {
          const ps = d.prospective_scores;
          const scores = Object.entries(ps?.scores ?? {});
          const dr = d.drift;
          const driftStatus = Object.entries(dr?.status ?? {});
          return (
            <div className="space-y-3">
              <Sub right={ps?.label && <Tag s={ps.label} tone="info" />}>Prospective scores</Sub>
              {!ps ? (
                <Banner tone="neutral" title="Prospective status not available">
                  The prospective status record has not been produced. Reliability is unknown.
                </Banner>
              ) : scores.length === 0 || ps.resolved === 0 ? (
                <Banner tone="weak" title="No resolved forecasts yet — reliability unknown">
                  {fmtAny(ps.resolved)} resolved · {fmtAny(ps.open)} open. {d.note ?? ""}
                </Banner>
              ) : (
                <>
                  <p className="text-xs text-ink2">
                    {fmtAny(ps.resolved)} resolved · {fmtAny(ps.open)} open. Scores are computed only on resolved prospective forecasts.
                  </p>
                  <JsonTable value={ps.scores} />
                </>
              )}

              <Sub>Drift</Sub>
              {!dr ? (
                <p className="text-xs text-muted">Drift check not available.</p>
              ) : (
                <div className="space-y-2 text-xs">
                  {dr.resolved < dr.min_resolved_for_assessment ? (
                    <Banner tone="neutral" title="Drift not assessable">
                      {dr.resolved} resolved forecasts &lt; {dr.min_resolved_for_assessment} required for a drift assessment. No drift status is reported.
                    </Banner>
                  ) : driftStatus.length === 0 ? (
                    <p className="text-muted">No per-target drift status recorded.</p>
                  ) : (
                    <JsonTable value={dr.status} />
                  )}
                  <p className="text-ink2">
                    Alerts:{" "}
                    {dr.alerts.length === 0 ? (
                      "none"
                    ) : (
                      <span className="text-[#f3a7a7]">{dr.alerts.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" · ")}</span>
                    )}
                  </p>
                </div>
              )}

              <Sub>Calibration study of the discovery decision rule</Sub>
              {d.calibration_study ? (
                <CalibrationView c={d.calibration_study} />
              ) : (
                <EmptyState title="Calibration study not yet available">
                  <p>No completed study record exists yet (a full registered run may still be in progress). False-positive rates and quarantine decisions are unknown.</p>
                </EmptyState>
              )}
            </div>
          );
        }}
      </CState>
    </Panel>
  );
}

/* ================================================================ 3 · research army */

function SessionView({ s }: { s: SpecialistSession }) {
  const cost = s.steps.reduce((a, x) => a + (typeof x.cost === "number" ? x.cost : 0), 0);
  const llmSteps = s.steps.filter((x) => x.used_llm).length;
  return (
    <div className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <code className="text-xs font-semibold text-ink">{s.session}</code>
        <span className="text-[11px] text-muted">
          {s.steps.length} steps · {llmSteps} with LLM · {usd(cost, 3)} API-equivalent
        </span>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <TableWrap label="Session steps">
          <table className="data">
            <thead>
              <tr>
                <th>Role</th>
                <th>LLM</th>
                <th className="num">Cost</th>
                <th>Valid</th>
              </tr>
            </thead>
            <tbody>
              {s.steps.map((x, i) => (
                <tr key={i}>
                  <td className="font-mono text-xs">{x.role}</td>
                  <td className="text-xs">{x.used_llm === null ? "—" : x.used_llm ? "used" : "no"}</td>
                  <td className="num text-xs">{typeof x.cost === "number" ? usd(x.cost, 4) : "—"}</td>
                  <td className="text-xs">{x.valid === null ? <Na>not checked</Na> : x.valid ? "yes" : <span className="text-[#f3a7a7]">no</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        <div className="min-w-0">
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Proposal verdicts</p>
          {s.proposals.length === 0 ? (
            <p className="text-xs text-muted">No proposals.</p>
          ) : (
            <ul className="space-y-1.5">
              {s.proposals.map((p, i) => (
                <li key={i} className="text-xs">
                  <span className="mr-2 font-medium text-ink">{p.by}</span>
                  <Tag s={p.status} />
                  {p.reasons?.length ? <div className="mt-0.5 text-[11px] text-ink2 [overflow-wrap:anywhere]">{p.reasons.join(" · ")}</div> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      {(s.revalidations ?? []).map((r, i) => (
        <div key={i} className="mt-3 rounded border border-warn/40 bg-warn/5 p-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-warn">Revalidation · {fmtTime(r.utc)}</p>
          <p className="mt-0.5 text-xs text-ink2 [overflow-wrap:anywhere]">{r.reason}</p>
          <ul className="mt-1.5 space-y-1">
            {r.results.map((x, j) => (
              <li key={j} className="text-xs">
                <span className="mr-2 font-medium">{x.by}</span>
                <Tag s={x.original} tone="neutral" /> <span className="text-muted">→</span> <Tag s={x.now?.status} />
                {x.original !== x.now?.status && <span className="ml-2 text-[11px] font-semibold text-warn">verdict changed</span>}
                {x.now?.key && (
                  <div className="text-[11px] text-muted [overflow-wrap:anywhere]">
                    key <code>{x.now.key}</code>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {s.lineage && (
        <p className="mt-2 text-[11px] text-muted [overflow-wrap:anywhere]">
          Lineage: sources {(s.lineage.sources ?? []).join(", ") || "—"} · tests cited {(s.lineage.tests_cited ?? []).join(", ") || "—"}
          {s.lineage.journal ? <> · journal {s.lineage.journal}</> : null}
        </p>
      )}
    </div>
  );
}

export function ResearchArmy({ poll }: { poll: Poll<CArmyResp> }) {
  return (
    <Panel id="army" title="3 · Research Army" subtitle="Roles, what they actually are, measured work and cost (GET /api/control/army)">
      <CState poll={poll} what="research army">
        {(d) => {
          const byId = new Map(d.value.roles.map((r) => [r.role, r]));
          const counts = new Map<string, number>();
          for (const r of d.roles) {
            const k = r.class?.class ?? "unclassified";
            counts.set(k, (counts.get(k) ?? 0) + 1);
          }
          const classes = [...CAPABILITY_CLASSES, ...Array.from(counts.keys()).filter((k) => !(CAPABILITY_CLASSES as readonly string[]).includes(k))];
          const tot = d.value.roles.reduce(
            (a, r) => ({ tasks: a.tasks + (r.tasks || 0), llm: a.llm + (r.llm_calls || 0), usd: a.usd + (r.llm_usd_api_equiv || 0), wall: a.wall + (r.wall_s || 0) }),
            { tasks: 0, llm: 0, usd: 0, wall: 0 },
          );
          const dd = d.value.dedup_with_without;
          return (
            <div className="space-y-3">
              <Sub>{d.roles.length} roles by capability class</Sub>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                {classes.map((c) => (
                  <Kpi key={c} label={c.replace(/_/g, " ")} value={counts.get(c) ?? 0} />
                ))}
              </div>
              <p className="text-xs text-ink2">
                Recorded totals: {fmtAny(tot.tasks)} tasks · {fmtAny(tot.llm)} LLM calls · {usd(tot.usd, 3)} API-equivalent · {num(tot.wall, 1)} s wall time.
              </p>

              <Sub>Roles</Sub>
              <TableWrap label="Research army roles">
                <table className="data">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Role</th>
                      <th>Class</th>
                      <th>LLM usage</th>
                      <th className="num">Tasks</th>
                      <th className="num">LLM calls</th>
                      <th className="num">Cost (API-eq.)</th>
                      <th className="num">Wall s</th>
                      <th>Contributions</th>
                      <th>Flag</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.roles.map((r) => {
                      const v = byId.get(r.id);
                      return (
                        <tr key={r.id}>
                          <td className={`align-top font-mono text-xs font-semibold ${d.value.flagged.includes(r.id) ? "text-warn" : ""}`}>{r.id}</td>
                          <td className="!whitespace-normal min-w-[11rem] align-top text-xs">
                            <div className="text-ink">{r.title}</div>
                            <div className="text-[11px] text-muted">{r.division}</div>
                          </td>
                          <td className="align-top">{r.class ? <Tag s={r.class.class} tone="neutral" /> : <Na>unclassified</Na>}</td>
                          <td className="!whitespace-normal min-w-[12rem] align-top text-[11px] text-ink2" title={r.class?.runs}>
                            {r.class?.llm ?? <Na />}
                          </td>
                          <td className="num align-top">
                            {v ? fmtAny(v.tasks) : <Na>—</Na>}
                            {v?.failed ? <div className="text-[11px] text-[#f3a7a7]">{v.failed} failed</div> : null}
                          </td>
                          <td className="num align-top">{v ? fmtAny(v.llm_calls) : "—"}</td>
                          <td className="num align-top">{v ? usd(v.llm_usd_api_equiv, 3) : "—"}</td>
                          <td className="num align-top">{v ? num(v.wall_s, 1) : "—"}</td>
                          <td className="!whitespace-normal min-w-[14rem] align-top">{v ? <Kv data={v.contributions} /> : <Na>no record</Na>}</td>
                          <td className="align-top">{v?.flag ? <Tag s={v.flag} tone="weak" /> : <span className="text-muted">—</span>}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableWrap>
              <p className="text-xs text-ink2">
                Flagged roles: {d.value.flagged.length === 0 ? "none" : d.value.flagged.join(", ")}.{" "}
                {d.value.policy && <span className="text-muted">{d.value.policy}</span>}
              </p>

              <Sub>Specialist sessions</Sub>
              {d.specialist_sessions.length === 0 ? (
                <p className="text-xs text-muted">No specialist sessions recorded.</p>
              ) : (
                <div className="space-y-3">
                  {d.specialist_sessions.map((s) => (
                    <SessionView key={s.session} s={s} />
                  ))}
                </div>
              )}

              <Sub right={<Tag s="estimate" tone="weak" />}>Duplicate filter (A4): with vs without</Sub>
              {!dd ? (
                <p className="text-xs text-muted">No dedup comparison recorded.</p>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-ink2">
                    Duplicates stopped with A4: <span className="font-semibold text-ink">{fmtAny(dd.duplicates_stopped_with_A4)}</span> · A4 measured cost{" "}
                    {num(dd.A4_cost_measured_wall_s, 2)} s · measured chain cost per candidate {num(dd.measured_chain_wall_s_per_candidate, 2)} s
                  </p>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <div className="rounded-md border border-line p-2">
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">With A4 (measured)</p>
                      <Kv data={dd.with_A4} />
                    </div>
                    <div className="rounded-md border border-dashed border-warn/50 p-2">
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-warn">Without A4 (estimate, not re-run)</p>
                      <Kv data={dd.without_A4_estimate} />
                    </div>
                  </div>
                  {dd.label && <p className="text-[11px] text-muted">{dd.label}</p>}
                </div>
              )}
            </div>
          );
        }}
      </CState>
    </Panel>
  );
}

/* ================================================================ 4 · quantitative discoveries */

function PeriodCell({ r, missing }: { r: PeriodRow | undefined; missing: string }) {
  if (!r) return <Na>{missing}</Na>;
  const ci = typeof r.ci_lo === "number" && typeof r.ci_hi === "number";
  return (
    <div className="min-w-[11rem] text-xs" title={r.id}>
      <div>
        <span className="text-muted">effect </span>
        <span className="font-semibold text-ink">
          <N v={r.effect} d={4} />
        </span>
        {ci && (
          <span className="text-muted">
            {" "}
            [<N v={r.ci_lo} d={4} />, <N v={r.ci_hi} d={4} />]
          </span>
        )}
      </div>
      <div className="text-[11px] text-ink2">
        n {fmtAny(r.n)} · p <P v={r.p} /> · p adj. <P v={r.p_adj} />
      </div>
    </div>
  );
}

function FindingsTable({ rows, label }: { rows: CFinding[]; label: string }) {
  if (rows.length === 0) return <p className="text-xs text-muted">None.</p>;
  const extra = Array.from(
    new Set(rows.flatMap((f) => Object.keys(f).filter((k) => !FINDING_META_KEYS.includes(k) && k !== "discovery" && k !== "confirmation"))),
  ).sort();
  return (
    <TableWrap label={label}>
      <table className="data">
        <thead>
          <tr>
            <th>Hypothesis</th>
            <th>Status</th>
            <th>Discovery</th>
            <th>Confirmation</th>
            {extra.map((k) => (
              <th key={k}>{k}</th>
            ))}
            <th>Metric</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => (
            <tr key={f.hypothesis} className={f.quarantined_metric ? "bg-down/10" : undefined}>
              <td className="align-top">
                <div className="font-mono text-xs">{f.hypothesis}</div>
                {f.run_id && <div className="text-[11px] text-muted">run {f.run_id}</div>}
              </td>
              <td className="align-top">{f.status === "supported" ? <Tag s="supported · exploratory" tone="weak" /> : <Tag s={f.status} tone="neutral" />}</td>
              <td className="align-top">
                <PeriodCell r={f.discovery} missing="no discovery row" />
              </td>
              <td className="align-top">
                <PeriodCell r={f.confirmation} missing="not run (no confirmation row)" />
              </td>
              {extra.map((k) => (
                <td key={k} className="align-top">
                  <PeriodCell r={f[k] as PeriodRow | undefined} missing="—" />
                </td>
              ))}
              <td className="align-top">{f.quarantined_metric ? <Tag s="quarantined metric" tone="bad" /> : <span className="text-[11px] text-muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

/** Correction lines reference the corrected line as "<event> (line N)" (1-based line in the follow-up log). */
function correctionTarget(c: EventFollowup, all: EventFollowup[]): number {
  const m = /\(line\s+(\d+)\)/.exec(c.correction_of ?? "");
  if (m) {
    const i = Number(m[1]) - 1;
    if (i >= 0 && i < all.length && !all[i].correction_of) return i;
  }
  const ev = (c.correction_of ?? "").split(" ")[0];
  return all.findIndex((x) => !x.correction_of && x.event_id === ev);
}

function FollowupCard({ f, corrections }: { f: EventFollowup; corrections: EventFollowup[] }) {
  const corrected = corrections.length > 0;
  return (
    <li className="rounded-md border border-line p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <code className="font-semibold text-ink">{f.event_id ?? "—"}</code>
        <span className="text-muted">recorded {fmtTime(f.recorded_utc)}</span>
        {corrected && <Tag s="corrected below" tone="weak" />}
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-x-3 gap-y-1 sm:grid-cols-[auto_minmax(0,1fr)]">
        <dt className="text-muted">Series</dt>
        <dd className="[overflow-wrap:anywhere]">{f.series ?? "—"}</dd>
        <dt className="text-muted">Observed |4h log return|</dt>
        <dd className="tnum">{typeof f.observed_abs_4h_log_return === "number" ? `${(f.observed_abs_4h_log_return * 100).toFixed(3)}%` : "—"}</dd>
        <dt className="text-muted">Registered reference</dt>
        <dd className="[overflow-wrap:anywhere]">{f.registered_reference ?? "—"}</dd>
        <dt className="text-muted">{corrected ? "Original label (superseded)" : "Label"}</dt>
        <dd className={`[overflow-wrap:anywhere] ${corrected ? "text-muted line-through decoration-warn/60" : "text-ink2"}`}>{f.label ?? "—"}</dd>
        {(f.archives ?? []).length > 0 && (
          <>
            <dt className="text-muted">Archives</dt>
            <dd className="space-y-0.5">
              {f.archives!.map((a) => (
                <div key={a.url} className="[overflow-wrap:anywhere]">
                  {a.day} · <Hash v={a.sha256} n={12} label="sha256" /> · {a.checksum_verified ? <span className="text-up">checksum verified</span> : <span className="text-[#f3a7a7]">checksum NOT verified</span>}
                </div>
              ))}
            </dd>
          </>
        )}
      </dl>
      {corrections.map((c, i) => (
        <div key={i} className="mt-2 rounded border border-warn/50 bg-warn/5 p-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-warn">
            Correction · recorded {fmtTime(c.recorded_utc)} · of {c.correction_of}
          </p>
          <p className="mt-1 text-ink [overflow-wrap:anywhere]">
            <span className="text-muted">Corrected label: </span>
            {c.label ?? "—"}
          </p>
          {c.reason && <p className="mt-0.5 text-ink2 [overflow-wrap:anywhere]">Reason: {c.reason}</p>}
        </div>
      ))}
    </li>
  );
}

export function QuantDiscoveries({ poll }: { poll: Poll<CQuantResp> }) {
  return (
    <Panel id="quant" title="4 · Quantitative Discoveries" subtitle="One entry per hypothesis, latest registry run (GET /api/control/quant)">
      <CState poll={poll} what="quant discoveries">
        {(d) => {
          const sup = d.findings.filter((f) => f.status === "supported");
          const inc = d.findings.filter((f) => f.status !== "supported");
          const fu = d.event_followups;
          const corr = new Map<number, EventFollowup[]>();
          const orphan: EventFollowup[] = [];
          fu.forEach((x) => {
            if (!x.correction_of) return;
            const t = correctionTarget(x, fu);
            if (t < 0) orphan.push(x);
            else corr.set(t, [...(corr.get(t) ?? []), x]);
          });
          return (
            <div className="space-y-3">
              <Banner tone="weak" title="Exploratory">
                {d.label ?? "All 'supported' results are exploratory until prospectively confirmed."}
              </Banner>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Kpi label="Tests run" value={fmtAny(d.counts.total_tests)} />
                <Kpi label="Distinct hypotheses" value={fmtAny(d.counts.distinct_hypotheses)} />
                <Kpi label="Registry runs" value={fmtAny(d.counts.runs)} />
                <Kpi label="Supported / inconclusive" value={`${sup.length} / ${inc.length}`} sub="hypotheses" />
              </div>
              {d.counts.note && <p className="text-[11px] text-muted">{d.counts.note}</p>}
              {d.note && <p className="text-[11px] text-muted">{d.note}</p>}

              <Sub>Quarantined metrics</Sub>
              {d.quarantined_metrics.length === 0 ? (
                <p className="text-xs text-ink2">
                  None recorded. <span className="text-muted">(Also empty while the calibration study has not finished — see Prediction Reliability. Quarantine applies to calendar families only.)</span>
                </p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {d.quarantined_metrics.map((m) => (
                    <Tag key={m} s={`quarantined: ${m}`} tone="bad" />
                  ))}
                </div>
              )}

              <Sub right={<Tag s="exploratory" tone="weak" />}>Supported ({sup.length})</Sub>
              <FindingsTable rows={sup} label="Supported findings" />
              <Sub>Inconclusive ({inc.length})</Sub>
              <FindingsTable rows={inc} label="Inconclusive findings" />

              {(d.counts.by_family_period ?? []).length > 0 && (
                <Details summary="Tests by family and period">
                  <TableWrap label="Tests by family and period">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Family</th>
                          <th>Period</th>
                          <th className="num">Tests</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.counts.by_family_period!.map((r) => (
                          <tr key={`${r.family}|${r.period}`}>
                            <td className="font-mono text-xs">{r.family}</td>
                            <td className="text-xs">{r.period.toLowerCase()}</td>
                            <td className="num">{fmtAny(r.n)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableWrap>
                </Details>
              )}

              <Sub>Event follow-ups</Sub>
              {fu.length === 0 ? (
                <p className="text-xs text-muted">None recorded.</p>
              ) : (
                <ul className="space-y-2">
                  {fu.map((f, i) => (f.correction_of ? null : <FollowupCard key={i} f={f} corrections={corr.get(i) ?? []} />))}
                  {orphan.map((c, i) => (
                    <li key={`o${i}`} className="rounded-md border border-warn/50 bg-warn/5 p-3 text-xs">
                      <p className="font-semibold text-warn">Correction of {c.correction_of} (corrected line not found)</p>
                      <p className="mt-1 [overflow-wrap:anywhere]">{c.label}</p>
                      {c.reason && <p className="mt-0.5 text-ink2">Reason: {c.reason}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        }}
      </CState>
    </Panel>
  );
}

/* ================================================================ 5 · evolution */

export function Evolution({ poll }: { poll: Poll<CEvolutionResp> }) {
  return (
    <Panel id="evolution" title="5 · Evolution" subtitle="Improvement proposals, each judged only by its own category's evaluator (GET /api/control/evolution)">
      <CState poll={poll} what="evolution proposals">
        {(d) => {
          const errs = Object.entries(d.errors ?? {});
          const cats = Object.keys(d.categories);
          const extra = Array.from(new Set(d.proposals.map((p) => p.category))).filter((c) => !cats.includes(c));
          return (
            <div className="space-y-3">
              {d.rule && (
                <Banner tone="info" title="Rule">
                  {d.rule}
                </Banner>
              )}
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Kpi label="Proposals" value={d.proposals.length} />
                <Kpi label="Promotable" value={d.proposals.filter((p) => p.promotable).length} />
                <Kpi label="Promoted" value={d.promoted.length} />
                <Kpi label="Excluded test fixtures" value={fmtAny(d.excluded_test_fixtures)} sub="not counted as proposals" />
              </div>
              {errs.length > 0 && (
                <Banner tone="bad" title="Sources that could not be read">
                  <Kv data={d.errors} />
                </Banner>
              )}
              {[...cats, ...extra].map((c) => {
                const rows = d.proposals.filter((p) => p.category === c);
                return (
                  <section key={c} aria-label={c} className="rounded-md border border-line p-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <h3 className="font-mono text-xs font-semibold text-ink">{c}</h3>
                      <span className="text-[11px] text-muted">{d.by_category?.[c] ?? rows.length} proposal(s)</span>
                    </div>
                    <p className="mt-0.5 text-[11px] text-ink2">
                      <span className="text-muted">Evaluator: </span>
                      {d.categories[c] ?? <Na>no evaluator defined</Na>}
                    </p>
                    {rows.length === 0 ? (
                      <p className="mt-2 text-xs text-muted">No proposals in this category.</p>
                    ) : (
                      <div className="mt-2">
                        <TableWrap label={`${c} proposals`}>
                          <table className="data">
                            <thead>
                              <tr>
                                <th>Proposal</th>
                                <th>Status</th>
                                <th>Independent evidence</th>
                                <th>Promotable</th>
                                <th>Human review</th>
                              </tr>
                            </thead>
                            <tbody>
                              {rows.map((p) => (
                                <tr key={p.id}>
                                  <td className="!whitespace-normal min-w-[16rem] align-top text-xs">
                                    <div className="text-ink [overflow-wrap:anywhere]">{p.title}</div>
                                    <div className="text-[11px] text-muted [overflow-wrap:anywhere]">
                                      {p.source} · <code>{p.id}</code>
                                    </div>
                                  </td>
                                  <td className="align-top">
                                    <Tag s={p.status} />
                                  </td>
                                  <td className="!whitespace-normal min-w-[12rem] align-top text-xs text-ink2">{p.independent_evidence}</td>
                                  <td className="align-top text-xs">{p.promotable ? <span className="font-semibold text-up">yes</span> : "no"}</td>
                                  <td className="align-top text-xs">{p.requires_human_review ? "required" : <span className="text-muted">—</span>}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </TableWrap>
                      </div>
                    )}
                  </section>
                );
              })}
              <p className="text-xs text-ink2">
                Promoted: {d.promoted.length === 0 ? "none" : d.promoted.map((p) => (typeof p === "string" ? p : JSON.stringify(p))).join(", ")}.
              </p>
            </div>
          );
        }}
      </CState>
    </Panel>
  );
}

/* ================================================================ 6 · operations */

export function Operations({ poll }: { poll: Poll<COpsResp> }) {
  return (
    <Panel id="ops" title="6 · Operations" subtitle="Durable scheduler, data sources and research budget (GET /api/control/ops)">
      <CState poll={poll} what="operations">
        {(d) => {
          const b = d.budget_today;
          const wl = b?.limits?.research_daily_wall_s;
          const ll = b?.limits?.research_daily_llm_calls;
          const crit = d.runs.filter((r) => !!r.critical);
          const opt = d.runs.filter((r) => !r.critical);
          const failedCrit = crit.filter((r) => /fail/.test(r.status)).length;
          const runsTable = (rows: typeof d.runs, label: string) =>
            rows.length === 0 ? (
              <p className="text-xs text-muted">No runs recorded.</p>
            ) : (
              <TableWrap label={label}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>Job</th>
                      <th>Slot</th>
                      <th>Status</th>
                      <th className="num">Attempts</th>
                      <th>Started</th>
                      <th>Finished</th>
                      <th>Next attempt</th>
                      <th>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={`${r.job}|${r.slot}|${i}`}>
                        <td className="font-mono text-xs">{r.job}</td>
                        <td className="font-mono text-xs">{r.slot}</td>
                        <td>
                          <Tag s={r.status} />
                        </td>
                        <td className="num">{fmtAny(r.attempts)}</td>
                        <td className="text-xs">{fmtTime(r.started_utc)}</td>
                        <td className="text-xs">{fmtTime(r.finished_utc)}</td>
                        <td className="text-xs">{r.status === "succeeded" ? <span className="text-muted">—</span> : fmtTime(r.next_attempt_utc)}</td>
                        <td className="!whitespace-normal min-w-[10rem] text-xs text-[#f3a7a7] [overflow-wrap:anywhere]">{r.error ?? <span className="text-muted">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            );
          return (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Kpi
                  label="Scheduler"
                  value={d.scheduler_alive ? "alive" : "not alive"}
                  tone={d.scheduler_alive ? "up" : "down"}
                  sub={`last tick ${ageText(d.last_tick_age_s)}`}
                />
                <Kpi label="Last tick" value={d.heartbeat?.last_tick_utc ? fmtTime(d.heartbeat.last_tick_utc).slice(11) : "never"} sub={d.heartbeat?.last_tick_host ?? "host unknown"} />
                <Kpi label="Army state" value={d.army_state ?? "unknown"} tone={d.army_state === "running" ? undefined : "warn"} />
                <Kpi label="Critical failures" value={failedCrit} tone={failedCrit ? "down" : undefined} sub={`of ${crit.length} recent critical runs`} />
              </div>

              <Sub right={<Tag s="critical" tone="info" />}>Recent critical runs (forecasting path)</Sub>
              {runsTable(crit, "Critical runs")}
              <Sub right={<Tag s="optional" tone="neutral" />}>Recent optional runs (research)</Sub>
              {runsTable(opt, "Optional runs")}
              {d.counts.length > 0 && (
                <Details summary="Run counts by job and status">
                  <TableWrap label="Run counts">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Job</th>
                          <th>Status</th>
                          <th className="num">Runs</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.counts.map((c, i) => (
                          <tr key={i}>
                            <td className="font-mono text-xs">{c.job}</td>
                            <td>
                              <Tag s={c.status} />
                            </td>
                            <td className="num">{fmtAny(c.n)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableWrap>
                </Details>
              )}

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div className="min-w-0">
                  <Sub>Source health</Sub>
                  {d.sources.length === 0 ? (
                    <p className="text-xs text-muted">No sources recorded.</p>
                  ) : (
                    <TableWrap label="Source health">
                      <table className="data">
                        <thead>
                          <tr>
                            <th>Source</th>
                            <th>State</th>
                            <th>Last OK</th>
                            <th className="num">Consec. failures</th>
                            <th>Last error</th>
                          </tr>
                        </thead>
                        <tbody>
                          {d.sources.map((s) => (
                            <tr key={s.name}>
                              <td className="font-mono text-xs">{s.name}</td>
                              <td>
                                <Tag s={s.state} />
                              </td>
                              <td className="text-xs">{fmtTime(s.last_ok_utc)}</td>
                              <td className="num">{fmtAny(s.consecutive_failures)}</td>
                              <td className="!whitespace-normal text-xs text-ink2 [overflow-wrap:anywhere]">
                                {s.last_error ? `${fmtTime(s.last_error_utc)} · ${s.last_error}` : <span className="text-muted">—</span>}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </TableWrap>
                  )}
                  <Sub>Notifications</Sub>
                  {d.notifications.length === 0 ? (
                    <p className="text-xs text-ink2">None recorded.</p>
                  ) : (
                    <JsonTable value={d.notifications} />
                  )}
                </div>
                <div className="min-w-0">
                  <Sub>Research budget today{b?.day ? ` · ${b.day}` : ""}</Sub>
                  {!b ? (
                    <p className="text-xs text-muted">Budget record not available.</p>
                  ) : (
                    <div className="space-y-3 text-xs">
                      <div>
                        <div className="mb-1 flex justify-between gap-2">
                          <span className="text-ink2">Research wall time</span>
                          <span className="tnum">
                            {num(b.research_wall_s, 0)} s / {wl != null ? `${num(wl, 0)} s` : "no limit recorded"}
                          </span>
                        </div>
                        {wl != null && <Progress value={b.research_wall_s ?? 0} max={wl} tone={(b.research_wall_s ?? 0) >= wl ? "bad" : "info"} label="Research wall time used" />}
                      </div>
                      <div>
                        <div className="mb-1 flex justify-between gap-2">
                          <span className="text-ink2">Research LLM calls</span>
                          <span className="tnum">
                            {fmtAny(b.research_llm_calls)} / {ll != null ? fmtAny(ll) : "no limit recorded"}
                          </span>
                        </div>
                        {ll != null && <Progress value={b.research_llm_calls ?? 0} max={ll} tone={(b.research_llm_calls ?? 0) >= ll ? "bad" : "info"} label="Research LLM calls used" />}
                      </div>
                      <p className="text-[11px] text-muted">These daily limits apply to optional research; critical forecasting jobs are scheduled separately.</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        }}
      </CState>
    </Panel>
  );
}
