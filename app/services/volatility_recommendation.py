from typing import Dict, List, Tuple


_ACTION_THRESHOLDS = {
    "LONG_BREAKOUT": 6.0,
    "LONG_PULLBACK": 5.5,
    "LONG_EARLY_MOMENTUM": 5.5,
    "SHORT_BREAKDOWN": 6.0,
    "SHORT_REBOUND": 5.5,
    "SHORT_EARLY_WEAKNESS": 5.5,
    "AVOID_FOMO": 5.0,
}


def _safe_float(value): # Bỏ tham số default=None để trả về None chuẩn
    try:
        if value is None: return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _add_score(scores: dict, reasons: dict, action: str, points: float, reason: str):
    scores[action] = scores.get(action, 0.0) + float(points)
    reasons.setdefault(action, []).append(reason)


def _downgrade_confidence(confidence: str) -> str:
    order = ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"]
    if confidence not in order:
        return "LOW"
    idx = order.index(confidence)
    if idx <= 0:
        return "LOW"
    return order[idx - 1]


def _score_to_confidence(score: float) -> str:
    if score >= 9.0:
        return "VERY_HIGH"
    if score >= 7.0:
        return "HIGH"
    if score >= 5.5:
        return "MEDIUM"
    return "LOW"


def _event_is_large(alert: dict) -> bool:
    abs_1m = abs(_safe_float(alert.get("signed_delta_1m")) or 0.0)
    abs_5m = abs(_safe_float(alert.get("signed_delta_5m")) or 0.0)
    return abs_1m >= 5.0 or abs_5m >= 10.0


def _fallback_recommendation(alert: dict, reason: str) -> dict:
    action = "AVOID_FOMO" if _event_is_large(alert) else "WATCH_ONLY"
    return {
        "recommendation": action,
        "confidence": "LOW",
        "reason": reason,
        "reason_codes": [reason, "price_only_alert"],
        "scores": {action: 0.0},
        "top_actions": [(action, 0.0)],
        "context_state": reason,
    }


def _support_bonus(direction: str, supportive: dict) -> Tuple[float, List[str]]:
    score = 0.0
    reasons = []

    for tf, row in supportive.items():
        # FIX LỖI 5: Khung supportive quá hạn thì không tính bonus
        if row.get("freshness") in ["missing", "expired"]:
            continue
            
        ema50 = _safe_float(row.get("ema50"))
        ema200 = _safe_float(row.get("ema200"))
        regime = row.get("regime")
        mtf = _safe_float(row.get("mtf_score"))

        if ema50 is not None and ema200 is not None:
            if direction == "LONG" and ema50 > ema200:
                score += 0.4
                reasons.append(f"{tf}_ema_support")
            elif direction == "SHORT" and ema50 < ema200:
                score += 0.4
                reasons.append(f"{tf}_ema_support")

        if direction == "LONG" and regime == "BULL":
            score += 0.3
            reasons.append(f"{tf}_bull_regime")
        elif direction == "SHORT" and regime == "BEAR":
            score += 0.3
            reasons.append(f"{tf}_bear_regime")

        if mtf is not None and mtf >= 0.7:
            score += 0.2
            reasons.append(f"{tf}_mtf_high")

    return score, reasons


