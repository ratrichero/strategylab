from typing import List


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


def build_volatility_message_block(alert: dict, context: dict, recommendation: dict) -> List[str]:
    lines: List[str] = []

    direction = "TĂNG" if alert.get("direction") == "UP" else "GIẢM"
    icon = "🟢" if alert.get("direction") == "UP" else "🔴"
    symbol = alert.get("symbol") or ""
    price_str = _fmt_price(alert.get("current_price"))

    lines.append(
        f"{icon} <b>{symbol}</b> {price_str} {direction}: {alert.get('reason')} "
        f"| 1m {alert.get('signed_delta_1m', 0):+.2f}% | 5m {alert.get('signed_delta_5m', 0):+.2f}%"
    )

    primary = context.get("primary")
    if primary is None:
        lines.append(
            f"└─ Ctx: thiếu xác nhận | Khuyến nghị: <b>{recommendation.get('recommendation')}</b> "
            f"({recommendation.get('confidence')})"
        )
        lines.append(
            f"   Lý do: {', '.join(recommendation.get('reason_codes', [])[:3]) or recommendation.get('reason')}"
        )
        return lines

    ctx_parts = [
        f"15m {primary.get('regime') or 'n/a'}",
        f"MTF {_fmt_float(primary.get('mtf_score'))}",
        f"RSI {_fmt_float(primary.get('rsi'), 1)}",
        f"Bias {_fmt_float(primary.get('derivative_bias'))}",
        f"{primary.get('freshness')}",
    ]

    supportive = context.get("supportive") or {}
    support_parts = []
    for tf in ["1h", "4h"]:
        row = supportive.get(tf)
        if not row:
            continue
        support_parts.append(
            f"{tf}:{row.get('regime') or 'n/a'}/{_fmt_float(row.get('mtf_score'))}/{row.get('freshness')}"
        )

    lines.append(
        f"└─ Ctx: {' | '.join(ctx_parts)}"
        + (f" | Hỗ trợ: {', '.join(support_parts)}" if support_parts else "")
    )

    lines.append(
        f"   Khuyến nghị: <b>{recommendation.get('recommendation')}</b> "
        f"({recommendation.get('confidence')})"
    )

    reason_codes = recommendation.get("reason_codes") or []
    if reason_codes:
        lines.append(f"   Lý do: {', '.join(reason_codes[:4])}")

    return lines