"""Універсальна обгортка для SQLite та PostgreSQL"""
import os
import logging
from typing import Optional, Any, List
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class DatabaseWrapper:
    """Обгортка для роботи з SQLite або PostgreSQL"""
    
    def __init__(self):
        self.db_type: Optional[str] = None
        self.db_url: Optional[str] = None
        self.db_path: Optional[str] = None
        self._detect_database()
    
    def _detect_database(self):
        """Визначити тип БД з environment variables"""
        database_url = os.getenv("DATABASE_URL")
        
        if database_url and (database_url.startswith("postgres") or database_url.startswith("postgresql")):
            self.db_type = "postgres"
            # Render використовує postgres://, але asyncpg потребує postgresql://
            if database_url.startswith("postgres://"):
                database_url = database_url.replace("postgres://", "postgresql://", 1)
            self.db_url = database_url
            logger.info(f"🐘 PostgreSQL виявлено: {database_url[:30]}...")
        else:
            self.db_type = "sqlite"
            self.db_path = os.getenv("DB_PATH", "data/taxi.sqlite3")
            logger.info(f"📁 SQLite виявлено: {self.db_path}")
    
    @asynccontextmanager
    async def get_connection(self):
        """Отримати connection до БД"""
        if self.db_type == "postgres":
            import asyncpg
            conn = await asyncpg.connect(self.db_url)
            try:
                yield conn
            finally:
                await conn.close()
        else:
            import aiosqlite
            conn = await aiosqlite.connect(self.db_path)
            try:
                yield conn
            finally:
                await conn.close()
    
    async def execute(self, query: str, *args) -> None:
        """Виконати запит без повернення даних"""
        async with self.get_connection() as conn:
            if self.db_type == "postgres":
                # PostgreSQL використовує $1, $2 замість ?
                query = self._convert_placeholders(query)
                await conn.execute(query, *args)
            else:
                await conn.execute(query, args)
                await conn.commit()
    
    async def fetchone(self, query: str, *args) -> Optional[tuple]:
        """Виконати запит та повернути один рядок"""
        async with self.get_connection() as conn:
            if self.db_type == "postgres":
                query = self._convert_placeholders(query)
                return await conn.fetchrow(query, *args)
            else:
                async with conn.execute(query, args) as cur:
                    return await cur.fetchone()
    
    async def fetchall(self, query: str, *args) -> List[tuple]:
        """Виконати запит та повернути всі рядки"""
        async with self.get_connection() as conn:
            if self.db_type == "postgres":
                query = self._convert_placeholders(query)
                rows = await conn.fetch(query, *args)
                return [tuple(row.values()) for row in rows]
            else:
                async with conn.execute(query, args) as cur:
                    return await cur.fetchall()
    
    def _convert_placeholders(self, query: str) -> str:
        """Конвертувати ? на $1, $2, ... для PostgreSQL"""
        if self.db_type != "postgres":
            return query
        
        # Проста заміна ? на $1, $2, $3...
        parts = query.split('?')
        if len(parts) == 1:
            return query
        
        result = parts[0]
        for i, part in enumerate(parts[1:], 1):
            result += f"${i}" + part
        
        return result
    
    def _convert_datetime_sql(self, query: str) -> str:
        """Конвертувати SQL для дат"""
        if self.db_type == "postgres":
            # PostgreSQL використовує NOW() замість datetime('now')
            query = query.replace("datetime('now')", "NOW()")
            query = query.replace("AUTOINCREMENT", "")
            query = query.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
            query = query.replace("REAL", "DOUBLE PRECISION")
        
        return query


# Глобальний екземпляр
db_wrapper = DatabaseWrapper()