def evaluate_volatility_recommendation(alert: dict, context: dict) -> dict:
    primary = context.get("primary")
    context_state = context.get("context_state")

    if primary is None: return _fallback_recommendation(alert, "missing_context")
    if primary.get("freshness") == "expired": return _fallback_recommendation(alert, "stale_context")

    supportive = context.get("supportive") or {}
    event_direction = alert.get("direction")
    
    signed_delta_1m = _safe_float(alert.get("signed_delta_1m")) or 0.0
    signed_delta_5m = _safe_float(alert.get("signed_delta_5m")) or 0.0
    abs_1m = abs(signed_delta_1m)
    abs_5m = abs(signed_delta_5m)

    regime = primary.get("regime")
    ema50 = _safe_float(primary.get("ema50"))
    ema200 = _safe_float(primary.get("ema200"))
    ema200_slope = _safe_float(primary.get("ema200_slope"))
    rsi = _safe_float(primary.get("rsi"))
    rsi_slope = _safe_float(primary.get("rsi_slope"))
    close = _safe_float(primary.get("close"))
    atr = _safe_float(primary.get("atr"))
    atr_percentile = _safe_float(primary.get("atr_percentile"))
    bb_width = _safe_float(primary.get("bb_width"))
    
    # FIX LỖI 3: Để nguyên giá trị None, không ép về 0.0
    vol_ratio = _safe_float(primary.get("vol_ratio"))
    volume_score = _safe_float(primary.get("volume_score"))
    
    # FIX LỖI 2: Direction Mismatch.
    # Nếu Alert nổ chiều UP, nhưng Cache đang là đồ của kèo SHORT, thì bôi đen mtf và derivative_bias
    cache_direction = primary.get("direction")
    if cache_direction and cache_direction != ("LONG" if event_direction == "UP" else "SHORT"):
        mtf_score = None
        derivative_bias = None
    else:
        mtf_score = _safe_float(primary.get("mtf_score"))
        derivative_bias = _safe_float(primary.get("derivative_bias"))

    extension_atr = None
    if close is not None and ema50 is not None and atr is not None and atr > 0:
        extension_atr = abs(close - ema50) / atr

    ema_up = ema50 is not None and ema200 is not None and ema50 > ema200
    ema_down = ema50 is not None and ema200 is not None and ema50 < ema200

    high_volume = (vol_ratio is not None and vol_ratio >= 1.5) or (volume_score is not None and volume_score >= 1.5)
    weak_volume = (vol_ratio is not None and vol_ratio < 1.0) or (volume_score is not None and volume_score <= 0.0)

    scores: Dict[str, float] = {
        "LONG_BREAKOUT": 0.0,
        "LONG_PULLBACK": 0.0,
        "LONG_EARLY_MOMENTUM": 0.0,
        "SHORT_BREAKDOWN": 0.0,
        "SHORT_REBOUND": 0.0,
        "SHORT_EARLY_WEAKNESS": 0.0,
        "AVOID_FOMO": 0.0,
    }
    reasons: Dict[str, List[str]] = {}

    # ── LONG_BREAKOUT ───────────────────────────────────────
    if event_direction == "UP":
        _add_score(scores, reasons, "LONG_BREAKOUT", 1.0, "up_event")
    if regime == "BULL":
        _add_score(scores, reasons, "LONG_BREAKOUT", 2.0, "bull_regime")
    elif regime == "SIDEWAYS":
        _add_score(scores, reasons, "LONG_BREAKOUT", 1.0, "sideways_regime")
    elif regime == "BEAR":
        _add_score(scores, reasons, "LONG_BREAKOUT", -3.0, "bear_regime")

    if ema_up:
        _add_score(scores, reasons, "LONG_BREAKOUT", 1.5, "ema_up")
    if ema200_slope is not None and ema200_slope > 0:
        _add_score(scores, reasons, "LONG_BREAKOUT", 1.0, "ema200_slope_up")
    if mtf_score is not None and mtf_score >= 0.7:
        _add_score(scores, reasons, "LONG_BREAKOUT", 2.0, "mtf_high")
    elif mtf_score is not None and mtf_score >= 0.5:
        _add_score(scores, reasons, "LONG_BREAKOUT", 1.0, "mtf_mid")
    elif mtf_score is not None and mtf_score > 0:
        _add_score(scores, reasons, "LONG_BREAKOUT", -1.5, "mtf_weak")

    if high_volume:
        _add_score(scores, reasons, "LONG_BREAKOUT", 1.5, "volume_confirm")
    elif weak_volume:
        _add_score(scores, reasons, "LONG_BREAKOUT", -1.0, "volume_weak")

    if derivative_bias is not None and derivative_bias > 0:
        _add_score(scores, reasons, "LONG_BREAKOUT", 1.0, "positive_bias")
    elif derivative_bias is not None and derivative_bias < 0:
        _add_score(scores, reasons, "LONG_BREAKOUT", -1.0, "negative_bias")

    if rsi is not None:
        if 50 <= rsi <= 70:
            _add_score(scores, reasons, "LONG_BREAKOUT", 1.0, "rsi_breakout_zone")
        elif rsi > 80:
            _add_score(scores, reasons, "LONG_BREAKOUT", -2.0, "rsi_too_hot")

    if extension_atr is not None and extension_atr > 2.0:
        _add_score(scores, reasons, "LONG_BREAKOUT", -2.0, "too_extended")

    support_score, support_reasons = _support_bonus("LONG", supportive)
    if support_score:
        _add_score(scores, reasons, "LONG_BREAKOUT", support_score, "supportive_context")
        reasons["LONG_BREAKOUT"].extend(support_reasons)

    # ── LONG_PULLBACK ───────────────────────────────────────
    if event_direction == "UP":
        _add_score(scores, reasons, "LONG_PULLBACK", 0.5, "up_event")
    if regime == "BULL":
        _add_score(scores, reasons, "LONG_PULLBACK", 2.0, "bull_regime")
    elif regime == "SIDEWAYS":
        _add_score(scores, reasons, "LONG_PULLBACK", 0.5, "sideways_regime")
    elif regime == "BEAR":
        _add_score(scores, reasons, "LONG_PULLBACK", -3.0, "bear_regime")

    if ema_up:
        _add_score(scores, reasons, "LONG_PULLBACK", 1.5, "ema_up")
    if extension_atr is not None:
        if extension_atr <= 1.5:
            _add_score(scores, reasons, "LONG_PULLBACK", 2.0, "near_ema50")
        elif extension_atr > 2.0:
            _add_score(scores, reasons, "LONG_PULLBACK", -1.0, "far_from_ema50")

    if rsi is not None:
        if 40 <= rsi <= 55:
            _add_score(scores, reasons, "LONG_PULLBACK", 2.0, "rsi_pullback_zone")
        elif rsi < 30:
            _add_score(scores, reasons, "LONG_PULLBACK", -1.0, "rsi_too_weak")

    if mtf_score is not None and mtf_score >= 0.6:
        _add_score(scores, reasons, "LONG_PULLBACK", 1.5, "mtf_support")
    elif mtf_score is not None and mtf_score > 0 and mtf_score < 0.4:
        _add_score(scores, reasons, "LONG_PULLBACK", -1.5, "mtf_weak")

    if rsi_slope is not None and rsi_slope > 0:
        _add_score(scores, reasons, "LONG_PULLBACK", 1.5, "rsi_slope_up")

    if vol_ratio is not None and vol_ratio > 2.0:
        _add_score(scores, reasons, "LONG_PULLBACK", -1.5, "volume_too_hot")

    support_score, support_reasons = _support_bonus("LONG", supportive)
    if support_score:
        _add_score(scores, reasons, "LONG_PULLBACK", support_score, "supportive_context")
        reasons["LONG_PULLBACK"].extend(support_reasons)

    # ── LONG_EARLY_MOMENTUM ────────────────────────────────
    if signed_delta_1m > 0 and abs_5m < abs_1m:
        _add_score(scores, reasons, "LONG_EARLY_MOMENTUM", 2.0, "early_up_momentum")
    if regime is not None and regime != "BEAR":
        _add_score(scores, reasons, "LONG_EARLY_MOMENTUM", 1.5, "not_bear_regime")
    if ema_up:
        _add_score(scores, reasons, "LONG_EARLY_MOMENTUM", 1.0, "ema_up")
    if rsi is not None and 45 <= rsi <= 60:
        _add_score(scores, reasons, "LONG_EARLY_MOMENTUM", 1.5, "rsi_early_zone")
    if rsi_slope is not None and rsi_slope > 0:
        _add_score(scores, reasons, "LONG_EARLY_MOMENTUM", 1.5, "rsi_slope_up")
    if vol_ratio is not None:
        if 1.2 <= vol_ratio <= 2.0:
            _add_score(scores, reasons, "LONG_EARLY_MOMENTUM", 1.5, "volume_balanced")
        elif vol_ratio > 2.5:
            _add_score(scores, reasons, "LONG_EARLY_MOMENTUM", -1.0, "volume_spiky")
    if mtf_score is not None and mtf_score >= 0.5:
        _add_score(scores, reasons, "LONG_EARLY_MOMENTUM", 1.0, "mtf_ok")
    if derivative_bias is not None and derivative_bias >= 0:
        _add_score(scores, reasons, "LONG_EARLY_MOMENTUM", 1.0, "non_negative_bias")

    # ── SHORT_BREAKDOWN ────────────────────────────────────
    if event_direction == "DOWN":
        _add_score(scores, reasons, "SHORT_BREAKDOWN", 1.0, "down_event")
    if regime == "BEAR":
        _add_score(scores, reasons, "SHORT_BREAKDOWN", 2.0, "bear_regime")
    elif regime == "SIDEWAYS":
        _add_score(scores, reasons, "SHORT_BREAKDOWN", 1.0, "sideways_regime")
    elif regime == "BULL":
        _add_score(scores, reasons, "SHORT_BREAKDOWN", -3.0, "bull_regime")

    if ema_down:
        _add_score(scores, reasons, "SHORT_BREAKDOWN", 1.5, "ema_down")
    if mtf_score is not None and mtf_score >= 0.7:
        _add_score(scores, reasons, "SHORT_BREAKDOWN", 2.0, "mtf_high")
    elif mtf_score is not None and mtf_score >= 0.5:
        _add_score(scores, reasons, "SHORT_BREAKDOWN", 1.0, "mtf_mid")
    elif mtf_score is not None and mtf_score > 0:
        _add_score(scores, reasons, "SHORT_BREAKDOWN", -1.5, "mtf_weak")

    if high_volume:
        _add_score(scores, reasons, "SHORT_BREAKDOWN", 1.5, "volume_confirm")

    if derivative_bias is not None and derivative_bias < 0:
        _add_score(scores, reasons, "SHORT_BREAKDOWN", 1.0, "negative_bias")

    if rsi is not None:
        if 40 <= rsi <= 60:
            _add_score(scores, reasons, "SHORT_BREAKDOWN", 1.0, "rsi_breakdown_zone")
        elif rsi < 25:
            _add_score(scores, reasons, "SHORT_BREAKDOWN", -1.5, "rsi_oversold")

    if extension_atr is not None and extension_atr > 2.0:
        _add_score(scores, reasons, "SHORT_BREAKDOWN", -2.0, "too_extended")

    support_score, support_reasons = _support_bonus("SHORT", supportive)
    if support_score:
        _add_score(scores, reasons, "SHORT_BREAKDOWN", support_score, "supportive_context")
        reasons["SHORT_BREAKDOWN"].extend(support_reasons)

    # ── SHORT_REBOUND ──────────────────────────────────────
    if event_direction == "UP" and abs_1m < max(5.0, abs_5m + 0.5):
        _add_score(scores, reasons, "SHORT_REBOUND", 1.0, "up_rebound_event")
    if regime == "BEAR":
        _add_score(scores, reasons, "SHORT_REBOUND", 2.0, "bear_regime")
    elif regime == "SIDEWAYS":
        _add_score(scores, reasons, "SHORT_REBOUND", 1.0, "sideways_regime")
    elif regime == "BULL":
        _add_score(scores, reasons, "SHORT_REBOUND", -3.0, "bull_regime")

    if ema_down:
        _add_score(scores, reasons, "SHORT_REBOUND", 1.5, "ema_down")
    if extension_atr is not None and extension_atr <= 1.5:
        _add_score(scores, reasons, "SHORT_REBOUND", 2.0, "near_ema50")
    if rsi is not None and 55 <= rsi <= 70:
        _add_score(scores, reasons, "SHORT_REBOUND", 2.0, "rsi_rebound_zone")
    if mtf_score is not None and mtf_score >= 0.6:
        _add_score(scores, reasons, "SHORT_REBOUND", 1.5, "mtf_support")
    if rsi_slope is not None and rsi_slope < 0:
        _add_score(scores, reasons, "SHORT_REBOUND", 1.0, "rsi_slope_down")

    support_score, support_reasons = _support_bonus("SHORT", supportive)
    if support_score:
        _add_score(scores, reasons, "SHORT_REBOUND", support_score, "supportive_context")
        reasons["SHORT_REBOUND"].extend(support_reasons)

    # ── SHORT_EARLY_WEAKNESS ───────────────────────────────
    if signed_delta_1m < 0 and abs_5m < abs_1m:
        _add_score(scores, reasons, "SHORT_EARLY_WEAKNESS", 2.0, "early_down_weakness")
    if regime is not None and regime != "BULL":
        _add_score(scores, reasons, "SHORT_EARLY_WEAKNESS", 1.5, "not_bull_regime")
    if ema_down:
        _add_score(scores, reasons, "SHORT_EARLY_WEAKNESS", 1.0, "ema_down")
    if rsi is not None and 40 <= rsi <= 55:
        _add_score(scores, reasons, "SHORT_EARLY_WEAKNESS", 1.5, "rsi_weakness_zone")
    if rsi_slope is not None and rsi_slope < 0:
        _add_score(scores, reasons, "SHORT_EARLY_WEAKNESS", 1.5, "rsi_slope_down")
    if vol_ratio is not None and 1.2 <= vol_ratio <= 2.0:
        _add_score(scores, reasons, "SHORT_EARLY_WEAKNESS", 1.5, "volume_balanced")
    if mtf_score is not None and mtf_score >= 0.5:
        _add_score(scores, reasons, "SHORT_EARLY_WEAKNESS", 1.0, "mtf_ok")
    if derivative_bias is not None and derivative_bias <= 0:
        _add_score(scores, reasons, "SHORT_EARLY_WEAKNESS", 1.0, "non_positive_bias")

    # ── AVOID_FOMO ─────────────────────────────────────────
    if abs_1m >= 5.0 or abs_5m >= 10.0:
        _add_score(scores, reasons, "AVOID_FOMO", 2.0, "large_spike")
    if rsi is not None and (rsi > 80 or rsi < 20):
        _add_score(scores, reasons, "AVOID_FOMO", 2.0, "rsi_extreme")
    if extension_atr is not None and extension_atr > 2.5:
        _add_score(scores, reasons, "AVOID_FOMO", 2.0, "too_extended")
    if vol_ratio is not None and vol_ratio > 3.0:
        _add_score(scores, reasons, "AVOID_FOMO", 1.5, "blowoff_volume")
    if mtf_score is not None and mtf_score > 0 and mtf_score < 0.5:
        _add_score(scores, reasons, "AVOID_FOMO", 1.5, "mtf_weak")
    if event_direction == "UP" and derivative_bias is not None and derivative_bias < 0:
        _add_score(scores, reasons, "AVOID_FOMO", 1.0, "negative_bias_against_pump")
    if event_direction == "DOWN" and derivative_bias is not None and derivative_bias > 0:
        _add_score(scores, reasons, "AVOID_FOMO", 1.0, "positive_bias_against_dump")
    if atr_percentile is not None and atr_percentile >= 0.9:
        _add_score(scores, reasons, "AVOID_FOMO", 1.0, "atr_hot_zone")
    if bb_width is not None and bb_width >= 0.15:
        _add_score(scores, reasons, "AVOID_FOMO", 0.5, "bb_expanded")

    avoid_score = scores.get("AVOID_FOMO", 0.0)
    if avoid_score >= 8.0:
        return {
            "recommendation": "NO_TRADE",
            "confidence": "LOW" if primary.get("freshness") == "stale" else "MEDIUM",
            "reason": "avoid_override",
            "reason_codes": reasons.get("AVOID_FOMO", [])[:4] + ["avoid_override"],
            "scores": scores,
            "top_actions": sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3],
            "context_state": context_state,
        }

    if avoid_score >= _ACTION_THRESHOLDS["AVOID_FOMO"]:
        return {
            "recommendation": "AVOID_FOMO",
            "confidence": "LOW" if primary.get("freshness") == "stale" else _score_to_confidence(avoid_score),
            "reason": "avoid_fomo",
            "reason_codes": reasons.get("AVOID_FOMO", [])[:4],
            "scores": scores,
            "top_actions": sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3],
            "context_state": context_state,
        }

    long_actions = ["LONG_BREAKOUT", "LONG_PULLBACK", "LONG_EARLY_MOMENTUM"]
    short_actions = ["SHORT_BREAKDOWN", "SHORT_REBOUND", "SHORT_EARLY_WEAKNESS"]

    passed_long = [(a, scores[a]) for a in long_actions if scores[a] >= _ACTION_THRESHOLDS[a]]
    passed_short = [(a, scores[a]) for a in short_actions if scores[a] >= _ACTION_THRESHOLDS[a]]

    passed_long.sort(key=lambda x: x[1], reverse=True)
    passed_short.sort(key=lambda x: x[1], reverse=True)

    if passed_long and passed_short:
        top_long = passed_long[0]
        top_short = passed_short[0]
        if abs(top_long[1] - top_short[1]) <= 3.0:
            return {
                "recommendation": "NO_TRADE",
                "confidence": "LOW" if primary.get("freshness") == "stale" else "MEDIUM",
                "reason": "conflict_actions",
                "reason_codes": [top_long[0], top_short[0], "conflict_actions"],
                "scores": scores,
                "top_actions": sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3],
                "context_state": context_state,
            }

    passed_actions = [(a, s) for a, s in scores.items() if a != "AVOID_FOMO" and s >= _ACTION_THRESHOLDS.get(a, 999)]
    passed_actions.sort(key=lambda x: x[1], reverse=True)

    if not passed_actions:
        return {
            "recommendation": "WATCH_ONLY",
            "confidence": "LOW" if primary.get("freshness") == "stale" else "MEDIUM",
            "reason": "no_action_passed",
            "reason_codes": ["no_action_passed"],
            "scores": scores,
            "top_actions": sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3],
            "context_state": context_state,
        }

    top_action, top_score = passed_actions[0]
    confidence = _score_to_confidence(top_score)
    if primary.get("freshness") == "stale":
        confidence = _downgrade_confidence(confidence)

    reason_codes = reasons.get(top_action, [])[:5]
    if primary.get("freshness") == "stale":
        reason_codes.append("stale_context")

    return {
        "recommendation": top_action,
        "confidence": confidence,
        "reason": "action_selected",
        "reason_codes": reason_codes,
        "scores": scores,
        "top_actions": sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3],
        "context_state": context_state,
    }
