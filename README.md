# cibus-daily-buy

Automates daily supermarket coupon purchases on the [Cibus Pluxee](https://consumers.pluxee.co.il) platform.

## Overview

Many Israeli employers provide daily meal benefits through Cibus Pluxee. These benefits reset each day, so unused budget is lost. This script automates the purchase of digital supermarket coupons — logging in, selecting the right denomination based on remaining budget, and completing checkout. It supports session reuse via a persistent Chrome profile, OTP delivery through Telegram, budget-aware coupon selection (₪100 or ₪30), and is designed to run unattended via cron.

## Table of Contents

- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration-env)
- [Usage](#usage)
- [Scheduling with Cron](#scheduling-with-cron)
- [Telegram Integration](#telegram-integration)
- [Project Structure](#project-structure)
- [Key Design Decisions](#key-design-decisions)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

## How It Works

1. **Launch Chromium** via `xvfb-run` (visible mode bypasses Cibus bot detection)
2. **Navigate to Cibus homepage** and authenticate — the persistent Chrome profile reuses sessions across runs; OTP is requested via Telegram only when needed
3. **Read remaining budget** and pick the coupon amount: ₪100 if budget ≥ 100, ₪30 if budget ≥ 30
4. **Navigate to the restaurant page** and add the coupon to cart
5. **Go to checkout** and confirm the order (or clean up the cart in `--dry-run` mode)

## Prerequisites

- Python 3.10+
- xvfb (virtual display for headless servers):
  ```bash
  sudo apt install -y xvfb
  ```
- Python dependencies and Playwright browser:
  ```bash
  pip install -r requirements.txt
  playwright install chromium
  ```

## Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/AdirTuval/cibus-daily-buy.git
   cd cibus-daily-buy
   ```

2. Create and fill in your environment file:
   ```bash
   cp .env.example .env
   # Edit .env with your Cibus credentials (and optionally Telegram vars)
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

4. Run:
   ```bash
   xvfb-run python cibus_daily_buy.py
   ```

## Configuration (`.env`)

| Variable | Required | Description |
|---|---|---|
| `CIBUS_USERNAME` | ✅ | Your Cibus login email |
| `CIBUS_PASSWORD` | ✅ | Your Cibus password |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram bot token from [@BotFather](https://t.me/BotFather) — enables OTP delivery and remote abort |
| `TELEGRAM_CHAT_ID` | Optional | Your Telegram user/chat ID |
| `RESTAURANT_URL` | Optional | Full URL of the restaurant/store page (defaults to store #33237) |

`PREORDER_URL` is hardcoded in `config.py` and not configurable via `.env`.

## Usage

All commands require `xvfb-run` to provide a virtual display (it sets `DISPLAY` automatically):

```bash
# Live purchase
xvfb-run python cibus_daily_buy.py

# Navigate the full flow but skip purchase, then clean cart
xvfb-run python cibus_daily_buy.py --dry-run

# Delete Chrome profile and log in from scratch (forces new OTP)
xvfb-run python cibus_daily_buy.py --fresh-login

# Override log file path (default: logs/<timestamp>_run.log)
xvfb-run python cibus_daily_buy.py --log-file /path/to/my.log
```

A log file is always created on each run; `--log-file` only overrides the destination path.

The script can also be run as a module:

```bash
xvfb-run python -m cibus_daily_buy
```

## Scheduling with Cron

Run automatically every day at 08:00:

```cron
0 8 * * * xvfb-run /path/to/cibus-daily-buy/venv/bin/python /path/to/cibus-daily-buy/cibus_daily_buy.py --log-file
```

`xvfb-run` sets `DISPLAY` and provides a virtual framebuffer so the browser can run in visible mode. All paths (`screenshots/`, `chrome_profile/`, `logs/`) are anchored to the project root via `__file__`, so cron's working directory doesn't matter.

## Telegram Integration

### OTP Delivery

When Telegram is configured, the script sends OTP prompts to your chat and waits for your reply — no terminal interaction needed.

**Setup:**

1. Message [@BotFather](https://t.me/BotFather) on Telegram and send `/newbot` to create a bot.
2. Copy the **bot token** (e.g. `123456789:AAxxxxx`) into `TELEGRAM_BOT_TOKEN` in `.env`.
3. Send any message to your new bot, then open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
4. Find `"chat": {"id": <number>}` in the response — set `TELEGRAM_CHAT_ID=<number>` in `.env`.

**How it works:**

- When an OTP is needed, the bot messages you asking for the code.
- You have **9 minutes** to reply (OTP expires after 10). The bot sends a reminder every **10 seconds** with elapsed time.
- If the OTP times out, the script restarts the full login flow with a fresh browser — up to **3 retries** before giving up.
- If Telegram is not configured, the script falls back to a terminal `input()` prompt.

### Remote Abort

You can skip today's run by sending **"NO"** to the bot before the script starts.

Before each run, `check_daily_abort()` checks for unprocessed Telegram messages. If the next message is "NO", the script acknowledges it and exits cleanly. You can also send "NO" during the OTP wait to abort mid-run.

## Project Structure

```
cibus_daily_buy.py              # entry-point shim → calls cibus_daily_buy.run.main()
cibus_daily_buy/
    __init__.py
    __main__.py                 # python -m cibus_daily_buy support
    config.py                   # constants, env loading, logger setup
    telegram.py                 # OTP via Telegram, remote abort check
    browser.py                  # screenshots, wait_and_click, session, API logger
    login.py                    # credentials + OTP flow
    purchase.py                 # budget check, restaurant nav, cart, checkout, cleanup
    run.py                      # orchestrator — CLI parsing, browser launch, retry loop
```

## Key Design Decisions

- **Visible mode + xvfb** — `headless=False` bypasses Cibus bot detection; `xvfb-run` provides a virtual display on servers without a monitor.
- **Persistent Chrome profile** — `launch_persistent_context()` retains cookies, IndexedDB, service workers, and all browser state. This is more robust than Playwright's `storage_state()`, which only captures cookies and localStorage.
- **Defensive selectors** — Multiple CSS/text selector fallbacks per element because the site's HTML varies across sessions. Each selector is tried in order with a short timeout before moving to the next.
- **`__file__`-anchored paths** — All directories (`screenshots/`, `chrome_profile/`, `logs/`) resolve relative to the package, not the working directory. Safe for cron and any launch context.
- **`.type()` over `.fill()`** — Cibus uses Angular reactive forms that require keydown/keyup events. Playwright's `.fill()` bypasses these events, leaving fields empty. `.type()` fires the events Angular expects.
- **OTP retry loop** — Up to 3 full login restarts on OTP timeout, each with `fresh_login=True` to discard stale session state and start clean.
- **Stale lock cleanup** — Removes Chrome `SingletonLock`/`SingletonSocket`/`SingletonCookie` files before launch to handle unclean shutdowns (e.g. cron killing the process).

## Troubleshooting

| Problem | Solution |
|---|---|
| `DISPLAY environment variable is not set` | Run with `xvfb-run`: `xvfb-run python cibus_daily_buy.py` |
| Chrome won't launch (stale lock files) | Handled automatically; if it persists, delete `chrome_profile/Singleton*` manually |
| OTP never arrives on Telegram | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`; make sure you've sent at least one message to the bot first |
| `Budget too low` error | Your account has less than ₪30 remaining today |
| Cart not cleaned in dry-run | The site's HTML may have changed — check screenshots in `screenshots/` for updated selectors |
| Profile seems corrupted | Use `--fresh-login` to delete `chrome_profile/` and start fresh |
| Script exits with "Aborted by user 'NO' message" | You (or a previous message) sent "NO" to the Telegram bot — this is the remote abort feature working as intended |

## Contributing

Issues and pull requests are welcome.
