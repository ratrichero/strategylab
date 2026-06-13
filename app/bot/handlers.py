"""Unified Telegram Bot Handlers — Full admin + live controls"""
import json
from telegram import Update, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from app.services.config_service import get_runtime_config, update_runtime_config
from app.db.session import SessionLocal
from app.db.models import Signal, PendingSignal
from app.services.price_feed import get_all_current_prices
from app.core.trading_mode import get_current_mode


def start_handler(update: Update, context: CallbackContext):
    mode = get_current_mode()
    mode_icon = {"PAPER":"📋","TESTNET":"🧪","LIVE":"💰"}.get(mode.value,"📋")
    update.message.reply_text(
        f"🤖 <b>Quant Research Lab v2.0</b>\n{mode_icon} Mode: {mode.value}\n\nChọn chức năng:",
        parse_mode=ParseMode.HTML, reply_markup=_main_menu())


def status_handler(update: Update, context: CallbackContext):
    cfg = get_runtime_config(); mode = get_current_mode()
    from app.services.price_feed import get_price_feed
    feed = get_price_feed().get_stats()
    with SessionLocal() as db:
        oc = db.query(Signal).filter(Signal.status=="OPEN").count()
        pc = db.query(PendingSignal).filter(PendingSignal.status=="WAIT").count()
    active = cfg.get("ACTIVE_STRATEGIES","candlestick")
    mode_icon = {"PAPER":"📋","TESTNET":"🧪","LIVE":"💰"}.get(mode.value,"📋")
    msg = (f"<b>📊 SYSTEM STATUS</b>\n\n"
           f"Mode: {mode_icon} <b>{mode.value}</b>\n"
           f"Scheduler: {'🟢' if cfg.get('ENABLE_SCHEDULER') else '🔴'}\n"
           f"Feed: {'🟢 '+feed['mode'] if feed['healthy'] else '🔴 UNHEALTHY'}\n"
           f"Symbols: {feed['symbols_count']}\n\n"
           f"🟢 Open: {oc}\n⏳ Pending: {pc}\n\n"
           f"Strategies: {active}\nScore: {cfg.get('SCORE_THRESHOLD',5)}\n"
           f"Top: {cfg.get('TOP_LIMIT',400)}")
    update.message.reply_text(msg, parse_mode=ParseMode.HTML)


def trades_handler(update: Update, context: CallbackContext):
    with SessionLocal() as db:
        open_t = db.query(Signal).filter(Signal.status=="OPEN").order_by(Signal.created_at.desc()).all()
        pend   = db.query(PendingSignal).filter(PendingSignal.status=="WAIT").order_by(PendingSignal.created_at.desc()).limit(10).all()
    prices = get_all_current_prices(); lines = []
    if open_t:
        lines.append("<b>🟢 OPEN</b>")
        for t in open_t[:10]:
            cur = prices.get(t.symbol,0); entry = float(t.entry_price)
            pnl = ((cur-entry)/entry*100 if t.direction=="LONG" else (entry-cur)/entry*100) if cur else 0
            lines.append(f"  {t.symbol} {t.direction} {t.timeframe} [{t.strategy_name}] → {pnl:+.2f}%")
    if pend:
        lines.append("\n<b>⏳ PENDING</b>")
        for p in pend[:5]:
            lines.append(f"  {p.symbol} {p.direction} {p.timeframe} @ {p.trigger_price:.4f}")
    if not lines: lines.append("📭 Không có lệnh")
    update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


def performance_handler(update: Update, context: CallbackContext):
    from app.analytics.performance_engine import calculate_performance
    with SessionLocal() as db:
        trades = db.query(Signal).filter(Signal.status.in_(["WIN","LOSS"])).order_by(Signal.candle_time.asc()).all()
    m = calculate_performance(trades)
    msg = (f"<b>📊 PERFORMANCE</b>\n\nTotal: {m['total_trades']}\nWinrate: {m['winrate_percent']}%\n"
           f"PF: {m['profit_factor']}\nSharpe: {m['sharpe_ratio']}\nMax DD: {m['max_drawdown_percent']}%\n"
           f"Expect: {m['expectancy_percent']}%\nEquity: ${m['final_equity']}\n"
           f"Win Streak: {m['max_consecutive_wins']}\nLoss Streak: {m['max_consecutive_losses']}")
    update.message.reply_text(msg, parse_mode=ParseMode.HTML)


