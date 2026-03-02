import time

import requests

from cibus_daily_buy.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, log


class OTPTimeoutError(Exception):
    """Raised when the user does not reply with an OTP within the deadline."""


def send_telegram(text: str) -> bool:
    """Send a message via Telegram bot. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10,
        )
        if not resp.ok:
            log.warning(f"Telegram sendMessage failed: {resp.text}")
            return False
        return True
    except Exception as e:
        log.warning(f"Telegram send error: {e}")
        return False


def ask_telegram(prompt: str) -> str:
    """
    Send prompt via Telegram and wait for a reply.
    Falls back to terminal input() if Telegram is not configured.
    Raises OTPTimeoutError if no reply arrives within the deadline.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.info("Telegram not configured — falling back to terminal input")
        return input(f"{prompt}: ").strip()

    if not send_telegram(prompt):
        return input(f"{prompt}: ").strip()

    # Bootstrap offset so we ignore messages older than this moment
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
            params={"limit": 1, "offset": -1},
            timeout=10,
        )
        updates = r.json().get("result", [])
        offset = (updates[-1]["update_id"] + 1) if updates else 0
    except Exception as e:
        log.warning(f"Telegram getUpdates (bootstrap) error: {e}")
        return input(f"{prompt}: ").strip()

    otp_deadline = 9 * 60  # 9 minutes (OTP expires after 10)
    reminder_interval = 10  # seconds between reminder messages
    log.info(f"Waiting for Telegram reply (timeout: {otp_deadline}s)…")
    start = time.time()
    deadline = start + otp_deadline
    last_reminder = start
    while time.time() < deadline:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 5},
                timeout=15,
            )
            for update in r.json().get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                if msg.get("chat", {}).get("id") == TELEGRAM_CHAT_ID and "text" in msg:
                    code = msg["text"].strip()
                    send_telegram(f"Got it: {code}")
                    return code
        except Exception as e:
            log.warning(f"Telegram poll error: {e}")
            time.sleep(5)

        now = time.time()
        if now - last_reminder >= reminder_interval:
            elapsed = int(now - start)
            m, s = divmod(elapsed, 60)
            send_telegram(f"Still waiting for OTP… ({m}m {s}s elapsed)")
            last_reminder = now

    log.warning("OTP reply timed out after 9 minutes — restarting login flow")
    send_telegram("OTP timed out after 9 minutes, restarting…")
    raise OTPTimeoutError("No OTP received within 9 minutes")
