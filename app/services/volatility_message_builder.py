from typing import List


ALERT_REASON_LABELS = {
    "BTC 1m": "BTC biến động mạnh 1 phút",
    "BTC 5m": "BTC biến động mạnh 5 phút",
    "Short-term spike": "Giật mạnh ngắn hạn",
    "Large move": "Biến động lớn",
    "Early abnormal move": "Biến động bất thường sớm",
}

REGIME_LABELS = {
    "BULL": "Tăng",
    "BEAR": "Giảm",
    "SIDEWAYS": "Đi ngang",
}

FRESHNESS_LABELS = {
    "fresh": "Mới",
    "stale": "Cũ",
    "expired": "Quá hạn",
    "missing": "Thiếu",
}

CONFIDENCE_LABELS = {
    "VERY_HIGH": "Rất cao",
    "HIGH": "Cao",
    "MEDIUM": "Vừa",
    "LOW": "Thấp",
}

REASON_LABELS = {
    "missing_context": "Thiếu dữ liệu bối cảnh",
    "stale_context": "Bối cảnh tham chiếu đã cũ",
    "price_only_alert": "Mới chỉ có tín hiệu giá",
    "no_action_passed": "Chưa đủ điều kiện hành động",
    "conflict_actions": "Tín hiệu còn mâu thuẫn",
    "avoid_override": "Rủi ro FOMO quá cao",
    "supportive_context": "Khung lớn đang hỗ trợ",
    "up_event": "Giá đang tăng mạnh",
    "down_event": "Giá đang giảm mạnh",
    "bull_regime": "Bối cảnh ngắn hạn đang thiên tăng",
    "bear_regime": "Bối cảnh ngắn hạn đang thiên giảm",
    "sideways_regime": "Bối cảnh ngắn hạn đang đi ngang",
    "not_bear_regime": "Chưa rơi vào xu hướng giảm mạnh",
    "not_bull_regime": "Chưa rơi vào xu hướng tăng mạnh",
    "ema_up": "EMA50 đang nằm trên EMA200",
    "ema_down": "EMA50 đang nằm dưới EMA200",
    "ema200_slope_up": "EMA200 đang dốc lên",
    "mtf_high": "Đồng thuận đa khung mạnh",
    "mtf_mid": "Đồng thuận đa khung trung bình",
    "mtf_weak": "Đồng thuận đa khung yếu",
    "mtf_support": "Khung lớn đang ủng hộ",
    "mtf_ok": "Khung lớn chưa mâu thuẫn",
    "volume_confirm": "Khối lượng xác nhận nhịp giá",
    "volume_weak": "Khối lượng xác nhận còn yếu",
    "volume_balanced": "Khối lượng ở mức hợp lý",
    "volume_spiky": "Khối lượng tăng sốc, dễ nhiễu",
    "volume_too_hot": "Khối lượng quá nóng",
    "positive_bias": "Phái sinh đang ủng hộ nhịp tăng",
    "negative_bias": "Phái sinh đang ủng hộ nhịp giảm",
    "non_negative_bias": "Phái sinh không chống lại nhịp tăng",
    "non_positive_bias": "Phái sinh không chống lại nhịp giảm",
    "negative_bias_against_pump": "Giá tăng nhưng phái sinh chưa ủng hộ",
    "positive_bias_against_dump": "Giá giảm nhưng phái sinh chưa ủng hộ",
    "rsi_breakout_zone": "RSI đang ở vùng thuận breakout",
    "rsi_pullback_zone": "RSI đang ở vùng pullback đẹp",
    "rsi_early_zone": "RSI còn sớm, chưa quá nóng",
    "rsi_rebound_zone": "RSI đang ở vùng hồi dễ short",
    "rsi_weakness_zone": "RSI cho thấy đà yếu dần",
    "rsi_slope_up": "RSI đang dốc lên",
    "rsi_slope_down": "RSI đang dốc xuống",
    "rsi_too_hot": "RSI quá nóng",
    "rsi_too_weak": "RSI quá yếu",
    "rsi_extreme": "RSI đang ở vùng cực đoan",
    "rsi_oversold": "RSI đã quá bán, dễ bật ngược",
    "near_ema50": "Giá đang gần EMA50",
    "far_from_ema50": "Giá đang lệch xa EMA50",
    "too_extended": "Giá đã chạy quá xa",
    "large_spike": "Biến động quá mạnh",
    "blowoff_volume": "Khối lượng bùng nổ, dễ có nhịp xả ngược",
    "atr_hot_zone": "Biến động đang quá nóng",
    "bb_expanded": "Dải Bollinger đang mở rộng mạnh",
    "early_up_momentum": "Đà tăng mới hình thành",
    "early_down_weakness": "Đà giảm mới hình thành",
    "up_rebound_event": "Giá đang hồi lên trong bối cảnh có thể short",
    "action_selected": "Đã có đủ cơ sở hành động",
    "avoid_fomo": "Biến động quá nóng, nên tránh đuổi theo",
}


