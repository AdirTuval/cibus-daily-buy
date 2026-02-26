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

Single-file script (`cibus_daily_buy.py`) with this flow:

1. Launch Chromium with `he-IL` locale
2. Navigate to Cibus homepage and log in
3. Navigate to coupon/gift card section
4. Search for coupon by `COUPON_KEYWORD` (Hebrew text)
5. Purchase (skipped in `--dry-run` mode)
6. Optionally send coupon to self

**Configuration constants** at the top of the file: `CIBUS_URL`, `USERNAME`, `PASSWORD`, `COUPON_KEYWORD`, `COUPON_AMOUNT`.

### Key Patterns

- **Defensive selectors**: Multiple CSS/text selector fallbacks for each element, since the site's HTML varies. Catches `PlaywrightTimeoutError` and tries the next selector.
- **Debug screenshots**: Taken at each major step (named `01_homepage`, `02_login_page_debug`, etc.) and on errors, saved to `SCREENSHOTS_DIR`.
- **`wait_and_click()`**: Helper that waits for visibility before clicking, with configurable timeout.
