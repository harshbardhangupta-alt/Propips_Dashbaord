import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { Empty, ErrorBox, Modal, Notice, Pill, Spinner, Tabs } from "../components/ui";
import { money, num, time, tone } from "../lib/format";

const VIEWS = {
  open: { label: "Open", status: "OPEN" },
  waiting: { label: "Waiting for entry", status: "PENDING_ENTRY,CONFIGURED" },
  closed: { label: "Closed", status: "CLOSED" },
  other: { label: "Cancelled / rejected", status: "CANCELLED,EXPIRED,REJECTED" },
} as const;
type ViewKey = keyof typeof VIEWS;
const STRAT: Record<string, string> = { DASHBOARD1_MTF: "MTF", DASHBOARD2_MECHANICAL: "Swing" };
const STATUS: Record<string, string> = { OPEN: "Open", PENDING_ENTRY: "Waiting", CONFIGURED: "Paused", CLOSED: "Closed", CANCELLED: "Cancelled", EXPIRED: "Expired", REJECTED: "Rejected" };
const EXIT: Record<string, string> = { TAKE_PROFIT: "Target hit", TAKE_PROFIT_GAP: "Target hit (gap)", STOP_LOSS: "Stop hit", STOP_LOSS_GAP: "Stop hit (gap)", MANUAL_EXIT: "Closed by you" };

