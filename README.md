# 🚀 Advanced Telegram Google Drive Cloner Bot (Rclone)

A complete, production-ready, fully asynchronous Python Telegram bot that copies Google Drive files and folders to your own Google Drive using Rclone. The bot is fully optimized for containerized environments and is ready to deploy directly on **Railway**.

---

## ✨ Features

- **File & Folder Detection**: Automatically detects whether the sent Google Drive URL is a file or a folder.
- **Server-Side Cloning**: Utilizes Rclone's `--drive-server-side-across-configs` for ultra-fast, server-side copying within Google Drive (doesn't consume local/bot bandwidth!).
- **JSON Log Progress Tracker**: Captures Rclone's real-time JSON statistics, updating Telegram dynamically with:
  - 📂 **File Name** currently being transferred
  - 📊 **Percentage Completed** (with visual progress bar)
  - ⚡ **Speed** (e.g., `45.2 MB/s`)
  - 📦 **Transferred Size** / Total Size (e.g., `1.2 GB / 5.0 GB`)
  - ⏳ **ETA** (Estimated Time of Arrival)
- **Task Queue**: Processes requests sequentially, letting users queue multiple transfers without overloading the system.
- **Task Cancellation**: Cancel currently active transfers using `/cancel` instantly.
- **Admin System**: Restricted to authorized users specified via `ADMIN_ID` environment variable.
- **Flexible Database**: Connects to **MongoDB** for task history logs, or automatically falls back to local JSON file storage (`logs/history.json`) if MongoDB is not provided.
- **Stateless & Containerized**: Reads Rclone configuration directly from environment variables and deploys seamlessly on **Railway** via Docker.

---

## 🛠️ Setup & Local Installation

### Prerequisites
- Python 3.11 or higher
- Rclone installed on your local machine (if testing locally)
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather)

### Step 1: Clone and Install Dependencies
```bash
git clone <repository-url>
cd google-tele
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
Create a `.env` file in the root directory (use `.env.example` as a template):
```env
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
ADMIN_ID=YOUR_TELEGRAM_USER_ID
DRIVE_DESTINATION=gdrive:cloned_files
RCLONE_CONFIG="[gdrive]\ntype = drive\nscope = drive\n..."
```
> 💡 **Tip**: For `RCLONE_CONFIG`, open your local `rclone.conf` (located in `~/.config/rclone/rclone.conf` on Linux/macOS or `%APPDATA%/rclone/rclone.conf` on Windows) and paste its entire contents. Replace newline characters with `\n` if needed, or simply write them out.

### Step 3: Run the Bot Locally
```bash
python -m bot.main
```

---

## 🤖 Telegram Commands

- `/start` - Start the bot, receive a beautiful greeting and instructions.
- `/help` - View detailed usage guide and command descriptions.
- `/ping` - Check the bot's server latency and connection status.
- `/stats` - View current task queue size, active transfer stats, and overall clone history.
- `/cancel` - Cancel your currently running copy task immediately.

---

## ☁️ Railway Deployment Guide

This project is fully designed for **Railway** deployment.

### Method 1: Deploy with Dockerfile (Recommended & Easiest)
Railway automatically detects the `Dockerfile` in the root folder, installs system dependencies (including Rclone), installs Python packages, and boots up.

1. Create a new project on **Railway**.
2. Link your GitHub repository.
3. Configure the following environment variables in the **Variables** tab:
   - `BOT_TOKEN`: Your Telegram Bot Token.
   - `ADMIN_ID`: Your Telegram numeric User ID (you can get this from [@userinfobot](https://t.me/userinfobot)).
   - `DRIVE_DESTINATION`: Your Google Drive remote destination path (e.g. `gdrive:cloned_files`).
   - `RCLONE_CONFIG`: The complete contents of your `rclone.conf` file.
   - `MONGODB_URI` *(Optional)*: A MongoDB connection string (e.g., from a free MongoDB Atlas cluster). If not set, it will persist history to a local JSON file inside the container (non-persistent across restarts, but fine for normal usage).
4. Click **Deploy**. Railway will build the container and start running the bot!

---

## 📂 Project Structure

```text
├── bot/
│   ├── __init__.py
│   └── main.py             # App entry point
├── config/
│   ├── __init__.py
│   └── settings.py         # Config & env validation
├── modules/
│   ├── __init__.py
│   ├── commands.py         # Bot commands (/start, /help, etc.)
│   └── clone.py            # Link processing and progress updates
├── utils/
│   ├── __init__.py
│   ├── rclone.py           # Rclone execution wrapper
│   ├── queue.py            # Async Task Queue
│   ├── database.py         # MongoDB & JSON fallback storage
│   └── helpers.py          # Formatters & Link parsers
├── logs/                   # Local logs directory
├── Dockerfile              # Container spec
├── requirements.txt        # Python dependencies
└── Procfile                # Process config for platforms
```

---

## 🔒 Security
- All sensitive tokens and configs are loaded through environment variables.
- Direct links are validated strictly before any Rclone operations.
- Unauthorized Telegram users are blocked at the middleware level, protecting your Google Drive from abuse.
