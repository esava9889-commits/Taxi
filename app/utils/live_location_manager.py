"""
Менеджер Live Location для відстеження водіїв
Автоматично оновлює геопозицію водія для клієнта
"""
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class LiveLocationManager:
    """Глобальний менеджер для відстеження активних live locations"""
    
    # Словник: order_id -> {"message_id": int, "user_id": int, "driver_id": int, "task": asyncio.Task}
    active_locations: Dict[int, dict] = {}
    
    @classmethod
    async def start_tracking(
        cls,
        bot,
        order_id: int,
        user_id: int,
        driver_id: int,
        message_id: int,
        db_path: str
    ) -> None:
        """
        Почати відстеження водія для замовлення
        
        Args:
            bot: Telegram bot instance
            order_id: ID замовлення
            user_id: Telegram ID клієнта
            driver_id: DB ID водія
            message_id: ID повідомлення з live location
            db_path: Шлях до БД
        """
        # Зупинити попереднє відстеження якщо є
        await cls.stop_tracking(order_id)
        
        # Створити фонову задачу
        task = asyncio.create_task(
            cls._update_location_loop(bot, order_id, user_id, driver_id, message_id, db_path)
        )
        
        cls.active_locations[order_id] = {
            "message_id": message_id,
            "user_id": user_id,
            "driver_id": driver_id,
            "task": task,
            "started_at": datetime.now(timezone.utc)
        }
        
        logger.info(f"📍 Live location tracking started for order #{order_id}, message_id={message_id}")
    
    @classmethod
    async def stop_tracking(cls, order_id: int) -> None:
        """Зупинити відстеження для замовлення"""
        if order_id not in cls.active_locations:
            logger.debug(f"📍 Order #{order_id} not in active locations, nothing to stop")
            return
        
        location_data = cls.active_locations[order_id]
        task = location_data.get("task")
        
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        del cls.active_locations[order_id]
        logger.info(f"📍 Live location tracking stopped for order #{order_id}")
    
    @classmethod
    async def _update_location_loop(
        cls,
        bot,
        order_id: int,
        user_id: int,
        driver_id: int,
        message_id: int,
        db_path: str
    ) -> None:
        """
        Фонова задача для оновлення локації кожні 20 секунд
        """
        from app.storage.db import get_driver_by_id, get_order_by_id
        
        try:
            update_count = 0
            max_updates = 45  # 45 оновлень × 20 сек = 15 хвилин
            
            while update_count < max_updates:
                await asyncio.sleep(20)  # Оновлювати кожні 20 секунд
                
                # Перевірити чи замовлення ще активне
                order = await get_order_by_id(db_path, order_id)
                if not order or order.status not in ["accepted", "in_progress"]:
                    logger.info(f"📍 Order #{order_id} is no longer active, stopping location updates")
                    break
                
                # Отримати поточну локацію водія
                driver = await get_driver_by_id(db_path, driver_id)
                if not driver or not driver.last_lat or not driver.last_lon:
                    logger.warning(f"⚠️ Driver {driver_id} has no location, skipping update")
                    continue
                
                # Оновити live location
                try:
                    await bot.edit_message_live_location(
                        chat_id=user_id,
                        message_id=message_id,
                        latitude=driver.last_lat,
                        longitude=driver.last_lon
                    )
                    update_count += 1
                    logger.debug(f"📍 Live location updated for order #{order_id} ({update_count}/{max_updates})")
                except Exception as e:
                    error_msg = str(e).lower()
                    if "message is not modified" in error_msg:
                        # Локація не змінилась - це нормально
                        pass
                    elif "message to edit not found" in error_msg:
                        # Клієнт видалив повідомлення
                        logger.warning(f"⚠️ Live location message deleted by client for order #{order_id}")
                        break
                    else:
                        logger.error(f"❌ Error updating live location for order #{order_id}: {e}")
            
            logger.info(f"📍 Live location tracking completed for order #{order_id} after {update_count} updates")
            
        except asyncio.CancelledError:
            logger.info(f"📍 Live location tracking cancelled for order #{order_id}")
            raise
        except Exception as e:
            logger.error(f"❌ Fatal error in live location loop for order #{order_id}: {e}", exc_info=True)
        finally:
            # Видалити з активних
            if order_id in cls.active_locations:
                del cls.active_locations[order_id]
    
    @classmethod
    def get_active_count(cls) -> int:
        """Отримати кількість активних відстежувань"""
        return len(cls.active_locations)
    
    @classmethod
    async def stop_all(cls) -> None:
        """Зупинити всі активні відстеження (для shutdown)"""
        order_ids = list(cls.active_locations.keys())
        for order_id in order_ids:
            await cls.stop_tracking(order_id)
        logger.info(f"📍 All live location tracking stopped ({len(order_ids)} orders)")
