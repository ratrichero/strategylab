/**
 * All time utilities — always display as Vietnam time (UTC+7)
 * DB stores naive UTC. We add +7h and use getUTC* to read shifted values.
 */

const VN_OFFSET_MS = 7 * 60 * 60 * 1000; // +7 hours in ms

/** Parse a UTC string (with or without Z/+) to ms timestamp */
export function parseUtcMs(v: string | undefined | null): number {
  if (!v) return 0;
  let s = String(v);
  if (!s.includes('Z') && !s.includes('+')) s += 'Z';
  const d = new Date(s);
  return isNaN(d.getTime()) ? 0 : d.getTime();
}

/** Format UTC timestamp → "MM/dd HH:mm" in VN timezone (UTC+7) */
export function utcToVN(v: string | undefined | null): string {
  if (!v) return '-';
  const ms = parseUtcMs(v);
  if (!ms) return '-';
  // Shift to VN time, then read using getUTC* (avoids browser tz)
  const vn = new Date(ms + VN_OFFSET_MS);
  const M = String(vn.getUTCMonth() + 1).padStart(2, '0');
  const D = String(vn.getUTCDate()).padStart(2, '0');
  const h = String(vn.getUTCHours()).padStart(2, '0');
  const m = String(vn.getUTCMinutes()).padStart(2, '0');
  return `${M}/${D} ${h}:${m}`;
}

/** Format UTC timestamp → full "YYYY-MM-dd HH:mm:ss" in VN timezone */
export function utcToVNFull(v: string | undefined | null): string {
  if (!v) return '-';
  const ms = parseUtcMs(v);
  if (!ms) return '-';
  const vn = new Date(ms + VN_OFFSET_MS);
  const Y = vn.getUTCFullYear();
  const M = String(vn.getUTCMonth() + 1).padStart(2, '0');
  const D = String(vn.getUTCDate()).padStart(2, '0');
  const h = String(vn.getUTCHours()).padStart(2, '0');
  const m = String(vn.getUTCMinutes()).padStart(2, '0');
  const s = String(vn.getUTCSeconds()).padStart(2, '0');
  return `${Y}-${M}-${D} ${h}:${m}:${s}`;
}

/** Get today's date string in VN timezone: "YYYY-MM-DD" */
export function getTodayVN(): string {
  const vn = new Date(Date.now() + VN_OFFSET_MS);
  const Y = vn.getUTCFullYear();
  const M = String(vn.getUTCMonth() + 1).padStart(2, '0');
  const D = String(vn.getUTCDate()).padStart(2, '0');
  return `${Y}-${M}-${D}`;
}

/**
 * Convert VN date range for ALL backend APIs.
 * Send plain "YYYY-MM-DD" — backend _parse_vn_date handles:
 *   start "2026-06-15" → UTC 2026-06-14T17:00:00
 *   end   "2026-06-15" → UTC 2026-06-15T17:00:00 (auto +1 day exclusive)
 * Same approach as Edge Discovery (confirmed working).
 */
export function toUtcRangeFromVNDate(startDate: string, endDate: string) {
  return { start: startDate || '', end: endDate || '' };
}

/** Normalize a UTC string from DB (add Z if missing) */
export function normalizeUtcString(v: string | undefined | null): string {
  if (!v) return v as any;
  const s = String(v);
  return !s.includes('Z') && !s.includes('+') ? s + 'Z' : s;
}

/** Normalize all date fields on a signal/trade object */
export function normalizeSignalDates<T extends Record<string, any>>(s: T): T {
  return {
    ...s,
    candle_time: normalizeUtcString(s.candle_time),
    exit_time: normalizeUtcString(s.exit_time),
    created_at: normalizeUtcString(s.created_at),
  } as T;
}

/**
 * Format a UTC ms timestamp → "MM/dd HH:mm" in VN for chart labels.
 * Use this in equity curve / chart data preparation.
 */
export function msToVNLabel(ms: number): string {
  if (!ms) return '';
  const vn = new Date(ms + VN_OFFSET_MS);
  const M = String(vn.getUTCMonth() + 1).padStart(2, '0');
  const D = String(vn.getUTCDate()).padStart(2, '0');
  const h = String(vn.getUTCHours()).padStart(2, '0');
  const m = String(vn.getUTCMinutes()).padStart(2, '0');
  return `${M}/${D} ${h}:${m}`;
}
