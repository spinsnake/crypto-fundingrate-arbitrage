import requests
from ..config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

class TelegramNotifier:
    def __init__(self, token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_alert(self, message: str):
        if not self.token or not self.chat_id:
            print(f"[Telegram] Config missing. Alert not sent: {message}")
            return

        try:
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            requests.post(self.base_url, json=payload, timeout=5)
        except Exception as e:
            print(f"[Telegram] Error sending message: {e}")
