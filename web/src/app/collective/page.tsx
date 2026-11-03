"use client";
import { useRouter } from "next/navigation";
import { BarChart, CompositionBar, HBars } from "@/components/charts";
import { NetworkGraph } from "@/components/NetworkGraph";
import { EmptyState, ErrorNote, Kpi, NoSimCta, PageTitle, Panel } from "@/components/ui";
import { usePoll } from "@/lib/hooks";
import { KINDS, kindColor, kindLabel, stanceColor } from "@/lib/colors";
import { hms, num, pct, signed } from "@/lib/format";
import type { Collective, Network, SimState } from "@/lib/types";

export default function CollectivePage() {
  const router = useRouter();
  const st = usePoll<SimState>("/api/sim/state", 3000);
  const hasSim = !!st.data && st.data.status !== "idle";
  const col = usePoll<Collective>(hasSim ? "/api/sim/collective" : null, 3000);
  const net = usePoll<Network>(hasSim ? "/api/sim/network" : null, 5000);
  const open = (id: number) => router.push(`/agents#agent-${id}`);

  if (st.data && !hasSim) {
    return (
      <div>
        <PageTitle title="Collective behaviour" />
        <NoSimCta />
      </div>
    );
  }
  const c = col.data;
  const kinds = c ? KINDS.filter((k) => c.by_kind?.[k] || c.stance_by_kind?.[k] !== undefined) : [];
  const ipm = c?.influence_per_minute ?? [];
  const maxMin = Math.max(0, ...ipm.map((r) => r.minute), Math.floor((st.data?.t_ms ?? 0) / 60000));
  const ipmBars = Array.from({ length: maxMin + 1 }, (_, m) => {
    const v = ipm.find((r) => r.minute === m)?.count ?? 0;
    return { label: String(m), value: v, tip: `minute ${m}: ${v} influence events` };
  });
  const w = c?.wealth;
  const wealthBars = (w?.log10_hist ?? []).map((v, i) => {
    const lo = w!.log10_edges[i];
    const hi = w!.log10_edges[i + 1];
    return {
      label: lo !== undefined ? `$${compactPow(lo)}` : String(i),
      value: v,
      tip: `$${compactPow(lo)}–$${compactPow(hi)}: ${v} agents`,
    };
  });

  return (
    <div className="space-y-4">
      <PageTitle title="Collective behaviour" />
      <ErrorNote error={col.error} what="collective" />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Wealth Gini" value={num(w?.gini, 3)} sub="equity inequality" />
        <Kpi label="Influence events" value={st.data?.influence_events ?? "—"} sub="stance updates via social graph" />
        <Kpi label="Imitation events" value={c?.imitation_events ?? "—"} sub="strategy copies" />
        <Kpi label="Panic events" value={c?.panic_events ?? "—"} tone={(c?.panic_events ?? 0) > 0 ? "warn" : undefined} />
        <Kpi label="MM withdrawals" value={c?.mm_withdrawals ?? "—"} tone={(c?.mm_withdrawals ?? 0) > 0 ? "warn" : undefined} />
        <Kpi label="Liquidations" value={st.data?.liquidations ?? "—"} tone={(st.data?.liquidations ?? 0) > 0 ? "down" : undefined} />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <Panel
          title="Interaction graph"
          subtitle={net.data ? `${net.data.nodes.length} agents · ${net.data.edges.length} edges · social influence ${net.data.enabled ? "enabled" : "disabled"}. Fill = kind, size = reputation, outline = stance. Click a node to open the agent.` : undefined}
        >
          <ErrorNote error={net.error} what="network" />
          {net.data ? <NetworkGraph net={net.data} onOpen={open} /> : <EmptyState title="Loading network…" />}
        </Panel>

        <div className="space-y-4">
          <Panel title="Behavioural clusters" subtitle="Clustered on behaviour features; composition by agent kind.">
            {c?.clusters?.length ? (
              <ul className="space-y-3">
                {c.clusters.map((cl) => (
                  <li key={cl.id} className="space-y-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
                      <span className="font-semibold">Cluster {cl.id} <span className="font-normal text-muted">· {cl.size} agents</span></span>
                      <span className="text-ink2 tnum">
                        stance <span style={{ color: stanceColor(cl.mean_stance) }}>{signed(cl.mean_stance, 2)}</span> · ret{" "}
                        <span className={cl.mean_return_pct >= 0 ? "text-up" : "text-down"}>{pct(cl.mean_return_pct, 3)}</span> · lev {num(cl.mean_leverage, 2)}
                      </span>
                    </div>
                    <CompositionBar
                      label={`Cluster ${cl.id} composition: ${Object.entries(cl.composition).map(([k, v]) => `${k} ${v}`).join(", ")}`}
                      parts={KINDS.filter((k) => cl.composition[k]).map((k) => ({ key: k, value: cl.composition[k], color: kindColor(k), label: kindLabel(k) }))}
                    />
                    <p className="text-[11px] text-muted">
                      {Object.entries(cl.composition).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${kindLabel(k)} ${v}`).join(" · ")}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No clusters yet" />
            )}
          </Panel>
          <Panel title="Stance by kind" subtitle="Mean sentiment stance: −1 bearish … +1 bullish.">
            {kinds.length ? (
              <HBars
                label="Mean stance by agent kind"
                domain={[-1, 1]}
                format={(v) => signed(v, 2)}
                rows={kinds.map((k) => ({ key: k, label: kindLabel(k), value: c?.stance_by_kind?.[k] ?? 0, color: stanceColor(c?.stance_by_kind?.[k] ?? 0) }))}
              />
            ) : (
              <EmptyState title="No data" />
            )}
          </Panel>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Influence / contagion per minute" subtitle="Count of social-influence stance updates in each virtual minute.">
          {ipmBars.length > 1 ? (
            <BarChart bars={ipmBars} height={170} color="#9085e9" label="Influence events per minute" yFormat={(v) => v.toFixed(0)} />
          ) : (
            <EmptyState title="No influence events yet" />
          )}
        </Panel>
        <Panel title="Wealth distribution" subtitle={`Histogram of log₁₀ equity (USD). Gini ${num(w?.gini, 3)}.`}>
          {wealthBars.length ? (
            <BarChart bars={wealthBars} height={170} color="#199e70" label="Wealth distribution histogram" yFormat={(v) => v.toFixed(0)} />
          ) : (
            <EmptyState title="No wealth data" />
          )}
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Panel title="Strategy performance by kind" subtitle="CVaR5 = mean of the worst 5% of agent returns within the kind.">
          {kinds.length ? (
            <div className="overflow-x-auto">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Kind</th>
                    <th scope="col" className="num">N</th>
                    <th scope="col" className="num">Mean ret</th>
                    <th scope="col" className="num">Median ret</th>
                    <th scope="col" className="num">CVaR5 ret</th>
                    <th scope="col" className="num">Mean max DD</th>
                  </tr>
                </thead>
                <tbody>
                  {kinds.map((k) => {
                    const s = c?.by_kind?.[k];
                    return (
                      <tr key={k}>
                        <td>
                          <span aria-hidden className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: kindColor(k) }} />
                          {kindLabel(k)}
                        </td>
                        <td className="num">{s?.n ?? "—"}</td>
                        <td className={`num ${(s?.mean_return_pct ?? 0) >= 0 ? "text-up" : "text-down"}`}>{pct(s?.mean_return_pct, 3)}</td>
                        <td className="num">{pct(s?.median_return_pct, 3)}</td>
                        <td className="num text-down">{pct(s?.cvar5_return_pct, 3)}</td>
                        <td className="num">{num(s?.mean_max_dd_pct, 3)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No data" />
          )}
        </Panel>
        <Panel title="Contagion feed" subtitle="Recent social-influence stance changes and liquidations.">
          <div className="max-h-80 space-y-1 overflow-y-auto text-xs">
            {(c?.liquidations_recent ?? []).map((l, i) => (
              <div key={`l${i}`} className="flex gap-2 border-b border-line pb-1">
                <span className="text-muted tnum">{hms(l.t / 1000)}</span>
                <span className="rounded border border-down/50 px-1 text-[10px] uppercase text-down">liq</span>
                <button className="text-accent hover:underline" onClick={() => open(l.agent)}>#{l.agent}</button>
                <span className="text-ink2">{kindLabel(l.kind)} · {l.closed_lots} lots closed · insurance {num(l.insurance_cover, 0)}</span>
              </div>
            ))}
            {(c?.influence_recent ?? []).map((r, i) => (
              <div key={`i${i}`} className="flex flex-wrap gap-x-2 border-b border-line pb-1">
                <span className="text-muted tnum">{hms(r.t / 1000)}</span>
                <button className="text-accent hover:underline" onClick={() => open(r.agent)}>#{r.agent}</button>
                <span className="text-ink2">{kindLabel(r.kind)}</span>
                <span className="tnum">
                  <span style={{ color: stanceColor(r.prev) }}>{signed(r.prev, 2)}</span> →{" "}
                  <span style={{ color: stanceColor(r.new) }}>{signed(r.new, 2)}</span>
                </span>
                <span className="text-muted">social signal {signed(r.social, 2)}</span>
              </div>
            ))}
            {!c?.influence_recent?.length && !c?.liquidations_recent?.length && <EmptyState title="No contagion events yet" />}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function compactPow(log10v: number | undefined): string {
  if (log10v === undefined || !Number.isFinite(log10v)) return "?";
  const v = Math.pow(10, log10v);
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}
