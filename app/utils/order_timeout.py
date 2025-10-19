"""Система таймаутів для замовлень - автоматична перепропозиція та підвищення ціни"""
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


class OrderTimeoutManager:
    """
    Менеджер таймаутів для замовлень.
    
    Коли замовлення створено і надіслано в групу водіїв:
    - Запускається таймер на 3 хвилини
    - Якщо жоден водій не прийняв за цей час - замовлення перепропонується
    - Повідомлення в групі оновлюється з позначкою "🔴 ТЕРМІНОВЕ"
    - Клієнту надсилається повідомлення про затримку
    """
    
    def __init__(self):
        self._timers: Dict[int, asyncio.Task] = {}  # {order_id: task}
        self._timeout_seconds = 180  # 3 хвилини
        self._timeout_count: Dict[int, int] = {}  # {order_id: скільки разів спрацював таймер}
    
    async def start_timeout(
        self,
        bot: Bot,
        order_id: int,
        db_path: str,
        group_chat_id: int,
        group_message_id: Optional[int] = None
    ) -> None:
        """
        Запустити таймер для замовлення.
        
        Args:
            bot: Екземпляр бота
            order_id: ID замовлення
            db_path: Шлях до БД
            group_chat_id: ID групи водіїв
            group_message_id: ID повідомлення в групі
        """
        # Якщо таймер вже існує - скасувати його
        if order_id in self._timers:
            self._timers[order_id].cancel()
        
        # Створити новий таймер
        task = asyncio.create_task(
            self._timeout_handler(
                bot, order_id, db_path, group_chat_id, group_message_id
            )
        )
        self._timers[order_id] = task
        
        logger.info(f"⏱️ Таймер запущено для замовлення #{order_id} (3 хв)")
    
    def cancel_timeout(self, order_id: int) -> None:
        """
        Скасувати таймер (коли замовлення прийнято).
        
        Args:
            order_id: ID замовлення
        """
        if order_id in self._timers:
            self._timers[order_id].cancel()
            del self._timers[order_id]
            logger.info(f"✅ Таймер скасовано для замовлення #{order_id}")
        
        # Видалити лічильник
        if order_id in self._timeout_count:
            del self._timeout_count[order_id]
    
    async def _timeout_handler(
        self,
        bot: Bot,
        order_id: int,
        db_path: str,
        group_chat_id: int,
        group_message_id: Optional[int]
    ) -> None:
        """
        Обробник таймауту.
        
        Викликається автоматично через 3 хвилини якщо замовлення не прийнято.
        """
        try:
            # Чекати 3 хвилини
            await asyncio.sleep(self._timeout_seconds)
            
            # Перевірити статус замовлення
            from app.storage.db import get_order_by_id
            order = await get_order_by_id(db_path, order_id)
            
            if not order:
                logger.warning(f"⚠️ Замовлення #{order_id} не знайдено")
                return
            
            # Якщо замовлення вже прийнято - нічого не робити
            if order.status != "pending":
                logger.info(f"✅ Замовлення #{order_id} вже прийнято, таймаут скасовано")
                return
            
            # Підрахувати скільки разів спрацював таймер
            if order_id not in self._timeout_count:
                self._timeout_count[order_id] = 0
            self._timeout_count[order_id] += 1
            
            timeout_count = self._timeout_count[order_id]
            logger.warning(f"⏰ TIMEOUT #{timeout_count}: Замовлення #{order_id} не прийнято за {timeout_count * 3} хв!")
            
            # ⭐ НОВА ЛОГІКА: Пропозиція підняти ціну клієнту
            try:
                # Безпечне форматування суми
                current_fare = order.fare_amount if order.fare_amount else 100.0
                
                # Inline кнопки для підвищення ціни
                kb_price_increase = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="💵 +15 грн", callback_data=f"increase_price:{order_id}:15"),
                            InlineKeyboardButton(text="💵 +30 грн", callback_data=f"increase_price:{order_id}:30"),
                        ],
                        [InlineKeyboardButton(text="💵 +50 грн", callback_data=f"increase_price:{order_id}:50")],
                        [InlineKeyboardButton(text="❌ Скасувати замовлення", callback_data=f"cancel_waiting_order:{order_id}")]
                    ]
                )
                
                await bot.send_message(
                    order.user_id,
                    f"⏰ <b>Шукаємо водія вже {timeout_count * 3} хвилин...</b>\n\n"
                    f"На жаль, всі водії зараз зайняті.\n\n"
                    f"💰 <b>Поточна ціна:</b> {current_fare:.0f} грн\n\n"
                    f"💡 <b>Підвищте ціну щоб швидше знайти водія:</b>\n\n"
                    f"Водії частіше приймають замовлення з вищою ціною.",
                    reply_markup=kb_price_increase
                )
                logger.info(f"📨 Клієнту #{order.user_id} запропоновано підняти ціну (спроба #{timeout_count})")
            except Exception as e:
                logger.error(f"❌ Не вдалося запропонувати підняти ціну: {e}")
            
            # Оновити повідомлення в групі з позначкою "ТЕРМІНОВЕ"
            if group_message_id:
                try:
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(
                                text="✅ Прийняти замовлення",
                                callback_data=f"accept_order:{order_id}"
                            )]
                        ]
                    )
                    
                    # Безпечне форматування суми
                    fare_text = f"{order.fare_amount:.0f} грн" if order.fare_amount else "Уточнюється"
                    
                    await bot.edit_message_text(
                        chat_id=group_chat_id,
                        message_id=group_message_id,
                        text=(
                            f"🔴 <b>ТЕРМІНОВЕ ЗАМОВЛЕННЯ #{order_id}</b>\n"
                            f"⚠️ <b>Вже чекає {timeout_count * 3}+ хвилин!</b>\n\n"
                            f"📍 Звідки: {order.pickup_address or 'Не вказано'}\n"
                            f"📍 Куди: {order.destination_address or 'Не вказано'}\n\n"
                            f"💰 Вартість: {fare_text}\n\n"
                            f"❗️ <i>Клієнт очікує! Візьміть замовлення ЗАРАЗ!</i>"
                        ),
                        reply_markup=kb
                    )
                    logger.info(f"📤 Повідомлення в групі оновлено: ТЕРМІНОВЕ #{order_id} ({timeout_count * 3} хв)")
                except Exception as e:
                    if "message is not modified" not in str(e):
                        logger.error(f"❌ Не вдалося оновити повідомлення в групі: {e}")
            
            # Перезапустити таймер на ще 3 хвилини
            await self.start_timeout(
                bot, order_id, db_path, group_chat_id, group_message_id
            )
            
            # Якщо замовлення чекає більше 6 хвилин - повідомити адміна
            # (можна додати логіку в майбутньому)
            
        except asyncio.CancelledError:
            # Таймер скасовано (замовлення прийнято)
            logger.info(f"🛑 Таймер скасовано для замовлення #{order_id}")
        except Exception as e:
            logger.error(f"❌ Помилка в timeout handler для #{order_id}: {e}")
        finally:
            # Видалити таймер зі списку
            if order_id in self._timers:
                del self._timers[order_id]


# Глобальний екземпляр менеджера таймаутів
_timeout_manager = OrderTimeoutManager()


async def start_order_timeout(
    bot: Bot,
    order_id: int,
    db_path: str,
    group_chat_id: int,
    group_message_id: Optional[int] = None
) -> None:
    """
    Запустити таймер для замовлення.
    
    Викликати одразу після відправки замовлення в групу водіїв.
    """
    await _timeout_manager.start_timeout(
        bot, order_id, db_path, group_chat_id, group_message_id
    )


def cancel_order_timeout(order_id: int) -> None:
    """
    Скасувати таймер (коли водій прийняв замовлення).
    
    Викликати одразу після accept_order.
    """
    _timeout_manager.cancel_timeout(order_id)
