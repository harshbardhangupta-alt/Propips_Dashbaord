import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { ChartPanel, LEVEL_COLORS } from "../charts/ChartPanel";
import { Level } from "../charts/PriceChart";
import { money, num } from "../lib/format";
import { useDebounced } from "../lib/useDebounced";
import { Field, Modal, Notice, Pill, Spinner } from "./ui";

const TF: [string, string][] = [["daily", "Daily"], ["h4", "4H"], ["m15", "15m"], ["m5", "5m"]];

function parse(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : NaN;
}

export function AutoTradeModalD1({ row, onClose }: { row: any; onClose: () => void }) {
  const qc = useQueryClient();
  const [amount, setAmount] = useState("");
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [trigger, setTrigger] = useState("CANDLE_CLOSE_ABOVE");
  const [fromLatest, setFromLatest] = useState(false);
  const [ack, setAck] = useState(false);
  const requestId = useMemo(() => crypto.randomUUID(), []);

  const triggers = useQuery({ queryKey: ["d1-triggers"], queryFn: () => api("/api/d1/triggers"), staleTime: Infinity });
  const mtf = useQuery({ queryKey: ["d1-mtf", row.symbol], queryFn: () => api(`/api/d1/stocks/${encodeURIComponent(row.symbol)}/mtf`) });

  const v = { amount: parse(amount), entry: parse(entry), stop: parse(stop), target: parse(target) };
  const complete = Object.values(v).every((x) => typeof x === "number" && !Number.isNaN(x));
  const body = complete
    ? { symbol: row.symbol, allocation: v.amount, entry: v.entry, stop_loss: v.stop, take_profit: v.target, entry_trigger: trigger, entry_source: fromLatest ? "LATEST_VERIFIED_PRICE" : "MANUAL" }
    : null;
  const debounced = useDebounced(body, 300);
  const preview = useQuery({ queryKey: ["d1-preview", debounced], queryFn: () => api("/api/d1/preview", { body: debounced }), enabled: !!debounced });
  const plan = preview.data?.plan;
  const create = useMutation({ mutationFn: () => api("/api/d1/trades", { body: { ...body, confirm: true, client_request_id: requestId } }), onSuccess: () => qc.invalidateQueries() });

  const ltp: number | null = row.quote?.ltp ?? null;
  const levels: Level[] = [];
  if (v.entry) levels.push({ label: "Entry", price: v.entry, color: LEVEL_COLORS.entry });
  if (v.stop) levels.push({ label: "Stop", price: v.stop, color: LEVEL_COLORS.stop });
  if (v.target) levels.push({ label: "Target", price: v.target, color: LEVEL_COLORS.target });
  const m = mtf.data;

  return (
    <Modal open onClose={onClose} wide title={
      <div className="flex items-baseline gap-3">
        <span className="text-lg font-semibold">{row.symbol}</span>
        <span className="text-sm text-fg-muted">{row.company_name}</span>
        <span className="num text-lg">{num(ltp)}</span>
      </div>
    }>
      {create.isSuccess ? (
        <div className="space-y-4 py-6 text-center">
          <div className="text-lg font-medium">Auto trade is on for {row.symbol}</div>
          <p className="text-sm text-fg-muted">A paper buy happens only when price reaches {num(v.entry)} and all timeframes agree. You can follow it in My Trades.</p>
          <button className="btn-primary" onClick={onClose}>Done</button>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr,340px]">
          <div className="min-w-0 space-y-4">
            <ChartPanel symbol={row.symbol} levels={levels} defaultTf="1D" />
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-fg-muted">Trend check:</span>
              {mtf.isLoading ? <Spinner /> : m?.available ? TF.map(([k, label]) => (
                <Pill key={k} tone={m[k].passed && m[k].freshness === "FRESH" ? "good" : m[k].status === "UNAVAILABLE" ? "muted" : "bad"} title={m[k].note ?? m[k].status}>{label} {m[k].passed && m[k].freshness === "FRESH" ? "✓" : "✕"}</Pill>
              )) : <span className="text-xs text-fg-faint">not available ({m?.error?.message ?? "no market data"})</span>}
            </div>
          </div>

          <div className="space-y-4">
            <Field label="Amount to invest (₹)" hint={preview.data ? `Paper cash available: ${money(preview.data.account.available_cash, 0)}` : undefined}>
              <input className="input num" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="20000" />
            </Field>
            <Field label="Buy at">
              <div className="flex gap-2">
                <input className="input num" inputMode="decimal" value={entry} onChange={(e) => { setEntry(e.target.value); setFromLatest(false); }} />
                <button className="btn-ghost btn-sm whitespace-nowrap" disabled={!ltp || row.quote?.data_state === "STALE"} onClick={() => { setEntry(String(ltp)); setFromLatest(true); }}>Current price</button>
              </div>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Stop loss"><input className="input num" inputMode="decimal" value={stop} onChange={(e) => setStop(e.target.value)} /></Field>
              <Field label="Target"><input className="input num" inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} /></Field>
            </div>
            <details className="text-sm">
              <summary className="cursor-pointer text-fg-faint">More options</summary>
              <div className="mt-2">
                <Field label="When to buy" hint={triggers.data?.triggers?.[trigger]}>
                  <select className="input" value={trigger} onChange={(e) => setTrigger(e.target.value)}>
                    <option value="CANDLE_CLOSE_ABOVE">When a 5-min candle closes above the price</option>
                    <option value="CROSS_ABOVE">As soon as price crosses above</option>
                    <option value="TOUCH_BELOW">When price dips below (buy the dip)</option>
                  </select>
                </Field>
              </div>
            </details>

            {preview.isFetching && <Spinner />}
            {plan && (
              <div className="rounded-lg bg-white/[0.03] p-3 text-sm">
                <div className="grid grid-cols-2 gap-y-1">
                  <span className="text-fg-muted">Shares</span><span className="num text-right">{plan.quantity}</span>
                  <span className="text-fg-muted">Invested</span><span className="num text-right">{money(plan.capital_required)}</span>
                  <span className="text-fg-muted">Max loss</span><span className="num text-right text-down">{money(plan.planned_risk)}</span>
                  <span className="text-fg-muted">Potential profit</span><span className="num text-right text-up">{money(plan.potential_reward)}</span>
                  <span className="text-fg-muted">Risk : reward</span><span className="num text-right">1 : {num(plan.reward_risk)}</span>
                </div>
              </div>
            )}
            {plan?.errors?.map((e: string) => <Notice key={e} tone="bad">{e}</Notice>)}
            {create.isError && <Notice tone="bad">{(create.error as Error).message}</Notice>}

            <label className="flex items-start gap-2 text-sm text-fg-muted">
              <input type="checkbox" className="mt-1" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              I understand this is paper trading — no real order is placed.
            </label>
            <div className="flex gap-2">
              <button className="btn-ghost flex-1" onClick={onClose}>Cancel</button>
              <button className="btn-primary flex-1" disabled={!plan?.ok || !ack || create.isPending || preview.isFetching} onClick={() => create.mutate()}>
                {create.isPending ? "Starting…" : "Start auto trade"}
              </button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
