import time
import logging
from datetime import datetime
from pyrogram import Client
from pyrogram.types import Message
from config.settings import settings
from utils.database import db
from utils.queue import task_queue
from utils.helpers import format_bytes

logger = logging.getLogger("bot.commands")

def admin_only(func):
    """Decorator to restrict commands to users configured in ADMIN_IDS."""
    async def wrapper(client: Client, message: Message, *args, **kwargs):
        if not message.from_user:
            return
        user_id = message.from_user.id
        if user_id not in settings.ADMIN_IDS:
            logger.warning(f"Unauthorized access attempt by User ID {user_id}")
            await message.reply_text("? **Access Denied!**\nYou are not authorized to use this bot.")
            return
        return await func(client, message, *args, **kwargs)
    return wrapper

@admin_only
async def start_command(client: Client, message: Message):
    """Sends greeting message to admin."""
    user = message.from_user
    welcome_text = (
        f"?? **Hello, {user.first_name}!**\n\n"
        f"?? Welcome to **GDrive Rclone Cloner Bot**.\n"
        f"This bot allows you to clone Google Drive files and folders server-side to your own Google Drive using Rclone.\n\n"
        f"?? **How to use**:\n"
        f"Simply send or forward any Google Drive link to this chat (files or folders). The bot will detect the type and start cloning immediately!\n\n"
        f"?? **Available Commands**:\n"
        f"+- /start - Restart / Greeting\n"
        f"+- /help - View detailed usage guide\n"
        f"+- /ping - Check server latency\n"
        f"+- /stats - Check database and queue stats\n"
        f"+- /cancel - Cancel your running clone task\n"
        f"+- /setfolder - Set the destination folder for uploads\n\n"
        f"? _Status: Operational & Ready!_"
    )
    await message.reply_text(welcome_text)

@admin_only
async def help_command(client: Client, message: Message):
    """Sends help instructions to admin."""
    help_text = (
        f"?? **GDrive Cloner Bot Guide**\n\n"
        f"**1. Folder Cloning**:\n"
        f"Send a Google Drive folder link like:\n"
        f"https://drive.google.com/drive/folders/YOUR_FOLDER_ID\n"
        f"The bot will create a folder in your destination Drive and copy all its contents server-side.\n\n"
        f"**2. File Cloning**:\n"
        f"Send a Google Drive file link like:\n"
        f"https://drive.google.com/file/d/YOUR_FILE_ID/view\n"
        f"The bot will copy the file to your destination Drive.\n\n"
        f"? **Why Server-Side Copy?**\n"
        f"By using --drive-server-side-across-configs, the copy happens directly inside Google's network. "
        f"No data is downloaded to the bot's server, making it extremely fast (usually instant for single files, and multi-gigabyte folders copy in seconds!).\n\n"
        f"?? **Task Cancellation**:\n"
        f"If you send a wrong link or want to stop a transfer, type /cancel <task_id>. The active task will be killed safely and the next queued task will start."
    )
    await message.reply_text(help_text)

@admin_only
async def ping_command(client: Client, message: Message):
    """Checks latency/ping."""
    start_time = time.time()
    msg = await message.reply_text("?? **Pinging server...**")
    latency = (time.time() - start_time) * 1000
    await msg.edit_text(f"?? **Pong!**\n? Latency: {latency:.1f} ms")

@admin_only
async def stats_command(client: Client, message: Message):
    """Fetches and displays task database and queue status."""
    db_stats = db.get_stats()
    queue_size = len(task_queue.pending_tasks)
    active_tasks = task_queue.active_tasks.values()
    
    if active_tasks:
        active_status = ""
        for t in active_tasks:
            active_status += f"\n🔄 Running: {t.dest_name} ({t.progress.get('percentage', 0.0):.1f}%)\n  └─ 🛑 Cancel: `/cancel {t.task_id}`"
    else:
        active_status = "?? Idle"

    stats_text = (
        f"?? **GDrive Cloner Stats**\n\n"
        f"?? **Task Queue Status**:\n"
        f"+- **Queue Size**: `{queue_size} pending`\n"
        f"+- **Active Tasks**: {active_status}\n\n"
        f"??? **Database Summary**:\n"
        f"+- **Total Tasks**: `{db_stats['total_tasks']}`\n"
        f"+- **Completed**: `{db_stats['completed']}`\n"
        f"+- **Failed**: `{db_stats['failed']}`\n"
        f"+- **Canceled**: `{db_stats['canceled']}`\n"
        f"+- **Total Transferred**: `{format_bytes(db_stats['total_transferred_bytes'])}`"
    )
    await message.reply_text(stats_text)

@admin_only
async def cancel_command(client: Client, message: Message):
    """Cancels a running cloning task."""
    command_parts = message.text.split()
    if len(command_parts) != 2:
        await message.reply_text("Usage: /cancel <task_id>\n\nUse /stats to see active task IDs.")
        return

    task_id = command_parts[1]
    logger.info(f"Cancel requested for task {task_id} by {message.from_user.id}")
    
    if await task_queue.cancel_task(task_id, message.from_user.id):
        await message.reply_text(f"Task {task_id} cancellation requested.")
    else:
        await message.reply_text(f"Task {task_id} not found, not yours, or already completed.")

@admin_only
async def setfolder_command(client: Client, message: Message):
    """Sets the dynamic destination folder for future uploads."""
    command_parts = message.text.split(" ", 1)
    if len(command_parts) == 1:
        await message.reply_text(
            f"**Current Destination:** {settings.CURRENT_DESTINATION}\n\n"
            "To change the folder, send the folder name or path.\n"
            "**Examples:**\n"
            "/setfolder Movies\n"
            "/setfolder Software/Windows\n"
            "/setfolder / (to upload to the root of the drive)"
        )
        return
        
    new_folder = command_parts[1].strip()
    
    # Remove leading slashes so it builds correctly
    if new_folder.startswith('/'):
        new_folder = new_folder[1:]
        
    # Build the full destination: fastDrive:FolderName
    if new_folder == "" or new_folder == "/":
        new_dest = settings.DRIVE_REMOTE_NAME
    else:
        new_dest = f"{settings.DRIVE_REMOTE_NAME}{new_folder}"
        
    settings.CURRENT_DESTINATION = new_dest
    await message.reply_text(f"? **Folder Updated Successfully!**\n\nAll new files will now be uploaded to:\n{settings.CURRENT_DESTINATION}")



