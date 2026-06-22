"""Unified Telegram bot handlers: admin commands and live controls."""
import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, Update
from telegram.ext import CallbackContext

from app.core.trading_mode import get_current_mode
from app.db.models import PendingSignal, Signal
from app.db.session import SessionLocal
from app.services.config_service import get_runtime_config, update_runtime_config
from app.services.price_feed import get_all_current_prices


def _mode_icon(mode: str) -> str:
    return {"PAPER": "📋", "TESTNET": "🧪", "LIVE": "💰"}.get(str(mode), "📋")


def start_handler(update: Update, context: CallbackContext):
    mode = get_current_mode()
    update.message.reply_text(
        f"🤖 <b>Quant Research Lab</b>\n"
        f"{_mode_icon(mode.value)} Chế độ: <b>{mode.value}</b>\n\n"
        f"Chọn chức năng bạn muốn dùng:",
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu(),
    )


def status_handler(update: Update, context: CallbackContext):
    cfg = get_runtime_config()
    mode = get_current_mode()
    from app.services.price_feed import get_price_feed

    feed = get_price_feed().get_stats()
    with SessionLocal() as db:
        open_count = db.query(Signal).filter(Signal.status == "OPEN").count()
        pending_count = db.query(PendingSignal).filter(PendingSignal.status == "WAIT").count()

    msg = (
        f"📊 <b>Trạng thái hệ thống</b>\n\n"
        f"{_mode_icon(mode.value)} Chế độ: <b>{mode.value}</b>\n"
        f"⏱ Scheduler: {'✅ bật' if cfg.get('ENABLE_SCHEDULER') else '⏸ tắt'}\n"
        f"🔍 Monitor: {'✅ bật' if cfg.get('ENABLE_MONITOR') else '⏸ tắt'}\n"
        f"📡 Price feed: {'✅ ' + feed['mode'] if feed['healthy'] else '⚠️ lỗi'}\n"
        f"🪙 Symbols: {feed['symbols_count']}\n\n"
        f"📈 Lệnh đang mở: <b>{open_count}</b>\n"
        f"⏳ Lệnh chờ: <b>{pending_count}</b>\n\n"
        f"🧩 Strategy: {cfg.get('ACTIVE_STRATEGIES', 'candlestick')}\n"
        f"⭐ Score min: {cfg.get('SCORE_THRESHOLD', 5)}\n"
        f"🎯 Top limit: {cfg.get('TOP_LIMIT', 400)}"
    )
    update.message.reply_text(msg, parse_mode=ParseMode.HTML)


def trades_handler(update: Update, context: CallbackContext):
    with SessionLocal() as db:
        open_trades = db.query(Signal).filter(Signal.status == "OPEN").order_by(Signal.created_at.desc()).all()
        pendings = db.query(PendingSignal).filter(PendingSignal.status == "WAIT").order_by(PendingSignal.created_at.desc()).limit(10).all()

    prices = get_all_current_prices()
    lines = []
    if open_trades:
        lines.append("📈 <b>Lệnh đang mở</b>")
        for trade in open_trades[:10]:
            current = prices.get(trade.symbol, 0)
            entry = float(trade.entry_price or 0)
            pnl = 0
            if current and entry:
                pnl = ((current - entry) / entry * 100) if trade.direction == "LONG" else ((entry - current) / entry * 100)
            lines.append(f"🪙 {trade.symbol} {trade.direction} {trade.timeframe} [{trade.strategy_name}] → {pnl:+.2f}%")

    if pendings:
        lines.append("\n⏳ <b>Lệnh chờ khớp</b>")
        for pending in pendings[:5]:
            lines.append(f"🎯 {pending.symbol} {pending.direction} {pending.timeframe} @ {float(pending.trigger_price):.4f}")

    if not lines:
        lines.append("📭 Hiện chưa có lệnh nào.")

    update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


