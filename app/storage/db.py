from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Union
import os
import logging

import aiosqlite

# Додаємо підтримку PostgreSQL
try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

# Імпорт connection manager
from app.storage.db_connection import db_manager

logger = logging.getLogger(__name__)


# === HELPER ФУНКЦІЇ ДЛЯ ОБОХ БД ===

def _parse_datetime(value: Union[str, datetime, None]) -> Optional[datetime]:
    """
    Безпечна конвертація datetime з БД.
    - Якщо вже datetime об'єкт (PostgreSQL) - повернути як є
    - Якщо рядок (SQLite) - конвертувати через fromisoformat()
    - Якщо None - повернути None
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            # Спробувати ISO 8601 (SQLite зберігає через isoformat)
            return datetime.fromisoformat(value)
        except Exception:
            # Спробувати кілька відомих форматів
            for fmt in (
                "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S.%f%z",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
            ):
                try:
                    return datetime.strptime(value, fmt)
                except Exception:
                    continue
            # Якщо не вдалося розпарсити – повернути None щоб не падати
            logger.debug(f"_parse_datetime: unsupported format '{value}'")
            return None
    return value

def _is_postgres() -> bool:
    """Перевірити чи використовується PostgreSQL"""
    database_url = os.getenv("DATABASE_URL", "")
    return database_url.startswith("postgres")


def _get_postgres_url() -> Optional[str]:
    """Отримати PostgreSQL URL"""
    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgres://"):
        # Конвертувати для asyncpg
        return database_url.replace("postgres://", "postgresql://", 1)
    return database_url


async def _get_connection(db_path: str):
    """Отримати connection (автоматично SQLite або PostgreSQL)"""
    if _is_postgres():
        import asyncpg
        url = _get_postgres_url()
        return await asyncpg.connect(url)
    else:
        return await aiosqlite.connect(db_path)


async def _close_connection(conn):
    """Закрити connection"""
    if _is_postgres():
        await conn.close()
    else:
        await conn.close()


def _convert_query(query: str) -> str:
    """Конвертувати SQL для PostgreSQL"""
    if not _is_postgres():
        return query
    
    # Замінити ? на $1, $2, $3...
    parts = query.split('?')
    if len(parts) == 1:
        return query
    
    result = parts[0]
    for i, part in enumerate(parts[1:], 1):
        result += f"${i}" + part
    
    return result


@dataclass
class SavedAddress:
    id: Optional[int]
    user_id: int
    name: str
    emoji: str
    address: str
    lat: Optional[float]
    lon: Optional[float]
    created_at: datetime


@dataclass
class Order:
    id: Optional[int]
    user_id: int  # client Telegram user id
    name: str
    phone: str
    pickup_address: str
    destination_address: str
    comment: Optional[str]
    created_at: datetime
    # Координати для розрахунку відстані
    pickup_lat: Optional[float] = None
    pickup_lon: Optional[float] = None
    dest_lat: Optional[float] = None
    dest_lon: Optional[float] = None
    # Extended lifecycle fields
    driver_id: Optional[int] = None
    distance_m: Optional[int] = None
    duration_s: Optional[int] = None
    fare_amount: Optional[float] = None
    commission: Optional[float] = None
    status: str = "pending"  # pending|offered|accepted|in_progress|completed|cancelled
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    # ID повідомлення в групі водіїв
    group_message_id: Optional[int] = None
    # Причина скасування
    cancel_reason: Optional[str] = None
    # Клас авто
    car_class: str = "economy"  # economy | standard | comfort | business
    # Чайові
    tip_amount: Optional[float] = None
    # Спосіб оплати
    payment_method: str = "cash"  # cash | card


async def ensure_driver_columns(db_path: str) -> None:
    """Міграція: додати відсутні колонки до drivers (ТІЛЬКИ для SQLite)"""
    import logging
    logger = logging.getLogger(__name__)
    
    # Це міграція тільки для SQLite
    if _is_postgres():
        logger.debug("PostgreSQL: міграції drivers виконуються в init_postgres.py")
        return
    
    async with db_manager.connect(db_path) as db:
        # Перевірити чи таблиця drivers існує (SQLite синтаксис)
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='drivers'"
        ) as cur:
            table_exists = await cur.fetchone()
        
        if not table_exists:
            logger.info("ℹ️  Таблиця drivers ще не створена, пропускаю міграцію")
            return
        
        # Отримати поточні колонки (SQLite синтаксис)
        async with db.execute("PRAGMA table_info(drivers)") as cur:
            columns = await cur.fetchall()
            col_names = [c[1] for c in columns]
        
        # Додати card_number якщо немає
        if 'card_number' not in col_names:
            logger.info("⚙️  Міграція: додаю колонку card_number...")
            await db.execute("ALTER TABLE drivers ADD COLUMN card_number TEXT")
            await db.commit()
            logger.info("✅ Колонка card_number додана")
        
        # Додати car_class якщо немає
        if 'car_class' not in col_names:
            logger.info("⚙️  Міграція: додаю колонку car_class...")
            await db.execute("ALTER TABLE drivers ADD COLUMN car_class TEXT NOT NULL DEFAULT 'economy'")
            await db.commit()
            logger.info("✅ Колонка car_class додана")


async def init_db(db_path: str) -> None:
    """Ініціалізація бази даних (SQLite або PostgreSQL)"""
    
    # Перевірити чи це PostgreSQL
    database_url = os.getenv("DATABASE_URL")
    
    if database_url and database_url.startswith("postgres"):
        # PostgreSQL на Render
        logger.info("🐘 Ініціалізація PostgreSQL...")
        
        # Конвертувати postgres:// на postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        
        from app.storage.init_postgres import init_postgres_db
        await init_postgres_db(database_url)
        logger.info("✅ PostgreSQL готова!")
        return
    
    # SQLite для локальної розробки
    logger.info(f"📁 Ініціалізація SQLite: {db_path}")
    
    # Перевірити що папка існує
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        logger.info(f"📁 Створюю папку для БД: {db_dir}")
        os.makedirs(db_dir, exist_ok=True)
    
    try:
        logger.info("🔨 Відкриваю з'єднання з SQLite...")
        async with db_manager.connect(db_path) as db:
            logger.info("✅ З'єднання встановлено, створюю таблиці...")
            # Збережені адреси
            await db.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_addresses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '📍',
                address TEXT NOT NULL,
                lat REAL,
                lon REAL,
                created_at TEXT NOT NULL
            )
            """
        )
        
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    pickup_address TEXT NOT NULL,
                    destination_address TEXT NOT NULL,
                    comment TEXT,
                    created_at TEXT NOT NULL,
                    pickup_lat REAL,
                    pickup_lon REAL,
                    dest_lat REAL,
                    dest_lon REAL,
                    driver_id INTEGER,
                    distance_m INTEGER,
                    duration_s INTEGER,
                    fare_amount REAL,
                    commission REAL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    started_at TEXT,
                    finished_at TEXT,
                    group_message_id INTEGER,
                    car_class TEXT NOT NULL DEFAULT 'economy',
                    tip_amount REAL,
                    payment_method TEXT NOT NULL DEFAULT 'cash'
                )
                """
            )
            # Tariffs: single-row or versioned tariffs
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tariffs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    base_fare REAL NOT NULL,
                    per_km REAL NOT NULL,
                    per_minute REAL NOT NULL,
                    minimum REAL NOT NULL,
                    commission_percent REAL NOT NULL DEFAULT 0.02,
                    night_tariff_percent REAL NOT NULL DEFAULT 50.0,
                    weather_percent REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL
                )
                """
            )
            
            # ⭐ МІГРАЦІЯ: Додати нові колонки якщо їх немає
            try:
                await db.execute("ALTER TABLE tariffs ADD COLUMN night_tariff_percent REAL NOT NULL DEFAULT 50.0")
                logger.info("✅ Додано колонку night_tariff_percent до tariffs")
            except:
                pass  # Колонка вже існує
            
            try:
                await db.execute("ALTER TABLE tariffs ADD COLUMN weather_percent REAL NOT NULL DEFAULT 0.0")
                logger.info("✅ Додано колонку weather_percent до tariffs")
            except:
                pass  # Колонка вже існує
            
            # ⭐⭐ МІГРАЦІЯ: Додати систему карми
            try:
                await db.execute("ALTER TABLE drivers ADD COLUMN karma INTEGER NOT NULL DEFAULT 100")
                logger.info("✅ Додано колонку karma до drivers")
            except:
                pass  # Колонка вже існує
            
            try:
                await db.execute("ALTER TABLE drivers ADD COLUMN total_orders INTEGER NOT NULL DEFAULT 0")
                logger.info("✅ Додано колонку total_orders до drivers")
            except:
                pass
            
            try:
                await db.execute("ALTER TABLE drivers ADD COLUMN rejected_orders INTEGER NOT NULL DEFAULT 0")
                logger.info("✅ Додано колонку rejected_orders до drivers")
            except:
                pass

            # ⭐ Додати колонку priority до drivers, якщо немає
            try:
                await db.execute("ALTER TABLE drivers ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
                logger.info("✅ Додано колонку priority до drivers")
            except:
                pass

            # Глобальні налаштування (app_settings)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            
            try:
                await db.execute("ALTER TABLE users ADD COLUMN karma INTEGER NOT NULL DEFAULT 100")
                logger.info("✅ Додано колонку karma до users")
            except:
                pass
            
            try:
                await db.execute("ALTER TABLE users ADD COLUMN total_orders INTEGER NOT NULL DEFAULT 0")
                logger.info("✅ Додано колонку total_orders до users")
            except:
                pass
            
            try:
                await db.execute("ALTER TABLE users ADD COLUMN cancelled_orders INTEGER NOT NULL DEFAULT 0")
                logger.info("✅ Додано колонку cancelled_orders до users")
            except:
                pass
            
            try:
                await db.execute("ALTER TABLE users ADD COLUMN bonus_rides_available INTEGER NOT NULL DEFAULT 0")
                logger.info("✅ Додано колонку bonus_rides_available до users")
            except Exception as e:
                logger.debug(f"Колонка bonus_rides_available вже існує або помилка: {e}")
                pass
            # Users: registered clients
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    role TEXT NOT NULL,
                    city TEXT,
                    language TEXT NOT NULL DEFAULT 'uk',
                    created_at TEXT NOT NULL
                )
                """
            )
            # Міграція: додати нові колонки в users якщо їх немає
            try:
                await db.execute("ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0")
            except Exception:
                pass  # Колонка вже існує
            
            try:
                await db.execute("ALTER TABLE users ADD COLUMN karma INTEGER DEFAULT 100")
            except Exception:
                pass
            
            try:
                await db.execute("ALTER TABLE users ADD COLUMN total_orders INTEGER DEFAULT 0")
            except Exception:
                pass
            
            try:
                await db.execute("ALTER TABLE users ADD COLUMN cancelled_orders INTEGER DEFAULT 0")
            except Exception:
                pass
            
            try:
                await db.execute("ALTER TABLE users ADD COLUMN bonus_rides_available INTEGER DEFAULT 0")
                logger.info("✅ Додано колонку bonus_rides_available до users (PostgreSQL)")
            except Exception as e:
                logger.debug(f"Колонка bonus_rides_available вже існує: {e}")
                pass
            
            # Drivers: applications and active drivers
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS drivers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_user_id INTEGER NOT NULL,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    car_make TEXT NOT NULL,
                    car_model TEXT NOT NULL,
                    car_plate TEXT NOT NULL,
                    license_photo_file_id TEXT,
                    city TEXT,
                    status TEXT NOT NULL,  -- pending | approved | rejected
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    online INTEGER NOT NULL DEFAULT 0,
                    last_lat REAL,
                    last_lon REAL,
                    last_seen_at TEXT,
                    car_class TEXT NOT NULL DEFAULT 'economy',
                    card_number TEXT,
                    priority INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            # Helpful indices
            await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_driver_id ON orders(driver_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_drivers_status ON drivers(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_drivers_tg_user ON drivers(tg_user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_drivers_online ON drivers(online)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_drivers_priority ON drivers(priority)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_saved_addresses_user ON saved_addresses(user_id)")
        
            # Ratings table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    from_user_id INTEGER NOT NULL,
                    to_user_id INTEGER NOT NULL,
                    rating INTEGER NOT NULL,
                    comment TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ratings_to_user ON ratings(to_user_id)")
        
            # Client ratings (водії оцінюють клієнтів)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS client_ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    driver_id INTEGER NOT NULL,
                    rating INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_client_ratings ON client_ratings(client_id)")
        
            # Tips (чайові)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL UNIQUE,
                    amount REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        
            # Referral program (реферальна програма)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER NOT NULL,
                    referred_id INTEGER NOT NULL,
                    referral_code TEXT NOT NULL,
                    bonus_amount REAL NOT NULL DEFAULT 50,
                    referrer_bonus REAL NOT NULL DEFAULT 30,
                    used INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_referrals_code ON referrals(referral_code)")
        
            # Payments table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    driver_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    commission REAL NOT NULL,
                    commission_paid INTEGER NOT NULL DEFAULT 0,
                    payment_method TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    commission_paid_at TEXT
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_driver ON payments(driver_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_commission_paid ON payments(commission_paid)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_driver_unpaid ON payments(driver_id, commission_paid)")
        
            await db.commit()
            
            # Перевірити що таблиці створено
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ) as cur:
                tables = await cur.fetchall()
                logger.info(f"📊 Створено таблиць: {len(tables)}")
                if len(tables) > 0:
                    table_names = [t[0] for t in tables]
                    logger.info(f"📋 Таблиці: {', '.join(table_names)}")
                else:
                    logger.error("❌ ЖОДНОЇ таблиці не створено!")
        
        logger.info("✅ Всі таблиці SQLite створено!")
    
    except Exception as e:
        logger.error(f"❌ ПОМИЛКА при створенні таблиць: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise
    
    # Виконати міграції ПІСЛЯ створення всіх таблиць (ТІЛЬКИ для SQLite)
    if not _is_postgres():
        try:
            await ensure_driver_columns(db_path)
            # Міграція: додати commission_percent у tariffs якщо відсутнє
            async with db_manager.connect(db_path) as db:
                async with db.execute("PRAGMA table_info(tariffs)") as cur:
                    cols = await cur.fetchall()
                    col_names = [c[1] for c in cols]
                if 'commission_percent' not in col_names:
                    await db.execute("ALTER TABLE tariffs ADD COLUMN commission_percent REAL NOT NULL DEFAULT 0.02")
                    await db.commit()
            
            logger.info("✅ SQLite міграції завершено успішно!")
        
        except Exception as e:
            logger.error(f"❌ ПОМИЛКА при SQLite міграціях: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    logger.info("✅ init_db() завершено успішно!")


async def insert_order(db_path: str, order: Order) -> int:
    async with db_manager.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO orders (
                user_id, name, phone, pickup_address, destination_address, comment, created_at,
                pickup_lat, pickup_lon, dest_lat, dest_lon,
                driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id,
                car_class, tip_amount, payment_method
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.user_id,
                order.name,
                order.phone,
                order.pickup_address,
                order.destination_address,
                order.comment,
                order.created_at,
                order.pickup_lat,
                order.pickup_lon,
                order.dest_lat,
                order.dest_lon,
                order.driver_id,
                order.distance_m,
                order.duration_s,
                order.fare_amount,
                order.commission,
                order.status,
                (order.started_at if order.started_at else None),
                (order.finished_at if order.finished_at else None),
                order.group_message_id,
                order.car_class,
                order.tip_amount,
                order.payment_method,
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def update_order_group_message(db_path: str, order_id: int, message_id: int) -> bool:
    """Оновити ID повідомлення в групі водіїв"""
    async with db_manager.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE orders SET group_message_id = ? WHERE id = ?",
            (message_id, order_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def increase_order_fare(db_path: str, order_id: int, increase_amount: float) -> bool:
    """
    Підвищити ціну замовлення на вказану суму.
    
    Args:
        db_path: Шлях до БД
        order_id: ID замовлення
        increase_amount: Сума підвищення (грн)
    
    Returns:
        True якщо оновлено успішно
    """
    async with db_manager.connect(db_path) as db:
        # Отримати поточну ціну
        cur = await db.execute(
            "SELECT fare_amount FROM orders WHERE id = ?",
            (order_id,)
        )
        row = await cur.fetchone()
        
        if not row:
            return False
        
        current_fare = row[0] if row[0] else 100.0
        new_fare = current_fare + increase_amount
        
        # Оновити ціну
        cur = await db.execute(
            "UPDATE orders SET fare_amount = ? WHERE id = ?",
            (new_fare, order_id),
        )
        await db.commit()
        
        logger.info(f"💰 Ціна замовлення #{order_id} підвищена: {current_fare:.0f} → {new_fare:.0f} грн (+{increase_amount:.0f})")
        return cur.rowcount > 0


async def cancel_order_by_client(db_path: str, order_id: int, user_id: int) -> bool:
    """
    Скасувати замовлення клієнтом.
    
    Можна скасувати якщо статус:
    - pending (очікує водія)
    - accepted (водій прийняв, але ще не в дорозі)
    
    НЕМОЖНА скасувати якщо:
    - in_progress (вже везуть)
    - completed (завершено)
    - cancelled (вже скасовано)
    """
    async with db_manager.connect(db_path) as db:
        # Спочатку отримати замовлення щоб зменшити карму водія якщо він був призначений
        cur = await db.execute(
            "SELECT driver_id, status FROM orders WHERE id = ? AND user_id = ?",
            (order_id, user_id)
        )
        row = await cur.fetchone()
        
        if not row:
            return False
        
        driver_id, status = row[0], row[1]
        
        # Перевірити чи можна скасувати
        if status not in ('pending', 'accepted'):
            return False
        
        # Скасувати замовлення
        cur = await db.execute(
            "UPDATE orders SET status = 'cancelled', finished_at = ? WHERE id = ? AND user_id = ? AND status IN ('pending', 'accepted')",
            (datetime.now(timezone.utc), order_id, user_id),
        )
        await db.commit()
        
        # 🛑 Зупинити live location трекінг якщо був активний
        try:
            from app.utils.live_location_manager import LiveLocationManager
            await LiveLocationManager.stop_tracking(order_id)
        except Exception as e:
            logger.warning(f"⚠️ Не вдалося зупинити live location: {e}")
        
        # Якщо водій був призначений (статус accepted) - повідомити водія
        if driver_id and status == 'accepted':
            logger.warning(f"⚠️ Клієнт скасував замовлення #{order_id}, водій #{driver_id} буде повідомлений")
            # Тут не зменшуємо карму водія, бо це клієнт скасував, не водій
            # Водій буде повідомлений в обробнику скасування
        
        return cur.rowcount > 0


async def cancel_order_by_driver(db_path: str, order_id: int, driver_id: int, reason: str = "Driver cancelled") -> bool:
    """
    Скасувати замовлення водієм.
    
    Водій може скасувати тільки своє активне замовлення.
    Замовлення ПОВНІСТЮ скасовується (статус 'cancelled') БЕЗ штрафу для клієнта.
    """
    async with db_manager.connect(db_path) as db:
        # Перевірити що це замовлення цього водія
        cur = await db.execute(
            "SELECT id, user_id FROM orders WHERE id = ? AND driver_id = ? AND status IN ('accepted', 'in_progress')",
            (order_id, driver_id)
        )
        row = await cur.fetchone()
        
        if not row:
            return False
        
        user_id = row[1]
        
        # ПОВНІСТЮ скасувати замовлення (не повертати в pending!)
        # Причина: клієнт не винен що водій відмовився
        cur = await db.execute(
            "UPDATE orders SET status = 'cancelled', driver_id = NULL, finished_at = ? WHERE id = ?",
            (datetime.now(timezone.utc), order_id)
        )
        await db.commit()
        
        # 🛑 Зупинити live location трекінг якщо був активний
        try:
            from app.utils.live_location_manager import LiveLocationManager
            await LiveLocationManager.stop_tracking(order_id)
        except Exception as e:
            logger.warning(f"⚠️ Не вдалося зупинити live location: {e}")
        
        # ВАЖЛИВО: Клієнт НЕ втрачає карму, бо скасував водій (не клієнт)
        logger.warning(f"⚠️ Водій #{driver_id} скасував замовлення #{order_id}: {reason}. Замовлення ПОВНІСТЮ скасовано, карма клієнта #{user_id} НЕ зменшена")
        return cur.rowcount > 0


async def get_active_order_for_driver(db_path: str, driver_id: int) -> Optional[Order]:
    """
    Отримати активне замовлення водія.
    
    Активне замовлення = статус 'accepted' або 'in_progress'.
    """
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, user_id, name, phone, pickup_address, destination_address, comment, created_at,
                   pickup_lat, pickup_lon, dest_lat, dest_lon,
                   driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id,
                   car_class, tip_amount, payment_method
            FROM orders 
            WHERE driver_id = ? AND status IN ('accepted', 'in_progress')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (driver_id,),
        ) as cursor:
            row = await cursor.fetchone()
    
    if not row:
        return None
    
    return Order(
        id=row[0],
        user_id=row[1],
        name=row[2],
        phone=row[3],
        pickup_address=row[4],
        destination_address=row[5],
        comment=row[6],
        created_at=_parse_datetime(row[7]),
        pickup_lat=row[8],
        pickup_lon=row[9],
        dest_lat=row[10],
        dest_lon=row[11],
        driver_id=row[12],
        distance_m=row[13],
        duration_s=row[14],
        fare_amount=row[15],
        commission=row[16],
        status=row[17],
        started_at=_parse_datetime(row[18]),
        finished_at=_parse_datetime(row[19]),
        group_message_id=row[20],
        car_class=row[21],
        tip_amount=row[22],
        payment_method=row[23],
    )


# ==================== Збережені адреси ====================

async def save_address(db_path: str, address: SavedAddress) -> int:
    """Зберегти адресу користувача"""
    async with db_manager.connect(db_path) as db:
        cur = await db.execute(
            """
            INSERT INTO saved_addresses (user_id, name, emoji, address, lat, lon, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                address.user_id,
                address.name,
                address.emoji,
                address.address,
                address.lat,
                address.lon,
                address.created_at,
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_user_saved_addresses(db_path: str, user_id: int) -> List[SavedAddress]:
    """Отримати всі збережені адреси користувача"""
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, user_id, name, emoji, address, lat, lon, created_at
            FROM saved_addresses
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [
                SavedAddress(
                    id=row[0],
                    user_id=row[1],
                    name=row[2],
                    emoji=row[3],
                    address=row[4],
                    lat=row[5],
                    lon=row[6],
                    created_at=_parse_datetime(row[7]),
                )
                for row in rows
            ]


async def get_saved_address_by_id(db_path: str, address_id: int, user_id: int) -> Optional[SavedAddress]:
    """Отримати збережену адресу за ID"""
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, user_id, name, emoji, address, lat, lon, created_at
            FROM saved_addresses
            WHERE id = ? AND user_id = ?
            """,
            (address_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            
            return SavedAddress(
                id=row[0],
                user_id=row[1],
                name=row[2],
                emoji=row[3],
                address=row[4],
                lat=row[5],
                lon=row[6],
                created_at=_parse_datetime(row[7]),
            )


async def delete_saved_address(db_path: str, address_id: int, user_id: int) -> bool:
    """Видалити збережену адресу"""
    async with db_manager.connect(db_path) as db:
        cur = await db.execute(
            "DELETE FROM saved_addresses WHERE id = ? AND user_id = ?",
            (address_id, user_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def update_saved_address(db_path: str, address_id: int, user_id: int, name: str, emoji: str) -> bool:
    """Оновити назву та емодзі збереженої адреси"""
    async with db_manager.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE saved_addresses SET name = ?, emoji = ? WHERE id = ? AND user_id = ?",
            (name, emoji, address_id, user_id)
        )
        await db.commit()
        return cur.rowcount > 0


# ==================== Онлайн/Офлайн статус ====================

async def set_driver_online_status(db_path: str, driver_id: int, online: bool) -> bool:
    """Змінити онлайн статус водія"""
    async with db_manager.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE drivers SET online = ?, last_seen_at = ? WHERE id = ?",
            (1 if online else 0, datetime.now(timezone.utc), driver_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def get_online_drivers_count(db_path: str, city: Optional[str] = None) -> int:
    """Підрахунок онлайн водіїв"""
    async with db_manager.connect(db_path) as db:
        if city:
            async with db.execute(
                "SELECT COUNT(*) FROM drivers WHERE online = 1 AND status = 'approved' AND city = ?",
                (city,)
            ) as cur:
                return (await cur.fetchone())[0]
        else:
            async with db.execute(
                "SELECT COUNT(*) FROM drivers WHERE online = 1 AND status = 'approved'"
            ) as cur:
                return (await cur.fetchone())[0]


async def get_online_drivers(db_path: str, city: Optional[str] = None) -> List[Driver]:
    """Отримати список онлайн водіїв"""
    async with db_manager.connect(db_path) as db:
        if city:
            query = """
                SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate,
                       license_photo_file_id, city, status, created_at, updated_at, online,
                       last_lat, last_lon, last_seen_at, car_class, card_number, car_color, priority
                FROM drivers
                WHERE online = 1 AND status = 'approved' AND city = ?
                ORDER BY priority DESC, last_seen_at DESC
            """
            params = (city,)
        else:
            query = """
                SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate,
                       license_photo_file_id, city, status, created_at, updated_at, online,
                       last_lat, last_lon, last_seen_at, car_class, card_number, car_color, priority
                FROM drivers
                WHERE online = 1 AND status = 'approved'
                ORDER BY priority DESC, last_seen_at DESC
            """
            params = ()
        
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [
                Driver(
                    id=row[0],
                    tg_user_id=row[1],
                    full_name=row[2],
                    phone=row[3],
                    car_make=row[4],
                    car_model=row[5],
                    car_plate=row[6],
                    license_photo_file_id=row[7],
                    city=row[8],
                    status=row[9],
                    created_at=_parse_datetime(row[10]),
                    updated_at=_parse_datetime(row[11]),
                    online=bool(row[12]),
                    last_lat=row[13],
                    last_lon=row[14],
                    last_seen_at=_parse_datetime(row[15]) if row[15] else None,
                    car_class=row[16] if row[16] else "economy",
                    card_number=row[17],
                    car_color=row[18] if len(row) > 18 else None,  # ← ВИПРАВЛЕНО
                    priority=(row[19] if len(row) > 19 else 0),  # ← ВИПРАВЛЕНО: було row[18]
                )
                for row in rows
            ]


async def get_user_active_order(db_path: str, user_id: int) -> Optional[Order]:
    """
    Отримати активне замовлення користувача (pending, accepted або in_progress)
    """
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, user_id, name, phone, pickup_address, destination_address, comment, created_at,
                   driver_id, distance_m, duration_s, fare_amount, commission, status,
                   started_at, finished_at, pickup_lat, pickup_lon, dest_lat, dest_lon, group_message_id,
                   car_class, tip_amount, payment_method
            FROM orders
            WHERE user_id = ? AND status IN ('pending', 'accepted', 'in_progress')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            
            return Order(
                id=row[0],
                user_id=row[1],
                name=row[2],
                phone=row[3],
                pickup_address=row[4],
                destination_address=row[5],
                comment=row[6],
                created_at=_parse_datetime(row[7]),
                driver_id=row[8],
                distance_m=row[9],
                duration_s=row[10],
                fare_amount=row[11],
                commission=row[12],
                status=row[13],
                started_at=_parse_datetime(row[14]) if row[14] else None,
                finished_at=_parse_datetime(row[15]) if row[15] else None,
                pickup_lat=row[16],
                pickup_lon=row[17],
                dest_lat=row[18],
                dest_lon=row[19],
                group_message_id=row[20],
                car_class=row[21] if row[21] else "economy",
                tip_amount=row[22],
                payment_method=row[23] if row[23] else "cash",
            )


async def fetch_recent_orders(db_path: str, limit: int = 10) -> List[Order]:
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, user_id, name, phone, pickup_address, destination_address, comment, created_at,
                   pickup_lat, pickup_lon, dest_lat, dest_lon,
                   driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id,
                   car_class, tip_amount, payment_method
            FROM orders
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()

    orders: List[Order] = []
    for row in rows:
            orders.append(
                Order(
                    id=row[0],
                    user_id=row[1],
                    name=row[2],
                    phone=row[3],
                    pickup_address=row[4],
                    destination_address=row[5],
                    comment=row[6],
                    created_at=_parse_datetime(row[7]),
                    pickup_lat=row[8],
                    pickup_lon=row[9],
                    dest_lat=row[10],
                    dest_lon=row[11],
                    driver_id=row[12],
                    distance_m=row[13],
                    duration_s=row[14],
                    fare_amount=row[15],
                    commission=row[16],
                    status=row[17],
                    started_at=(_parse_datetime(row[18]) if row[18] else None),
                    finished_at=(_parse_datetime(row[19]) if row[19] else None),
                    group_message_id=row[20],
                    car_class=row[21] if row[21] else "economy",
                    tip_amount=row[22],
                    payment_method=row[23] if row[23] else "cash",
                )
            )
    return orders


async def get_pending_orders(db_path: str, city: Optional[str] = None) -> List[Order]:
    """
    Отримати всі очікуючі замовлення (pending)
    """
    async with db_manager.connect(db_path) as db:
        query = """
            SELECT id, user_id, name, phone, pickup_address, destination_address, comment, created_at,
                   pickup_lat, pickup_lon, dest_lat, dest_lon,
                   driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id,
                   car_class, tip_amount, payment_method
            FROM orders
            WHERE status = 'pending'
            ORDER BY created_at DESC
        """
        
        async with db.execute(query) as cur:
            rows = await cur.fetchall()

    orders = []
    for row in rows:
        orders.append(
            Order(
                    id=row[0],
                    user_id=row[1],
                    name=row[2],
                    phone=row[3],
                    pickup_address=row[4],
                    destination_address=row[5],
                    comment=row[6],
                    created_at=_parse_datetime(row[7]),
                    pickup_lat=row[8],
                    pickup_lon=row[9],
                    dest_lat=row[10],
                    dest_lon=row[11],
                    driver_id=row[12],
                    distance_m=row[13],
                    duration_s=row[14],
                    fare_amount=row[15],
                    commission=row[16],
                    status=row[17],
                    started_at=(_parse_datetime(row[18]) if row[18] else None),
                    finished_at=(_parse_datetime(row[19]) if row[19] else None),
                    group_message_id=row[20],
                    car_class=row[21] if row[21] else "economy",
                    tip_amount=row[22] if row[22] is not None else 0.0,
                    payment_method=row[23] if row[23] else "cash",
            )
        )
    return orders


# --- Users ---

@dataclass
class User:
    user_id: int
    full_name: str
    phone: str
    role: str
    created_at: datetime
    city: Optional[str] = None
    language: str = "uk"  # uk, ru, en
    karma: int = 100  # Карма клієнта (100 = ідеально)
    total_orders: int = 0  # Всього замовлень
    cancelled_orders: int = 0  # Скасованих замовлень
    is_blocked: bool = False  # Чи заблокований клієнт
    bonus_rides_available: int = 0  # Бонусні поїздки від адміна (додаткові до ліміту)


async def upsert_user(db_path: str, user: User) -> None:
    """
    Insert or replace a user profile. Uses user_id as a stable primary key.
    """
    async with db_manager.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, full_name, phone, role, city, language, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              full_name=excluded.full_name,
              phone=excluded.phone,
              role=excluded.role,
              city=excluded.city,
              language=excluded.language
            """,
            (
                user.user_id,
                user.full_name,
                user.phone,
                user.role,
                user.city,
                user.language,
                user.created_at,
            ),
        )
        await db.commit()


