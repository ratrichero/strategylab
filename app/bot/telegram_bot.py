from telegram import BotCommand
from telegram.ext import (Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters)
from app.bot.notifications import setup as setup_notifications


def run_bot(token: str):
    from app.bot.handlers import (
        start_handler, status_handler, trades_handler, performance_handler,
        filter_handler, config_handler, set_handler, mode_handler,
        strategies_handler, cancel_pending_handler, retrain_handler,
        report_handler, agent_report_handler, ml_status_handler,
        text_handler, button_handler)

    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start",           start_handler))
    dp.add_handler(CommandHandler("status",          status_handler))
    dp.add_handler(CommandHandler("trades",          trades_handler))
    dp.add_handler(CommandHandler("performance",     performance_handler))
    dp.add_handler(CommandHandler("filter",          filter_handler))
    dp.add_handler(CommandHandler("config",          config_handler))
    dp.add_handler(CommandHandler("set",             set_handler))
    dp.add_handler(CommandHandler("mode",            mode_handler))
    dp.add_handler(CommandHandler("strategies",      strategies_handler))
    dp.add_handler(CommandHandler("cancel_pending",  cancel_pending_handler))
    dp.add_handler(CommandHandler("retrain",         retrain_handler))
    dp.add_handler(CommandHandler("report",          report_handler))
    dp.add_handler(CommandHandler("agent",           agent_report_handler))
    dp.add_handler(CommandHandler("ml",              ml_status_handler))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, text_handler))

    updater.bot.set_my_commands([
        BotCommand("start",         "🏠 Menu chính"),
        BotCommand("status",        "📊 Trạng thái hệ thống"),
        BotCommand("trades",        "📋 Lệnh đang mở"),
        BotCommand("performance",   "📈 Hiệu suất"),
        BotCommand("filter",        "🎯 Open Trade Filter"),
        BotCommand("config",        "⚙️ Runtime config"),
        BotCommand("set",           "✏️ /set KEY VALUE"),
        BotCommand("mode",          "🔄 Trading mode"),
        BotCommand("strategies",    "📋 Strategies"),
        BotCommand("cancel_pending","🚫 Cancel all pending"),
        BotCommand("retrain",       "🤖 Retrain ML"),
        BotCommand("report",        "📊 /report daily|weekly|monthly"),
        BotCommand("agent",         "🤖 /agent daily|weekly|monthly"),
        BotCommand("ml",            "🤖 ML status"),
    ])

    setup_notifications(updater.bot)
    print("🤖 Telegram Bot started (polling)...")
    updater.start_polling()
    return updater
