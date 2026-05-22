import re
import json
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger("bot.helpers")

# Regular expressions for Google Drive links
FOLDER_REGEXES = [
    re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9-_]{25,})"),
    re.compile(r"drive\.google\.com/drive/mobile/folders/([a-zA-Z0-9-_]{25,})"),
]

FILE_REGEXES = [
    re.compile(r"drive\.google\.com/file/d/([a-zA-Z0-9-_]{25,})"),
    re.compile(r"drive\.google\.com/open\?id=([a-zA-Z0-9-_]{25,})"),
    re.compile(r"docs\.google\.com/(?:document|spreadsheets|presentation|forms|drawings)/d/([a-zA-Z0-9-_]{25,})"),
]

def parse_gdrive_link(url: str) -> Optional[Tuple[str, str]]:
    """
    Parses a Google Drive URL and extracts (link_type, gdrive_id).
    Returns None if URL is invalid.
    """
    if not url or not isinstance(url, str):
        return None

    # Check folders first
    for regex in FOLDER_REGEXES:
        match = regex.search(url)
        if match:
            return "folder", match.group(1)

    # Check files next
    for regex in FILE_REGEXES:
        match = regex.search(url)
        if match:
            return "file", match.group(1)

    return None

def format_bytes(bytes_count: int) -> str:
    """Formats raw bytes count to human-readable size."""
    if bytes_count is None:
        return "0 B"
    bytes_count = float(bytes_count)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.2f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.2f} EB"

def format_speed(bytes_per_sec: float) -> str:
    """Formats bytes per second to human-readable speed."""
    if not bytes_per_sec:
        return "0 B/s"
    return f"{format_bytes(int(bytes_per_sec))}/s"

def format_eta(seconds: Optional[float]) -> str:
    """Formats seconds to human-readable ETA (e.g. 1h 2m 3s)."""
    if seconds is None or seconds < 0:
        return "Unknown"
    
    seconds = int(seconds)
    if seconds == 0:
        return "0s"
        
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    eta_str = ""
    if hours > 0:
        eta_str += f"{hours}h "
    if minutes > 0:
        eta_str += f"{minutes}m "
    if seconds > 0 or not eta_str:
        eta_str += f"{seconds}s"
        
    return eta_str.strip()

def build_progress_bar(percentage: float, length: int = 10) -> str:
    """Creates a visual progress bar string (e.g. █████░░░░░)."""
    percentage = max(0.0, min(100.0, percentage))
    filled_len = int(round(length * percentage / 100))
    bar = "█" * filled_len + "░" * (length - filled_len)
    return bar

def parse_rclone_log_line(line: str) -> Optional[Dict]:
    """
    Parses Rclone's JSON log line when --use-json-log is active.
    Extracts stats if present.
    """
    if not line:
        return None

    try:
        data = json.loads(line.strip())
        
        # Check if this log entry contains stats
        if "stats" in data:
            stats = data["stats"]
            
            percentage = stats.get("percentage", 0.0)
            speed = stats.get("speed", 0.0)
            transferred = stats.get("bytes", 0)
            total = stats.get("totalBytes", 0)
            eta = stats.get("eta")
            
            # Active file name detection from 'transferring' array
            active_file = "Calculating..."
            transferring_list = stats.get("transferring")
            if transferring_list and isinstance(transferring_list, list) and len(transferring_list) > 0:
                # Get the first transferring file
                active_file = transferring_list[0].get("name", "Calculating...")
            
            return {
                "percentage": percentage,
                "speed_raw": speed,
                "speed": format_speed(speed),
                "transferred_bytes": transferred,
                "transferred": format_bytes(transferred),
                "total_bytes": total,
                "total": format_bytes(total) if total else "Unknown",
                "eta_raw": eta,
                "eta": format_eta(eta) if eta is not None else "Unknown",
                "active_file": active_file,
                "is_stats": True
            }
            
        # Standard info/error logging line
        return {
            "is_stats": False,
            "level": data.get("level", "info"),
            "msg": data.get("msg", ""),
            "time": data.get("time", "")
        }
    except json.JSONDecodeError:
        # Plain-text rclone log format: "YYYY/MM/DD HH:MM:SS LEVEL  : message"
        stripped = line.strip()
        import re as _re
        m = _re.match(r'\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} (INFO|NOTICE|WARNING|ERROR|CRITICAL|DEBUG)\s*:?\s*(.*)', stripped)
        if m:
            raw_level = m.group(1).upper()
            msg = m.group(2).strip()
            level = "error" if raw_level in ("ERROR", "CRITICAL") else "info"
            return {
                "is_stats": False,
                "level": level,
                "msg": msg,
                "time": ""
            }
        # Unknown non-JSON line — only treat as error if it looks like one
        if any(w in stripped.lower() for w in ("error", "fatal", "critical", "failed", "didn't")):
            return {"is_stats": False, "level": "error", "msg": stripped, "time": ""}
        return {"is_stats": False, "level": "info", "msg": stripped, "time": ""}
    except Exception as e:
        logger.error(f"Error parsing log line: {e}")
        return None
