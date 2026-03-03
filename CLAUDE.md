# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python Playwright script that automates daily coupon purchases on the Cibus Pluxee platform (Israeli supermarket coupon service).

## Setup

```bash
cp .env.example .env   # fill in CIBUS_USERNAME, CIBUS_PASSWORD (and optionally Telegram vars)
pip install -r requirements.txt
playwright install chromium
sudo apt install -y xvfb   # virtual display for headless operation
```

## Running

```bash
python cibus_daily_buy.py                # headless mode (live purchase)
python cibus_daily_buy.py --visible      # show browser window (debug)
python cibus_daily_buy.py --dry-run      # navigate but skip purchase, then clean cart
python cibus_daily_buy.py --fresh-login  # ignore saved session, force new OTP
python cibus_daily_buy.py --log-file     # write log to logs/<timestamp>_run.log in project root
```

## Scheduling (cron)

```cron
0 8 * * * xvfb-run /path/to/venv/bin/python /path/to/cibus-daily-buy/cibus_daily_buy.py --visible --log-file
```

The `xvfb-run --visible` combo runs the browser in actual visible mode into a virtual framebuffer, bypassing Cibus bot detection that blocks headless Chromium. Paths (`screenshots/`, `session.json`, `logs/`) are always anchored to the project root via `__file__`, so cron's working directory doesn't matter.

## Configuration (`.env`)

| Variable | Required | Notes |
|---|---|---|
| `CIBUS_USERNAME` | ✅ | Login email |
| `CIBUS_PASSWORD` | ✅ | |
| `TELEGRAM_BOT_TOKEN` | Optional | OTP delivery; falls back to terminal `input()` |
| `TELEGRAM_CHAT_ID` | Optional | |
| `RESTAURANT_URL` | Optional | Defaults to store #33237 (hardcoded in `config.py`) |

`PREORDER_URL` is hardcoded in `config.py` (not in `.env`).

## Architecture

Python package (`cibus_daily_buy/`) with a backward-compatible shim (`python cibus_daily_buy.py` still works). Also runnable via `python -m cibus_daily_buy`.

### Package structure

```
cibus_daily_buy.py              # thin shim → calls cibus_daily_buy.run.main()
cibus_daily_buy/
    __init__.py                 # empty
    __main__.py                 # python -m cibus_daily_buy support
    config.py                   # all constants, env loading, logger
    telegram.py                 # OTPTimeoutError, send_telegram, ask_telegram
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
        run (imports config, browser, login, purchase, telegram)
```

### Flow

1. Launch Chromium with `he-IL` locale
2. Navigate to Cibus homepage and log in (with session reuse + OTP via Telegram)
3. Check remaining budget: ₪100 coupon if budget ≥ 100, ₪30 if budget ≥ 30, error if below 30
4. Navigate to restaurant page
5. Add coupon to cart by price label
6. Navigate to checkout and confirm (skipped in `--dry-run` mode, which also cleans up cart)

### Key Patterns

- **Defensive selectors**: Multiple CSS/text selector fallbacks for each element, since the site's HTML varies. Catches `PlaywrightTimeoutError` and tries the next selector.
- **Debug screenshots**: Taken at each major step (named `01_homepage`, `02_login_filled`, etc.) and on errors, saved to `SCREENSHOT_DIR`.
- **`wait_and_click()`**: Helper that waits for visibility before clicking, with configurable timeout.
- **Session persistence**: Saves/loads browser cookies to `session.json` to avoid OTP on every run.
- **`__file__`-anchored paths**: `SCREENSHOT_DIR`, `SESSION_FILE`, and `LOG_DIR` in `config.py` are resolved relative to the package, not the cwd. Safe to run from cron or any directory.
- **`LOG_FORMAT`**: Single format string constant shared by the stdout handler (`basicConfig`) and the optional file handler (`--log-file`).
- **OTP retry loop**: `run()` in `run.py` retries the full login flow up to `MAX_OTP_RETRIES` (3) times on `OTPTimeoutError`. Retries always use `fresh_login=True` to discard stale session state. `ask_telegram()` waits 9 minutes for a Telegram reply (matching OTP lifetime), sends a reminder every 10 s, then raises `OTPTimeoutError` instead of falling back to terminal input.
