# cibus-daily-buy

Automates daily purchase of a digital supermarket coupon on the
[Cibus Pluxee](https://consumers.pluxee.co.il) platform (Israeli employee benefits service).

## How it works

The script logs in to your Cibus account (reusing a saved session when available to avoid
repeated OTP prompts), navigates to a configured restaurant/store page, adds the selected
denomination to the basket, then proceeds to checkout and confirms the order. If an OTP is
required during login, it is delivered via Telegram (with up to 3 automatic retries on
timeout) or falls back to a terminal prompt when Telegram is not configured.

The browser always runs in visible mode (`headless=False`) to bypass bot detection — a
virtual framebuffer (`xvfb`) is required on headless servers.

## Prerequisites

- Python 3.10+
- `xvfb` (virtual display, required on headless/server environments):
  ```bash
  sudo apt install -y xvfb
  ```
- Install Python dependencies:
  ```bash
  pip install -r requirements.txt
  playwright install chromium
  ```

## Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/youruser/cibus-daily-buy.git
   cd cibus-daily-buy
   ```

2. Copy the example env file and fill in your credentials:
   ```bash
   cp .env.example .env
   # edit .env with your editor
   ```

3. *(Optional)* Set up a Telegram bot for OTP delivery — see [Telegram OTP setup](#telegram-otp-setup) below.

## Configuration (`.env`)

| Variable | Description | Required |
|----------|-------------|----------|
| `CIBUS_USERNAME` | Your Cibus login email | ✅ |
| `CIBUS_PASSWORD` | Your Cibus password | ✅ |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather | Optional |
| `TELEGRAM_CHAT_ID` | Your Telegram user/chat ID | Optional |
| `RESTAURANT_URL` | Full URL of the restaurant/store page | Optional (has default) |

## Usage

`xvfb-run` is required to provide a virtual display (sets `DISPLAY` automatically):

```bash
# Live purchase
xvfb-run python cibus_daily_buy.py

# Navigate to checkout but don't confirm the order
xvfb-run python cibus_daily_buy.py --dry-run

# Ignore saved session and log in from scratch (forces new OTP)
xvfb-run python cibus_daily_buy.py --fresh-login

# Write log to logs/<timestamp>_run.log
xvfb-run python cibus_daily_buy.py --log-file

# Write log to a custom path
xvfb-run python cibus_daily_buy.py --log-file /path/to/my.log
```

A log file is always created on each run; `--log-file` only overrides the destination path.

## Scheduling (cron)

Run automatically every day at 08:00:

```cron
0 8 * * * xvfb-run /path/to/cibus-daily-buy/venv/bin/python /path/to/cibus-daily-buy/cibus_daily_buy.py --log-file
```

`xvfb-run` sets `DISPLAY` and provides a virtual framebuffer so the browser can run in
visible mode. Paths (`screenshots/`, `session.json`, `logs/`) are anchored to the project
root, so cron's working directory doesn't matter.

## Telegram OTP setup

Receiving OTP codes via Telegram lets the script run fully unattended:

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts to create a bot.
3. Copy the **bot token** (looks like `123456789:AAxxxxx`) into `TELEGRAM_BOT_TOKEN` in `.env`.
4. Get your **chat ID**:
   - Send any message to your new bot.
   - Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
   - Find `"chat": {"id": <number>}` in the response — that number is your chat ID.
5. Set `TELEGRAM_CHAT_ID=<number>` in `.env`.

When an OTP is needed, the bot will message you asking for the code. Reply with the digits
and the script will continue automatically. If the OTP times out, the script retries the
login flow up to 3 times before giving up.

If Telegram is not configured, the script falls back to a terminal `input()` prompt.

## Screenshots

Debug screenshots are saved to `./screenshots/` at each major step (homepage, login,
restaurant page, basket, checkout). They are gitignored and useful for diagnosing failures.
