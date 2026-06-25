import time
from threading import Lock
from datetime import datetime, timezone
from typing import Dict, Optional

from app.db.session import SessionLocal
from app.db.models import PendingSignal, Signal, ScanDebug, ScanRun


_CONTEXT_CACHE: Dict[str, dict] = {}
_CONTEXT_LOCK = Lock()

_PRIMARY_TF = "15m"
_SUPPORTIVE_TFS = ["1h", "4h"]

_FRESH_MAX_AGE = {
    "15m": 20 * 60,
    "1h": 90 * 60,
    "4h": 6 * 60 * 60,
}

_STALE_MAX_AGE = {
    "15m": 45 * 60,
    "1h": 3 * 60 * 60,
    "4h": 12 * 60 * 60,
}


def _cache_key(symbol: str, timeframe: str) -> str:
    return f"{symbol.upper()}::{timeframe}"


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dt_to_ts(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return None


def _classify_freshness(timeframe: str, age_seconds: Optional[float]) -> str:
    if age_seconds is None:
        return "missing"

    fresh_limit = _FRESH_MAX_AGE.get(timeframe, 20 * 60)
    stale_limit = _STALE_MAX_AGE.get(timeframe, fresh_limit * 2)

    if age_seconds <= fresh_limit:
        return "fresh"
    if age_seconds <= stale_limit:
        return "stale"
    return "expired"


def _normalize_payload(payload: dict, symbol: str, timeframe: str) -> dict:
    now = time.time()
    snapshot_ts = _dt_to_ts(payload.get("snapshot_ts")) or now
    age_seconds = max(0.0, now - snapshot_ts)
    vol_ratio = payload.get("vol_ratio")
    if vol_ratio is None:
        vol_ratio = payload.get("volume_ratio")

    normalized = {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "source": payload.get("source") or "unknown",
        "snapshot_ts": snapshot_ts,
        "updated_at": _dt_to_ts(payload.get("updated_at")) or now,
        "age_seconds": age_seconds,
        "freshness": _classify_freshness(timeframe, age_seconds),
        "regime": payload.get("regime"),
        "strategy_name": payload.get("strategy_name"),
        "pattern": payload.get("pattern"),
        "direction": payload.get("direction"),
        "trend_score": _safe_float(payload.get("trend_score")),
        "momentum_score": _safe_float(payload.get("momentum_score")),
        "volume_score": _safe_float(payload.get("volume_score")),
        "mtf_score": _safe_float(payload.get("mtf_score")),
        "derivative_bias": _safe_float(payload.get("derivative_bias")),
        "total_score": _safe_float(payload.get("total_score")),
        "ema50": _safe_float(payload.get("ema50")),
        "ema200": _safe_float(payload.get("ema200")),
        "ema200_slope": _safe_float(payload.get("ema200_slope")),
        "rsi": _safe_float(payload.get("rsi")),
        "rsi_slope": _safe_float(payload.get("rsi_slope")),
        "atr_percentile": _safe_float(payload.get("atr_percentile")),
        "bb_width": _safe_float(payload.get("bb_width")),
        "bb_position": _safe_float(payload.get("bb_position")),
        "close": _safe_float(payload.get("close")),
        "atr": _safe_float(payload.get("atr")),
        "vol_ratio": _safe_float(vol_ratio),
    }
    return normalized


def update_volatility_context_snapshot(symbol: str, timeframe: str, payload: dict):
    if not symbol or not timeframe or not isinstance(payload, dict):
        return

    key = _cache_key(symbol, timeframe)

    with _CONTEXT_LOCK:
        existing = _CONTEXT_CACHE.get(key) or {}
        merged = dict(existing)
        
        # FIX LỖI 1: Nếu là scan_basic (nến mới), PHẢI XÓA SẠCH rác candidate của nến cũ
        if payload.get("source") == "scan_basic":
            for k in ["strategy_name", "pattern", "direction", "trend_score", 
                      "momentum_score", "volume_score", "mtf_score", "derivative_bias", "total_score"]:
                merged.pop(k, None)

        for k, v in payload.items():
            if v is not None:
                merged[k] = v
                
        normalized = _normalize_payload(merged, symbol, timeframe)
        _CONTEXT_CACHE[key] = normalized

def _extract_snapshot_fields(indicators_snapshot: dict) -> dict:
    if not isinstance(indicators_snapshot, dict):
        return {}

    return {
        "ema50": indicators_snapshot.get("ema50"),
        "ema200": indicators_snapshot.get("ema200"),
        "ema200_slope": indicators_snapshot.get("ema200_slope"),
        "rsi": indicators_snapshot.get("rsi"),
        "rsi_slope": indicators_snapshot.get("rsi_slope"),
        "atr_percentile": indicators_snapshot.get("atr_percentile"),
        "bb_width": indicators_snapshot.get("bb_width"),
        "bb_position": indicators_snapshot.get("bb_position"),
        "close": indicators_snapshot.get("close"),
        "atr": indicators_snapshot.get("atr"),
        # XỬ LÝ ĐỒNG BỘ TÊN BIẾN
        "vol_ratio": indicators_snapshot.get("vol_ratio") or indicators_snapshot.get("volume_ratio"),
    }


def _load_from_cache(symbol: str, timeframe: str) -> Optional[dict]:
    key = _cache_key(symbol, timeframe)
    with _CONTEXT_LOCK:
        row = _CONTEXT_CACHE.get(key)
        if not row:
            return None
        return dict(row)


def _row_to_payload(row, symbol: str, timeframe: str, source: str) -> Optional[dict]:
    if row is None:
        return None

    indicators_snapshot = getattr(row, "indicators_snapshot", None) or {}
    payload = _extract_snapshot_fields(indicators_snapshot)

    payload.update({
        "source": source,
        "snapshot_ts": getattr(row, "candle_time", None) or getattr(row, "created_at", None),
        "updated_at": time.time(),
        "regime": getattr(row, "regime", None),
        "strategy_name": getattr(row, "strategy_name", None),
        "pattern": getattr(row, "pattern", None),
        "direction": getattr(row, "direction", None),
        "trend_score": getattr(row, "trend_score", None),
        "momentum_score": getattr(row, "momentum_score", None),
        "volume_score": getattr(row, "volume_score", None),
        "mtf_score": getattr(row, "mtf_score", None),
        "derivative_bias": getattr(row, "derivative_bias", None),
        "total_score": getattr(row, "signal_score", None) or getattr(row, "total_score", None),
    })

    return _normalize_payload(payload, symbol, timeframe)


def _load_from_db(symbol: str, timeframe: str) -> Optional[dict]:
    # FIX LỖI 4: Lấy hết ra, so sánh Timestamp, cái nào thật sự mới nhất thì lấy
    candidates = []
    try:
        with SessionLocal() as db:
            pending = db.query(PendingSignal).filter(
                PendingSignal.symbol == symbol, PendingSignal.timeframe == timeframe
            ).order_by(PendingSignal.candle_time.desc()).first()
            if pending: candidates.append((pending, getattr(pending, "candle_time", None), "db_pending_signal"))

            signal = db.query(Signal).filter(
                Signal.symbol == symbol, Signal.timeframe == timeframe
            ).order_by(Signal.candle_time.desc()).first()
            if signal: candidates.append((signal, getattr(signal, "candle_time", None), "db_signal"))

            scan_row = db.query(ScanDebug).join(ScanRun, ScanDebug.scan_id == ScanRun.id).filter(
                ScanDebug.symbol == symbol, ScanRun.timeframe == timeframe
            ).order_by(ScanDebug.candle_time.desc()).first()
            if scan_row: candidates.append((scan_row, getattr(scan_row, "candle_time", None), "db_scan_debug"))

            if not candidates:
                return None
            
            # Lọc bỏ None ts và tìm max
            valid_candidates = [c for c in candidates if c[1] is not None]
            if not valid_candidates:
                return None
                
            best_row, _, source_name = max(valid_candidates, key=lambda x: x[1])
            return _row_to_payload(best_row, symbol, timeframe, source_name)
            
    except Exception as e:
        print(f"[VOL CONTEXT] db fallback error {symbol}/{timeframe}: {type(e).__name__}: {e}")
    return None


def _load_context(symbol: str, timeframe: str) -> Optional[dict]:
    row = _load_from_cache(symbol, timeframe)
    if row is not None:
        return row

    row = _load_from_db(symbol, timeframe)
    if row is not None:
        update_volatility_context_snapshot(symbol, timeframe, row)
        return _load_from_cache(symbol, timeframe)

    return None


def build_volatility_context(alert: dict) -> dict:
    symbol = (alert.get("symbol") or "").upper()
    primary = _load_context(symbol, _PRIMARY_TF)
    
    if primary is None:
        context_state = "missing_context"
    elif primary.get("freshness") == "expired":
        context_state = "expired_context"
    elif primary.get("freshness") == "stale":
        context_state = "stale_context"
    else:
        context_state = "ok"

    supportive = {}
    # LỌC HIỆU SUẤT: Nếu primary missing hoặc expired, skip query supportive luôn cho nhẹ DB
    if context_state not in ["missing_context", "expired_context"]:
        for tf in _SUPPORTIVE_TFS:
            row = _load_context(symbol, tf)
            if row is not None:
                supportive[tf] = row

    return {
        "symbol": symbol,
        "primary_tf": _PRIMARY_TF,
        "primary": primary,
        "supportive": supportive,
        "context_state": context_state,
        "has_primary": primary is not None,
        "has_supportive": bool(supportive),
    }
