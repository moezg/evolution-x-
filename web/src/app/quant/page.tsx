"use client";
import { useEffect, useState } from "react";
import { PageTitle } from "@/components/ui";
import { CalendarPanel, CyclesPanel, DependencyPanel, EventExplorer, ForwardPanel, LineagePanel, QuantHeader, RankingsPanel } from "@/components/quant";
import { usePoll } from "@/lib/hooks";
import type {
  CalendarResp,
  CyclesResp,
  ElectionsResp,
  EventsResp,
  FomcResp,
  ForecastLinkResp,
  QuantProtocol,
  RankingsResp,
  TestsResp,
  WorkflowResp,
} from "@/lib/quant";

const SECTIONS: [string, string][] = [
  ["claims", "Claims policy"],
  ["calendar", "Calendar scanner"],
  ["cycles", "Cycles"],
  ["events", "Political & macro events"],
  ["dependency", "Correlation & dependency"],
  ["rankings", "Discovery rankings"],
  ["lineage", "Research lineage"],
  ["forward", "Forward monitor"],
];

/**
 * Quantitative Intelligence: the pre-registered quant discovery workflow (quant_protocol_v1). Read-only, GET only.
 * Artifacts 404 until a workflow run has produced them; they are re-checked every minute.
 */
export default function QuantPage() {
  const protocol = usePoll<QuantProtocol>("/api/quant/protocol", 0);
  const tests = usePoll<TestsResp>("/api/quant/tests", 60000);
  const calendar = usePoll<CalendarResp>("/api/quant/calendar", 60000);
  const cycles = usePoll<CyclesResp>("/api/quant/cycles", 60000);
  const fomc = usePoll<FomcResp>("/api/quant/fomc", 60000);
  const elections = usePoll<ElectionsResp>("/api/quant/elections", 60000);
  const fcast = usePoll<ForecastLinkResp>("/api/quant/forecast-link", 60000);
  const rankings = usePoll<RankingsResp>("/api/quant/rankings", 60000);
  const workflow = usePoll<WorkflowResp>("/api/quant/workflow", 30000);
  const fomcEvents = usePoll<EventsResp>("/api/quant/events?category=fomc", 300000);

  // lineage selection: defaults to the top-ranked hypothesis
  const [hyp, setHyp] = useState("");
  useEffect(() => {
    const r = rankings.data?.ranking;
    if (!hyp && r?.length) setHyp(r[0].hypothesis);
  }, [rankings.data, hyp]);

  const reload = () => [protocol, tests, calendar, cycles, fomc, elections, fcast, rankings, workflow, fomcEvents].forEach((p) => p.refresh());

  return (
    <div className="space-y-4">
      <PageTitle title="Quantitative Intelligence">
        <button type="button" className="btn btn-sm" onClick={reload}>
          Reload
        </button>
      </PageTitle>
      <nav aria-label="Sections" className="-mx-1 flex gap-1 overflow-x-auto px-1 text-xs">
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#${id}`} className="whitespace-nowrap rounded border border-line px-2 py-1 text-ink2 hover:bg-panel2 hover:text-ink">
            {label}
          </a>
        ))}
      </nav>
      <QuantHeader protocol={protocol} tests={tests} />
      <CalendarPanel poll={calendar} />
      <CyclesPanel poll={cycles} />
      <EventExplorer fomc={fomc} elections={elections} />
      <DependencyPanel cycles={cycles} fomc={fomc} fcast={fcast} />
      <RankingsPanel poll={rankings} onSelect={setHyp} selected={hyp} />
      <LineagePanel poll={workflow} tests={tests} hypothesis={hyp} setHypothesis={setHyp} />
      <ForwardPanel fcast={fcast} fomcEvents={fomcEvents} elections={elections} />
    </div>
  );
}
