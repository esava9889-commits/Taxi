"""Рейтинг клієнтів (водії оцінюють клієнтів)"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.config.config import AppConfig
from app.storage.db import (
    get_order_by_id,
    get_driver_by_tg_user_id,
    insert_client_rating,
    get_client_average_rating,
    ClientRating,
)

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="client_rating")

    @router.callback_query(F.data.startswith("rate:client:"))
    async def show_client_rating_options(call: CallbackQuery) -> None:
        """Показати опції оцінки клієнта"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":", 2)[2])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        # Перевірка що це водій цього замовлення
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.id != order.driver_id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        await call.answer()
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="⭐️ 5 - Чудово", callback_data=f"rate_client:{order.user_id}:5:{order_id}"),
                ],
                [
                    InlineKeyboardButton(text="⭐️ 4 - Добре", callback_data=f"rate_client:{order.user_id}:4:{order_id}"),
                ],
                [
                    InlineKeyboardButton(text="⭐️ 3 - Нормально", callback_data=f"rate_client:{order.user_id}:3:{order_id}"),
                ],
                [
                    InlineKeyboardButton(text="⭐️ 2 - Погано", callback_data=f"rate_client:{order.user_id}:2:{order_id}"),
                ],
                [
                    InlineKeyboardButton(text="⭐️ 1 - Жахливо", callback_data=f"rate_client:{order.user_id}:1:{order_id}"),
                ]
            ]
        )
        
        await call.message.answer(
            "⭐️ <b>Оцініть клієнта</b>\n\n"
            f"👤 {order.name}\n\n"
            "Врахуйте:\n"
            "• Ввічливість та поведінку\n"
            "• Пунктуальність (чи не змусив чекати)\n"
            "• Чистоту (чи не забруднив авто)\n"
            "• Адекватність маршруту",
            reply_markup=kb
        )

    @router.callback_query(F.data.startswith("rate_client:"))
    async def rate_client(call: CallbackQuery) -> None:
        """Оцінити клієнта"""
        if not call.from_user:
            return
        
        parts = call.data.split(":")
        client_id = int(parts[1])
        rating_value = int(parts[2])
        order_id = int(parts[3])
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        # Зберегти оцінку
        client_rating = ClientRating(
            id=None,
            order_id=order_id,
            client_id=client_id,
            driver_id=driver.id,
            rating=rating_value,
            created_at=datetime.now(timezone.utc)
        )
        
        await insert_client_rating(config.database_path, client_rating)
        
        # Отримати новий середній рейтинг
        avg_rating = await get_client_average_rating(config.database_path, client_id)
        
        stars = "⭐️" * rating_value
        await call.answer(f"✅ Оцінка {stars} збережена!", show_alert=True)
        
        # Повідомлення для водія
        rating_text = {
            5: "Чудовий клієнт! 🌟",
            4: "Хороший клієнт ✨",
            3: "Нормальний клієнт 👌",
            2: "Проблемний клієнт ⚠️",
            1: "Поганий клієнт ❌"
        }
        
        await call.message.edit_text(
            f"✅ <b>Дякуємо за оцінку!</b>\n\n"
            f"Ви оцінили клієнта: {stars}\n"
            f"{rating_text.get(rating_value, '')}\n\n"
            f"📊 Середній рейтинг клієнта: {avg_rating:.1f} ⭐️" if avg_rating else ""
        )
        
        # Попередження клієнта якщо рейтинг низький
        if avg_rating and avg_rating < 3.0:
            try:
                await call.bot.send_message(
                    client_id,
                    "⚠️ <b>Увага!</b>\n\n"
                    f"Ваш рейтинг як пасажира: {avg_rating:.1f} ⭐️\n\n"
                    "Низький рейтинг може призвести до:\n"
                    "• Водії можуть відхиляти ваші замовлення\n"
                    "• Довше очікування таксі\n\n"
                    "💡 Покращіть рейтинг:\n"
                    "• Будьте ввічливі з водіями\n"
                    "• Приходьте вчасно\n"
                    "• Підтримуйте чистоту в авто"
                )
            except Exception as e:
                logger.error(f"Failed to notify client about low rating: {e}")

    return router
