# GDrive Rclone Telegram Bot

A Telegram bot that uses Rclone to clone files and folders within Google Drive server-side.

## Tech Stack
- **Language:** Python 3.12
- **Bot Framework:** python-telegram-bot v20.8
- **Database:** MongoDB (optional) or local JSON fallback
- **External Tool:** rclone (installed as system dependency)

## Project Structure
- `bot/` — Entry point (`main.py`)
- `config/` — Settings and environment variable handling (`settings.py`)
- `modules/` — Bot commands and clone logic
- `utils/` — rclone wrapper, queue, database, and helpers
- `logs/` — Application and transfer logs

## Running the Bot
```
python -m bot.main
```

## Required Environment Variables (Secrets)
- `BOT_TOKEN` — Telegram bot token (from @BotFather)
- `ADMIN_ID` — Your Telegram user ID (comma-separated for multiple)
- `DRIVE_DESTINATION` — Google Drive destination in format `remote_name:path` (e.g. `gdrive:cloned_files`)
- `RCLONE_CONFIG` — Full contents of your `rclone.conf` file (use `\n` for newlines)

## Optional Environment Variables
- `MONGODB_URI` — MongoDB connection URI for persistent task history

## User Preferences
- No frontend; this is a pure backend Telegram bot worker process