async def get_user_by_id(db_path: str, user_id: int) -> Optional[User]:
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """SELECT user_id, full_name, phone, role, city, language, created_at,
               CASE WHEN is_blocked IS NULL THEN 0 WHEN is_blocked THEN 1 ELSE 0 END as is_blocked,
               COALESCE(karma, 100) as karma,
               COALESCE(total_orders, 0) as total_orders,
               COALESCE(cancelled_orders, 0) as cancelled_orders,
               COALESCE(bonus_rides_available, 0) as bonus_rides_available
               FROM users WHERE user_id = ?""",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    return User(
        user_id=row[0],
        full_name=row[1],
        phone=row[2],
        role=row[3],
        created_at=_parse_datetime(row[6]),
        city=row[4],
        language=row[5] if row[5] else "uk",
        is_blocked=bool(row[7]),
        karma=row[8],
        total_orders=row[9],
        cancelled_orders=row[10],
        bonus_rides_available=row[11],
    )


async def get_all_users(db_path: str, role: str = "client") -> List[User]:
    """Отримати всіх користувачів з певною роллю"""
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """SELECT user_id, full_name, phone, role, city, language, created_at, 
               CASE WHEN is_blocked IS NULL THEN 0 WHEN is_blocked THEN 1 ELSE 0 END as is_blocked, 
               COALESCE(karma, 100) as karma,
               COALESCE(total_orders, 0) as total_orders,
               COALESCE(cancelled_orders, 0) as cancelled_orders,
               COALESCE(bonus_rides_available, 0) as bonus_rides_available
               FROM users WHERE role = ? ORDER BY created_at DESC""",
            (role,),
        ) as cursor:
            rows = await cursor.fetchall()
    
    users = []
    for row in rows:
        users.append(User(
            user_id=row[0],
            full_name=row[1],
            phone=row[2],
            role=row[3],
            created_at=_parse_datetime(row[6]),
            city=row[4],
            language=row[5] if row[5] else "uk",
            is_blocked=bool(row[7]),
            karma=row[8],
            total_orders=row[9],
            cancelled_orders=row[10],
            bonus_rides_available=row[11],
        ))
    return users


