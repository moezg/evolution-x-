"use client";
import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { hms } from "@/lib/format";
import { DOWN, UP } from "@/lib/colors";
import type { Candle } from "@/lib/types";

const HIST_COLOR = "#f2c14e";

/** Live candlesticks (lightweight-charts v5) with a volume pane and optional HISTORICAL overlay line. */
export function CandleChart({
  candles,
  historical,
  height = 360,
  label,
  dataLabel = "synthetic",
}: {
  dataLabel?: string;
  candles: Candle[];
  historical?: { t: number; close: number }[] | null;
  height?: number;
  label: string;
}) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const cs = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const vs = useRef<ISeriesApi<"Histogram"> | null>(null);
  const hs = useRef<ISeriesApi<"Line"> | null>(null);
  const fitted = useRef(false);
  const titleRef = useRef("");

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#161615" },
        textColor: "#c3c2b7",
        fontSize: 11,
        attributionLogo: false,
        panes: { separatorColor: "#2c2c2a", enableResize: false },
      },
      grid: { vertLines: { color: "#222220" }, horzLines: { color: "#222220" } },
      rightPriceScale: { borderColor: "#383835" },
      timeScale: {
        borderColor: "#383835",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (t: Time) => hms(Number(t)).slice(0, 5),
      },
      localization: { timeFormatter: (t: Time) => `T+${hms(Number(t))}` },
      crosshair: { mode: CrosshairMode.Normal },
    });
    cs.current = c.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      title: "SYNTHETIC",
    });
    titleRef.current = "";
    vs.current = c.addSeries(
      HistogramSeries,
      { priceFormat: { type: "volume" }, color: "#3987e5", title: "volume BTC" },
      1,
    );
    try {
      c.panes()[1]?.setHeight(Math.round(height * 0.22));
    } catch {
      /* older API */
    }
    chart.current = c;
    fitted.current = false;
    return () => {
      c.remove();
      chart.current = null;
      cs.current = null;
      vs.current = null;
      hs.current = null;
    };
  }, [height]);

  useEffect(() => {
    const c = chart.current;
    if (!c || !cs.current || !vs.current) return;
    const title = dataLabel === "counterfactual_synthetic" ? "COUNTERFACTUAL · SYNTHETIC" : "SYNTHETIC";
    if (titleRef.current !== title) {
      cs.current.applyOptions({ title });
      titleRef.current = title;
    }
    const seen = new Set<number>();
    const rows = candles.filter((k) => (seen.has(k.t) ? false : (seen.add(k.t), true))).sort((a, b) => a.t - b.t);
    cs.current.setData(rows.map((k) => ({ time: k.t as UTCTimestamp, open: k.open, high: k.high, low: k.low, close: k.close })));
    vs.current.setData(
      rows.map((k) => ({ time: k.t as UTCTimestamp, value: k.volume, color: k.close >= k.open ? "rgba(27,175,122,0.55)" : "rgba(230,103,103,0.55)" })),
    );
    if (historical && historical.length) {
      if (!hs.current) {
        hs.current = c.addSeries(LineSeries, { color: HIST_COLOR, lineWidth: 2, title: "HISTORICAL", priceLineVisible: false });
      }
      const hseen = new Set<number>();
      hs.current.setData(
        historical
          .filter((p) => Number.isFinite(p.close) && (hseen.has(p.t) ? false : (hseen.add(p.t), true)))
          .sort((a, b) => a.t - b.t)
          .map((p) => ({ time: p.t as UTCTimestamp, value: p.close })),
      );
    } else if (hs.current) {
      c.removeSeries(hs.current);
      hs.current = null;
    }
    if (!fitted.current && rows.length > 1) {
      c.timeScale().fitContent();
      fitted.current = true;
    }
  }, [candles, historical, dataLabel]);

  return <div ref={el} role="img" aria-label={label} style={{ height }} className="w-full" />;
}
