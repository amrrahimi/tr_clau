// The candle chart, using TradingView's Lightweight Charts library.
// Zooming (mouse wheel / pinch) and dragging into the past are built into the
// library; this file sets the look and tells the app when older candles are needed.

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
  type UTCTimestamp,
} from "lightweight-charts";
import { pricePrecision } from "./candles.ts";
import { formatLocalDateTime, formatLocalTick } from "./format.ts";
import type { Candle } from "./types.ts";

// Colors close to TradingView's dark theme.
export const THEME = {
  background: "#131722",
  text: "#d1d4dc",
  grid: "#1e222d",
  border: "#2a2e39",
  up: "#089981",
  down: "#f23645",
};

/** When fewer than this many candles are left of the view, load older ones. */
const LOAD_OLDER_MARGIN = 10;
/** How many candles are visible when a chart opens. */
const INITIAL_VISIBLE = 120;

function toBar(c: Candle) {
  return { time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close };
}

export class ChartView {
  private readonly chart: IChartApi;
  private readonly series: ISeriesApi<"Candlestick">;
  private precision = 2;

  constructor(container: HTMLElement, private readonly onNeedOlder: () => void) {
    this.chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: THEME.background },
        textColor: THEME.text,
        fontFamily: "Vazirmatn, Tahoma, -apple-system, Segoe UI, sans-serif",
      },
      grid: { vertLines: { color: THEME.grid }, horzLines: { color: THEME.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: THEME.border },
      // Times are shown in the computer's local time (the library shows UTC by default).
      localization: { timeFormatter: (time: unknown) => formatLocalDateTime(time as number) },
      timeScale: {
        borderColor: THEME.border,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
        tickMarkFormatter: (time: unknown, markType: number) => formatLocalTick(time as number, markType),
      },
    });
    this.series = this.chart.addSeries(CandlestickSeries, {
      upColor: THEME.up,
      downColor: THEME.down,
      borderVisible: false,
      wickUpColor: THEME.up,
      wickDownColor: THEME.down,
    });
    this.chart.timeScale().subscribeVisibleLogicalRangeChange((range: LogicalRange | null) => {
      if (range && range.from < LOAD_OLDER_MARGIN) this.onNeedOlder();
    });
  }

  /** Show a new list of candles (new coin, market or timeframe). */
  setCandles(candles: Candle[]): void {
    this.setPrecisionFor(candles[candles.length - 1]?.close);
    this.series.setData(candles.map(toBar));
    const count = candles.length;
    this.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, count - INITIAL_VISIBLE), to: count + 5 });
  }

  /** Older candles were put in front: redraw without moving what the user is looking at. */
  prependCandles(candles: Candle[], added: number): void {
    const range = this.chart.timeScale().getVisibleLogicalRange();
    this.series.setData(candles.map(toBar));
    if (range) {
      this.chart.timeScale().setVisibleLogicalRange({ from: range.from + added, to: range.to + added });
    }
  }

  /** Update the latest candle, or add a new one. */
  updateCandle(candle: Candle): void {
    this.series.update(toBar(candle));
  }

  private setPrecisionFor(price: number | undefined): void {
    this.precision = pricePrecision(price ?? 0);
    this.series.applyOptions({
      priceFormat: { type: "price", precision: this.precision, minMove: 10 ** -this.precision },
    });
  }

  get pricePrecision(): number {
    return this.precision;
  }

  destroy(): void {
    this.chart.remove();
  }
}
