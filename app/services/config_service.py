import json
from app.db.session import SessionLocal
from sqlalchemy import text
from app.core.time_utils import utc_now
import os as _os

DEFAULTS = {
    "TIMEFRAME": "15m", "SCORE_THRESHOLD": "5",
    "BODY_RATIO_THRESHOLD": "0.35", "VOLUME_MULTIPLIER": "1.15",
    "ATR_RATIO_MIN": "0.0015", "COOLDOWN_HOURS": "4",
    "MTF_ENABLED": "true", "AI_THRESHOLD": "0.0",
    "TOP_LIMIT": "400", "ENABLE_SCHEDULER": "true",
    "ENABLE_MONITOR": "true", "ENGINE_VERSION": "5.0",
    "ACTIVE_STRATEGIES": "candlestick",
    "MAX_OPEN_TRADES": "10",
    "TRADING_MODE": "PAPER",
    "RISK_CONFIG": json.dumps({
        "15m": {"sl_mult": 0.02, "tp_mult": 0.04},
        "1h":  {"sl_mult": 0.025,"tp_mult": 0.05},
        "4h":  {"sl_mult": 0.03, "tp_mult": 0.06}
    }),
    "DERIVATIVE_CONFIG": json.dumps({
        "pre_buffer": 1, "bias_scale": {"15m": 0.6, "1h": 0.8, "4h": 1.0}
    }),
    "PENDING_CONFIG": json.dumps({
        "enabled": True,
        "atr_entry_multiplier": {"15m": 0.4, "1h": 0.5, "4h": 0.6},
        "expire_hours": {"15m": 0.5, "1h": 2, "4h": 8}
    }),
    "OPEN_TRADE_FILTER": json.dumps({"enabled": True}),
    "PREFILL_CONFIG": json.dumps({"enabled": True}),
    "STRATEGY_THRESHOLDS": json.dumps({
        "candlestick": 5.0, "breakout": 6.0,
        "mean_reversion": 5.5, "pullback": 5.5, "trend_following": 5.5
    }),
    "LIMIT_ORDER_CONFIG": json.dumps({
        "enabled": True,
        "entry_reprice_pct": {
            "15m": 0.01,
            "1h": 0.008,
            "4h": 0.005
        }
    }),
    "POSITION_SIZE_CONFIG": json.dumps({
        "mode": "fixed_usdt",
        "fixed_usdt_per_trade": 200,
        "risk_per_trade_pct": 0.01,
        "default_leverage": 3,
        "max_position_usdt": 500,
    }),
    "PROFIT_LOCK_CONFIG": json.dumps({
    "enabled": False,
    "threshold_pct": 20,
    "min_open_trades": 3,
    "cooldown_minutes": 60
    }),
    "PROTECTION_LEVELS_CONFIG": json.dumps({
        "enabled": True,
        "timeframes": {
            "15m": {"levels": [
                {"trigger_pct": 0.02, "action": "move_to_entry", "buffer_pct": 0.002},
                {"trigger_pct": 0.04, "action": "move_stop_to_profit_pct", "target_profit_pct": 0.015}
            ]},
            "1h": {"levels": [
                {"trigger_pct": 0.025, "action": "move_to_entry", "buffer_pct": 0.0025}
            ]},
            "4h": {"levels": [
                {"trigger_pct": 0.03, "action": "move_to_entry", "buffer_pct": 0.003}
            ]}
        }
    }),
    "RETRY_POLICY_CONFIG": json.dumps({
        "enabled": True,
        "error_classification": {
            "deterministic": [
                "insufficient balance",
                "margin is insufficient",
                "leverage failed",
                "qty too small",
                "actual notional too small",
                "order would immediately trigger",
                "price is outside the price band",
                "apikey permission",
                "symbol not trading",
                "set_leverage_failed",
            ],
            "temporary": [
                "timeout",
                "network",
                "connection",
                "connection reset",
                "connection refused",
            ],
            "rate_limit": [
                "too many requests",
                "rate limit",
                "429",
            ]
        },
        "retry_strategies": {
            "duplicate_guard": {
                "max_retries": 0,
                "backoff": "none"
            },
            "deterministic": {
                "max_retries": 0,
                "backoff": "none"
            },
            "temporary": {
                "max_retries": 5,
                "backoff": "exponential",
                "initial": 10,
                "max": 300
            },
            "rate_limit": {
                "max_retries": 3,
                "backoff": "fixed",
                "seconds": 60
            }
        },
        "circuit_breaker": {
            "enabled": True,
            "failure_threshold": 5,
            "cooldown_seconds": 300
        }
    }),
    "CONNECTION_OVERRIDE": "false",
    "STRATEGY_CONFIG": json.dumps({
        "candlestick": {
            "threshold": 7.5,
            "patterns": {
                "Bullish Engulfing": 8.0,
                "Hammer": 8.5,
                "Bearish Engulfing": 99.0,
                "Morning Star": 8.0,
                "Evening Star": 8.5,
                "Bullish Marubozu": 7.5,
                "Bearish Marubozu": 99.0
            }
        },
        "pullback": {
            "threshold": 8.0,
            "patterns": {
                "Bullish Pullback": 8.0,
                "Bearish Pullback": 8.2
            }
        },
        "breakout": {
            "threshold": 8.0,
            "patterns": {
                "Bullish Breakout": 8.0,
                "Bearish Breakout": 8.2
            }
        },
        "mean_reversion": {
            "threshold": 99.0,
            "patterns": {
                "Mean Reversion": 99.0
            }
        },
        "trend_following": {
            "threshold": 8.0
        }
    }),
}

_runtime_cache = None


