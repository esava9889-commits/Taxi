from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import aiosqlite


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
                group_message_id INTEGER
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
                city TEXT,
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
                city TEXT,
                status TEXT NOT NULL,  -- pending | approved | rejected
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                online INTEGER NOT NULL DEFAULT 0,
                last_lat REAL,
                last_lon REAL,
                last_seen_at TEXT
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
        # Try to add missing columns for incremental upgrades (SQLite only)
        await _ensure_columns(db)


async def insert_order(db_path: str, order: Order) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO orders (
                user_id, name, phone, pickup_address, destination_address, comment, created_at,
                pickup_lat, pickup_lon, dest_lat, dest_lon,
                driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.user_id,
                order.name,
                order.phone,
                order.pickup_address,
                order.destination_address,
                order.comment,
                order.created_at.isoformat(),
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
                (order.started_at.isoformat() if order.started_at else None),
                (order.finished_at.isoformat() if order.finished_at else None),
                order.group_message_id,
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def update_order_group_message(db_path: str, order_id: int, message_id: int) -> bool:
    """Оновити ID повідомлення в групі водіїв"""
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE orders SET group_message_id = ? WHERE id = ?",
            (message_id, order_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def cancel_order_by_client(db_path: str, order_id: int, user_id: int) -> bool:
    """Скасувати замовлення клієнтом (тільки якщо pending)"""
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE orders SET status = 'cancelled', finished_at = ? WHERE id = ? AND user_id = ? AND status = 'pending'",
            (datetime.now(timezone.utc).isoformat(), order_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def fetch_recent_orders(db_path: str, limit: int = 10) -> List[Order]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, user_id, name, phone, pickup_address, destination_address, comment, created_at,
                   pickup_lat, pickup_lon, dest_lat, dest_lon,
                   driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id
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
                started_at=(datetime.fromisoformat(row[18]) if row[18] else None),
                finished_at=(datetime.fromisoformat(row[19]) if row[19] else None),
                group_message_id=row[20],
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


async def upsert_user(db_path: str, user: User) -> None:
    """
    Insert or replace a user profile. Uses user_id as a stable primary key.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, full_name, phone, role, city, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              full_name=excluded.full_name,
              phone=excluded.phone,
              role=excluded.role,
              city=excluded.city
            """,
            (
                user.user_id,
                user.full_name,
                user.phone,
                user.role,
                user.city,
                user.created_at.isoformat(),
            ),
        )
        await db.commit()


async def get_user_by_id(db_path: str, user_id: int) -> Optional[User]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT user_id, full_name, phone, role, city, created_at FROM users WHERE user_id = ?",
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
        created_at=datetime.fromisoformat(row[5]),
        city=row[4],
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
    city: Optional[str] = None
    online: int = 0
    last_lat: Optional[float] = None
    last_lon: Optional[float] = None
    last_seen_at: Optional[datetime] = None


async def create_driver_application(db_path: str, driver: Driver) -> int:
    async with aiosqlite.connect(db_path) as db:
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
            SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status,
                   created_at, updated_at, online, last_lat, last_lon, last_seen_at
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
                online=r[11],
                last_lat=r[12],
                last_lon=r[13],
                last_seen_at=(datetime.fromisoformat(r[14]) if r[14] else None),
            )
        )
    return drivers


async def get_driver_by_id(db_path: str, driver_id: int) -> Optional[Driver]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status,
                   created_at, updated_at, city, online, last_lat, last_lon, last_seen_at
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
        city=row[11],
        online=row[12],
        last_lat=row[13],
        last_lon=row[14],
        last_seen_at=(datetime.fromisoformat(row[15]) if row[15] else None),
    )


async def get_driver_by_tg_user_id(db_path: str, tg_user_id: int) -> Optional[Driver]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status,
                   created_at, updated_at, city, online, last_lat, last_lon, last_seen_at
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
        city=row[11],
        online=row[12],
        last_lat=row[13],
        last_lon=row[14],
        last_seen_at=(datetime.fromisoformat(row[15]) if row[15] else None),
    )


async def set_driver_online(db_path: str, tg_user_id: int, online: bool) -> None:
    now = datetime.now(timezone.utc)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE drivers SET online = ?, last_seen_at = ? WHERE tg_user_id = ? AND status = 'approved'",
            (1 if online else 0, now.isoformat(), tg_user_id),
        )
        await db.commit()


async def update_driver_location(db_path: str, tg_user_id: int, lat: float, lon: float) -> None:
    now = datetime.now(timezone.utc)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE drivers SET last_lat = ?, last_lon = ?, last_seen_at = ? WHERE tg_user_id = ? AND status = 'approved'",
            (lat, lon, now.isoformat(), tg_user_id),
        )
        await db.commit()


