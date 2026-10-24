import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ChartPanel, LEVEL_COLORS } from "../charts/ChartPanel";
import { Level } from "../charts/PriceChart";
import { money, num, time } from "../lib/format";
import { useDebounced } from "../lib/useDebounced";
import { ExplainButton } from "./ExplainButton";
import { PaperBadge } from "./PaperBadge";
import { ErrorBox, Field, KV, Modal, Notice, Pill, Spinner } from "./ui";

export function AutoTradeModalD2({ signal: s, onClose }: { signal: any; onClose: () => void }) {
  const qc = useQueryClient();
  const [allocation, setAllocation] = useState("");
  const [override, setOverride] = useState(false);
  const [oEntry, setOEntry] = useState(String(s.entry));
  const [oStop, setOStop] = useState(String(s.stop_loss));
  const [oTarget, setOTarget] = useState(String(s.target));
  const [ack, setAck] = useState(false);

  const alloc = Number(allocation);
  const valid = allocation.trim() !== "" && Number.isFinite(alloc) && alloc > 0;
  const body = valid ? { signal_id: s.id, allocation: alloc, override: override ? { entry: Number(oEntry), stop_loss: Number(oStop), target: Number(oTarget) } : null } : null;
  const debounced = useDebounced(body, 300);
  const preview = useQuery({ queryKey: ["d2-preview", debounced], queryFn: () => api("/api/d2/preview", { body: debounced }), enabled: !!debounced });
  const plan = preview.data?.plan;
  const create = useMutation({ mutationFn: () => api("/api/d2/trades", { body: { ...body, confirm: true } }), onSuccess: () => qc.invalidateQueries() });

  const f = s.fibonacci ?? {};
  const z = s.demand_zone;
  const levels: Level[] = [
    { label: "Entry", price: override ? Number(oEntry) : s.entry, color: LEVEL_COLORS.entry },
    { label: "Stop", price: override ? Number(oStop) : s.stop_loss, color: LEVEL_COLORS.stop },
    { label: "Target", price: override ? Number(oTarget) : s.target, color: LEVEL_COLORS.target },
    ...(s.impulse ? [{ label: "Impulse high", price: s.impulse.high, color: LEVEL_COLORS.fib, dashed: true }, { label: "Impulse low", price: s.impulse.low, color: LEVEL_COLORS.fib, dashed: true }] : []),
    ...(f.fib_50 ? [{ label: "Fib 50%", price: f.fib_50, color: LEVEL_COLORS.fib, dashed: true }, { label: "Fib 61.8%", price: f.fib_618, color: LEVEL_COLORS.fib, dashed: true }, { label: "Fib 78.6%", price: f.fib_786, color: LEVEL_COLORS.fib, dashed: true }] : []),
    ...(z ? [{ label: "Zone high", price: z.high, color: LEVEL_COLORS.zone, dashed: true }, { label: "Zone low", price: z.low, color: LEVEL_COLORS.zone, dashed: true }] : []),
  ];

  return (
    <Modal open onClose={onClose} wide title={
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <div className="text-lg font-semibold">{s.symbol} <span className="text-sm font-normal text-fg-muted">· {s.company_name}</span></div>
          <div className="text-xs text-fg-faint">Dashboard 2 · Mechanical Swing paper auto trade</div>
        </div>
        <div className="ml-2"><div className="num text-lg">{num(s.quote?.ltp ?? s.ltp)}</div><div className="text-[11px] text-fg-faint">{s.quote?.data_state?.replace(/_/g, " ").toLowerCase() ?? "no quote"} · {time(s.quote?.fetched_at)}</div></div>
        <Pill tone="good">Score {s.score.toFixed(0)} · {s.grade}</Pill>
        {s.after_market && <Pill tone="muted">{s.after_market_label}</Pill>}
        <PaperBadge />
      </div>
    }>
      {create.isSuccess ? (
        <div className="space-y-4">
          <Notice tone="good">Paper auto trade #{create.data.trade.id} armed (PENDING ENTRY). {create.data.message}</Notice>
          <div className="flex justify-end"><button className="btn-primary" onClick={onClose}>Done</button></div>
        </div>
      ) : (
        <div className="space-y-6">
          <ChartPanel symbol={s.symbol} levels={levels} defaultTf="4H" />
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="rounded-xl border border-ink-line bg-ink p-4 space-y-3">
              <div className="label">Strategy evidence</div>
              <KV rows={[
                ["Daily trend", <span>{s.daily?.bias} · close {num(s.daily?.close)} vs EMA50 {num(s.daily?.ema50)}</span>],
                ["4H structure", s.h4?.structure?.replace(/_/g, " ").toLowerCase()],
                ["Impulse", s.impulse ? `${num(s.impulse.low)} → ${num(s.impulse.high)}` : "—"],
                ["Swing low / high", s.impulse ? `${time(s.impulse.low_time)} / ${time(s.impulse.high_time)}` : "—"],
                ["Break of structure", s.impulse ? `> ${num(s.impulse.bos_level)} @ ${time(s.impulse.bos_time)}` : "—"],
                ["Fib 50 / 61.8 / 78.6", f.fib_50 ? `${num(f.fib_50)} / ${num(f.fib_618)} / ${num(f.fib_786)}` : "—"],
                ["Pullback low", s.pullback ? `${num(s.pullback.low)} (${s.pullback.retracement_pct}% retr.)` : "—"],
                ["Demand zone", z ? `${num(z.low)} – ${num(z.high)}` : "—"],
                ["Confirmation candle", s.confirmation ? `${time(s.confirmation.time)} · O ${num(s.confirmation.open)} C ${num(s.confirmation.close)}` : "—"],
                ["Valid until", time(s.valid_until)],
              ]} />
              <div className="text-[11px] text-fg-faint">Demand zones are technical price areas; they do not prove institutional orders.</div>
            </div>
            <div className="rounded-xl border border-ink-line bg-ink p-4 space-y-3">
              <div className="label">Strategy trade plan {override && <Pill tone="warn">OVERRIDDEN</Pill>}</div>
              <KV rows={[
                ["Entry (buy-stop)", num(s.entry)],
                ["Stop loss", num(s.stop_loss)],
                ["Target (3R)", num(s.target)],
                ["Reward : risk", `1 : ${s.reward_risk}`],
              ]} />
              <div className="text-[11px] text-fg-faint">{s.plan?.entry_rule}. Values are calculated by the Mechanical Swing engine and read-only by default.</div>
              <label className="flex items-center gap-2 text-sm text-fg-muted"><input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} /> Manually override levels</label>
              {override && (
                <div className="space-y-3">
                  <Notice tone="warn">Overridden trades are labelled as such, keep the original strategy values, and must still meet the 1:3 minimum.</Notice>
                  <div className="grid grid-cols-3 gap-2">
                    <Field label="Entry"><input className="input num" value={oEntry} onChange={(e) => setOEntry(e.target.value)} /></Field>
                    <Field label="Stop"><input className="input num" value={oStop} onChange={(e) => setOStop(e.target.value)} /></Field>
                    <Field label="Target"><input className="input num" value={oTarget} onChange={(e) => setOTarget(e.target.value)} /></Field>
                  </div>
                </div>
              )}
              <ExplainButton kind="D2_SIGNAL" signalId={s.id} />
            </div>
            <div className="rounded-xl border border-ink-line bg-ink p-4 space-y-3">
              <Field label="Fund allocation (₹)" hint={preview.data ? `Available paper cash ${money(preview.data.account.available_cash, 0)}` : "Required — never auto-filled"}>
                <input className="input num" inputMode="decimal" value={allocation} onChange={(e) => setAllocation(e.target.value)} placeholder="e.g. 25000" />
              </Field>
              {preview.isFetching && <Spinner />}
              {plan && (
                <>
                  <KV rows={[["Quantity", `${plan.quantity} sh`], ["Capital required", money(plan.capital_required)], ["Planned risk", money(plan.planned_risk)], ["Potential reward", money(plan.potential_reward)], ["Reward : risk", `1 : ${num(plan.reward_risk)}`], ["Remaining paper cash", money(plan.remaining_cash)]]} />
                  {plan.errors.map((e: string) => <Notice key={e} tone="bad">{e}</Notice>)}
                  {plan.warnings.map((e: string) => <Notice key={e} tone="warn">{e}</Notice>)}
                </>
              )}
              {preview.isError && <ErrorBox error={preview.error} />}
              <label className="flex items-center gap-2 text-sm text-fg-muted"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I confirm the allocation and that this is a paper (simulated) trade only.</label>
              {create.isError && <ErrorBox error={create.error} />}
              <div className="flex justify-end gap-2">
                <button className="btn-ghost" onClick={onClose}>Cancel</button>
                <button className="btn-primary" disabled={!plan?.ok || !ack || create.isPending || preview.isFetching} onClick={() => create.mutate()}>{create.isPending ? "Enabling…" : "Enable Paper Auto Trade"}</button>
              </div>
              <div className="text-[11px] text-fg-faint">Enabling never opens a position by itself. Entry is simulated only if a completed 5m candle trades through the buy-stop while the signal is still valid; trading at/below the stop first invalidates it.</div>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
