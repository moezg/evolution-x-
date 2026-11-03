"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { usePoll } from "@/lib/hooks";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/agents", label: "Agents" },
  { href: "/collective", label: "Collective" },
  { href: "/observatory", label: "Observatory" },
  { href: "/observatory/cascade", label: "Cascade Lab" },
  { href: "/evolution", label: "Evolution" },
  { href: "/scenarios", label: "Scenarios" },
  { href: "/council", label: "Council" },
  { href: "/research", label: "Research" },
];

interface Health {
  ok: boolean;
  engine_version: string;
  mode: string;
  real_trading: boolean;
}

export function Header() {
  const path = usePathname() || "/";
  const health = usePoll<Health>("/api/health", 15000);
  const ok = health.data?.ok && !health.error;
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-page/95 backdrop-blur">
      <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
        <Link href="/" prefetch={false} className="flex items-baseline gap-2 font-semibold tracking-[0.18em] text-ink">
          <span aria-hidden className="text-accent">◆</span>
          EVOLUTION&nbsp;X
        </Link>
        <span
          className="rounded-full border border-warn/60 bg-warn/10 px-2.5 py-0.5 text-[11px] font-bold tracking-wider text-warn"
          title="All markets are simulated. There is no connection to any real exchange."
        >
          RESEARCH-ONLY · NO REAL TRADING
        </span>
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted" role="status" aria-live="polite">
          <span
            aria-hidden
            className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-up" : health.loading ? "bg-muted" : "bg-down"}`}
          />
          {ok ? `engine v${health.data?.engine_version}` : health.loading ? "connecting…" : "backend offline"}
        </span>
        <nav aria-label="Primary" className="-mx-1 flex w-full gap-1 overflow-x-auto pb-0.5">
          {NAV.map((n) => {
            // Longest matching prefix wins, so /observatory/cascade does not also highlight /observatory.
            const matches = (h: string) => (h === "/" ? path === "/" : path === h || path.startsWith(h + "/"));
            const best = NAV.filter((x) => matches(x.href)).sort((a, b) => b.href.length - a.href.length)[0];
            const active = best?.href === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                prefetch={false}
                aria-current={active ? "page" : undefined}
                className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${
                  active ? "bg-panel2 font-semibold text-ink ring-1 ring-line2" : "text-ink2 hover:bg-panel hover:text-ink"
                }`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
