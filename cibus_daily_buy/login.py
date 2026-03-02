import time

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from cibus_daily_buy.browser import is_authenticated, save_session, take_screenshot
from cibus_daily_buy.config import PASSWORD, USERNAME, log
from cibus_daily_buy.telegram import ask_telegram


def _find_otp_field(page):
    """Try multiple selectors defensively — the site's HTML varies across sessions."""
    otp_selectors = [
        'input[type="number"][maxlength]',
        'input[placeholder*="קוד"]',
        'input[placeholder*="code" i]',
        'input[name*="otp"]',
        'input[name*="code"]',
    ]
    for sel in otp_selectors:
        try:
            otp_field = page.wait_for_selector(sel, timeout=4000)
            log.info(f"OTP field found: {sel}")
            return otp_field
        except PlaywrightTimeout:
            continue
    return None


def _handle_otp(page, context, otp_field) -> None:
    """Ask for OTP via Telegram, fill, and submit."""
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


def login(page, context) -> None:
    """Full login flow: check session → credentials → OTP → save."""
    if is_authenticated(page):
        log.info("Session still valid — skipping login")
        return

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
    otp_field = _find_otp_field(page)
    if otp_field:
        _handle_otp(page, context, otp_field)
    else:
        log.info("No OTP field — assuming login succeeded")
        save_session(context)

    take_screenshot(page, "03_after_login")
    log.info("Login complete")
