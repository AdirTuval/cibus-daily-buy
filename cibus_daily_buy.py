"""
Cibus Pluxee - Daily Coupon Auto-Buyer
=======================================
Automates daily login → navigate → purchase a digital supermarket coupon.

Prerequisites:
    pip install playwright python-dotenv requests
    playwright install chromium

Usage:
    python cibus_daily_buy.py              # Run once (headless)
    python cibus_daily_buy.py --visible    # Run with browser visible (for debugging)
    python cibus_daily_buy.py --dry-run    # Navigate to item but don't buy

Schedule with cron (e.g., every day at 08:00):
    0 8 * * * cd /path/to/script && .venv/bin/python cibus_daily_buy.py >> cibus.log 2>&1
"""

import argparse
import json
import os
import sys
import time
import logging
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import requests  # pip install requests

# ============================================================
# CONFIGURATION — loaded from .env (copy .env.example → .env)
# ============================================================

load_dotenv()

CIBUS_URL = "https://consumers.pluxee.co.il"

USERNAME = os.getenv("CIBUS_USERNAME", "")
PASSWORD = os.getenv("CIBUS_PASSWORD", "")

RESTAURANT_URL = os.getenv(
    "RESTAURANT_URL",
    "https://consumers.pluxee.co.il/restaurants/pickup/restaurant/33237",
)
COUPON_AMOUNT = int(os.getenv("COUPON_AMOUNT", "30"))

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

# ============================================================
# HELPERS
# ============================================================

def take_screenshot(page, name: str):
    """Save a screenshot for debugging."""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{SCREENSHOT_DIR}/{ts}_{name}.png"
    page.screenshot(path=path, full_page=True)
    log.info(f"Screenshot saved: {path}")
    return path


def wait_and_click(page, selector: str, description: str, timeout=ACTION_TIMEOUT):
    """Wait for an element and click it."""
    log.info(f"Waiting for: {description} ({selector})")
    element = page.wait_for_selector(selector, timeout=timeout)
    element.click()
    log.info(f"Clicked: {description}")
    return element


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
    Falls back to terminal input() if Telegram is not configured or times out.
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

    log.info("Waiting for Telegram reply (timeout: 300s)…")
    deadline = time.time() + 300
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

    log.warning("Telegram reply timed out — falling back to terminal input")
    return input(f"{prompt}: ").strip()


def save_session(context) -> None:
    """Persist browser cookies/storage to SESSION_FILE."""
    state = context.storage_state()
    with open(SESSION_FILE, "w") as f:
        json.dump(state, f)
    log.info(f"Session saved → {SESSION_FILE}")


def is_authenticated(page) -> bool:
    """Return True if the login form is absent (i.e. session is active)."""
    try:
        page.wait_for_selector("#user", timeout=4000)
        return False  # login form is visible → not authenticated
    except PlaywrightTimeout:
        return True  # no login form → already authenticated


# ============================================================
# MAIN AUTOMATION FLOW
# ============================================================

