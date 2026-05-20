import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
import pymongo
from config.settings import settings

logger = logging.getLogger("bot.database")

class Database:
    def __init__(self):
        self.mongodb_client: Optional[pymongo.MongoClient] = None
        self.db = None
        self.collection = None
        self.local_db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs", "history.json"))
        
        # Ensure logs directory exists
        os.makedirs(os.path.dirname(self.local_db_path), exist_ok=True)
        
        if settings.MONGODB_URI:
            try:
                logger.info("Connecting to MongoDB...")
                self.mongodb_client = pymongo.MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
                # Test connection
                self.mongodb_client.server_info()
                self.db = self.mongodb_client.get_database("telegram_rclone_bot")
                self.collection = self.db.get_collection("tasks")
                logger.info("Successfully connected to MongoDB.")
            except Exception as e:
                logger.error(f"Failed to connect to MongoDB, falling back to local JSON: {e}")
                self.mongodb_client = None
                self.db = None
                self.collection = None
        else:
            logger.info("No MONGODB_URI provided. Using local JSON history storage.")

        if not self.collection:
            # Initialize empty local JSON if not exists
            if not os.path.exists(self.local_db_path):
                self._save_local_history([])

    def _load_local_history(self) -> List[Dict]:
        """Loads task history from local JSON file."""
        try:
            if os.path.exists(self.local_db_path):
                with open(self.local_db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading local history JSON: {e}")
        return []

    def _save_local_history(self, history: List[Dict]):
        """Saves task history to local JSON file."""
        try:
            with open(self.local_db_path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=4, default=str)
        except Exception as e:
            logger.error(f"Error saving local history JSON: {e}")

    def add_task(self, task_id: str, user_id: int, url: str, link_type: str) -> Dict:
        """Adds a new task to the database."""
        task_doc = {
            "task_id": task_id,
            "user_id": user_id,
            "url": url,
            "type": link_type,
            "status": "pending",
            "total_bytes": 0,
            "transferred_bytes": 0,
            "speed": "0 B/s",
            "start_time": datetime.utcnow().isoformat(),
            "end_time": None,
            "error_message": None
        }

        if self.collection is not None:
            try:
                # Convert standard isoformat string back to real Datetime objects for MongoDB if desired
                # But strings are fully fine and uniform across both JSON & Mongo
                self.collection.insert_one(task_doc.copy())
            except Exception as e:
                logger.error(f"MongoDB insert failed, writing locally: {e}")
                self._add_local_task(task_doc)
        else:
            self._add_local_task(task_doc)

        return task_doc

    def _add_local_task(self, task_doc: Dict):
        history = self._load_local_history()
        history.append(task_doc)
        self._save_local_history(history)

    def update_task(self, task_id: str, updates: Dict) -> bool:
        """Updates an existing task in the database."""
        if self.collection is not None:
            try:
                result = self.collection.update_one({"task_id": task_id}, {"$set": updates})
                if result.matched_count > 0:
                    return True
            except Exception as e:
                logger.error(f"MongoDB update failed, writing locally: {e}")
                # Fall through to local update
        
        # Local update fallback
        history = self._load_local_history()
        updated = False
        for task in history:
            if task["task_id"] == task_id:
                task.update(updates)
                updated = True
                break
        if updated:
            self._save_local_history(history)
            return True
        return False

    def get_task(self, task_id: str) -> Optional[Dict]:
        """Retrieves a single task by ID."""
        if self.collection is not None:
            try:
                task = self.collection.find_one({"task_id": task_id}, {"_id": 0})
                if task:
                    return task
            except Exception as e:
                logger.error(f"MongoDB find failed, reading locally: {e}")
        
        history = self._load_local_history()
        for task in history:
            if task["task_id"] == task_id:
                return task
        return None

    def get_stats(self) -> Dict:
        """Gives summary statistics for the stats command."""
        total = 0
        completed = 0
        failed = 0
        canceled = 0
        total_transferred = 0

        if self.collection is not None:
            try:
                total = self.collection.count_documents({})
                completed = self.collection.count_documents({"status": "completed"})
                failed = self.collection.count_documents({"status": "failed"})
                canceled = self.collection.count_documents({"status": "canceled"})
                
                # Calculate total transferred
                pipeline = [{"$group": {"_id": None, "total": {"$sum": "$transferred_bytes"}}}]
                agg = list(self.collection.aggregate(pipeline))
                if agg:
                    total_transferred = agg[0].get("total", 0)
                
                return {
                    "total_tasks": total,
                    "completed": completed,
                    "failed": failed,
                    "canceled": canceled,
                    "total_transferred_bytes": total_transferred
                }
            except Exception as e:
                logger.error(f"MongoDB aggregate failed, computing locally: {e}")
        
        history = self._load_local_history()
        total = len(history)
        for task in history:
            if task["status"] == "completed":
                completed += 1
            elif task["status"] == "failed":
                failed += 1
            elif task["status"] == "canceled":
                canceled += 1
            
            total_transferred += task.get("transferred_bytes", 0)

        return {
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "canceled": canceled,
            "total_transferred_bytes": total_transferred
        }

    def get_user_history(self, user_id: int, limit: int = 5) -> List[Dict]:
        """Retrieves recent task history for a user."""
        if self.collection is not None:
            try:
                cursor = self.collection.find({"user_id": user_id}, {"_id": 0}).sort("start_time", pymongo.DESCENDING).limit(limit)
                return list(cursor)
            except Exception as e:
                logger.error(f"MongoDB get history failed, reading locally: {e}")
        
        history = self._load_local_history()
        user_tasks = [t for t in history if t["user_id"] == user_id]
        # Sort by start_time descending
        user_tasks.sort(key=lambda x: x.get("start_time", ""), reverse=True)
        return user_tasks[:limit]

# Global database instance
db = Database()
