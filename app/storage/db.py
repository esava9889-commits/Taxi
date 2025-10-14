from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
