"""Report Service - báo cáo ngày/tuần/tháng."""
from datetime import timedelta
import numpy as np
from app.db.session import SessionLocal
from app.db.models import Signal, PendingSignal
from app.services.telegram_service import send_telegram
from app.core.time_utils import utc_now, to_vn_str


def _metrics(trades):
    if not trades:
        return {"total_trades": 0, "wins": 0, "losses": 0, "winrate_pct": 0,
                "profit_factor": 0, "expectancy": 0, "sharpe": 0, "max_drawdown": 0, "final_equity": 10000}
    returns = np.array([float(t.result_percent or 0) for t in trades])
    wins = int((returns > 0).sum())
    losses = len(returns) - wins
    wr = wins / len(returns) * 100 if returns.size > 0 else 0
    gp = float(returns[returns > 0].sum()) if wins > 0 else 0
    gl = abs(float(returns[returns < 0].sum())) if losses > 0 else 1
    pf = round(gp / gl, 2) if gl > 0 else 0
    exp = round(float(returns.mean()), 4)
    sharpe = round(float(returns.mean() / (returns.std() + 1e-10) * np.sqrt(252)), 2)
    equity = 10000.0
    peak = equity
    max_dd = 0
    for r in returns:
        equity *= (1 + r / 100)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
    return {"total_trades": len(returns), "wins": wins, "losses": losses,
            "winrate_pct": round(wr, 1), "profit_factor": pf,
            "expectancy": round(exp * 100, 3), "sharpe": sharpe,
            "max_drawdown": round(max_dd, 2), "final_equity": round(equity, 2)}


def _generate(report_type, days, title):
    db = SessionLocal()
    now = utc_now()
    cutoff = now - timedelta(days=days)
    period_trades = db.query(Signal).filter(
        Signal.status.in_(["WIN", "LOSS"]),
        Signal.exit_time >= cutoff,
    ).order_by(Signal.exit_time.asc()).all()
    all_trades = db.query(Signal).filter(Signal.status.in_(["WIN", "LOSS"])).all()
    open_count = db.query(Signal).filter(Signal.status == "OPEN").count()
    pending_count = db.query(PendingSignal).filter(PendingSignal.status == "WAIT").count()
    db.close()

    m_p = _metrics(period_trades)
    m_a = _metrics(all_trades)
    long_trades = [t for t in period_trades if t.direction == "LONG"]
    short_trades = [t for t in period_trades if t.direction == "SHORT"]
    long_wr = sum(1 for t in long_trades if t.status == "WIN") / (len(long_trades) or 1) * 100
    short_wr = sum(1 for t in short_trades if t.status == "WIN") / (len(short_trades) or 1) * 100

    strat_groups = {}
    for t in period_trades:
        strat_groups.setdefault(t.strategy_name or "unknown", []).append(t)
    strat_lines = ""
    for name, group in strat_groups.items():
        sm = _metrics(group)
        strat_lines += f"  {name}: {sm['total_trades']}x WR={sm['winrate_pct']}%\n"

    sorted_t = sorted(period_trades, key=lambda t: float(t.result_percent or 0), reverse=True)
    best = sorted_t[0] if sorted_t else None
    worst = sorted_t[-1] if sorted_t else None

    date_range = (
        f"{to_vn_str(cutoff, '%Y-%m-%d')} → "
        f"{to_vn_str(now, '%Y-%m-%d')} (GMT+7)"
    )
    report = (
        f"<b>{title}</b>\n<i>{date_range}</i>\n\n"
        f"<b>📊 HIỆU SUẤT KỲ NÀY</b>\n"
        f"📈 Lệnh: {m_p['total_trades']}\n"
        f"🎯 Winrate: {m_p['winrate_pct']}%\n"
        f"💰 PF: {m_p['profit_factor']}\n"
        f"📐 Sharpe: {m_p['sharpe']}\n"
        f"📉 Max DD: {m_p['max_drawdown']}%\n"
        f"🎲 Expect: {m_p['expectancy']}%\n\n"
        f"<b>🧭 HƯỚNG LỆNH</b>\n"
        f"🟢 LONG: {len(long_trades)}x WR={long_wr:.1f}%\n"
        f"🔴 SHORT: {len(short_trades)}x WR={short_wr:.1f}%\n"
    )
    if strat_lines:
        report += f"\n<b>🧩 STRATEGY</b>\n{strat_lines}"
    if best:
        report += f"\n<b>🏆 Lệnh tốt nhất:</b> {best.symbol} {best.direction} {float(best.result_percent):+.2f}%\n"
    if worst:
        report += f"<b>📉 Lệnh yếu nhất:</b> {worst.symbol} {worst.direction} {float(worst.result_percent):+.2f}%\n"
    report += (
        f"\n<b>📌 TRẠNG THÁI</b>\n"
        f"🟢 Đang mở: {open_count}\n"
        f"⏳ Đang chờ: {pending_count}\n"
        f"💵 Equity: ${m_a['final_equity']}"
    )

    try:
        from sqlalchemy import text
        db2 = SessionLocal()
        db2.execute(
            text("INSERT INTO reports (report_type,period_start,period_end,content,created_at) VALUES (:rt,:ps,:pe,:c,NOW())"),
            {"rt": report_type, "ps": cutoff, "pe": now, "c": report},
        )
        db2.commit()
        db2.close()
    except Exception as e:
        print(f"[REPORT] DB save error: {e}")

    return report


def send_daily():
    report = _generate("daily", 1, "📊 BÁO CÁO NGÀY")
    send_telegram(report)
    return report


def send_weekly():
    report = _generate("weekly", 7, "📊 BÁO CÁO TUẦN")
    send_telegram(report)
    return report


def send_monthly():
    report = _generate("monthly", 30, "📊 BÁO CÁO THÁNG")
    send_telegram(report)
    return report
