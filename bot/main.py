import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)
from config.settings import settings
from utils.queue import task_queue
from utils.rclone import check_rclone_installed
from modules.commands import (
    start_command,
    help_command,
    ping_command,
    stats_command,
    cancel_command,
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

async def post_init(application: Application) -> None:
    """This function is called by the application after initialization but before starting."""
    logger.info("Initializing background task queue...")
    task_queue.start()
    logger.info("Background task queue successfully started.")

def main():
    """Main entry point to bootstrap the Telegram Bot."""
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

    # 2. Build the Telegram Application
    application = (
        ApplicationBuilder()
        .token(settings.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # 3. Register Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("cancel", cancel_command))

    # 4. Register Message Handlers (specifically intercepting links or texts from Admins)
    application.add_handler(
        MessageHandler(
            ~filters.COMMAND, 
            handle_message
        )
    )

    # 5. Start Keep-Alive Server (For Replit)
    logger.info("Starting Keep-Alive web server...")
    keep_alive()

    # 6. Start Polling for updates
    logger.info("Bot is active and polling for updates... Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
