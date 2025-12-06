import requests
from ..config import DISCORD_WEBHOOK_URL

class DiscordNotifier:
    def __init__(self, webhook_url=DISCORD_WEBHOOK_URL):
        self.webhook_url = webhook_url

    def send_alert(self, message: str):
        if not self.webhook_url:
            print(f"[Discord] Config missing. Alert not sent.")
            return

        try:
            # Discord webhooks support 'content' for the message body
            payload = {
                "content": message
            }
            requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception as e:
            print(f"[Discord] Error sending message: {e}")
