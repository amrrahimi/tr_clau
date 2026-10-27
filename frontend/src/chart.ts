// The candle chart, using TradingView's Lightweight Charts library.
// Zooming (mouse wheel / pinch) and dragging into the past are built into the
// library; this file sets the look and tells the app when older candles are needed.

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPrimitivePaneRenderer,
  type IPrimitivePaneView,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type ISeriesPrimitive,
  type LogicalRange,
  type SeriesAttachedParameter,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { pricePrecision } from "./candles.ts";
import { formatLocalDateTime, formatLocalTick } from "./format.ts";
import { tradeBoxes, tradeMarkers, type Box } from "./strategyState.ts";
import type { ZoneId } from "./timezone.ts";
import type { Candle, IndicatorResult, Trade } from "./types.ts";

// Colors close to TradingView's dark theme.
export const THEME = {
  background: "#131722",
  text: "#d1d4dc",
  grid: "#1e222d",
  border: "#2a2e39",
  up: "#089981",
  down: "#f23645",
};

const OWN_PANE_HEIGHT = 120;
const LEVEL_COLOR = "#787b86";

/**
 * Which pane each indicator goes in: price-chart indicators share pane 0,
 * every other indicator gets its own pane below, in list order.
 */
export function paneLayout(results: Pick<IndicatorResult, "id" | "pane">[]): Map<string, number> {
  const panes = new Map<string, number>();
  let next = 1;
  for (const r of results) panes.set(r.id, r.pane === "price" ? 0 : next++);
  return panes;
}

