import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import { PaperBadge } from "./PaperBadge";

const NAV = [
  { to: "/", label: "MTF Stocks" },
  { to: "/scanner", label: "Swing Scanner" },
  { to: "/trades", label: "My Trades" },
  { to: "/settings", label: "Settings" },
];

function Dot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-up" : warn ? "bg-warn" : "bg-down"}`} />;
}

export function Layout() {
  const status = useQuery({ queryKey: ["system-status"], queryFn: () => api("/api/system/status"), refetchInterval: 20000 });
  const s = status.data;
  const dhan = s?.dhan?.status;
  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-40 border-b border-ink-line bg-ink/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3">
          <div className="flex items-center gap-2">
            <div className="grid h-7 w-7 place-items-center rounded-md bg-neon text-xs font-bold text-ink">PT</div>
            <span className="font-semibold tracking-tight">Paper Terminal</span>
          </div>
          <nav className="flex gap-1">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end className={({ isActive }) => `rounded-md px-3 py-1.5 text-sm transition ${isActive ? "bg-white/[0.07] text-fg" : "text-fg-muted hover:text-fg"}`}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-4 text-xs text-fg-muted">
            <span className="flex items-center gap-1.5" title={s?.dhan?.detail?.message ?? ""}>
              <Dot ok={dhan === "CONNECTED"} warn={dhan === "UNTESTED" || dhan === "NOT_CONFIGURED"} />
              {dhan === "CONNECTED" ? "Dhan connected" : dhan === "NOT_CONFIGURED" ? "Dhan not set up" : dhan === "UNTESTED" ? "Dhan not tested" : status.isError ? "Backend offline" : `Dhan: ${(dhan ?? "…").replace(/_/g, " ").toLowerCase()}`}
            </span>
            <span className="flex items-center gap-1.5"><Dot ok={!!s?.market_open} warn={!s?.market_open} />{s?.market_open ? "Market open" : "Market closed"}</span>
            <PaperBadge />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-5 py-6">
        <Outlet />
      </main>
    </div>
  );
}
