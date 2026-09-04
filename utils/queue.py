import asyncio
import logging
import uuid
import os
from datetime import datetime
from typing import Dict, List, Optional
from pyrogram.types import Message
from pyrogram.errors import MessageNotModified
from utils.database import db
from utils.rclone import run_rclone_task, cancel_rclone_task
from utils.helpers import build_progress_bar, format_bytes

logger = logging.getLogger("bot.queue")

class CloneTask:
    def __init__(
        self, 
        user_id: int, 
        url: str, 
        link_type: str, 
        dest_name: str, 
        message: Message
    ):
        self.task_id = str(uuid.uuid4())[:8]
        self.user_id = user_id
        self.url = url
        self.link_type = link_type
        self.dest_name = dest_name
        self.message = message
        self.status = "pending"
        self.created_at = datetime.utcnow()
        self.target_folder = ""
        self.progress: Dict = {
            "percentage": 0.0,
            "speed": "0 B/s",
            "transferred": "0 B",
            "total": "Unknown",
            "eta": "Unknown",
            "active_file": "Initializing...",
            "checks": 0
        }

class TaskQueue:
    def __init__(self):
        self.pending_tasks: List[CloneTask] = []
        self.active_tasks: Dict[str, CloneTask] = {}
        self._workers: List[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self.queue = asyncio.Queue()

    def start(self):
        """Starts the queue background workers."""
        if not self._workers:
            for _ in range(3):
                task = asyncio.create_task(self._worker_loop())
                self._workers.append(task)
            logger.info("3 Task Queue workers started.")

    async def add_task(
        self, 
        user_id: int, 
        url: str, 
        link_type: str, 
        dest_name: str, 
        message: Message
    ) -> CloneTask:
        """Adds a new cloning task to the queue."""
        from config.settings import settings
        task = CloneTask(user_id, url, link_type, dest_name, message)
        task.target_folder = settings.CURRENT_DESTINATION
        
        db.add_task(task.task_id, user_id, url, link_type)
        
        self.pending_tasks.append(task)
        await self.queue.put(task)
        
        logger.info(f"Task {task.task_id} added to queue. Position: {self.get_queue_position(task.task_id)}")
        return task

    async def cancel_task(self, task_id: str, user_id: int) -> bool:
        """Cancels a task if it belongs to the user."""
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            if task.user_id == user_id:
                task.status = "canceled"
                cancel_rclone_task(task_id)
                return True
                
        for i, task in enumerate(self.pending_tasks):
            if task.task_id == task_id and task.user_id == user_id:
                del self.pending_tasks[i]
                
                temp_queue = []
                while not self.queue.empty():
                    item = await self.queue.get()
                    if item.task_id != task_id:
                        temp_queue.append(item)
                for item in temp_queue:
                    await self.queue.put(item)
                    
                db.update_task(task_id, {
                    "status": "canceled",
                    "end_time": datetime.utcnow().isoformat()
                })
                logger.info(f"Task {task_id} removed from pending queue.")
                return True
                
        return False

    def get_queue_position(self, task_id: str) -> int:
        if task_id in self.active_tasks:
            return 0
        for idx, task in enumerate(self.pending_tasks):
            if task.task_id == task_id:
                return idx + 1
        return 0

    def get_user_tasks(self, user_id: int) -> List[CloneTask]:
        tasks = []
        for task in self.active_tasks.values():
            if task.user_id == user_id:
                tasks.append(task)
        for task in self.pending_tasks:
            if task.user_id == user_id:
                tasks.append(task)
        return tasks

    async def _worker_loop(self):
        while True:
            task = await self.queue.get()
            
            async with self._lock:
                if task in self.pending_tasks:
                    self.pending_tasks.remove(task)
            
            if task.status == "canceled":
                self.queue.task_done()
                continue
                
            self.active_tasks[task.task_id] = task
            task.status = "running"
            db.update_task(task.task_id, {"status": "running"})
            
            local_file_path = None
            last_update_time = datetime.utcnow()
            
            try:
                if task.link_type == "telegram_file":
                    try:
                        logger.info(f"Downloading Telegram file {task.dest_name}...")
                        local_file_path = f"/tmp/{task.task_id}_{task.dest_name}"
                        
                        last_update_time = datetime.utcnow()
                        async def progress_callback(current, total, message, dest_name):
                            nonlocal last_update_time
                            now = datetime.utcnow()
                            if (now - last_update_time).total_seconds() >= 4.0:
                                percentage = (current / total) * 100 if total else 0
                                progress_bar = build_progress_bar(percentage)
                                text = (
                                    f"?? **Downloading from Telegram...**\n"
                                    f"?? **Name**: {dest_name}\n\n"
                                    f"?? {progress_bar} ({percentage:.1f}%)\n"
                                    f"?? **Downloaded**: {format_bytes(current)} / {format_bytes(total)}"
                                )
                                asyncio.create_task(self._safe_edit_message(message, text))
                                last_update_time = now

                        client = task.message._client
                        await client.download_media(
                            message=task.url,
                            file_name=local_file_path,
                            progress=progress_callback,
                            progress_args=(task.message, task.dest_name)
                        )
                        
                        task.url = local_file_path
                        task.link_type = "local_file"
                    except Exception as e:
                        logger.error(f"Failed to download Telegram file: {e}")
                        raise Exception(f"Failed to download file from Telegram: {e}")

                error_occurred = False
                error_msg = ""
                last_logs = []
                
                async for update in run_rclone_task(task.link_type, task.url, task.dest_name, task.task_id, task.target_folder):
                    if not update:
                        continue
                    
                    if not update.get("is_stats"):
                        msg = update.get("msg", "")
                        if msg:
                            last_logs.append(str(msg))
                            if len(last_logs) > 5:
                                last_logs.pop(0)
                                
                        if update.get("level") == "error":
                            error_occurred = True
                            error_msg = msg if msg else "Unknown error"
                            continue
                    
                    if update.get("is_stats"):
                        if "error" in update:
                            error_occurred = True
                            error_msg = update["error"]
                            break
                            
                        task.progress.update(update)
                        
                        db.update_task(task.task_id, {
                            "total_bytes": update.get("total_bytes", 0),
                            "transferred_bytes": update.get("transferred_bytes", 0),
                            "speed": update.get("speed", "0 B/s")
                        })
                        
                        now = datetime.utcnow()
                        if (now - last_update_time).total_seconds() >= 4.0:
                            progress_bar = build_progress_bar(update["percentage"])
                            progress_text = (
                                f"?? **Cloning Content...**\n"
                                f"?? **Name**: {task.dest_name}\n\n"
                                f"?? {progress_bar} ({update['percentage']:.1f}%)\n"
                                f"? **Speed**: {update['speed']}\n"
                                f"?? **Transferred**: {update['transferred']} / {update['total']}\n"
                                f"?? **ETA**: {update['eta']}\n"
                                f"?? **Active**: {update['active_file']}\n\n"
                                f"?? Use /cancel {task.task_id} to stop this task."
                            )
                            await self._safe_edit_message(task.message, progress_text)
                            last_update_time = now

                if task.status == "running":
                    if error_occurred:
                        await self._handle_failed_task(task, error_msg)
                    else:
                        await self._handle_completed_task(task, last_logs)
                elif task.status == "canceled":
                    canceled_text = (
                        f"?? **Task Canceled Successfully**\n"
                        f"?? **Name**: {task.dest_name}\n"
                        f"?? **Duration**: {int((datetime.utcnow() - task.created_at).total_seconds())}s"
                    )
                    await self._safe_edit_message(task.message, canceled_text)

            except asyncio.CancelledError:
                logger.warning(f"Task {task.task_id} asyncio task cancelled.")
                await self._handle_canceled_task(task)
            except Exception as e:
                logger.exception(f"Error processing task {task.task_id}: {e}")
                await self._handle_failed_task(task, str(e))
            finally:
                if task.task_id in self.active_tasks:
                    del self.active_tasks[task.task_id]
                self.queue.task_done()
                if local_file_path and os.path.exists(local_file_path):
                    try:
                        os.remove(local_file_path)
                    except:
                        pass

    async def _handle_completed_task(self, task: CloneTask, last_logs: List[str]):
        task.status = "completed"
        db.update_task(task.task_id, {
            "status": "completed",
            "end_time": datetime.utcnow().isoformat()
        })
        
        success_text = (
            f"? **Cloning Completed!**\n"
            f"?? **Name**: {task.dest_name}\n"
            f"?? **Type**: {task.link_type.capitalize()}\n"
            f"?? **Destination**: {task.target_folder}\n"
            f"?? **Total Transferred**: {task.progress.get('transferred', 'Unknown')}\n"
            f"?? **Files Checked/Skipped**: {task.progress.get('checks', 0)}\n"
            f"?? **Total Time**: {int((datetime.utcnow() - task.created_at).total_seconds())}s"
        )
        
        transferred = task.progress.get('transferred', 'Unknown')
        if transferred in ('0 B', 'Unknown') and last_logs:
            logs_str = "\n".join(last_logs)
            success_text += f"\n\n?? **Note:** 0 B transferred. Rclone Output:\n{logs_str[-500:]}"
            
        await self._safe_edit_message(task.message, success_text)

    async def _handle_failed_task(self, task: CloneTask, error_msg: str):
        task.status = "failed"
        db.update_task(task.task_id, {
            "status": "failed",
            "error_message": error_msg,
            "end_time": datetime.utcnow().isoformat()
        })
        
        failed_text = (
            f"?? **Cloning Failed**\n"
            f"?? **Name**: {task.dest_name}\n"
            f"? **Error**: {error_msg}"
        )
        await self._safe_edit_message(task.message, failed_text)

    async def _handle_canceled_task(self, task: CloneTask):
        task.status = "canceled"
        db.update_task(task.task_id, {
            "status": "canceled",
            "end_time": datetime.utcnow().isoformat()
        })
        canceled_text = (
            f"?? **Task Canceled**\n"
            f"?? **Name**: {task.dest_name}\n"
            f"?? **Duration**: {int((datetime.utcnow() - task.created_at).total_seconds())}s"
        )
        await self._safe_edit_message(task.message, canceled_text)

    async def _safe_edit_message(self, message: Message, text: str):
        try:
            await message.edit_text(text)
        except MessageNotModified:
            pass
        except Exception as e:
            logger.error(f"Telegram error editing message: {e}")

task_queue = TaskQueue()