def get_runtime_config(force_reload=False):
    global _runtime_cache
    if _runtime_cache and not force_reload:
        return _runtime_cache
    db = SessionLocal()
    rows = db.execute(text("SELECT key, value FROM app_config")).fetchall()
    db.close()
    config = {k: v for k, v in rows}

    def parse_json(key):
        raw = config.get(key, DEFAULTS[key])
        try: return json.loads(raw)
        except: return json.loads(DEFAULTS[key])

    _runtime_cache = {
        "TIMEFRAME":             config.get("TIMEFRAME",             DEFAULTS["TIMEFRAME"]),
        "SCORE_THRESHOLD":       float(config.get("SCORE_THRESHOLD", DEFAULTS["SCORE_THRESHOLD"])),
        "BODY_RATIO_THRESHOLD":  float(config.get("BODY_RATIO_THRESHOLD", DEFAULTS["BODY_RATIO_THRESHOLD"])),
        "VOLUME_MULTIPLIER":     float(config.get("VOLUME_MULTIPLIER",    DEFAULTS["VOLUME_MULTIPLIER"])),
        "ATR_RATIO_MIN":         float(config.get("ATR_RATIO_MIN",        DEFAULTS["ATR_RATIO_MIN"])),
        "COOLDOWN_HOURS":        int(config.get("COOLDOWN_HOURS",         DEFAULTS["COOLDOWN_HOURS"])),
        "AI_THRESHOLD":          float(config.get("AI_THRESHOLD",         DEFAULTS["AI_THRESHOLD"])),
        "TOP_LIMIT":             int(config.get("TOP_LIMIT",              DEFAULTS["TOP_LIMIT"])),
        "MTF_ENABLED":           config.get("MTF_ENABLED", "true").lower() == "true",
        "ENABLE_SCHEDULER":      config.get("ENABLE_SCHEDULER", "true").lower() == "true",
        "ENABLE_MONITOR":        config.get("ENABLE_MONITOR",  "true").lower() == "true",
        "ENGINE_VERSION":        float(config.get("ENGINE_VERSION",       DEFAULTS["ENGINE_VERSION"])),
        "ACTIVE_STRATEGIES":     config.get("ACTIVE_STRATEGIES",          DEFAULTS["ACTIVE_STRATEGIES"]),
        "TRADING_MODE":          config.get("TRADING_MODE",               DEFAULTS["TRADING_MODE"]),
        "RISK_CONFIG":           parse_json("RISK_CONFIG"),
        "DERIVATIVE_CONFIG":     parse_json("DERIVATIVE_CONFIG"),
        "PENDING_CONFIG":        parse_json("PENDING_CONFIG"),
        "OPEN_TRADE_FILTER":     parse_json("OPEN_TRADE_FILTER"),
        "PREFILL_CONFIG":        parse_json("PREFILL_CONFIG"),
        "STRATEGY_THRESHOLDS":   parse_json("STRATEGY_THRESHOLDS"),
        "MAX_OPEN_TRADES":       int(config.get("MAX_OPEN_TRADES", DEFAULTS["MAX_OPEN_TRADES"])),
        "LIMIT_ORDER_CONFIG":    parse_json("LIMIT_ORDER_CONFIG"),
        "POSITION_SIZE_CONFIG":  parse_json("POSITION_SIZE_CONFIG"),
        "CONNECTION_OVERRIDE":   config.get("CONNECTION_OVERRIDE", DEFAULTS["CONNECTION_OVERRIDE"]),
        "STRATEGY_CONFIG":       parse_json("STRATEGY_CONFIG"),
        "PROFIT_LOCK_CONFIG":       parse_json("PROFIT_LOCK_CONFIG"),
        "PROTECTION_LEVELS_CONFIG": parse_json("PROTECTION_LEVELS_CONFIG"),
        "RETRY_POLICY_CONFIG":     parse_json("RETRY_POLICY_CONFIG"),
        
    }
    return _runtime_cache


def update_runtime_config(data: dict):
    global _runtime_cache
    db = SessionLocal()
    for k, v in data.items():
        if k in ["RISK_CONFIG","DERIVATIVE_CONFIG","PENDING_CONFIG",
                 "OPEN_TRADE_FILTER","PREFILL_CONFIG","STRATEGY_THRESHOLDS",
                 "LIMIT_ORDER_CONFIG","POSITION_SIZE_CONFIG","STRATEGY_CONFIG","PROFIT_LOCK_CONFIG","PROTECTION_LEVELS_CONFIG","RETRY_POLICY_CONFIG"]:
            try: json.loads(v)
            except: db.close(); raise ValueError(f"{k} is invalid JSON")
        db.execute(text("""
            INSERT INTO app_config (key, value, updated_at)
            VALUES (:k, :v, NOW())
            ON CONFLICT (key) DO UPDATE SET value = :v, updated_at = NOW()
        """), {"k": k, "v": str(v)})
    db.commit(); db.close()
    _runtime_cache = None



CONNECTION_KEYS = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_TESTNET_API_KEY",
    "BINANCE_TESTNET_API_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
]


def get_app_config_value(key: str, default: str = "") -> str:
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT value FROM app_config WHERE key = :k"),
            {"k": key}
        ).fetchone()
        return row[0] if row and row[0] is not None else default
    finally:
        db.close()


def is_connection_override_enabled() -> bool:
    raw = get_app_config_value(
        "CONNECTION_OVERRIDE",
        _os.getenv("CONNECTION_OVERRIDE", "false")
    )
    return str(raw).strip().lower() == "true"


def get_connection_value(key: str, default: str = "") -> str:
    if key == "DATABASE_URL":
        return _os.environ.get("DATABASE_URL", default)

    if is_connection_override_enabled():
        val = get_app_config_value(key, "")
        if val:
            return val

    return _os.environ.get(key, default)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]