import { format } from "date-fns";

// DB stores naive UTC → append Z
export function normalizeUtc(v?: string): string {
  if (!v) return "";
  const s = String(v);
  return s.includes("Z") || s.includes("+") ? s : s.replace(" ", "T") + "Z";
}

export function parseUtcMs(v?: string): number {
  if (!v) return 0;
  const d = new Date(normalizeUtc(v));
  return isNaN(d.getTime()) ? 0 : d.getTime();
}

export function utcToLocal(v?: string): string {
  if (!v) return "-";
  const ms = parseUtcMs(v);
  return ms ? format(new Date(ms), "MM/dd HH:mm") : "-";
}

export function getTodayVN(): string {
  return new Date(Date.now() + 7 * 3600 * 1000).toISOString().slice(0, 10);
}

export function vnDateToUtcRange(start: string, end: string) {
  const s = start ? new Date(start + "T00:00:00+07:00").toISOString() : "";
  const e = end
    ? new Date(new Date(end + "T00:00:00+07:00").getTime() + 86400000).toISOString()
    : "";
  return { start: s, end: e };
}

export function fmtPct(v: number, dec = 2): string {
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(dec)}%`;
}

export function fmtUSD(v: number): string {
  return "$" + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
