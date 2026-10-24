import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { num } from "../lib/format";
import { Spinner } from "../components/ui";
import { Level, PriceChart } from "./PriceChart";
import { TradingViewWidget } from "./TradingViewWidget";

const TFS = ["5m", "15m", "1H", "4H", "1D"] as const;

export function ChartPanel({ symbol, levels, defaultTf = "1D" }: { symbol: string; levels: Level[]; defaultTf?: (typeof TFS)[number] }) {
  const [tf, setTf] = useState<string>(defaultTf);
  const [tv, setTv] = useState(false);
  const q = useQuery({ queryKey: ["chart", symbol, tf], queryFn: () => api(`/api/system/chart/${encodeURIComponent(symbol)}?tf=${tf}`), enabled: !tv, staleTime: 30_000 });
  const tvSymbol = q.data?.tradingview_symbol ?? `NSE:${symbol.replace(/[^A-Z0-9_]/gi, "_").toUpperCase()}`;

  return (
    <div className="rounded-xl border border-ink-line bg-ink p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex gap-1">
          {TFS.map((t) => <button key={t} onClick={() => setTf(t)} className={`tab !px-2 !py-1 text-xs num ${tf === t ? "tab-active" : ""}`}>{t}</button>)}
        </div>
        <button className="text-xs text-fg-faint hover:text-fg" onClick={() => setTv(!tv)}>{tv ? "← Back to chart" : "Open in TradingView widget"}</button>
      </div>
      {tv ? (
        <TradingViewWidget symbol={tvSymbol} timeframe={tf} />
      ) : q.isLoading ? (
        <div className="grid h-[380px] place-items-center"><Spinner label="Loading chart…" /></div>
      ) : !q.data?.available ? (
        <div className="grid h-[380px] place-items-center px-6 text-center text-sm text-fg-muted">
          Chart not available — {q.isError ? (q.error as Error).message : q.data?.error ? q.data.error.message : "no candles from Dhan yet"}.
        </div>
      ) : (
        <PriceChart bars={q.data.candles} levels={levels} />
      )}
      {levels.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {levels.map((l) => (
            <span key={l.label} className="flex items-center gap-1.5 text-fg-muted">
              <span className="h-0.5 w-3 rounded" style={{ background: l.color }} />{l.label} <span className="num text-fg">{num(l.price)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export const LEVEL_COLORS = { entry: "#D9FF00", stop: "#E5736B", target: "#4ADE80", fib: "rgba(163,173,166,0.7)", zone: "rgba(120,170,255,0.75)", ltp: "#F5F7F5" };