def performance_handler(update: Update, context: CallbackContext):
    from app.analytics.performance_engine import calculate_performance

    with SessionLocal() as db:
        trades = db.query(Signal).filter(Signal.status.in_(["WIN", "LOSS"])).order_by(Signal.candle_time.asc()).all()

    metrics = calculate_performance(trades)
    msg = (
        f"📈 <b>Hiệu suất giao dịch</b>\n\n"
        f"🔢 Tổng lệnh: {metrics['total_trades']}\n"
        f"🎯 Winrate: {metrics['winrate_percent']}%\n"
        f"🧮 Profit Factor: {metrics['profit_factor']}\n"
        f"📐 Sharpe: {metrics['sharpe_ratio']}\n"
        f"📉 Max DD: {metrics['max_drawdown_percent']}%\n"
        f"📊 Expectancy: {metrics['expectancy_percent']}%\n"
        f"💵 Equity cuối: ${metrics['final_equity']}\n"
        f"🔥 Chuỗi thắng dài nhất: {metrics['max_consecutive_wins']}\n"
        f"🧊 Chuỗi thua dài nhất: {metrics['max_consecutive_losses']}"
    )
    update.message.reply_text(msg, parse_mode=ParseMode.HTML)


def filter_handler(update: Update, context: CallbackContext):
    cfg = get_runtime_config()
    otf = cfg.get("OPEN_TRADE_FILTER", {"enabled": False})
    identity = otf.get("identity", {})
    dirs = identity.get("directions", ["LONG", "SHORT"])
    strategies = identity.get("strategies", []) or ["Tất cả"]
    msg = (
        f"🎯 <b>Open Trade Filter</b>\n\n"
        f"Trạng thái: {'✅ đang bật' if otf.get('enabled', False) else '⏸ đang tắt'}\n\n"
        f"🧭 Hướng lệnh: {' | '.join(dirs)}\n"
        f"🧩 Strategy: {', '.join(strategies)}\n"
        f"⭐ Score min: {otf.get('score', {}).get('min_overall', 5)}\n"
        f"📊 Max concurrent: {otf.get('position', {}).get('max_concurrent_trades', 20)}"
    )
    update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=_filter_menu())


def config_handler(update: Update, context: CallbackContext):
    cfg = get_runtime_config()
    msg = (
        f"⚙️ <b>Cấu hình runtime</b>\n\n"
        f"⏱ Scheduler: {'✅ bật' if cfg.get('ENABLE_SCHEDULER') else '⏸ tắt'}\n"
        f"🔍 Monitor: {'✅ bật' if cfg.get('ENABLE_MONITOR') else '⏸ tắt'}\n"
        f"🧭 MTF: {'✅ bật' if cfg.get('MTF_ENABLED') else '⏸ tắt'}\n\n"
        f"⭐ Score: {cfg.get('SCORE_THRESHOLD')}\n"
        f"🤖 AI: {cfg.get('AI_THRESHOLD')}\n"
        f"🎯 Top: {cfg.get('TOP_LIMIT')}\n"
        f"⏳ Cooldown: {cfg.get('COOLDOWN_HOURS')}h\n"
        f"🔧 Engine: {cfg.get('ENGINE_VERSION')}"
    )
    update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=_config_menu())


def set_handler(update: Update, context: CallbackContext):
    allowed = {
        "SCORE_THRESHOLD", "TOP_LIMIT", "AI_THRESHOLD", "COOLDOWN_HOURS",
        "MTF_ENABLED", "ENABLE_SCHEDULER", "ENABLE_MONITOR",
        "BODY_RATIO_THRESHOLD", "VOLUME_MULTIPLIER", "ATR_RATIO_MIN",
        "ENGINE_VERSION",
    }
    args = context.args
    if len(args) < 2:
        update.message.reply_text(f"📝 Cách dùng: /set KEY VALUE\n\nKey hợp lệ: {', '.join(sorted(allowed))}")
        return

    key = args[0].upper()
    value = " ".join(args[1:])
    if key not in allowed:
        update.message.reply_text(f"❌ Key không hợp lệ: {key}")
        return

    try:
        update_runtime_config({key: value})
        update.message.reply_text(f"✅ Đã cập nhật <b>{key}</b> = <code>{value}</code>", parse_mode=ParseMode.HTML)
    except Exception as exc:
        update.message.reply_text(f"⚠️ Không cập nhật được: {exc}")


