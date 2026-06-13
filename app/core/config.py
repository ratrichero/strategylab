import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL         = os.getenv("DATABASE_URL")
TELEGRAM_TOKEN       = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_BASE         = "https://fapi.binance.com"
DEFAULT_ENGINE_VERSION = 2.0
