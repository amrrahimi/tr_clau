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
  type IPriceLine,
  type IPrimitivePaneRenderer,
  type IPrimitivePaneView,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type ISeriesPrimitive,
  type Logical,
  type LogicalRange,
  type SeriesAttachedParameter,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { pricePrecision } from "./candles.ts";
import { formatLocalDateTime, formatLocalTick } from "./format.ts";
import { tradeBoxes, tradeMarkers, type Box, type MarkerLabels } from "./strategyState.ts";
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
/** How close (pixels) the mouse must be to a draggable line to grab it. */
const DRAG_GRAB_PX = 6;

/** What is written and drawn inside one box of a position (matched by entry time and kind). */
export interface BoxDecor {
  from: number;
  kind: "profit" | "loss";
  texts: string[];
  lines: { price: number; color: string; dash?: boolean; style?: "dotted" | "dashed" | "solid"; width?: number }[];
}

/** A price level line of an open position. With drag, the owner can move it with the mouse. */
export interface Level {
  key?: string;
  price: number;
  color: string;
  title: string;
  style?: "dotted" | "dashed" | "solid";
  width?: number;
  axisLabel?: boolean;   // default true
  hidden?: boolean;      // not drawn (its picture is drawn elsewhere, e.g. inside a box) but still draggable
  drag?: {
    /** While dragging: the line's label, and other lines that move along (e.g. the break-even trigger). */
    onMove(price: number): { title: string; others?: Record<string, { price: number; title: string }> };
    onDrop(price: number): void;
  };
}

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
  private levelLines = new Map<string, { line: IPriceLine; level: Level }>();
  private dragging: { key: string; level: Level; price: number } | null = null;
  private pendingLevels: Level[] | null = null;   // levels that came in while a line was being dragged

  constructor(container: HTMLElement, private readonly onNeedOlder: () => void) {
    this.chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "rgba(0, 0, 0, 0)" },   // glass: the panel behind it is the background
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
    this.listenForLineDrags(container);
  }

  /**
   * The owner drags a stop-loss or take-profit line with the mouse. The library's price lines
   * cannot be dragged, so: a press near a draggable line (in the price pane) starts a drag, the
   * chart's own scrolling is switched off meanwhile, the line follows the mouse, and on release
   * the level's onDrop gets the new price.
   */
  private listenForLineDrags(container: HTMLElement): void {
    const yOf = (e: MouseEvent) => e.clientY - container.getBoundingClientRect().top;
    const near = (y: number): { key: string; level: Level } | null => {
      if (y > (this.chart.panes()[0]?.getHeight() ?? 0)) return null;   // below the price pane
      let best: { key: string; level: Level; d: number } | null = null;
      for (const [key, { level }] of this.levelLines) {
        if (!level.drag) continue;
        const ly = this.series.priceToCoordinate(level.price);
        if (ly === null) continue;
        const d = Math.abs(ly - y);
        if (d <= DRAG_GRAB_PX && (!best || d < best.d)) best = { key, level, d };
      }
      return best;
    };
    const grab = (e: MouseEvent) => {
      if (e.button !== 0) return;
      if (this.dragging) {   // the mouse event after the pointer event: keep it from the chart too
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      const hit = near(yOf(e));
      if (!hit) return;
      e.preventDefault();
      e.stopPropagation();
      this.dragging = { key: hit.key, level: hit.level, price: hit.level.price };
      this.chart.applyOptions({ handleScroll: false, handleScale: false });
      container.style.cursor = "ns-resize";
    };
    // Capture phase: seen before the chart's own handlers (some versions listen to pointer, some to mouse events).
    container.addEventListener("pointerdown", grab, true);
    container.addEventListener("mousedown", grab, true);
    container.addEventListener("pointermove", (e) => {
      if (!this.dragging) container.style.cursor = near(yOf(e)) ? "ns-resize" : "";
    });
    window.addEventListener("pointermove", (e) => {
      const drag = this.dragging;
      if (!drag) return;
      const price = this.series.coordinateToPrice(yOf(e));
      if (price === null || !(price > 0)) return;
      drag.price = price;
      const preview = drag.level.drag!.onMove(price);
      this.levelLines.get(drag.key)?.line.applyOptions({ price, title: preview.title });
      for (const [key, other] of Object.entries(preview.others ?? {})) {
        this.levelLines.get(key)?.line.applyOptions(other);
      }
    });
    window.addEventListener("pointerup", () => {
      const drag = this.dragging;
      if (!drag) return;
      this.dragging = null;
      this.chart.applyOptions({ handleScroll: true, handleScale: true });
      container.style.cursor = "";
      const pending = this.pendingLevels;
      this.pendingLevels = null;
      if (pending) this.setLevels(pending);
      if (drag.price !== drag.level.price) drag.level.drag!.onDrop(drag.price);
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

  /** Show candles from..to (by their place in the list); past the last one is empty space on the right. */
  showRange(from: number, to: number): void {
    this.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, from), to });
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
  setIndicators(results: IndicatorResult[], look?: { width: number; style: "dotted" | "dashed" | "solid" }): void {
    const signature = layoutSignature(results);
    if (signature !== this.signature) this.rebuild(results);
    this.signature = signature;
    if (look) {   // the owner's line settings for strategy lines (bot chart)
      const lineStyle = look.style === "dashed" ? LineStyle.Dashed : look.style === "dotted" ? LineStyle.Dotted : LineStyle.Solid;
      for (const r of results) {
        for (const o of r.outputs) {
          if (o.style !== "histogram") this.indicatorSeries.get(`${r.id}:${o.key}`)?.applyOptions({ lineWidth: look.width as 1, lineStyle });
        }
      }
    }
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
  setTrades(trades: Trade[], lastTime: number | null, labels?: MarkerLabels,
    signal?: { trade: Trade; labels: MarkerLabels } | null,
    show: { markers?: boolean; boxes?: boolean } = {}): void {
    const markers = show.markers === false ? [] : tradeMarkers(trades, labels);
    const boxes = show.boxes === false ? [] : tradeBoxes(trades, lastTime);
    if (signal) {
      // The fresh signal: its own words ("long signal") and boxes on the forming candle.
      markers.push(...tradeMarkers([signal.trade], signal.labels));
      markers.sort((a, b) => a.time - b.time);
      boxes.push(...tradeBoxes([signal.trade], signal.trade.entryTime).map((b) => ({ ...b, minBars: 6 })));
    }
    this.markers.setMarkers(markers.map((m) => ({ ...m, time: m.time as UTCTimestamp })));
    this.boxes.setBoxes(boxes);
  }

  /** Text and short lines drawn inside the position boxes, and the signal candles' bands. */
  setDecor(decor: BoxDecor[], signalTimes: number[] = []): void {
    this.boxes.setDecor(decor, signalTimes);
  }

  /**
   * Price levels of open positions on the price axis (entry, stop-loss, take-profit): a dotted line
   * across the chart and the price in a coloured label on the axis, like the current price.
   */
  setLevels(levels: Level[]): void {
    if (this.dragging) {
      this.pendingLevels = levels;   // drawn when the owner lets go of the line
      return;
    }
    for (const { line } of this.levelLines.values()) this.series.removePriceLine(line);
    this.levelLines.clear();
    levels.forEach((l, n) => {
      const line = this.series.createPriceLine({
        price: l.price, color: l.color, lineWidth: (l.width ?? (l.drag ? 2 : 1)) as 1 | 2 | 3 | 4,
        lineStyle: l.style === "dashed" ? LineStyle.Dashed : l.style === "solid" ? LineStyle.Solid : LineStyle.Dotted,
        axisLabelVisible: !l.hidden && l.axisLabel !== false, title: l.hidden ? "" : l.title, lineVisible: !l.hidden,
      });
      this.levelLines.set(l.key ?? String(n), { line, level: l });
    });
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
  private decor: BoxDecor[] = [];
  private signals: number[] = [];
  private param: SeriesAttachedParameter<Time> | null = null;
  private readonly view: IPrimitivePaneView;

  /** Pixel rectangle of a box on screen, or null when it is not on the loaded candles. */
  private rect(box: Box): { left: number; right: number; top: number; bottom: number } | null {
    const param = this.param!;
    const timeScale = param.chart.timeScale();
    const x1 = timeScale.timeToCoordinate(box.from as UTCTimestamp);
    const x2 = timeScale.timeToCoordinate(box.to as UTCTimestamp);
    const y1 = param.series.priceToCoordinate(box.top);
    const y2 = param.series.priceToCoordinate(box.bottom);
    if (x1 === null || x2 === null || y1 === null || y2 === null) return null;
    const barSpacing = Math.abs((timeScale.logicalToCoordinate(1 as Logical) ?? 0) - (timeScale.logicalToCoordinate(0 as Logical) ?? 0));
    const width = Math.max(Math.abs(x2 - x1), Math.max(6, (box.minBars ?? 0) * barSpacing));
    const left = Math.min(x1, x2);
    return { left, right: left + width, top: Math.min(y1, y2), bottom: Math.max(y1, y2) };
  }

  constructor() {
    const renderer: IPrimitivePaneRenderer = {
      draw: (target) => {   // inside the boxes: short lines (profit lock) and the texts
        const param = this.param;
        if (!param || !this.decor.length) return;
        target.useMediaCoordinateSpace(({ context }) => {
          for (const d of this.decor) {
            const box = this.boxes.find((b) => b.from === d.from && b.kind === d.kind);
            if (!box) continue;
            const r = this.rect(box);
            if (!r) continue;
            for (const line of d.lines) {
              const y = param.series.priceToCoordinate(line.price);
              if (y === null) continue;
              context.strokeStyle = line.color;
              const style = line.style ?? (line.dash ? "dashed" : "solid");
              context.lineWidth = line.width ?? 2;
              context.setLineDash(style === "dashed" ? [5, 4] : style === "dotted" ? [1, 3] : []);
              context.beginPath();
              context.moveTo(r.left, y);
              context.lineTo(r.right, y);
              context.stroke();
            }
            context.setLineDash([]);
            context.font = "11px sans-serif";
            context.fillStyle = "rgba(255,255,255,0.85)";
            context.textBaseline = "top";
            const near = d.kind === "profit" ? r.top + 3 : r.bottom - 3 - 13 * d.texts.length;
            d.texts.forEach((text, n) => context.fillText(text, r.left + 4, near + 13 * n));
          }
        });
      },
      drawBackground: (target) => {
        const param = this.param;
        if (!param || (!this.boxes.length && !this.signals.length)) return;
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
            // Current width of one candle (changes with zoom).
            const barSpacing = Math.abs((timeScale.logicalToCoordinate(1 as Logical) ?? 0) - (timeScale.logicalToCoordinate(0 as Logical) ?? 0));
            const minWidth = Math.max(6, (box.minBars ?? 0) * barSpacing);
            const width = Math.max(Math.round(Math.abs(x2 - x1) * hr), Math.round(minWidth * hr));
            const top = Math.round(Math.min(y1, y2) * vr);
            const height = Math.max(Math.round(Math.abs(y2 - y1) * vr), 1);
            context.fillStyle = box.color;
            context.fillRect(left, top, width, height);
          }
          // The candle that gave the signal: a light band over its whole height.
          const barSpacing = Math.abs((timeScale.logicalToCoordinate(1 as Logical) ?? 0) - (timeScale.logicalToCoordinate(0 as Logical) ?? 0));
          for (const t of this.signals) {
            const x = timeScale.timeToCoordinate(t as UTCTimestamp);
            if (x === null) continue;
            context.fillStyle = "rgba(255, 213, 79, 0.16)";
            context.fillRect(Math.round((x - barSpacing / 2) * hr), 0, Math.max(2, Math.round(barSpacing * hr)), context.canvas.height);
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

  setDecor(decor: BoxDecor[], signals: number[]): void {
    this.decor = decor;
    this.signals = signals;
    this.param?.requestUpdate();
  }
}
