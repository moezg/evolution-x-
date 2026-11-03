"use client";
import { useMemo, useState } from "react";
import { CandleChart } from "@/components/CandleChart";
import { clockFmt, LineChart } from "@/components/charts";
import { DepthChart, Ladder } from "@/components/OrderBook";
import { EventsFeed, PopulationTable, ShockPanel, SimControls, StartForm } from "@/components/sim";
import { EmptyState, ErrorNote, Kpi, Legend, PageTitle, Panel, ProvenanceBadge } from "@/components/ui";
import { useLiveState, usePoll } from "@/lib/hooks";
import { compact, hms, num, usd } from "@/lib/format";
import type { AgentRow, Book, CandlesResp, Series } from "@/lib/types";

export default function OverviewPage() {
  const { state, connected } = useLiveState();
  const [venue, setVenue] = useState(0);
  const hasSim = !!state && state.status !== "idle";
  const tS = (state?.t_ms ?? 0) / 1000;
  const step = Math.max(5, Math.ceil(tS / 400 / 5) * 5);

  const candles = usePoll<CandlesResp>(hasSim ? `/api/sim/candles?venue=${venue}` : null, 2000);
  const book = usePoll<Book>(hasSim ? `/api/sim/book?venue=${venue}&levels=20` : null, 1000);
  const series = usePoll<Series>(hasSim ? `/api/sim/series?step=${step}` : null, 2000);
  const agents = usePoll<AgentRow[]>(hasSim ? "/api/sim/agents" : null, 3000);

  const v = state?.venues?.[venue];
  const spreadBps = v && v.mid ? ((v.ask - v.bid) / v.mid) * 1e4 : undefined;
  const label = candles.data?.data_label ?? state?.data_label ?? "synthetic";
  const shockMarkers = useMemo(() => (state?.shocks ?? []).map((s) => ({ x: s.at_s, label: s.type })), [state?.shocks]);

  const sx = series.data?.t ?? [];
  const fundSeries = useMemo(() => {
    const s = series.data;
    if (!s) return [];
    return [
      { name: "venue A mid", color: "#3987e5", values: s.mid_0 ?? [] },
      { name: "venue B mid", color: "#199e70", values: s.mid_1 ?? [] },
      { name: "latent fundamental (hidden)", color: "#c98500", values: s.fundamental ?? [], dashed: true },
    ];
  }, [series.data]);

  return (
    <div className="space-y-4">
      <PageTitle title="Market overview">
        {state && (
          <span className="text-xs text-muted">
            {connected ? "live stream" : "reconnecting…"}
            {state.config_fingerprint ? ` · config ${state.config_fingerprint}` : ""}
            {state.seed !== undefined ? ` · seed ${state.seed}` : ""}
          </span>
        )}
      </PageTitle>

      {hasSim && state ? (
        <Panel title="Simulation controls" subtitle={`mode: ${state.mode ?? "—"} · ${state.n_agents ?? "—"} agents`}>
          <SimControls state={state} />
        </Panel>
      ) : null}

      <Panel
        id="start"
        title={hasSim ? "Start a new run" : "Start a simulation"}
        subtitle={hasSim ? "Starting a new run replaces the current one." : "No simulation is running. Configure and start a synthetic market."}
      >
        {hasSim ? (
          <details>
            <summary className="cursor-pointer text-sm text-ink2 hover:text-ink">Show run configuration</summary>
            <div className="mt-3">
              <StartForm />
            </div>
          </details>
        ) : (
          <StartForm />
        )}
      </Panel>

      {hasSim && state && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
            <Kpi label="Virtual time" value={hms(tS)} sub={`of ${hms((state.duration_ms ?? 0) / 1000)}`} />
            <Kpi label="Speed" value={state.speed === 0 ? "max" : `${num(state.speed, 0)}×`} sub={`wall ${num(state.wall_time_s, 1)} s`} />
            <Kpi label="Events / s" value={compact(state.events_per_s)} sub={`${compact(state.events_processed)} total`} />
            <Kpi label="Trades" value={compact(state.n_trades, 2)} sub={`${state.rejections ?? 0} rejections`} />
            <Kpi label="Liquidations" value={state.liquidations ?? 0} tone={(state.liquidations ?? 0) > 0 ? "down" : undefined} sub={`${state.influence_events ?? 0} influence events`} />
            <Kpi label="Funding rate" value={state.funding_rate !== undefined ? `${(state.funding_rate * 100).toFixed(4)}%` : "—"} sub="per interval" />
            <Kpi label={`Spread ${v?.name ?? ""}`} value={spreadBps !== undefined ? `${spreadBps.toFixed(2)} bps` : "—"} sub={v ? `mid ${num(v.mid)}` : undefined} />
            <Kpi label="Insurance fund" value={usd(state.insurance_fund_usd, 0)} sub={`fees ${usd(state.fee_pool_usd, 0)}`} />
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Panel
              className="xl:col-span-2"
              title={
                <span className="flex flex-wrap items-center gap-2">
                  BTC/USDT 1-min candles <ProvenanceBadge label={label} />
                  {!!candles.data?.historical?.length && <ProvenanceBadge label="historical" />}
                </span>
              }
              subtitle={
                candles.data?.historical?.length
                  ? `Simulated path vs recorded day (${state.historical?.source_file ?? "historical"}) — the gold line is HISTORICAL data.`
                  : "Simulated market. Lower pane: volume (BTC)."
              }
              actions={
                <label className="flex items-center gap-2 text-xs text-ink2">
                  Venue
                  <select className="input w-auto" value={venue} onChange={(e) => setVenue(Number(e.target.value))}>
                    {(state.venues ?? []).map((vv, i) => (
                      <option key={vv.name} value={i}>
                        {vv.name}
                        {vv.halted ? " (halted)" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              }
            >
              <ErrorNote error={candles.error} what="candles" />
              {candles.data?.candles?.length ? (
                <>
                  <CandleChart
                    candles={candles.data.candles}
                    historical={candles.data.historical}
                    height={420}
                    label={`Candlestick chart for ${v?.name ?? "venue"}, ${label} data`}
                  />
                  {!!candles.data.historical?.length && (
                    <div className="mt-2">
                      <Legend
                        items={[
                          { label: `${label === "counterfactual_synthetic" ? "counterfactual synthetic" : "synthetic"} candles`, color: "#1baf7a" },
                          { label: "HISTORICAL close", color: "#f2c14e" },
                        ]}
                      />
                    </div>
                  )}
                </>
              ) : (
                <EmptyState title="Waiting for the first candle…">Candles appear after one virtual minute.</EmptyState>
              )}
            </Panel>

            <Panel
              title={
                <span className="flex flex-wrap items-center gap-2">
                  Order book · {v?.name ?? `venue ${venue}`} <ProvenanceBadge label={label} />
                </span>
              }
              subtitle={v?.halted ? "Venue HALTED (circuit breaker)" : `${book.data ? `${book.data.bids.length}+${book.data.asks.length} levels` : ""}`}
            >
              <ErrorNote error={book.error} what="book" />
              {book.data ? (
                <div className="space-y-3">
                  <DepthChart book={book.data} height={170} />
                  <Ladder book={book.data} rows={8} />
                </div>
              ) : (
                <EmptyState title="Loading book…" />
              )}
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel
              title={
                <span className="flex flex-wrap items-center gap-2">
                  Mid price vs latent fundamental <ProvenanceBadge label={label} />
                </span>
              }
              subtitle="Latent fundamental — hidden from agents (ground truth only the simulator knows)."
            >
              <ErrorNote error={series.error} what="series" />
              {sx.length > 1 ? (
                <>
                  <Legend items={fundSeries.map((s) => ({ label: s.name, color: s.color, dashed: s.dashed }))} />
                  <LineChart
                    x={sx}
                    series={fundSeries}
                    height={220}
                    xFormat={clockFmt} timeAxis
                    yFormat={(y) => y.toFixed(0)}
                    label="Line chart: venue mids and latent fundamental over virtual time"
                    markers={shockMarkers}
                  />
                </>
              ) : (
                <EmptyState title="Collecting series…" />
              )}
            </Panel>
            <Panel
              title={
                <span className="flex flex-wrap items-center gap-2">
                  Liquidity: spread &amp; depth <ProvenanceBadge label={label} />
                </span>
              }
              subtitle="Separate charts — different units."
            >
              {sx.length > 1 ? (
                <div className="space-y-2">
                  <div>
                    <h3 className="text-xs text-ink2">Spread (bps)</h3>
                    <LineChart x={sx} series={[{ name: "spread bps", color: "#d55181", values: series.data?.spread_bps ?? [] }]} height={110}
                      xFormat={clockFmt} timeAxis label="Spread in basis points over time" markers={shockMarkers} />
                  </div>
                  <div>
                    <h3 className="text-xs text-ink2">Top-of-book depth (BTC)</h3>
                    <LineChart x={sx} series={[{ name: "depth BTC", color: "#199e70", values: series.data?.depth ?? [] }]} height={110}
                      xFormat={clockFmt} timeAxis label="Book depth in BTC over time" markers={shockMarkers} />
                  </div>
                </div>
              ) : (
                <EmptyState title="Collecting series…" />
              )}
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,0.8fr)_minmax(0,1fr)]">
            <Panel title="Agent population by kind" subtitle={`${state.n_agents ?? "—"} agents`}>
              <ErrorNote error={agents.error} what="agents" />
              <PopulationTable agents={agents.data} counts={state.counts} />
            </Panel>
            <Panel title="Shock injection" subtitle="Exogenous intervention, recorded in the event log.">
              <ShockPanel disabled={state.status !== "running" && state.status !== "paused"} />
              {!!state.shocks?.length && (
                <div className="mt-3 border-t border-line pt-2">
                  <h3 className="mb-1 text-xs text-ink2">Scheduled / applied shocks</h3>
                  <ul className="space-y-0.5 text-[11px] text-ink2">
                    {state.shocks.map((s, i) => (
                      <li key={i} className="tnum">
                        T+{hms(s.at_s)} · {s.type} · mag {s.magnitude} · {s.duration_s}s{s.note ? ` · ${s.note}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Panel>
            <Panel title="Recent events" className="lg:col-span-2 xl:col-span-1">
              <EventsFeed enabled={hasSim} />
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
