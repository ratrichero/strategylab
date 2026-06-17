import { utcToVN } from './time';

/** Alias for utcToVN — used by Market page */
export function utcToLocal(v?: string): string {
  return utcToVN(v);
}

export function fmtPct(v: number, dec = 2): string {
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(dec)}%`;
}

export function fmtUSD(v: number): string {
  return "$" + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
