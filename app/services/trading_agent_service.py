from datetime import timedelta
import numpy as np
from typing import Dict, List, Optional

from app.core.time_utils import utc_now, to_vn_str
from app.db.models import PendingSignal, Signal
from app.db.session import SessionLocal
from app.services.llm_router import ask_gemini, ask_groq
from app.services.telegram_service import send_telegram


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _metrics(trades: List[Signal]) -> Dict[str, float]:
    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "winrate_pct": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "final_equity": 10000.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
        }

    returns = np.array([_safe_float(t.result_percent) for t in trades], dtype=float)
    wins = int((returns > 0).sum())
    losses = int((returns < 0).sum())
    winrate = wins / len(returns) * 100 if len(returns) else 0.0
    avg_win = float(returns[returns > 0].mean()) if wins > 0 else 0.0
    avg_loss = float(returns[returns < 0].mean()) if losses > 0 else 0.0
    gross_profit = float(returns[returns > 0].sum()) if wins > 0 else 0.0
    gross_loss = abs(float(returns[returns < 0].sum())) if losses > 0 else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    expectancy = round(float(returns.mean()), 3)
    sharpe = round(float(returns.mean() / (returns.std() + 1e-10) * np.sqrt(252)), 2)

    equity = 10000.0
    peak = equity
    max_dd = 0.0
    for r in returns:
        equity *= (1 + r / 100)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)

    return {
        "total_trades": int(len(returns)),
        "wins": wins,
        "losses": losses,
        "winrate_pct": round(winrate, 1),
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "sharpe": sharpe,
        "max_drawdown": round(max_dd, 2),
        "final_equity": round(equity, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
    }


def _detect_anomalies(
    period_trades: List[Signal],
    all_trades: List[Signal],
    pending_count: int,
    live_context: Optional[Dict] = None,
) -> List[str]:
    anomalies = []
    live_context = live_context or {}
    p_metrics = _metrics(period_trades)
    if p_metrics["total_trades"] == 0:
        anomalies.append("No closed trades in this report period.")
    else:
        if p_metrics["winrate_pct"] < 30:
            anomalies.append(f"Low winrate: {p_metrics['winrate_pct']}%.")
        if p_metrics["winrate_pct"] > 80 and p_metrics["total_trades"] >= 5:
            anomalies.append(f"Unusually high winrate: {p_metrics['winrate_pct']}%, check sample bias.")
        if p_metrics["profit_factor"] < 1.1:
            anomalies.append(f"Weak profit factor: {p_metrics['profit_factor']}.")
        if p_metrics["expectancy"] < 0.2:
            anomalies.append(f"Low expectancy: {p_metrics['expectancy']}% per trade.")
        if p_metrics["max_drawdown"] > 15:
            anomalies.append(f"Large max drawdown: {p_metrics['max_drawdown']}%.")

        atr_values = [_safe_float(t.atr_ratio) * 100 for t in period_trades if getattr(t, "atr_ratio", None) is not None]
        if atr_values:
            avg_atr = float(np.mean(atr_values))
            high_atr_count = sum(1 for x in atr_values if x > 3.0)
            if avg_atr > 2.5:
                anomalies.append(f"Strong volatility regime: average ATR {avg_atr:.2f}% in this period.")
            elif avg_atr > 1.5:
                anomalies.append(f"Elevated volatility: average ATR {avg_atr:.2f}%.")
            if high_atr_count >= 3:
                anomalies.append(f"{high_atr_count} trades had ATR > 3%, market noise is high.")

        current_streak = 0
        max_loss_streak = 0
        for trade in sorted(period_trades, key=lambda x: x.exit_time or x.created_at):
            if _safe_float(trade.result_percent) < 0:
                current_streak += 1
                max_loss_streak = max(max_loss_streak, current_streak)
            else:
                current_streak = 0
        if max_loss_streak >= 3:
            anomalies.append(f"Loss streak: {max_loss_streak} consecutive losses.")

        long_trades = [t for t in period_trades if t.direction == "LONG"]
        short_trades = [t for t in period_trades if t.direction == "SHORT"]
        total_dir = len(long_trades) + len(short_trades)
        if total_dir > 0:
            long_bias = len(long_trades) / total_dir * 100
            if long_bias >= 70:
                anomalies.append(f"Direction bias: LONG is {long_bias:.0f}% of period trades.")
            if long_bias <= 30:
                anomalies.append(f"Direction bias: SHORT is {100 - long_bias:.0f}% of period trades.")

        if all_trades:
            all_metrics = _metrics(all_trades)
            if p_metrics["winrate_pct"] < all_metrics["winrate_pct"] - 15:
                anomalies.append("This period underperformed lifetime winrate by more than 15 percentage points.")

    if pending_count >= 10:
        anomalies.append(f"High pending count: {pending_count} waiting orders.")

    if live_context.get("open_unrealized_pct") is not None and live_context["open_unrealized_pct"] < -2.0:
        anomalies.append(f"Open trades are under pressure: unrealized PnL {live_context['open_unrealized_pct']:.2f}%.")

    if live_context.get("user_stream_connected") is False:
        anomalies.append("Binance user stream is not connected; fill/close sync may lag.")

    if live_context.get("recent_vol_alerts"):
        anomalies.append(f"Recent volatility alerts: {len(live_context['recent_vol_alerts'])} symbols flagged.")

    return anomalies


def _build_live_context(open_trades: List[Signal], pending_count: int) -> Dict:
    context = {
        "pending_count": pending_count,
        "pending_placed_count": 0,
        "open_unrealized_pct": None,
        "price_feed_connected": None,
        "user_stream_connected": None,
        "user_stream_events_saved": None,
        "recent_vol_alerts": [],
        "exit_reasons": {},
    }

    try:
        with SessionLocal() as db:
            context["pending_placed_count"] = db.query(PendingSignal).filter(
                PendingSignal.status == "WAIT",
                PendingSignal.exchange_order_id.isnot(None),
            ).count()

            rows = db.query(Signal.exit_reason).filter(
                Signal.status.in_(["WIN", "LOSS", "MANUAL"]),
                Signal.exit_reason.isnot(None),
            ).order_by(Signal.exit_time.desc()).limit(100).all()
            reasons = {}
            for (reason,) in rows:
                reasons[reason or "UNKNOWN"] = reasons.get(reason or "UNKNOWN", 0) + 1
            context["exit_reasons"] = reasons
    except Exception as e:
        context["db_context_error"] = f"{type(e).__name__}: {e}"

    try:
        from app.services.price_feed import get_all_current_prices, get_price_feed

        prices = get_all_current_prices() or {}
        total_pnl = 0.0
        counted = 0
        for trade in open_trades:
            current = prices.get(trade.symbol)
            entry = _safe_float(trade.entry_price)
            if current is None or entry <= 0:
                continue
            current = float(current)
            if trade.direction == "LONG":
                pnl = (current - entry) / entry * 100
            else:
                pnl = (entry - current) / entry * 100
            total_pnl += pnl
            counted += 1
        if counted:
            context["open_unrealized_pct"] = round(total_pnl, 3)

        stats = get_price_feed().get_stats()
        context["price_feed_connected"] = bool(stats.get("connected") or stats.get("ws_running"))
        context["price_feed_mode"] = stats.get("mode") or stats.get("active_source")
        context["price_feed_symbols"] = stats.get("symbols_count")
    except Exception as e:
        context["price_feed_error"] = f"{type(e).__name__}: {e}"

    try:
        from app.services.binance_user_stream_service import get_user_stream

        stats = get_user_stream().get_stats()
        context["user_stream_connected"] = bool(stats.get("connected"))
        context["user_stream_events_saved"] = stats.get("events_saved")
        context["user_stream_last_error"] = stats.get("last_error")
    except Exception as e:
        context["user_stream_error"] = f"{type(e).__name__}: {e}"

    try:
        from app.services.volatility_alert_service import get_recent_volatility_alerts

        context["recent_vol_alerts"] = get_recent_volatility_alerts(5)
    except Exception:
        context["recent_vol_alerts"] = []

    return context


def _format_live_context(live_context: Dict) -> str:
    lines = ["<b>📌 BỐI CẢNH LIVE</b>"]
    lines.append(f"📊 PnL tạm tính lệnh mở: {live_context.get('open_unrealized_pct')}%")
    lines.append(f"⏳ Lệnh chờ placed/waiting: {live_context.get('pending_placed_count')}/{live_context.get('pending_count')}")
    lines.append(f"📡 Price feed: {live_context.get('price_feed_connected')} | mode={live_context.get('price_feed_mode')}")
    lines.append(f"🔐 User stream: {live_context.get('user_stream_connected')} | events={live_context.get('user_stream_events_saved')}")

    reasons = live_context.get("exit_reasons") or {}
    if reasons:
        top = sorted(reasons.items(), key=lambda x: x[1], reverse=True)[:6]
        lines.append("📝 Lý do đóng gần đây: " + ", ".join(f"{k}={v}" for k, v in top))

    alerts = live_context.get("recent_vol_alerts") or []
    if alerts:
        parts = []
        for alert in alerts[:5]:
            delta_1m = alert.get("signed_delta_1m", alert.get("delta_1m"))
            delta_5m = alert.get("signed_delta_5m", alert.get("delta_5m"))
            parts.append(
                f"{alert.get('symbol')} {alert.get('direction')} "
                f"1m={_safe_float(delta_1m):+.2f}% "
                f"5m={_safe_float(delta_5m):+.2f}%"
            )
        lines.append("🌊 Cảnh báo biến động gần đây: " + "; ".join(parts))

    return "\n".join(lines)


def _compose_base_report(
    title: str,
    periods: str,
    m_p: Dict[str, float],
    m_a: Dict[str, float],
    long_trades: List[Signal],
    short_trades: List[Signal],
    strat_lines: str,
    best: Optional[Signal],
    worst: Optional[Signal],
    open_count: int,
    pending_count: int,
    anomalies: List[str],
    live_context: Dict,
) -> str:
    report = (
        f"<b>{title}</b>\n"
        f"<i>{periods}</i>\n\n"
        f"<b>📊 HIỆU SUẤT KỲ NÀY</b>\n"
        f"Lệnh: {m_p['total_trades']}\n"
        f"Winrate: {m_p['winrate_pct']}%\n"
        f"PF: {m_p['profit_factor']}\n"
        f"Sharpe: {m_p['sharpe']}\n"
        f"Max DD: {m_p['max_drawdown']}%\n"
        f"Expectancy: {m_p['expectancy']}% / lệnh\n"
        f"Avg Win: {m_p['avg_win']}% | Avg Loss: {m_p['avg_loss']}%\n\n"
        f"<b>🧭 HƯỚNG LỆNH</b>\n"
        f"🟢 LONG: {len(long_trades)} lệnh\n"
        f"🔴 SHORT: {len(short_trades)} lệnh\n"
    )
    if strat_lines:
        report += f"\n<b>🧩 STRATEGY</b>\n{strat_lines}"
    if best:
        report += f"\n<b>🏆 Lệnh tốt nhất:</b> {best.symbol} {best.direction} {_safe_float(best.result_percent):+.2f}%\n"
    if worst:
        report += f"<b>📉 Lệnh yếu nhất:</b> {worst.symbol} {worst.direction} {_safe_float(worst.result_percent):+.2f}%\n"
    report += (
        f"\n<b>📌 TRẠNG THÁI</b>\n"
        f"🟢 Đang mở: {open_count}\n"
        f"⏳ Đang chờ: {pending_count}\n"
        f"💵 Equity ước tính: ${m_a['final_equity']}\n\n"
        f"{_format_live_context(live_context)}\n"
    )
    if anomalies:
        report += "\n<b>⚠️ CẢNH BÁO / BẤT THƯỜNG</b>\n"
        for item in anomalies:
            report += f"- {item}\n"
    return report


def _generate_agent_prompt(summary: str, anomalies: List[str], live_context: Dict) -> str:
    prompt = (
        "Ban la chuyen gia phan tich giao dich dinh luong. "
        "Duoi day la bao cao hieu suat va trang thai live cua trading system. "
        "Hay tom tat ngan gon, neu xu huong chinh, rui ro dang chu y, va diem can theo doi tiep. "
        "Tra loi bang tieng Viet, ro rang, khong dua loi khuyen dau tu tuyet doi.\n\n"
        "BAO CAO:\n" + summary + "\n"
    )
    if anomalies:
        prompt += "\nCANH BAO:\n" + "\n".join(f"- {x}" for x in anomalies) + "\n"
    prompt += "\nLIVE CONTEXT RAW:\n" + str(live_context) + "\n"
    prompt += (
        "\nYeu cau:\n"
        "1. Tom tat ket qua chinh.\n"
        "2. Giai thich xu huong va bat thuong neu co.\n"
        "3. Danh gia rui ro live: open PnL, pending, feed/user stream, volatility alerts.\n"
        "4. De xuat diem can theo doi, khong tu de xuat vao lenh."
    )
    return prompt


def _ask_agent(prompt: str) -> Optional[str]:
    response = ask_gemini(prompt)
    if response:
        return response
    return ask_groq(prompt)


def generate_agent_report(report_type: str, days: int, title: str) -> str:
    db = SessionLocal()
    now = utc_now()
    cutoff = now - timedelta(days=days)
    try:
        period_trades = db.query(Signal).filter(
            Signal.status.in_(["WIN", "LOSS"]),
            Signal.exit_time >= cutoff,
        ).order_by(Signal.exit_time.asc()).all()
        all_trades = db.query(Signal).filter(Signal.status.in_(["WIN", "LOSS"])).all()
        open_trades = db.query(Signal).filter(Signal.status == "OPEN").all()
        pending_count = db.query(PendingSignal).filter(PendingSignal.status == "WAIT").count()
    finally:
        db.close()

    open_count = len(open_trades)
    live_context = _build_live_context(open_trades, pending_count)
    m_p = _metrics(period_trades)
    m_a = _metrics(all_trades)
    long_trades = [t for t in period_trades if t.direction == "LONG"]
    short_trades = [t for t in period_trades if t.direction == "SHORT"]

    strat_groups = {}
    for trade in period_trades:
        strat_groups.setdefault(trade.strategy_name or "unknown", []).append(trade)
    strat_lines = ""
    for name, group in strat_groups.items():
        sm = _metrics(group)
        strat_lines += f"  {name}: {sm['total_trades']} trades, WR={sm['winrate_pct']}%\n"

    sorted_trades = sorted(period_trades, key=lambda t: _safe_float(t.result_percent), reverse=True)
    best = sorted_trades[0] if sorted_trades else None
    worst = sorted_trades[-1] if sorted_trades else None

    date_range = f"{to_vn_str(cutoff, '%Y-%m-%d')} -> {to_vn_str(now, '%Y-%m-%d')} (GMT+7)"

    anomalies = _detect_anomalies(period_trades, all_trades, pending_count, live_context)
    base_report = _compose_base_report(
        title,
        date_range,
        m_p,
        m_a,
        long_trades,
        short_trades,
        strat_lines,
        best,
        worst,
        open_count,
        pending_count,
        anomalies,
        live_context,
    )

    prompt = _generate_agent_prompt(base_report, anomalies, live_context)
    ai_summary = _ask_agent(prompt)
    if ai_summary:
        report = f"{base_report}\n\n<b>🧠 TÓM TẮT AI</b>\n{ai_summary}"
    else:
        report = f"{base_report}\n\n⚠️ AI chưa phản hồi, mình gửi báo cáo nền trước."

    try:
        from sqlalchemy import text

        db2 = SessionLocal()
        db2.execute(
            text(
                "INSERT INTO reports (report_type, period_start, period_end, content, created_at) "
                "VALUES (:rt, :ps, :pe, :c, NOW())"
            ),
            {"rt": report_type, "ps": cutoff, "pe": now, "c": report},
        )
        db2.commit()
        db2.close()
    except Exception as e:
        print(f"[AGENT REPORT] DB save error: {e}")

    return report


def generate_live_risk_report() -> str:
    from sqlalchemy import text
    from app.services.live_health_service import get_live_health

    health = get_live_health()
    db = health.get("database") or {}
    price_feed = health.get("price_feed") or {}
    user_stream = health.get("user_stream") or {}
    alerts = health.get("market_alerts") or []

    lines = [
        "<b>🧠 LIVE RISK ANALYST</b>",
        f"📌 Trạng thái: {health.get('status')} | mode={health.get('mode')}",
        f"⚠️ Vấn đề: {', '.join(health.get('issues') or []) or 'không có'}",
        f"🔔 Cảnh báo: {', '.join(health.get('warnings') or []) or 'không có'}",
        "",
        "<b>📊 TRẠNG THÁI LIVE</b>",
        f"📈 Lệnh mở: {db.get('open_count', 0)} | coin={', '.join(db.get('open_symbols') or []) or 'không có'}",
        f"⏳ Lệnh chờ: {db.get('pending_wait_count', 0)} | placed={db.get('pending_placed_count', 0)}",
        f"🛡 Thiếu protection: {db.get('missing_protection_count', 0)}",
        f"⏱ Pending quá lâu: {db.get('stale_pending_count', 0)}",
        f"EXCHANGE_CLOSE_UNKNOWN: {db.get('exchange_close_unknown_count', 0)}",
        "",
        "<b>🔧 HẠ TẦNG</b>",
        f"📡 Price feed: {price_feed.get('healthy')} | mode={price_feed.get('mode')} | symbols={price_feed.get('symbols_count')}",
        f"🔐 User stream: {user_stream.get('connected')} | events={user_stream.get('events_saved')} | last={user_stream.get('last_event_type')}",
    ]

    if alerts:
        lines.append("")
        lines.append("<b>🌊 BIẾN ĐỘNG GẦN ĐÂY</b>")
        for alert in alerts[:5]:
            lines.append(
                f"- {alert.get('symbol')} {alert.get('direction')} "
                f"{_safe_float(alert.get('delta_1m')):+.2f}%/1m "
                f"{_safe_float(alert.get('delta_5m')):+.2f}%/5m "
                f"({alert.get('reason')})"
            )

    base_report = "\n".join(lines)
    prompt = (
        "Ban la live risk analyst cho mot futures trading bot. "
        "Hay doc health snapshot ben duoi va tra loi ngan gon bang tieng Viet: "
        "rui ro cap bach, dieu kien co the tiep tuc van hanh, va muc can theo doi. "
        "Khong dua khuyen nghi vao lenh moi.\n\n"
        f"{base_report}\n\nRAW HEALTH:\n{health}"
    )
    ai_summary = _ask_agent(prompt)
    report = f"{base_report}\n\n<b>🧠 TÓM TẮT RỦI RO AI</b>\n{ai_summary}" if ai_summary else f"{base_report}\n\n⚠️ AI chưa phản hồi, mình gửi health summary trước."

    try:
        with SessionLocal() as db2:
            now = utc_now()
            db2.execute(
                text(
                    "INSERT INTO reports (report_type, period_start, period_end, content, created_at) "
                    "VALUES (:rt, :ps, :pe, :c, NOW())"
                ),
                {"rt": "agent_live", "ps": now, "pe": now, "c": report},
            )
            db2.commit()
    except Exception as e:
        print(f"[AGENT LIVE] DB save error: {e}")

    return report


def send_agent_daily():
    report = generate_agent_report("daily", 1, "🧠 BÁO CÁO AGENT NGÀY")
    send_telegram(report)
    return report


def send_agent_weekly():
    report = generate_agent_report("weekly", 7, "🧠 BÁO CÁO AGENT TUẦN")
    send_telegram(report)
    return report


def send_agent_monthly():
    report = generate_agent_report("monthly", 30, "🧠 BÁO CÁO AGENT THÁNG")
    send_telegram(report)
    return report


def send_agent_live():
    report = generate_live_risk_report()
    send_telegram(report)
    return report