def _fmt_price(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    if value >= 1000:
        return f"${value:,.2f}"
    if value >= 1:
        return f"${value:,.4f}"
    return f"${value:,.6f}"


def _fmt_float(value, decimals=2, suffix="") -> str:
    try:
        return f"{float(value):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_symbol(symbol) -> str:
    symbol = (symbol or "").upper()
    if symbol.endswith("USDT") and len(symbol) > 4:
        return symbol[:-4]
    return symbol


def _translate_alert_reason(reason: str) -> str:
    return ALERT_REASON_LABELS.get(reason, reason or "")


def _translate_regime(regime: str) -> str:
    return REGIME_LABELS.get(regime, regime or "n/a")


def _translate_freshness(freshness: str) -> str:
    return FRESHNESS_LABELS.get(freshness, freshness or "n/a")


def _translate_confidence(confidence: str) -> str:
    return CONFIDENCE_LABELS.get(confidence, confidence or "n/a")


def _translate_action(action: str, alert: dict) -> str:
    direction = alert.get("direction")

    if action == "LONG_BREAKOUT":
        return "Mua breakout"
    if action == "LONG_PULLBACK":
        return "Canh mua khi hồi"
    if action == "LONG_EARLY_MOMENTUM":
        return "Mua sớm theo đà"
    if action == "SHORT_BREAKDOWN":
        return "Short thủng hỗ trợ"
    if action == "SHORT_REBOUND":
        return "Canh short khi hồi"
    if action == "SHORT_EARLY_WEAKNESS":
        return "Short sớm khi đà yếu dần"
    if action == "WATCH_ONLY":
        return "Chỉ quan sát"
    if action == "NO_TRADE":
        return "Bỏ qua, chưa nên vào lệnh"
    if action == "AVOID_FOMO":
        if direction == "UP":
            return "Tránh FOMO (không mua đuổi)"
        if direction == "DOWN":
            return "Tránh FOMO (không short đuổi)"
        return "Tránh FOMO (đứng ngoài)"

    return action or "Chỉ quan sát"


def _translate_reason_code(code: str) -> str:
    if not code:
        return ""

    if code in REASON_LABELS:
        return REASON_LABELS[code]

    if code.endswith("_ema_support"):
        tf = code.split("_", 1)[0]
        return f"Khung {tf} đang đồng thuận theo EMA"

    if code.endswith("_bull_regime"):
        tf = code.split("_", 1)[0]
        return f"Khung {tf} đang nghiêng tăng"

    if code.endswith("_bear_regime"):
        tf = code.split("_", 1)[0]
        return f"Khung {tf} đang nghiêng giảm"

    if code.endswith("_mtf_high"):
        tf = code.split("_", 1)[0]
        return f"Khung {tf} đồng thuận mạnh"

    return code


def _build_supportive_text(supportive: dict) -> str:
    parts = []
    for tf in ["1h", "4h"]:
        row = supportive.get(tf)
        if not row:
            continue

        regime = _translate_regime(row.get("regime"))
        freshness = _translate_freshness(row.get("freshness"))
        mtf_score = row.get("mtf_score")

        if mtf_score is not None:
            parts.append(f"{tf} {regime} | MTF {_fmt_float(mtf_score)} | {freshness}")
        else:
            parts.append(f"{tf} {regime} | {freshness}")

    return " | ".join(parts)


def _build_reason_text(recommendation: dict) -> str:
    reason_codes = recommendation.get("reason_codes") or []
    translated = []
    seen = set()

    for code in reason_codes:
        text = _translate_reason_code(code)
        if not text or text in seen:
            continue
        seen.add(text)
        translated.append(text)

    if translated:
        return ", ".join(translated[:4])

    fallback_reason = recommendation.get("reason")
    return _translate_reason_code(fallback_reason) or (fallback_reason or "")


def build_volatility_message_block(alert: dict, context: dict, recommendation: dict) -> List[str]:
    lines: List[str] = []

    direction = "TĂNG" if alert.get("direction") == "UP" else "GIẢM"
    icon = "🟢" if alert.get("direction") == "UP" else "🔴"
    symbol = _fmt_symbol(alert.get("symbol"))
    price_str = _fmt_price(alert.get("current_price"))
    alert_reason = _translate_alert_reason(alert.get("reason"))
    action_text = _translate_action(recommendation.get("recommendation"), alert)
    confidence_text = _translate_confidence(recommendation.get("confidence"))

    lines.append(
        f"{icon} <b>{symbol}</b> {price_str} {direction}: {alert_reason} "
        f"| 1m {alert.get('signed_delta_1m', 0):+.2f}% | 5m {alert.get('signed_delta_5m', 0):+.2f}%"
    )

    primary = context.get("primary")
    if primary is None:
        lines.append("└─ Bối cảnh: thiếu dữ liệu xác nhận")
        lines.append(f"   Gợi ý: <b>{action_text}</b>")
        lines.append(f"   Độ tin cậy: {confidence_text}")
        lines.append(f"   Lý do: {_build_reason_text(recommendation)}")
        return lines

    ctx_parts = [
        f"15m {_translate_regime(primary.get('regime'))}",
        f"MTF {_fmt_float(primary.get('mtf_score'))}",
        f"RSI {_fmt_float(primary.get('rsi'), 1)}",
        f"Bias {_fmt_float(primary.get('derivative_bias'))}",
        f"Dữ liệu {_translate_freshness(primary.get('freshness'))}",
    ]

    supportive = context.get("supportive") or {}
    support_text = _build_supportive_text(supportive)

    lines.append(f"└─ Bối cảnh: {' | '.join(ctx_parts)}")
    if support_text:
        lines.append(f"   Hỗ trợ: {support_text}")

    lines.append(f"   Gợi ý: <b>{action_text}</b>")
    lines.append(f"   Độ tin cậy: {confidence_text}")
    lines.append(f"   Lý do: {_build_reason_text(recommendation)}")

    return lines