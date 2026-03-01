import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURATION — loaded from .env (copy .env.example → .env)
# ============================================================

CIBUS_URL = "https://consumers.pluxee.co.il"

USERNAME = os.getenv("CIBUS_USERNAME", "")
PASSWORD = os.getenv("CIBUS_PASSWORD", "")

RESTAURANT_URL = os.getenv(
    "RESTAURANT_URL",
    "https://consumers.pluxee.co.il/restaurants/pickup/restaurant/33237",
)
PREORDER_URL = "https://consumers.pluxee.co.il/restaurants/pickup/preorder"
# Timeouts (ms)
NAVIGATION_TIMEOUT = 30_000
ACTION_TIMEOUT     = 15_000

# Screenshot directory for debugging
SCREENSHOT_DIR = "./screenshots"

# Session persistence — avoids triggering OTP on every run
SESSION_FILE = "./session.json"

# Telegram OTP delivery (optional — falls back to terminal input if not set)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("cibus")