def filter_handler(update: Update, context: CallbackContext):
    cfg = get_runtime_config(); otf = cfg.get("OPEN_TRADE_FILTER",{"enabled":False})
    enabled = otf.get("enabled",False); identity = otf.get("identity",{})
    dirs = identity.get("directions",["LONG","SHORT"]); strats = identity.get("strategies",[]) or ["All"]
    msg = (f"<b>🎯 OPEN TRADE FILTER</b>\n\nStatus: {'🟢 ACTIVE' if enabled else '🔴 OFF'}\n\n"
           f"Direction: {' | '.join(dirs)}\nStrategies: {', '.join(strats)}\n"
           f"Min Score: {otf.get('score',{}).get('min_overall',5)}\n"
           f"Max Concurrent: {otf.get('position',{}).get('max_concurrent_trades',20)}")
    update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=_filter_menu())


def config_handler(update: Update, context: CallbackContext):
    cfg = get_runtime_config()
    msg = (f"<b>⚙️ CONFIG</b>\n\nScheduler: {'🟢' if cfg.get('ENABLE_SCHEDULER') else '🔴'}\n"
           f"Monitor: {'🟢' if cfg.get('ENABLE_MONITOR') else '🔴'}\n"
           f"MTF: {'🟢' if cfg.get('MTF_ENABLED') else '🔴'}\n\n"
           f"Score: {cfg.get('SCORE_THRESHOLD')}\nAI: {cfg.get('AI_THRESHOLD')}\n"
           f"Top: {cfg.get('TOP_LIMIT')}\nCooldown: {cfg.get('COOLDOWN_HOURS')}h\n"
           f"Engine: {cfg.get('ENGINE_VERSION')}")
    update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=_config_menu())


def set_handler(update: Update, context: CallbackContext):
    ALLOWED = {"SCORE_THRESHOLD","TOP_LIMIT","AI_THRESHOLD","COOLDOWN_HOURS","MTF_ENABLED",
               "ENABLE_SCHEDULER","ENABLE_MONITOR","BODY_RATIO_THRESHOLD","VOLUME_MULTIPLIER",
               "ATR_RATIO_MIN","ENGINE_VERSION"}
    args = context.args
    if len(args) < 2:
        update.message.reply_text(f"Usage: /set KEY VALUE\n\nKeys: {', '.join(sorted(ALLOWED))}"); return
    key = args[0].upper(); value = " ".join(args[1:])
    if key not in ALLOWED:
        update.message.reply_text(f"❌ Key không hợp lệ: {key}"); return
    try: update_runtime_config({key: value}); update.message.reply_text(f"✅ {key} = {value}")
    except Exception as e: update.message.reply_text(f"❌ {e}")


def mode_handler(update: Update, context: CallbackContext):
    mode = get_current_mode(); args = context.args
    if args:
        new = args[0].upper()
        if new not in ["PAPER","TESTNET","LIVE"]:
            update.message.reply_text("❌ Use: /mode PAPER|TESTNET|LIVE"); return
        if new == "LIVE":
            update.message.reply_text(
                "⚠️ <b>WARNING:</b> LIVE mode uses REAL MONEY!\n\n"
                "Send /mode_confirm_live to proceed.",
                parse_mode=ParseMode.HTML); return
        update_runtime_config({"TRADING_MODE": new})
        from app.core.trading_mode import get_trading_mode
        get_trading_mode().invalidate_cache()
        update.message.reply_text(f"✅ Mode: {new}"); return
    icon = {"PAPER":"📋","TESTNET":"🧪","LIVE":"💰"}.get(mode.value,"❓")
    update.message.reply_text(f"Mode: {icon} <b>{mode.value}</b>\nTo change: /mode PAPER|TESTNET|LIVE",
                              parse_mode=ParseMode.HTML)


def strategies_handler(update: Update, context: CallbackContext):
    from app.strategies.registry import list_all
    cfg = get_runtime_config()
    active = [s.strip() for s in cfg.get("ACTIVE_STRATEGIES","candlestick").split(",")]
    lines = ["<b>⚙️ STRATEGIES</b>\n"]
    for name in list_all():
        lines.append(f"{'🟢' if name in active else '⚪'} {name}")
    update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
                              reply_markup=_strategy_menu(list_all(), active))


def cancel_pending_handler(update: Update, context: CallbackContext):
    with SessionLocal() as db:
        count = db.query(PendingSignal).filter(PendingSignal.status=="WAIT").update(
            {"status":"CANCELLED","rejection_reason":"manual_telegram"})
        db.commit()
    update.message.reply_text(f"🚫 Cancelled {count} pending signals.")


def retrain_handler(update: Update, context: CallbackContext):
    update.message.reply_text("🔄 Retraining...")
    from app.services.model_retrainer import retrain_model
    result = retrain_model()
    if result.get("status") == "success":
        msg = f"✅ Retrain OK\nAUC: {result.get('avg_auc',0):.4f}\nSamples: {result.get('train_size',0)}"
    elif result.get("status") == "skipped": msg = f"⏭ Skipped: {result.get('reason')}"
    else: msg = f"❌ {result.get('message',result.get('reason','unknown'))}"
    update.message.reply_text(msg)


