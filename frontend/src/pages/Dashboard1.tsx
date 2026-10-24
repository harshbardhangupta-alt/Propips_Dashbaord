import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { AccountStrip } from "../components/AccountStrip";
import { AutoTradeModalD1 } from "../components/AutoTradeModalD1";
import { SetupNotice } from "../components/SetupNotice";
import { ErrorBox, Pill, Spinner } from "../components/ui";
import { num, pct, tone } from "../lib/format";

const TREND_LABEL: Record<string, string> = { BULLISH: "Bullish", BEARISH: "Bearish", NEUTRAL: "Neutral", UNAVAILABLE: "No data", NOT_EVALUATED: "—" };
const STATUS_LABEL: Record<string, string> = { PENDING_ENTRY: "Waiting for entry", OPEN: "Position open", CONFIGURED: "Paused" };

export default function Dashboard1() {
  const q = useQuery({ queryKey: ["d1-stocks"], queryFn: () => api("/api/d1/stocks"), refetchInterval: 20_000 });
  const [search, setSearch] = useState("");
  const [show, setShow] = useState("ALL");
  const [selected, setSelected] = useState<any | null>(null);
  const rows: any[] = q.data?.stocks ?? [];

  const view = useMemo(() => {
    const s = search.trim().toUpperCase();
    return rows
      .filter((r) => !s || r.symbol.includes(s) || r.company_name.toUpperCase().includes(s))
      .filter((r) => show === "ALL" || (show === "BULLISH" ? r.bias === "BULLISH" : show === "ACTIVE" ? !!r.trade : r.position_status === "OPEN"))
      .sort((a, b) => (b.quality ?? 0) - (a.quality ?? 0) || a.symbol.localeCompare(b.symbol));
  }, [rows, search, show]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">MTF Stocks</h1>
          <p className="mt-1 text-sm text-fg-muted">Nifty 100 · trend checked on Daily, 4-hour, 15-min and 5-min charts</p>
        </div>
        <AccountStrip code="D1_MTF" />
      </div>
      <SetupNotice universe="NIFTY100" />
      <div className="flex flex-wrap items-center gap-3">
        <input className="input !w-72" placeholder="Search stock…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select className="input !w-auto" value={show} onChange={(e) => setShow(e.target.value)}>
          <option value="ALL">All stocks</option>
          <option value="BULLISH">Bullish only</option>
          <option value="ACTIVE">Auto trade on</option>
          <option value="OPEN">Open positions</option>
        </select>
        <span className="text-xs text-fg-faint">{view.length} stocks</span>
      </div>
      {q.isLoading ? <Spinner /> : q.isError ? <ErrorBox error={q.error} /> : rows.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Stock</th><th className="text-right">Price</th><th className="text-right">Change</th><th>Trend</th><th>Timeframes aligned</th><th>Auto trade</th></tr></thead>
            <tbody>
              {view.map((r) => (
                <tr key={r.symbol} className="cursor-pointer" onClick={() => setSelected(r)}>
                  <td>
                    <div className="font-medium">{r.symbol}</div>
                    <div className="max-w-[260px] truncate text-xs text-fg-faint">{r.company_name}</div>
                  </td>
                  <td className="num text-right">{num(r.quote?.ltp)}</td>
                  <td className={`num text-right ${tone(r.quote?.pct_change)}`}>{pct(r.quote?.pct_change)}</td>
                  <td><Pill value={r.bias}>{TREND_LABEL[r.bias] ?? r.bias}</Pill></td>
                  <td>
                    <div className="flex items-center gap-2">
                      <div className="flex gap-0.5">{[0, 1, 2, 3].map((i) => <span key={i} className={`h-1.5 w-5 rounded-full ${i < (r.quality ?? 0) ? "bg-up" : "bg-white/10"}`} />)}</div>
                      <span className="num text-xs text-fg-faint">{r.quality ?? 0}/4</span>
                    </div>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {r.trade ? <Pill value={r.trade.status}>{STATUS_LABEL[r.trade.status] ?? r.trade.status}</Pill> : (
                      <button className="btn-ghost btn-sm" disabled={!r.security_id} onClick={() => setSelected(r)}>Set up</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selected && <AutoTradeModalD1 row={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
