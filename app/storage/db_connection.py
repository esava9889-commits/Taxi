"""Менеджер підключення до БД: тільки SQLite"""
import os
import logging
from typing import Optional, Any
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class DatabaseConnection:
    """Менеджер підключення до БД: тільки SQLite"""
    def __init__(self):
        self.db_type: Optional[str] = "sqlite"
        self.db_url: Optional[str] = None
        self.db_path: Optional[str] = None
        self._detect_database()

    def _detect_database(self):
        """Тип БД завжди SQLite"""
        self.db_type = "sqlite"
        self.db_path = os.getenv("DB_PATH", "data/taxi.sqlite3")
        logger.info(f"📁 Database: SQLite ({self.db_path})")

    def connect(self, db_path: str):
        """Отримати connection тільки SQLite"""
        return _connection_context(self, db_path)

@asynccontextmanager
async def _connection_context(manager: DatabaseConnection, db_path: str):
    """Async context manager для підключення тільки SQLite"""
    logger.debug(f"🔌 Відкриваю підключення до SQLite...")
    import aiosqlite
    try:
        conn = await aiosqlite.connect(db_path)
        logger.debug(f"✅ SQLite підключення до {db_path}")
        try:
            yield SQLiteAdapter(conn)
        finally:
            await conn.close()
            logger.debug("🔒 SQLite підключення закрито")
    except Exception as e:
        logger.error(f"❌ Помилка підключення SQLite: {e}")
        raise

class SQLiteAdapter:
    """Заглушка: реалізуйте доступні методи для SQLite"""
    def __init__(self, connection):
        self.connection = connection
    # Тут залиште реалізацію як була для SQLite