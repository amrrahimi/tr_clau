// Number formatting for prices and volumes. Digits stay Latin (0-9) in both
// languages so prices look the same as on the exchange.

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

// ---------- chart times in the computer's local time ----------
// Candle times stay in UTC everywhere; only what is displayed is local.

const pad = (n: number) => String(n).padStart(2, "0");

/** The time shown under the crosshair, e.g. "2026-10-24 17:20". */
export function formatLocalDateTime(timeSeconds: number): string {
  const d = new Date(timeSeconds * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Labels along the time axis. The chart says what kind of mark it is:
 * 0 year, 1 month, 2 day of month, 3 time, 4 time with seconds.
 */
export function formatLocalTick(timeSeconds: number, markType: number): string {
  const d = new Date(timeSeconds * 1000);
  switch (markType) {
    case 0: return String(d.getFullYear());
    case 1: return MONTHS[d.getMonth()];
    case 2: return String(d.getDate());
    case 4: return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    default: return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
}

/** Show the futures symbol "BTC/USDT:USDT" as "BTC/USDT". */
export function displaySymbol(symbol: string): string {
  return symbol.split(":")[0];
}
