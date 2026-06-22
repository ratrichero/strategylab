import requests
from app.core.config import get_telegram_chat_id, get_telegram_token


def send_telegram(message):
    token = get_telegram_token()
    chat_id = get_telegram_chat_id()
    if not token or not chat_id:
        print("Telegram not configured")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(
        url,
        json={"chat_id": chat_id, "parse_mode": "HTML", "text": message},
        timeout=10,
    )
