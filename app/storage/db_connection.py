"""Універсальний connection manager для SQLite та PostgreSQL"""
import os
import logging
from typing import Optional, Any
from contextlib import asynccontextmanager

try:
    import asyncpg
except ImportError:
    asyncpg = None

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
    logger.debug(f"🔌 Відкриваю підключення до {manager.db_type}...")
    
    if manager.db_type == "postgres":
        import asyncpg
        try:
            conn = await asyncpg.connect(manager.db_url)
            logger.debug("✅ PostgreSQL підключення встановлено")
            try:
                yield PostgresAdapter(conn)
            finally:
                await conn.close()
                logger.debug("🔒 PostgreSQL підключення закрито")
        except Exception as e:
            logger.error(f"❌ Помилка підключення PostgreSQL: {e}")
            raise
    else:
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


class SQLiteCursor:
    """Обгортка для aiosqlite cursor з підтримкою await"""
    
    def __init__(self, adapter, query, params):
        self.adapter = adapter
        self.query = query
        self.params = params
        self._cursor = None
        self._executed = False
        self._lastrowid = None
        self._rowcount = 0
    
    async def __aenter__(self):
        """Відкрити cursor через async context manager"""
        if not self._cursor:
            # Отримати cursor від connection
            self._cursor = self.adapter.conn.execute(self.query, self.params or ())
        # Відкрити реальний aiosqlite cursor
        await self._cursor.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрити cursor"""
        if self._cursor:
            await self._cursor.__aexit__(exc_type, exc_val, exc_tb)
        return False
    
    def __await__(self):
        """Зробити cursor awaitable для INSERT/UPDATE/DELETE операцій"""
        return self._execute_and_return_self().__await__()
    
    async def _execute_and_return_self(self):
        """Виконати запит і повернути self"""
        if not self._executed:
            await self._execute()
        return self
    
    async def _execute(self):
        """Виконати запит"""
        if self._executed:
            return
        
        self._executed = True
        # aiosqlite.Connection.execute() НЕ є coroutine - просто повертає cursor
        self._cursor = self.adapter.conn.execute(self.query, self.params or ())
    
    @property
    def lastrowid(self):
        """Отримати ID останнього вставленого рядка"""
        if self._cursor:
            return self._cursor.lastrowid
        return None
    
    @property
    def rowcount(self):
        """Кількість змінених рядків"""
        if self._cursor:
            return self._cursor.rowcount
        return 0
    
    async def fetchone(self):
        """Отримати один рядок"""
        if not self._cursor:
            # aiosqlite.Connection.execute() НЕ є coroutine
            self._cursor = self.adapter.conn.execute(self.query, self.params or ())
        return await self._cursor.fetchone()
    
    async def fetchall(self):
        """Отримати всі рядки"""
        if not self._cursor:
            # aiosqlite.Connection.execute() НЕ є coroutine
            self._cursor = self.adapter.conn.execute(self.query, self.params or ())
        return await self._cursor.fetchall()


class SQLiteAdapter:
    """Адаптер для SQLite"""
    
    def __init__(self, conn):
        self.conn = conn
        self.is_postgres = False
    
    def _convert_params(self, params):
        """Конвертувати datetime об'єкти в ISO string для SQLite"""
        if not params:
            return params
        
        from datetime import datetime, date
        converted = []
        for param in params:
            if isinstance(param, (datetime, date)):
                # SQLite очікує рядки для дат
                converted.append(param.isoformat())
            else:
                converted.append(param)
        return tuple(converted)
    
    def execute(self, query: str, params=None):
        """Виконати запит - повертає async context manager з підтримкою await"""
        if params:
            params = self._convert_params(params)
        return SQLiteCursor(self, query, params)
    
    async def commit(self):
        """Зберегти зміни"""
        await self.conn.commit()
    
    async def fetchone(self, query: str, params=None):
        """Отримати один рядок"""
        if params:
            params = self._convert_params(params)
        async with self.conn.execute(query, params or ()) as cur:
            return await cur.fetchone()
    
    async def fetchall(self, query: str, params=None):
        """Отримати всі рядки"""
        if params:
            params = self._convert_params(params)
        async with self.conn.execute(query, params or ()) as cur:
            return await cur.fetchall()


