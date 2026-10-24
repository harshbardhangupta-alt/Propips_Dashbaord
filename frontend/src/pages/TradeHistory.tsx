import { useQuery } from "@tanstack/react-query";
import { ColorType, createChart, LineSeries, UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";
import { api } from "../api/client";
import { Empty, ErrorBox, Panel, Pill, Spinner, Stat } from "../components/ui";
import { money, num, time, tone } from "../lib/format";

const STRATS = [
  { id: "DASHBOARD1_MTF", label: "Dashboard 1 · MTF", color: "#D9FF00" },
  { id: "DASHBOARD2_MECHANICAL", label: "Dashboard 2 · Mechanical Swing", color: "#7FB2FF" },
];

function stats(ts: any[]) {
  const wins = ts.filter((t) => t.net_pnl > 0);
  const losses = ts.filter((t) => t.net_pnl <= 0);
  const net = ts.reduce((a, t) => a + t.net_pnl, 0);
  const grossWin = wins.reduce((a, t) => a + t.net_pnl, 0);
  const grossLoss = -losses.reduce((a, t) => a + t.net_pnl, 0);
  return { n: ts.length, wins: wins.length, losses: losses.length, net, avgWin: wins.length ? grossWin / wins.length : null, avgLoss: losses.length ? -grossLoss / losses.length : null, pf: grossLoss > 0 ? grossWin / grossLoss : null, charges: ts.reduce((a, t) => a + (t.charges || 0), 0) };
}

export default function TradeHistory() {
  const q = useQuery({ queryKey: ["trades", "closed-history"], queryFn: () => api("/api/paper/trades?status=CLOSED&limit=2000"), refetchInterval: 30000 });
  const closed: any[] = useMemo(() => [...(q.data?.trades ?? [])].sort((a, b) => (a.exit_at < b.exit_at ? -1 : 1)), [q.data]);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || closed.length === 0) return;
    const chart = createChart(ref.current, {
      height: 260, autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#A3ADA6", fontFamily: "JetBrains Mono, monospace", fontSize: 11 },
      grid: { vertLines: { color: "rgba(245,247,245,0.04)" }, horzLines: { color: "rgba(245,247,245,0.04)" } },
      rightPriceScale: { borderColor: "rgba(245,247,245,0.08)" }, timeScale: { borderColor: "rgba(245,247,245,0.08)", timeVisible: true },
    });
    for (const s of STRATS) {
      let cum = 0;
      let last = 0;
      const pts = closed.filter((t) => t.strategy === s.id).map((t) => {
        cum += t.net_pnl;
        let ts = Math.floor(new Date(t.exit_at).getTime() / 1000) + 19800;
        if (ts <= last) ts = last + 1;
        last = ts;
        return { time: ts as UTCTimestamp, value: Math.round(cum * 100) / 100 };
      });
      if (pts.length) chart.addSeries(LineSeries, { color: s.color, lineWidth: 2, title: s.label }).setData(pts);
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [closed]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Trade History</h1>
        <p className="mt-1 text-sm text-fg-muted">Closed simulated paper trades by strategy. These results are paper simulations, not evidence of real-world profitability.</p>
      </div>
      {q.isLoading ? <Spinner /> : q.isError ? <ErrorBox error={q.error} /> : closed.length === 0 ? <Panel><Empty title="No closed paper trades yet">Closed trades and cumulative simulated net P&L appear here.</Empty></Panel> : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {STRATS.map((s) => {
              const st = stats(closed.filter((t) => t.strategy === s.id));
              return (
                <Panel key={s.id} title={<span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: s.color }} />{s.label}</span>}>
                  <div className="grid grid-cols-3 gap-4">
                    <Stat label="Net P&L (sim.)" value={money(st.net)} toneClass={tone(st.net)} />
                    <Stat label="Trades" value={st.n} hint={`${st.wins}W / ${st.losses}L`} />
                    <Stat label="Win share" value={st.n ? `${((st.wins / st.n) * 100).toFixed(0)}%` : "—"} hint={`sample of ${st.n}`} />
                    <Stat label="Avg win" value={money(st.avgWin)} toneClass="text-up" />
                    <Stat label="Avg loss" value={money(st.avgLoss)} toneClass="text-down" />
                    <Stat label="Profit factor" value={st.pf ? num(st.pf) : "—"} hint={`charges ${money(st.charges)}`} />
                  </div>
                </Panel>
              );
            })}
          </div>
          <Panel title="Cumulative simulated net P&L"><div ref={ref} className="w-full" /></Panel>
          <Panel pad={false} title="Closed trades">
            <div className="table-wrap !rounded-none !border-0 max-h-[50vh]">
              <table className="data">
                <thead><tr><th>ID</th><th>Strategy</th><th>Symbol</th><th>Entry</th><th className="text-right">Price</th><th>Exit</th><th className="text-right">Price</th><th className="text-right">Qty</th><th>Reason</th><th className="text-right">Gross</th><th className="text-right">Costs</th><th className="text-right">Net</th></tr></thead>
                <tbody>{[...closed].reverse().map((t) => (
                  <tr key={t.id}><td className="num text-fg-muted">#{t.id}</td><td className="text-xs">{t.strategy === "DASHBOARD1_MTF" ? "D1" : "D2"}</td><td className="font-medium">{t.symbol}</td><td className="text-xs">{time(t.entry_at)}</td><td className="num text-right">{num(t.entry_price)}</td><td className="text-xs">{time(t.exit_at)}</td><td className="num text-right">{num(t.exit_price)}</td><td className="num text-right">{t.filled_qty}</td><td><Pill value={t.exit_reason} /></td><td className={`num text-right ${tone(t.gross_pnl)}`}>{money(t.gross_pnl)}</td><td className="num text-right text-fg-muted">{money(t.charges)}</td><td className={`num text-right ${tone(t.net_pnl)}`}>{money(t.net_pnl)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
