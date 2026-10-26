// The candle chart, using TradingView's Lightweight Charts library.
// Zooming (mouse wheel / pinch) and dragging into the past are built into the
// library; this file sets the look and tells the app when older candles are needed.

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
  type UTCTimestamp,
} from "lightweight-charts";
import { pricePrecision } from "./candles.ts";
import { formatLocalDateTime, formatLocalTick } from "./format.ts";
import type { ZoneId } from "./timezone.ts";
import type { Analysis, Candle, LineName, LinePoint } from "./types.ts";

// Colors close to TradingView's dark theme.
export const THEME = {
  background: "#131722",
  text: "#d1d4dc",
  grid: "#1e222d",
  border: "#2a2e39",
  up: "#089981",
  down: "#f23645",
};

// Indicator colors, close to TradingView's defaults.
export const LINE_COLORS: Record<LineName, string> = {
  emaFast: "#f7c948",
  emaSlow: "#ab47bc",
  bbUpper: "#2962ff",
  bbMiddle: "#ff6d00",
  bbLower: "#2962ff",
  rsi: "#7e57c2",
};
const PRICE_LINES: LineName[] = ["emaFast", "emaSlow", "bbUpper", "bbMiddle", "bbLower"];
const RSI_PANE = 1;
const RSI_PANE_HEIGHT = 130;

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
  private zone: ZoneId = "local";
  // Indicator lines are created when first needed and removed when switched off.
  private readonly lines = new Map<LineName, ISeriesApi<"Line">>();

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
      // Times are shown in the chosen time zone (the library shows UTC by default).
      localization: { timeFormatter: (time: unknown) => formatLocalDateTime(time as number, this.zone) },
      timeScale: {
        borderColor: THEME.border,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
        tickMarkFormatter: (time: unknown, markType: number) => formatLocalTick(time as number, markType, this.zone),
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

  /** Show times in another zone. The formatters are set again so the chart redraws its labels. */
  setTimeZone(zone: ZoneId): void {
    this.zone = zone;
    this.chart.applyOptions({
      localization: { timeFormatter: (time: unknown) => formatLocalDateTime(time as number, this.zone) },
      timeScale: { tickMarkFormatter: (time: unknown, markType: number) => formatLocalTick(time as number, markType, this.zone) },
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

  /**
   * Draw the indicator lines of an analysis; lines it does not contain are removed.
   * `null` removes all of them (used while a new chart loads).
   */
  setIndicators(analysis: Analysis | null): void {
    const wanted = analysis?.lines ?? {};
    for (const [name, series] of [...this.lines]) {
      if (!wanted[name]) {
        this.chart.removeSeries(series);
        this.lines.delete(name);
      }
    }
    for (const [name, points] of Object.entries(wanted) as [LineName, LinePoint[]][]) {
      const series = this.lines.get(name) ?? this.createLine(name);
      series.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    }
  }

  private createLine(name: LineName): ISeriesApi<"Line"> {
    const isRsi = name === "rsi";
    const series = this.chart.addSeries(
      LineSeries,
      {
        color: LINE_COLORS[name],
        lineWidth: name === "bbUpper" || name === "bbLower" ? 1 : 2,
        priceLineVisible: false,
        lastValueVisible: isRsi,
        crosshairMarkerVisible: false,
        priceFormat: isRsi
          ? { type: "price", precision: 2, minMove: 0.01 }
          : { type: "price", precision: this.precision, minMove: 10 ** -this.precision },
        // RSI always runs from 0 to 100, so its pane keeps that scale.
        autoscaleInfoProvider: isRsi ? () => ({ priceRange: { minValue: 0, maxValue: 100 } }) : undefined,
      },
      isRsi ? RSI_PANE : 0,
    );
    if (isRsi) {
      for (const level of [70, 30]) {
        series.createPriceLine({
          price: level, color: "#787b86", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "",
        });
      }
      this.chart.panes()[RSI_PANE]?.setHeight(RSI_PANE_HEIGHT);
    }
    this.lines.set(name, series);
    return series;
  }

  /** Update the latest candle, or add a new one. */
  updateCandle(candle: Candle): void {
    this.series.update(toBar(candle));
  }

  private setPrecisionFor(price: number | undefined): void {
    this.precision = pricePrecision(price ?? 0);
    const priceFormat = { type: "price" as const, precision: this.precision, minMove: 10 ** -this.precision };
    this.series.applyOptions({ priceFormat });
    for (const name of PRICE_LINES) this.lines.get(name)?.applyOptions({ priceFormat });
  }

  get pricePrecision(): number {
    return this.precision;
  }

  destroy(): void {
    this.chart.remove();
  }
}
