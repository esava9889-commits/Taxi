from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import aiosqlite


@dataclass
class Order:
    id: Optional[int]
    user_id: int
    name: str
    phone: str
    pickup_address: str
    destination_address: str
    comment: Optional[str]
    created_at: datetime


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
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
                created_at TEXT NOT NULL
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
                created_at TEXT NOT NULL
            )
            """
        )
        # Users: registered clients
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
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
                status TEXT NOT NULL,  -- pending | approved | rejected
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Helpful indices
        await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_drivers_status ON drivers(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_drivers_tg_user ON drivers(tg_user_id)")
        await db.commit()


async def insert_order(db_path: str, order: Order) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO orders (
                user_id, name, phone, pickup_address, destination_address, comment, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.user_id,
                order.name,
                order.phone,
                order.pickup_address,
                order.destination_address,
                order.comment,
                order.created_at.isoformat(),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def fetch_recent_orders(db_path: str, limit: int = 10) -> List[Order]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, user_id, name, phone, pickup_address, destination_address, comment, created_at
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
                created_at=datetime.fromisoformat(row[7]),
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


async def upsert_user(db_path: str, user: User) -> None:
    """
    Insert or replace a user profile. Uses user_id as a stable primary key.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, full_name, phone, role, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              full_name=excluded.full_name,
              phone=excluded.phone,
              role=excluded.role
            """,
            (
                user.user_id,
                user.full_name,
                user.phone,
                user.role,
                user.created_at.isoformat(),
            ),
        )
        await db.commit()


async def get_user_by_id(db_path: str, user_id: int) -> Optional[User]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT user_id, full_name, phone, role, created_at FROM users WHERE user_id = ?",
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
        created_at=datetime.fromisoformat(row[4]),
    )


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


async def create_driver_application(db_path: str, driver: Driver) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO drivers (
                tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                driver.tg_user_id,
                driver.full_name,
                driver.phone,
                driver.car_make,
                driver.car_model,
                driver.car_plate,
                driver.license_photo_file_id,
                driver.status,
                driver.created_at.isoformat(),
                driver.updated_at.isoformat(),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def update_driver_status(db_path: str, driver_id: int, status: str) -> None:
    now = datetime.now(timezone.utc)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE drivers SET status = ?, updated_at = ? WHERE id = ?",
            (status, now.isoformat(), driver_id),
        )
        await db.commit()


async def fetch_pending_drivers(db_path: str, limit: int = 20) -> List[Driver]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status, created_at, updated_at
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
                created_at=datetime.fromisoformat(r[9]),
                updated_at=datetime.fromisoformat(r[10]),
            )
        )
    return drivers


async def get_driver_by_id(db_path: str, driver_id: int) -> Optional[Driver]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status, created_at, updated_at
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
        created_at=datetime.fromisoformat(row[9]),
        updated_at=datetime.fromisoformat(row[10]),
    )


async def get_driver_by_tg_user_id(db_path: str, tg_user_id: int) -> Optional[Driver]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status, created_at, updated_at
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
        created_at=datetime.fromisoformat(row[9]),
        updated_at=datetime.fromisoformat(row[10]),
    )


# --- Tariffs ---

@dataclass
class Tariff:
    id: Optional[int]
    base_fare: float
    per_km: float
    per_minute: float
    minimum: float
    created_at: datetime


async def insert_tariff(db_path: str, t: Tariff) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO tariffs (base_fare, per_km, per_minute, minimum, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (t.base_fare, t.per_km, t.per_minute, t.minimum, t.created_at.isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_latest_tariff(db_path: str) -> Optional[Tariff]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT id, base_fare, per_km, per_minute, minimum, created_at FROM tariffs ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    return Tariff(
        id=row[0],
        base_fare=row[1],
        per_km=row[2],
        per_minute=row[3],
        minimum=row[4],
        created_at=datetime.fromisoformat(row[5]),
    )
