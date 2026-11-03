"use client";
import { useCallback, useEffect, useState } from "react";
import { PageTitle } from "@/components/ui";
import { CommandCenter, ControlsPanel, CyclesPanel, DiscoveriesPanel, EvolutionPanel, MemoryPanel, PolicyBanner, PredictivePanel } from "@/components/army";
import { apiPost, errorMessage } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import type {
  ArmyCycle,
  ArmyForecast,
  ArmySource,
  ControlIn,
  ControlResp,
  CycleResp,
  Edge,
  JournalResp,
  LineageResp,
  MemoryResp,
  Proposal,
  RolesResp,
} from "@/lib/army";
import type { ProspectiveResp } from "@/lib/forecast";

const SECTIONS: [string, string][] = [
  ["agents", "Agent Command Center"],
  ["cycles", "Cycles & tasks"],
  ["discoveries", "Discoveries"],
  ["evolution", "Strategy Evolution"],
  ["predictive", "Predictive Performance"],
  ["memory", "Scientific Memory"],
  ["controls", "Controls"],
];

/**
 * Research Army Control Center: the 24-role research army, its durable cycles, discoveries, lineage, memory and human
 * controls. Everything is read from /api/army/*; the only writes are explicit human control actions (POST /api/army/control).
 */
export default function ResearchArmyPage() {
  const roles = usePoll<RolesResp>("/api/army/roles", 5000);
  const cycles = usePoll<ArmyCycle[]>("/api/army/cycles", 10000);
  const sources = usePoll<ArmySource[]>("/api/army/sources", 30000);
  const memory = usePoll<MemoryResp>("/api/army/memory", 30000);
  const graph = usePoll<Edge[]>("/api/army/graph", 30000);
  const proposals = usePoll<Proposal[]>("/api/army/proposals", 30000);
  const forecast = usePoll<ArmyForecast>("/api/army/forecast", 60000);
  const prospective = usePoll<ProspectiveResp>("/api/forecast/prospective", 60000);
  const journal = usePoll<JournalResp>("/api/army/journal?limit=200", 15000);
  const control = usePoll<ControlResp>("/api/army/control", 5000);

  // selected cycle: defaults to the newest one
  const [cycle, setCycle] = useState("");
  useEffect(() => {
    const cs = cycles.data;
    if (!cs?.length || (cycle && cs.some((c) => c.id === cycle))) return;
    setCycle(cs[0].id);
  }, [cycles.data, cycle]);
  const running = cycles.data?.find((c) => c.id === cycle)?.status === "running";
  const detail = usePoll<CycleResp>(cycle ? `/api/army/cycle/${encodeURIComponent(cycle)}` : null, running ? 4000 : 20000);

  // selected hypothesis for the lineage view: defaults to the most recently updated one
  const [hyp, setHyp] = useState("");
  useEffect(() => {
    const hs = memory.data?.hypotheses;
    if (!hs?.length || (hyp && hs.some((h) => h.id === hyp))) return;
    setHyp(hs[0].id);
  }, [memory.data, hyp]);
  const lineage = usePoll<LineageResp>(hyp ? `/api/army/lineage/${encodeURIComponent(hyp)}` : null, 30000);

  const [node, setNode] = useState("");
  const nodeEdges = usePoll<Edge[]>(node ? `/api/army/graph?node=${encodeURIComponent(node)}` : "/api/army/graph", 30000);

  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const { refresh: refreshControl } = control;
  const { refresh: refreshJournal } = journal;
  const { refresh: refreshCycles } = cycles;
  const send = useCallback(
    async (body: ControlIn, confirmText?: string) => {
      if (confirmText && !window.confirm(confirmText)) return;
      setBusy(true);
      setMsg(null);
      try {
        await apiPost<ControlResp>("/api/army/control", body);
        setMsg({ ok: true, text: `Recorded: ${body.action}${body.key ? ` ${body.key} = ${JSON.stringify(body.value)}` : ""}` });
      } catch (e) {
        setMsg({ ok: false, text: errorMessage(e) });
      } finally {
        setBusy(false);
        refreshControl();
        refreshJournal();
        if (body.action === "run_cycle") refreshCycles();
      }
    },
    [refreshControl, refreshJournal, refreshCycles],
  );

  const reload = () => [roles, cycles, sources, memory, graph, proposals, forecast, prospective, journal, control, detail, lineage, nodeEdges].forEach((p) => p.refresh());

  return (
    <div className="space-y-4">
      <PageTitle title="Research Army Control Center">
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
      <PolicyBanner roles={roles.data} />
      <CommandCenter roles={roles} />
      <CyclesPanel cycles={cycles} selected={cycle} setSelected={setCycle} detail={detail} />
      <DiscoveriesPanel sources={sources} />
      <EvolutionPanel memory={memory} sources={sources} graph={graph} detail={detail} selectedHyp={hyp} setSelectedHyp={setHyp} lineage={lineage} />
      <PredictivePanel army={forecast} prospective={prospective} />
      <MemoryPanel memory={memory} edges={nodeEdges} node={node} setNode={setNode} allEdges={graph.data} />
      <ControlsPanel control={control} proposals={proposals} journal={journal} send={send} busy={busy} msg={msg} />
    </div>
  );
}
