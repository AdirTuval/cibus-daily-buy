import os
from datetime import datetime

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from cibus_daily_buy.config import ACTION_TIMEOUT, SCREENSHOT_DIR, log


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


def save_session(context) -> None:
    """Session auto-persists via Chrome profile directory."""
    log.info("Session auto-persisted via Chrome profile")


def is_authenticated(page) -> bool:
    """Return True if the login form is absent (i.e. session is active)."""
    try:
        page.wait_for_selector("#user", timeout=4000)
        return False  # login form is visible → not authenticated
    except PlaywrightTimeout:
        return True  # no login form → already authenticated


def attach_api_logger(page) -> None:
    """Log Pluxee API traffic for debugging / discovering cart-clearing endpoints."""
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
