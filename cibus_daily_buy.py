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
PREORDER_URL = "https://consumers.pluxee.co.il/restaurants/pickup/preorder"
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

def run(headless: bool = True, dry_run: bool = False, fresh_login: bool = False, capture_reorder: bool = False):
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

        # Log Pluxee API traffic for debugging / discovering cart-clearing endpoints
        def _log_request(request):
            if "pluxee.co.il/api" in request.url.lower():
                log.info(f"  >> {request.method} {request.url}")
                if request.post_data:
                    log.info(f"     PostData: {request.post_data[:1000]}")

        def _log_response(response):
            if "pluxee.co.il/api" in response.url.lower():
                log.info(f"  << {response.status} {response.url}")
                try:
                    log.info(f"     Body: {response.text()[:1000]}")
                except Exception:
                    pass

        page.on("request", _log_request)
        page.on("response", _log_response)

        try:
            # ------------------------------------------
            # STEP 1: Navigate to Cibus
            # ------------------------------------------
            log.info(f"Navigating to {CIBUS_URL}")
            # "domcontentloaded" is faster than "networkidle"; Angular hydrates async
            # so we wait_for_selector separately where needed
            page.goto(CIBUS_URL, wait_until="domcontentloaded")
            time.sleep(2)
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
            # CAPTURE REORDER MODE (discovery)
            # ------------------------------------------
            if capture_reorder:
                log.info("CAPTURE MODE — navigating to order history")
                page.goto("https://consumers.pluxee.co.il/restaurants/orders",
                          wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                take_screenshot(page, "orders_page")
                log.info("CAPTURE MODE — click the reorder button in the browser.")
                log.info("All API calls are being logged. Waiting 20s...")
                # Must use Playwright's wait (not time.sleep) to keep the event loop
                # alive so page.on("request"/"response") handlers fire.
                page.wait_for_timeout(20_000)
                return True

            # ------------------------------------------
            # STEP 3: Navigate to restaurant page (sets server-side session context)
            # ------------------------------------------
            log.info(f"Navigating to restaurant page: {RESTAURANT_URL}")
            page.goto(RESTAURANT_URL, wait_until="domcontentloaded")
            page.wait_for_selector(".card", timeout=ACTION_TIMEOUT)
            take_screenshot(page, "04_restaurant_page")

            # ------------------------------------------
            # STEP 4: Add coupon to cart
            # ------------------------------------------
            card_selector = f'.card:has(.card-footer label:text("₪{COUPON_AMOUNT}.00"))'
            card = page.locator(card_selector).first
            plus_btn = card.locator('input[type="image"]')
            plus_btn.wait_for(state="visible", timeout=ACTION_TIMEOUT)

            log.info(f"Clicking + on ₪{COUPON_AMOUNT} card")
            with page.expect_response("**/api/main.py") as resp_info:
                plus_btn.click()
            response = resp_info.value
            body = response.json()
            log.info(f"prx_add_prod_to_cart response: code={body.get('code')}, msg={body.get('msg')}")
            if body.get("code") != 0:
                raise RuntimeError(f"Failed to add to cart: code={body.get('code')}, msg={body.get('msg')}")
            log.info(f"Added ₪{COUPON_AMOUNT} to cart")
            take_screenshot(page, "05_after_add_to_cart")

            # ------------------------------------------
            # STEP 5: Navigate to checkout page
            # ------------------------------------------
            log.info("Navigating to checkout...")
            page.goto(PREORDER_URL, wait_until="domcontentloaded")
            time.sleep(2)
            take_screenshot(page, "06_preorder_page")

            # Verify checkout page is stable
            checkout_ok = False
            if "preorder" in page.url:
                confirm_btn = page.locator('button:has-text("אישור ההזמנה")')
                try:
                    confirm_btn.wait_for(state="visible", timeout=ACTION_TIMEOUT)
                    checkout_ok = True
                    log.info("Checkout page stable — confirm button visible")
                except PlaywrightTimeout:
                    log.warning("Checkout page loaded but confirm button not found")
            else:
                log.warning(f"Redirected away from checkout: {page.url}")

            if dry_run:
                # --- DRY RUN: verify result and clean up cart ---
                if checkout_ok:
                    log.info("DRY RUN — full flow verified successfully!")
                else:
                    log.warning("DRY RUN — checkout verification FAILED")

                # Attempt to remove item from cart via trash icon on checkout page
                log.info("DRY RUN — cleaning up cart...")
                cleaned = False
                trash_selectors = [
                    'img[src*="icon-trash"]',         # exact match for the known SVG
                    'img[src*="trash"]',              # any trash icon image
                    '[class*="trash"]',               # fallback: element with "trash" in class
                    '[class*="delete"]',              # fallback: element with "delete" in class
                ]
                # Navigate back to checkout if we got redirected
                if "preorder" not in page.url:
                    page.goto(PREORDER_URL, wait_until="domcontentloaded")
                    time.sleep(1)

                for sel in trash_selectors:
                    try:
                        trash_btn = page.locator(sel).first
                        if trash_btn.is_visible(timeout=2000):
                            log.info(f"Found trash button: {sel}")
                            take_screenshot(page, "07_before_trash_click")
                            trash_btn.click()
                            time.sleep(2)
                            take_screenshot(page, "08_after_trash_click")
                            cleaned = True
                            log.info("Cart item removed via trash icon")
                            break
                    except Exception:
                        continue

                if not cleaned:
                    log.warning("Could not find trash button — deleting session.json as fallback")
                    take_screenshot(page, "07_trash_not_found")
                    try:
                        os.remove(SESSION_FILE)
                        log.info(f"Deleted {SESSION_FILE} — next run will force fresh login")
                    except FileNotFoundError:
                        pass
                else:
                    save_session(context)
                    log.info("Session saved with clean cart")

                log.info("DRY RUN complete")
                return checkout_ok

            # ------------------------------------------
            # STEP 6: Confirm order (live mode only)
            # ------------------------------------------
            if not checkout_ok:
                raise RuntimeError("Checkout page not ready — aborting")

            log.info("Confirming order...")
            confirm_btn.click()
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
    parser.add_argument("--capture-reorder", action="store_true",
                        help="Navigate to order history and capture reorder API call")
    args = parser.parse_args()

    success = run(headless=not args.visible, dry_run=args.dry_run, fresh_login=args.fresh_login,
                  capture_reorder=args.capture_reorder)
    sys.exit(0 if success else 1)
