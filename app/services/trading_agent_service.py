from datetime import timedelta
import numpy as np
from typing import Dict, List, Optional
from app.db.session import SessionLocal
from app.db.models import Signal, PendingSignal
from app.services.llm_router import ask_groq, ask_gemini
from app.services.telegram_service import send_telegram
from app.core.time_utils import utc_now, vn_now, to_vn_str


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
        }

    returns = np.array([float(t.result_percent or 0) for t in trades])
    wins = int((returns > 0).sum())
    losses = len(returns) - wins
    winrate = wins / len(returns) * 100 if len(returns) else 0.0
    avg_win = float(returns[returns > 0].mean()) if wins > 0 else 0.0
    avg_loss = float(returns[returns < 0].mean()) if losses > 0 else 0.0
    gross_profit = float(returns[returns > 0].sum()) if wins > 0 else 0.0
    gross_loss = abs(float(returns[returns < 0].sum())) if losses > 0 else 1.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0
    expectancy = round(float(returns.mean()) * 100, 3)
    sharpe = round(float(returns.mean() / (returns.std() + 1e-10) * np.sqrt(252)), 2)

    equity = 10000.0
    peak = equity
    max_dd = 0.0
    for r in returns:
        equity *= (1 + r / 100)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)

    return {
        "total_trades": len(returns),
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


def _detect_anomalies(period_trades: List[Signal], all_trades: List[Signal], pending_count: int) -> List[str]:
    anomalies = []
    p_metrics = _metrics(period_trades)
    if p_metrics["total_trades"] == 0:
        anomalies.append("Không có lệnh đóng trong kỳ báo cáo.")
        return anomalies

    if p_metrics["winrate_pct"] < 30:
        anomalies.append(f"Winrate thấp: {p_metrics['winrate_pct']}%.")
    if p_metrics["winrate_pct"] > 80:
        anomalies.append(f"Winrate cao bất thường: {p_metrics['winrate_pct']}%, kiểm tra bias dữ liệu.")
    if p_metrics["profit_factor"] < 1.1:
        anomalies.append(f"Profit factor yếu: {p_metrics['profit_factor']}.")
    if p_metrics["expectancy"] < 0.2:
        anomalies.append(f"Expectancy thấp: {p_metrics['expectancy']}%.")
    if p_metrics["max_drawdown"] > 15:
        anomalies.append(f"Max drawdown lớn: {p_metrics['max_drawdown']}%.")
    if pending_count >= 10:
        anomalies.append(f"Có nhiều lệnh pending: {pending_count} lệnh.")

    atr_values = [float(t.atr_ratio or 0) * 100 for t in period_trades if getattr(t, "atr_ratio", None) is not None]
    if atr_values:
        avg_atr = float(np.mean(atr_values))
        high_atr_count = sum(1 for x in atr_values if x > 3.0)
        if avg_atr > 2.5:
            anomalies.append(f"Biến động mạnh: ATR trung bình {avg_atr:.2f}% trong kỳ báo cáo.")
        elif avg_atr > 1.5:
            anomalies.append(f"Volatility cao: ATR trung bình {avg_atr:.2f}%.")
        if high_atr_count >= 3:
            anomalies.append(f"Có {high_atr_count} trades ATR > 3%, cảnh báo thị trường đang rất ồn.")

    # consecutive loss detection
    current_streak = 0
    max_loss_streak = 0
    for t in sorted(period_trades, key=lambda x: x.exit_time or x.created_at):
        if float(t.result_percent or 0) < 0:
            current_streak += 1
            max_loss_streak = max(max_loss_streak, current_streak)
        else:
            current_streak = 0
    if max_loss_streak >= 3:
        anomalies.append(f"Chuỗi thua dài: {max_loss_streak} lệnh liên tiếp.")

    long_trades = [t for t in period_trades if t.direction == "LONG"]
    short_trades = [t for t in period_trades if t.direction == "SHORT"]
    if len(long_trades) + len(short_trades) > 0:
        long_bias = len(long_trades) / max(1, len(long_trades) + len(short_trades)) * 100
        if long_bias >= 70:
            anomalies.append(f"Bias dài hạn: LONG chiếm {long_bias:.0f}% tổng lệnh.")
        if long_bias <= 30:
            anomalies.append(f"Bias ngắn hạn: SHORT chiếm {100-long_bias:.0f}% tổng lệnh.")

    if all_trades:
        all_metrics = _metrics(all_trades)
        if p_metrics["winrate_pct"] < all_metrics["winrate_pct"] - 15:
            anomalies.append("Hiệu suất kỳ này kém hơn hiệu suất tổng thể hơn 15 điểm phần trăm.")

    return anomalies


def _compose_base_report(title: str, report_type: str, periods: str, m_p: Dict[str, float], m_a: Dict[str, float], long_trades: List[Signal], short_trades: List[Signal], strat_lines: str, best: Optional[Signal], worst: Optional[Signal], open_count: int, pending_count: int, anomalies: List[str]) -> str:
    report = (
        f"<b>{title}</b>\n"
        f"<i>{periods}</i>\n\n"
        f"<b>═══ HIỆU SUẤT KỲ ═══</b>\n"
        f"📈 Trades: {m_p['total_trades']}\n"
        f"🎯 Winrate: {m_p['winrate_pct']}%\n"
        f"💰 PF: {m_p['profit_factor']}\n"
        f"📐 Sharpe: {m_p['sharpe']}\n"
        f"📉 Max DD: {m_p['max_drawdown']}%\n"
        f"🎲 Expect: {m_p['expectancy']}%\n"
        f"📊 Avg Win: {m_p['avg_win']}% | Avg Loss: {m_p['avg_loss']}%\n\n"
        f"<b>═══ DIRECTION ═══</b>\n"
        f"🟢 LONG: {len(long_trades)} lệnh\n"
        f"🔴 SHORT: {len(short_trades)} lệnh\n"
    )
    if strat_lines:
        report += f"\n<b>═══ STRATEGY ═══</b>\n{strat_lines}"
    if best:
        report += f"\n<b>🏆 Best:</b> {best.symbol} {best.direction} {float(best.result_percent):+.2f}%\n"
    if worst:
        report += f"<b>💀 Worst:</b> {worst.symbol} {worst.direction} {float(worst.result_percent):+.2f}%\n"
    report += (
        f"\n<b>═══ TRẠNG THÁI ═══</b>\n"
        f"🟢 Open: {open_count}\n"
        f"⏳ Pending: {pending_count}\n"
        f"💵 Equity: ${m_a['final_equity']}\n"
    )
    if anomalies:
        report += f"\n<b>═══ CẢNH BÁO / BẤT THƯỜNG ═══</b>\n"
        for item in anomalies:
            report += f"⚠️ {item}\n"
    return report


def _generate_agent_prompt(summary: str, anomalies: List[str]) -> str:
    prompt = (
        "Bạn là chuyên gia phân tích giao dịch định lượng. "
        "Dưới đây là báo cáo hiệu suất giao dịch. Hãy tóm tắt lại, giải thích xu hướng chính, nêu ra các cảnh báo quan trọng và chỉ ra nguyên nhân bất thường có thể. "
        "Trả lời ngắn gọn, rõ ràng, bằng tiếng Việt."
        "\n\nBÁO CÁO:\n" + summary + "\n"
    )
    if anomalies:
        prompt += "\nCác điểm cảnh báo:\n" + "\n".join(anomalies) + "\n"
    prompt += (
        "\nYêu cầu:\n"
        "1. Tóm tắt kết quả chính.\n"
        "2. Giải thích xu hướng chính.\n"
        "3. Cảnh báo yếu tố rủi ro.\n"
        "4. Chỉ ra nguyên nhân bất thường và đề xuất điểm cần chú ý."
    )
    return prompt


def _ask_agent(prompt: str) -> Optional[str]:
    response = ask_groq(prompt)
    if response:
        return response
    response = ask_gemini(prompt)
    return response


def generate_agent_report(report_type: str, days: int, title: str) -> str:
    db = SessionLocal()
    now = utc_now()
    cutoff = now - timedelta(days=days)
    period_trades = db.query(Signal).filter(
        Signal.status.in_(["WIN", "LOSS"]),
        Signal.exit_time >= cutoff,
    ).order_by(Signal.exit_time.asc()).all()
    all_trades = db.query(Signal).filter(Signal.status.in_(["WIN", "LOSS"])) .all()
    open_count = db.query(Signal).filter(Signal.status == "OPEN").count()
    pending_count = db.query(PendingSignal).filter(PendingSignal.status == "WAIT").count()
    db.close()

    m_p = _metrics(period_trades)
    m_a = _metrics(all_trades)
    long_trades = [t for t in period_trades if t.direction == "LONG"]
    short_trades = [t for t in period_trades if t.direction == "SHORT"]

    strat_groups = {}
    for t in period_trades:
        strat_groups.setdefault(t.strategy_name or "unknown", []).append(t)
    strat_lines = ""
    for name, group in strat_groups.items():
        sm = _metrics(group)
        strat_lines += f"  {name}: {sm['total_trades']} lệnh, WR={sm['winrate_pct']}%\n"

    sorted_trades = sorted(period_trades, key=lambda t: float(t.result_percent or 0), reverse=True)
    best = sorted_trades[0] if sorted_trades else None
    worst = sorted_trades[-1] if sorted_trades else None

    date_range = (
        f"{to_vn_str(cutoff, '%Y-%m-%d')} → "
        f"{to_vn_str(now, '%Y-%m-%d')} (GMT+7)"
    )

    anomalies = _detect_anomalies(period_trades, all_trades, pending_count)
    base_report = _compose_base_report(title, report_type, date_range, m_p, m_a, long_trades, short_trades, strat_lines, best, worst, open_count, pending_count, anomalies)

    ai_summary = None
    prompt = _generate_agent_prompt(base_report, anomalies)
    ai_summary = _ask_agent(prompt)
    if ai_summary:
        report = f"{base_report}\n\n<b>═══ TÓM TẮT AI ═══</b>\n{ai_summary}"
    else:
        report = f"{base_report}\n\n⚠️ AI không khả dụng, gửi báo cáo cơ bản." 

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


def send_agent_daily():
    report = generate_agent_report("daily", 1, "📊 DAILY AGENT REPORT")
    send_telegram(report)
    return report


def send_agent_weekly():
    report = generate_agent_report("weekly", 7, "📊 WEEKLY AGENT REPORT")
    send_telegram(report)
    return report


def send_agent_monthly():
    report = generate_agent_report("monthly", 30, "📊 MONTHLY AGENT REPORT")
    send_telegram(report)
    return report
