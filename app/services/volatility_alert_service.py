import os
import json
import time
from collections import deque
from statistics import mean
from typing import Deque, Dict, List, Optional, Tuple

from app.core.bg_runner import start_daemon_job
from app.services.config_service import get_runtime_config
from app.services.telegram_service import send_telegram


class _SymbolState:
    def __init__(self):
        self.history: Deque[Tuple[float, float]] = deque()
        self.last_alert_at: float = 0.0
        self.last_alert_key: Optional[str] = None
        self.last_price: Optional[float] = None
        self.last_price_ts: float = 0.0

    def record_price(self, price: float, ts: float):
        if self.last_price is not None and self.last_price > 0:
            delta = abs(price - self.last_price) / self.last_price
            if delta < 0.0002 and ts - self.last_price_ts < 5:
                return

        self.history.append((ts, price))
        self.last_price = price
        self.last_price_ts = ts
        cutoff = ts - self.max_history
        while self.history and self.history[0][0] < cutoff:
            self.history.popleft()

    @property
    def max_history(self) -> float:
        return float(os.getenv("VOL_ALERT_HISTORY_SECONDS", "600"))

    def price_at(self, age_seconds: float, now: float) -> Optional[Tuple[float, float]]:
        target = now - age_seconds
        candidate = None
        for ts, price in self.history:
            if ts <= target:
                candidate = (price, now - ts)
            else:
                break
        return candidate

    def avg_short_move(self, now: float) -> float:
        moves: List[float] = []
        last_ts, last_price = None, None
        for ts, price in self.history:
            if last_ts is None:
                last_ts, last_price = ts, price
                continue
            if ts - last_ts < 20:
                continue
            if last_price and last_price > 0:
                moves.append(abs(price - last_price) / last_price * 100)
            last_ts, last_price = ts, price
        return mean(moves) if moves else 0.0


