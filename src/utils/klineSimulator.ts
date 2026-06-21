// @ts-nocheck
/* eslint-disable */
/**
 * Kline 1m simulator — fetch from Binance Futures, cache, batch.
 * Used by Research page when user overrides RR/SL/TP.
 */

const BINANCE_FAPI = 'https://fapi.binance.com/fapi/v1/klines';
const MAX_LIMIT = 1500;            // Binance max per request
const MAX_DAYS = 3;                // Cap simulation window
const MS_PER_MIN = 60_000;
const MS_PER_DAY = 86_400_000;
const CHART_CONTEXT_BEFORE_MS = 30 * MS_PER_MIN;

// In-memory cache: key = `${symbol}_${startMs}_${endMs}`
const klineCache = new Map();

/**
 * Fetch 1m klines for a symbol over a time range, auto-paginate.
 * Returns array of { openTime, open, high, low, close, volume }
 */
export async function fetchKlines1m(symbol, startMs, endMs) {
  const cacheKey = `${symbol}_${startMs}_${endMs}`;
  if (klineCache.has(cacheKey)) return klineCache.get(cacheKey);

  const allKlines = [];
  let cursor = startMs;
  let safety = 0;

  while (cursor < endMs && safety < 20) {
    safety++;
    const url = `${BINANCE_FAPI}?symbol=${symbol}&interval=1m&startTime=${cursor}&endTime=${endMs}&limit=${MAX_LIMIT}`;
    try {
      const res = await fetch(url);
      if (!res.ok) {
        console.warn(`[Kline] ${symbol} HTTP ${res.status}`);
        break;
      }
      const data = await res.json();
      if (!Array.isArray(data) || data.length === 0) break;

      for (const k of data) {
        allKlines.push({
          openTime: k[0],
          open: parseFloat(k[1]),
          high: parseFloat(k[2]),
          low: parseFloat(k[3]),
          close: parseFloat(k[4]),
          volume: parseFloat(k[5]),
        });
      }

      const lastOpen = data[data.length - 1][0];
      if (data.length < MAX_LIMIT) break;
      cursor = lastOpen + MS_PER_MIN;
    } catch (e) {
      console.error(`[Kline] ${symbol} fetch error:`, e);
      break;
    }
  }

  klineCache.set(cacheKey, allKlines);
  return allKlines;
}

/**
 * Batch fetcher with concurrency control and progress callback.
 * tasks: Array<{ symbol, startMs, endMs }>
 * onProgress: (done, total) => void
 */
export async function batchFetchKlines(tasks, onProgress, batchSize = 3, delayMs = 250) {
  const results = new Map();
  let done = 0;

  for (let i = 0; i < tasks.length; i += batchSize) {
    const batch = tasks.slice(i, i + batchSize);
    for (const t of batch) {
      const klines = await fetchKlines1m(t.symbol, t.startMs, t.endMs);
      results.set(t.symbol, klines);
      done++;
      if (onProgress) onProgress(done, tasks.length);
      if (delayMs > 0 && done < tasks.length) {
        await new Promise(r => setTimeout(r, delayMs));
      }
    }
    if (i + batchSize < tasks.length) {
      await new Promise(r => setTimeout(r, delayMs));
    }
  }
  return results;
}

export function getTradeEntryMs(t) {
  const anchorStr = t?.entry_time || t?.filled_at || t?.pending_filled_at || t?.created_at || t?.candle_time;
  if (!anchorStr) return NaN;
  return new Date(anchorStr).getTime();
}

/**
 * Given trades, compute unique symbols + their global time windows.
 * Each trade contributes: [filled_at, filled_at + 3 days] (capped by exit_time + buffer).
 * Returns Array<{ symbol, startMs, endMs }>.
 */
export function buildFetchPlan(trades) {
  const bySymbol = new Map();

  for (const t of trades) {
    const symbol = t.symbol;
    if (!symbol) continue;

    const anchorMs = getTradeEntryMs(t);
    if (!Number.isFinite(anchorMs)) continue;

    const exitMs = t.exit_time ? new Date(t.exit_time).getTime() : 0;
    const endCap = anchorMs + MAX_DAYS * MS_PER_DAY;
    // End = min(anchor + 3d, max(exit + 1h buffer, anchor + 1h))
    const endMs = exitMs ? Math.min(endCap, exitMs + 60 * MS_PER_MIN) : endCap;
    const startMs = Math.max(0, anchorMs - CHART_CONTEXT_BEFORE_MS);

    if (!bySymbol.has(symbol)) {
      bySymbol.set(symbol, { startMs, endMs });
    } else {
      const cur = bySymbol.get(symbol);
      cur.startMs = Math.min(cur.startMs, startMs);
      cur.endMs = Math.max(cur.endMs, endMs);
    }
  }

  return Array.from(bySymbol.entries()).map(([symbol, range]) => ({
    symbol,
    startMs: range.startMs,
    endMs: range.endMs,
  }));
}

/**
 * Simulate a single trade using 1m klines.
 *
 * @param trade - Trade object with entry_price, candle_time, direction, etc.
 * @param klines - Full kline array for this symbol (will be sliced by time).
 * @param opts  - { slPct, tpPct, rrOverride, reverseDirection }
 *
 * Logic:
 *   1. Determine effective direction (reverse if requested).
 *   2. Compute SL/TP %:
 *      - If slPct+tpPct given → use directly.
 *      - Else if rrOverride given → derive sl_pct from original SL distance, tp = sl * rr.
 *   3. Compute SL/TP absolute prices from entry_price.
 *   4. Iterate klines from filled time, check high/low vs SL/TP.
 *   5. If both hit in same candle → conservative: SL wins (worst-case).
 *   6. If no hit after MAX_DAYS → NOT_COUNT.
 *
 * Returns: { sim_result, sim_status, sim_counted, sim_sl, sim_tp, hit_at_ms,
 *            exit_reason, slices_used, _debug_* }
 */
