"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { clockFmt, LineChart } from "@/components/charts";
import { EmptyState, ErrorNote, JsonTable, KeyValue, NoSimCta, PageTitle, Panel, ProvenanceBadge } from "@/components/ui";
import { usePoll } from "@/lib/hooks";
import { KINDS, kindColor, kindLabel, stanceColor } from "@/lib/colors";
import { fmtAny, hms, num, pct, signed, usd } from "@/lib/format";
import type { AgentDetail, AgentRow, SimState } from "@/lib/types";

type Col = { key: string; label: string; num?: boolean; get: (a: AgentRow) => number | string; render?: (a: AgentRow) => React.ReactNode };

const COLS: Col[] = [
  { key: "id", label: "ID", num: true, get: (a) => a.id },
  {
    key: "kind", label: "Kind", get: (a) => a.kind,
    render: (a) => (
      <span className="whitespace-nowrap">
        <span aria-hidden className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: kindColor(a.kind) }} />
        {kindLabel(a.kind)}
      </span>
    ),
  },
  { key: "equity", label: "Equity", num: true, get: (a) => a.equity, render: (a) => usd(a.equity, 0) },
  { key: "return_pct", label: "Return", num: true, get: (a) => a.return_pct,
    render: (a) => <span className={a.return_pct > 0 ? "text-up" : a.return_pct < 0 ? "text-down" : ""}>{pct(a.return_pct, 3)}</span> },
  { key: "pos", label: "Pos BTC (A / B)", num: true, get: (a) => (a.positions_btc ?? []).reduce((x, y) => x + y, 0),
    render: (a) => (a.positions_btc ?? []).map((p) => num(p, 3)).join(" / ") },
  { key: "leverage", label: "Lev", num: true, get: (a) => a.leverage, render: (a) => num(a.leverage, 3) },
  { key: "max_drawdown_pct", label: "Max DD", num: true, get: (a) => a.max_drawdown_pct, render: (a) => `${num(a.max_drawdown_pct, 2)}%` },
  { key: "reputation", label: "Rep", num: true, get: (a) => a.reputation, render: (a) => num(a.reputation, 3) },
  { key: "stance", label: "Stance", num: true, get: (a) => a.stance,
    render: (a) => (
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: stanceColor(a.stance) }} />
        {signed(a.stance, 2)}
      </span>
    ) },
  { key: "strategy_version", label: "Ver", num: true, get: (a) => a.strategy_version },
  { key: "orders_sent", label: "Orders", num: true, get: (a) => a.orders_sent },
  { key: "liquidations", label: "Liqs", num: true, get: (a) => a.liquidations },
  { key: "fees_paid_usd", label: "Fees", num: true, get: (a) => a.fees_paid_usd, render: (a) => usd(a.fees_paid_usd, 0) },
];

