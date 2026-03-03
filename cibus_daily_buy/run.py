import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

from cibus_daily_buy.browser import attach_api_logger, take_screenshot
from cibus_daily_buy.config import (
    CIBUS_URL,
    LOG_DIR,
    LOG_FORMAT,
    NAVIGATION_TIMEOUT,
    SESSION_FILE,
    log,
)
from cibus_daily_buy.login import login
from cibus_daily_buy.telegram import OTPTimeoutError
from cibus_daily_buy.purchase import (
    add_to_cart,
    check_budget,
    cleanup_cart,
    confirm_order,
    navigate_to_checkout,
    navigate_to_restaurant,
)


def _add_file_logger():
    """Attach a FileHandler to the cibus logger → logs/<ts>_run.log."""
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"{ts}_run.log")
    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger("cibus").addHandler(handler)
    return log_path


def _launch_browser(p, headless, fresh_login):
    """Launch Chromium, create context with optional session, attach API logger."""
    browser = p.chromium.launch(headless=headless)

    context_kwargs = {"viewport": {"width": 1280, "height": 800}, "locale": "he-IL"}

    if fresh_login:
        log.info("Fresh login requested — ignoring saved session")
    else:
        try:
            with open(SESSION_FILE) as f:
                # Reusing saved cookies avoids triggering OTP on every run
                context_kwargs["storage_state"] = json.load(f)
            log.info(f"Loading session from {SESSION_FILE}")
        except FileNotFoundError:
            pass
    context = browser.new_context(**context_kwargs)

    page = context.new_page()
    page.set_default_timeout(NAVIGATION_TIMEOUT)
    attach_api_logger(page)
    return browser, context, page


MAX_OTP_RETRIES = 3


def run(headless: bool = True, dry_run: bool = False, fresh_login: bool = False):
    log.info("=" * 50)
    log.info(f"Cibus Daily Buy — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'} | Headless: {headless}")
    log.info("=" * 50)

    for attempt in range(1, MAX_OTP_RETRIES + 1):
        with sync_playwright() as p:
            # Force fresh login on retries so stale session state can't interfere
            effective_fresh = fresh_login or attempt > 1
            browser, context, page = _launch_browser(p, headless, effective_fresh)
            try:
                # Step 1: Navigate to Cibus
                log.info(f"Navigating to {CIBUS_URL}")
                page.goto(CIBUS_URL, wait_until="domcontentloaded")
                time.sleep(2)
                take_screenshot(page, "01_homepage")

                # Step 2: Login
                login(page, context)

                # Step 3: Check budget and choose coupon amount
                coupon_amount = check_budget(page)

                # Step 4: Navigate to restaurant
                navigate_to_restaurant(page)

                # Step 5: Add to cart
                add_to_cart(page, coupon_amount)

                # Step 6: Checkout
                checkout_ok = navigate_to_checkout(page)

                # Step 7: Dry run — verify & clean up
                if dry_run:
                    if checkout_ok:
                        log.info("DRY RUN — full flow verified successfully!")
                    else:
                        log.warning("DRY RUN — checkout verification FAILED")
                    cleanup_cart(page, context)
                    log.info("DRY RUN complete")
                    return checkout_ok

                # Step 8: Confirm order (live)
                if not checkout_ok:
                    raise RuntimeError("Checkout page not ready — aborting")
                confirm_order(page)
                return True

            except OTPTimeoutError:
                log.warning(f"OTP timed out (attempt {attempt}/{MAX_OTP_RETRIES})")
                if attempt < MAX_OTP_RETRIES:
                    log.info("Restarting login flow with a fresh browser…")
                    continue
                raise RuntimeError(
                    f"OTP not provided after {MAX_OTP_RETRIES} attempts"
                )

            except Exception as e:
                log.error(f"❌ Error: {e}")
                try:
                    take_screenshot(page, "error")
                except Exception:
                    pass
                raise

            finally:
                browser.close()


def main():
    parser = argparse.ArgumentParser(description="Cibus Pluxee Daily Auto-Buyer")
    parser.add_argument("--visible", action="store_true", help="Show browser window")
    parser.add_argument("--dry-run", action="store_true", help="Stop before actual purchase")
    parser.add_argument("--fresh-login", action="store_true", help="Ignore saved session and log in from scratch")
    parser.add_argument("--log-file", action="store_true",
                        help="Write log output to logs/<timestamp>_run.log in the project root")
    args = parser.parse_args()

    if args.log_file:
        log_path = _add_file_logger()
        log.info(f"Logging to file: {log_path}")

    success = run(headless=not args.visible, dry_run=args.dry_run, fresh_login=args.fresh_login)
    sys.exit(0 if success else 1)
