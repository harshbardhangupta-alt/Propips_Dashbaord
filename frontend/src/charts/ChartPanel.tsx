import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { num, time } from "../lib/format";
import { Notice, Spinner, Tabs } from "../components/ui";
import { Level, PriceChart } from "./PriceChart";
import { TradingViewWidget } from "./TradingViewWidget";

const TFS = ["5m", "15m", "1H", "4H", "1D"] as const;

export function ChartPanel({ symbol, levels, defaultTf = "1D" }: { symbol: string; levels: Level[]; defaultTf?: (typeof TFS)[number] }) {
  const [tf, setTf] = useState<string>(defaultTf);
  const [mode, setMode] = useState<"engine" | "tv">("engine");
  const q = useQuery({ queryKey: ["chart", symbol, tf], queryFn: () => api(`/api/system/chart/${encodeURIComponent(symbol)}?tf=${tf}`), enabled: mode === "engine", staleTime: 30_000 });
  const tvSymbol = q.data?.tradingview_symbol ?? `NSE:${symbol.replace(/[^A-Z0-9_]/gi, "_").toUpperCase()}`;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr,240px]">
      <div className="min-w-0 rounded-xl border border-ink-line bg-ink p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <Tabs value={mode} onChange={setMode} items={[{ id: "engine", label: "Dhan data · engine view" }, { id: "tv", label: "TradingView widget" }]} />
          <div className="flex gap-1">
            {TFS.map((t) => (
              <button key={t} onClick={() => setTf(t)} className={`tab !px-2 !py-1 text-xs num ${tf === t ? "tab-active" : ""}`}>{t}</button>
            ))}
          </div>
        </div>
        {mode === "engine" ? (
          q.isLoading ? (
            <div className="grid h-[380px] place-items-center"><Spinner label="Loading Dhan candles…" /></div>
          ) : q.isError ? (
            <div className="grid h-[380px] place-items-center"><Notice tone="bad">{(q.error as Error).message}</Notice></div>
          ) : !q.data?.available ? (
            <div className="grid h-[380px] place-items-center p-6 text-center">
              <Notice tone="warn">
                Chart unavailable: {q.data?.error ? `${q.data.error.status} — ${q.data.error.message}` : "Dhan returned no completed candles."} No placeholder data is shown.
              </Notice>
            </div>
          ) : (
            <>
              <PriceChart bars={q.data.candles} levels={levels} />
              <div className="mt-1.5 text-[11px] text-fg-faint">
                {q.data.source} · completed candles only · fetched {time(q.data.fetched_at)} IST · same data the strategy engine uses
              </div>
            </>
          )
        ) : (
          <>
            <TradingViewWidget symbol={tvSymbol} timeframe={tf} />
            <div className="mt-1.5 text-[11px] text-fg-faint">
              {tvSymbol} via TradingView's embed widget — TradingView's data feed, display only, not used by the engine. Some NSE symbols may be restricted in embedded widgets.
            </div>
          </>
        )}
      </div>
      <div className="rounded-xl border border-ink-line bg-ink p-4">
        <div className="label mb-3">Price levels</div>
        {levels.length === 0 ? (
          <div className="text-sm text-fg-faint">Enter a plan to see levels.</div>
        ) : (
          <ul className="space-y-2">
            {[...levels].sort((a, b) => b.price - a.price).map((l) => (
              <li key={l.label} className="flex items-center justify-between gap-3 text-sm">
                <span className="flex items-center gap-2 text-fg-muted">
                  <span className="h-0.5 w-3 rounded" style={{ background: l.color }} />
                  {l.label}
                </span>
                <span className="num text-fg">{num(l.price)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export const LEVEL_COLORS = { entry: "#D9FF00", stop: "#E5736B", target: "#4ADE80", fib: "rgba(163,173,166,0.7)", zone: "rgba(120,170,255,0.75)", ltp: "#F5F7F5" };
