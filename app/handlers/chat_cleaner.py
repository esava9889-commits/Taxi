"""Обробник очищення чату - кнопка 🪄"""
from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.types import Message

from app.config.config import AppConfig
from app.storage.db import get_user_by_id, get_driver_by_tg_user_id
from app.handlers.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="chat_cleaner")

    @router.message(F.text == "🪄")
    async def clean_chat(message: Message) -> None:
        """Очистити чат - видалити 5 останніх повідомлень"""
        if not message.from_user:
            return
        
        try:
            # Видалити саме повідомлення з 🪄
            current_msg_id = message.message_id
            deleted_count = 0
            
            # Видалити 5 повідомлень (включаючи поточне)
            for i in range(5):
                try:
                    await message.bot.delete_message(
                        chat_id=message.from_user.id,
                        message_id=current_msg_id - i
                    )
                    deleted_count += 1
                except Exception as e:
                    # Ігноруємо помилки (повідомлення може бути вже видалене або недоступне)
                    logger.debug(f"Не вдалося видалити повідомлення {current_msg_id - i}: {e}")
                    pass
            
            logger.info(f"🪄 Користувач {message.from_user.id} очистив {deleted_count} повідомлень")
            
        except Exception as e:
            logger.error(f"❌ Помилка очищення чату для {message.from_user.id}: {e}")
        
        # ⭐ ПОВЕРНУТИ КЛАВІАТУРУ: Після очищення чату показати головне меню
        try:
            user = await get_user_by_id(config.database_path, message.from_user.id)
            driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
            
            is_driver = driver is not None and driver.status == "approved"
            is_admin = user and message.from_user.id in config.bot.admin_ids if user else False
            is_blocked = user.is_blocked if user else False
            
            kb = main_menu_keyboard(
                is_driver=is_driver,
                is_admin=is_admin,
                is_blocked=is_blocked
            )
            
            await message.answer(
                "🪄 <b>Чат очищено!</b>",
                reply_markup=kb
            )
        except Exception as e:
            logger.error(f"❌ Помилка відправки клавіатури: {e}")

    return router
