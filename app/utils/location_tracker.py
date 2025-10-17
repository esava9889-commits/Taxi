"""Система відстеження геолокації водіїв"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)


async def location_reminder_task(bot, db_path: str) -> None:
    """
    Фонове завдання для нагадування водіям про оновлення геолокації.
    
    Кожні 5 хвилин перевіряє онлайн водіїв:
    - Якщо локація старіша за 10 хвилин - надіслати нагадування
    - Якщо локація старіша за 20 хвилин - перевести водія в офлайн
    """
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
    import aiosqlite
    
    while True:
        try:
            # Чекати 5 хвилин між перевірками
            await asyncio.sleep(300)  # 300 секунд = 5 хвилин
            
            logger.info("🔄 Перевірка геолокацій онлайн водіїв...")
            
            now = datetime.now(timezone.utc)
            
            async with aiosqlite.connect(db_path) as db:
                # Отримати всіх онлайн водіїв
                async with db.execute(
                    """
                    SELECT id, tg_user_id, full_name, last_seen_at, last_lat, last_lon
                    FROM drivers
                    WHERE status = 'approved' AND online = 1
                    """
                ) as cur:
                    drivers = await cur.fetchall()
            
            for driver_id, tg_user_id, full_name, last_seen_str, last_lat, last_lon in drivers:
                try:
                    # Якщо локація взагалі не встановлена
                    if not last_seen_str or not last_lat or not last_lon:
                        kb = ReplyKeyboardMarkup(
                            keyboard=[
                                [KeyboardButton(text="📍 Поділитися локацією", request_location=True)],
                                [KeyboardButton(text="🚗 Панель водія")]
                            ],
                            resize_keyboard=True
                        )
                        
                        await bot.send_message(
                            tg_user_id,
                            "📍 <b>Встановіть вашу локацію</b>\n\n"
                            "Щоб отримувати замовлення поряд,\n"
                            "поділіться вашою геолокацією.\n\n"
                            "Натисніть кнопку нижче 👇",
                            reply_markup=kb
                        )
                        logger.info(f"📨 Нагадування про локацію надіслано водієві {full_name}")
                        continue
                    
                    # Перевірити чи не застаріла локація
                    last_seen = datetime.fromisoformat(last_seen_str)
                    time_diff = (now - last_seen).total_seconds() / 60  # в хвилинах
                    
                    # Якщо локація старіша за 20 хвилин - перевести в офлайн
                    if time_diff > 20:
                        from app.storage.db import set_driver_online
                        await set_driver_online(db_path, tg_user_id, False)
                        
                        await bot.send_message(
                            tg_user_id,
                            "🔴 <b>Ви переведені в офлайн</b>\n\n"
                            "Ваша геолокація не оновлювалась більше 20 хвилин.\n\n"
                            "Для отримання замовлень:\n"
                            "1. Поділіться локацією 📍\n"
                            "2. Натисніть '🚀 Почати роботу'\n"
                            "3. Перейдіть в онлайн 🟢"
                        )
                        logger.warning(f"🔴 Водій {full_name} переведений в офлайн (застаріла локація)")
                    
                    # Якщо локація старіша за 10 хвилин - надіслати нагадування
                    elif time_diff > 10:
                        kb = ReplyKeyboardMarkup(
                            keyboard=[
                                [KeyboardButton(text="📍 Оновити локацію", request_location=True)],
                                [KeyboardButton(text="🚗 Панель водія")]
                            ],
                            resize_keyboard=True
                        )
                        
                        await bot.send_message(
                            tg_user_id,
                            f"⚠️ <b>Оновіть вашу локацію</b>\n\n"
                            f"Ваша геолокація не оновлювалась {int(time_diff)} хв.\n\n"
                            f"Для отримання замовлень поряд,\n"
                            f"оновіть локацію 👇",
                            reply_markup=kb
                        )
                        logger.info(f"📨 Нагадування оновити локацію надіслано водієві {full_name}")
                
                except Exception as e:
                    logger.error(f"❌ Помилка при обробці водія {tg_user_id}: {e}")
                    continue
            
            logger.info(f"✅ Перевірка завершена. Оброблено {len(drivers)} водіїв")
        
        except Exception as e:
            logger.error(f"❌ Помилка в location_reminder_task: {e}")
            await asyncio.sleep(60)  # Почекати хвилину перед повторною спробою


async def check_driver_location_status(db_path: str, tg_user_id: int) -> dict:
    """
    Перевірити статус геолокації водія.
    
    Returns:
        dict: {
            'has_location': bool,
            'age_minutes': int,
            'status': 'fresh' | 'warning' | 'stale' | 'none'
        }
    """
    import aiosqlite
    
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT last_seen_at, last_lat, last_lon FROM drivers WHERE tg_user_id = ?",
            (tg_user_id,)
        ) as cur:
            row = await cur.fetchone()
    
    if not row:
        return {'has_location': False, 'age_minutes': 0, 'status': 'none'}
    
    last_seen_str, last_lat, last_lon = row
    
    if not last_seen_str or not last_lat or not last_lon:
        return {'has_location': False, 'age_minutes': 0, 'status': 'none'}
    
    last_seen = datetime.fromisoformat(last_seen_str)
    now = datetime.now(timezone.utc)
    age_minutes = int((now - last_seen).total_seconds() / 60)
    
    if age_minutes < 10:
        status = 'fresh'  # Свіжа локація
    elif age_minutes < 20:
        status = 'warning'  # Потребує оновлення
    else:
        status = 'stale'  # Застаріла
    
    return {
        'has_location': True,
        'age_minutes': age_minutes,
        'status': status
    }
