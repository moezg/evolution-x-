"use client";
import { PageTitle } from "@/components/ui";
import { Evolution, LiveForecasts, Operations, QuantDiscoveries, Reliability, ResearchArmy } from "@/components/control";
import { usePoll } from "@/lib/hooks";
import type { CArmyResp, CEvolutionResp, CForecastsResp, COpsResp, CQuantResp, CReliabilityResp } from "@/lib/control";

const SECTIONS: [string, string][] = [
  ["forecasts", "Live Forecasts"],
  ["reliability", "Reliability"],
  ["army", "Research Army"],
  ["quant", "Discoveries"],
  ["evolution", "Evolution"],
  ["ops", "Operations"],
];

/**
 * Predictive Intelligence Control Center. Read-only (GET /api/control/*); each section fetches its own endpoint, so a
 * failing endpoint only affects its own section. Every number shown is a persisted record; nothing is extrapolated.
 */
export default function ControlPage() {
  const forecasts = usePoll<CForecastsResp>("/api/control/forecasts", 60000);
  const reliability = usePoll<CReliabilityResp>("/api/control/reliability", 120000);
  const army = usePoll<CArmyResp>("/api/control/army", 120000);
  const quant = usePoll<CQuantResp>("/api/control/quant", 120000);
  const evolution = usePoll<CEvolutionResp>("/api/control/evolution", 120000);
  const ops = usePoll<COpsResp>("/api/control/ops", 30000);
  const reload = () => [forecasts, reliability, army, quant, evolution, ops].forEach((p) => p.refresh());

  return (
    <div className="space-y-4">
      <PageTitle title="Predictive Intelligence Control Center">
        <button type="button" className="btn btn-sm" onClick={reload}>
          Reload
        </button>
      </PageTitle>
      <p className="max-w-prose text-xs text-ink2">
        Every figure here is read from persisted records (forecast ledger, scheduler database, army store, test registry, study and proposal files). Where evidence is
        insufficient the page says so; nothing is extrapolated, smoothed or filled in. Research only — no trading signals.
      </p>
      <nav aria-label="Sections" className="-mx-1 flex gap-1 overflow-x-auto px-1 text-xs">
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#${id}`} className="whitespace-nowrap rounded border border-line px-2 py-1 text-ink2 hover:bg-panel2 hover:text-ink">
            {label}
          </a>
        ))}
      </nav>
      <LiveForecasts poll={forecasts} />
      <Reliability poll={reliability} />
      <ResearchArmy poll={army} />
      <QuantDiscoveries poll={quant} />
      <Evolution poll={evolution} />
      <Operations poll={ops} />
    </div>
  );
}
