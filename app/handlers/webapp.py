"""
Обробник для Telegram WebApp - інтерактивна карта

Цей модуль дозволяє користувачам вибирати місце на інтерактивній карті
замість надсилання геолокації або введення адреси текстом.

Використання:
    1. Деплой index.html на GitHub Pages / Netlify
    2. Встановити WEBAPP_URL в .env
    3. Бот автоматично додасть кнопку "🗺 Обрати на карті"
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from app.config.config import AppConfig
from app.utils.maps import reverse_geocode

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="webapp")
    
    # URL вашої WebApp (змініть після деплою на GitHub Pages)
    # Наприклад: https://ваш-логін.github.io/taxi-map/
    WEBAPP_URL = config.webapp_url if hasattr(config, 'webapp_url') else "https://yourusername.github.io/taxi-map/"
    
    @router.message(F.web_app_data)
    async def handle_webapp_data(message: Message, state: FSMContext) -> None:
        """
        Обробник даних з WebApp (карти)
        """
        if not message.web_app_data:
            return
        
        try:
            # Парсинг даних з WebApp
            data = json.loads(message.web_app_data.data)
            
            if data.get('type') == 'location':
                latitude = data.get('latitude')
                longitude = data.get('longitude')
                
                if not latitude or not longitude:
                    await message.answer("❌ Помилка: не вдалося отримати координати")
                    return
                
                # Отримати адресу з координат (reverse geocoding)
                address = await reverse_geocode(latitude, longitude)
                
                if not address:
                    address = f"Координати: {latitude:.6f}, {longitude:.6f}"
                
                # Зберегти в state залежно від поточного стану
                current_state = await state.get_state()
                
                # Перевірити в якому стані користувач (pickup або destination)
                state_data = await state.get_data()
                
                if current_state == "OrderStates:pickup" or state_data.get('waiting_for') == 'pickup':
                    # Зберегти адресу подачі
                    await state.update_data(
                        pickup_address=address,
                        pickup_lat=latitude,
                        pickup_lng=longitude,
                    )
                    
                    await message.answer(
                        f"✅ <b>Адреса подачі:</b>\n📍 {address}\n\n"
                        f"Тепер вкажіть <b>куди</b> їхати 👇",
                    )
                    
                    # Перейти до наступного кроку
                    from app.handlers.order import OrderStates
                    await state.set_state(OrderStates.destination)
                    
                elif current_state == "OrderStates:destination" or state_data.get('waiting_for') == 'destination':
                    # Зберегти адресу призначення
                    await state.update_data(
                        dest_address=address,
                        dest_lat=latitude,
                        dest_lng=longitude,
                    )
                    
                    await message.answer(
                        f"✅ <b>Адреса призначення:</b>\n📍 {address}\n\n"
                        f"⏳ Розраховую вартість поїздки...",
                    )
                    
                    # Продовжити процес створення замовлення
                    # Викликаємо логіку з order.py
                    data = await state.get_data()
                    
                    # Імпортуємо функцію обробки після вибору адреси
                    from app.handlers.order import process_order_calculation
                    await process_order_calculation(message, state, config)
                else:
                    # Невідомий стан
                    await message.answer(
                        f"📍 <b>Обрана адреса:</b>\n{address}\n\n"
                        f"Координати: {latitude:.6f}, {longitude:.6f}"
                    )
                
                logger.info(
                    f"WebApp location received: {latitude}, {longitude} -> {address}"
                )
                
        except json.JSONDecodeError:
            logger.error(f"Failed to parse WebApp data: {message.web_app_data.data}")
            await message.answer("❌ Помилка обробки даних з карти")
        except Exception as e:
            logger.error(f"Error handling WebApp data: {e}")
            await message.answer("❌ Виникла помилка. Спробуйте ще раз.")
    
    return router


def create_map_keyboard(webapp_url: str, button_text: str = "🗺 Обрати на карті") -> InlineKeyboardMarkup:
    """
    Створює INLINE клавіатуру з кнопкою для відкриття карти
    
    Args:
        webapp_url: URL WebApp з картою
        button_text: Текст кнопки
    
    Returns:
        InlineKeyboardMarkup з кнопкою WebApp
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button_text,
                    web_app=WebAppInfo(url=webapp_url)
                )
            ]
        ]
    )


def create_location_keyboard_with_map(webapp_url: Optional[str] = None) -> ReplyKeyboardMarkup:
    """
    Створює клавіатуру з геолокацією та (опціонально) картою
    
    Args:
        webapp_url: URL WebApp з картою (якщо None - кнопка карти не додається)
    
    Returns:
        ReplyKeyboardMarkup
    """
    buttons = [
        [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
    ]
    
    # Додати кнопку карти, якщо URL налаштовано
    if webapp_url:
        buttons.append([
            KeyboardButton(
                text="🗺 Обрати на карті",
                web_app=WebAppInfo(url=webapp_url)
            )
        ])
    
    buttons.extend([
        [KeyboardButton(text="🎤 Голосом")],
        [KeyboardButton(text="❌ Скасувати")],
    ])
    
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=False,
    )
