import os
import tempfile
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

class Settings:
    def __init__(self):
        # 1. Telegram Bot Token & API Details
        self.BOT_TOKEN = os.getenv("BOT_TOKEN")
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN environment variable is required!")
            
        self.API_ID = int(os.getenv("API_ID", 0))
        if not self.API_ID:
            raise ValueError("API_ID environment variable is required!")
            
        self.API_HASH = os.getenv("API_HASH")
        if not self.API_HASH:
            raise ValueError("API_HASH environment variable is required!")

        # 2. Admin ID(s)
        admin_id_raw = os.getenv("ADMIN_ID")
        if not admin_id_raw:
            raise ValueError("ADMIN_ID environment variable is required!")
        
        self.ADMIN_IDS = []
        for x in admin_id_raw.split(","):
            val = x.strip()
            if val.isdigit():
                self.ADMIN_IDS.append(int(val))
            elif val:
                # Support negative IDs if chat/channel IDs are used
                try:
                    self.ADMIN_IDS.append(int(val))
                except ValueError:
                    pass
        
        if not self.ADMIN_IDS:
            raise ValueError("No valid integers found in ADMIN_ID!")

        # 3. Drive Destination
        self.DRIVE_DESTINATION = os.getenv("DRIVE_DESTINATION")
        if not self.DRIVE_DESTINATION:
            raise ValueError("DRIVE_DESTINATION environment variable is required (e.g. gdrive:cloned_files)!")
        
        if ":" not in self.DRIVE_DESTINATION:
            raise ValueError("DRIVE_DESTINATION must be in the format 'remote_name:path' (e.g., 'gdrive:cloned_files')!")
        
        self.REMOTE_NAME = self.DRIVE_DESTINATION.split(":")[0]
        self.DEST_PATH = self.DRIVE_DESTINATION.split(":", 1)[1]

        # 4. MongoDB URI (Optional)
        self.MONGODB_URI = os.getenv("MONGODB_URI")

        # 5. Rclone Config Content (Optional if running locally)
        self.RCLONE_CONFIG_CONTENT = os.getenv("RCLONE_CONFIG")
        
        if self.RCLONE_CONFIG_CONTENT:
            # Write Rclone Config to temporary file (useful for Replit)
            self.RCLONE_CONFIG_PATH = self._write_rclone_config()
        else:
            # Fallback for local PC execution
            default_path = os.path.expanduser("~/.config/rclone/rclone.conf")
            windows_path = os.path.expanduser("~/AppData/Roaming/rclone/rclone.conf")
            
            if os.path.exists(windows_path):
                self.RCLONE_CONFIG_PATH = windows_path
            elif os.path.exists(default_path):
                self.RCLONE_CONFIG_PATH = default_path
            else:
                raise ValueError("RCLONE_CONFIG environment variable is required on server, or rclone.conf must exist locally!")

    def _write_rclone_config(self) -> str:
        """Writes the Rclone configuration contents to a temporary file."""
        # Replace literal \n sequence with actual newlines to support simple env strings
        content = self.RCLONE_CONFIG_CONTENT.replace("\\n", "\n").replace("\n\n", "\n")
        
        # Write to a file in the workspace to ensure it persists and remains accessible
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "temp_rclone.conf"))
        
        # Ensure directory exists (should be root)
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        print(f"[Config] Dynamic rclone config written successfully to: {config_path}")
        return config_path

# Global config instance
settings = Settings()