async def block_user(db_path: str, user_id: int) -> None:
    """Заблокувати користувача"""
    async with db_manager.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET is_blocked = TRUE WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()


async def unblock_user(db_path: str, user_id: int) -> None:
    """Розблокувати користувача"""
    async with db_manager.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET is_blocked = FALSE WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()


async def delete_user(db_path: str, user_id: int) -> bool:
    """Видалити користувача з БД (коли стає водієм)"""
    async with db_manager.connect(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM users WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


# --- Drivers ---

@dataclass
class Driver:
    id: Optional[int]
    tg_user_id: int
    full_name: str
    phone: str
    car_make: str
    car_model: str
    car_plate: str
    license_photo_file_id: Optional[str]
    status: str  # pending | approved | rejected
    created_at: datetime
    updated_at: datetime
    city: Optional[str] = None
    online: int = 0
    last_lat: Optional[float] = None
    last_lon: Optional[float] = None
    last_seen_at: Optional[datetime] = None
    car_class: str = "economy"  # economy | standard | comfort | business
    card_number: Optional[str] = None  # Номер картки для оплати
    karma: int = 100  # Карма водія (100 = ідеально)
    total_orders: int = 0  # Всього замовлень
    rejected_orders: int = 0  # Відмов від замовлень
    car_color: Optional[str] = None  # ✅ ДОДАНО: Колір авто
    priority: int = 0  # 1 = пріоритетний для прямих DM


async def create_driver_application(db_path: str, driver: Driver) -> int:
    async with db_manager.connect(db_path) as db:
        # Спробувати з car_color (нова колонка)
        try:
            cursor = await db.execute(
                """
                INSERT INTO drivers (
                    tg_user_id, full_name, phone, car_make, car_model, car_plate, car_color, license_photo_file_id, city, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    driver.tg_user_id,
                    driver.full_name,
                    driver.phone,
                    driver.car_make,
                    driver.car_model,
                    driver.car_plate,
                    driver.car_color,  # ← ДОДАНО
                    driver.license_photo_file_id,
                    driver.city,
                    driver.status,
                    driver.created_at,
                    driver.updated_at,
                ),
            )
        except Exception as e:
            # Fallback: Колонки car_color немає в БД
            import logging
            logging.getLogger(__name__).warning(f"⚠️ car_color не в БД, fallback: {e}")
            cursor = await db.execute(
                """
                INSERT INTO drivers (
                    tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, city, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    driver.tg_user_id,
                    driver.full_name,
                    driver.phone,
                    driver.car_make,
                    driver.car_model,
                    driver.car_plate,
                    driver.license_photo_file_id,
                    driver.city,
                    driver.status,
                    driver.created_at,
                    driver.updated_at,
                ),
            )
        await db.commit()
        return cursor.lastrowid


async def update_driver_status(db_path: str, driver_id: int, status: str) -> None:
    now = datetime.now(timezone.utc)
    async with db_manager.connect(db_path) as db:
        await db.execute(
            "UPDATE drivers SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, driver_id),
        )
        await db.commit()


async def fetch_pending_drivers(db_path: str, limit: int = 20) -> List[Driver]:
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status,
                   created_at, updated_at, city, online, last_lat, last_lon, last_seen_at, car_class, card_number, car_color, priority
            FROM drivers
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
    drivers: List[Driver] = []
    for r in rows:
        drivers.append(
            Driver(
                id=r[0],
                tg_user_id=r[1],
                full_name=r[2],
                phone=r[3],
                car_make=r[4],
                car_model=r[5],
                car_plate=r[6],
                license_photo_file_id=r[7],
                status=r[8],
                created_at=_parse_datetime(r[9]),
                updated_at=_parse_datetime(r[10]),
                city=r[11],
                online=r[12],
                last_lat=r[13],
                last_lon=r[14],
                last_seen_at=(_parse_datetime(r[15]) if r[15] else None),
                car_class=r[16] if r[16] else "economy",
                card_number=r[17],
                car_color=r[18] if len(r) > 18 else None,  # ← ДОДАНО
                priority=(r[19] if len(r) > 19 else 0),
            )
        )
    return drivers


async def get_driver_by_id(db_path: str, driver_id: int) -> Optional[Driver]:
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status,
                   created_at, updated_at, city, online, last_lat, last_lon, last_seen_at, car_class, card_number, car_color, priority,
                   karma, total_orders, rejected_orders
            FROM drivers WHERE id = ?
            """,
            (driver_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    return Driver(
        id=row[0],
        tg_user_id=row[1],
        full_name=row[2],
        phone=row[3],
        car_make=row[4],
        car_model=row[5],
        car_plate=row[6],
        license_photo_file_id=row[7],
        status=row[8],
        created_at=_parse_datetime(row[9]),
        updated_at=_parse_datetime(row[10]),
        city=row[11],
        online=row[12],
        last_lat=row[13],
        last_lon=row[14],
        last_seen_at=(_parse_datetime(row[15]) if row[15] else None),
        car_class=row[16] if row[16] else "economy",
        card_number=row[17],
        car_color=row[18] if len(row) > 18 else None,
        priority=(row[19] if len(row) > 19 else 0),
        karma=(row[20] if len(row) > 20 else 100),
        total_orders=(row[21] if len(row) > 21 else 0),
        rejected_orders=(row[22] if len(row) > 22 else 0),
    )


async def delete_driver_account(db_path: str, tg_user_id: int) -> bool:
    """Видалити акаунт водія (повністю з усіх таблиць)"""
    async with db_manager.connect(db_path) as db:
        try:
            # Отримати ID водія перед видаленням
            cursor = await db.execute(
                "SELECT id FROM drivers WHERE tg_user_id = ?",
                (tg_user_id,)
            )
            row = await cursor.fetchone()
            
            if not row:
                return False
            
            driver_id = row[0]
            
            # Видалити всі пов'язані дані
            # 1. Payments
            await db.execute("DELETE FROM payments WHERE driver_id = ?", (driver_id,))
            
            # 2. Orders (де водій був призначений)
            await db.execute(
                "UPDATE orders SET driver_id = NULL, status = 'cancelled' WHERE driver_id = ? AND status NOT IN ('completed', 'cancelled')",
                (driver_id,)
            )
            
            # 3. Ratings (як водія)
            await db.execute("DELETE FROM ratings WHERE to_user_id = ?", (tg_user_id,))
            
            # 4. Client ratings
            await db.execute("DELETE FROM client_ratings WHERE driver_id = ?", (driver_id,))
            
            # 5. Driver applications (якщо є таблиця)
            try:
                await db.execute("DELETE FROM driver_applications WHERE tg_user_id = ?", (tg_user_id,))
            except:
                pass
            
            # 6. Сам запис водія
            await db.execute("DELETE FROM drivers WHERE id = ?", (driver_id,))
            
            await db.commit()
            
            logger.info(f"✅ Видалено акаунт водія {driver_id} (tg_user_id: {tg_user_id})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Помилка видалення акаунта водія {tg_user_id}: {e}")
            return False


async def get_driver_by_tg_user_id(db_path: str, tg_user_id: int) -> Optional[Driver]:
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status,
                   created_at, updated_at, city, online, last_lat, last_lon, last_seen_at, car_class, card_number, car_color, priority,
                   karma, total_orders, rejected_orders
            FROM drivers WHERE tg_user_id = ? ORDER BY id DESC LIMIT 1
            """,
            (tg_user_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    return Driver(
        id=row[0],
        tg_user_id=row[1],
        full_name=row[2],
        phone=row[3],
        car_make=row[4],
        car_model=row[5],
        car_plate=row[6],
        license_photo_file_id=row[7],
        status=row[8],
        created_at=_parse_datetime(row[9]),
        updated_at=_parse_datetime(row[10]),
        city=row[11],
        online=row[12],
        last_lat=row[13],
        last_lon=row[14],
        last_seen_at=(_parse_datetime(row[15]) if row[15] else None),
        car_class=row[16] if row[16] else "economy",
        card_number=row[17],
        car_color=row[18] if len(row) > 18 else None,
        priority=(row[19] if len(row) > 19 else 0),
        karma=(row[20] if len(row) > 20 else 100),
        total_orders=(row[21] if len(row) > 21 else 0),
        rejected_orders=(row[22] if len(row) > 22 else 0),
    )


async def set_driver_online(db_path: str, tg_user_id: int, online: bool) -> None:
    now = datetime.now(timezone.utc)
    async with db_manager.connect(db_path) as db:
        await db.execute(
            "UPDATE drivers SET online = ?, last_seen_at = ? WHERE tg_user_id = ? AND status = 'approved'",
            (1 if online else 0, now, tg_user_id),
        )
        await db.commit()


async def update_driver_location(db_path: str, tg_user_id: int, lat: float, lon: float) -> None:
    now = datetime.now(timezone.utc)
    async with db_manager.connect(db_path) as db:
        await db.execute(
            "UPDATE drivers SET last_lat = ?, last_lon = ?, last_seen_at = ? WHERE tg_user_id = ? AND status = 'approved'",
            (lat, lon, now, tg_user_id),
        )
        await db.commit()


async def offer_order_to_driver(db_path: str, order_id: int, driver_id: int) -> bool:
    async with db_manager.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE orders SET driver_id = ?, status = 'offered' WHERE id = ? AND status = 'pending'",
            (driver_id, order_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def accept_order(db_path: str, order_id: int, driver_id: int) -> bool:
    """Accept order from group - set driver and status to accepted"""
    async with db_manager.connect(db_path) as db:
        # Нова логіка: замовлення має status='pending' і driver_id=NULL
        # Перший водій хто клікне - отримує замовлення
        cur = await db.execute(
            (
                "UPDATE orders \n"
                "SET status = 'accepted', driver_id = ? \n"
                "WHERE id = ? \n"
                "  AND status = 'pending' \n"
                "  AND driver_id IS NULL \n"
                "  AND (SELECT car_class FROM drivers WHERE id = ?) = car_class"
            ),
            (driver_id, order_id, driver_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def reject_order(db_path: str, order_id: int) -> bool:
    """Reject order by driver - set status back to pending"""
    async with db_manager.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE orders SET status = 'pending', driver_id = NULL WHERE id = ? AND status = 'offered'",
            (order_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def add_rejected_driver(db_path: str, order_id: int, driver_db_id: int) -> None:
    """Add driver to rejected list for this order (stored as JSON in a new table or field)"""
    # For simplicity, we'll create a simple rejected_offers table
    async with db_manager.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS rejected_offers (order_id INTEGER, driver_id INTEGER, rejected_at TEXT)"
        )
        await db.execute(
            "INSERT INTO rejected_offers (order_id, driver_id, rejected_at) VALUES (?, ?, ?)",
            (order_id, driver_db_id, datetime.now(timezone.utc)),
        )
        await db.commit()


async def get_rejected_drivers_for_order(db_path: str, order_id: int) -> List[int]:
    """Get list of driver IDs who rejected this order"""
    async with db_manager.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS rejected_offers (order_id INTEGER, driver_id INTEGER, rejected_at TEXT)"
        )
        async with db.execute(
            "SELECT driver_id FROM rejected_offers WHERE order_id = ?",
            (order_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [row[0] for row in rows]


async def start_order(db_path: str, order_id: int, driver_id: int) -> bool:
    now = datetime.now(timezone.utc)
    async with db_manager.connect(db_path) as db:
        # Дозволяємо оновити якщо замовлення ще не почалось (accepted) або вже в процесі (in_progress)
        cur = await db.execute(
            "UPDATE orders SET status = 'in_progress', started_at = COALESCE(started_at, ?) WHERE id = ? AND driver_id = ? AND status IN ('accepted', 'in_progress')",
            (now, order_id, driver_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def complete_order(
    db_path: str,
    order_id: int,
    driver_id: int,
    fare_amount: float,
    distance_m: int,
    duration_s: int,
    commission: float,
) -> bool:
    import logging
    logger = logging.getLogger(__name__)
    
    now = datetime.now(timezone.utc)
    async with db_manager.connect(db_path) as db:
        # Спочатку перевіримо поточний статус замовлення
        async with db.execute(
            "SELECT id, status, driver_id FROM orders WHERE id = ?",
            (order_id,)
        ) as check_cursor:
            check_row = await check_cursor.fetchone()
            if check_row:
                current_status = check_row[1]
                current_driver = check_row[2]
                logger.info(f"🔍 complete_order: замовлення #{order_id}, поточний статус: {current_status}, driver_id: {current_driver}")
                
                if current_driver != driver_id:
                    logger.error(f"❌ complete_order: замовлення #{order_id} належить водію {current_driver}, а не {driver_id}")
                    return False
                    
                if current_status not in ('accepted', 'in_progress'):
                    logger.error(f"❌ complete_order: замовлення #{order_id} має статус '{current_status}', не можна завершити")
                    return False
            else:
                logger.error(f"❌ complete_order: замовлення #{order_id} не знайдено в БД")
                return False
        
        # Тепер оновлюємо
        cur = await db.execute(
            """
            UPDATE orders
            SET status = 'completed', finished_at = ?, fare_amount = ?, distance_m = ?, duration_s = ?, commission = ?
            WHERE id = ? AND driver_id = ? AND status IN ('accepted', 'in_progress')
            """,
            (now, fare_amount, distance_m, duration_s, commission, order_id, driver_id),
        )
        await db.commit()
        
        rows_affected = cur.rowcount
        if rows_affected > 0:
            logger.info(f"✅ complete_order: замовлення #{order_id} успішно оновлено, статус → 'completed'")
        else:
            logger.error(f"❌ complete_order: замовлення #{order_id} НЕ оновлено (rows_affected=0)")
        
        return rows_affected > 0


async def finalize_order_after_rating(db_path: str, order_id: int) -> bool:
    """
    Завершує замовлення після оцінки клієнта.
    Використовується коли клієнт ставить оцінку або пропускає її.
    """
    now = datetime.now(timezone.utc)
    async with db_manager.connect(db_path) as db:
        cur = await db.execute(
            """
            UPDATE orders
            SET status = 'completed', finished_at = COALESCE(finished_at, ?)
            WHERE id = ? AND status != 'completed' AND status != 'cancelled'
            """,
            (now, order_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_order_by_id(db_path: str, order_id: int) -> Optional[Order]:
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, user_id, name, phone, pickup_address, destination_address, comment, created_at,
                   pickup_lat, pickup_lon, dest_lat, dest_lon,
                   driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id,
                   car_class, tip_amount, payment_method
            FROM orders WHERE id = ?
            """,
            (order_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    return Order(
        id=row[0],
        user_id=row[1],
        name=row[2],
        phone=row[3],
        pickup_address=row[4],
        destination_address=row[5],
        comment=row[6],
        created_at=_parse_datetime(row[7]),
        pickup_lat=row[8],
        pickup_lon=row[9],
        dest_lat=row[10],
        dest_lon=row[11],
        driver_id=row[12],
        distance_m=row[13],
        duration_s=row[14],
        fare_amount=row[15],
        commission=row[16],
        status=row[17],
        started_at=(_parse_datetime(row[18]) if row[18] else None),
        finished_at=(_parse_datetime(row[19]) if row[19] else None),
        group_message_id=row[20],
        car_class=row[21] if row[21] else "economy",
        tip_amount=row[22],
        payment_method=row[23] if row[23] else "cash",
    )


async def fetch_online_drivers(db_path: str, limit: int = 50) -> List[Driver]:
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status,
                   created_at, updated_at, city, online, last_lat, last_lon, last_seen_at, car_class, card_number, car_color, priority
            FROM drivers WHERE status = 'approved' AND online = 1
            ORDER BY last_seen_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
    drivers: List[Driver] = []
    for r in rows:
        drivers.append(
            Driver(
                id=r[0],
                tg_user_id=r[1],
                full_name=r[2],
                phone=r[3],
                car_make=r[4],
                car_model=r[5],
                car_plate=r[6],
                license_photo_file_id=r[7],
                status=r[8],
                created_at=_parse_datetime(r[9]),
                updated_at=_parse_datetime(r[10]),
                city=r[11],
                online=r[12],
                last_lat=r[13],
                last_lon=r[14],
                last_seen_at=(_parse_datetime(r[15]) if r[15] else None),
                car_class=r[16] if r[16] else "economy",
                card_number=r[17],
                car_color=r[18] if len(r) > 18 else None,  # ← ДОДАНО
                priority=(r[19] if len(r) > 19 else 0),
            )
        )
    return drivers


# --- Ratings ---

@dataclass
class Rating:
    id: Optional[int]
    order_id: int
    from_user_id: int
    to_user_id: int
    rating: int  # 1-5
    comment: Optional[str]
    created_at: datetime


@dataclass
class ClientRating:
    id: Optional[int]
    order_id: int
    client_id: int
    driver_id: int
    rating: int  # 1-5
    created_at: datetime


async def insert_rating(db_path: str, rating: Rating) -> int:
    async with db_manager.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO ratings (order_id, from_user_id, to_user_id, rating, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (rating.order_id, rating.from_user_id, rating.to_user_id, rating.rating, rating.comment, rating.created_at),
        )
        await db.commit()
        return cursor.lastrowid


async def get_driver_average_rating(db_path: str, driver_user_id: int) -> Optional[float]:
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            "SELECT AVG(rating) FROM ratings WHERE to_user_id = ?",
            (driver_user_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row and row[0] else None


# --- Client Ratings ---

async def insert_client_rating(db_path: str, rating: ClientRating) -> int:
    async with db_manager.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO client_ratings (order_id, client_id, driver_id, rating, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rating.order_id, rating.client_id, rating.driver_id, rating.rating, rating.created_at),
        )
        await db.commit()
        return cursor.lastrowid


async def get_client_average_rating(db_path: str, client_id: int) -> Optional[float]:
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            "SELECT AVG(rating) FROM client_ratings WHERE client_id = ?",
            (client_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row and row[0] else None


# --- Tips ---

async def add_tip_to_order(db_path: str, order_id: int, amount: float) -> bool:
    async with db_manager.connect(db_path) as db:
        try:
            await db.execute(
                "INSERT INTO tips (order_id, amount, created_at) VALUES (?, ?, ?)",
                (order_id, amount, datetime.now(timezone.utc))
            )
            await db.commit()
            return True
        except:
            return False


async def get_driver_tips_total(db_path: str, driver_tg_id: int) -> float:
    """Отримати загальну суму чайових водія"""
    async with db_manager.connect(db_path) as db:
        # Get driver DB id
        async with db.execute("SELECT id FROM drivers WHERE tg_user_id = ?", (driver_tg_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return 0.0
        driver_db_id = row[0]
        
        async with db.execute(
            """
            SELECT SUM(t.amount) FROM tips t
            JOIN orders o ON t.order_id = o.id
            WHERE o.driver_id = ?
            """,
            (driver_db_id,)
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row and row[0] else 0.0


# --- Referral Program ---

async def create_referral_code(db_path: str, user_id: int, code: str) -> None:
    async with db_manager.connect(db_path) as db:
        await db.execute(
            "INSERT INTO referrals (referrer_id, referred_id, referral_code, created_at) VALUES (?, 0, ?, ?)",
            (user_id, code, datetime.now(timezone.utc))
        )
        await db.commit()


async def get_referral_code(db_path: str, user_id: int) -> Optional[str]:
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            "SELECT referral_code FROM referrals WHERE referrer_id = ? AND referred_id = 0 LIMIT 1",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


async def apply_referral_code(db_path: str, new_user_id: int, code: str) -> bool:
    async with db_manager.connect(db_path) as db:
        # Знайти власника коду
        async with db.execute(
            "SELECT referrer_id FROM referrals WHERE referral_code = ? AND referred_id = 0",
            (code,)
        ) as cur:
            row = await cur.fetchone()
        
        if not row:
            return False
        
        referrer_id = row[0]
        
        # Створити запис про реферала
        await db.execute(
            """
            INSERT INTO referrals (referrer_id, referred_id, referral_code, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (referrer_id, new_user_id, code, datetime.now(timezone.utc))
        )
        await db.commit()
        return True


async def get_user_referral_stats(db_path: str, user_id: int) -> dict:
    async with db_manager.connect(db_path) as db:
        # Кількість запрошених
        async with db.execute(
            "SELECT COUNT(*), SUM(referrer_bonus) FROM referrals WHERE referrer_id = ? AND referred_id != 0",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
    
    return {
        'referred_count': row[0] if row else 0,
        'total_bonus': row[1] if row and row[1] else 0
    }


# --- Payments & Commissions ---

@dataclass
class Payment:
    id: Optional[int]
    order_id: int
    driver_id: int
    amount: float
    commission: float
    commission_paid: bool
    payment_method: str  # cash, card
    created_at: datetime
    commission_paid_at: Optional[datetime] = None


async def insert_payment(db_path: str, payment: Payment) -> int:
    async with db_manager.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO payments (order_id, driver_id, amount, commission, commission_paid, payment_method, created_at, commission_paid_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (payment.order_id, payment.driver_id, payment.amount, payment.commission, 1 if payment.commission_paid else 0, payment.payment_method, payment.created_at, payment.commission_paid_at if payment.commission_paid_at else None),
        )
        await db.commit()
        return cursor.lastrowid


async def mark_commission_paid(db_path: str, driver_tg_id: int) -> None:
    now = datetime.now(timezone.utc)
    async with db_manager.connect(db_path) as db:
        # Get driver's DB id
        async with db.execute("SELECT id FROM drivers WHERE tg_user_id = ? AND status = 'approved'", (driver_tg_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return
        driver_db_id = row[0]
        await db.execute(
            "UPDATE payments SET commission_paid = 1, commission_paid_at = ? WHERE driver_id = ? AND commission_paid = 0",
            (now, driver_db_id),
        )
        await db.commit()


async def get_driver_earnings_today(db_path: str, driver_tg_id: int) -> Tuple[float, float]:
    """Returns (total_earned, total_commission_owed) for today"""
    async with db_manager.connect(db_path) as db:
        async with db.execute("SELECT id FROM drivers WHERE tg_user_id = ? AND status = 'approved'", (driver_tg_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return (0.0, 0.0)
        driver_db_id = row[0]
        today = datetime.now(timezone.utc).date()
        async with db.execute(
            """
            SELECT SUM(amount), SUM(commission) FROM payments
            WHERE driver_id = ? AND DATE(created_at) = ?
            """,
            (driver_db_id, today),
        ) as cur:
            row = await cur.fetchone()
    total_earned = row[0] if row and row[0] else 0.0
    total_commission = row[1] if row and row[1] else 0.0
    return (total_earned, total_commission)


async def get_driver_detailed_earnings_today(db_path: str, driver_tg_id: int) -> dict:
    """
    Повертає детальну статистику заробітку водія за сьогодні
    
    Returns:
        dict: {
            'total': float,           # Загальний заробіток
            'cash': float,            # Готівка
            'card': float,            # Картка
            'commission': float,      # Комісія
            'trips_count': int,       # Кількість поїздок
            'hours_worked': float     # Відпрацьовано годин
        }
    """
    async with db_manager.connect(db_path) as db:
        # Отримати driver_id
        async with db.execute(
            "SELECT id FROM drivers WHERE tg_user_id = ? AND status = 'approved'",
            (driver_tg_id,)
        ) as cur:
            row = await cur.fetchone()
        
        if not row:
            return {
                'total': 0.0,
                'cash': 0.0,
                'card': 0.0,
                'commission': 0.0,
                'trips_count': 0,
                'hours_worked': 0.0
            }
        
        driver_db_id = row[0]
        today = datetime.now(timezone.utc).date()
        
        # Отримати розбивку по готівці та картці
        async with db.execute(
            """
            SELECT 
                SUM(CASE WHEN payment_method = 'cash' THEN amount ELSE 0 END) as cash_total,
                SUM(CASE WHEN payment_method = 'card' THEN amount ELSE 0 END) as card_total,
                SUM(commission) as total_commission,
                SUM(amount) as total_amount
            FROM payments
            WHERE driver_id = ? AND DATE(created_at) = ?
            """,
            (driver_db_id, today)
        ) as cur:
            row = await cur.fetchone()
        
        cash = row[0] if row and row[0] else 0.0
        card = row[1] if row and row[1] else 0.0
        commission = row[2] if row and row[2] else 0.0
        total = row[3] if row and row[3] else 0.0
        
        # Отримати кількість поїздок та тривалість
        async with db.execute(
            """
            SELECT 
                COUNT(*) as trips_count,
                SUM(COALESCE(duration_s, 0)) as total_duration_seconds
            FROM orders
            WHERE driver_id = ? 
            AND status = 'completed'
            AND DATE(created_at) = ?
            """,
            (driver_db_id, today)
        ) as cur:
            row = await cur.fetchone()
        
        trips_count = row[0] if row and row[0] else 0
        total_duration_seconds = row[1] if row and row[1] else 0
        hours_worked = total_duration_seconds / 3600.0 if total_duration_seconds else 0.0
        
        # Якщо немає даних про тривалість, орієнтовно 20 хв на поїздку
        if hours_worked == 0 and trips_count > 0:
            hours_worked = (trips_count * 20) / 60.0
        
        return {
            'total': total,
            'cash': cash,
            'card': card,
            'commission': commission,
            'trips_count': trips_count,
            'hours_worked': hours_worked
        }


async def get_driver_unpaid_commission(db_path: str, driver_tg_id: int) -> float:
    async with db_manager.connect(db_path) as db:
        async with db.execute("SELECT id FROM drivers WHERE tg_user_id = ? AND status = 'approved'", (driver_tg_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return 0.0
        driver_db_id = row[0]
        async with db.execute(
            "SELECT SUM(commission) FROM payments WHERE driver_id = ? AND commission_paid = 0",
            (driver_db_id,),
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row and row[0] else 0.0


# --- Order History ---

async def get_user_order_history(db_path: str, user_id: int, limit: int = 10) -> List[Order]:
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, user_id, name, phone, pickup_address, destination_address, comment, created_at,
                   pickup_lat, pickup_lon, dest_lat, dest_lon,
                   driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id,
                   car_class, tip_amount, payment_method
            FROM orders
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    orders: List[Order] = []
    for row in rows:
        orders.append(
            Order(
                id=row[0],
                user_id=row[1],
                name=row[2],
                phone=row[3],
                pickup_address=row[4],
                destination_address=row[5],
                comment=row[6],
                created_at=_parse_datetime(row[7]),
                pickup_lat=row[8],
                pickup_lon=row[9],
                dest_lat=row[10],
                dest_lon=row[11],
                driver_id=row[12],
                distance_m=row[13],
                duration_s=row[14],
                fare_amount=row[15],
                commission=row[16],
                status=row[17],
                started_at=(_parse_datetime(row[18]) if row[18] else None),
                finished_at=(_parse_datetime(row[19]) if row[19] else None),
                group_message_id=row[20],
                car_class=row[21] if row[21] else "economy",
                tip_amount=row[22],
                payment_method=row[23] if row[23] else "cash",
            )
        )
    return orders


async def get_driver_order_history(db_path: str, driver_tg_id: int, limit: int = 10) -> List[Order]:
    async with db_manager.connect(db_path) as db:
        # Get driver DB id
        async with db.execute("SELECT id FROM drivers WHERE tg_user_id = ?", (driver_tg_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return []
        driver_db_id = row[0]
        async with db.execute(
            """
            SELECT id, user_id, name, phone, pickup_address, destination_address, comment, created_at,
                   pickup_lat, pickup_lon, dest_lat, dest_lon,
                   driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id,
                   car_class, tip_amount, payment_method
            FROM orders
            WHERE driver_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (driver_db_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    orders: List[Order] = []
    for row in rows:
        orders.append(
            Order(
                id=row[0],
                user_id=row[1],
                name=row[2],
                phone=row[3],
                pickup_address=row[4],
                destination_address=row[5],
                comment=row[6],
                created_at=_parse_datetime(row[7]),
                pickup_lat=row[8],
                pickup_lon=row[9],
                dest_lat=row[10],
                dest_lon=row[11],
                driver_id=row[12],
                distance_m=row[13],
                duration_s=row[14],
                fare_amount=row[15],
                commission=row[16],
                status=row[17],
                started_at=(_parse_datetime(row[18]) if row[18] else None),
                finished_at=(_parse_datetime(row[19]) if row[19] else None),
                group_message_id=row[20],
                car_class=row[21] if row[21] else "economy",
                tip_amount=row[22],
                payment_method=row[23] if row[23] else "cash",
            )
        )
    return orders


async def _ensure_columns(db: aiosqlite.Connection) -> None:
    async def has_column(table: str, column: str) -> bool:
        async with db.execute(f"PRAGMA table_info({table})") as cur:
            rows = await cur.fetchall()
        return any(r[1] == column for r in rows)

    # Best-effort add columns if missing
    # Orders
    if not await has_column('orders', 'pickup_lat'):
        await db.execute("ALTER TABLE orders ADD COLUMN pickup_lat REAL")
    if not await has_column('orders', 'pickup_lon'):
        await db.execute("ALTER TABLE orders ADD COLUMN pickup_lon REAL")
    if not await has_column('orders', 'dest_lat'):
        await db.execute("ALTER TABLE orders ADD COLUMN dest_lat REAL")
    if not await has_column('orders', 'dest_lon'):
        await db.execute("ALTER TABLE orders ADD COLUMN dest_lon REAL")
    if not await has_column('orders', 'driver_id'):
        await db.execute("ALTER TABLE orders ADD COLUMN driver_id INTEGER")
    if not await has_column('orders', 'distance_m'):
        await db.execute("ALTER TABLE orders ADD COLUMN distance_m INTEGER")
    if not await has_column('orders', 'duration_s'):
        await db.execute("ALTER TABLE orders ADD COLUMN duration_s INTEGER")
    if not await has_column('orders', 'fare_amount'):
        await db.execute("ALTER TABLE orders ADD COLUMN fare_amount REAL")
    if not await has_column('orders', 'commission'):
        await db.execute("ALTER TABLE orders ADD COLUMN commission REAL")
    if not await has_column('orders', 'status'):
        await db.execute("ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
    if not await has_column('orders', 'started_at'):
        await db.execute("ALTER TABLE orders ADD COLUMN started_at TEXT")
    if not await has_column('orders', 'finished_at'):
        await db.execute("ALTER TABLE orders ADD COLUMN finished_at TEXT")
    if not await has_column('orders', 'group_message_id'):
        await db.execute("ALTER TABLE orders ADD COLUMN group_message_id INTEGER")
    if not await has_column('orders', 'car_class'):
        await db.execute("ALTER TABLE orders ADD COLUMN car_class TEXT NOT NULL DEFAULT 'economy'")
    if not await has_column('orders', 'tip_amount'):
        await db.execute("ALTER TABLE orders ADD COLUMN tip_amount REAL")
    if not await has_column('orders', 'payment_method'):
        await db.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'cash'")

    # Drivers
    if not await has_column('drivers', 'online'):
        await db.execute("ALTER TABLE drivers ADD COLUMN online INTEGER NOT NULL DEFAULT 0")
    if not await has_column('drivers', 'last_lat'):
        await db.execute("ALTER TABLE drivers ADD COLUMN last_lat REAL")
    if not await has_column('drivers', 'last_lon'):
        await db.execute("ALTER TABLE drivers ADD COLUMN last_lon REAL")
    if not await has_column('drivers', 'last_seen_at'):
        await db.execute("ALTER TABLE drivers ADD COLUMN last_seen_at TEXT")
    if not await has_column('drivers', 'city'):
        await db.execute("ALTER TABLE drivers ADD COLUMN city TEXT")
    if not await has_column('drivers', 'car_class'):
        await db.execute("ALTER TABLE drivers ADD COLUMN car_class TEXT NOT NULL DEFAULT 'economy'")
    if not await has_column('drivers', 'card_number'):
        await db.execute("ALTER TABLE drivers ADD COLUMN card_number TEXT")
    
    # Users
    if not await has_column('users', 'city'):
        await db.execute("ALTER TABLE users ADD COLUMN city TEXT")
    if not await has_column('users', 'language'):
        await db.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'uk'")


# --- Tariffs ---

@dataclass
class Tariff:
    id: Optional[int]
    base_fare: float
    per_km: float
    per_minute: float
    minimum: float
    commission_percent: float  # e.g., 0.02 for 2%
    night_tariff_percent: float = 50.0  # % надбавка за нічний тариф (за замовчуванням 50%)
    weather_percent: float = 0.0  # % надбавка за погодні умови (за замовчуванням 0%)
    created_at: Optional[datetime] = None


async def insert_tariff(db_path: str, t: Tariff) -> int:
    async with db_manager.connect(db_path) as db:
        # Спробувати з новими колонками
        try:
            cursor = await db.execute(
                """
                INSERT INTO tariffs (base_fare, per_km, per_minute, minimum, commission_percent, night_tariff_percent, weather_percent, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (t.base_fare, t.per_km, t.per_minute, t.minimum, t.commission_percent, t.night_tariff_percent, t.weather_percent, t.created_at),
            )
        except Exception as e:
            # Fallback: стара схема без нових колонок
            logger.warning(f"⚠️ Insert tariff: використовую стару схему (без night_tariff_percent/weather_percent)")
            cursor = await db.execute(
                """
                INSERT INTO tariffs (base_fare, per_km, per_minute, minimum, commission_percent, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (t.base_fare, t.per_km, t.per_minute, t.minimum, t.commission_percent, t.created_at),
            )
        
        await db.commit()
        return cursor.lastrowid


async def update_tariff_multipliers(db_path: str, night_percent: float, weather_percent: float) -> bool:
    """Оновити множники націнок в останньому тарифі"""
    async with db_manager.connect(db_path) as db:
        # Отримати ID останнього тарифу
        cur = await db.execute("SELECT id FROM tariffs ORDER BY id DESC LIMIT 1")
        row = await cur.fetchone()
        
        if not row:
            return False
        
        tariff_id = row[0]
        
        # Оновити множники
        cur = await db.execute(
            """
            UPDATE tariffs 
            SET night_tariff_percent = ?, weather_percent = ?
            WHERE id = ?
            """,
            (night_percent, weather_percent, tariff_id)
        )
        await db.commit()
        
        logger.info(f"✅ Оновлено націнки: нічний={night_percent}%, погода={weather_percent}%")
        return cur.rowcount > 0


async def get_latest_tariff(db_path: str) -> Optional[Tariff]:
    """Отримати останній тариф (з підтримкою старої та нової схеми)"""
    async with db_manager.connect(db_path) as db:
        # СПОЧАТКУ спробувати зі СТАРОЮ схемою (безпечно)
        try:
            async with db.execute(
                "SELECT id, base_fare, per_km, per_minute, minimum, commission_percent, created_at FROM tariffs ORDER BY id DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
            
            if not row:
                return None
            
            # Базові дані є (стара схема працює)
            base_tariff = {
                'id': row[0],
                'base_fare': row[1],
                'per_km': row[2],
                'per_minute': row[3],
                'minimum': row[4],
                'commission_percent': row[5] if row[5] is not None else 0.02,
                'created_at': _parse_datetime(row[6])
            }
            
            # Тепер спробувати прочитати НОВІ колонки (якщо є)
            try:
                async with db.execute(
                    "SELECT night_tariff_percent, weather_percent FROM tariffs WHERE id = ? LIMIT 1",
                    (base_tariff['id'],)
                ) as cursor:
                    extra_row = await cursor.fetchone()
                
                if extra_row and len(extra_row) >= 2:
                    base_tariff['night_tariff_percent'] = extra_row[0] if extra_row[0] is not None else 50.0
                    base_tariff['weather_percent'] = extra_row[1] if extra_row[1] is not None else 0.0
                    logger.info("✅ Tariffs: використовую НОВУ схему (з night_tariff_percent/weather_percent)")
                else:
                    raise Exception("New columns not found")
            
            except Exception:
                # Нові колонки відсутні - використати дефолти
                base_tariff['night_tariff_percent'] = 50.0
                base_tariff['weather_percent'] = 0.0
                logger.warning("⚠️ Tariffs: використовую СТАРУ схему (дефолти: night=50%, weather=0%)")
            
            return Tariff(**base_tariff)
        
        except Exception as e:
            logger.error(f"❌ Критична помилка читання tariffs: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None


# === СИСТЕМА КАРМИ ===

async def decrease_driver_karma(db_path: str, driver_id: int, amount: int = 5) -> bool:
    """Зменшити карму водія (за відмову від замовлення)"""
    async with db_manager.connect(db_path) as db:
        try:
            # Зменшити карму, але не нижче 0
            await db.execute(
                """
                UPDATE drivers 
                SET karma = GREATEST(0, karma - ?),
                    rejected_orders = rejected_orders + 1
                WHERE id = ?
                """,
                (amount, driver_id)
            )
            await db.commit()
            logger.info(f"⚠️ Карма водія #{driver_id} зменшена на -{amount}")
            return True
        except Exception as e:
            logger.error(f"❌ Помилка зменшення карми водія: {e}")
            return False


async def decrease_client_karma(db_path: str, user_id: int, amount: int = 5) -> bool:
    """Зменшити карму клієнта (за скасування замовлення)"""
    async with db_manager.connect(db_path) as db:
        try:
            await db.execute(
                """
                UPDATE users 
                SET karma = GREATEST(0, karma - ?),
                    cancelled_orders = cancelled_orders + 1
                WHERE user_id = ?
                """,
                (amount, user_id)
            )
            await db.commit()
            logger.info(f"⚠️ Карма клієнта #{user_id} зменшена на -{amount}")
            return True
        except Exception as e:
            logger.error(f"❌ Помилка зменшення карми клієнта: {e}")
            return False


async def increase_driver_karma(db_path: str, driver_id: int, amount: int = 1) -> bool:
    """Збільшити карму водія (за успішне замовлення), макс 100"""
    async with db_manager.connect(db_path) as db:
        try:
            await db.execute(
                """
                UPDATE drivers 
                SET karma = LEAST(100, karma + ?),
                    total_orders = total_orders + 1
                WHERE id = ?
                """,
                (amount, driver_id)
            )
            await db.commit()
            logger.info(f"✅ Карма водія #{driver_id} збільшена на +{amount}")
            return True
        except Exception as e:
            logger.error(f"❌ Помилка збільшення карми водія: {e}")
            return False


async def increase_client_karma(db_path: str, user_id: int, amount: int = 1) -> bool:
    """Збільшити карму клієнта (за успішне замовлення), макс 100"""
    async with db_manager.connect(db_path) as db:
        try:
            await db.execute(
                """
                UPDATE users 
                SET karma = LEAST(100, karma + ?),
                    total_orders = total_orders + 1
                WHERE user_id = ?
                """,
                (amount, user_id)
            )
            await db.commit()
            logger.info(f"✅ Карма клієнта #{user_id} збільшена на +{amount}")
            return True
        except Exception as e:
            logger.error(f"❌ Помилка збільшення карми клієнта: {e}")
            return False


async def add_rides_to_client(db_path: str, user_id: int, count: int) -> bool:
    """
    Додати поїздки клієнту (адмін функція).
    
    Збільшує total_orders БЕЗ зміни карми.
    Використовується адміном для коригування статистики.
    """
    async with db_manager.connect(db_path) as db:
        try:
            await db.execute(
                """UPDATE users 
                   SET bonus_rides_available = bonus_rides_available + ?,
                       total_orders = total_orders + ?
                   WHERE user_id = ?""",
                (count, count, user_id)
            )
            await db.commit()
            logger.info(f"✅ Адмін додав {count} бонусних поїздок клієнту #{user_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Помилка додавання поїздок клієнту: {e}")
            return False


async def use_bonus_ride(db_path: str, user_id: int) -> bool:
    """
    Використати одну бонусну поїздку.
    
    Викликається при створенні замовлення якщо базовий ліміт перевищено.
    Зменшує bonus_rides_available на 1.
    
    Returns:
        True якщо бонусна поїздка була використана, False якщо немає доступних
    """
    async with db_manager.connect(db_path) as db:
        try:
            # Спочатку перевірити чи є доступні бонусні поїздки
            async with db.execute(
                "SELECT COALESCE(bonus_rides_available, 0) FROM users WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row or row[0] <= 0:
                    return False
            
            # Зменшити кількість бонусних поїздок
            await db.execute(
                "UPDATE users SET bonus_rides_available = bonus_rides_available - 1 WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()
            logger.info(f"✅ Клієнт #{user_id} використав бонусну поїздку")
            return True
        except Exception as e:
            logger.error(f"❌ Помилка використання бонусної поїздки: {e}")
            return False


async def use_bonus_ride(db_path: str, user_id: int) -> bool:
    """
    Використати одну бонусну поїздку.
    
    Викликається при створенні замовлення якщо базовий ліміт перевищено.
    Зменшує bonus_rides_available на 1.
    
    Returns:
        True якщо бонусна поїздка була використана, False якщо немає доступних
    """
    async with db_manager.connect(db_path) as db:
        try:
            # Спочатку перевірити чи є доступні бонусні поїздки
            async with db.execute(
                "SELECT COALESCE(bonus_rides_available, 0) FROM users WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row or row[0] <= 0:
                    return False
            
            # Зменшити кількість бонусних поїздок
            await db.execute(
                "UPDATE users SET bonus_rides_available = bonus_rides_available - 1 WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()
            logger.info(f"✅ Клієнт #{user_id} використав бонусну поїздку")
            return True
        except Exception as e:
            logger.error(f"❌ Помилка використання бонусної поїздки: {e}")
            return False

# --- Pricing Settings (Налаштування ціноутворення) ---

@dataclass
class PricingSettings:
    """Налаштування всіх множників для ціноутворення"""
    id: Optional[int] = None
    
    # Класи авто (множники)
    economy_multiplier: float = 1.0
    standard_multiplier: float = 1.3
    comfort_multiplier: float = 1.6
    business_multiplier: float = 2.0
    
    # Часові націнки
    night_percent: float = 50.0  # 23:00-06:00
    peak_hours_percent: float = 30.0  # 7-9, 17-19
    weekend_percent: float = 20.0  # Пт-Нд вечір 18-23
    monday_morning_percent: float = 15.0  # Пн 7-10
    
    # Погода
    weather_percent: float = 0.0
    
    # Попит (множники при різному співвідношенні замовлень/водіїв)
    demand_very_high_percent: float = 40.0  # ratio > 3
    demand_high_percent: float = 25.0  # ratio > 2
    demand_medium_percent: float = 15.0  # ratio > 1.5
    demand_low_discount_percent: float = 10.0  # ratio < 0.3 (знижка)
    
    # Інші параметри
    no_drivers_percent: float = 50.0  # Коли немає водіїв взагалі
    
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


async def get_pricing_settings(db_path: str) -> PricingSettings | None:
    """Отримати поточні налаштування ціноутворення (або None якщо не налаштовано)"""
    async with db_manager.connect(db_path) as db:
        try:
            async with db.execute(
                """
                SELECT id, economy_multiplier, standard_multiplier, comfort_multiplier, business_multiplier,
                       night_percent, peak_hours_percent, weekend_percent, monday_morning_percent,
                       weather_percent, demand_very_high_percent, demand_high_percent, 
                       demand_medium_percent, demand_low_discount_percent, no_drivers_percent,
                       created_at, updated_at
                FROM pricing_settings ORDER BY id DESC LIMIT 1
                """
            ) as cursor:
                row = await cursor.fetchone()
            
            if row:
                return PricingSettings(
                    id=row[0],
                    economy_multiplier=row[1],
                    standard_multiplier=row[2],
                    comfort_multiplier=row[3],
                    business_multiplier=row[4],
                    night_percent=row[5],
                    peak_hours_percent=row[6],
                    weekend_percent=row[7],
                    monday_morning_percent=row[8],
                    weather_percent=row[9],
                    demand_very_high_percent=row[10],
                    demand_high_percent=row[11],
                    demand_medium_percent=row[12],
                    demand_low_discount_percent=row[13],
                    no_drivers_percent=row[14],
                    created_at=_parse_datetime(row[15]) if row[15] else None,
                    updated_at=_parse_datetime(row[16]) if row[16] else None,
                )
        except Exception as e:
            logger.warning(f"⚠️ Помилка читання pricing_settings: {e}")
    
    # Повернути None якщо не знайдено
    return None


async def upsert_pricing_settings(db_path: str, settings: PricingSettings) -> bool:
    """Створити або оновити налаштування ціноутворення"""
    async with db_manager.connect(db_path) as db:
        try:
            now = datetime.now(timezone.utc)
            
            # Перевірити чи є запис
            async with db.execute("SELECT id FROM pricing_settings LIMIT 1") as cursor:
                existing = await cursor.fetchone()
            
            if existing:
                # Оновити
                await db.execute(
                    """
                    UPDATE pricing_settings SET
                        economy_multiplier = ?,
                        standard_multiplier = ?,
                        comfort_multiplier = ?,
                        business_multiplier = ?,
                        night_percent = ?,
                        peak_hours_percent = ?,
                        weekend_percent = ?,
                        monday_morning_percent = ?,
                        weather_percent = ?,
                        demand_very_high_percent = ?,
                        demand_high_percent = ?,
                        demand_medium_percent = ?,
                        demand_low_discount_percent = ?,
                        no_drivers_percent = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        settings.economy_multiplier,
                        settings.standard_multiplier,
                        settings.comfort_multiplier,
                        settings.business_multiplier,
                        settings.night_percent,
                        settings.peak_hours_percent,
                        settings.weekend_percent,
                        settings.monday_morning_percent,
                        settings.weather_percent,
                        settings.demand_very_high_percent,
                        settings.demand_high_percent,
                        settings.demand_medium_percent,
                        settings.demand_low_discount_percent,
                        settings.no_drivers_percent,
                        now,
                        existing[0]
                    )
                )
            else:
                # Створити новий
                await db.execute(
                    """
                    INSERT INTO pricing_settings (
                        economy_multiplier, standard_multiplier, comfort_multiplier, business_multiplier,
                        night_percent, peak_hours_percent, weekend_percent, monday_morning_percent,
                        weather_percent, demand_very_high_percent, demand_high_percent,
                        demand_medium_percent, demand_low_discount_percent, no_drivers_percent,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        settings.economy_multiplier,
                        settings.standard_multiplier,
                        settings.comfort_multiplier,
                        settings.business_multiplier,
                        settings.night_percent,
                        settings.peak_hours_percent,
                        settings.weekend_percent,
                        settings.monday_morning_percent,
                        settings.weather_percent,
                        settings.demand_very_high_percent,
                        settings.demand_high_percent,
                        settings.demand_medium_percent,
                        settings.demand_low_discount_percent,
                        settings.no_drivers_percent,
                        now,
                        now
                    )
                )
            
            await db.commit()
            logger.info("✅ Налаштування ціноутворення збережено")
            return True
            
        except Exception as e:
            logger.error(f"❌ Помилка збереження pricing_settings: {e}")
            return False


# ════════════════════════════════════════════════════════════════════════════
# METRICS HELPERS (для моніторингу)
# ════════════════════════════════════════════════════════════════════════════

async def count_users(db_path: str) -> int:
    """Підрахувати загальну кількість користувачів"""
    async with db_manager.connect(db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def count_drivers(db_path: str) -> int:
    """Підрахувати загальну кількість водіїв (approved)"""
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM drivers WHERE status = ?", ("approved",)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def count_online_drivers(db_path: str) -> int:
    """Підрахувати кількість онлайн водіїв"""
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM drivers WHERE is_online = ? AND status = ?",
            (True, "approved")
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def count_orders(db_path: str) -> int:
    """Підрахувати загальну кількість замовлень"""
    async with db_manager.connect(db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM orders") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def count_orders_by_status(db_path: str, statuses: list) -> int:
    """
    Підрахувати кількість замовлень за статусами
    
    Args:
        db_path: Шлях до БД
        statuses: Список статусів (наприклад, ["pending", "accepted"])
    
    Returns:
        Кількість замовлень
    """
    if not statuses:
        return 0
    
    async with db_manager.connect(db_path) as db:
        placeholders = ",".join(["?" for _ in statuses])
        query = f"SELECT COUNT(*) FROM orders WHERE status IN ({placeholders})"
        
        async with db.execute(query, tuple(statuses)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
