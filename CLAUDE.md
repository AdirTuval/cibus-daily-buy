# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python Playwright script that automates daily coupon purchases on the Cibus Pluxee platform (Israeli supermarket coupon service).

## Setup

```bash
pip install playwright
playwright install chromium
```

## Running

```bash
python cibus_daily_buy.py           # headless mode
python cibus_daily_buy.py --visible  # show browser window (debug)
python cibus_daily_buy.py --dry-run  # navigate but skip purchase
```

## Architecture

Python package (`cibus_daily_buy/`) with a backward-compatible shim (`python cibus_daily_buy.py` still works). Also runnable via `python -m cibus_daily_buy`.

### Package structure

```
cibus_daily_buy.py              # thin shim → calls cibus_daily_buy.run.main()
cibus_daily_buy/
    __init__.py                 # empty
    __main__.py                 # python -m cibus_daily_buy support
    config.py                   # all constants, env loading, logger
    telegram.py                 # send_telegram, ask_telegram
    browser.py                  # take_screenshot, wait_and_click, save_session, is_authenticated, attach_api_logger
    login.py                    # login flow + OTP
    purchase.py                 # restaurant nav, add to cart, checkout, confirm, cleanup
    run.py                      # orchestrator (run + main) — reads like a recipe
```

### Import dependency graph (no cycles)

```
config  ←── telegram
   ↑         ↑
   ├── browser ←── login (also imports telegram)
   │      ↑
   └── purchase
          ↑
        run (imports config, browser, login, purchase)
```

### Flow

1. Launch Chromium with `he-IL` locale
2. Navigate to Cibus homepage and log in (with session reuse + OTP via Telegram)
3. Check remaining budget and choose coupon amount (₪100 if budget >= 100, else ₪30)
4. Navigate to restaurant page
5. Add coupon to cart by price label
6. Navigate to checkout and confirm (skipped in `--dry-run` mode, which also cleans up cart)

### Key Patterns

- **Defensive selectors**: Multiple CSS/text selector fallbacks for each element, since the site's HTML varies. Catches `PlaywrightTimeoutError` and tries the next selector.
- **Debug screenshots**: Taken at each major step (named `01_homepage`, `02_login_filled`, etc.) and on errors, saved to `SCREENSHOT_DIR`.
- **`wait_and_click()`**: Helper that waits for visibility before clicking, with configurable timeout.
- **Session persistence**: Saves/loads browser cookies to `session.json` to avoid OTP on every run.
