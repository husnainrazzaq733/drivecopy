import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler

from config.settings import settings
from utils.queue import task_queue
from utils.rclone import check_rclone_installed
from modules.commands import (
    start_command,
    help_command,
    ping_command,
    stats_command,
    cancel_command,
    setfolder_command,
)
from modules.clone import handle_message
from utils.keep_alive import keep_alive

# Set up directories
os.makedirs("logs", exist_ok=True)

# Configure logging
log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Console logging
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_format)

# File logging with rotation (10MB max, 5 backups)
file_handler = RotatingFileHandler("logs/bot.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
file_handler.setFormatter(log_format)

logging.basicConfig(
    level=logging.INFO,
    handlers=[console_handler, file_handler]
)

logger = logging.getLogger("bot.main")

from pyrogram import idle
import asyncio

async def async_main():
    """Main entry point to bootstrap the Telegram Bot using Pyrogram."""
    logger.info("==============================================")
    logger.info("    Starting GDrive Rclone Telegram Bot...    ")
    logger.info("==============================================")

    # 1. Diagnostic Checks
    if not check_rclone_installed():
        logger.warning(
            "⚠️ Rclone binary is not found in system PATH! "
            "Please ensure Rclone is installed otherwise clone operations will fail."
        )
    else:
        logger.info("✅ Rclone binary verified and operational.")

    logger.info(f"Target Google Drive Destination: '{settings.DRIVE_DESTINATION}'")
    logger.info(f"Configured Authorized Admins: {settings.ADMIN_IDS}")

    # 2. Build the Pyrogram Client
    app = Client(
        "drive_bot",
        api_id=settings.API_ID,
        api_hash=settings.API_HASH,
        bot_token=settings.BOT_TOKEN,
        max_concurrent_transmissions=8,
    )

    # 3. Register Command Handlers
    app.add_handler(MessageHandler(start_command, filters.command("start")))
    app.add_handler(MessageHandler(help_command, filters.command("help")))
    app.add_handler(MessageHandler(ping_command, filters.command("ping")))
    app.add_handler(MessageHandler(stats_command, filters.command("stats")))
    app.add_handler(MessageHandler(cancel_command, filters.command("cancel")))
    app.add_handler(MessageHandler(setfolder_command, filters.command("setfolder")))

    # 4. Register Message Handlers (specifically intercepting links or texts from Admins)
    app.add_handler(MessageHandler(handle_message))

    # Start background task queue
    logger.info("Initializing background task queue...")
    task_queue.start()

    # 5. Start Keep-Alive Server (For Replit)
    logger.info("Starting Keep-Alive web server...")
    keep_alive()

    # 6. Start Polling for updates
    logger.info("Bot is active and polling for updates... Press Ctrl+C to stop.")
    await app.start()
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.run(async_main())

