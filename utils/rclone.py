import os
import shutil
import asyncio
import logging
import configparser
import tempfile
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


def _build_src_config(gdrive_id: str, task_id: str) -> str:
    """
    Creates a temporary rclone config file that adds a new source remote
    identical to the main remote but with root_folder_id set to gdrive_id.
    Returns the path to the temp config file.
    The caller is responsible for deleting it.
    """
    config = configparser.RawConfigParser()
    config.read(settings.RCLONE_CONFIG_PATH)

    # Copy the existing remote section into a new temp section
    src_name = f"_src_{task_id}"
    config.add_section(src_name)
    for key, value in config.items(settings.REMOTE_NAME):
        config.set(src_name, key, value)
    config.set(src_name, "root_folder_id", gdrive_id)

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".conf", delete=False, encoding="utf-8"
    )
    config.write(tmp)
    tmp.close()
    return tmp.name, src_name


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

    tmp_config_path = None

    try:
        if link_type == "folder":
            # Build a temp config with a new remote that has root_folder_id = gdrive_id
            tmp_config_path, src_remote = _build_src_config(gdrive_id, task_id)
            src = f"{src_remote}:"
            dest = f"{settings.REMOTE_NAME}:{settings.DEST_PATH}/{dest_name}"
            cmd = [
                "rclone", "copy", src, dest,
                "--config", tmp_config_path,
                "--drive-server-side-across-configs",
                "--transfers", "16",
                "--checkers", "16",
                "--use-json-log",
                "--stats", "2s",
                "--stats-log-level", "NOTICE",
                "-v"
            ]
        else:  # file
            # copyid copies a single file by its Drive ID into the destination folder.
            # Destination is a plain path relative to the remote root (no remote: prefix).
            dest_dir = settings.DEST_PATH + "/"
            cmd = [
                "rclone", "backend", "copyid",
                f"{settings.REMOTE_NAME}:",
                gdrive_id,
                dest_dir,
                "--config", settings.RCLONE_CONFIG_PATH,
                "-v"
            ]

        logger.info(f"Starting Rclone command for task {task_id}: {' '.join(cmd)}")

        # Start async subprocess
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        # Register process for cancellation
        _active_processes[task_id] = process

        # Collect error lines to surface a useful message on failure
        error_lines = []

        # Read stdout line-by-line asynchronously
        while True:
            raw_line = await process.stdout.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            logger.info(f"[Rclone {task_id}] {line}")
            parsed = parse_rclone_log_line(line)
            if parsed:
                if not parsed.get("is_stats") and parsed.get("level") in ("error", "warning"):
                    msg = parsed.get("msg", "")
                    if msg:
                        error_lines.append(msg)
                yield parsed
            else:
                # Non-JSON line (e.g. CRITICAL errors printed before JSON logging starts)
                error_lines.append(line)

        # Wait for process to complete
        return_code = await process.wait()
        logger.info(f"Rclone task {task_id} completed with return code {return_code}")

        if return_code != 0 and return_code != -15:  # -15 is SIGTERM (canceled)
            detail = " | ".join(error_lines[-3:]) if error_lines else f"exit code {return_code}"
            yield {
                "is_stats": False,
                "level": "error",
                "msg": detail,
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
        # Clean up temp config if created
        if tmp_config_path and os.path.exists(tmp_config_path):
            try:
                os.remove(tmp_config_path)
            except Exception:
                pass
