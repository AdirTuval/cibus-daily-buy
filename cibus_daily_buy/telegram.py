import json
import time

import requests

from cibus_daily_buy.config import PROJECT_ROOT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, log

TELEGRAM_OFFSET_FILE = str(PROJECT_ROOT / "telegram_offset.json")


class OTPTimeoutError(Exception):
    """Raised when the user does not reply with an OTP within the deadline."""


class UserAbortError(Exception):
    """Raised when the user explicitly sends 'NO' to abort the script."""


def _load_offset() -> int:
    """Load the last confirmed Telegram update_id from disk. Returns 0 if not found."""
    try:
        with open(TELEGRAM_OFFSET_FILE) as f:
            return json.load(f).get("offset", 0)
    except (FileNotFoundError, Exception):
        return 0


def _save_offset(offset: int) -> None:
    """Persist the next expected update_id so future calls skip already-processed updates."""
    try:
        with open(TELEGRAM_OFFSET_FILE, "w") as f:
            json.dump({"offset": offset}, f)
    except Exception as e:
        log.warning(f"Failed to save telegram offset: {e}")


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


def check_daily_abort() -> None:
    """Check if the next unprocessed Telegram message is 'NO'. Raise UserAbortError if so."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    offset = _load_offset()
    try:
        updates = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
            params={"offset": offset, "limit": 20},
            timeout=10,
        ).json().get("result", [])
    except Exception as e:
        log.warning(f"check_daily_abort: fetch failed, skipping check: {e}")
        return  # fail open — don't block script on network error

    new_offset = offset
    for update in updates:
        new_offset = update["update_id"] + 1
        msg = update.get("message", {})
        if msg.get("chat", {}).get("id") != TELEGRAM_CHAT_ID:
            continue
        text = msg.get("text", "").strip()
        if text.upper() == "NO":
            _save_offset(new_offset)
            log.info("Pre-run abort: next unprocessed Telegram message is 'NO'")
            send_telegram("Script aborted for today: received 'NO'")
            raise UserAbortError("Aborted by user 'NO' message before run")

    _save_offset(new_offset)  # acknowledge all scanned updates, even if no abort


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

    offset = _load_offset()

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
                msg = update.get("message", {})
                if msg.get("chat", {}).get("id") == TELEGRAM_CHAT_ID and "text" in msg:
                    code = msg["text"].strip()
                    offset = update["update_id"] + 1
                    _save_offset(offset)  # confirm before acting
                    if code.upper() == "NO":
                        log.info("OTP-time abort: user sent 'NO' via Telegram")
                        send_telegram("Script aborted: received 'NO' during OTP wait")
                        raise UserAbortError("Aborted by user 'NO' during OTP wait")
                    send_telegram(f"Got it: {code}")
                    return code
        except UserAbortError:
            raise
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
