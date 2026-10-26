// Number formatting for prices and volumes. Digits stay Latin (0-9) in both
// languages so prices look the same as on the exchange.

import { zoneParts, type ZoneId } from "./timezone.ts";

export function formatPrice(price: number | null | undefined, precision: number): string {
  if (price === null || price === undefined || !Number.isFinite(price)) return "—";
  return price.toLocaleString("en-US", {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  });
}

/** 1234567 -> "1.23M". Volumes only need to be compared, not read exactly. */
export function formatVolume(volume: number): string {
  if (!Number.isFinite(volume) || volume <= 0) return "—";
  const units: [number, string][] = [[1e9, "B"], [1e6, "M"], [1e3, "K"]];
  for (const [size, unit] of units) {
    if (volume >= size) return `${(volume / size).toFixed(2)}${unit}`;
  }
  return volume.toFixed(0);
}

// ---------- chart times in the chosen time zone ----------
// Candle times stay in UTC everywhere; only what is displayed changes.
// `zone` is "local" (this computer), "UTC" or a zone name like "Europe/London".

const pad = (n: number) => String(n).padStart(2, "0");

/** The time shown under the crosshair, e.g. "2026-10-24 17:20". */
export function formatLocalDateTime(timeSeconds: number, zone: ZoneId = "local"): string {
  const p = zoneParts(timeSeconds * 1000, zone);
  return `${p.year}-${pad(p.month)}-${pad(p.day)} ${pad(p.hour)}:${pad(p.minute)}`;
}

/** "17:20" if the time is today (in that zone), otherwise "2026-10-24 17:20". */
export function formatSince(timeSeconds: number, nowMs: number = Date.now(), zone: ZoneId = "local"): string {
  const p = zoneParts(timeSeconds * 1000, zone);
  const now = zoneParts(nowMs, zone);
  const sameDay = p.year === now.year && p.month === now.month && p.day === now.day;
  return sameDay ? `${pad(p.hour)}:${pad(p.minute)}` : formatLocalDateTime(timeSeconds, zone);
}

/** A running clock, e.g. "14:06:32". */
export function formatClock(nowMs: number, zone: ZoneId = "local"): string {
  const p = zoneParts(nowMs, zone);
  return `${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Labels along the time axis. The chart says what kind of mark it is:
 * 0 year, 1 month, 2 day of month, 3 time, 4 time with seconds.
 */
export function formatLocalTick(timeSeconds: number, markType: number, zone: ZoneId = "local"): string {
  const p = zoneParts(timeSeconds * 1000, zone);
  switch (markType) {
    case 0: return String(p.year);
    case 1: return MONTHS[p.month - 1];
    case 2: return String(p.day);
    case 4: return `${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
    default: return `${pad(p.hour)}:${pad(p.minute)}`;
  }
}

/** Show the futures symbol "BTC/USDT:USDT" as "BTC/USDT". */
export function displaySymbol(symbol: string): string {
  return symbol.split(":")[0];
}
