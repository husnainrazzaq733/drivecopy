import re
import logging
import urllib.request
import urllib.error
import asyncio
from pyrogram import Client
from pyrogram.types import Message
from config.settings import settings
from modules.commands import admin_only
from utils.helpers import parse_gdrive_link
from utils.queue import task_queue

logger = logging.getLogger("bot.clone")

def scrape_gdrive_name(link_type: str, gdrive_id: str) -> str:
    """
    Attempts to scrape the actual file or folder name from Google Drive public URL.
    Falls back to a default folder name if scraping fails or page is private.
    """
    if link_type == "file":
        url = f"https://drive.google.com/file/d/{gdrive_id}/view?usp=sharing"
    else:
        url = f"https://drive.google.com/drive/folders/{gdrive_id}?usp=sharing"
        
    try:
        # Simulate browser request to fetch the initial HTML payload
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9'
            }
        )
        # 5 seconds timeout to keep bot highly responsive
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8', errors='ignore')
            title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()
                # Clean up title by removing Google Drive suffix
                if " - Google Drive" in title:
                    title = title.replace(" - Google Drive", "").strip()
                
                # Check for default or error titles
                if title and title not in ("Google Drive", "Google Drive: Sign-in", "Meet Google Drive – One place for all your files"):
                    # Sanitize title to prevent Telegram Markdown parsing errors
                    title = re.sub(r'[_*\[\]`]', '-', title)
                    logger.info(f"Successfully scraped GDrive name: '{title}' for ID {gdrive_id}")
                    return title
    except Exception as e:
        logger.warning(f"Could not scrape GDrive name for ID {gdrive_id}: {e}")
        
    # Standard clean fallback (using hyphen instead of underscore to prevent Markdown errors)
    return f"{link_type}-{gdrive_id}"

@admin_only
async def handle_message(client: Client, message: Message):
    """Handles text messages and files, detects Google Drive links, and queues cloning tasks."""
    # Ignore commands since we removed the ~filters.command from main.py
    if message.text and message.text.startswith('/'):
        return
    if message.caption and message.caption.startswith('/'):
        return

    # Check for direct file uploads
    file_obj = None
    file_name = None
    
    if message.document:
        file_obj = message.document
        file_name = file_obj.file_name
    elif message.video:
        file_obj = message.video
        file_name = file_obj.file_name or "video.mp4"
    elif message.audio:
        file_obj = message.audio
        file_name = file_obj.file_name or "audio.mp3"
    elif message.photo:
        file_obj = message.photo
        file_name = "photo.jpg"

    if file_obj:
        file_id = file_obj.file_id
        # Size limit check (2GB for bots using Pyrogram)
        if hasattr(file_obj, 'file_size') and file_obj.file_size and file_obj.file_size > 2000 * 1024 * 1024:
            await message.reply_text(
                "❌ **File too large!**\n"
                "The bot can only download files up to 2GB from Telegram. "
                "For larger files, please provide a Google Drive link."
            )
            return

        user_id = message.from_user.id
        user_tasks = task_queue.get_user_tasks(user_id)
        if len(user_tasks) >= 3:
            await message.reply_text(
                "⚠️ **Queue Limit Exceeded!**\n"
                "You already have 3 active or pending tasks. "
                "Please wait for them to finish or cancel one with `/cancel`."
            )
            return

        status_msg = await message.reply_text("⏳ **Queuing Telegram file...**")
        
        try:
            # We use link_type = "telegram_file", url = file_id (which Pyrogram uses)
            task = await task_queue.add_task(user_id, file_id, "telegram_file", file_name, status_msg)
            pos = task_queue.get_queue_position(task.task_id)
            if pos > 0:
                await status_msg.edit_text(
                    f"📥 **Task Queued**\n"
                    f"📂 **Name**: `{file_name}`\n"
                    f"🔗 **Type**: `Telegram File`\n"
                    f"📊 **Position in queue**: `{pos}`\n\n"
                    f"⚡ _Please wait, your task will start automatically..._"
                )
            else:
                await status_msg.edit_text(
                    f"🌀 **Initializing Upload Task...**\n"
                    f"📂 **Name**: `{file_name}`\n"
                    f"🔗 **Type**: `Telegram File`"
                )
        except Exception as e:
            logger.exception(f"Unhandled error in file handler: {e}")
            await status_msg.edit_text(f"❌ **Error Occurred:**\n`{str(e)}`")
        return

    # Fallback to Text processing (Google Drive Links)
    text = message.text or message.caption
    if not text:
        return

    text = text.strip()
    
    # Parse link
    parsed = parse_gdrive_link(text)
    if not parsed:
        await message.reply_text(
            "❌ **Invalid Google Drive Link or File!**\n\n"
            "Please send a valid file directly, or a Google Drive link, e.g.:\n"
            "• `https://drive.google.com/file/d/FILE_ID/view`\n"
            "• `https://drive.google.com/drive/folders/FOLDER_ID`"
        )
        return

    link_type, gdrive_id = parsed
    
    user_id = message.from_user.id
    user_tasks = task_queue.get_user_tasks(user_id)
    
    if len(user_tasks) >= 3:
        await message.reply_text(
            "⚠️ **Queue Limit Exceeded!**\n"
            "You already have 3 active or pending tasks. "
            "Please wait for them to finish or cancel one with `/cancel` before queueing more."
        )
        return

    status_msg = await message.reply_text("⏳ **Fetching Google Drive metadata...**")

    try:
        loop = asyncio.get_running_loop()
        dest_name = await loop.run_in_executor(None, scrape_gdrive_name, link_type, gdrive_id)

        task = await task_queue.add_task(user_id, gdrive_id, link_type, dest_name, status_msg)
        pos = task_queue.get_queue_position(task.task_id)
        
        if pos > 0:
            await status_msg.edit_text(
                f"📥 **Task Queued**\n"
                f"📂 **Name**: `{dest_name}`\n"
                f"🔗 **Type**: `{link_type.capitalize()}`\n"
                f"📊 **Position in queue**: `{pos}`\n\n"
                f"⚡ _Please wait, your task will start automatically..._"
            )
        else:
            await status_msg.edit_text(
                f"🌀 **Initializing Clone Task...**\n"
                f"📂 **Name**: `{dest_name}`\n"
                f"🔗 **Type**: `{link_type.capitalize()}`"
            )
    except Exception as e:
        logger.exception(f"Unhandled error in clone handler: {e}")
        await status_msg.edit_text(f"❌ **Error Occurred:**\n`{str(e)}`")
