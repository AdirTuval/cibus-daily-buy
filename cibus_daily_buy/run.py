import argparse
import json
import os
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

from cibus_daily_buy.browser import attach_api_logger, take_screenshot
from cibus_daily_buy.config import (
    CIBUS_URL,
    NAVIGATION_TIMEOUT,
    SESSION_FILE,
    log,
)
from cibus_daily_buy.login import login
from cibus_daily_buy.purchase import (
    add_to_cart,
    check_budget,
    cleanup_cart,
    confirm_order,
    navigate_to_checkout,
    navigate_to_restaurant,
)


def _launch_browser(p, headless, fresh_login):
    """Launch Chromium, create context with optional session, attach API logger."""
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
    attach_api_logger(page)
    return browser, context, page


def _capture_reorder_mode(page) -> bool:
    """Navigate to order history and log API calls for discovery."""
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


def run(headless: bool = True, dry_run: bool = False, fresh_login: bool = False, capture_reorder: bool = False):
    log.info("=" * 50)
    log.info(f"Cibus Daily Buy — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'} | Headless: {headless}")
    log.info("=" * 50)

    with sync_playwright() as p:
        browser, context, page = _launch_browser(p, headless, fresh_login)
        try:
            # Step 1: Navigate to Cibus
            log.info(f"Navigating to {CIBUS_URL}")
            page.goto(CIBUS_URL, wait_until="domcontentloaded")
            time.sleep(2)
            take_screenshot(page, "01_homepage")

            # Step 2: Login
            login(page, context)

            # Step 3: Capture mode (early return)
            if capture_reorder:
                return _capture_reorder_mode(page)

            # Step 4: Check budget and choose coupon amount
            coupon_amount = check_budget(page)

            # Step 5: Navigate to restaurant
            navigate_to_restaurant(page)

            # Step 6: Add to cart
            add_to_cart(page, coupon_amount)

            # Step 7: Checkout
            checkout_ok = navigate_to_checkout(page)

            # Step 8: Dry run — verify & clean up
            if dry_run:
                if checkout_ok:
                    log.info("DRY RUN — full flow verified successfully!")
                else:
                    log.warning("DRY RUN — checkout verification FAILED")
                cleanup_cart(page, context)
                log.info("DRY RUN complete")
                return checkout_ok

            # Step 9: Confirm order (live)
            if not checkout_ok:
                raise RuntimeError("Checkout page not ready — aborting")
            confirm_order(page)
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


def main():
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
