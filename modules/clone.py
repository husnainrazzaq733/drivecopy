import re
import logging
import urllib.request
import urllib.error
from telegram import Update
from telegram.ext import ContextTypes
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
                    logger.info(f"Successfully scraped GDrive name: '{title}' for ID {gdrive_id}")
                    return title
    except Exception as e:
        logger.warning(f"Could not scrape GDrive name for ID {gdrive_id}: {e}")
        
    # Standard clean fallback
    return f"{link_type}_{gdrive_id}"

@admin_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages, detects Google Drive links, and queues cloning tasks."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    
    # Parse link
    parsed = parse_gdrive_link(text)
    if not parsed:
        await update.message.reply_text(
            "❌ **Invalid Google Drive Link!**\n\n"
            "Please send a valid Google Drive file or folder link, e.g.:\n"
            "• `https://drive.google.com/file/d/FILE_ID/view`\n"
            "• `https://drive.google.com/drive/folders/FOLDER_ID`",
            parse_mode="Markdown"
        )
        return

    link_type, gdrive_id = parsed
    
    # Check if this link is already active or queued for this user
    user_id = update.effective_user.id
    user_tasks = task_queue.get_user_tasks(user_id)
    
    # Prevent user from submitting multiple parallel jobs to keep the server stable
    if len(user_tasks) >= 3:
        await update.message.reply_text(
            "⚠️ **Queue Limit Exceeded!**\n"
            "You already have 3 active or pending tasks. "
            "Please wait for them to finish or cancel one with `/cancel` before queueing more."
        )
        return

    # Send initial queuing response
    status_msg = await update.message.reply_text(
        "⏳ **Fetching Google Drive metadata...**",
        parse_mode="Markdown"
    )

    # Scrape actual file/folder name inside executor to avoid blocking the asyncio event loop
    loop = asyncio.get_running_loop()
    dest_name = await loop.run_in_executor(None, scrape_gdrive_name, link_type, gdrive_id)

    # Add task to queue
    task = await task_queue.add_task(user_id, text, link_type, dest_name, status_msg)
    
    # Get queue position
    pos = task_queue.get_queue_position(task.task_id)
    
    if pos > 0:
        # Task is pending in queue
        await status_msg.edit_text(
            f"📥 **Task Queued**\n"
            f"📂 **Name**: `{dest_name}`\n"
            f"🔗 **Type**: `{link_type.capitalize()}`\n"
            f"📊 **Position in queue**: `{pos}`\n\n"
            f"⚡ _Please wait, your task will start automatically..._",
            parse_mode="Markdown"
        )
    else:
        # Task is starting immediately
        await status_msg.edit_text(
            f"🌀 **Initializing Clone Task...**\n"
            f"📂 **Name**: `{dest_name}`\n"
            f"🔗 **Type**: `{link_type.capitalize()}`",
            parse_mode="Markdown"
        )
