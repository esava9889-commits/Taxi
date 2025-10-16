"""Система промокодів і знижок"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
import aiosqlite

from app.config.config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class Promocode:
    id: Optional[int]
    code: str
    discount_percent: float  # 0-100
    discount_amount: Optional[float]  # Фіксована знижка
    max_uses: int
    uses_count: int
    valid_until: Optional[datetime]
    created_at: datetime
    active: bool


async def create_promocode_table(db_path: str) -> None:
    """Створити таблицю промокодів"""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS promocodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                discount_percent REAL NOT NULL DEFAULT 0,
                discount_amount REAL,
                max_uses INTEGER NOT NULL DEFAULT 0,
                uses_count INTEGER NOT NULL DEFAULT 0,
                valid_until TEXT,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        
        # Таблиця використань промокодів
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS promocode_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promocode_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                order_id INTEGER,
                discount_amount REAL NOT NULL,
                used_at TEXT NOT NULL,
                FOREIGN KEY (promocode_id) REFERENCES promocodes(id)
            )
            """
        )
        await db.commit()


async def get_promocode(db_path: str, code: str) -> Optional[Promocode]:
    """Отримати промокод за кодом"""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, code, discount_percent, discount_amount, max_uses, uses_count, 
                   valid_until, created_at, active
            FROM promocodes
            WHERE code = ? AND active = 1
            """,
            (code.upper(),)
        ) as cur:
            row = await cur.fetchone()
    
    if not row:
        return None
    
    return Promocode(
        id=row[0],
        code=row[1],
        discount_percent=row[2],
        discount_amount=row[3],
        max_uses=row[4],
        uses_count=row[5],
        valid_until=datetime.fromisoformat(row[6]) if row[6] else None,
        created_at=datetime.fromisoformat(row[7]),
        active=bool(row[8])
    )


async def apply_promocode(db_path: str, code: str, user_id: int, fare: float) -> tuple[bool, float, str]:
    """
    Застосувати промокод
    
    Returns:
        (success, discounted_fare, message)
    """
    promo = await get_promocode(db_path, code)
    
    if not promo:
        return False, fare, "❌ Промокод не знайдено"
    
    # Перевірка термін дії
    if promo.valid_until and datetime.now(timezone.utc) > promo.valid_until:
        return False, fare, "❌ Промокод прострочений"
    
    # Перевірка кількість використань
    if promo.max_uses > 0 and promo.uses_count >= promo.max_uses:
        return False, fare, "❌ Промокод вичерпано"
    
    # Перевірка чи використовував цей користувач
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM promocode_uses WHERE promocode_id = ? AND user_id = ?",
            (promo.id, user_id)
        ) as cur:
            count = (await cur.fetchone())[0]
    
    if count > 0:
        return False, fare, "❌ Ви вже використовували цей промокод"
    
    # Розрахунок знижки
    if promo.discount_amount:
        # Фіксована знижка
        discount = min(promo.discount_amount, fare)
    else:
        # Відсоткова знижка
        discount = fare * (promo.discount_percent / 100.0)
    
    discounted_fare = max(0, fare - discount)
    
    return True, discounted_fare, f"✅ Знижка {discount:.2f} грн ({promo.discount_percent}%)"


async def use_promocode(db_path: str, promocode_id: int, user_id: int, order_id: int, discount_amount: float) -> None:
    """Записати використання промокоду"""
    async with aiosqlite.connect(db_path) as db:
        # Додати використання
        await db.execute(
            """
            INSERT INTO promocode_uses (promocode_id, user_id, order_id, discount_amount, used_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (promocode_id, user_id, order_id, discount_amount, datetime.now(timezone.utc).isoformat())
        )
        
        # Оновити лічильник
        await db.execute(
            "UPDATE promocodes SET uses_count = uses_count + 1 WHERE id = ?",
            (promocode_id,)
        )
        await db.commit()


def create_router(config: AppConfig) -> Router:
    router = Router(name="promocodes")

    @router.message(F.text.startswith("/promo "))
    async def check_promocode(message: Message, state: FSMContext) -> None:
        """Перевірити промокод"""
        if not message.from_user or not message.text:
            return
        
        # Створити таблицю якщо не існує
        await create_promocode_table(config.database_path)
        
        code = message.text.split(" ", 1)[1].strip().upper()
        
        # Отримати поточну вартість з state (якщо є)
        data = await state.get_data()
        fare = data.get("estimated_fare", 100.0)  # Тестова вартість
        
        success, new_fare, msg = await apply_promocode(config.database_path, code, message.from_user.id, fare)
        
        if success:
            await state.update_data(
                promocode=code,
                original_fare=fare,
                discounted_fare=new_fare
            )
        
        await message.answer(msg)

    return router
