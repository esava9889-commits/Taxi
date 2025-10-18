"""Database adapter - автоматичний вибір між SQLite та PostgreSQL"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_database_config() -> dict:
    """
    Визначити тип БД та параметри підключення.
    
    Returns:
        dict: {
            'type': 'sqlite' | 'postgres',
            'url': str,  # для postgres
            'path': str  # для sqlite
        }
    """
    database_url = os.getenv("DATABASE_URL")
    
    if database_url and database_url.startswith("postgres"):
        # PostgreSQL на Render
        logger.info("🐘 Використовую PostgreSQL")
        
        # Render використовує postgres://, але asyncpg потребує postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        
        return {
            'type': 'postgres',
            'url': database_url,
            'path': None
        }
    else:
        # SQLite для локальної розробки
        db_path = os.getenv("DB_PATH", "data/taxi.sqlite3")
        logger.info(f"📁 Використовую SQLite: {db_path}")
        
        return {
            'type': 'sqlite',
            'url': None,
            'path': db_path
        }


async def get_db_connection():
    """
    Отримати підключення до БД (SQLite або PostgreSQL).
    
    Usage:
        async with get_db_connection() as conn:
            # використовувати conn
    """
    config = get_database_config()
    
    if config['type'] == 'postgres':
        import asyncpg
        return await asyncpg.connect(config['url'])
    else:
        import aiosqlite
        return await aiosqlite.connect(config['path'])
