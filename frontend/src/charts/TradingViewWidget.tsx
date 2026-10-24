import { useEffect, useRef } from "react";

const INTERVAL: Record<string, string> = { "5m": "5", "15m": "15", "1H": "60", "4H": "240", "1D": "D" };

/**
 * Official TradingView Advanced Chart embed widget (display only, TradingView's own data feed).
 * It cannot draw our strategy levels, and some NSE symbols may be unavailable in embedded widgets
 * because of exchange licensing — the levels panel beside it is the synchronized reference.
 */
export function TradingViewWidget({ symbol, timeframe, height = 380 }: { symbol: string; timeframe: string; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.innerHTML = "";
    const inner = document.createElement("div");
    inner.className = "tradingview-widget-container__widget";
    inner.style.height = "100%";
    el.appendChild(inner);
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.async = true;
    script.type = "text/javascript";
    script.innerHTML = JSON.stringify({
      autosize: true, symbol, interval: INTERVAL[timeframe] ?? "D", timezone: "Asia/Kolkata", theme: "dark", style: "1", locale: "en",
      backgroundColor: "rgba(11,13,12,1)", gridColor: "rgba(245,247,245,0.04)", allow_symbol_change: false, hide_side_toolbar: true,
      save_image: false, calendar: false, support_host: "https://www.tradingview.com",
    });
    el.appendChild(script);
    return () => {
      el.innerHTML = "";
    };
  }, [symbol, timeframe]);
  return <div ref={ref} className="tradingview-widget-container w-full" style={{ height }} />;
}