export default function AgentsPage() {
  const st = usePoll<SimState>("/api/sim/state", 3000);
  const hasSim = !!st.data && st.data.status !== "idle";
  const agents = usePoll<AgentRow[]>(hasSim ? "/api/sim/agents" : null, 3000);
  const [kind, setKind] = useState("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "id", dir: 1 });
  const [sel, setSel] = useState<number | null>(null);

  useEffect(() => {
    const m = window.location.hash.match(/agent-(\d+)/);
    if (m) setSel(Number(m[1]));
  }, []);
  useEffect(() => {
    if (sel === null) history.replaceState(null, "", window.location.pathname);
    else history.replaceState(null, "", `#agent-${sel}`);
  }, [sel]);

  const rows = useMemo(() => {
    let r = agents.data ?? [];
    if (kind !== "all") r = r.filter((a) => a.kind === kind);
    const qq = q.trim();
    if (qq) r = r.filter((a) => String(a.id).startsWith(qq) || a.kind.includes(qq.toLowerCase()));
    const col = COLS.find((c) => c.key === sort.key) ?? COLS[0];
    return [...r].sort((a, b) => {
      const x = col.get(a);
      const y = col.get(b);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [agents.data, kind, q, sort]);

  if (st.data && !hasSim) {
    return (
      <div>
        <PageTitle title="Agent explorer" />
        <NoSimCta />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageTitle title="Agent explorer">
        <ProvenanceBadge label={st.data?.data_label} />
      </PageTitle>
      <div className={`grid grid-cols-1 gap-4 ${sel !== null ? "xl:grid-cols-[minmax(0,1fr)_minmax(0,560px)]" : ""}`}>
        <Panel
          title={`Agents (${rows.length}${agents.data ? ` of ${agents.data.length}` : ""})`}
          subtitle="Click a row (or press Enter) to open its detail panel. Click column headers to sort."
          actions={
            <>
              <label className="field !flex-row items-center gap-2">
                <span>Kind</span>
                <select className="input w-auto" value={kind} onChange={(e) => setKind(e.target.value)}>
                  <option value="all">all kinds</option>
                  {KINDS.map((k) => (
                    <option key={k} value={k}>
                      {kindLabel(k)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field !flex-row items-center gap-2">
                <span>Search</span>
                <input className="input w-28" type="search" placeholder="id…" value={q} onChange={(e) => setQ(e.target.value)} />
              </label>
            </>
          }
        >
          <ErrorNote error={agents.error} what="agents" />
          {!agents.data ? (
            <EmptyState title="Loading agents…" />
          ) : rows.length === 0 ? (
            <EmptyState title="No agents match the filter" />
          ) : (
            <div className="max-h-[70vh] overflow-auto rounded border border-line">
              <table className="data">
                <thead>
                  <tr>
                    {COLS.map((c) => (
                      <th key={c.key} scope="col" className={c.num ? "num" : ""} aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
                        <button
                          className="uppercase hover:text-ink"
                          onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? ((-s.dir) as 1 | -1) : c.num && c.key !== "id" ? -1 : 1 }))}
                        >
                          {c.label}
                          {sort.key === c.key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((a) => (
                    <tr
                      key={a.id}
                      tabIndex={0}
                      aria-selected={sel === a.id}
                      onClick={() => setSel(a.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setSel(a.id);
                        }
                      }}
                      className={`cursor-pointer ${sel === a.id ? "!bg-accent/15" : ""}`}
                    >
                      {COLS.map((c) => (
                        <td key={c.key} className={c.num ? "num" : ""}>
                          {c.render ? c.render(a) : fmtAny(c.get(a))}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        {sel !== null && <AgentPanel id={sel} onSelect={setSel} onClose={() => setSel(null)} label={st.data?.data_label} />}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-line pt-3">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink2">{title}</h3>
      {children}
    </section>
  );
}

function AgentPanel({ id, onClose, onSelect, label }: { id: number; onClose: () => void; onSelect: (id: number) => void; label?: string }) {
  const d = usePoll<AgentDetail>(`/api/sim/agents/${id}`, 2000);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
    ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [id]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const a = d.data && d.data.id === id ? d.data : undefined;
  const eq = a?.equity_curve ?? [];
  const obs = a?.observable_inputs as Record<string, unknown> | undefined;
  const view = obs?.home_venue_view as Record<string, number | boolean> | undefined;

  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="region"
      aria-label={`Agent ${id} detail`}
      className="min-w-0 rounded-lg border border-line2 bg-panel p-3 outline-none sm:p-4 xl:sticky xl:top-28 xl:max-h-[calc(100vh-8rem)] xl:overflow-y-auto"
    >
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">
            Agent #{id}{" "}
            {a && (
              <span className="ml-1 text-sm font-normal text-ink2">
                <span aria-hidden className="mr-1 inline-block h-2.5 w-2.5 rounded-full" style={{ background: kindColor(a.kind) }} />
                {kindLabel(a.kind)} · strategy v{a.strategy_version} · home venue {a.home_venue === 0 ? "A" : "B"}
              </span>
            )}
          </h2>
          {a && (
            <p className="text-xs text-muted tnum">
              latency: order {a.order_latency_ms} ms · market data {a.md_latency_ms} ms · wake every {a.wake_ms} ms
            </p>
          )}
        </div>
        <button className="btn btn-sm" onClick={onClose} aria-label="Close agent detail">
          ✕ Close
        </button>
      </div>
      <ErrorNote error={d.error} what="agent" />
      {!a ? (
        <EmptyState title="Loading agent…" />
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            {[
              ["Equity", usd(a.equity, 0)],
              ["Return", pct(a.return_pct, 3)],
              ["Leverage", num(a.leverage, 3)],
              ["Max DD", `${num(a.max_drawdown_pct, 2)}%`],
              ["Pos A BTC", num(a.positions_btc?.[0], 4)],
              ["Pos B BTC", num(a.positions_btc?.[1], 4)],
              ["Reputation", num(a.reputation, 3)],
              ["Stance", signed(a.stance, 3)],
            ].map(([k, v]) => (
              <div key={k} className="rounded border border-line bg-panel2 px-2 py-1">
                <div className="text-[10px] uppercase text-muted">{k}</div>
                <div className="font-semibold tnum">{v}</div>
              </div>
            ))}
          </div>

          <Section title="Equity curve">
            <div className="mb-1"><ProvenanceBadge label={label} /></div>
            {eq.length > 1 ? (
              <LineChart
                x={eq.map((p) => p[0] / 1000)}
                series={[{ name: "equity USD", color: "#3987e5", values: eq.map((p) => p[1]) }]}
                height={150}
                timeAxis
                xFormat={clockFmt}
                label={`Equity curve of agent ${id}`}
              />
            ) : (
              <p className="text-xs text-muted">Not enough points yet.</p>
            )}
          </Section>

          <Section title="Parameters">
            <KeyValue data={a.params} />
          </Section>

          <Section title="Observable decision inputs (what the agent can see)">
            {obs ? (
              <div className="space-y-2">
                <p className="text-[11px] text-muted tnum">
                  data as of T+{hms(Number(obs.data_t_ms ?? 0) / 1000)} (md latency {String(obs.md_latency_ms ?? "—")} ms) · private
                  fundamental: {obs.has_private_fundamental ? "yes (noisy estimate)" : "no"}
                </p>
                {view && (
                  <div className="grid grid-cols-3 gap-1 text-[11px] tnum">
                    {(["bid", "ask", "mid", "last"] as const).map((k) => (
                      <div key={k} className="rounded bg-panel2 px-2 py-1">
                        <span className="text-muted">{k}</span> {typeof view[k] === "number" ? num((view[k] as number) / 100) : "—"}
                      </div>
                    ))}
                    <div className="rounded bg-panel2 px-2 py-1">
                      <span className="text-muted">depth bid BTC</span> {num(Number(view.depth_bid) / 1e4, 2)}
                    </div>
                    <div className="rounded bg-panel2 px-2 py-1">
                      <span className="text-muted">depth ask BTC</span> {num(Number(view.depth_ask) / 1e4, 2)}
                    </div>
                    <div className="rounded bg-panel2 px-2 py-1">
                      <span className="text-muted">halted</span> {String(view.halted)}
                    </div>
                  </div>
                )}
                <KeyValue data={Object.fromEntries(Object.entries(obs).filter(([k]) => !["home_venue_view", "data_t_ms", "md_latency_ms", "has_private_fundamental"].includes(k)))} />
                <p className="text-[10px] text-muted">Prices converted from integer ticks (1 tick = 0.01 USD); depth = top-5 levels converted from lots (1 lot = 0.0001 BTC). Decision quantities are in raw lots.</p>
              </div>
            ) : (
              <p className="text-xs text-muted">—</p>
            )}
          </Section>

          <Section title={`Recent decisions (${a.recent_decisions?.length ?? 0})`}>
            {a.recent_decisions?.length ? (
              <div className="max-h-48 overflow-auto">
                <JsonTable value={[...a.recent_decisions].reverse().map((r) => ({ ...r, t: hms(Number(r.t) / 1000) }))} />
              </div>
            ) : (
              <p className="text-xs text-muted">No decisions logged yet.</p>
            )}
          </Section>

          <Section title={`Open orders (${a.open_orders?.length ?? 0})`}>
            {a.open_orders?.length ? (
              <div className="overflow-x-auto">
                <table className="data">
                  <thead><tr><th>ID</th><th>Venue</th><th>Side</th><th className="num">Price</th><th className="num">Qty</th></tr></thead>
                  <tbody>
                    {a.open_orders.map((o) => (
                      <tr key={o.id}>
                        <td>{o.id}</td><td>{o.venue}</td>
                        <td className={o.side === "buy" || o.side === "bid" ? "text-up" : "text-down"}>{o.side}</td>
                        <td className="num">{num(o.price)}</td><td className="num">{num(o.qty, 4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-muted">No resting orders.</p>
            )}
          </Section>

          <Section title={`Trade history (${a.trades?.length ?? 0})`}>
            {a.trades?.length ? (
              <div className="max-h-56 overflow-auto">
                <table className="data">
                  <thead><tr><th>Time</th><th>Venue</th><th>Side</th><th className="num">Price</th><th className="num">Qty</th><th>Counterparty</th></tr></thead>
                  <tbody>
                    {a.trades.map((t) => {
                      const buy = t.buyer === id;
                      const cp = buy ? t.seller : t.buyer;
                      return (
                        <tr key={t.id}>
                          <td className="tnum">{hms(t.t_ms / 1000)}</td>
                          <td>{t.venue === 0 ? "A" : "B"}</td>
                          <td className={buy ? "text-up" : "text-down"}>{buy ? "buy" : "sell"}{(buy ? t.aggressor === "buy" : t.aggressor === "sell") ? " (taker)" : ""}</td>
                          <td className="num">{num(t.price)}</td>
                          <td className="num">{num(t.qty, 4)}</td>
                          <td>
                            {cp >= 0 ? (
                              <button className="text-accent underline-offset-2 hover:underline" onClick={() => onSelect(cp)}>#{cp}</button>
                            ) : (
                              <span className="text-muted">external</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-muted">No trades yet.</p>
            )}
          </Section>

          <Section title="Memory">
            <KeyValue data={a.memory} />
          </Section>

          <Section title={`Strategy lineage (${a.lineage?.length ?? 0} changes)`}>
            {a.lineage?.length ? (
              <ol className="relative space-y-3 border-l border-line2 pl-4">
                {a.lineage.map((l, i) => {
                  const keys = Array.from(new Set([...Object.keys(l.before ?? {}), ...Object.keys(l.after ?? {})]));
                  return (
                    <li key={i} className="relative">
                      <span aria-hidden className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full border-2 border-panel bg-accent" />
                      <div className="text-xs">
                        <b>v{l.version}</b> <span className="text-muted tnum">at T+{hms(l.t / 1000)}</span> · {l.reason}
                        {l.source_agent !== undefined && l.source_agent !== null && (
                          <>
                            {" "}from{" "}
                            <button className="text-accent hover:underline" onClick={() => onSelect(l.source_agent as number)}>#{l.source_agent}</button>
                          </>
                        )}
                      </div>
                      {keys.length > 0 && (
                        <table className="data mt-1">
                          <thead><tr><th>Param</th><th className="num">Before</th><th className="num">After</th></tr></thead>
                          <tbody>
                            {keys.map((k) => {
                              const b = l.before?.[k];
                              const af = l.after?.[k];
                              const changed = JSON.stringify(b) !== JSON.stringify(af);
                              return (
                                <tr key={k} className={changed ? "" : "opacity-60"}>
                                  <td>{k}</td>
                                  <td className="num text-down/90">{fmtAny(b)}</td>
                                  <td className={`num ${changed ? "text-up" : ""}`}>{fmtAny(af)}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      )}
                    </li>
                  );
                })}
              </ol>
            ) : (
              <p className="text-xs text-muted">Still running its initial strategy (v{a.strategy_version}). No imitation or adaptation yet.</p>
            )}
          </Section>

          <Section title={`Neighbors in the social graph (${a.neighbors?.length ?? 0})`}>
            {a.neighbors?.length ? (
              <ul className="flex flex-wrap gap-1.5">
                {a.neighbors.map((n) => (
                  <li key={n}>
                    <button className="btn btn-sm" onClick={() => onSelect(n)} aria-label={`Open agent ${n}`}>#{n}</button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted">No neighbors.</p>
            )}
          </Section>
        </div>
      )}
    </div>
  );
}
