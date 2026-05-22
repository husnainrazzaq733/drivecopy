import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from telegram import Message
from telegram.error import TelegramError
from utils.database import db
from utils.rclone import run_rclone_task, cancel_rclone_task
from utils.helpers import build_progress_bar

logger = logging.getLogger("bot.queue")

class CloneTask:
    def __init__(
        self, 
        user_id: int, 
        url: str,
        gdrive_id: str,
        link_type: str, 
        dest_name: str, 
        message: Message
    ):
        self.task_id = str(uuid.uuid4())[:8]  # Compact 8-char ID
        self.user_id = user_id
        self.url = url
        self.gdrive_id = gdrive_id
        self.link_type = link_type
        self.dest_name = dest_name
        self.message = message  # Telegram message to edit with progress
        self.status = "pending"
        self.created_at = datetime.utcnow()
        self.progress: Dict = {
            "percentage": 0.0,
            "speed": "0 B/s",
            "transferred": "0 B",
            "total": "Unknown",
            "eta": "Unknown",
            "active_file": "Initializing..."
        }

class TaskQueue:
    def __init__(self):
        self.pending_tasks: List[CloneTask] = []
        self.active_task: Optional[CloneTask] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def start(self):
        """Starts the queue background worker."""
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._worker_loop())
            logger.info("Task Queue worker started.")

    async def add_task(
        self, 
        user_id: int, 
        url: str,
        gdrive_id: str,
        link_type: str, 
        dest_name: str, 
        message: Message
    ) -> CloneTask:
        """Adds a new cloning task to the queue."""
        task = CloneTask(user_id, url, gdrive_id, link_type, dest_name, message)
        
        # Save to database
        db.add_task(task.task_id, user_id, url, link_type)
        
        async with self._lock:
            self.pending_tasks.append(task)
            logger.info(f"Task {task.task_id} added to queue. Position: {len(self.pending_tasks)}")
        
        return task

    async def cancel_task(self, task_id: str, user_id: int) -> bool:
        """Cancels a task if it is running or pending in the queue."""
        # 1. Check if it is the active task
        if self.active_task and self.active_task.task_id == task_id:
            logger.info(f"Request to cancel active task: {task_id}")
            # Rclone runner will terminate, causing process exit, marking it as canceled
            canceled = cancel_rclone_task(task_id)
            if canceled:
                self.active_task.status = "canceled"
                db.update_task(task_id, {
                    "status": "canceled",
                    "end_time": datetime.utcnow().isoformat()
                })
                return True

        # 2. Check if it is in the pending queue
        async with self._lock:
            for task in self.pending_tasks:
                if task.task_id == task_id:
                    self.pending_tasks.remove(task)
                    task.status = "canceled"
                    db.update_task(task_id, {
                        "status": "canceled",
                        "end_time": datetime.utcnow().isoformat()
                    })
                    logger.info(f"Task {task_id} removed from pending queue.")
                    return True
                    
        return False

    def get_queue_position(self, task_id: str) -> int:
        """Returns the 1-based queue position of a pending task, or 0 if not pending."""
        for idx, task in enumerate(self.pending_tasks):
            if task.task_id == task_id:
                return idx + 1
        return 0

    def get_active_task_for_user(self, user_id: int) -> Optional[CloneTask]:
        """Gets the currently active/running task for a specific user."""
        if self.active_task and self.active_task.user_id == user_id:
            return self.active_task
        return None

    def get_user_tasks(self, user_id: int) -> List[CloneTask]:
        """Gets all pending and active tasks for a user."""
        tasks = []
        if self.active_task and self.active_task.user_id == user_id:
            tasks.append(self.active_task)
        for task in self.pending_tasks:
            if task.user_id == user_id:
                tasks.append(task)
        return tasks

    async def _worker_loop(self):
        """Infinite worker loop to process queued tasks sequentially."""
        while True:
            try:
                next_task = None
                async with self._lock:
                    if self.pending_tasks:
                        next_task = self.pending_tasks.pop(0)
                        self.active_task = next_task
                
                if next_task:
                    logger.info(f"Worker processing task {next_task.task_id}")
                    await self._process_task(next_task)
                    self.active_task = None
                else:
                    await asyncio.sleep(2)
            except Exception as e:
                logger.exception(f"Error in queue worker loop: {e}")
                await asyncio.sleep(5)

    async def _process_task(self, task: CloneTask):
        """Runs the Rclone process and handles live Telegram updates."""
        task.status = "running"
        db.update_task(task.task_id, {"status": "running"})

        last_update_time = datetime.utcnow()
        try:
            # Send initial progress message
            initial_text = (
                f"⚡ **Task Started**\n"
                f"📂 **Name**: `{task.dest_name}`\n"
                f"🔗 **Type**: `{task.link_type.capitalize()}`\n"
                f"⏳ **Status**: Initializing Rclone..."
            )
            await self._safe_edit_message(task.message, initial_text)

            # Start Rclone async generator
            error_occurred = False
            error_msg = ""
            
            async for update in run_rclone_task(task.link_type, task.gdrive_id, task.dest_name, task.task_id):
                if not update:
                    continue
                
                if not update.get("is_stats") and update.get("level") == "error":
                    error_occurred = True
                    error_msg = update.get("msg", "Unknown error")
                    continue
                
                # We received standard statistics update
                if update.get("is_stats"):
                    # Handle custom errors returned inside progress
                    if "error" in update:
                        error_occurred = True
                        error_msg = update["error"]
                        break

                    task.progress.update(update)

                    # Update database periodically
                    db.update_task(task.task_id, {
                        "total_bytes": update.get("total_bytes", 0),
                        "transferred_bytes": update.get("transferred_bytes", 0),
                        "speed": update.get("speed", "0 B/s")
                    })

                    # Throttle Telegram edits to prevent rate limits (max once every 2 seconds)
                    now = datetime.utcnow()
                    if (now - last_update_time).total_seconds() >= 2.0:
                        checks = update.get("checks", 0)
                        transfers = update.get("transfers", 0)
                        transferred_bytes = update.get("transferred_bytes", 0)
                        is_scanning = transferred_bytes == 0 and checks > 0 and transfers == 0

                        if is_scanning:
                            progress_text = (
                                f"🔍 **Scanning Files...**\n"
                                f"📂 **Name**: `{task.dest_name}`\n"
                                f"🔗 **Type**: `{task.link_type.capitalize()}`\n\n"
                                f"├─ 📋 **Files scanned**: `{checks}`\n"
                                f"└─ ⏳ **Please wait...**\n\n"
                                f"🚫 Use `/cancel` to stop this task."
                            )
                        else:
                            progress_bar = build_progress_bar(update["percentage"])
                            progress_text = (
                                f"🌀 **Cloning Content...**\n"
                                f"📂 **Name**: `{task.dest_name}`\n\n"
                                f"├─ {progress_bar} ({update['percentage']:.1f}%)\n"
                                f"├─ ⚡ **Speed**: `{update['speed']}`\n"
                                f"├─ 📦 **Transferred**: `{update['transferred']} / {update['total']}`\n"
                                f"├─ ⏳ **ETA**: `{update['eta']}`\n"
                                f"└─ 📄 **Active**: `{update['active_file']}`\n\n"
                                f"🚫 Use `/cancel` to stop this task."
                            )
                        await self._safe_edit_message(task.message, progress_text)
                        last_update_time = now

            # If task didn't hit error or get canceled
            if task.status == "running":
                if error_occurred:
                    await self._handle_failed_task(task, error_msg)
                else:
                    await self._handle_completed_task(task)
            elif task.status == "canceled":
                canceled_text = (
                    f"❌ **Task Canceled Successfully**\n"
                    f"📂 **Name**: `{task.dest_name}`\n"
                    f"⏱️ **Duration**: {int((datetime.utcnow() - task.created_at).total_seconds())}s"
                )
                await self._safe_edit_message(task.message, canceled_text)

        except asyncio.CancelledError:
            # Task was canceled internally
            logger.warning(f"Task {task.task_id} asyncio task cancelled.")
            await self._handle_canceled_task(task)
        except Exception as e:
            logger.exception(f"Error processing task {task.task_id}: {e}")
            await self._handle_failed_task(task, str(e))

    async def _handle_completed_task(self, task: CloneTask):
        task.status = "completed"
        db.update_task(task.task_id, {
            "status": "completed",
            "end_time": datetime.utcnow().isoformat()
        })
        
        success_text = (
            f"✅ **Cloning Completed!**\n"
            f"📂 **Name**: `{task.dest_name}`\n"
            f"🔗 **Type**: `{task.link_type.capitalize()}`\n"
            f"📦 **Total Transferred**: `{task.progress.get('transferred', 'Unknown')}`\n"
            f"⏱️ **Total Time**: {int((datetime.utcnow() - task.created_at).total_seconds())}s"
        )
        await self._safe_edit_message(task.message, success_text)
        logger.info(f"Task {task.task_id} completed successfully.")

    async def _handle_failed_task(self, task: CloneTask, error_msg: str):
        task.status = "failed"
        db.update_task(task.task_id, {
            "status": "failed",
            "error_message": error_msg,
            "end_time": datetime.utcnow().isoformat()
        })
        
        failed_text = (
            f"⚠️ **Cloning Failed**\n"
            f"📂 **Name**: `{task.dest_name}`\n"
            f"❌ **Error**: `{error_msg}`"
        )
        await self._safe_edit_message(task.message, failed_text)
        logger.error(f"Task {task.task_id} failed: {error_msg}")

    async def _handle_canceled_task(self, task: CloneTask):
        task.status = "canceled"
        db.update_task(task.task_id, {
            "status": "canceled",
            "end_time": datetime.utcnow().isoformat()
        })
        canceled_text = (
            f"❌ **Task Canceled**\n"
            f"📂 **Name**: `{task.dest_name}`\n"
            f"⏱️ **Duration**: {int((datetime.utcnow() - task.created_at).total_seconds())}s"
        )
        await self._safe_edit_message(task.message, canceled_text)

    async def _safe_edit_message(self, message: Message, text: str):
        """Safely edits a Telegram message, catching common API exceptions."""
        try:
            await message.edit_text(text, parse_mode="Markdown")
        except TelegramError as e:
            err_str = str(e)
            if "Message is not modified" in err_str:
                return
            # If Markdown parsing failed, retry as plain text
            if "can't parse" in err_str.lower() or "parse" in err_str.lower():
                try:
                    plain = text.replace("**", "").replace("`", "").replace("_", "")
                    await message.edit_text(plain)
                except TelegramError:
                    pass
            else:
                logger.error(f"Telegram error editing message: {e}")

# Global task queue instance
task_queue = TaskQueue()
