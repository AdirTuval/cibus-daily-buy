import argparse
import logging
import os
import shutil
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
    PROFILE_DIR,
    log,
)
from cibus_daily_buy.login import login
from cibus_daily_buy.telegram import OTPTimeoutError, UserAbortError, check_daily_abort
from cibus_daily_buy.purchase import (
    add_to_cart,
    check_budget,
    cleanup_cart,
    confirm_order,
    navigate_to_checkout,
    navigate_to_restaurant,
)


def _add_file_logger(path=None):
    """Attach a FileHandler to the cibus logger. Uses logs/<ts>_run.log if path not given."""
    if path is None:
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(LOG_DIR, f"{ts}_run.log")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    handler = logging.FileHandler(path)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger("cibus").addHandler(handler)
    return path


def _remove_lock_files():
    """Remove stale Chrome lock files left after unclean shutdowns (e.g. cron kill)."""
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock = os.path.join(PROFILE_DIR, name)
        try:
            os.remove(lock)
        except FileNotFoundError:
            pass


def _launch_browser(p, fresh_login):
    """Launch Chromium with a persistent profile (requires xvfb on headless servers)."""
    if fresh_login:
        log.info("Fresh login requested — deleting Chrome profile")
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    else:
        _remove_lock_files()

    try:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="he-IL",
        )
    except Exception as e:
        log.warning(f"Failed to launch with existing profile: {e}")
        log.info("Deleting corrupted profile and retrying…")
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="he-IL",
        )

    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(NAVIGATION_TIMEOUT)
    attach_api_logger(page)
    return context, page


MAX_OTP_RETRIES = 3


def run(dry_run: bool = False, fresh_login: bool = False):
    log.info("=" * 50)
    log.info(f"Cibus Daily Buy — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    log.info("=" * 50)

    check_daily_abort()

    for attempt in range(1, MAX_OTP_RETRIES + 1):
        with sync_playwright() as p:
            # Force fresh login on retries so stale session state can't interfere
            effective_fresh = fresh_login or attempt > 1
            context, page = _launch_browser(p, effective_fresh)
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

            except UserAbortError:
                raise  # intentional — no screenshot, no retry

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
                context.close()


def main():
    if not os.environ.get("DISPLAY"):
        sys.exit(
            "Error: DISPLAY environment variable is not set.\n"
            "Run via xvfb-run: xvfb-run python cibus_daily_buy.py"
        )

    parser = argparse.ArgumentParser(description="Cibus Pluxee Daily Auto-Buyer")
    parser.add_argument("--dry-run", action="store_true", help="Stop before actual purchase")
    parser.add_argument("--fresh-login", action="store_true", help="Ignore saved session and log in from scratch")
    parser.add_argument("--log-file", metavar="PATH", nargs="?", const=None,
                        help="Log file path (default: logs/<timestamp>_run.log). Always created.")
    args = parser.parse_args()

    log_path = _add_file_logger(args.log_file)
    log.info(f"Logging to file: {log_path}")

    try:
        success = run(dry_run=args.dry_run, fresh_login=args.fresh_login)
    except UserAbortError as e:
        log.info(f"Run aborted intentionally: {e}")
        sys.exit(0)
    except Exception as e:
        log.error(f"Fatal error: {e}")
        sys.exit(1)
    sys.exit(0 if success else 1)
