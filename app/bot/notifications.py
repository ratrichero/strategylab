from telegram import Bot, ParseMode
from app.core.config import TELEGRAM_CHAT_ID

_bot = None

def setup(bot: Bot):
    global _bot; _bot = bot

def _send(text: str, parse_mode=ParseMode.HTML):
    if not _bot or not TELEGRAM_CHAT_ID: return
    try: _bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode=parse_mode)
    except Exception as e: print(f"[NOTIFY] {e}")
