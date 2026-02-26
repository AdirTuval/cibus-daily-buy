# cibus-daily-buy

Automates daily purchase of a digital supermarket coupon on the
[Cibus Pluxee](https://consumers.pluxee.co.il) platform (Israeli employee benefits service).

## How it works

The script logs in to your Cibus account (reusing a saved session when available to avoid
repeated OTP prompts), navigates to a configured restaurant/store page, adds the selected
denomination to the basket, then proceeds to checkout and confirms the order. If an OTP is
required during login, it is delivered via Telegram or falls back to a terminal prompt.

## Prerequisites

- Python 3.10+
- Install dependencies:
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
| `COUPON_AMOUNT` | Denomination in ILS to purchase (e.g. `30`) | Optional (default: `30`) |

## Usage

```bash
# Live purchase (headless)
python cibus_daily_buy.py

# Show browser window (useful for debugging)
python cibus_daily_buy.py --visible

# Navigate to checkout but don't confirm the order
python cibus_daily_buy.py --dry-run

# Ignore saved session and log in from scratch (forces new OTP)
python cibus_daily_buy.py --fresh-login
```

## Scheduling (cron)

Run automatically every day at 08:00:

```cron
0 8 * * * cd /path/to/cibus-daily-buy && .venv/bin/python cibus_daily_buy.py >> cibus.log 2>&1
```

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
and the script will continue automatically.

If Telegram is not configured, the script falls back to a terminal `input()` prompt.

## Screenshots

Debug screenshots are saved to `./screenshots/` at each major step (homepage, login,
restaurant page, basket, checkout). They are gitignored and useful for diagnosing failures.
