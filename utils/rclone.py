import os
import shutil
import asyncio
import logging
from typing import AsyncGenerator, Dict, Optional
from config.settings import settings
from utils.helpers import parse_rclone_log_line

logger = logging.getLogger("bot.rclone")

# Track active subprocesses: task_id -> asyncio.subprocess.Process
_active_processes: Dict[str, asyncio.subprocess.Process] = {}

def check_rclone_installed() -> bool:
    """Checks if Rclone is installed in the system PATH."""
    return shutil.which("rclone") is not None

def cancel_rclone_task(task_id: str) -> bool:
    """Cancels a running Rclone process by killing the subprocess."""
    process = _active_processes.get(task_id)
    if process:
        try:
            logger.info(f"Terminating Rclone process for task {task_id} (PID: {process.pid})")
            process.terminate()
            return True
        except Exception as e:
            logger.error(f"Error terminating process {process.pid}: {e}")
            try:
                process.kill()
                return True
            except Exception:
                pass
    return False

async def run_rclone_task(
    link_type: str, 
    gdrive_id: str, 
    dest_name: str, 
    task_id: str
) -> AsyncGenerator[Dict, None]:
    """
    Asynchronously runs Rclone to copy/clone a GDrive file or folder.
    Yields parsed real-time progress dicts.
    """
    if not check_rclone_installed():
        yield {
            "percentage": 0.0,
            "speed": "0 B/s",
            "transferred": "0 B",
            "total": "Unknown",
            "eta": "Unknown",
            "active_file": "Rclone NOT installed",
            "is_stats": True,
            "error": "Rclone binary was not found in the system PATH!"
        }
        return

    # Build the command based on link type
    if link_type == "folder":
        # Copies folder contents into a subfolder named dest_name
        src = f"{settings.REMOTE_NAME},root_folder_id={gdrive_id}:"
        
        # If destination doesn't end with colon (it has a path), we append /dest_name
        if settings.CURRENT_DESTINATION.endswith(":"):
            dest = f"{settings.CURRENT_DESTINATION}{dest_name}"
        else:
            dest = f"{settings.CURRENT_DESTINATION}/{dest_name}"
            
        cmd = [
            "rclone", "copy", src, dest,
            "--config", settings.RCLONE_CONFIG_PATH,
            "--drive-server-side-across-configs",
            "--transfers", "16",
            "--checkers", "32",
            "--use-json-log",
            "--stats", "2s",
            "--stats-log-level", "NOTICE"
        ]
    elif link_type == "local_file":
        # Copies a local file to the destination folder
        src = gdrive_id  # In this case, gdrive_id contains the local file path
        dest = settings.CURRENT_DESTINATION
        cmd = [
            "rclone", "copy", src, dest,
            "--config", settings.RCLONE_CONFIG_PATH,
            "--transfers", "8",
            "--checkers", "16",
            "--use-json-log",
            "--stats", "2s",
            "--stats-log-level", "NOTICE"
        ]
    else:  # file (Google Drive file)
        # copyid copies a file by ID to the destination directory
        # copyid expects only the path part after the remote name
        remote_name = settings.DRIVE_REMOTE_NAME
        dest_dir = settings.CURRENT_DESTINATION[len(remote_name):]
        if not dest_dir:
            dest_dir = "/"
        else:
            dest_dir = f"{dest_dir}/"
            
        cmd = [
            "rclone", "backend", "copyid",
            remote_name,
            gdrive_id,
            dest_dir,
            "--config", settings.RCLONE_CONFIG_PATH,
            "--drive-server-side-across-configs",
            "--transfers", "16",
            "--checkers", "32",
            "--use-json-log",
            "--stats", "2s",
            "--stats-log-level", "NOTICE"
        ]

    logger.info(f"Starting Rclone command for task {task_id}: {' '.join(cmd)}")

    try:
        # Start async subprocess
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        # Register process for cancellation
        _active_processes[task_id] = process

        # Read stdout line-by-line asynchronously
        # For standard text files, process.stdout.readline() returns a line
        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            
            line = line_bytes.decode('utf-8', errors='ignore').strip()
            parsed = parse_rclone_log_line(line)
            if parsed:
                # If it has error levels or is standard output
                if not parsed.get("is_stats") and parsed.get("level") == "error":
                    logger.error(f"[Rclone Run {task_id}] {parsed.get('msg')}")
                
                yield parsed

        # Wait for process to complete
        return_code = await process.wait()
        logger.info(f"Rclone task {task_id} completed with return code {return_code}")
        
        if return_code != 0 and return_code != -15:  # -15 is SIGTERM (canceled)
            yield {
                "is_stats": False,
                "level": "error",
                "msg": f"Rclone exited with error code {return_code}",
                "exit_code": return_code
            }

    except asyncio.CancelledError:
        logger.warning(f"Rclone execution coroutine for task {task_id} was cancelled.")
        if task_id in _active_processes:
            cancel_rclone_task(task_id)
        raise

    except Exception as e:
        logger.exception(f"Unexpected error executing Rclone task {task_id}: {e}")
        yield {
            "is_stats": False,
            "level": "error",
            "msg": str(e)
        }

    finally:
        # Deregister process
        if task_id in _active_processes:
            del _active_processes[task_id]
