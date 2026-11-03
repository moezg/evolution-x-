"use client";
import Link from "next/link";
import { PageTitle } from "@/components/ui";
import { Banner, CapabilityMatrix, ExperimentsSection, HowToRead, RealismSection, VolatilitySection } from "@/components/observatory";
import { usePoll } from "@/lib/hooks";
import type { Audit, ExperimentsResp, ObsIndex, RealismResp, VolatilityResp } from "@/lib/observatory";

const SECTIONS: [string, string][] = [
  ["capabilities", "Capabilities"],
  ["volatility", "Volatility diagnosis"],
  ["experiments", "Experiments A/B/C"],
  ["realism", "Realism track"],
  ["how-to-read", "How to read"],
];

/** Static research artifacts: fetched once (interval 0); "Reload" re-reads them. */
export default function ObservatoryPage() {
  const index = usePoll<ObsIndex>("/api/observatory/index", 0);
  const audit = usePoll<Audit>("/api/observatory/audit", 0);
  const vol = usePoll<VolatilityResp>("/api/observatory/volatility", 0);
  const exp = usePoll<ExperimentsResp>("/api/observatory/experiments", 0);
  const real = usePoll<RealismResp>("/api/observatory/realism", 0);
  const reload = () => [index, audit, vol, exp, real].forEach((p) => p.refresh());

  return (
    <div className="space-y-4">
      <PageTitle title="Emergent Behavior Observatory">
        <Link href="/observatory/cascade" prefetch={false} className="btn btn-sm">
          Liquidation Cascade Laboratory →
        </Link>
        <button type="button" className="btn btn-sm" onClick={reload}>
          Reload
        </button>
      </PageTitle>
      <Banner index={index} />
      <p className="text-xs text-ink2">
        Experiment C2 (liquidation cascades: whale size × leverage, paired arms, threshold, exploratory C2x and research memory) has its own view:{" "}
        <Link href="/observatory/cascade" prefetch={false} className="text-[#9ec5f4] underline">
          Liquidation Cascade Laboratory
        </Link>
        .
      </p>
      <nav aria-label="Sections" className="-mx-1 flex gap-1 overflow-x-auto px-1 text-xs">
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#${id}`} className="whitespace-nowrap rounded border border-line px-2 py-1 text-ink2 hover:bg-panel2 hover:text-ink">
            {label}
          </a>
        ))}
      </nav>
      <CapabilityMatrix poll={audit} />
      <VolatilitySection poll={vol} />
      <ExperimentsSection poll={exp} />
      <RealismSection poll={real} />
      <HowToRead labels={exp.data?.protocol.common?.labels} />
    </div>
  );
}
