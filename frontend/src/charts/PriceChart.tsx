import { CandlestickSeries, ColorType, createChart, HistogramSeries, IChartApi, LineStyle, UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

export type Level = { label: string; price: number; color: string; dashed?: boolean };
export type Bar = { time: number; open: number; high: number; low: number; close: number; volume: number };

// Lightweight Charts renders UTC; shift epoch by IST offset so the axis reads exchange time.
const IST_OFFSET = 19800;

/** TradingView Lightweight Charts (Apache-2.0) rendering validated Dhan OHLC with strategy levels. */
export function PriceChart({ bars, levels, height = 380 }: { bars: Bar[]; levels: Level[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // Rebuild only when the level values change, not on every parent render.
  const levelKey = JSON.stringify(levels);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#A3ADA6", fontFamily: "JetBrains Mono, monospace", fontSize: 11 },
      grid: { vertLines: { color: "rgba(245,247,245,0.04)" }, horzLines: { color: "rgba(245,247,245,0.04)" } },
      rightPriceScale: { borderColor: "rgba(245,247,245,0.08)" },
      timeScale: { borderColor: "rgba(245,247,245,0.08)", timeVisible: true, secondsVisible: false },
      crosshair: { horzLine: { color: "rgba(217,255,0,0.35)" }, vertLine: { color: "rgba(217,255,0,0.35)" } },
    });
    chartRef.current = chart;
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#4ADE80", downColor: "#E5736B", wickUpColor: "#4ADE80", wickDownColor: "#E5736B", borderVisible: false,
    });
    candles.setData(bars.map((b) => ({ time: (b.time + IST_OFFSET) as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })));
    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "", color: "rgba(163,173,166,0.25)" });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(bars.map((b) => ({ time: (b.time + IST_OFFSET) as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "rgba(74,222,128,0.18)" : "rgba(229,115,107,0.18)" })));
    for (const l of levels) {
      if (!Number.isFinite(l.price)) continue;
      candles.createPriceLine({ price: l.price, color: l.color, lineWidth: 1, lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title: l.label });
    }
    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, levelKey, height]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}