async def offer_order_to_driver(db_path: str, order_id: int, driver_id: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE orders SET driver_id = ?, status = 'offered' WHERE id = ? AND status = 'pending'",
            (driver_id, order_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def accept_order(db_path: str, order_id: int, driver_id: int) -> bool:
    """Accept order from group - set driver and status to accepted"""
    async with aiosqlite.connect(db_path) as db:
        # Нова логіка: замовлення має status='pending' і driver_id=NULL
        # Перший водій хто клікне - отримує замовлення
        cur = await db.execute(
            "UPDATE orders SET status = 'accepted', driver_id = ? WHERE id = ? AND status = 'pending' AND driver_id IS NULL",
            (driver_id, order_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def reject_order(db_path: str, order_id: int) -> bool:
    """Reject order by driver - set status back to pending"""
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE orders SET status = 'pending', driver_id = NULL WHERE id = ? AND status = 'offered'",
            (order_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def add_rejected_driver(db_path: str, order_id: int, driver_db_id: int) -> None:
    """Add driver to rejected list for this order (stored as JSON in a new table or field)"""
    # For simplicity, we'll create a simple rejected_offers table
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS rejected_offers (order_id INTEGER, driver_id INTEGER, rejected_at TEXT)"
        )
        await db.execute(
            "INSERT INTO rejected_offers (order_id, driver_id, rejected_at) VALUES (?, ?, ?)",
            (order_id, driver_db_id, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()


async def get_rejected_drivers_for_order(db_path: str, order_id: int) -> List[int]:
    """Get list of driver IDs who rejected this order"""
    async with aiosqlite.connect(db_path) as db:
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
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE orders SET status = 'in_progress', started_at = ? WHERE id = ? AND driver_id = ? AND status = 'accepted'",
            (now.isoformat(), order_id, driver_id),
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
    now = datetime.now(timezone.utc)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            UPDATE orders
            SET status = 'completed', finished_at = ?, fare_amount = ?, distance_m = ?, duration_s = ?, commission = ?
            WHERE id = ? AND driver_id = ? AND status = 'in_progress'
            """,
            (now.isoformat(), fare_amount, distance_m, duration_s, commission, order_id, driver_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_order_by_id(db_path: str, order_id: int) -> Optional[Order]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, user_id, name, phone, pickup_address, destination_address, comment, created_at,
                   pickup_lat, pickup_lon, dest_lat, dest_lon,
                   driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id
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
        created_at=datetime.fromisoformat(row[7]),
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
        started_at=(datetime.fromisoformat(row[18]) if row[18] else None),
        finished_at=(datetime.fromisoformat(row[19]) if row[19] else None),
        group_message_id=row[20],
    )


async def fetch_online_drivers(db_path: str, limit: int = 50) -> List[Driver]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, license_photo_file_id, status,
                   created_at, updated_at, city, online, last_lat, last_lon, last_seen_at
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
                created_at=datetime.fromisoformat(r[9]),
                updated_at=datetime.fromisoformat(r[10]),
                city=r[11],
                online=r[12],
                last_lat=r[13],
                last_lon=r[14],
                last_seen_at=(datetime.fromisoformat(r[15]) if r[15] else None),
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


async def insert_rating(db_path: str, rating: Rating) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO ratings (order_id, from_user_id, to_user_id, rating, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (rating.order_id, rating.from_user_id, rating.to_user_id, rating.rating, rating.comment, rating.created_at.isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_driver_average_rating(db_path: str, driver_user_id: int) -> Optional[float]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT AVG(rating) FROM ratings WHERE to_user_id = ?",
            (driver_user_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row and row[0] else None


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
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO payments (order_id, driver_id, amount, commission, commission_paid, payment_method, created_at, commission_paid_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (payment.order_id, payment.driver_id, payment.amount, payment.commission, 1 if payment.commission_paid else 0, payment.payment_method, payment.created_at.isoformat(), payment.commission_paid_at.isoformat() if payment.commission_paid_at else None),
        )
        await db.commit()
        return cursor.lastrowid


async def mark_commission_paid(db_path: str, driver_tg_id: int) -> None:
    now = datetime.now(timezone.utc)
    async with aiosqlite.connect(db_path) as db:
        # Get driver's DB id
        async with db.execute("SELECT id FROM drivers WHERE tg_user_id = ? AND status = 'approved'", (driver_tg_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return
        driver_db_id = row[0]
        await db.execute(
            "UPDATE payments SET commission_paid = 1, commission_paid_at = ? WHERE driver_id = ? AND commission_paid = 0",
            (now.isoformat(), driver_db_id),
        )
        await db.commit()


async def get_driver_earnings_today(db_path: str, driver_tg_id: int) -> Tuple[float, float]:
    """Returns (total_earned, total_commission_owed) for today"""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT id FROM drivers WHERE tg_user_id = ? AND status = 'approved'", (driver_tg_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return (0.0, 0.0)
        driver_db_id = row[0]
        today = datetime.now(timezone.utc).date().isoformat()
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


async def get_driver_unpaid_commission(db_path: str, driver_tg_id: int) -> float:
    async with aiosqlite.connect(db_path) as db:
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
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, user_id, name, phone, pickup_address, destination_address, comment, created_at,
                   pickup_lat, pickup_lon, dest_lat, dest_lon,
                   driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id
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
                created_at=datetime.fromisoformat(row[7]),
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
                started_at=(datetime.fromisoformat(row[18]) if row[18] else None),
                finished_at=(datetime.fromisoformat(row[19]) if row[19] else None),
                group_message_id=row[20],
            )
        )
    return orders


async def get_driver_order_history(db_path: str, driver_tg_id: int, limit: int = 10) -> List[Order]:
    async with aiosqlite.connect(db_path) as db:
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
                   driver_id, distance_m, duration_s, fare_amount, commission, status, started_at, finished_at, group_message_id
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
                created_at=datetime.fromisoformat(row[7]),
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
                started_at=(datetime.fromisoformat(row[18]) if row[18] else None),
                finished_at=(datetime.fromisoformat(row[19]) if row[19] else None),
                group_message_id=row[20],
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
    
    # Users
    if not await has_column('users', 'city'):
        await db.execute("ALTER TABLE users ADD COLUMN city TEXT")


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