def mode_handler(update: Update, context: CallbackContext):
    mode = get_current_mode()
    args = context.args
    if args:
        new_mode = args[0].upper()
        if new_mode not in ["PAPER", "TESTNET", "LIVE"]:
            update.message.reply_text("📝 Cách dùng: /mode PAPER|TESTNET|LIVE")
            return
        if new_mode == "LIVE":
            update.message.reply_text(
                "⚠️ <b>Xác nhận LIVE</b>\n\nLIVE là chế độ dùng tiền thật. Gửi /mode_confirm_live nếu bạn chắc chắn muốn bật.",
                parse_mode=ParseMode.HTML,
            )
            return
        update_runtime_config({"TRADING_MODE": new_mode})
        from app.core.trading_mode import get_trading_mode

        get_trading_mode().invalidate_cache()
        update.message.reply_text(f"✅ Đã chuyển chế độ sang <b>{new_mode}</b>", parse_mode=ParseMode.HTML)
        return

    update.message.reply_text(
        f"{_mode_icon(mode.value)} Chế độ hiện tại: <b>{mode.value}</b>\nĐổi bằng: /mode PAPER|TESTNET|LIVE",
        parse_mode=ParseMode.HTML,
    )


def strategies_handler(update: Update, context: CallbackContext):
    from app.strategies.registry import list_all

    cfg = get_runtime_config()
    active = [s.strip() for s in cfg.get("ACTIVE_STRATEGIES", "candlestick").split(",")]
    lines = ["🧩 <b>Strategies</b>\n"]
    for name in list_all():
        lines.append(f"{'✅' if name in active else '◻'} {name}")
    update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=_strategy_menu(list_all(), active))


def cancel_pending_handler(update: Update, context: CallbackContext):
    with SessionLocal() as db:
        count = db.query(PendingSignal).filter(PendingSignal.status == "WAIT").update(
            {"status": "CANCELLED", "rejection_reason": "manual_telegram"}
        )
        db.commit()
    update.message.reply_text(f"🚫 Đã hủy {count} lệnh chờ.")


def retrain_handler(update: Update, context: CallbackContext):
    update.message.reply_text("🤖 Đang retrain model...")
    from app.services.model_retrainer import retrain_model

    result = retrain_model()
    if result.get("status") == "success":
        msg = f"✅ Retrain xong\nAUC: {result.get('avg_auc', 0):.4f}\nSamples: {result.get('train_size', 0)}"
    elif result.get("status") == "skipped":
        msg = f"⏸ Bỏ qua: {result.get('reason')}"
    else:
        msg = f"⚠️ {result.get('message', result.get('reason', 'không rõ lỗi'))}"
    update.message.reply_text(msg)


def report_handler(update: Update, context: CallbackContext):
    args = context.args
    rtype = args[0].lower() if args else "daily"
    if rtype not in ["daily", "weekly", "monthly"]:
        update.message.reply_text("📝 Cách dùng: /report daily|weekly|monthly")
        return
    update.message.reply_text(f"📊 Đang tạo báo cáo {rtype}...")
    from app.services.report_service import send_daily, send_monthly, send_weekly

    {"daily": send_daily, "weekly": send_weekly, "monthly": send_monthly}[rtype]()


def agent_report_handler(update: Update, context: CallbackContext):
    args = context.args
    rtype = args[0].lower() if args else "daily"
    if rtype not in ["live", "daily", "weekly", "monthly"]:
        update.message.reply_text("📝 Cách dùng: /agent live|daily|weekly|monthly")
        return
    update.message.reply_text(f"🧠 Đang tạo báo cáo agent {rtype}...")
    from app.services.trading_agent_service import send_agent_daily, send_agent_live, send_agent_monthly, send_agent_weekly

    {"live": send_agent_live, "daily": send_agent_daily, "weekly": send_agent_weekly, "monthly": send_agent_monthly}[rtype]()


def ml_status_handler(update: Update, context: CallbackContext):
    from app.ml.evaluate import evaluate_recent
    from app.ml.feature_registry import FEATURE_VERSION, get_feature_count
    from app.ml.predict import _engine

    loaded = _engine._get_model() is not None
    ev = evaluate_recent(days=30)
    msg = f"🤖 <b>ML Status</b>\n\nModel: {'✅ đã load' if loaded else '⏸ chưa load'}\nFeatures: {get_feature_count()} v{FEATURE_VERSION}\n"
    if "error" not in ev:
        msg += f"\n30 ngày: {ev['total_signals']} tín hiệu | AUC={ev['auc']:.4f} | WR={ev['overall_winrate'] * 100:.1f}%"
    update.message.reply_text(msg, parse_mode=ParseMode.HTML)