class VolatilityAlertService:
    def __init__(self):
        self._states: Dict[str, _SymbolState] = {}
        self._last_cycle = 0.0
        self._recent_alerts: Deque[dict] = deque(maxlen=50)
        self._table_ready = False
        self._load_config()

    def _load_config(self):
        """Load config from VOL_ALERT_CONFIG with env fallback."""
        cfg = get_runtime_config()
        vol_cfg = cfg.get("VOL_ALERT_CONFIG") or {}

        self._enabled = vol_cfg.get("enabled", os.getenv("ENABLE_VOL_ALERTS", "true").lower() in ["1", "true", "yes", "on"])
        self._cycle_delay = float(vol_cfg.get("cycle_seconds", os.getenv("VOL_ALERT_CYCLE_SECONDS", "3")))
        self._symbols_limit = int(vol_cfg.get("symbols_limit", os.getenv("VOL_ALERT_SYMBOL_LIMIT", "1200")))

        btc_cfg = vol_cfg.get("btc", {})
        self._btc_threshold_1m = float(btc_cfg.get("threshold_1m_pct", os.getenv("VOL_ALERT_BTC_1M_PCT", "2.0")))
        self._btc_threshold_5m = float(btc_cfg.get("threshold_5m_pct", os.getenv("VOL_ALERT_BTC_5M_PCT", "3.5")))
        self._btc_cooldown = float(btc_cfg.get("cooldown_minutes", os.getenv("VOL_ALERT_BTC_COOLDOWN_MINUTES", "20"))) * 60

        major_cfg = vol_cfg.get("major", {})
        self._major_threshold_1m = float(major_cfg.get("threshold_1m_pct", os.getenv("VOL_ALERT_MAJOR_1M_PCT", "5.0")))
        self._major_threshold_5m = float(major_cfg.get("threshold_5m_pct", os.getenv("VOL_ALERT_MAJOR_5M_PCT", "8.0")))
        self._major_cooldown = float(major_cfg.get("cooldown_minutes", os.getenv("VOL_ALERT_MAJOR_COOLDOWN_MINUTES", "30"))) * 60
        self._major_symbols = {
            s.strip().upper()
            for s in major_cfg.get("symbols", os.getenv("VOL_ALERT_MAJOR_SYMBOLS", "ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,ADAUSDT"))
            if isinstance(s, str) and s.strip()
        }

        watch_cfg = vol_cfg.get("watchlist", {})
        self._watch_threshold_1m = float(watch_cfg.get("threshold_1m_pct", os.getenv("VOL_ALERT_WATCHLIST_1M_PCT", "6.0")))
        self._watch_threshold_5m = float(watch_cfg.get("threshold_5m_pct", os.getenv("VOL_ALERT_WATCHLIST_5M_PCT", "10.0")))
        self._watch_cooldown = float(watch_cfg.get("cooldown_minutes", os.getenv("VOL_ALERT_WATCHLIST_COOLDOWN_MINUTES", "25"))) * 60
        self._watchlist_symbols = {
            s.strip().upper()
            for s in watch_cfg.get("symbols", os.getenv("VOL_ALERT_WATCHLIST_SYMBOLS", ""))
            if isinstance(s, str) and s.strip()
        }

        coin_cfg = vol_cfg.get("coin", {})
        self._coin_threshold_1m = float(coin_cfg.get("threshold_1m_pct", os.getenv("VOL_ALERT_COIN_1M_PCT", "10.0")))
        self._coin_threshold_5m = float(coin_cfg.get("threshold_5m_pct", os.getenv("VOL_ALERT_COIN_5M_PCT", "15.0")))
        self._coin_cooldown = float(coin_cfg.get("cooldown_minutes", os.getenv("VOL_ALERT_COIN_COOLDOWN_MINUTES", "40"))) * 60

        self._unusual_ratio = float(vol_cfg.get("unusual_ratio", os.getenv("VOL_ALERT_UNUSUAL_RATIO", "3.0")))
        self._exclude_tokens = vol_cfg.get("exclude_tokens", ["UP", "DOWN", "BULL", "BEAR", "SHORT", "LONG"])
        self._priority_symbols = [
            s.strip().upper()
            for s in vol_cfg.get("priority_symbols", os.getenv("VOL_ALERT_PRIORITY_SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT"))
            if isinstance(s, str) and s.strip()
        ]

    def callback(self, price_map: dict):
        if not self._enabled:
            return

        now = time.time()
        if now - self._last_cycle < self._cycle_delay:
            return

        self._last_cycle = now
        start_daemon_job("volatility_alert", self._run_cycle, price_map, now)

    def _run_cycle(self, price_map: dict, now: float):
        alerts = []
        symbols_checked = 0

        for symbol, price in self._iter_symbols(price_map):
            if symbols_checked >= self._symbols_limit:
                break
            if not self._is_valid_symbol(symbol):
                continue
            if price is None or price <= 0:
                continue

            state = self._states.setdefault(symbol, _SymbolState())
            state.record_price(float(price), now)
            symbols_checked += 1

            alert = self._evaluate_symbol(symbol, state, now)
            if alert:
                alerts.append(alert)

        if not alerts:
            return

        alerts.sort(key=lambda x: (x["priority"], -x["magnitude"]))
        selected = alerts[:6]
        self._persist_alerts(selected)
        self._emit_message(selected)

    def _iter_symbols(self, price_map: dict):
        seen = set()
        for symbol in self._priority_symbols:
            if symbol in price_map:
                seen.add(symbol)
                yield symbol, price_map.get(symbol)
        for symbol, price in price_map.items():
            if symbol in seen:
                continue
            yield symbol, price

    def _is_valid_symbol(self, symbol: str) -> bool:
        if not symbol.endswith("USDT"):
            return False
        if any(token in symbol for token in self._exclude_tokens):
            return False
        if symbol == "USDT":
            return False
        return True

    def _evaluate_symbol(self, symbol: str, state: _SymbolState, now: float) -> Optional[dict]:
        if state.last_price is None:
            return None

        price_1m = state.price_at(60.0, now)
        price_5m = state.price_at(300.0, now)
        if not price_1m and not price_5m:
            return None

        current = state.last_price
        delta_1m = ((current - price_1m[0]) / price_1m[0] * 100) if price_1m else 0.0
        delta_5m = ((current - price_5m[0]) / price_5m[0] * 100) if price_5m else 0.0
        abs_1m = abs(delta_1m)
        abs_5m = abs(delta_5m)

        group, threshold_1m, threshold_5m, cooldown = self._thresholds_for(symbol)
        age_since_alert = now - state.last_alert_at

        if age_since_alert < cooldown:
            return None

        avg_move = state.avg_short_move(now)
        unusual_move = bool(avg_move and abs_1m >= max(1.2, avg_move * self._unusual_ratio) and abs_1m >= 5.0)

        trigger_tf = None
        alert_type = None
        if group == "btc" and abs_1m >= threshold_1m:
            trigger_tf = "1m"
            alert_type = "BTC 1m"
        elif group == "btc" and abs_5m >= threshold_5m:
            trigger_tf = "5m"
            alert_type = "BTC 5m"
        elif group != "btc" and abs_1m >= threshold_1m:
            trigger_tf = "1m"
            alert_type = "Short-term spike"
        elif group != "btc" and abs_5m >= threshold_5m:
            trigger_tf = "5m"
            alert_type = "Large move"
        elif unusual_move:
            trigger_tf = "1m"
            alert_type = "Early abnormal move"

        if not alert_type:
            return None

        trigger_delta = delta_1m if trigger_tf == "1m" else delta_5m
        direction = "UP" if trigger_delta > 0 else "DOWN"
        level = f"{direction}:{alert_type}"
        if state.last_alert_key == level and age_since_alert < cooldown * 2:
            return None

        state.last_alert_at = now
        state.last_alert_key = level

        return {
            "symbol": symbol,
            "direction": direction,
            "delta_1m": abs_1m,
            "delta_5m": abs_5m,
            "signed_delta_1m": delta_1m,
            "signed_delta_5m": delta_5m,
            "reason": alert_type,
            "trigger_tf": trigger_tf,
            "group": group,
            "magnitude": max(abs_1m, abs_5m),
            "priority": {"btc": 0, "watchlist": 1, "major": 2}.get(group, 3),
            "ts": now,
        }

    def _thresholds_for(self, symbol: str):
        if symbol == "BTCUSDT":
            return "btc", self._btc_threshold_1m, self._btc_threshold_5m, self._btc_cooldown
        if symbol in self._watchlist_symbols:
            return "watchlist", self._watch_threshold_1m, self._watch_threshold_5m, self._watch_cooldown
        if symbol in self._major_symbols:
            return "major", self._major_threshold_1m, self._major_threshold_5m, self._major_cooldown
        return "alt", self._coin_threshold_1m, self._coin_threshold_5m, self._coin_cooldown

    def _emit_message(self, alerts: List[dict]):
        lines = ["🌊 <b>Cảnh báo biến động giá</b>"]
        lines.append("Phát hiện biến động realtime. Hệ thống chỉ cảnh báo sớm, không thay đổi rule vào lệnh.")

        for alert in alerts:
            direction = "TĂNG" if alert["direction"] == "UP" else "GIẢM"
            icon = "🟢" if alert["direction"] == "UP" else "🔴"
            self._recent_alerts.appendleft(dict(alert))
            lines.append(
                f"{icon} <b>{alert['symbol']}</b> {direction}: {alert['reason']} "
                f"| 1m {alert['signed_delta_1m']:+.2f}% "
                f"| 5m {alert['signed_delta_5m']:+.2f}%"
            )

        lines.append("\n👀 Dùng như tín hiệu theo dõi sớm; không phải lệnh giao dịch.")
        send_telegram("\n".join(lines))

    def get_recent_alerts(self, limit: int = 10) -> List[dict]:
        limit = max(0, int(limit))
        memory = list(self._recent_alerts)[:limit]
        if len(memory) >= limit:
            return memory

        rows = get_recent_persisted_alerts(limit=limit - len(memory))
        return memory + rows

    def _persist_alerts(self, alerts: List[dict]):
        if not alerts:
            return
        try:
            self._ensure_table()
            from sqlalchemy import text
            from app.db.session import SessionLocal

            with SessionLocal() as db:
                for alert in alerts:
                    db.execute(text("""
                        INSERT INTO market_alert_events (
                            symbol, alert_group, direction, reason, trigger_tf,
                            delta_1m, delta_5m, magnitude, event_ts, raw
                        )
                        VALUES (
                            :symbol, :alert_group, :direction, :reason, :trigger_tf,
                            :delta_1m, :delta_5m, :magnitude, to_timestamp(:event_ts), CAST(:raw AS jsonb)
                        )
                    """), {
                        "symbol": alert.get("symbol"),
                        "alert_group": alert.get("group"),
                        "direction": alert.get("direction"),
                        "reason": alert.get("reason"),
                        "trigger_tf": alert.get("trigger_tf"),
                        "delta_1m": alert.get("signed_delta_1m"),
                        "delta_5m": alert.get("signed_delta_5m"),
                        "magnitude": alert.get("magnitude"),
                        "event_ts": alert.get("ts") or time.time(),
                        "raw": json.dumps(alert, default=str),
                    })
                db.commit()
        except Exception as e:
            print(f"[VOL ALERT] persist error: {type(e).__name__}: {e}")

    def _ensure_table(self):
        if self._table_ready:
            return
        from sqlalchemy import text
        from app.db.session import engine

        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS market_alert_events (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    alert_group TEXT,
                    direction TEXT,
                    reason TEXT,
                    trigger_tf TEXT,
                    delta_1m DOUBLE PRECISION,
                    delta_5m DOUBLE PRECISION,
                    magnitude DOUBLE PRECISION,
                    event_ts TIMESTAMPTZ,
                    raw JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_market_alert_events_created
                ON market_alert_events (created_at DESC)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_market_alert_events_symbol_created
                ON market_alert_events (symbol, created_at DESC)
            """))
        self._table_ready = True


_service: Optional[VolatilityAlertService] = None


def get_volatility_alert_service() -> VolatilityAlertService:
    global _service
    if _service is None:
        _service = VolatilityAlertService()
    return _service


def register_volatility_alerts():
    from app.services.price_feed import add_price_callback

    add_price_callback(get_volatility_alert_service().callback)


def get_recent_volatility_alerts(limit: int = 10) -> List[dict]:
    return get_volatility_alert_service().get_recent_alerts(limit)


def ensure_market_alert_table():
    get_volatility_alert_service()._ensure_table()


def get_recent_persisted_alerts(limit: int = 10, hours: int = 24) -> List[dict]:
    try:
        ensure_market_alert_table()
        from sqlalchemy import text
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            rows = db.execute(text("""
                SELECT symbol, alert_group, direction, reason, trigger_tf,
                       delta_1m, delta_5m, magnitude, event_ts, created_at
                FROM market_alert_events
                WHERE created_at >= NOW() - (:hours || ' hours')::interval
                ORDER BY created_at DESC
                LIMIT :limit
            """), {"hours": int(hours), "limit": int(limit)}).mappings().all()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[VOL ALERT] recent query error: {type(e).__name__}: {e}")
        return []
