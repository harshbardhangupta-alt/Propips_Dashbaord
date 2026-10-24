import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { ChartPanel, LEVEL_COLORS } from "../charts/ChartPanel";
import { Level } from "../charts/PriceChart";
import { money, num, time } from "../lib/format";
import { useDebounced } from "../lib/useDebounced";
import { ExplainButton } from "./ExplainButton";
import { PaperBadge } from "./PaperBadge";
import { ErrorBox, Field, KV, Modal, Notice, Pill, Spinner } from "./ui";

const TF_LABEL: Record<string, string> = { daily: "Daily · primary trend", h4: "4-hour · structure", m15: "15-minute · setup", m5: "5-minute · entry" };

function parse(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : NaN;
}

export function AutoTradeModalD1({ row, onClose }: { row: any; onClose: () => void }) {
  const qc = useQueryClient();
  const [allocation, setAllocation] = useState("");
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [maxRisk, setMaxRisk] = useState("");
  const [trigger, setTrigger] = useState("CANDLE_CLOSE_ABOVE");
  const [entrySource, setEntrySource] = useState<"MANUAL" | "LATEST_VERIFIED_PRICE">("MANUAL");
  const [step, setStep] = useState<"form" | "confirm">("form");
  const [ack, setAck] = useState(false);
  const requestId = useMemo(() => crypto.randomUUID(), []);

  const triggers = useQuery({ queryKey: ["d1-triggers"], queryFn: () => api("/api/d1/triggers"), staleTime: Infinity });
  const mtf = useQuery({ queryKey: ["d1-mtf", row.symbol], queryFn: () => api(`/api/d1/stocks/${encodeURIComponent(row.symbol)}/mtf`) });

  const vals = { allocation: parse(allocation), entry: parse(entry), stop: parse(stop), target: parse(target), maxRisk: parse(maxRisk) };
  const complete = [vals.allocation, vals.entry, vals.stop, vals.target].every((v) => v !== null && !Number.isNaN(v) && (v as number) > 0) && (vals.maxRisk === null || (vals.maxRisk as number) > 0);
  const body = complete
    ? { symbol: row.symbol, allocation: vals.allocation, entry: vals.entry, stop_loss: vals.stop, take_profit: vals.target, max_risk_amount: vals.maxRisk, entry_trigger: trigger, entry_source: entrySource }
    : null;
  const debounced = useDebounced(body, 300);
  const preview = useQuery({ queryKey: ["d1-preview", debounced], queryFn: () => api("/api/d1/preview", { body: debounced }), enabled: !!debounced });
  const plan = preview.data?.plan;

  const create = useMutation({
    mutationFn: () => api("/api/d1/trades", { body: { ...body, confirm: true, client_request_id: requestId } }),
    onSuccess: () => {
      qc.invalidateQueries();
    },
  });

  useEffect(() => setAck(false), [step]);

  const ltp: number | null = row.quote?.ltp ?? null;
  const levels: Level[] = [];
  if (vals.entry) levels.push({ label: "Entry", price: vals.entry, color: LEVEL_COLORS.entry });
  if (vals.stop) levels.push({ label: "Stop", price: vals.stop, color: LEVEL_COLORS.stop });
  if (vals.target) levels.push({ label: "Target", price: vals.target, color: LEVEL_COLORS.target });

  const m = mtf.data;
  const inputErr = (v: number | null) => (v !== null && (Number.isNaN(v) || v <= 0) ? "Enter a positive number" : null);

  return (
    <Modal open onClose={onClose} wide title={
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <div className="text-lg font-semibold">{row.symbol} <span className="text-sm font-normal text-fg-muted">· {row.company_name}</span></div>
          <div className="text-xs text-fg-faint">Dashboard 1 · MTF paper auto trade</div>
        </div>
        <div className="ml-2 text-right">
          <div className="num text-lg">{num(ltp)}</div>
          <div className="text-[11px] text-fg-faint">{row.quote?.data_state?.replace(/_/g, " ").toLowerCase() ?? "no quote"} · {time(row.quote?.fetched_at)}</div>
        </div>
        <PaperBadge />
      </div>
    }>
      {create.isSuccess ? (
        <div className="space-y-4">
          <Notice tone="good">Paper auto trade #{create.data.trade.id} armed (PENDING ENTRY). {create.data.message}</Notice>
          <div className="flex justify-end"><button className="btn-primary" onClick={onClose}>Done</button></div>
        </div>
      ) : step === "form" ? (
        <div className="space-y-6">
          <ChartPanel symbol={row.symbol} levels={levels} defaultTf="1D" />
          <div className="grid gap-6 lg:grid-cols-[1.1fr,1fr]">
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Fund allocation (₹)" error={inputErr(vals.allocation)} hint={preview.data ? `Available paper cash ${money(preview.data.account.available_cash, 0)}` : "Simulated paper cash"}>
                  <input className="input num" inputMode="decimal" value={allocation} onChange={(e) => setAllocation(e.target.value)} placeholder="e.g. 20000" />
                </Field>
                <Field label="Entry price" error={inputErr(vals.entry)} hint={entrySource === "LATEST_VERIFIED_PRICE" ? `Using latest verified price (${row.quote?.source ?? ""})` : "Manual price"}>
                  <div className="flex gap-2">
                    <input className="input num" inputMode="decimal" value={entry} onChange={(e) => { setEntry(e.target.value); setEntrySource("MANUAL"); }} placeholder="e.g. 1520.50" />
                    <button className="btn-ghost btn-sm whitespace-nowrap" disabled={!ltp || row.quote?.data_state === "STALE"} title={row.quote?.data_state === "STALE" ? "Latest quote is stale" : ""} onClick={() => { setEntry(String(ltp)); setEntrySource("LATEST_VERIFIED_PRICE"); }}>Use latest price</button>
                  </div>
                </Field>
                <Field label="Stop loss" error={inputErr(vals.stop) ?? (vals.entry && vals.stop && vals.stop >= vals.entry ? "Stop must be below entry for a BUY" : null)}>
                  <input className="input num" inputMode="decimal" value={stop} onChange={(e) => setStop(e.target.value)} />
                </Field>
                <Field label="Take profit" error={inputErr(vals.target) ?? (vals.entry && vals.target && vals.target <= vals.entry ? "Target must be above entry" : null)}>
                  <input className="input num" inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} />
                </Field>
                <Field label="Max monetary risk (optional, ₹)" error={inputErr(vals.maxRisk)} hint="Caps quantity further; never increases it">
                  <input className="input num" inputMode="decimal" value={maxRisk} onChange={(e) => setMaxRisk(e.target.value)} />
                </Field>
                <Field label="Entry trigger" hint={triggers.data?.triggers?.[trigger]}>
                  <select className="input" value={trigger} onChange={(e) => setTrigger(e.target.value)}>
                    {Object.keys(triggers.data?.triggers ?? { CANDLE_CLOSE_ABOVE: "" }).map((t) => <option key={t} value={t}>{t.replace(/_/g, " ").toLowerCase()}{t === triggers.data?.default ? " (default)" : ""}</option>)}
                  </select>
                </Field>
              </div>
              <Notice tone="muted">
                A price touch does not guarantee a fill at your level. Fills are simulated on completed 5-minute Dhan candles with {preview.data?.account?.limits?.slippage_bps ?? 5} bps slippage; gaps fill at the candle open,
                and fills more than {preview.data?.account?.limits?.max_entry_deviation_pct ?? 0.5}% beyond the entry are skipped. A pending entry stays armed for {triggers.data?.pending_validity_trading_days ?? 5} trading sessions.
              </Notice>
            </div>
            <div className="space-y-4">
              <div className="rounded-xl border border-ink-line bg-ink p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div className="label">MTF confirmation</div>
                  {mtf.isFetching ? <Spinner /> : m?.available ? <Pill value={m.confirmation} /> : <Pill value="UNAVAILABLE" />}
                </div>
                {m && !m.available && <Notice tone="warn">Live MTF evaluation failed: {m.error?.status} — {m.error?.message}{m.cached_at ? ` (last stored ${time(m.cached_at)})` : ""}</Notice>}
                {m?.available && (
                  <ul className="space-y-2">
                    {(["daily", "h4", "m15", "m5"] as const).map((k) => (
                      <li key={k} className="flex items-center justify-between gap-3 text-sm">
                        <span className="text-fg-muted">{TF_LABEL[k]}</span>
                        <span className="flex items-center gap-2">
                          <span className="text-[11px] text-fg-faint num">{time(m[k].last_candle)}</span>
                          <Pill value={m[k].freshness} />
                          <Pill value={m[k].status} />
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {m?.available && m.reasons?.length > 0 && <ul className="mt-3 space-y-1 text-xs text-fg-faint">{m.reasons.map((r: string) => <li key={r}>· {r}</li>)}</ul>}
                <div className="mt-3 text-[11px] text-fg-faint">Entry is simulated only when Daily, 4H and 15m pass on fresh completed candles AND the 5m trigger fires.</div>
                {m?.available && <div className="mt-3"><ExplainButton kind="D1_MTF" symbol={row.symbol} /></div>}
              </div>
              <div className="rounded-xl border border-ink-line bg-ink p-4">
                <div className="mb-3 flex items-center justify-between"><div className="label">Position plan (backend-calculated)</div>{preview.isFetching && <Spinner />}</div>
                {!plan ? (
                  <div className="text-sm text-fg-faint">Enter allocation, entry, stop and target.</div>
                ) : (
                  <>
                    <KV rows={[
                      ["Quantity", `${plan.quantity} sh`],
                      ["Capital utilisation", money(plan.capital_required)],
                      ["Est. buy charges", money(plan.estimated_buy_charges)],
                      ["Planned risk", money(plan.planned_risk)],
                      ["Potential reward", money(plan.potential_reward)],
                      ["Reward : risk", <span className={plan.reward_risk >= 2 ? "text-up" : "text-down"}>1 : {num(plan.reward_risk)}</span>],
                      ["Risk budget", money(plan.risk_budget)],
                      ["Limited by", plan.limiting_factor || "—"],
                      ["Remaining paper cash", money(plan.remaining_cash)],
                    ]} />
                    {plan.errors.length > 0 && <div className="mt-3 space-y-1">{plan.errors.map((e: string) => <Notice key={e} tone="bad">{e}</Notice>)}</div>}
                    {plan.warnings.length > 0 && <div className="mt-3 space-y-1">{plan.warnings.map((e: string) => <Notice key={e} tone="warn">{e}</Notice>)}</div>}
                  </>
                )}
                {preview.isError && <ErrorBox error={preview.error} />}
              </div>
              <div className="flex justify-end gap-2">
                <button className="btn-ghost" onClick={onClose}>Cancel</button>
                <button className="btn-primary" disabled={!plan?.ok || preview.isFetching} onClick={() => setStep("confirm")}>Review & confirm</button>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="mx-auto max-w-2xl space-y-5">
          <Notice tone="neon">Final review. Enabling arms a SIMULATED paper trade. No order is sent to Dhan or any broker, and no position opens until the trigger and MTF conditions pass.</Notice>
          <div className="rounded-xl border border-ink-line bg-ink p-5">
            <KV rows={[
              ["Stock", `${row.symbol} — ${row.company_name}`],
              ["Fund allocation", money(vals.allocation)],
              ["Entry trigger", `${trigger.replace(/_/g, " ").toLowerCase()} — ${triggers.data?.triggers?.[trigger] ?? ""}`],
              ["Entry price", `${num(vals.entry)} (${entrySource === "MANUAL" ? "manual" : "latest verified price"})`],
              ["Stop loss", num(vals.stop)],
              ["Take profit", num(vals.target)],
              ["Quantity", `${plan.quantity}`],
              ["Planned risk", money(plan.planned_risk)],
              ["Potential reward", money(plan.potential_reward)],
              ["Reward : risk", `1 : ${num(plan.reward_risk)}`],
              ["MTF status now", m?.available ? `${m.confirmation} · D ${m.daily.status} · 4H ${m.h4.status} · 15m ${m.m15.status} · 5m ${m.m5.status}` : "unavailable"],
              ["Paper account balance", money(preview.data.account.available_cash)],
              ["Est. remaining cash", money(plan.remaining_cash)],
              ["Execution", "PAPER ONLY — simulated"],
            ]} />
          </div>
          <label className="flex items-center gap-2 text-sm text-fg-muted"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I confirm this is a paper (simulated) trade only.</label>
          {create.isError && <ErrorBox error={create.error} />}
          <div className="flex justify-end gap-2">
            <button className="btn-ghost" onClick={() => setStep("form")}>Back</button>
            <button className="btn-primary" disabled={!ack || create.isPending} onClick={() => create.mutate()}>{create.isPending ? "Enabling…" : "Enable Auto Trade"}</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