class PostgresCursor:
    """Емуляція cursor для PostgreSQL з async context manager та awaitable"""
    
    def __init__(self, adapter, query, params):
        self.adapter = adapter
        self.query = adapter._convert_query(query)
        self.params = params
        self._result = None
        self._lastrowid = None
        self._rowcount = 0
        self._executed = False
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False
    
    def __await__(self):
        """Зробити cursor awaitable для INSERT/UPDATE/DELETE операцій"""
        return self._execute_and_return_self().__await__()
    
    async def _execute_and_return_self(self):
        """Виконати запит і повернути self"""
        if not self._executed:
            await self._execute()
        return self
    
    async def _execute(self):
        """Виконати запит для INSERT/UPDATE/DELETE"""
        if self._executed:
            return
        
        self._executed = True
        
        # Визначити тип запиту
        query_upper = self.query.strip().upper()
        
        if query_upper.startswith('INSERT'):
            # Для INSERT спробувати отримати id через RETURNING
            # Але якщо таблиця не має 'id', це не спрацює
            if 'RETURNING' not in query_upper:
                # Спробувати з RETURNING id
                try:
                    returning_query = self.query.rstrip(';') + ' RETURNING id'
                    if self.params:
                        result = await self.adapter.conn.fetchrow(returning_query, *self.params)
                    else:
                        result = await self.adapter.conn.fetchrow(returning_query)
                    
                    if result and 'id' in result:
                        self._lastrowid = result['id']
                        self._rowcount = 1
                    else:
                        self._rowcount = 1
                except Exception as e:
                    # Якщо колонка 'id' не існує або інша помилка PostgreSQL, просто виконати INSERT без RETURNING
                    logger.debug(f"INSERT без RETURNING id (таблиця може не мати колонки 'id'): {type(e).__name__}")
                    try:
                        if self.params:
                            status = await self.adapter.conn.execute(self.query, *self.params)
                        else:
                            status = await self.adapter.conn.execute(self.query)
                        
                        # Для INSERT status буде "INSERT 0 1" (0 = OID, 1 = rows affected)
                        self._rowcount = 1
                    except Exception as e2:
                        logger.error(f"Помилка виконання INSERT: {e2}")
                        raise
            else:
                # Якщо RETURNING вже є в запиті
                if self.params:
                    result = await self.adapter.conn.fetchrow(self.query, *self.params)
                else:
                    result = await self.adapter.conn.fetchrow(self.query)
                
                if result and 'id' in result:
                    self._lastrowid = result['id']
                self._rowcount = 1
        else:
            # Для UPDATE/DELETE
            if self.params:
                result = await self.adapter.conn.execute(self.query, *self.params)
            else:
                result = await self.adapter.conn.execute(self.query)
            
            # Отримати rowcount з результату (format: "UPDATE 5")
            if result:
                try:
                    parts = result.split()
                    if len(parts) >= 2:
                        self._rowcount = int(parts[-1])
                except:
                    self._rowcount = 0
    
    @property
    def lastrowid(self):
        """Отримати ID останнього вставленого рядка"""
        return self._lastrowid
    
    @property
    def rowcount(self):
        """Кількість змінених рядків"""
        return self._rowcount
    
    async def fetchone(self):
        """Отримати один рядок"""
        if self.params:
            return await self.adapter.conn.fetchrow(self.query, *self.params)
        return await self.adapter.conn.fetchrow(self.query)
    
    async def fetchall(self):
        """Отримати всі рядки"""
        if self.params:
            rows = await self.adapter.conn.fetch(self.query, *self.params)
        else:
            rows = await self.adapter.conn.fetch(self.query)
        return [tuple(row.values()) for row in rows] if rows else []


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
    
    def execute(self, query: str, params=None):
        """Виконати запит - повертає async context manager (cursor)"""
        # Повертаємо PostgresCursor який підтримує async with
        return PostgresCursor(self, query, params)
    
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
