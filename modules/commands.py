import time
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from config.settings import settings
from utils.database import db
from utils.queue import task_queue
from utils.helpers import format_bytes

logger = logging.getLogger("bot.commands")

def admin_only(func):
    """Decorator to restrict commands to users configured in ADMIN_IDS."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user or not update.message:
            return
        user_id = update.effective_user.id
        if user_id not in settings.ADMIN_IDS:
            logger.warning(f"Unauthorized access attempt by User ID {user_id}")
            await update.message.reply_text("❌ **Access Denied!**\nYou are not authorized to use this bot.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

@admin_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends greeting message to admin."""
    user = update.effective_user
    welcome_text = (
        f"👋 **Hello, {user.first_name}!**\n\n"
        f"🤖 Welcome to **GDrive Rclone Cloner Bot**.\n"
        f"This bot allows you to clone Google Drive files and folders server-side to your own Google Drive using Rclone.\n\n"
        f"ℹ️ **How to use**:\n"
        f"Simply send or forward any Google Drive link to this chat (files or folders). The bot will detect the type and start cloning immediately!\n\n"
        f"📌 **Available Commands**:\n"
        f"├─ `/start` - Restart / Greeting\n"
        f"├─ `/help` - View detailed usage guide\n"
        f"├─ `/ping` - Check server latency\n"
        f"├─ `/stats` - Check database and queue stats\n"
        f"└─ `/cancel` - Cancel your running clone task\n\n"
        f"⚡ _Status: Operational & Ready!_"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

@admin_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends help instructions to admin."""
    help_text = (
        f"📖 **GDrive Cloner Bot Guide**\n\n"
        f"**1. Folder Cloning**:\n"
        f"Send a Google Drive folder link like:\n"
        f"`https://drive.google.com/drive/folders/YOUR_FOLDER_ID`\n"
        f"The bot will create a folder in your destination Drive and copy all its contents server-side.\n\n"
        f"**2. File Cloning**:\n"
        f"Send a Google Drive file link like:\n"
        f"`https://drive.google.com/file/d/YOUR_FILE_ID/view`\n"
        f"The bot will copy the file to your destination Drive.\n\n"
        f"🚀 **Why Server-Side Copy?**\n"
        f"By using `--drive-server-side-across-configs`, the copy happens directly inside Google's network. "
        f"No data is downloaded to the bot's server, making it extremely fast (usually instant for single files, and multi-gigabyte folders copy in seconds!).\n\n"
        f"🚫 **Task Cancellation**:\n"
        f"If you send a wrong link or want to stop a transfer, type `/cancel`. The active task will be killed safely and the next queued task will start."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

@admin_only
async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks latency/ping."""
    start_time = time.time()
    msg = await update.message.reply_text("🏓 **Pinging server...**", parse_mode="Markdown")
    latency = (time.time() - start_time) * 1000
    await msg.edit_text(f"🏓 **Pong!**\n⚡ Latency: `{latency:.1f} ms`", parse_mode="Markdown")

@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches and displays task database and queue status."""
    # Get database records stats
    db_stats = db.get_stats()
    
    # Get queue status
    queue_size = len(task_queue.pending_tasks)
    active_task = task_queue.active_task
    
    active_status = "💤 Idle"
    if active_task:
        active_status = (
            f"🌀 Running\n"
            f"  └─ ID: `{active_task.task_id}`\n"
            f"  └─ Name: `{active_task.dest_name}`\n"
            f"  └─ Percentage: `{active_task.progress.get('percentage', 0.0):.1f}%`"
        )

    stats_text = (
        f"📊 **GDrive Cloner Stats**\n\n"
        f"🖥️ **Task Queue Status**:\n"
        f"├─ **Queue Size**: `{queue_size} pending`\n"
        f"└─ **Active Task**: {active_status}\n\n"
        f"🗄️ **Database Summary**:\n"
        f"├─ **Total Tasks**: `{db_stats['total_tasks']}`\n"
        f"├─ **Completed**: `{db_stats['completed']}`\n"
        f"├─ **Failed**: `{db_stats['failed']}`\n"
        f"├─ **Canceled**: `{db_stats['canceled']}`\n"
        f"└─ **Total Transferred**: `{format_bytes(db_stats['total_transferred_bytes'])}`"
    )
    await update.message.reply_text(stats_text, parse_mode="Markdown")

@admin_only
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the active or queued task for the user."""
    user_id = update.effective_user.id
    user_tasks = task_queue.get_user_tasks(user_id)
    
    if not user_tasks:
        await update.message.reply_text("❌ You have no active or pending clone tasks.")
        return
        
    # Cancel the first active/pending task found
    task_to_cancel = user_tasks[0]
    await update.message.reply_text(f"⏳ Attempting to cancel task `{task_to_cancel.task_id}` (`{task_to_cancel.dest_name}`)...")
    
    canceled = await task_queue.cancel_task(task_to_cancel.task_id, user_id)
    if not canceled:
        await update.message.reply_text("❌ Failed to cancel task. It might have already finished.")
