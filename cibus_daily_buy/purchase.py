import time

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from cibus_daily_buy.browser import save_session, take_screenshot
from cibus_daily_buy.config import (
    ACTION_TIMEOUT,
    COUPON_AMOUNT,
    PREORDER_URL,
    RESTAURANT_URL,
    log,
)


def navigate_to_restaurant(page) -> None:
    """Navigate to the restaurant page (sets server-side session context)."""
    log.info(f"Navigating to restaurant page: {RESTAURANT_URL}")
    page.goto(RESTAURANT_URL, wait_until="domcontentloaded")
    page.wait_for_selector(".card", timeout=ACTION_TIMEOUT)
    take_screenshot(page, "04_restaurant_page")


def add_to_cart(page) -> None:
    """Find the coupon card by price and click the + button."""
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


def navigate_to_checkout(page) -> bool:
    """Go to the preorder URL. Returns True if the confirm button is visible."""
    log.info("Navigating to checkout...")
    page.goto(PREORDER_URL, wait_until="domcontentloaded")
    time.sleep(2)
    take_screenshot(page, "06_preorder_page")

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

    return checkout_ok


def confirm_order(page) -> None:
    """Re-locate the confirm button, click it, and wait for confirmation."""
    log.info("Confirming order...")
    confirm_btn = page.locator('button:has-text("אישור ההזמנה")')
    confirm_btn.click()
    page.wait_for_load_state("domcontentloaded")
    time.sleep(3)
    take_screenshot(page, "07_after_confirm")
    log.info("✅ Purchase completed successfully!")


def _confirm_deletion(page) -> None:
    """Handle the deletion confirmation dialog."""
    try:
        confirm_delete = page.locator('button:has-text("כן, למחוק")')
        confirm_delete.wait_for(state="visible", timeout=ACTION_TIMEOUT)
        confirm_delete.click()
        time.sleep(2)
        take_screenshot(page, "09_after_confirm_delete")
        log.info("Confirmed cart item deletion")
    except Exception as e:
        log.warning(f"No confirmation dialog found: {e}")


def cleanup_cart(page, context) -> None:
    """Remove items from cart via trash icon on the checkout page."""
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
                _confirm_deletion(page)
                cleaned = True
                log.info("Cart item removed via trash icon")
                break
        except Exception:
            continue

    if not cleaned:
        log.warning("Could not find trash button — cart may still contain items")
        take_screenshot(page, "07_trash_not_found")

    save_session(context)
    log.info("Session saved")
