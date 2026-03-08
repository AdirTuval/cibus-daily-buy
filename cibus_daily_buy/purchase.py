import re
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from cibus_daily_buy.browser import save_session, take_screenshot
from cibus_daily_buy.config import (
    ACTION_TIMEOUT,
    PREORDER_URL,
    RESTAURANT_URL,
    log,
)


def check_budget(page) -> int:
    """Read remaining budget from the page and choose the coupon amount."""
    budget_el = page.locator(".budget")
    budget_el.wait_for(state="visible", timeout=ACTION_TIMEOUT)
    text = budget_el.text_content()
    take_screenshot(page, "04_budget")

    match = re.search(r"₪([\d,]+\.?\d*)", text)
    if not match:
        raise RuntimeError(f"Could not parse budget from: {text!r}")
    budget = float(match.group(1).replace(",", ""))
    log.info(f"Remaining budget: ₪{budget:.2f}")

    if budget >= 100:
        coupon_amount = 100
    elif budget >= 30:
        coupon_amount = 30
    else:
        raise RuntimeError(f"Budget too low: ₪{budget:.2f}")

    log.info(f"Selected coupon amount: ₪{coupon_amount}")
    return coupon_amount


def navigate_to_restaurant(page) -> None:
    """Navigate to the restaurant page (sets server-side session context)."""
    log.info(f"Navigating to restaurant page: {RESTAURANT_URL}")
    page.goto(RESTAURANT_URL, wait_until="domcontentloaded")
    page.wait_for_selector(".card", timeout=ACTION_TIMEOUT)
    take_screenshot(page, "05_restaurant_page")


def add_to_cart(page, coupon_amount: int) -> None:
    """Find the coupon card by price and click the + button."""
    card_selector = f'.card:has(.card-footer label:text("₪{coupon_amount}.00"))'
    card = page.locator(card_selector).first
    plus_btn = card.locator('input[type="image"]')
    plus_btn.wait_for(state="visible", timeout=ACTION_TIMEOUT)

    log.info(f"Clicking + on ₪{coupon_amount} card")
    with page.expect_response("**/api/main.py") as resp_info:
        plus_btn.click()
    response = resp_info.value
    body = response.json()
    log.info(f"prx_add_prod_to_cart response: code={body.get('code')}, msg={body.get('msg')}")
    if body.get("code") != 0:
        raise RuntimeError(f"Failed to add to cart: code={body.get('code')}, msg={body.get('msg')}")
    log.info(f"Added ₪{coupon_amount} to cart")
    take_screenshot(page, "06_after_add_to_cart")


def navigate_to_checkout(page) -> bool:
    """Go to the preorder URL. Returns True if the confirm button is visible."""
    log.info("Navigating to checkout...")
    page.goto(PREORDER_URL, wait_until="domcontentloaded")
    time.sleep(2)
    take_screenshot(page, "07_preorder_page")

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
    take_screenshot(page, "08_after_confirm")
    log.info("✅ Purchase completed successfully!")


def _confirm_deletion(page) -> None:
    """Handle the deletion confirmation dialog after trash click."""
    confirm_selectors = [
        'button:has-text("כן, למחוק")',
        'text="כן, למחוק"',
        ':text("למחוק")',
    ]
    for sel in confirm_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=5000):
                log.info(f"Found confirm-delete button: {sel}")
                btn.click()
                time.sleep(2)
                take_screenshot(page, "10_after_confirm_delete")
                log.info("Confirmed cart item deletion")
                return
        except Exception:
            continue
    log.warning("Could not find confirm-delete button in dialog")
    take_screenshot(page, "10_confirm_delete_failed")


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
                take_screenshot(page, "08_before_trash_click")
                trash_btn.click()
                time.sleep(2)
                take_screenshot(page, "09_after_trash_click")
                _confirm_deletion(page)
                cleaned = True
                log.info("Cart item removed via trash icon")
                break
        except Exception:
            continue

    if not cleaned:
        log.warning("Could not find trash button — cart may still contain items")
        take_screenshot(page, "08_trash_not_found")

    save_session(context)
    log.info("Session saved")
