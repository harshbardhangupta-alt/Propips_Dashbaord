import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { AccountStrip } from "../components/AccountStrip";
import { AutoTradeModalD2 } from "../components/AutoTradeModalD2";
import { SetupNotice } from "../components/SetupNotice";
import { Empty, ErrorBox, Notice, Pill, Spinner, Tabs } from "../components/ui";
import { num, time } from "../lib/format";

export default function Dashboard2() {
  const qc = useQueryClient();
  const [view, setView] = useState<"qualified" | "rejected">("qualified");
  const [selected, setSelected] = useState<any | null>(null);
  const status = useQuery({ queryKey: ["d2-status"], queryFn: () => api("/api/d2/scanner/status"), refetchInterval: (q) => (q.state.data?.running ? 2000 : 10000) });
  const sigs = useQuery({ queryKey: ["d2-signals", view], queryFn: () => api(`/api/d2/signals?view=${view}`), refetchInterval: 15000 });
  const act = useMutation({ mutationFn: (path: string) => api(`/api/d2/scanner/${path}`, { method: "POST" }), onSuccess: () => qc.invalidateQueries() });
  const s = status.data;
  const last = s?.latest;
  const rows: any[] = sigs.data?.signals ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Swing Scanner</h1>
          <p className="mt-1 text-sm text-fg-muted">Nifty 250 · Mechanical Swing strategy · minimum 1:3 risk-reward</p>
        </div>
        <AccountStrip code="D2_MECH" />
      </div>
      <SetupNotice universe="NIFTY250" />

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-line bg-ink-panel px-4 py-3">
        <span className={`h-2 w-2 rounded-full ${s?.running ? "bg-neon animate-pulse" : s?.auto_scan_enabled ? "bg-up" : "bg-fg-faint"}`} />
        <div className="text-sm">
          {s?.running ? <>Scanning… {s.progress.done}/{s.progress.total}</> : s?.auto_scan_enabled ? <>Auto scan on · every 5 min, 9:15–3:00</> : <>Auto scan off</>}
          {last && !s?.running && (
            <span className="text-fg-muted"> · Last scan {time(last.finished_at ?? last.started_at)} — {last.status === "FAILED" ? <span className="text-down">failed</span> : `${last.qualified} setup${last.qualified === 1 ? "" : "s"} found`}</span>
          )}
          {s?.next_regular_scan && !s?.running && <span className="text-fg-faint"> · Next {time(s.next_regular_scan)}</span>}
        </div>
        <div className="ml-auto flex gap-2">
          <button className="btn-ghost btn-sm" disabled={act.isPending || s?.running} onClick={() => act.mutate("run-now")}>Scan now</button>
          {s?.auto_scan_enabled
            ? <button className="btn-ghost btn-sm" disabled={act.isPending} onClick={() => act.mutate("stop")}>Stop auto scan</button>
            : <button className="btn-primary btn-sm" disabled={act.isPending} onClick={() => act.mutate("start")}>Start auto scan</button>}
        </div>
      </div>
      {last?.status === "FAILED" && <Notice tone="bad">{last.message}</Notice>}
      {act.isError && <ErrorBox error={act.error} />}

      <Tabs value={view} onChange={setView} items={[{ id: "qualified", label: "Buy setups" }, { id: "rejected", label: "Not qualified" }]} />

      {sigs.isLoading ? <Spinner /> : sigs.isError ? <ErrorBox error={sigs.error} /> : rows.length === 0 ? (
        <div className="rounded-xl border border-ink-line">
          <Empty title={view === "qualified" ? "No buy setups right now" : "Nothing here yet"}>
            {view === "qualified" ? "Setups appear only when every rule of the strategy passes. Seeing none is normal." : "Run a scan to see which stocks didn't qualify and why."}
          </Empty>
        </div>
      ) : view === "qualified" ? (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Stock</th><th className="text-right">Price</th><th>Grade</th><th className="text-right">Buy above</th><th className="text-right">Stop loss</th><th className="text-right">Target</th><th className="text-right">Risk : reward</th><th></th></tr></thead>
            <tbody>
              {rows.map((r) => {
                const active = r.trade && ["PENDING_ENTRY", "OPEN", "CONFIGURED"].includes(r.trade.status);
                const tradable = r.validity === "VALID" && !active;
                return (
                  <tr key={r.id} className="cursor-pointer" onClick={() => setSelected(r)}>
                    <td><div className="font-medium">{r.symbol}{r.is_new && <span className="ml-2 text-[10px] font-semibold text-neon">NEW</span>}</div><div className="max-w-[240px] truncate text-xs text-fg-faint">{r.company_name}</div></td>
                    <td className="num text-right">{num(r.quote?.ltp ?? r.ltp)}</td>
                    <td><Pill tone="good">{r.grade} · {r.score.toFixed(0)}</Pill></td>
                    <td className="num text-right">{num(r.entry)}</td>
                    <td className="num text-right text-down">{num(r.stop_loss)}</td>
                    <td className="num text-right text-up">{num(r.target)}</td>
                    <td className="num text-right">1 : {r.reward_risk}</td>
                    <td className="text-right" onClick={(e) => e.stopPropagation()}>
                      {active ? <Pill value={r.trade.status}>{r.trade.status === "OPEN" ? "Position open" : "Waiting for entry"}</Pill>
                        : tradable ? <button className="btn-primary btn-sm" onClick={() => setSelected(r)}>Trade</button>
                        : <span className="text-xs text-fg-faint">{r.validity === "TRIGGERED" ? "Already triggered" : "Expired"}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Stock</th><th className="text-right">Score</th><th>Why not</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="font-medium">{r.symbol}</td>
                  <td className="num text-right">{r.score.toFixed(0)}</td>
                  <td className="!whitespace-normal text-sm text-fg-muted">{simpleReason(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selected && <AutoTradeModalD2 signal={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

const RULE_TEXT: Record<string, string> = {
  A: "Below its 50-day average (downtrend)",
  B: "No strong upward move to trade",
  C: "Pullback doesn't have 3 red candles yet",
  D: "Hasn't pulled back below the 50% level",
  E: "No support (demand) zone at the pullback",
  F: "Waiting for a green confirmation candle",
  G: "Market data missing or out of date",
  H: "Can't get a 1:3 risk-reward",
};

function simpleReason(r: any): string {
  if (r.status === "UNAVAILABLE") return "Not enough market data";
  const fail = r.checks?.find((c: any) => c.mandatory && !c.passed);
  if (fail) return RULE_TEXT[fail.rule] ?? fail.name;
  return r.rejection_reasons?.[0] ?? "Score too low";
}
