import os
import tempfile
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

class Settings:
    def __init__(self):
        # 1. Telegram Bot Token
        self.BOT_TOKEN = os.getenv("BOT_TOKEN")
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN environment variable is required!")

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

        # 5. Rclone Config Content
        self.RCLONE_CONFIG_CONTENT = os.getenv("RCLONE_CONFIG")
        if not self.RCLONE_CONFIG_CONTENT:
            raise ValueError("RCLONE_CONFIG environment variable is required!")

        # Write Rclone Config to temporary file
        self.RCLONE_CONFIG_PATH = self._write_rclone_config()

    def _write_rclone_config(self) -> str:
        """Writes the Rclone configuration contents to a temporary file."""
        # Replace literal \n sequences with actual newlines
        content = self.RCLONE_CONFIG_CONTENT.replace("\\n", "\n")

        # If the config ended up on a single line (no newlines), reconstruct proper
        # rclone INI format. The format is: [Section] key = val key = val ...
        # We must not split inside JSON values (which use {} braces).
        if "\n" not in content and "[" in content:
            content = self._fix_inline_config(content)

        # Remove double blank lines that can appear after reconstruction
        while "\n\n\n" in content:
            content = content.replace("\n\n\n", "\n\n")

        # Write to a file in the workspace
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "temp_rclone.conf"))
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"[Config] Dynamic rclone config written successfully to: {config_path}")
        return config_path

    @staticmethod
    def _fix_inline_config(content: str) -> str:
        """
        Converts a single-line rclone config into proper INI format.
        Inserts newlines before section headers and key=value pairs,
        while respecting JSON values inside {} braces.
        """
        result = []
        i = 0
        n = len(content)

        while i < n:
            ch = content[i]

            # Section header: insert newline before '[' unless at start
            if ch == "[":
                if result and result[-1] not in ("\n",):
                    result.append("\n")
                # Read to closing ']'
                j = content.index("]", i)
                result.append(content[i:j + 1])
                result.append("\n")
                i = j + 1
                # Skip trailing space after ']'
                while i < n and content[i] == " ":
                    i += 1
                continue

            # Key=value pair: read key name
            # A key starts at a non-space position after a newline or space
            if ch != " " and ch != "\n":
                # Collect key name
                j = i
                while j < n and content[j] not in (" ", "=", "\n"):
                    j += 1
                key = content[i:j]

                # Skip spaces before '='
                k = j
                while k < n and content[k] == " ":
                    k += 1

                if k < n and content[k] == "=":
                    # This is a key = value pair
                    result.append(key)
                    result.append(" = ")
                    k += 1  # skip '='
                    # Skip spaces after '='
                    while k < n and content[k] == " ":
                        k += 1
                    i = k
                    # Read value — careful with {} JSON blobs
                    depth = 0
                    while i < n:
                        c = content[i]
                        if c == "{":
                            depth += 1
                            result.append(c)
                            i += 1
                        elif c == "}":
                            depth -= 1
                            result.append(c)
                            i += 1
                        elif depth == 0 and c == " ":
                            # Space outside JSON — potential key separator
                            # Peek ahead: if next non-space chars look like 'word =' it's a new key
                            peek = i + 1
                            while peek < n and content[peek] == " ":
                                peek += 1
                            # Read potential next key
                            pk = peek
                            while pk < n and content[pk] not in (" ", "=", "\n", "["):
                                pk += 1
                            next_word = content[peek:pk]
                            # Skip spaces after next_word
                            pk2 = pk
                            while pk2 < n and content[pk2] == " ":
                                pk2 += 1
                            is_new_key = (
                                pk2 < n and content[pk2] == "=" and
                                bool(next_word) and next_word.replace("_", "").isalnum()
                            )
                            is_new_section = peek < n and content[peek] == "["
                            if is_new_key or is_new_section:
                                result.append("\n")
                                i = peek
                                break
                            else:
                                result.append(c)
                                i += 1
                        elif depth == 0 and c == "\n":
                            i += 1
                            break
                        else:
                            result.append(c)
                            i += 1
                    result.append("\n")
                else:
                    # Not a key=value, just copy
                    result.append(key)
                    i = j
            else:
                if ch != " " and ch != "\n":
                    result.append(ch)
                i += 1

        return "".join(result)

# Global config instance
settings = Settings()
