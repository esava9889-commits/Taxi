"""Database adapter - використання тільки SQLite"""
import os
import logging

logger = logging.getLogger(__name__)

def get_database_config() -> dict:
    """
    Завжди використовувати SQLite як тип БД.
    """
    db_path = os.getenv("DB_PATH", "data/taxi.sqlite3")
    logger.info(f"📁 Використовую тільки SQLite: {db_path}")

    return {
        'type': 'sqlite',
        'url': None,
        'path': db_path
    }

async def get_db_connection():
    """
    Отримати підключення до тільки SQLite.
    """
    config = get_database_config()
    import aiosqlite
    return await aiosqlite.connect(config['path'])