def text_handler(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    if context.user_data.get("awaiting_coin"):
        symbol = text.upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        context.user_data["awaiting_coin"] = False
        from app.services.advanced_analysis_service import analyze_advanced

        cfg = get_runtime_config()
        timeframe = cfg.get("TIMEFRAME", "1h")
        result = analyze_advanced(symbol, timeframe)
        if "error" in result:
            update.message.reply_text(f"⚠️ {result['error']}")
            return
        long_side = result["long"]
        short_side = result["short"]
        bias = "🟢 LONG" if long_side["score"] > short_side["score"] else "🔴 SHORT"
        msg = (
            f"🔎 <b>{symbol} | {timeframe}</b>\nRegime: {result['regime']}\nATR%: {result['atr_pct']}%\n\n"
            f"🟢 LONG: {long_side['score']}\n🔴 SHORT: {short_side['score']}\nThiên hướng: <b>{bias}</b>"
        )
        update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    if context.user_data.get("ai_mode"):
        from app.services.llm_router import ask_gemini, ask_groq

        answer = ask_gemini(f"Trả lời ngắn gọn:\n{text}") or ask_groq(f"Trả lời ngắn gọn:\n{text}")
        update.message.reply_text(answer or "🤔 AI hiện chưa phản hồi được.")


def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    if data == "back_main":
        query.edit_message_text("Chọn chức năng:", reply_markup=_main_menu())
    elif data == "back_filter":
        cfg = get_runtime_config(True)
        otf = cfg.get("OPEN_TRADE_FILTER", {"enabled": False})
        query.edit_message_text(
            f"🎯 Open Trade Filter: {'✅ đang bật' if otf.get('enabled', False) else '⏸ đang tắt'}",
            reply_markup=_filter_menu(),
        )
    elif data == "back_config":
        query.edit_message_text("⚙️ Cấu hình runtime", reply_markup=_config_menu())
    elif data == "filter_on":
        _update_otf({"enabled": True})
        query.edit_message_text("✅ Filter đã bật", reply_markup=_filter_menu())
    elif data == "filter_off":
        _update_otf({"enabled": False})
        query.edit_message_text("⏸ Filter đã tắt", reply_markup=_filter_menu())
    elif data == "filter_long":
        _update_otf_id({"directions": ["LONG"]})
        query.edit_message_text("🟢 Chỉ LONG", reply_markup=_filter_menu())
    elif data == "filter_short":
        _update_otf_id({"directions": ["SHORT"]})
        query.edit_message_text("🔴 Chỉ SHORT", reply_markup=_filter_menu())
    elif data == "filter_both":
        _update_otf_id({"directions": ["LONG", "SHORT"]})
        query.edit_message_text("🔄 Cả LONG và SHORT", reply_markup=_filter_menu())
    elif data == "toggle_scheduler":
        _toggle("ENABLE_SCHEDULER")
        cfg = get_runtime_config(True)
        query.edit_message_text(f"⏱ Scheduler: {'✅ bật' if cfg['ENABLE_SCHEDULER'] else '⏸ tắt'}", reply_markup=_config_menu())
    elif data == "toggle_monitor":
        _toggle("ENABLE_MONITOR")
        cfg = get_runtime_config(True)
        query.edit_message_text(f"🔍 Monitor: {'✅ bật' if cfg['ENABLE_MONITOR'] else '⏸ tắt'}", reply_markup=_config_menu())
    elif data == "toggle_mtf":
        _toggle("MTF_ENABLED")
        cfg = get_runtime_config(True)
        query.edit_message_text(f"🧭 MTF: {'✅ bật' if cfg['MTF_ENABLED'] else '⏸ tắt'}", reply_markup=_config_menu())
    elif data.startswith("toggle_strategy_"):
        name = data.replace("toggle_strategy_", "")
        _toggle_strategy(name)
        from app.strategies.registry import list_all

        cfg = get_runtime_config(True)
        active = [s.strip() for s in cfg.get("ACTIVE_STRATEGIES", "candlestick").split(",")]
        query.edit_message_text(f"✅ Đã đổi strategy: {name}\nĐang bật: {', '.join(active)}", reply_markup=_strategy_menu(list_all(), active))
    elif data == "ai_chat":
        context.user_data["ai_mode"] = True
        query.edit_message_text("🧠 AI Chat đã bật. Gửi câu hỏi cho mình nhé. /start để thoát.")
    elif data == "analyze":
        context.user_data["awaiting_coin"] = True
        query.edit_message_text("🔎 Nhập mã coin, ví dụ: BTC, ETH, SOL...")
    elif data == "close_all_trades":
        _close_all_trades(query)
    elif data.startswith("close_trade_"):
        trade_id = int(data.replace("close_trade_", ""))
        _close_single_trade(query, trade_id)


def _close_all_trades(query):
    with SessionLocal() as db:
        open_trades = db.query(Signal).filter(Signal.status == "OPEN").all()
        if not open_trades:
            query.edit_message_text("📭 Không có lệnh đang mở.")
            return
        prices = get_all_current_prices()
        from app.services.trade_close_service import close_trade

        count = 0
        for trade in open_trades:
            current = prices.get(trade.symbol)
            if current:
                close_trade(db, trade, current, "MANUAL")
                count += 1
        db.commit()
    query.edit_message_text(f"🛑 Đã đóng {count} lệnh đang mở.")


def _close_single_trade(query, trade_id):
    with SessionLocal() as db:
        trade = db.query(Signal).get(trade_id)
        if not trade or trade.status != "OPEN":
            query.edit_message_text("⚠️ Lệnh không tồn tại hoặc đã đóng.")
            return
        prices = get_all_current_prices()
        current = prices.get(trade.symbol)
        if not current:
            query.edit_message_text("⚠️ Chưa lấy được giá hiện tại.")
            return
        from app.services.trade_close_service import close_trade

        close_trade(db, trade, current, "MANUAL")
        db.commit()
    query.edit_message_text(f"✅ Đã đóng {trade.symbol} {trade.direction} @ {float(current):.4f}")


def _main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Phân tích coin", callback_data="analyze")],
        [InlineKeyboardButton("🎯 Trade filter", callback_data="back_filter")],
        [InlineKeyboardButton("⚙️ Cấu hình", callback_data="back_config")],
        [InlineKeyboardButton("🧠 AI Chat", callback_data="ai_chat")],
        [InlineKeyboardButton("🛑 Đóng tất cả lệnh", callback_data="close_all_trades")],
    ])