export default function Trades() {
  const [view, setView] = useState<ViewKey>("open");
  const [detail, setDetail] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["trades", view], queryFn: () => api(`/api/paper/trades?status=${VIEWS[view].status}`), refetchInterval: 10000 });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api("/api/paper/accounts"), refetchInterval: 15000 });
  const rows: any[] = q.data?.trades ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">My Trades</h1>
        <p className="mt-1 text-sm text-fg-muted">All trades are simulated paper trades.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {accounts.data?.accounts?.map((a: any) => (
          <div key={a.code} className="rounded-xl border border-ink-line bg-ink-panel p-4">
            <div className="text-sm text-fg-muted">{a.code === "D1_MTF" ? "MTF account" : "Swing account"}</div>
            <div className="mt-2 flex flex-wrap gap-x-8 gap-y-2">
              <div><div className="text-xs text-fg-faint">Total value</div><div className="num text-xl">{money(a.equity, 0)}</div></div>
              <div><div className="text-xs text-fg-faint">Cash available</div><div className="num text-xl">{money(a.available_cash, 0)}</div></div>
              <div><div className="text-xs text-fg-faint">Open P&L</div><div className={`num text-xl ${tone(a.unrealized_pnl)}`}>{money(a.unrealized_pnl)}</div></div>
              <div><div className="text-xs text-fg-faint">Realized P&L</div><div className={`num text-xl ${tone(a.net_realized_pnl)}`}>{money(a.net_realized_pnl)}</div></div>
              <div><div className="text-xs text-fg-faint">Won / lost</div><div className="num text-xl">{a.winning_trades} / {a.losing_trades}</div></div>
            </div>
          </div>
        ))}
      </div>
      <Tabs value={view} onChange={setView} items={(Object.keys(VIEWS) as ViewKey[]).map((k) => ({ id: k, label: VIEWS[k].label }))} />
      {q.isLoading ? <Spinner /> : q.isError ? <ErrorBox error={q.error} /> : rows.length === 0 ? (
        <div className="rounded-xl border border-ink-line"><Empty title="No trades here" /></div>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Stock</th><th>Strategy</th><th>Status</th><th className="text-right">Shares</th><th className="text-right">Buy</th><th className="text-right">Stop / Target</th><th className="text-right">{view === "closed" ? "Sold at" : "Now"}</th><th className="text-right">P&L</th><th></th></tr></thead>
            <tbody>
              {rows.map((t) => {
                const pnl = t.net_pnl ?? t.unrealized_pnl;
                return (
                  <tr key={t.id} className="cursor-pointer" onClick={() => setDetail(t.id)}>
                    <td className="font-medium">{t.symbol}</td>
                    <td className="text-fg-muted">{STRAT[t.strategy]}</td>
                    <td><Pill value={t.status}>{t.exit_reason ? EXIT[t.exit_reason] ?? STATUS[t.status] : STATUS[t.status]}</Pill></td>
                    <td className="num text-right">{t.filled_qty || t.planned_qty}</td>
                    <td className="num text-right">{num(t.entry_price ?? t.planned_entry)}</td>
                    <td className="num text-right text-fg-muted">{num(t.stop_loss)} / {num(t.target)}</td>
                    <td className="num text-right">{num(view === "closed" ? t.exit_price : t.last_price)}</td>
                    <td className={`num text-right ${tone(pnl)}`}>{pnl != null ? money(pnl) : "—"}</td>
                    <td className="text-right"><span className="text-xs text-fg-faint">Details →</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {detail !== null && <TradeDetail id={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

function TradeDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["trade", id], queryFn: () => api(`/api/paper/trades/${id}`), refetchInterval: 10000 });
  const act = useMutation({ mutationFn: (a: { path: string; body?: unknown }) => api(`/api/paper/trades/${id}/${a.path}`, { method: "POST", body: a.body }), onSuccess: () => qc.invalidateQueries() });
  const t = q.data;
  const rows: [string, string][] = t ? [
    ["Strategy", STRAT[t.strategy] + (t.is_overridden ? " (levels changed manually)" : "")],
    ["Amount set aside", money(t.allocation)],
    ["Planned buy", num(t.planned_entry)],
    ["Stop loss / target", `${num(t.stop_loss)} / ${num(t.target)}`],
    ["Shares", String(t.filled_qty || t.planned_qty)],
    ["Bought at", t.entry_price ? `${num(t.entry_price)} · ${time(t.entry_at)}` : "—"],
    ["Sold at", t.exit_price ? `${num(t.exit_price)} · ${time(t.exit_at)}` : "—"],
    ["Charges (est.)", money(t.charges)],
    ["P&L", money(t.net_pnl ?? t.unrealized_pnl)],
  ] : [];
  return (
    <Modal open onClose={onClose} title={t ? <div className="flex items-center gap-3"><span className="text-lg font-semibold">{t.symbol}</span><Pill value={t.status}>{STATUS[t.status]}</Pill></div> : "Trade"}>
      {!t ? <Spinner /> : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-y-1.5 text-sm">
            {rows.map(([k, v]) => <div key={k} className="contents"><span className="text-fg-muted">{k}</span><span className="num text-right">{v}</span></div>)}
          </div>
          {t.rejection_reason && <Notice tone="muted">{t.rejection_reason}</Notice>}
          <div className="flex flex-wrap gap-2">
            {t.status === "OPEN" && <button className="btn-danger btn-sm" onClick={() => window.confirm(`Close the paper position in ${t.symbol} at the current price?`) && act.mutate({ path: "manual-exit", body: { confirm: true } })}>Close position now</button>}
            {t.status === "PENDING_ENTRY" && <button className="btn-ghost btn-sm" onClick={() => act.mutate({ path: "disable-auto" })}>Pause</button>}
            {t.status === "CONFIGURED" && <button className="btn-ghost btn-sm" onClick={() => act.mutate({ path: "enable-auto" })}>Resume</button>}
            {["PENDING_ENTRY", "CONFIGURED"].includes(t.status) && <button className="btn-danger btn-sm" onClick={() => act.mutate({ path: "cancel" })}>Cancel trade</button>}
          </div>
          {act.isError && <ErrorBox error={act.error} />}
          <details className="text-sm">
            <summary className="cursor-pointer text-fg-faint">History</summary>
            <ol className="mt-2 space-y-1.5">
              {t.events.map((e: any) => <li key={e.id} className="text-fg-muted"><span className="num text-xs text-fg-faint">{time(e.at)}</span> — {e.message}</li>)}
            </ol>
          </details>
        </div>
      )}
    </Modal>
  );
}