def run(headless: bool = True, dry_run: bool = False, fresh_login: bool = False):
    log.info("=" * 50)
    log.info(f"Cibus Daily Buy — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'} | Headless: {headless}")
    log.info("=" * 50)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context_kwargs = {"viewport": {"width": 1280, "height": 800}, "locale": "he-IL"}
        if fresh_login:
            log.info("Fresh login requested — ignoring saved session")
        elif os.path.exists(SESSION_FILE):
            log.info(f"Loading session from {SESSION_FILE}")
            with open(SESSION_FILE) as f:
                # Reusing saved cookies avoids triggering OTP on every run
                context_kwargs["storage_state"] = json.load(f)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(NAVIGATION_TIMEOUT)

        try:
            # ------------------------------------------
            # STEP 1: Navigate to Cibus
            # ------------------------------------------
            log.info(f"Navigating to {CIBUS_URL}")
            # "domcontentloaded" is faster than "networkidle"; Angular hydrates async
            # so we wait_for_selector separately where needed
            page.goto(CIBUS_URL, wait_until="domcontentloaded")
            take_screenshot(page, "01_homepage")

            # ------------------------------------------
            # STEP 2: Login (with session reuse + OTP)
            # ------------------------------------------
            if is_authenticated(page):
                log.info("Session still valid — skipping login")
            else:
                log.info("Not authenticated — logging in...")

                # Step 2a: type username
                # .type() fires keydown/keyup events; Angular's reactive forms need these
                # — .fill() bypasses them and the field stays empty
                page.locator("#user").type(USERNAME)
                log.info("Typed username")

                # Step 2b: click "next" button
                page.locator("button:has-text('שנמשיך?'):visible").click()
                log.info("Clicked next")

                # Step 2c: wait for password field, type password
                page.wait_for_selector("#password")
                page.locator("#password").type(PASSWORD)
                log.info("Typed password")
                take_screenshot(page, "02_login_filled")

                # Step 2d: click login
                page.locator("button:has-text('כניסה'):visible").click()
                log.info("Clicked login")

                time.sleep(2)  # let Angular settle
                take_screenshot(page, "03_after_login_click")

                # Step 2e: check for OTP field
                # Try multiple selectors defensively — the site's HTML varies across sessions
                otp_selectors = [
                    'input[type="number"][maxlength]',
                    'input[placeholder*="קוד"]',
                    'input[placeholder*="code" i]',
                    'input[name*="otp"]',
                    'input[name*="code"]',
                ]
                otp_field = None
                for sel in otp_selectors:
                    try:
                        otp_field = page.wait_for_selector(sel, timeout=4000)
                        log.info(f"OTP field found: {sel}")
                        break
                    except PlaywrightTimeout:
                        continue

                if otp_field:
                    code = ask_telegram("Cibus OTP code please:")
                    otp_field.fill(code)
                    try:
                        page.locator(
                            'button:has-text("שנמשיך?"):visible, '
                            'button[type="submit"]:visible, button:has-text("אשר"):visible, '
                            'button:has-text("כניסה"):visible'
                        ).first.click()
                    except Exception:
                        page.keyboard.press("Enter")
                    time.sleep(2)
                    take_screenshot(page, "03b_after_otp")
                    save_session(context)
                else:
                    log.info("No OTP field — assuming login succeeded")
                    save_session(context)

                take_screenshot(page, "03_after_login")
                log.info("Login complete")

            # ------------------------------------------
            # STEP 3: Navigate to restaurant page
            # ------------------------------------------
            log.info(f"Navigating to restaurant page: {RESTAURANT_URL}")
            page.goto(RESTAURANT_URL, wait_until="domcontentloaded")
            # Angular renders cards asynchronously after DOMContentLoaded; explicit wait is required
            page.wait_for_selector(".card", timeout=15_000)
            take_screenshot(page, "04_restaurant_page")

            # ------------------------------------------
            # STEP 4: Find ₪COUPON_AMOUNT option and click its + button
            # ------------------------------------------
            log.info(f"Looking for ₪{COUPON_AMOUNT} option...")
            # Two card sections on the page may match the price label; .first picks the correct top one
            card = page.locator(f'.card:has(.card-footer label:text("₪{COUPON_AMOUNT}.00"))').first
            # The + button is <input type="image">, not <button> — standard button selectors won't find it
            add_btn = card.locator('input[type="image"]')
            add_btn.scroll_into_view_if_needed()
            add_btn.click()
            time.sleep(2)
            log.info(f"Added ₪{COUPON_AMOUNT} coupon to basket")
            take_screenshot(page, "05_added_to_basket")

            # ------------------------------------------
            # STEP 5: Dry-run stop point
            # ------------------------------------------
            if dry_run:
                log.info("DRY RUN — navigating to checkout page...")
                page.goto("https://consumers.pluxee.co.il/restaurants/pickup/preorder",
                          wait_until="domcontentloaded")
                time.sleep(1)
                take_screenshot(page, "06_preorder_page")
                log.info("DRY RUN — stopping before confirm (waiting 3s)")
                time.sleep(3)
                return True

            # ------------------------------------------
            # STEP 6: Navigate to preorder page and confirm order
            # ------------------------------------------
            log.info("Navigating to checkout...")
            page.goto("https://consumers.pluxee.co.il/restaurants/pickup/preorder",
                      wait_until="domcontentloaded")
            time.sleep(1)
            take_screenshot(page, "06_preorder_page")

            log.info("Confirming order...")
            page.locator('button:has-text("אישור ההזמנה")').click()
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)
            take_screenshot(page, "07_after_confirm")

            log.info("✅ Purchase completed successfully!")
            return True

        except Exception as e:
            log.error(f"❌ Error: {e}")
            try:
                take_screenshot(page, "error")
            except Exception:
                pass
            raise

        finally:
            browser.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cibus Pluxee Daily Auto-Buyer")
    parser.add_argument("--visible", action="store_true", help="Show browser window")
    parser.add_argument("--dry-run", action="store_true", help="Stop before actual purchase")
    parser.add_argument("--fresh-login", action="store_true", help="Ignore saved session and log in from scratch")
    args = parser.parse_args()

    success = run(headless=not args.visible, dry_run=args.dry_run, fresh_login=args.fresh_login)
    sys.exit(0 if success else 1)
