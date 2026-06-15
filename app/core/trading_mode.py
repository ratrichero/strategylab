"""Trading Mode Manager — PAPER / TESTNET / LIVE"""
import os
from enum import Enum
from typing import Optional, Dict


class TradingMode(str, Enum):
    PAPER   = "PAPER"
    TESTNET = "TESTNET"
    LIVE    = "LIVE"


class ConflictRule:
    @staticmethod
    def get_pending_block_condition(symbol, strategy_name, timeframe, mode):
        if mode != TradingMode.PAPER:
            return {"symbol": symbol, "status": "WAIT"}
        return {
            "symbol": symbol,
            "strategy_name": strategy_name,
            "timeframe": timeframe,
            "status": "WAIT"
        }

    @staticmethod
    def get_open_signal_block_condition(symbol, strategy_name, timeframe, mode):
        if mode != TradingMode.PAPER:
            return {"symbol": symbol, "status": "OPEN"}
        return {
            "symbol": symbol,
            "strategy_name": strategy_name,
            "timeframe": timeframe,
            "status": "OPEN"}


class TradingModeManager:
    _cache_ttl    = 30
    _cached_mode: Optional[TradingMode] = None
    _cached_at:   float = 0

    def get_mode(self) -> TradingMode:
        import time
        if self._cached_mode and time.time() - self._cached_at < self._cache_ttl:
            return self._cached_mode
        return self._load_from_db()

    def _load_from_db(self) -> TradingMode:
        import time
        try:
            from app.db.session import SessionLocal
            from sqlalchemy import text
            with SessionLocal() as db:
                row = db.execute(
                    text("SELECT value FROM app_config WHERE key = 'TRADING_MODE'")
                ).fetchone()
            raw = row[0] if row else "PAPER"
            mode = TradingMode(raw.upper())
        except Exception:
            raw = os.getenv("TRADING_MODE", "PAPER").upper()
            try:
                mode = TradingMode(raw)
            except ValueError:
                mode = TradingMode.PAPER
        self._cached_mode = mode
        self._cached_at   = time.time()
        return mode

    def invalidate_cache(self):
        self._cached_mode = None
        self._cached_at   = 0

    @property
    def is_paper(self): return self.get_mode() == TradingMode.PAPER
    @property
    def is_live(self):  return self.get_mode() == TradingMode.LIVE
    @property
    def is_testnet(self): return self.get_mode() == TradingMode.TESTNET
    @property
    def is_real_money(self): return self.get_mode() == TradingMode.LIVE

    def get_conflict_rule(self): return ConflictRule()

    def get_binance_config(self) -> Dict:
        from app.services.config_service import get_connection_value

        mode = self.get_mode()

        if mode == TradingMode.LIVE:
            return {
                "api_key":    get_connection_value("BINANCE_API_KEY"),
                "api_secret": get_connection_value("BINANCE_API_SECRET"),
                "base_url":   "https://fapi.binance.com",
                "testnet":    False,
            }
        elif mode == TradingMode.TESTNET:
            return {
                "api_key":    get_connection_value("BINANCE_TESTNET_API_KEY"),
                "api_secret": get_connection_value("BINANCE_TESTNET_API_SECRET"),
                "base_url":   "https://testnet.binancefuture.com",
                "testnet":    True,
            }

        return {
            "api_key": None,
            "api_secret": None,
            "base_url": None,
            "testnet": False,
        }

    def describe(self) -> Dict:
        mode = self.get_mode()
        return {
            "mode": mode.value,
            "is_real_money": self.is_real_money,
            "description": {
                TradingMode.PAPER:   "Paper trading — no real orders",
                TradingMode.TESTNET: "Testnet — real orders fake money",
                TradingMode.LIVE:    "⚠️ LIVE — real money!",
            }.get(mode, "Unknown")
        }


_trading_mode_manager = TradingModeManager()

def get_trading_mode() -> TradingModeManager: return _trading_mode_manager
def get_current_mode() -> TradingMode: return _trading_mode_manager.get_mode()
def is_paper_mode() -> bool: return _trading_mode_manager.is_paper
def is_live_mode()  -> bool: return _trading_mode_manager.is_live
