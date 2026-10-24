import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { money, tone } from "../lib/format";
import { Stat } from "./ui";

export function AccountStrip({ code }: { code: "D1_MTF" | "D2_MECH" }) {
  const q = useQuery({ queryKey: ["accounts"], queryFn: () => api("/api/paper/accounts"), refetchInterval: 15000 });
  const a = q.data?.accounts?.find((x: any) => x.code === code);
  if (!a) return null;
  return (
    <div className="panel px-5 py-4 grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-5">
      <Stat label="Paper account" value={<span className="font-sans text-sm">{a.name}</span>} hint="Simulated balance" />
      <Stat label="Available cash" value={money(a.available_cash, 0)} hint={`of ${money(a.initial_capital, 0)} initial`} />
      <Stat label="Reserved" value={money(a.reserved, 0)} hint={`${a.pending_entries} pending entr${a.pending_entries === 1 ? "y" : "ies"}`} />
      <Stat label="Deployed" value={money(a.capital_deployed, 0)} hint={`${a.open_positions} open`} />
      <Stat label="Unrealized" value={money(a.unrealized_pnl)} toneClass={tone(a.unrealized_pnl)} />
      <Stat label="Net realized" value={money(a.net_realized_pnl)} toneClass={tone(a.net_realized_pnl)} hint={`charges ${money(a.estimated_charges)}`} />
      <Stat label="Equity" value={money(a.equity, 0)} />
      <Stat label="Closed trades" value={`${a.trade_count}`} hint={`${a.winning_trades}W / ${a.losing_trades}L · min RR 1:${a.limits.min_reward_risk}`} />
    </div>
  );
}
