"""
Обробник для Telegram WebApp - інтерактивна карта

Цей модуль дозволяє користувачам вибирати місце на інтерактивній карті
замість надсилання геолокації або введення адреси текстом.
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
                address = await reverse_geocode("", latitude, longitude)
                
                if not address:
                    address = f"📍 Координати: {latitude:.6f}, {longitude:.6f}"
                
                # Зберегти в state залежно від поточного стану
                current_state = await state.get_state()
                state_data = await state.get_data()
                
                logger.info(f"📍 WebApp location: lat={latitude}, lng={longitude}, address={address}, state={current_state}, waiting_for={state_data.get('waiting_for')}")
                
                # Перевірити в якому стані користувач (pickup або destination)
                if current_state == "OrderStates:pickup" or state_data.get('waiting_for') == 'pickup':
                    # ===== PICKUP =====
                    # Зберегти адресу подачі (використовуємо ключі як в order.py!)
                    await state.update_data(
                        pickup=address,  # ← ключ як в order.py
                        pickup_lat=latitude,
                        pickup_lon=longitude,  # ← lon, не lng!
                    )
                    
                    logger.info(f"✅ WebApp pickup збережено: {address} ({latitude}, {longitude})")
                    
                    # Перейти до наступного кроку - destination
                    from app.handlers.order import OrderStates
                    await state.set_state(OrderStates.destination)
                    
                    # Показати інлайн кнопки для destination (як в order.py)
                    from app.storage.db import get_user_saved_addresses
                    saved_addresses = await get_user_saved_addresses(config.database_path, message.from_user.id)
                    
                    kb_buttons = [
                        [InlineKeyboardButton(text="📍 Надіслати геолокацію", callback_data="order:dest:send_location")],
                        [InlineKeyboardButton(text="✏️ Ввести адресу текстом", callback_data="order:dest:text")],
                    ]
                    
                    if saved_addresses:
                        kb_buttons.append([InlineKeyboardButton(text="📌 Вибрати зі збережених", callback_data="order:dest:saved")])
                    
                    kb_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="order:back:pickup")])
                    kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
                    
                    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
                    
                    await message.answer(
                        f"✅ <b>Місце подачі:</b>\n{address}\n\n"
                        "📍 <b>Куди їдемо?</b>\n\n"
                        "💡 Оберіть спосіб:",
                        reply_markup=kb
                    )
                    
                elif current_state == "OrderStates:destination" or state_data.get('waiting_for') == 'destination':
                    # ===== DESTINATION =====
                    # Зберегти адресу призначення (використовуємо ключі як в order.py!)
                    await state.update_data(
                        destination=address,  # ← ключ як в order.py
                        dest_lat=latitude,
                        dest_lon=longitude,  # ← lon, не lng!
                    )
                    
                    logger.info(f"✅ WebApp destination збережено: {address} ({latitude}, {longitude})")
                    
                    # Показати повідомлення про розрахунок
                    await message.answer(
                        f"✅ <b>Місце призначення:</b>\n📍 {address}\n\n"
                        f"⏳ Розраховую відстань та вартість поїздки...",
                    )
                    
                    # Отримати pickup з state
                    pickup_address = state_data.get('pickup', 'Не вказано')
                    
                    # Показати вибір класів авто (викликаємо функцію з order.py)
                    from app.handlers.order import show_car_class_selection_with_prices
                    await show_car_class_selection_with_prices(message, state)
                    
                else:
                    # Невідомий стан - просто показати адресу
                    await message.answer(
                        f"📍 <b>Обрана адреса:</b>\n{address}\n\n"
                        f"Координати: {latitude:.6f}, {longitude:.6f}"
                    )
                
                logger.info(f"📍 WebApp location processed: {latitude}, {longitude} -> {address}")
                
        except json.JSONDecodeError:
            logger.error(f"Failed to parse WebApp data: {message.web_app_data.data}")
            await message.answer("❌ Помилка обробки даних з карти")
        except Exception as e:
            logger.error(f"Error handling WebApp data: {e}", exc_info=True)
            await message.answer("❌ Виникла помилка. Спробуйте ще раз.")
    
    return router
