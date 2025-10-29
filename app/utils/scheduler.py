from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot


async def commission_reminder_task(bot: Bot, db_path: str) -> None:
    """
    Background task that sends daily commission reminders at 20:00
    
    Нагадує водіям про несплачену комісію щодня о 20:00.
    Картка адміна береться з БД (app_settings) - налаштовується в кабінеті адміна.
    """
    from app.storage.db_connection import db_manager
    import logging
    logger = logging.getLogger(__name__)
    
    while True:
        now = datetime.now(timezone.utc)
        
        # Check if it's 20:00 (8 PM)
        target_time = time(20, 0)  # 20:00
        
        if now.hour == target_time.hour and now.minute == target_time.minute:
            # Send reminders to all drivers with unpaid commission
            try:
                # ⭐ Отримати картку адміна з БД (налаштування в кабінеті адміна)
                admin_payment_card = "Не вказано"
                try:
                    async with db_manager.connect(db_path) as db:
                        row = await db.fetchone("SELECT value FROM app_settings WHERE key = 'admin_payment_card'")
                        if row:
                            admin_payment_card = row[0]
                            logger.info(f"💳 Картка адміна для нагадувань: {admin_payment_card}")
                        else:
                            logger.warning("⚠️ Картка адміна не налаштована в БД! Використовую 'Не вказано'")
                except Exception as e:
                    logger.error(f"❌ Помилка отримання картки адміна: {e}")
                
                # Отримати список водіїв
                async with db_manager.connect(db_path) as db:
                    # Get all approved drivers
                    async with db.execute(
                        "SELECT DISTINCT tg_user_id FROM drivers WHERE status = 'approved'"
                    ) as cur:
                        driver_ids = [row[0] for row in await cur.fetchall()]
                
                logger.info(f"📢 Відправка нагадувань про комісію {len(driver_ids)} водіям...")
                
                sent_count = 0
                for driver_id in driver_ids:
                    try:
                        from app.storage.db import get_driver_unpaid_commission
                        
                        unpaid = await get_driver_unpaid_commission(db_path, driver_id)
                        
                        if unpaid > 0:
                            await bot.send_message(
                                driver_id,
                                f"⏰ <b>Нагадування</b>\n\n"
                                f"💰 У вас є несплачена комісія: {unpaid:.2f} грн\n\n"
                                f"📌 <b>Перерахуйте комісію на банківський рахунок:</b>\n"
                                f"<code>{admin_payment_card}</code>\n\n"
                                f"Після переказу використайте команду /driver → 💳 Комісія → '✅ Я сплатив комісію'"
                            )
                            sent_count += 1
                            logger.info(f"✅ Нагадування відправлено водію {driver_id}: {unpaid:.2f} грн")
                    except Exception as e:
                        # Ignore errors for individual drivers
                        logger.error(f"❌ Помилка відправки нагадування водію {driver_id}: {e}")
                        pass
                
                logger.info(f"📊 Відправлено нагадувань: {sent_count} з {len(driver_ids)} водіїв")
                
            except Exception as e:
                logger.error(f"❌ Помилка в task нагадувань про комісію: {e}")
            
            # Sleep for 1 minute to avoid sending multiple times in the same minute
            await asyncio.sleep(60)
        else:
            # Check every minute
            await asyncio.sleep(60)


async def start_scheduler(bot: Bot, db_path: str) -> None:
    """
    Start all scheduled tasks
    
    Аргументи:
        bot: Bot instance
        db_path: Шлях до бази даних
        
    ⚠️ payment_card більше не потрібен - картка береться з БД!
    """
    # Start commission reminder task (картка береться з БД автоматично)
    asyncio.create_task(commission_reminder_task(bot, db_path))
    
    # ❌ ВИМКНЕНО: Location tracking task (перевірка геолокації кожні 5 хв)
    # Водій ділиться геолокацією ТІЛЬКИ під час виконання замовлення
    # from app.utils.location_tracker import location_reminder_task
    # asyncio.create_task(location_reminder_task(bot, db_path))