export function simulateTradeWithKlines(trade, klines, opts) {
  const entry = Number(trade.entry_price) || 0;
  if (!entry || !klines || klines.length === 0) {
    return {
      sim_result: null,
      sim_status: 'NOT_COUNT',
      sim_counted: false,
      sim_sl: null,
      sim_tp: null,
      hit_at_ms: null,
      exit_reason: 'no_data',
      _debug_no_kline: true,
      _debug_mae: null,
      _debug_mfe: null,
      _debug_hit_sl: false,
      _debug_hit_tp: false,
    };
  }

  // Effective direction
  let direction = trade.direction;
  if (opts.reverseDirection) {
    direction = direction === 'LONG' ? 'SHORT' : 'LONG';
  }

  // SL/TP %
  let slPct = null, tpPct = null;
  if (opts.slPct != null && opts.tpPct != null && opts.slPct > 0 && opts.tpPct > 0) {
    slPct = Math.abs(opts.slPct);
    tpPct = Math.abs(opts.tpPct);
  } else if (opts.rrOverride != null && opts.rrOverride > 0) {
    const origSL = Number(trade.stop_loss) || 0;
    slPct = origSL && entry ? (Math.abs(origSL - entry) / entry) * 100 : 2.0;
    tpPct = slPct * opts.rrOverride;
  } else {
    // No simulation params — shouldn't be called
    return {
      sim_result: trade.sim_result,
      sim_status: trade.sim_status || trade.status,
      sim_counted: true,
      sim_sl: trade.stop_loss,
      sim_tp: trade.take_profit,
      hit_at_ms: null,
      exit_reason: trade.exit_reason || '',
    };
  }

  // Absolute SL/TP
  const slPrice = direction === 'LONG' ? entry * (1 - slPct / 100) : entry * (1 + slPct / 100);
  const tpPrice = direction === 'LONG' ? entry * (1 + tpPct / 100) : entry * (1 - tpPct / 100);

  // Start scanning from actual/fallback entry time.
  const anchorMs = getTradeEntryMs(trade);
  if (!Number.isFinite(anchorMs)) {
    return {
      sim_result: null,
      sim_status: 'NOT_COUNT',
      sim_counted: false,
      sim_sl: slPrice,
      sim_tp: tpPrice,
      hit_at_ms: null,
      exit_reason: 'invalid_entry_time',
      _debug_mae: null,
      _debug_mfe: null,
      _debug_sl_pct: slPct,
      _debug_tp_pct: tpPct,
      _debug_hit_sl: false,
      _debug_hit_tp: false,
      _debug_direction_used: direction,
    };
  }
  const maxMs = anchorMs + MAX_DAYS * MS_PER_DAY;

  let hit = null;
  let scanned = 0;
  let maxAdversePct = 0;
  let maxFavorablePct = 0;

  for (const k of klines) {
    if (k.openTime < anchorMs) continue;
    if (k.openTime > maxMs) break;
    scanned++;

    let adversePct = 0;
    let favorablePct = 0;
    if (direction === 'LONG') {
      adversePct = Math.max(0, ((entry - k.low) / entry) * 100);
      favorablePct = Math.max(0, ((k.high - entry) / entry) * 100);
    } else {
      adversePct = Math.max(0, ((k.high - entry) / entry) * 100);
      favorablePct = Math.max(0, ((entry - k.low) / entry) * 100);
    }
    maxAdversePct = Math.max(maxAdversePct, adversePct);
    maxFavorablePct = Math.max(maxFavorablePct, favorablePct);

    const hitSL = direction === 'LONG' ? k.low <= slPrice : k.high >= slPrice;
    const hitTP = direction === 'LONG' ? k.high >= tpPrice : k.low <= tpPrice;

    if (hitSL && hitTP) {
      // Conservative: SL wins
      hit = { side: 'SL', at: k.openTime };
      break;
    } else if (hitSL) {
      hit = { side: 'SL', at: k.openTime };
      break;
    } else if (hitTP) {
      hit = { side: 'TP', at: k.openTime };
      break;
    }
  }

  if (!hit) {
    return {
      sim_result: null,
      sim_status: 'NOT_COUNT',
      sim_counted: false,
      sim_sl: slPrice,
      sim_tp: tpPrice,
      hit_at_ms: null,
      exit_reason: 'timeout',
      _debug_mae: maxAdversePct,
      _debug_mfe: maxFavorablePct,
      _debug_hit_sl: false,
      _debug_hit_tp: false,
      _debug_sl_pct: slPct,
      _debug_tp_pct: tpPct,
      _debug_scanned: scanned,
      _debug_direction_used: direction,
    };
  }

  const result = hit.side === 'TP' ? tpPct : -slPct;
  return {
    sim_result: result,
    sim_status: hit.side === 'TP' ? 'WIN' : 'LOSS',
    sim_counted: true,
    sim_sl: slPrice,
    sim_tp: tpPrice,
    hit_at_ms: hit.at,
    exit_reason: hit.side === 'TP' ? 'tp' : 'sl',
    _debug_mae: maxAdversePct,
    _debug_mfe: maxFavorablePct,
    _debug_hit_sl: hit.side === 'SL',
    _debug_hit_tp: hit.side === 'TP',
    _debug_sl_pct: slPct,
    _debug_tp_pct: tpPct,
    _debug_scanned: scanned,
    _debug_direction_used: direction,
  };
}

export function clearKlineCache() {
  klineCache.clear();
}

export function getKlineCacheSize() {
  return klineCache.size;
}
