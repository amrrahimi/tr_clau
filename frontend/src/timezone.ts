// Time zones for showing times on the chart. Display only: candle times stay
// in UTC everywhere else, so calculations never change with this choice.
// Daylight saving time (London, New York, Sydney...) is handled by the
// browser's built-in time zone database (Intl), not by fixed offsets.

import type { MessageKey } from "./locales/en.ts";

/** "local" = this computer's zone; otherwise an IANA zone name such as "Europe/London". */
export type ZoneId = string;

export interface ZoneOption {
  id: ZoneId;
  label: MessageKey;
}

export const ZONES: ZoneOption[] = [
  { id: "UTC", label: "tz.utc" },
  { id: "local", label: "tz.local" },
  { id: "Asia/Tehran", label: "tz.tehran" },
  { id: "Asia/Dubai", label: "tz.dubai" },
  { id: "Europe/Moscow", label: "tz.moscow" },
  { id: "Europe/Istanbul", label: "tz.istanbul" },
  { id: "Europe/London", label: "tz.london" },
  { id: "Europe/Berlin", label: "tz.frankfurt" }, // Frankfurt uses Berlin's zone
  { id: "America/New_York", label: "tz.newYork" },
  { id: "America/Chicago", label: "tz.chicago" },
  { id: "Asia/Tokyo", label: "tz.tokyo" },
  { id: "Asia/Hong_Kong", label: "tz.hongKong" },
  { id: "Asia/Singapore", label: "tz.singapore" },
  { id: "Australia/Sydney", label: "tz.sydney" },
];

export const DEFAULT_ZONE: ZoneId = "local";

export interface TimeParts {
  year: number;
  month: number; // 1-12
  day: number;
  hour: number; // 0-23
  minute: number;
  second: number;
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatterFor(zone: string): Intl.DateTimeFormat {
  let f = formatters.get(zone);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      hourCycle: "h23",
      year: "numeric", month: "numeric", day: "numeric",
      hour: "numeric", minute: "numeric", second: "numeric",
    });
    formatters.set(zone, f);
  }
  return f;
}

/** The calendar date and clock time of a moment, as seen in a zone. */
export function zoneParts(timeMs: number, zone: ZoneId): TimeParts {
  if (zone === "local") {
    const d = new Date(timeMs);
    return {
      year: d.getFullYear(), month: d.getMonth() + 1, day: d.getDate(),
      hour: d.getHours(), minute: d.getMinutes(), second: d.getSeconds(),
    };
  }
  const parts: Record<string, number> = {};
  for (const p of formatterFor(zone).formatToParts(new Date(timeMs))) {
    if (p.type !== "literal") parts[p.type] = Number(p.value);
  }
  return {
    year: parts.year, month: parts.month, day: parts.day,
    hour: parts.hour % 24, minute: parts.minute, second: parts.second,
  };
}

/** Minutes the zone is ahead of UTC at that moment (e.g. Tehran +210). */
export function offsetMinutes(timeMs: number, zone: ZoneId): number {
  const p = zoneParts(timeMs, zone);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return Math.round((asUtc - Math.floor(timeMs / 1000) * 1000) / 60000);
}

/** +210 -> "UTC+3:30", -300 -> "UTC-5", 0 -> "UTC". */
export function formatOffset(minutes: number): string {
  if (minutes === 0) return "UTC";
  const sign = minutes > 0 ? "+" : "-";
  const abs = Math.abs(minutes);
  const hours = Math.floor(abs / 60);
  const mins = abs % 60;
  return `UTC${sign}${hours}${mins ? ":" + String(mins).padStart(2, "0") : ""}`;
}

/** True if this computer knows the zone (very old systems may not). */
export function isKnownZone(zone: ZoneId): boolean {
  if (zone === "local") return true;
  try {
    formatterFor(zone);
    return true;
  } catch {
    return false;
  }
}

// ---------- remembering the choice ----------

const STORAGE_KEY = "trading-bot.timeZone";

export function loadZone(storage: Pick<Storage, "getItem"> | undefined = safeStorage()): ZoneId {
  try {
    const saved = storage?.getItem(STORAGE_KEY);
    return saved && ZONES.some((z) => z.id === saved) && isKnownZone(saved) ? saved : DEFAULT_ZONE;
  } catch {
    return DEFAULT_ZONE;
  }
}

export function saveZone(zone: ZoneId, storage: Pick<Storage, "setItem"> | undefined = safeStorage()): void {
  try {
    storage?.setItem(STORAGE_KEY, zone);
  } catch {
    // ignore
  }
}

function safeStorage(): Storage | undefined {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
}
