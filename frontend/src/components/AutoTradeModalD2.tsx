import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { ChartPanel, LEVEL_COLORS } from "../charts/ChartPanel";
import { Level } from "../charts/PriceChart";
import { money, num, time } from "../lib/format";
import { useDebounced } from "../lib/useDebounced";
import { ExplainButton } from "./ExplainButton";
import { Field, Modal, Notice, Pill, Spinner } from "./ui";

export function AutoTradeModalD2({ signal: s, onClose }: { signal: any; onClose: () => void }) {
  const qc = useQueryClient();
  const [amount, setAmount] = useState("");
  const [override, setOverride] = useState(false);
  const [oEntry, setOEntry] = useState(String(s.entry));
  const [oStop, setOStop] = useState(String(s.stop_loss));
  const [oTarget, setOTarget] = useState(String(s.target));
  const [ack, setAck] = useState(false);

  const alloc = Number(amount);
  const valid = amount.trim() !== "" && Number.isFinite(alloc) && alloc > 0;
  const body = valid ? { signal_id: s.id, allocation: alloc, override: override ? { entry: Number(oEntry), stop_loss: Number(oStop), target: Number(oTarget) } : null } : null;
  const debounced = useDebounced(body, 300);
  const preview = useQuery({ queryKey: ["d2-preview", debounced], queryFn: () => api("/api/d2/preview", { body: debounced }), enabled: !!debounced });
  const plan = preview.data?.plan;
  const create = useMutation({ mutationFn: () => api("/api/d2/trades", { body: { ...body, confirm: true } }), onSuccess: () => qc.invalidateQueries() });

  const f = s.fibonacci ?? {};
  const z = s.demand_zone;
  const levels: Level[] = [
    { label: "Buy above", price: override ? Number(oEntry) : s.entry, color: LEVEL_COLORS.entry },
    { label: "Stop", price: override ? Number(oStop) : s.stop_loss, color: LEVEL_COLORS.stop },
    { label: "Target", price: override ? Number(oTarget) : s.target, color: LEVEL_COLORS.target },
    ...(f.fib_50 ? [{ label: "50%", price: f.fib_50, color: LEVEL_COLORS.fib, dashed: true }] : []),
    ...(z ? [{ label: "Zone high", price: z.high, color: LEVEL_COLORS.zone, dashed: true }, { label: "Zone low", price: z.low, color: LEVEL_COLORS.zone, dashed: true }] : []),
  ];
  const tradable = s.status === "QUALIFIED" && s.validity === "VALID" && !(s.trade && ["PENDING_ENTRY", "OPEN", "CONFIGURED"].includes(s.trade.status));

  return (
    <Modal open onClose={onClose} wide title={
      <div className="flex items-baseline gap-3">
        <span className="text-lg font-semibold">{s.symbol}</span>
        <span className="text-sm text-fg-muted">{s.company_name}</span>
        <span className="num text-lg">{num(s.quote?.ltp ?? s.ltp)}</span>
        <Pill tone="good">{s.grade} · {s.score.toFixed(0)}</Pill>
      </div>
    }>
      {create.isSuccess ? (
        <div className="space-y-4 py-6 text-center">
          <div className="text-lg font-medium">Auto trade is on for {s.symbol}</div>
          <p className="text-sm text-fg-muted">A paper buy happens only if price goes above {num(s.entry)} before {time(s.valid_until)}. Follow it in My Trades.</p>
          <button className="btn-primary" onClick={onClose}>Done</button>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr,340px]">
          <div className="min-w-0 space-y-4">
            <ChartPanel symbol={s.symbol} levels={levels} defaultTf="4H" />
            <details className="rounded-lg border border-ink-line p-3 text-sm">
              <summary className="cursor-pointer text-fg-muted">Why this setup?</summary>
              <ul className="mt-3 space-y-1.5">
                {s.checks?.map((c: any) => (
                  <li key={c.rule + c.name} className="flex gap-2"><span className={c.passed ? "text-up" : "text-down"}>{c.passed ? "✓" : "✕"}</span><span><span className="text-fg">{c.name}</span> <span className="text-fg-faint">— {c.detail}</span></span></li>
                ))}
              </ul>
              <div className="mt-3"><ExplainButton kind="D2_SIGNAL" signalId={s.id} /></div>
              <div className="mt-2 text-xs text-fg-faint">The score is a checklist of strategy quality, not a probability of profit.</div>
            </details>
          </div>

          <div className="space-y-4">
            <div className="rounded-lg bg-white/[0.03] p-3 text-sm">
              <div className="grid grid-cols-2 gap-y-1">
                <span className="text-fg-muted">Buy above</span><span className="num text-right">{num(override ? Number(oEntry) : s.entry)}</span>
                <span className="text-fg-muted">Stop loss</span><span className="num text-right text-down">{num(override ? Number(oStop) : s.stop_loss)}</span>
                <span className="text-fg-muted">Target</span><span className="num text-right text-up">{num(override ? Number(oTarget) : s.target)}</span>
                <span className="text-fg-muted">Valid until</span><span className="num text-right">{time(s.valid_until)}</span>
              </div>
            </div>
            {!tradable ? <Notice tone="muted">This setup can't be traded now ({s.trade ? "already has a trade" : s.validity?.toLowerCase()}).</Notice> : (
              <>
                <Field label="Amount to invest (₹)" hint={preview.data ? `Paper cash available: ${money(preview.data.account.available_cash, 0)}` : undefined}>
                  <input className="input num" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="25000" />
                </Field>
                <details className="text-sm">
                  <summary className="cursor-pointer text-fg-faint">Change levels manually</summary>
                  <div className="mt-2 space-y-2">
                    <label className="flex items-center gap-2 text-fg-muted"><input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} /> Use my own levels (trade is marked “overridden”, 1:3 still required)</label>
                    {override && (
                      <div className="grid grid-cols-3 gap-2">
                        <Field label="Buy"><input className="input num" value={oEntry} onChange={(e) => setOEntry(e.target.value)} /></Field>
                        <Field label="Stop"><input className="input num" value={oStop} onChange={(e) => setOStop(e.target.value)} /></Field>
                        <Field label="Target"><input className="input num" value={oTarget} onChange={(e) => setOTarget(e.target.value)} /></Field>
                      </div>
                    )}
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
                  <button className="btn-primary flex-1" disabled={!plan?.ok || !ack || create.isPending || preview.isFetching} onClick={() => create.mutate()}>{create.isPending ? "Starting…" : "Start auto trade"}</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
