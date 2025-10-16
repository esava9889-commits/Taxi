"""Чайові для водіїв"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.config.config import AppConfig
from app.storage.db import get_order_by_id, add_tip_to_order, get_driver_by_id

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="tips")

    @router.callback_query(F.data.startswith("tip:show:"))
    async def show_tip_options(call: CallbackQuery) -> None:
        """Показати варіанти чайових"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":", 2)[2])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if order.status != "completed":
            await call.answer("❌ Можна залишити чайові тільки після завершення поїздки", show_alert=True)
            return
        
        # Перевірка чи вже залишені чайові
        if hasattr(order, 'tip_amount') and order.tip_amount and order.tip_amount > 0:
            await call.answer(f"✅ Ви вже залишили чайові {order.tip_amount:.0f} грн", show_alert=True)
            return
        
        await call.answer()
        
        # Варіанти чайових
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="💵 10 грн", callback_data=f"tip:add:{order_id}:10"),
                    InlineKeyboardButton(text="💵 20 грн", callback_data=f"tip:add:{order_id}:20"),
                ],
                [
                    InlineKeyboardButton(text="💵 50 грн", callback_data=f"tip:add:{order_id}:50"),
                    InlineKeyboardButton(text="💵 100 грн", callback_data=f"tip:add:{order_id}:100"),
                ],
                [InlineKeyboardButton(text="💰 Своя сума", callback_data=f"tip:custom:{order_id}")],
                [InlineKeyboardButton(text="❌ Без чайових", callback_data=f"tip:skip:{order_id}")]
            ]
        )
        
        await call.message.answer(
            "💝 <b>Залишити чайові водію?</b>\n\n"
            f"Вартість поїздки: {order.fare_amount:.2f} грн\n\n"
            "💡 <i>Чайові йдуть водію повністю (без комісії)</i>",
            reply_markup=kb
        )

    @router.callback_query(F.data.startswith("tip:add:"))
    async def add_tip(call: CallbackQuery) -> None:
        """Додати чайові"""
        if not call.from_user:
            return
        
        parts = call.data.split(":")
        order_id = int(parts[2])
        tip_amount = float(parts[3])
        
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        # Додати чайові
        success = await add_tip_to_order(config.database_path, order_id, tip_amount)
        
        if success:
            await call.answer(f"✅ Дякуємо! Чайові {tip_amount:.0f} грн додано", show_alert=True)
            
            # Повідомити водія
            if order.driver_id:
                driver = await get_driver_by_id(config.database_path, order.driver_id)
                if driver:
                    try:
                        await call.bot.send_message(
                            driver.tg_user_id,
                            f"💝 <b>Ви отримали чайові!</b>\n\n"
                            f"Замовлення #{order_id}\n"
                            f"💰 Сума: {tip_amount:.0f} грн\n\n"
                            f"Дякуємо за чудовий сервіс! ⭐️"
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify driver about tip: {e}")
            
            # Оновити повідомлення
            await call.message.edit_text(
                f"✅ <b>Дякуємо за чайові!</b>\n\n"
                f"💰 Сума: {tip_amount:.0f} грн\n"
                f"🚗 Водій отримав сповіщення"
            )
        else:
            await call.answer("❌ Помилка при додаванні чайових", show_alert=True)

    @router.callback_query(F.data.startswith("tip:skip:"))
    async def skip_tip(call: CallbackQuery) -> None:
        """Пропустити чайові"""
        await call.answer()
        await call.message.edit_text("👌 Добре, дякуємо за поїздку!")

    @router.callback_query(F.data.startswith("tip:custom:"))
    async def custom_tip(call: CallbackQuery) -> None:
        """Власна сума чайових"""
        # TODO: Реалізувати FSM для введення суми
        await call.answer(
            "💡 Напишіть суму чайових числом (наприклад: 30)\n"
            "Команда /cancel для скасування",
            show_alert=True
        )

    return router
