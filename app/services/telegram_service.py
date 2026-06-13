import requests
from app.core.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠ Telegram not configured")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID,"parse_mode": "HTML", "text": message})