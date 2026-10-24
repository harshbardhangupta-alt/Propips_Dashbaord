import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { Empty, ErrorBox, KV, Modal, Notice, Panel, Pill, Spinner, Stat, Tabs } from "../components/ui";
import { money, num, time, tone } from "../lib/format";

const VIEWS = {
  pending: { label: "Pending entries", status: "PENDING_ENTRY,CONFIGURED" },
  open: { label: "Open positions", status: "OPEN" },
  closed: { label: "Closed", status: "CLOSED" },
  rejected: { label: "Rejected", status: "REJECTED" },
  cancelled: { label: "Cancelled / expired", status: "CANCELLED,EXPIRED" },
  all: { label: "All", status: "" },
} as const;
type ViewKey = keyof typeof VIEWS;
const STRAT: Record<string, string> = { DASHBOARD1_MTF: "D1 · MTF", DASHBOARD2_MECHANICAL: "D2 · Mechanical" };

export default function PaperTradeBook() {
  const [view, setView] = useState<ViewKey>("open");
  const [strategy, setStrategy] = useState("");
  const [symbol, setSymbol] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [detail, setDetail] = useState<number | null>(null);
  const params = new URLSearchParams();
  if (VIEWS[view].status) params.set("status", VIEWS[view].status);
  if (strategy) params.set("strategy", strategy);
  if (symbol) params.set("symbol", symbol);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const q = useQuery({ queryKey: ["trades", params.toString()], queryFn: () => api(`/api/paper/trades?${params}`), refetchInterval: 10000 });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api("/api/paper/accounts") });
  const rows: any[] = q.data?.trades ?? [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Paper Trade Book</h1>
        <p className="mt-1 text-sm text-fg-muted">Every row is a simulated paper trade. Manual exits change only the paper ledger — never a broker position.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {accounts.data?.accounts?.map((a: any) => (
          <div key={a.code} className="panel px-5 py-4 grid grid-cols-3 gap-4 md:grid-cols-6">
            <Stat label={a.code === "D1_MTF" ? "D1 · MTF" : "D2 · Mechanical"} value={money(a.equity, 0)} hint="paper equity" />
            <Stat label="Available" value={money(a.available_cash, 0)} />
            <Stat label="Unrealized" value={money(a.unrealized_pnl)} toneClass={tone(a.unrealized_pnl)} />
            <Stat label="Gross realized" value={money(a.realized_gross_pnl)} toneClass={tone(a.realized_gross_pnl)} />
            <Stat label="Net realized" value={money(a.net_realized_pnl)} toneClass={tone(a.net_realized_pnl)} />
            <Stat label="Open / pending" value={`${a.open_positions} / ${a.pending_entries}`} />
          </div>
        ))}
      </div>
      <Panel pad={false}>
        <div className="flex flex-wrap items-center gap-3 px-5 py-4 border-b border-ink-line/70">
          <Tabs value={view} onChange={setView} items={(Object.keys(VIEWS) as ViewKey[]).map((k) => ({ id: k, label: VIEWS[k].label }))} />
          <select className="input !w-auto" value={strategy} onChange={(e) => setStrategy(e.target.value)}><option value="">All strategies</option><option value="DASHBOARD1_MTF">Dashboard 1 · MTF</option><option value="DASHBOARD2_MECHANICAL">Dashboard 2 · Mechanical</option></select>
          <input className="input !w-36" placeholder="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} />
          <input className="input !w-auto" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <input className="input !w-auto" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          {q.data && <span className="ml-auto text-xs text-fg-muted">Net P&L (closed in view) <span className={`num ${tone(q.data.summary.net_pnl)}`}>{money(q.data.summary.net_pnl)}</span> · {q.data.summary.wins}W/{q.data.summary.losses}L</span>}
        </div>
        {q.isLoading ? <div className="p-10 text-center"><Spinner /></div> : q.isError ? <div className="p-5"><ErrorBox error={q.error} /></div> : rows.length === 0 ? <Empty title="No paper trades in this view" /> : (
          <div className="table-wrap !rounded-none !border-0 max-h-[68vh]">
            <table className="data">
              <thead><tr>
                <th>ID</th><th>Strategy</th><th>Symbol</th><th>Status</th><th>Entry time</th><th className="text-right">Entry</th><th className="text-right">Qty</th><th className="text-right">Allocation</th><th className="text-right">Stop</th><th className="text-right">Target</th>
                <th>Exit time</th><th className="text-right">Exit</th><th>Exit reason</th><th className="text-right">Gross P&L</th><th className="text-right">Est. costs</th><th className="text-right">Net / Unrl.</th><th></th>
              </tr></thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id} className="cursor-pointer" onClick={() => setDetail(t.id)}>
                    <td className="num text-fg-muted">#{t.id}</td>
                    <td className="text-xs">{STRAT[t.strategy]}{t.is_overridden && <span className="ml-1"><Pill tone="warn">OVR</Pill></span>}</td>
                    <td className="font-medium">{t.symbol}</td>
                    <td><Pill value={t.status} /></td>
                    <td className="text-xs text-fg-muted">{time(t.entry_at)}</td>
                    <td className="num text-right">{t.entry_price ? num(t.entry_price) : <span className="text-fg-faint">{num(t.planned_entry)}*</span>}</td>
                    <td className="num text-right">{t.filled_qty || <span className="text-fg-faint">{t.planned_qty}*</span>}</td>
                    <td className="num text-right">{money(t.allocation, 0)}</td>
                    <td className="num text-right">{num(t.stop_loss)}</td>
                    <td className="num text-right">{num(t.target)}</td>
                    <td className="text-xs text-fg-muted">{time(t.exit_at)}</td>
                    <td className="num text-right">{num(t.exit_price)}</td>
                    <td>{t.exit_reason ? <Pill value={t.exit_reason} /> : "—"}</td>
                    <td className={`num text-right ${tone(t.gross_pnl)}`}>{t.gross_pnl != null ? money(t.gross_pnl) : "—"}</td>
                    <td className="num text-right text-fg-muted">{t.charges ? money(t.charges) : "—"}</td>
                    <td className={`num text-right ${tone(t.net_pnl ?? t.unrealized_pnl)}`}>{t.net_pnl != null ? money(t.net_pnl) : t.unrealized_pnl != null ? `${money(t.unrealized_pnl)} u` : "—"}</td>
                    <td className="text-right"><button className="btn-ghost btn-sm">Details</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="px-5 py-2 text-[11px] text-fg-faint">* planned (not yet filled). All values simulated.</div>
          </div>
        )}
      </Panel>
      {detail !== null && <TradeDetail id={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

function TradeDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["trade", id], queryFn: () => api(`/api/paper/trades/${id}`), refetchInterval: 10000 });
  const [confirmExit, setConfirmExit] = useState(false);
  const act = useMutation({
    mutationFn: (a: { path: string; body?: unknown }) => api(`/api/paper/trades/${id}/${a.path}`, { method: "POST", body: a.body }),
    onSuccess: () => { qc.invalidateQueries(); setConfirmExit(false); },
  });
  const t = q.data;
  return (
    <Modal open onClose={onClose} wide title={t ? <div className="flex items-center gap-3"><span className="text-lg font-semibold">#{t.id} · {t.symbol}</span><Pill value={t.status} /><span className="text-xs text-fg-faint">{STRAT[t.strategy]} · simulated</span></div> : "Trade"}>
      {!t ? <Spinner /> : (
        <div className="grid gap-6 lg:grid-cols-[320px,1fr]">
          <div className="space-y-4">
            <KV rows={[
              ["Entry trigger", t.entry_trigger.replace(/_/g, " ").toLowerCase()],
              ["Planned entry", num(t.planned_entry)], ["Stop", num(t.stop_loss)], ["Target", num(t.target)],
              ["Allocation", money(t.allocation)], ["Planned qty", t.planned_qty], ["Planned risk", money(t.planned_risk)], ["R:R", `1:${t.reward_risk}`],
              ["Reserved", money(t.reserved_amount)], ["Filled qty", t.filled_qty], ["Entry price", num(t.entry_price)], ["Exit price", num(t.exit_price)],
              ["Gross P&L", money(t.gross_pnl)], ["Est. charges", money(t.charges)], ["Est. slippage", money(t.slippage_cost)], ["Net P&L", money(t.net_pnl)],
              ["Unrealized", money(t.unrealized_pnl)], ["Last price", `${num(t.last_price)} · ${time(t.last_price_at)}`], ["Valid until", time(t.valid_until)],
              ["Auto entry", t.auto_entry_enabled ? "enabled" : "disabled"],
            ]} />
            {t.is_overridden && <Notice tone="warn">Overridden levels. Original strategy values: {JSON.stringify(t.original_values)}</Notice>}
            {t.rejection_reason && <Notice tone="bad">{t.rejection_reason}</Notice>}
            <div className="flex flex-wrap gap-2">
              {t.status === "PENDING_ENTRY" && <button className="btn-ghost btn-sm" onClick={() => act.mutate({ path: "disable-auto" })}>Disable auto entry</button>}
              {t.status === "CONFIGURED" && <button className="btn-ghost btn-sm" onClick={() => act.mutate({ path: "enable-auto" })}>Re-enable auto entry</button>}
              {t.status === "OPEN" && t.auto_entry_enabled && <button className="btn-ghost btn-sm" onClick={() => act.mutate({ path: "disable-auto" })}>Disable future auto entries</button>}
              {["PENDING_ENTRY", "CONFIGURED"].includes(t.status) && <button className="btn-danger btn-sm" onClick={() => act.mutate({ path: "cancel" })}>Cancel</button>}
              {t.status === "OPEN" && !confirmExit && <button className="btn-danger btn-sm" onClick={() => setConfirmExit(true)}>Manual paper exit…</button>}
            </div>
            {confirmExit && (
              <Notice tone="warn">
                Close this PAPER position at the latest verified price (minus simulated slippage)? This affects only the paper ledger.
                <div className="mt-2 flex gap-2"><button className="btn-danger btn-sm" onClick={() => act.mutate({ path: "manual-exit", body: { confirm: true } })}>Confirm paper exit</button><button className="btn-ghost btn-sm" onClick={() => setConfirmExit(false)}>Keep open</button></div>
              </Notice>
            )}
            {act.isError && <ErrorBox error={act.error} />}
          </div>
          <div className="space-y-5 min-w-0">
            <div>
              <div className="label mb-2">Simulated executions</div>
              {t.executions.length === 0 ? <div className="text-sm text-fg-faint">No simulated fills yet.</div> : (
                <div className="table-wrap"><table className="data"><thead><tr><th>Side</th><th className="text-right">Qty</th><th className="text-right">Price</th><th className="text-right">Ref.</th><th className="text-right">Charges</th><th>Reason</th><th>Time</th><th>Source</th></tr></thead>
                  <tbody>{t.executions.map((x: any) => (
                    <tr key={x.id}><td><Pill tone={x.side === "BUY" ? "neon" : "muted"}>{x.side} · SIM</Pill></td><td className="num text-right">{x.qty}</td><td className="num text-right">{num(x.price)}</td><td className="num text-right text-fg-muted">{num(x.reference_price)}</td><td className="num text-right">{money(x.charges)}</td><td><Pill value={x.reason} /></td><td className="text-xs">{time(x.executed_at)}</td><td className="text-xs text-fg-faint">{x.data_source}</td></tr>
                  ))}</tbody></table></div>
              )}
            </div>
            <div>
              <div className="label mb-2">Event history</div>
              <ol className="space-y-2 border-l border-ink-line pl-4">
                {t.events.map((e: any) => (
                  <li key={e.id} className="text-sm"><span className="text-xs text-fg-faint num">{time(e.at)}</span> <Pill value={e.event} /> <span className="text-fg-muted">{e.message}</span></li>
                ))}
              </ol>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
