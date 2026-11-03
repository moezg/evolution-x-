"use client";
import { useEffect, useState } from "react";
import { PageTitle } from "@/components/ui";
import {
  CalibrationPanel,
  ComparisonPanel,
  ErrorPanel,
  EvolutionPanel,
  FState,
  ForecastHeader,
  ProspectivePanel,
  SeriesPanel,
} from "@/components/forecast";
import { usePoll } from "@/lib/hooks";
import type { BacktestReport, EvolutionResp, ForecastProtocol, LedgerResp, ProspectiveResp, SeriesResp } from "@/lib/forecast";

const SECTIONS: [string, string][] = [
  ["protocol", "Protocol & exposure"],
  ["prospective", "Prospective ledger"],
  ["series", "Predictions vs outcomes"],
  ["calibration", "Calibration"],
  ["errors", "Error distributions"],
  ["comparison", "Model comparison"],
  ["evolution", "Evolution"],
];

/**
 * Forecasting laboratory: real-BTC probabilistic forecasts. The prospective ledger (the only independent evidence) is
 * polled; retrospective artifacts are fetched once and re-read with "Reload".
 */
export default function ForecastPage() {
  const protocol = usePoll<ForecastProtocol>("/api/forecast/protocol", 0);
  const report = usePoll<BacktestReport>("/api/forecast/backtest", 0);
  const ledger = usePoll<LedgerResp>("/api/forecast/ledger?limit=2000", 60000);
  const prospective = usePoll<ProspectiveResp>("/api/forecast/prospective", 60000);
  const evolution = usePoll<EvolutionResp>("/api/forecast/evolution", 0);
  const [target, setTarget] = useState("");
  // default: first binary target listed by the report
  useEffect(() => {
    const t = report.data?.targets;
    if (!t || (target && t[target])) return;
    const names = Object.keys(t);
    setTarget(names.find((n) => t[n].kind === "binary") ?? names[0] ?? "");
  }, [report.data, target]);
  const series = usePoll<SeriesResp>(target ? `/api/forecast/series?target=${encodeURIComponent(target)}` : null, 0);
  const reload = () => [protocol, report, ledger, prospective, evolution, series].forEach((p) => p.refresh());

  return (
    <div className="space-y-4">
      <PageTitle title="Forecasting Laboratory">
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
      <ForecastHeader protocol={protocol} report={report} />
      <ProspectivePanel ledger={ledger} prospective={prospective} protocol={protocol.data} />
      <FState poll={report} what="backtest report">
        {(rep) =>
          target && rep.targets[target] ? (
            <>
              <SeriesPanel report={rep} protocol={protocol.data} series={series} target={target} setTarget={setTarget} />
              <CalibrationPanel report={rep} protocol={protocol.data} target={target} setTarget={setTarget} />
              <ErrorPanel report={rep} protocol={protocol.data} series={series} target={target} setTarget={setTarget} />
              <ComparisonPanel report={rep} protocol={protocol.data} target={target} setTarget={setTarget} />
            </>
          ) : (
            <p className="text-xs text-muted">Loading targets…</p>
          )
        }
      </FState>
      <EvolutionPanel poll={evolution} protocol={protocol.data} />
    </div>
  );
}