def report_handler(update: Update, context: CallbackContext):
    args = context.args; rtype = args[0].lower() if args else "daily"
    if rtype not in ["daily","weekly","monthly"]:
        update.message.reply_text("Usage: /report daily|weekly|monthly"); return
    update.message.reply_text(f"📊 Generating {rtype} report...")
    from app.services.report_service import send_daily, send_weekly, send_monthly
    {"daily":send_daily,"weekly":send_weekly,"monthly":send_monthly}[rtype]()


def ml_status_handler(update: Update, context: CallbackContext):
    from app.ml.predict import _engine
    from app.ml.feature_registry import get_feature_count, FEATURE_VERSION
    from app.ml.evaluate import evaluate_recent
    loaded = _engine._get_model() is not None
    ev = evaluate_recent(days=30)
    msg = f"<b>🤖 ML STATUS</b>\n\nModel: {'✅' if loaded else '❌'}\nFeatures: {get_feature_count()} v{FEATURE_VERSION}\n"
    if "error" not in ev:
        msg += f"\n30d: {ev['total_signals']} sig | AUC={ev['auc']:.4f} | WR={ev['overall_winrate']*100:.1f}%"
    update.message.reply_text(msg, parse_mode=ParseMode.HTML)


def text_handler(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    if context.user_data.get("awaiting_coin"):
        symbol = text.upper()
        if not symbol.endswith("USDT"): symbol += "USDT"
        context.user_data["awaiting_coin"] = False
        from app.services.advanced_analysis_service import analyze_advanced
        cfg = get_runtime_config(); tf = cfg.get("TIMEFRAME","1h")
        res = analyze_advanced(symbol, tf)
        if "error" in res: update.message.reply_text(f"❌ {res['error']}"); return
        l = res["long"]; s = res["short"]
        bias = "🟢 LONG" if l["score"]>s["score"] else "🔴 SHORT"
        msg = (f"<b>{symbol} | {tf}</b>\nRegime: {res['regime']}\nATR%: {res['atr_pct']}%\n\n"
               f"🟢 LONG: {l['score']}\n🔴 SHORT: {s['score']}\nBias: <b>{bias}</b>")
        update.message.reply_text(msg, parse_mode=ParseMode.HTML); return
    if context.user_data.get("ai_mode"):
        from app.services.llm_router import ask_gemini, ask_groq
        answer = ask_gemini(f"Trả lời ngắn gọn:\n{text}") or ask_groq(f"Trả lời ngắn gọn:\n{text}")
        update.message.reply_text(answer or "⚠️ AI unavailable."); return


def button_handler(update: Update, context: CallbackContext):
    q = update.callback_query; q.answer(); data = q.data
    if data == "back_main": q.edit_message_text("Chọn chức năng:", reply_markup=_main_menu())
    elif data == "filter_on": _update_otf({"enabled":True}); q.edit_message_text("✅ Filter ON", reply_markup=_filter_menu())
    elif data == "filter_off": _update_otf({"enabled":False}); q.edit_message_text("⏸ Filter OFF", reply_markup=_filter_menu())
    elif data == "filter_long": _update_otf_id({"directions":["LONG"]}); q.edit_message_text("🟢 LONG only", reply_markup=_filter_menu())
    elif data == "filter_short": _update_otf_id({"directions":["SHORT"]}); q.edit_message_text("🔴 SHORT only", reply_markup=_filter_menu())
    elif data == "filter_both": _update_otf_id({"directions":["LONG","SHORT"]}); q.edit_message_text("🟡 Both", reply_markup=_filter_menu())
    elif data == "toggle_scheduler": _toggle("ENABLE_SCHEDULER"); cfg = get_runtime_config(True); q.edit_message_text(f"Scheduler: {'🟢' if cfg['ENABLE_SCHEDULER'] else '🔴'}", reply_markup=_config_menu())
    elif data == "toggle_monitor": _toggle("ENABLE_MONITOR"); cfg = get_runtime_config(True); q.edit_message_text(f"Monitor: {'🟢' if cfg['ENABLE_MONITOR'] else '🔴'}", reply_markup=_config_menu())
    elif data == "toggle_mtf": _toggle("MTF_ENABLED"); cfg = get_runtime_config(True); q.edit_message_text(f"MTF: {'🟢' if cfg['MTF_ENABLED'] else '🔴'}", reply_markup=_config_menu())
    elif data.startswith("toggle_strategy_"):
        name = data.replace("toggle_strategy_",""); _toggle_strategy(name)
        from app.strategies.registry import list_all
        cfg = get_runtime_config(True); active = [s.strip() for s in cfg.get("ACTIVE_STRATEGIES","candlestick").split(",")]
        q.edit_message_text(f"Toggled '{name}'\nActive: {', '.join(active)}", reply_markup=_strategy_menu(list_all(), active))
    elif data == "ai_chat": context.user_data["ai_mode"] = True; q.edit_message_text("🤖 AI Chat ON. Gửi câu hỏi. /start để thoát.")
    elif data == "analyze": context.user_data["awaiting_coin"] = True; q.edit_message_text("✏ Nhập mã coin (btc, eth...):")
    elif data == "close_all_trades":
        _close_all_trades(q)
    elif data.startswith("close_trade_"):
        trade_id = int(data.replace("close_trade_",""))
        _close_single_trade(q, trade_id)


def _close_all_trades(query):
    """Emergency close tất cả open trades."""
    with SessionLocal() as db:
        open_trades = db.query(Signal).filter(Signal.status == "OPEN").all()
        if not open_trades:
            query.edit_message_text("📭 Không có lệnh đang mở."); return
        prices = get_all_current_prices()
        from app.services.trade_close_service import close_trade
        count = 0
        for trade in open_trades:
            current = prices.get(trade.symbol)
            if current:
                close_trade(db, trade, current, "MANUAL")
                count += 1
        db.commit()
    query.edit_message_text(f"🛑 Đã đóng {count} lệnh.")


def _close_single_trade(query, trade_id):
    with SessionLocal() as db:
        trade = db.query(Signal).get(trade_id)
        if not trade or trade.status != "OPEN":
            query.edit_message_text("❌ Lệnh không tồn tại hoặc đã đóng."); return
        prices = get_all_current_prices()
        current = prices.get(trade.symbol)
        if not current:
            query.edit_message_text("❌ Không lấy được giá."); return
        from app.services.trade_close_service import close_trade
        close_trade(db, trade, current, "MANUAL")
        db.commit()
    query.edit_message_text(f"✅ Đã đóng {trade.symbol} {trade.direction} @ {current:.4f}")


# ── Menus ────────────────────────────────────────────────

def _main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 Phân tích Coin", callback_data="analyze")],
        [InlineKeyboardButton("🎯 Trade Filter", callback_data="back_filter")],
        [InlineKeyboardButton("⚙️ Config", callback_data="back_config")],
        [InlineKeyboardButton("🤖 AI Chat", callback_data="ai_chat")],
        [InlineKeyboardButton("🛑 Close All Trades", callback_data="close_all_trades")],
    ]
    return InlineKeyboardMarkup(keyboard)


