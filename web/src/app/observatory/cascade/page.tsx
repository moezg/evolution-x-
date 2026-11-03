"use client";
import Link from "next/link";
import { useState } from "react";
import { CascadeHeader, ConfigGrid, ExploratoryPanel, MemoryPanel, PairExplorer, ThresholdPanel, type PairSel, type Role } from "@/components/cascade";
import { SectionState } from "@/components/observatory";
import { EmptyState, PageTitle, Panel } from "@/components/ui";
import type { CascadeResp, Knowledge } from "@/lib/cascade";
import { usePoll } from "@/lib/hooks";

const SECTIONS: [string, string][] = [
  ["question", "Question"],
  ["grid", "Configuration grid"],
  ["threshold", "Threshold"],
  ["explorer", "Paired run explorer"],
  ["exploratory", "Exploratory C2x"],
  ["memory", "Research memory"],
];

/** Liquidation Cascade Laboratory: static C2/C2x artifacts, fetched once (interval 0); "Reload" re-reads them. */
export default function CascadePage() {
  const cas = usePoll<CascadeResp>("/api/observatory/cascade", 0);
  const know = usePoll<Knowledge>("/api/observatory/knowledge", 0);
  const [sel, setSel] = useState<PairSel | null>(null);
  const reload = () => [cas, know].forEach((p) => p.refresh());

  const explore = (role: Role) => (config: string) => {
    const idx = cas.data?.[role]?.run_index ?? [];
    const seed = idx.filter((r) => r.config === config).map((r) => r.seed).sort((a, b) => a - b)[0];
    setSel({ role, config, seed });
    document.getElementById("explorer")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="space-y-4">
      <PageTitle title="Liquidation Cascade Laboratory">
        <Link href="/observatory" prefetch={false} className="btn btn-sm">
          ← Observatory
        </Link>
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
      <SectionState poll={cas} what="cascade study">
        {(d) => (
          <>
            <CascadeHeader d={d} />
            <Panel
              id="grid"
              title="Configuration grid — whale size × leverage_use (confirmatory)"
              subtitle="Pre-registered classification per configuration over 8 paired seeds. Badge colours: grey = no secondary liquidations, amber = secondary liquidations without amplification / amplification without chain, red = cascade."
            >
              {d.confirmatory ? (
                <ConfigGrid rep={d.confirmatory} role="confirmatory" onExplore={explore("confirmatory")} />
              ) : (
                <EmptyState title="Confirmatory report: not produced yet" />
              )}
              {d.pilot && (
                <details className="mt-4 rounded border border-warn/40 p-2">
                  <summary className="cursor-pointer text-xs font-semibold text-warn">EXPLORATORY PILOT (seed {d.pilot.run_index[0]?.seed ?? "?"}) — feasibility only, not used in any confirmatory statistic</summary>
                  <div className="mt-2">
                    <ConfigGrid rep={d.pilot} role="pilot" onExplore={explore("pilot")} />
                  </div>
                </details>
              )}
            </Panel>
            <Panel id="threshold" title="Threshold (H2 onset, H3 shape) — confirmatory" subtitle="Per leverage_use: onset bracket = (largest size with 0/8, smallest size with ≥ 2/8). Sizes are nominal; the reached whale position is shown next to them (amendment_2).">
              {d.confirmatory?.threshold ? <ThresholdPanel th={d.confirmatory.threshold} configs={d.confirmatory.configs} /> : <EmptyState title="No threshold analysis yet" />}
            </Panel>
            <Panel id="explorer" title="Paired run explorer" subtitle="Arms A and B of one (configuration, seed) share everything except the secondary-liquidation execution switch.">
              <PairExplorer d={d} sel={sel} setSel={setSel} />
            </Panel>
            <Panel id="exploratory" title="Exploratory follow-up C2x — positioning explanation" subtitle="EXPLORATORY: same seeds as the confirmatory study, so not independent evidence; counterfactual model variants, never promoted.">
              <ExploratoryPanel d={d} onExplore={explore("exploratory")} />
            </Panel>
          </>
        )}
      </SectionState>
      <Panel id="memory" title="Research memory" subtitle="Mechanisms, simulator gaps, proposals and the next-experiment ranking recorded after C2/C2x.">
        <MemoryPanel poll={know} />
      </Panel>
    </div>
  );
}
