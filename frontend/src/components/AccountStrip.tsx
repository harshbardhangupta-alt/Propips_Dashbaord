import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { money, tone } from "../lib/format";

/** Compact account summary: just the numbers people check most. */
export function AccountStrip({ code }: { code: "D1_MTF" | "D2_MECH" }) {
  const q = useQuery({ queryKey: ["accounts"], queryFn: () => api("/api/paper/accounts"), refetchInterval: 15000 });
  const a = q.data?.accounts?.find((x: any) => x.code === code);
  if (!a) return null;
  const items: [string, string, string?][] = [
    ["Paper cash available", money(a.available_cash, 0)],
    ["Open positions", `${a.open_positions}${a.pending_entries ? ` · ${a.pending_entries} waiting` : ""}`],
    ["Open P&L", money(a.unrealized_pnl), tone(a.unrealized_pnl)],
    ["Realized P&L", money(a.net_realized_pnl), tone(a.net_realized_pnl)],
  ];
  return (
    <div className="flex flex-wrap gap-x-10 gap-y-3">
      {items.map(([k, v, t]) => (
        <div key={k}>
          <div className="text-xs text-fg-faint">{k}</div>
          <div className={`num text-lg ${t ?? ""}`}>{v}</div>
        </div>
      ))}
    </div>
  );
}
