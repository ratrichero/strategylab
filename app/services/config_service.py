import json
from app.db.session import SessionLocal
from sqlalchemy import text
from app.core.time_utils import utc_now

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
    "OPEN_TRADE_FILTER": json.dumps({"enabled": False}),
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
    }
    return _runtime_cache


def update_runtime_config(data: dict):
    global _runtime_cache
    db = SessionLocal()
    for k, v in data.items():
        if k in ["RISK_CONFIG","DERIVATIVE_CONFIG","PENDING_CONFIG",
                 "OPEN_TRADE_FILTER","PREFILL_CONFIG","STRATEGY_THRESHOLDS",
                 "LIMIT_ORDER_CONFIG"]:
            try: json.loads(v)
            except: db.close(); raise ValueError(f"{k} is invalid JSON")
        db.execute(text("""
            INSERT INTO app_config (key, value, updated_at)
            VALUES (:k, :v, NOW())
            ON CONFLICT (key) DO UPDATE SET value = :v, updated_at = utc_now()
        """), {"k": k, "v": str(v)})
    db.commit(); db.close()
    _runtime_cache = None