def _filter_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Bật", callback_data="filter_on"), InlineKeyboardButton("⏸ Tắt", callback_data="filter_off")],
        [InlineKeyboardButton("🟢 LONG", callback_data="filter_long"), InlineKeyboardButton("🔴 SHORT", callback_data="filter_short")],
        [InlineKeyboardButton("🔄 Cả hai", callback_data="filter_both")],
        [InlineKeyboardButton("🏠 Menu", callback_data="back_main")],
    ])


def _config_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱ Scheduler", callback_data="toggle_scheduler")],
        [InlineKeyboardButton("🔍 Monitor", callback_data="toggle_monitor")],
        [InlineKeyboardButton("🧭 MTF", callback_data="toggle_mtf")],
        [InlineKeyboardButton("🏠 Menu", callback_data="back_main")],
    ])


def _strategy_menu(all_s, active):
    keyboard = [[InlineKeyboardButton(f"{'✅' if name in active else '◻'} {name}", callback_data=f"toggle_strategy_{name}")] for name in all_s]
    keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)


def _toggle(key):
    cfg = get_runtime_config()
    current = cfg.get(key, True)
    update_runtime_config({key: "false" if current else "true"})


def _toggle_strategy(name):
    cfg = get_runtime_config()
    active = [s.strip() for s in cfg.get("ACTIVE_STRATEGIES", "candlestick").split(",")]
    if name in active:
        active.remove(name)
    else:
        active.append(name)
    if not active:
        active = ["candlestick"]
    update_runtime_config({"ACTIVE_STRATEGIES": ",".join(active)})


def _update_otf(updates):
    cfg = get_runtime_config(True)
    otf = cfg.get("OPEN_TRADE_FILTER", {"enabled": False})
    otf.update(updates)
    update_runtime_config({"OPEN_TRADE_FILTER": json.dumps(otf)})


def _update_otf_id(updates):
    cfg = get_runtime_config(True)
    otf = cfg.get("OPEN_TRADE_FILTER", {"enabled": True})
    otf.setdefault("identity", {}).update(updates)
    update_runtime_config({"OPEN_TRADE_FILTER": json.dumps(otf)})
