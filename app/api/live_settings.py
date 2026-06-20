"""
Live Settings API
==================
API cho FE Settings page:
- Profit Lock config
- Protection Levels config (percent-based, per timeframe)
- Risk Config (SL/TP %, per timeframe)
"""

import json
from fastapi import APIRouter
from app.services.config_service import get_runtime_config, update_runtime_config

router = APIRouter(prefix="/api/live-settings", tags=["live-settings"])


# ── Profit Lock ──────────────────────────────────────────────

@router.get("/profit-lock")
def get_profit_lock_config():
    """
    Returns:
    {
        "enabled": bool,
        "threshold_pct": float,   # tổng PnL % thực tế (không tính leverage)
        "min_open_trades": int,
        "cooldown_minutes": int
    }
    """
    cfg = get_runtime_config(force_reload=True)
    return cfg.get("PROFIT_LOCK_CONFIG", {})


@router.put("/profit-lock")
def set_profit_lock_config(body: dict):
    """
    Body:
    {
        "enabled": bool,
        "threshold_pct": float,
        "min_open_trades": int,
        "cooldown_minutes": int
    }
    """
    update_runtime_config({
        "PROFIT_LOCK_CONFIG": json.dumps(body)
    })
    return {"success": True, "config": body}


# ── Protection Levels ────────────────────────────────────────

@router.get("/protection-levels")
def get_protection_levels_config():
    """
    Returns:
    {
        "enabled": bool,
        "timeframes": {
            "15m": {
                "levels": [
                    {
                        "trigger_pct": float,
                        "action": "move_to_entry" | "move_stop_to_profit_pct",
                        "buffer_pct": float,          // only if action=move_to_entry
                        "target_profit_pct": float     // only if action=move_stop_to_profit_pct
                    }
                ]
            },
            "1h": { "levels": [...] },
            "4h": { "levels": [...] }
        }
    }
    """
    cfg = get_runtime_config(force_reload=True)
    return cfg.get("PROTECTION_LEVELS_CONFIG", {})


@router.put("/protection-levels")
def set_protection_levels_config(body: dict):
    """
    Body: same structure as GET response
    """
    update_runtime_config({
        "PROTECTION_LEVELS_CONFIG": json.dumps(body)
    })
    return {"success": True, "config": body}


# ── Risk Config (SL/TP %) ───────────────────────────────────

@router.get("/risk-config")
def get_risk_config():
    """
    Returns:
    {
        "15m": { "sl_pct": 0.02, "tp_pct": 0.04 },
        "1h":  { "sl_pct": 0.025, "tp_pct": 0.05 },
        "4h":  { "sl_pct": 0.03, "tp_pct": 0.06 }
    }

    NOTE: internal DB key RISK_CONFIG dùng sl_mult/tp_mult.
    API này convert sang sl_pct/tp_pct cho FE dễ hiểu.
    """
    cfg = get_runtime_config(force_reload=True)
    raw = cfg.get("RISK_CONFIG", {})

    result = {}
    for tf, vals in raw.items():
        result[tf] = {
            "sl_pct": float(vals.get("sl_mult", 0)),
            "tp_pct": float(vals.get("tp_mult", 0)),
        }
    return result


@router.put("/risk-config")
def set_risk_config(body: dict):
    """
    Body:
    {
        "15m": { "sl_pct": 0.03, "tp_pct": 0.05 },
        "1h":  { "sl_pct": 0.025, "tp_pct": 0.05 },
        "4h":  { "sl_pct": 0.03, "tp_pct": 0.06 }
    }

    API convert sl_pct/tp_pct -> sl_mult/tp_mult cho backward compat.
    """
    internal = {}
    for tf, vals in body.items():
        internal[tf] = {
            "sl_mult": float(vals.get("sl_pct", 0)),
            "tp_mult": float(vals.get("tp_pct", 0)),
        }
    update_runtime_config({
        "RISK_CONFIG": json.dumps(internal)
    })
    return {"success": True, "config": body}