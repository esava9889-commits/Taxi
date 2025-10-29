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
        logger.info("=" * 60)
        logger.info(f"🗺 WEBAPP DATA RECEIVED from user {message.from_user.id}")
        logger.info("=" * 60)
        logger.info(f"📦 Message object: {message}")
        logger.info(f"📦 Message type: {message.content_type}")
        logger.info(f"📦 Has web_app_data: {hasattr(message, 'web_app_data')}")
        logger.info(f"📦 web_app_data is None: {message.web_app_data is None}")
        
        if not message.web_app_data:
            logger.error("=" * 60)
            logger.error("❌ ERROR: message.web_app_data is None!")
            logger.error("=" * 60)
            logger.error(f"Message dict: {message.model_dump()}")
            await message.answer("❌ Помилка: не отримано даних з WebApp")
            return
        
        try:
            # Парсинг даних з WebApp
            raw_data = message.web_app_data.data
            logger.info(f"📦 Raw WebApp data string: '{raw_data}'")
            logger.info(f"📦 Data type: {type(raw_data)}")
            logger.info(f"📦 Data length: {len(raw_data)}")
            
            logger.info("🔧 Parsing JSON...")
            data = json.loads(raw_data)
            logger.info(f"✅ Parsed JSON successfully: {data}")
            logger.info(f"🔍 Data keys: {list(data.keys())}")
            logger.info(f"🔍 Data type field: '{data.get('type')}'")
            
            if data.get('type') == 'location':
                logger.info("✅ Data type is 'location'")
                
                latitude = data.get('latitude')
                longitude = data.get('longitude')
                
                logger.info(f"📍 Extracted coordinates:")
                logger.info(f"  - latitude: {latitude} (type: {type(latitude)})")
                logger.info(f"  - longitude: {longitude} (type: {type(longitude)})")
                
                if not latitude or not longitude:
                    logger.error(f"❌ Missing coordinates! lat={latitude}, lon={longitude}")
                    await message.answer("❌ Помилка: не вдалося отримати координати")
                    return
                
                logger.info("✅ Coordinates are valid")
                
                # Отримати адресу з координат (reverse geocoding)
                logger.info(f"🌍 Calling reverse_geocode({latitude}, {longitude})...")
                address = await reverse_geocode("", latitude, longitude)
                logger.info(f"✅ Reverse geocoding result: '{address}'")
                
                if not address:
                    address = f"📍 Координати: {latitude:.6f}, {longitude:.6f}"
                    logger.warning(f"⚠️ No address found, using coordinates: {address}")
                
                # Зберегти в state залежно від поточного стану
                current_state = await state.get_state()
                state_data = await state.get_data()
                
                waiting_for = state_data.get('waiting_for')
                logger.info(f"📍 WebApp location received:")
                logger.info(f"  - Latitude: {latitude}")
                logger.info(f"  - Longitude: {longitude}")
                logger.info(f"  - Address: {address}")
                logger.info(f"  - Current state: {current_state}")
                logger.info(f"  - Waiting for: {waiting_for}")
                logger.info(f"  - All state data keys: {list(state_data.keys())}")
                
                # Перевірити в якому стані користувач (pickup або destination)
                # ВАЖЛИВО: перевіряємо waiting_for ПЕРШИМ (надійніший спосіб!)
                if waiting_for == 'pickup':
                    # ===== PICKUP =====
                    # Зберегти адресу подачі (використовуємо ключі як в order.py!)
                    await state.update_data(
                        pickup=address,  # ← ключ як в order.py
                        pickup_lat=latitude,
                        pickup_lon=longitude,  # ← lon, не lng!
                        waiting_for=None,  # Очистити, щоб не було конфліктів
                    )
                    
                    logger.info(f"✅ WebApp pickup збережено: {address} ({latitude}, {longitude})")
                    logger.info(f"📦 State після збереження pickup: {await state.get_data()}")
                    
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
                    
                elif waiting_for == 'destination':
                    # ===== DESTINATION =====
                    # Зберегти адресу призначення (використовуємо ключі як в order.py!)
                    await state.update_data(
                        destination=address,  # ← ключ як in order.py
                        dest_lat=latitude,
                        dest_lon=longitude,  # ← lon, не lng!
                        waiting_for=None,  # Очистити, щоб не було конфліктів
                    )
                    
                    logger.info(f"✅ WebApp destination збережено: {address} ({latitude}, {longitude})")
                    logger.info(f"📦 State після збереження destination: {await state.get_data()}")
                    
                    # Показати повідомлення про розрахунок
                    await message.answer(
                        f"✅ <b>Місце призначення:</b>\n📍 {address}\n\n"
                        f"⏳ Розраховую відстань та вартість поїздки...",
                    )
                    
                    # ⭐ Перейти до стану car_class - обробник в order.py покаже класи автоматично
                    # Не можемо викликати show_car_class_selection_with_prices бо вона всередині create_router
                    # Замість цього - емулюємо callback який викличе показ класів
                    from app.handlers.order import OrderStates
                    await state.set_state(OrderStates.car_class)
                    
                    # Викликаємо callback який показує класи (є в order.py)
                    # Створюємо фейковий CallbackQuery для виклику show_classes_callback
                    # АБО просто дублюємо логіку розрахунку тут
                    
                    # Отримати дані для розрахунку
                    data = await state.get_data()
                    pickup_lat = data.get("pickup_lat")
                    pickup_lon = data.get("pickup_lon")
                    dest_lat = data.get("dest_lat")
                    dest_lon = data.get("dest_lon")
                    
                    # Розрахувати відстань
                    from app.utils.maps import get_distance_and_duration
                    from app.storage.db import get_latest_tariff, get_pricing_settings, get_online_drivers_count
                    from app.handlers.car_classes import calculate_fare_with_class, get_car_class_name, CAR_CLASSES
                    from app.handlers.dynamic_pricing import calculate_dynamic_price, get_surge_emoji
                    
                    distance_km = None
                    duration_minutes = None
                    
                    if pickup_lat and pickup_lon and dest_lat and dest_lon:
                        logger.info(f"📏 Розраховую відстань: ({pickup_lat},{pickup_lon}) → ({dest_lat},{dest_lon})")
                        result = await get_distance_and_duration("", pickup_lat, pickup_lon, dest_lat, dest_lon)
                        if result:
                            distance_m, duration_s = result
                            distance_km = distance_m / 1000.0
                            duration_minutes = duration_s / 60.0
                            await state.update_data(distance_km=distance_km, duration_minutes=duration_minutes, distance_m=distance_m, duration_s=duration_s)
                            logger.info(f"✅ Відстань: {distance_km:.1f} км, час: {duration_minutes:.0f} хв")
                    
                    if not distance_km:
                        distance_km = 5.0
                        duration_minutes = 15
                        await state.update_data(distance_km=distance_km, duration_minutes=duration_minutes)
                    
                    # Отримати тариф
                    tariff = await get_latest_tariff(config.database_path)
                    if not tariff:
                        await message.answer("❌ Помилка: тариф не налаштований. Зверніться до адміністратора.")
                        return
                    
                    # Базовий тариф
                    base_fare = max(
                        tariff.minimum,
                        tariff.base_fare + (distance_km * tariff.per_km) + (duration_minutes * tariff.per_minute)
                    )
                    
                    # Отримати налаштування ціноутворення
                    pricing = await get_pricing_settings(config.database_path)
                    if pricing is None:
                        from app.storage.db import PricingSettings
                        pricing = PricingSettings()
                    
                    custom_multipliers = {
                        "economy": pricing.economy_multiplier,
                        "standard": pricing.standard_multiplier,
                        "comfort": pricing.comfort_multiplier,
                        "business": pricing.business_multiplier
                    }
                    
                    # Отримати місто клієнта для динамічного ціноутворення
                    from app.storage.db import get_user_by_id
                    user = await get_user_by_id(config.database_path, message.from_user.id)
                    client_city = user.city if user and user.city else None
                    online_count = await get_online_drivers_count(config.database_path, client_city)
                    
                    # Показати класи з цінами
                    kb_buttons = []
                    
                    # Зберегти base_fare один раз
                    await state.update_data(base_fare=base_fare)
                    
                    for car_class_id, car_class_data in CAR_CLASSES.items():
                        class_fare = calculate_fare_with_class(base_fare, car_class_id, custom_multipliers)
                        
                        # calculate_dynamic_price повертає (final_price, explanation, total_multiplier)
                        final_fare, explanation, surge_mult = await calculate_dynamic_price(class_fare, client_city, online_count, 0)
                        
                        surge_emoji = get_surge_emoji(surge_mult)
                        class_name = get_car_class_name(car_class_id)
                        
                        button_text = f"{car_class_data['emoji']} {class_name}: {final_fare:.0f} грн"
                        if surge_mult != 1.0:
                            surge_percent = int((surge_mult - 1) * 100)
                            button_text = f"{car_class_data['emoji']} {class_name}: {final_fare:.0f} грн {surge_emoji}"
                        
                        kb_buttons.append([InlineKeyboardButton(
                            text=button_text,
                            callback_data=f"select_class:{car_class_id}"
                        )])
                    
                    kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
                    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
                    
                    logger.info(f"✅ Відправляю кнопки вибору класу авто (distance: {distance_km:.1f} km)")
                    
                    await message.answer(
                        f"🚗 <b>Оберіть клас автомобіля</b>\n\n"
                        f"📏 Відстань: {distance_km:.1f} км\n"
                        f"⏱ Час в дорозі: ~{int(duration_minutes)} хв\n\n"
                        f"💡 Виберіть клас авто:",
                        reply_markup=kb
                    )
                    
                else:
                    # Невідомий стан - показати помилку і дані для діагностики
                    logger.error(f"❌ Unknown waiting_for state: {waiting_for}, current_state: {current_state}")
                    await message.answer(
                        f"⚠️ <b>Помилка:</b> невідомий стан замовлення\n\n"
                        f"📍 <b>Обрана адреса:</b>\n{address}\n\n"
                        f"Координати: {latitude:.6f}, {longitude:.6f}\n\n"
                        f"🔧 Діагностика:\n"
                        f"State: {current_state}\n"
                        f"Waiting for: {waiting_for}\n\n"
                        f"Будь ласка, почніть замовлення спочатку /order"
                    )
                
                logger.info(f"📍 WebApp location processed: {latitude}, {longitude} -> {address}")
                
        except json.JSONDecodeError as e:
            logger.error("=" * 60)
            logger.error("❌ JSON DECODE ERROR")
            logger.error("=" * 60)
            logger.error(f"Error: {e}")
            logger.error(f"Raw data that failed: '{message.web_app_data.data}'")
            logger.error("=" * 60)
            await message.answer("❌ Помилка обробки даних з карти (невірний формат JSON)")
        except Exception as e:
            logger.error("=" * 60)
            logger.error("❌ EXCEPTION in WebApp handler")
            logger.error("=" * 60)
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"Exception message: {e}", exc_info=True)
            logger.error("=" * 60)
            await message.answer("❌ Виникла помилка. Спробуйте ще раз.")
    
    return router
