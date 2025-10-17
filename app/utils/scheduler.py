from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot


async def commission_reminder_task(bot: Bot, db_path: str, payment_card: str) -> None:
    """
    Background task that sends daily commission reminders at 20:00
    """
    import aiosqlite
    
    while True:
        now = datetime.now(timezone.utc)
        
        # Check if it's 20:00 (8 PM)
        target_time = time(20, 0)  # 20:00
        
        if now.hour == target_time.hour and now.minute == target_time.minute:
            # Send reminders to all drivers with unpaid commission
            try:
                async with aiosqlite.connect(db_path) as db:
                    # Get all approved drivers
                    async with db.execute(
                        "SELECT DISTINCT tg_user_id FROM drivers WHERE status = 'approved'"
                    ) as cur:
                        driver_ids = [row[0] for row in await cur.fetchall()]
                
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
                                f"<code>{payment_card}</code>\n\n"
                                f"Після переказу використайте команду /driver → 💳 Комісія → '✅ Я сплатив комісію'"
                            )
                    except Exception:
                        # Ignore errors for individual drivers
                        pass
            except Exception as e:
                print(f"Error in commission reminder task: {e}")
            
            # Sleep for 1 minute to avoid sending multiple times in the same minute
            await asyncio.sleep(60)
        else:
            # Check every minute
            await asyncio.sleep(60)


async def start_scheduler(bot: Bot, db_path: str, payment_card: str = "4149 4999 0123 4567") -> None:
    """Start all scheduled tasks"""
    # Start commission reminder task
    asyncio.create_task(commission_reminder_task(bot, db_path, payment_card))
    
    # Start location tracking task (перевірка геолокації кожні 5 хв)
    from app.utils.location_tracker import location_reminder_task
    asyncio.create_task(location_reminder_task(bot, db_path))