/** Identifies the drawn structure; if it is unchanged, only the data needs updating. */
export function layoutSignature(results: IndicatorResult[]): string {
  return results.map((r) => `${r.id}|${r.pane}|${r.outputs.map((o) => o.key + o.style + o.color).join(",")}|${r.levels.join(",")}`).join(";");
}

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
  // One series per indicator output, keyed "instanceId:outputKey".
  private readonly indicatorSeries = new Map<string, ISeriesApi<"Line"> | ISeriesApi<"Histogram">>();
  private priceScaled: ISeriesApi<"Line">[] = []; // series shown in price units, updated with the precision
  private signature = "";
  private readonly markers: ISeriesMarkersPluginApi<Time>;
  private readonly boxes = new PositionBoxes();

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
    this.markers = createSeriesMarkers(this.series, []);
    this.series.attachPrimitive(this.boxes);
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
    this.resetView(candles.length);
  }

  /**
   * Price axes back to automatic and the newest candles in view. Dragging a
   * price axis turns its automatic scaling off; without this reset the next
   * coin could be drawn outside the visible price range (an "empty" chart).
   */
  resetView(count: number): void {
    this.series.priceScale().applyOptions({ autoScale: true });
    for (const series of this.indicatorSeries.values()) series.priceScale().applyOptions({ autoScale: true });
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
   * Draw the indicators of an analysis. An empty list removes them all
   * (used while the bot is stopped or a new chart loads).
   */
  setIndicators(results: IndicatorResult[]): void {
    const signature = layoutSignature(results);
    if (signature !== this.signature) this.rebuild(results);
    this.signature = signature;
    for (const r of results) {
      for (const o of r.outputs) {
        const series = this.indicatorSeries.get(`${r.id}:${o.key}`);
        series?.setData(o.points.map((p) => (
          p.color ? { time: p.time as UTCTimestamp, value: p.value, color: p.color } : { time: p.time as UTCTimestamp, value: p.value }
        )));
      }
    }
  }

  /** Remove every indicator series and create them again for a new structure. */
  private rebuild(results: IndicatorResult[]): void {
    for (const series of this.indicatorSeries.values()) this.chart.removeSeries(series);
    this.indicatorSeries.clear();
    this.priceScaled = [];
    const panes = paneLayout(results);
    for (const r of results) {
      const pane = panes.get(r.id)!;
      const isVolume = r.type === "volume";
      const fixedScale = r.scale;
      const priceFormat = isVolume
        ? { type: "volume" as const }
        : fixedScale
          ? { type: "price" as const, precision: 2, minMove: 0.01 }
          : { type: "price" as const, precision: this.precision, minMove: 10 ** -this.precision };
      r.outputs.forEach((o, n) => {
        const common = {
          color: o.color,
          priceLineVisible: false,
          lastValueVisible: pane !== 0,
          priceFormat,
          autoscaleInfoProvider: fixedScale
            ? () => ({ priceRange: { minValue: fixedScale[0], maxValue: fixedScale[1] } })
            : undefined,
        };
        const series = o.style === "histogram"
          ? this.chart.addSeries(HistogramSeries, common, pane)
          : this.chart.addSeries(LineSeries, {
              ...common,
              lineWidth: r.type === "bb" && o.key !== "basis" ? 1 : 2,
              crosshairMarkerVisible: false,
            }, pane);
        if (n === 0) {
          for (const level of r.levels) {
            series.createPriceLine({ price: level, color: LEVEL_COLOR, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
          }
        }
        if (o.style === "line" && !fixedScale && !isVolume) this.priceScaled.push(series as ISeriesApi<"Line">);
        this.indicatorSeries.set(`${r.id}:${o.key}`, series);
      });
    }
    const allPanes = this.chart.panes();
    for (let i = 1; i < allPanes.length; i++) allPanes[i].setHeight(OWN_PANE_HEIGHT);
  }

  /** Distance of each pane's top edge from the chart's top, for placing the legends. */
  paneTops(): number[] {
    const tops: number[] = [];
    let y = 0;
    for (const pane of this.chart.panes()) {
      tops.push(y);
      y += pane.getHeight() + 1; // 1px separator between panes
    }
    return tops;
  }

  /**
   * Draw a strategy's trades: arrows on the candles and take-profit / stop-loss
   * boxes. An empty list removes them.
   */
  setTrades(trades: Trade[], lastTime: number | null): void {
    this.markers.setMarkers(tradeMarkers(trades).map((m) => ({ ...m, time: m.time as UTCTimestamp })));
    this.boxes.setBoxes(tradeBoxes(trades, lastTime));
  }

  /** Update the latest candle, or add a new one. */
  updateCandle(candle: Candle): void {
    this.series.update(toBar(candle));
  }

  private setPrecisionFor(price: number | undefined): void {
    this.precision = pricePrecision(price ?? 0);
    const priceFormat = { type: "price" as const, precision: this.precision, minMove: 10 ** -this.precision };
    this.series.applyOptions({ priceFormat });
    for (const series of this.priceScaled) series.applyOptions({ priceFormat });
  }

  get pricePrecision(): number {
    return this.precision;
  }

  destroy(): void {
    this.chart.remove();
  }
}

/**
 * Draws the green (take-profit) and red (stop-loss) box of each trade, like
 * TradingView's position tool. It is a "primitive": a small drawing plugin
 * the chart calls whenever it redraws.
 */
class PositionBoxes implements ISeriesPrimitive<Time> {
  private boxes: Box[] = [];
  private param: SeriesAttachedParameter<Time> | null = null;
  private readonly view: IPrimitivePaneView;

  constructor() {
    const renderer: IPrimitivePaneRenderer = {
      draw: () => undefined,
      drawBackground: (target) => {
        const param = this.param;
        if (!param || !this.boxes.length) return;
        const timeScale = param.chart.timeScale();
        const series = param.series;
        target.useBitmapCoordinateSpace(({ context, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
          for (const box of this.boxes) {
            const x1 = timeScale.timeToCoordinate(box.from as UTCTimestamp);
            const x2 = timeScale.timeToCoordinate(box.to as UTCTimestamp);
            const y1 = series.priceToCoordinate(box.top);
            const y2 = series.priceToCoordinate(box.bottom);
            if (x1 === null || x2 === null || y1 === null || y2 === null) continue; // not on the loaded candles
            const left = Math.round(Math.min(x1, x2) * hr);
            const width = Math.max(Math.round(Math.abs(x2 - x1) * hr), Math.round(6 * hr));
            const top = Math.round(Math.min(y1, y2) * vr);
            const height = Math.max(Math.round(Math.abs(y2 - y1) * vr), 1);
            context.fillStyle = box.color;
            context.fillRect(left, top, width, height);
          }
        });
      },
    };
    this.view = { zOrder: () => "bottom", renderer: () => renderer };
  }

  attached(param: SeriesAttachedParameter<Time>): void {
    this.param = param;
  }

  detached(): void {
    this.param = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }

  setBoxes(boxes: Box[]): void {
    this.boxes = boxes;
    this.param?.requestUpdate();
  }
}
