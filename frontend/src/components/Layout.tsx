import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import { ago } from "../lib/format";
import { PaperBadge } from "./PaperBadge";
import { Pill } from "./ui";
import { useAccount } from "../lib/account";

const NAV = [
  { to: "/", label: "MTF Paper Trading", sub: "Dashboard 1 · Nifty 100" },
  { to: "/scanner", label: "Mechanical Swing", sub: "Dashboard 2 · Nifty 250" },
  { to: "/book", label: "Paper Trade Book", sub: "Pending · Open · Closed" },
  { to: "/history", label: "Trade History", sub: "Simulated performance" },
  { to: "/settings", label: "Settings & API", sub: "Dhan · OpenAI · Universes" },
  { to: "/system", label: "System Status", sub: "Jobs · Data · Audit" },
];

export function Layout() {
  const status = useQuery({ queryKey: ["system-status"], queryFn: () => api("/api/system/status"), refetchInterval: 15000 });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api("/api/paper/accounts"), refetchInterval: 15000 });
  const [account, setAccount] = useAccount();
  const s = status.data;
  const acc = accounts.data?.accounts?.find((a: any) => a.code === account);

  return (
    <div className="flex min-h-full">
      <aside className="hidden lg:flex w-64 shrink-0 flex-col border-r border-ink-line bg-ink">
        <div className="px-5 pt-6 pb-5">
          <div className="flex items-center gap-2.5">
            <div className="h-7 w-7 rounded-md bg-neon text-ink grid place-items-center text-xs font-bold">PT</div>
            <div>
              <div className="text-sm font-semibold tracking-tight">Paper Terminal</div>
              <div className="text-[11px] text-fg-faint">NSE · simulated execution</div>
            </div>
          </div>
        </div>
        <nav className="flex-1 px-3 space-y-0.5">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end className={({ isActive }) => `block rounded-lg px-3 py-2.5 transition ${isActive ? "bg-white/[0.05] text-fg" : "text-fg-muted hover:text-fg hover:bg-white/[0.02]"}`}>
              {({ isActive }) => (
                <div className="flex items-center gap-3">
                  <span className={`h-4 w-0.5 rounded-full ${isActive ? "bg-neon" : "bg-transparent"}`} />
                  <div>
                    <div className="text-sm font-medium">{n.label}</div>
                    <div className="text-[11px] text-fg-faint">{n.sub}</div>
                  </div>
                </div>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="p-5 text-[11px] leading-relaxed text-fg-faint">
          All orders, fills and P&L are simulated. No broker order endpoint exists in this application.
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-40 border-b border-ink-line bg-ink/85 backdrop-blur">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
            <PaperBadge />
            <div className="flex items-center gap-2 text-xs text-fg-muted">
              <span className="text-fg-faint">Dhan</span>
              <Pill value={s?.dhan?.status ?? (status.isError ? "ERROR" : "…")} />
              {s?.dhan?.token_reminder_due && <Pill tone="warn">Token &gt; 24h old</Pill>}
            </div>
            <div className="flex items-center gap-2 text-xs text-fg-muted">
              <span className="text-fg-faint">Market data</span>
              <Pill value={s?.market_data?.state ?? "NO_DATA"} />
              <span className="num">{s?.market_data?.newest_quote_at ? ago(s.market_data.newest_quote_at) : "no quotes yet"}</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-fg-muted">
              <span className="text-fg-faint">NSE</span>
              <Pill tone={s?.market_open ? "good" : "muted"}>{s ? (s.market_open ? "MARKET OPEN" : s.holiday ? `CLOSED · ${s.holiday}` : "CLOSED") : "…"}</Pill>
            </div>
            <div className="ml-auto flex items-center gap-2 text-xs">
              <span className="text-fg-faint">Paper account</span>
              <select className="input !py-1 !text-xs !w-auto" value={account} onChange={(e) => setAccount(e.target.value as any)}>
                <option value="D1_MTF">Dashboard 1 — MTF</option>
                <option value="D2_MECH">Dashboard 2 — Mechanical</option>
              </select>
              {acc && <span className="num text-fg">₹{Math.round(acc.available_cash).toLocaleString("en-IN")} <span className="text-fg-faint">available</span></span>}
            </div>
          </div>
          {status.isError && <div className="px-5 pb-2 text-xs text-down">Backend unreachable — start the API (see README).</div>}
        </header>
        <nav className="lg:hidden flex gap-1 overflow-x-auto px-3 py-2 border-b border-ink-line">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end className={({ isActive }) => `tab whitespace-nowrap ${isActive ? "tab-active" : ""}`}>{n.label}</NavLink>
          ))}
        </nav>
        <main className="flex-1 min-w-0 px-5 py-6 max-w-[1680px] w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
