"""Універсальний connection manager для SQLite та PostgreSQL"""
import os
import logging
from typing import Optional, Any
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class DatabaseConnection:
    """Менеджер підключення до БД (автоматично SQLite або PostgreSQL)"""
    
    def __init__(self):
        self.db_type: Optional[str] = None
        self.db_url: Optional[str] = None
        self._detect_database()
    
    def _detect_database(self):
        """Визначити тип БД з environment variables"""
        database_url = os.getenv("DATABASE_URL")
        
        if database_url and (database_url.startswith("postgres") or database_url.startswith("postgresql")):
            self.db_type = "postgres"
            # Конвертувати postgres:// на postgresql://
            if database_url.startswith("postgres://"):
                database_url = database_url.replace("postgres://", "postgresql://", 1)
            self.db_url = database_url
            logger.info(f"🐘 Database: PostgreSQL")
        else:
            self.db_type = "sqlite"
            logger.info(f"📁 Database: SQLite")
    
    def connect(self, db_path: str):
        """Отримати connection (автоматично SQLite або PostgreSQL)"""
        return _connection_context(self, db_path)


@asynccontextmanager
async def _connection_context(manager: DatabaseConnection, db_path: str):
    """Async context manager для підключення"""
    if manager.db_type == "postgres":
        import asyncpg
        conn = await asyncpg.connect(manager.db_url)
        try:
            yield PostgresAdapter(conn)
        finally:
            await conn.close()
    else:
        import aiosqlite
        conn = await aiosqlite.connect(db_path)
        try:
            yield SQLiteAdapter(conn)
        finally:
            await conn.close()


class SQLiteAdapter:
    """Адаптер для SQLite"""
    
    def __init__(self, conn):
        self.conn = conn
        self.is_postgres = False
    
    async def execute(self, query: str, params=None):
        """Виконати запит"""
        if params:
            return await self.conn.execute(query, params)
        return await self.conn.execute(query)
    
    async def commit(self):
        """Зберегти зміни"""
        await self.conn.commit()
    
    async def fetchone(self, query: str, params=None):
        """Отримати один рядок"""
        async with self.conn.execute(query, params or ()) as cur:
            return await cur.fetchone()
    
    async def fetchall(self, query: str, params=None):
        """Отримати всі рядки"""
        async with self.conn.execute(query, params or ()) as cur:
            return await cur.fetchall()


class PostgresAdapter:
    """Адаптер для PostgreSQL"""
    
    def __init__(self, conn):
        self.conn = conn
        self.is_postgres = True
        self._last_cursor = None
        self._last_insert_id = None
    
    def _convert_query(self, query: str) -> str:
        """Конвертувати ? на $1, $2, ... для PostgreSQL"""
        parts = query.split('?')
        if len(parts) == 1:
            return query
        
        result = parts[0]
        for i, part in enumerate(parts[1:], 1):
            result += f"${i}" + part
        
        return result
    
    async def execute(self, query: str, params=None):
        """Виконати запит"""
        query_original = query
        query = self._convert_query(query)
        
        # Автоматично додати RETURNING id для INSERT
        if query_original.strip().upper().startswith("INSERT") and "RETURNING" not in query.upper():
            query = query.rstrip().rstrip(';') + " RETURNING id"
            # Виконати з RETURNING
            if params:
                row = await self.conn.fetchrow(query, *params)
            else:
                row = await self.conn.fetchrow(query)
            
            # Зберегти lastrowid
            self._last_insert_id = row[0] if row else None
            self._last_cursor = f"INSERT 0 1"
            return self
        
        # Звичайний запит
        if params:
            result = await self.conn.execute(query, *params)
        else:
            result = await self.conn.execute(query)
        
        self._last_cursor = result
        self._last_insert_id = None
        return self
    
    async def commit(self):
        """PostgreSQL не потребує явного commit"""
        pass
    
    @property
    def lastrowid(self):
        """Емуляція lastrowid для PostgreSQL"""
        return self._last_insert_id if hasattr(self, '_last_insert_id') else None
    
    @property  
    def rowcount(self):
        """Кількість змінених рядків"""
        if self._last_cursor:
            # Парсити результат типу "UPDATE 1"
            try:
                return int(self._last_cursor.split()[-1])
            except:
                return 0
        return 0
    
    async def fetchone(self, query: str, params=None):
        """Отримати один рядок"""
        query = self._convert_query(query)
        if params:
            return await self.conn.fetchrow(query, *params)
        return await self.conn.fetchrow(query)
    
    async def fetchall(self, query: str, params=None):
        """Отримати всі рядки"""
        query = self._convert_query(query)
        if params:
            rows = await self.conn.fetch(query, *params)
        else:
            rows = await self.conn.fetch(query)
        
        # Конвертувати asyncpg.Record в tuple для сумісності
        return [tuple(row.values()) for row in rows] if rows else []


# Глобальний інстанс
db_manager = DatabaseConnection()
