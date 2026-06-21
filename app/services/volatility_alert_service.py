import os
import time
from collections import deque
from statistics import mean
from typing import Deque, Dict, List, Optional, Tuple

from app.core.bg_runner import start_daemon_job
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
        # Khoảng thời gian giữa các lần duyệt cảnh báo để không chạy quá tải price feed.
        self._cycle_delay = float(os.getenv("VOL_ALERT_CYCLE_SECONDS", "3"))
        # Giới hạn số symbol được xử lý mỗi lần để giữ hiệu năng.
        self._symbols_limit = int(os.getenv("VOL_ALERT_SYMBOL_LIMIT", "1200"))
        # Ngưỡng cảnh báo cho BTC.
        self._btc_threshold_1m = float(os.getenv("VOL_ALERT_BTC_1M_PCT", "2.0"))
        self._btc_threshold_5m = float(os.getenv("VOL_ALERT_BTC_5M_PCT", "3.5"))
        # Thời gian chờ giữa 2 cảnh báo BTC cùng loại, tránh spam.
        self._btc_cooldown = float(os.getenv("VOL_ALERT_BTC_COOLDOWN_MINUTES", "20")) * 60
        # Coin khác: 1 phút > 10%, 5 phút > 15% mới cảnh báo.
        self._coin_threshold_1m = float(os.getenv("VOL_ALERT_COIN_1M_PCT", "10.0"))
        self._coin_threshold_5m = float(os.getenv("VOL_ALERT_COIN_5M_PCT", "15.0"))
        # Thời gian chờ giữa 2 cảnh báo cùng symbol coin khác.
        self._coin_cooldown = float(os.getenv("VOL_ALERT_COIN_COOLDOWN_MINUTES", "40")) * 60
        # Ngưỡng phát hiện sớm: biến động 1m lớn bất thường so với trung bình và tối thiểu 5%.
        self._unusual_ratio = float(os.getenv("VOL_ALERT_UNUSUAL_RATIO", "3.0"))
        # Bật/tắt toàn bộ cơ chế cảnh báo.
        self._enabled = os.getenv("ENABLE_VOL_ALERTS", "true").lower() in ["1", "true", "yes", "on"]
        # Loại trừ các symbol dạng token đòn bẩy, hướng tăng giảm, vì chỉ cần USDT spot.
        self._exclude_tokens = ["UP", "DOWN", "BULL", "BEAR", "SHORT", "LONG"]

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

        for symbol, price in price_map.items():
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
        alerts = alerts[:6]
        self._emit_message(alerts)

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
        direction = "UP" if (price_1m and current > price_1m[0]) or (price_5m and current > price_5m[0]) else "DOWN"
        delta_1m = ((current - price_1m[0]) / price_1m[0] * 100) if price_1m else 0.0
        delta_5m = ((current - price_5m[0]) / price_5m[0] * 100) if price_5m else 0.0
        abs_1m = abs(delta_1m)
        abs_5m = abs(delta_5m)

        btc = symbol == "BTCUSDT"
        threshold_1m = self._btc_threshold_1m if btc else self._coin_threshold_1m
        threshold_5m = self._btc_threshold_5m if btc else self._coin_threshold_5m
        cooldown = self._btc_cooldown if btc else self._coin_cooldown
        age_since_alert = now - state.last_alert_at

        # Chỉ gửi cảnh báo với mỗi symbol sau khi cooldown hết hạn.
        if age_since_alert < cooldown:
            return None

        # Tính biến động ngắn hạn, dùng để phát hiện cú tăng/giảm bất thường sớm.
        avg_move = state.avg_short_move(now)
        unusual_move = avg_move and abs_1m >= max(1.2, avg_move * self._unusual_ratio) and abs_1m >= 5.0

        alert_type = None
        if btc and abs_1m >= threshold_1m:
            alert_type = "BTC 1m"
        elif btc and abs_5m >= threshold_5m:
            alert_type = "BTC 5m"
        elif not btc and abs_1m >= threshold_1m:
            alert_type = "Lướt ngắn"
        elif not btc and abs_5m >= threshold_5m:
            alert_type = "Tăng/giảm lớn"
        elif unusual_move:
            alert_type = "Bất thường sớm"

        if not alert_type:
            return None

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
            "reason": alert_type,
            "magnitude": max(abs_1m, abs_5m),
            "priority": 0 if btc else 1,
        }

    def _emit_message(self, alerts: List[dict]):
        lines = ["<b>⚠️ Volatility Alert</b>"]
        lines.append("Giảm/ tăng bất thường theo giá realtime. Chỉ gửi khi thay đổi đủ lớn.")

        for alert in alerts:
            symbol = alert["symbol"]
            sign = "🔺" if alert["direction"] == "UP" else "🔻"
            lines.append(
                f"{sign} <b>{symbol}</b>: {alert['reason']} | 1m {alert['delta_1m']:.2f}% | 5m {alert['delta_5m']:.2f}%"
            )

        lines.append("\nKích hoạt cảnh báo sớm cho BTC và coin biến động bất thường.")
        send_telegram("\n".join(lines))


_service = VolatilityAlertService()


def register_volatility_alerts():
    from app.services.price_feed import add_price_callback

    add_price_callback(_service.callback)