def _filter_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ ON", callback_data="filter_on"),
         InlineKeyboardButton("⏸ OFF", callback_data="filter_off")],
        [InlineKeyboardButton("🟢 LONG", callback_data="filter_long"),
         InlineKeyboardButton("🔴 SHORT", callback_data="filter_short")],
        [InlineKeyboardButton("🟡 Both", callback_data="filter_both")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back_main")],
    ])


def _config_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Scheduler", callback_data="toggle_scheduler")],
        [InlineKeyboardButton("🔄 Monitor", callback_data="toggle_monitor")],
        [InlineKeyboardButton("🔄 MTF", callback_data="toggle_mtf")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back_main")],
    ])


def _strategy_menu(all_s, active):
    keyboard = [[InlineKeyboardButton(
        f"{'✅' if n in active else '⬜'} {n}", callback_data=f"toggle_strategy_{n}"
    )] for n in all_s]
    keyboard.append([InlineKeyboardButton("⬅️ Menu", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)


# ── Helpers ──────────────────────────────────────────────

def _toggle(key):
    cfg = get_runtime_config(); cur = cfg.get(key, True)
    update_runtime_config({key: "false" if cur else "true"})

def _toggle_strategy(name):
    cfg = get_runtime_config()
    active = [s.strip() for s in cfg.get("ACTIVE_STRATEGIES","candlestick").split(",")]
    if name in active: active.remove(name)
    else: active.append(name)
    if not active: active = ["candlestick"]
    update_runtime_config({"ACTIVE_STRATEGIES": ",".join(active)})

def _update_otf(updates):
    cfg = get_runtime_config(True)
    otf = cfg.get("OPEN_TRADE_FILTER",{"enabled":False})
    otf.update(updates)
    update_runtime_config({"OPEN_TRADE_FILTER": json.dumps(otf)})

def _update_otf_id(updates):
    cfg = get_runtime_config(True)
    otf = cfg.get("OPEN_TRADE_FILTER",{"enabled":True})
    otf.setdefault("identity",{}).update(updates)
    update_runtime_config({"OPEN_TRADE_FILTER": json.dumps(otf)})
