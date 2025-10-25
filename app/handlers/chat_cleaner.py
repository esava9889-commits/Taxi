"""Обробник очищення чату - кнопка 🪄"""
from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.types import Message

from app.config.config import AppConfig

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

    return router
