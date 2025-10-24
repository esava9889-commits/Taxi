from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router

logger = logging.getLogger(__name__)
from aiogram.types import CallbackQuery
from aiogram.filters import Command
from aiogram.types import Message

from app.config.config import AppConfig
from app.storage.db import (
    Rating,
    insert_rating,
    get_driver_average_rating,
    get_order_by_id,
)


def create_router(config: AppConfig) -> Router:
    router = Router(name="ratings")

    @router.callback_query(F.data.startswith("rate:skip:"))
    async def skip_rating(call: CallbackQuery) -> None:
        """Пропустити оцінювання"""
        if not call.from_user:
            return
        
        await call.answer("Дякуємо за поїздку! 🚖", show_alert=False)
        
        # ⭐ ОЧИСТИТИ ЧАТ: Видалити всі повідомлення за період замовлення
        try:
            # Видалити останні 50 повідомлень (весь період замовлення)
            if call.message:
                current_msg_id = call.message.message_id
                deleted_count = 0
                
                for i in range(50):
                    try:
                        await call.bot.delete_message(
                            chat_id=call.from_user.id,
                            message_id=current_msg_id - i
                        )
                        deleted_count += 1
                    except:
                        pass  # Ігноруємо помилки (повідомлення може бути вже видалене)
                
                logger.info(f"🧹 Очищено {deleted_count} повідомлень для клієнта {call.from_user.id} після пропуску оцінки")
        except Exception as e:
            logger.error(f"❌ Помилка очищення чату: {e}")
    
    @router.callback_query(F.data.startswith("rate:"))
    async def handle_rating(call: CallbackQuery) -> None:
        if not call.from_user:
            return
        
        parts = (call.data or "").split(":")
        if len(parts) < 5:
            await call.answer("❌ Невірний формат", show_alert=True)
            return
        
        # Format: rate:driver:<driver_tg_id>:<rating>:<order_id>
        target_type = parts[1]  # driver or client
        target_user_id = int(parts[2])
        rating_value = int(parts[3])
        order_id = int(parts[4])
        
        if not (1 <= rating_value <= 5):
            await call.answer("❌ Оцінка має бути від 1 до 5", show_alert=True)
            return
        
        # Verify order exists
        order = await get_order_by_id(config.database_path, order_id)
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        # Create rating
        rating = Rating(
            id=None,
            order_id=order_id,
            from_user_id=call.from_user.id,
            to_user_id=target_user_id,
            rating=rating_value,
            comment=None,
            created_at=datetime.now(timezone.utc)
        )
        
        await insert_rating(config.database_path, rating)
        
        stars = "⭐" * rating_value
        await call.answer(f"✅ Дякуємо за оцінку! {stars}", show_alert=True)
        
        # ⭐ ОЧИСТИТИ ЧАТ: Видалити всі повідомлення за період замовлення
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            if call.message:
                current_msg_id = call.message.message_id
                deleted_count = 0
                
                # Видалити останні 50 повідомлень (весь період замовлення)
                for i in range(50):
                    try:
                        await call.bot.delete_message(
                            chat_id=call.from_user.id,
                            message_id=current_msg_id - i
                        )
                        deleted_count += 1
                    except:
                        pass  # Ігноруємо помилки
                
                logger.info(f"🧹 Очищено {deleted_count} повідомлень для клієнта {call.from_user.id} після оцінки {rating_value}⭐")
        except Exception as e:
            logger.error(f"❌ Помилка очищення чату: {e}")
        
        # Notify rated user about their new average rating
        try:
            avg_rating = await get_driver_average_rating(config.database_path, target_user_id)
            if avg_rating:
                await call.bot.send_message(
                    target_user_id,
                    f"⭐️ Ви отримали нову оцінку: {rating_value}/5\n"
                    f"Ваш середній рейтинг: {avg_rating:.1f}/5"
                )
        except Exception:
            pass

    @router.message(Command("my_rating"))
    async def show_my_rating(message: Message) -> None:
        if not message.from_user:
            return
        
        avg_rating = await get_driver_average_rating(config.database_path, message.from_user.id)
        
        if avg_rating is None:
            await message.answer("⭐️ У вас поки немає оцінок.")
            return
        
        stars = "⭐️" * int(round(avg_rating))
        await message.answer(
            f"⭐️ <b>Ваш рейтинг</b>\n\n"
            f"{stars}\n"
            f"Середня оцінка: {avg_rating:.2f}/5"
        )

    return router
