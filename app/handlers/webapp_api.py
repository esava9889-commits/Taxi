"""
API endpoint для WebApp карти
Приймає координати з карти і зберігає в FSM state користувача
"""
from __future__ import annotations

import logging
from typing import Optional

import json
import aiohttp
from aiohttp import web
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey

from app.config.config import AppConfig
from app.utils.maps import reverse_geocode, _wait_for_nominatim

logger = logging.getLogger(__name__)


def validate_coordinates(lat: float, lon: float) -> bool:
    """
    Валідувати координати
    
    Args:
        lat: Широта
        lon: Довгота
    
    Returns:
        True якщо координати валідні, False інакше
    """
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180


async def webapp_location_handler(request: web.Request) -> web.Response:
    """
    ⚠️ DEPRECATED: Цей endpoint більше не використовується!
    
    Замість нього використовуйте webapp_order_handler (/api/webapp/order),
    який приймає обидві координати одразу (pickup + destination).
    
    Старий API endpoint для отримання координат поетапно.
    
    POST /api/webapp/location (DEPRECATED)
    Body: {
        "user_id": 123456,
        "latitude": 50.4501,
        "longitude": 30.5234,
        "type": "pickup" або "destination"
    }
    """
    try:
        # Отримати дані з запиту
        data = await request.json()
        
        user_id = data.get('user_id')
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        location_type = data.get('type')  # 'pickup' або 'destination'
        
        logger.info("=" * 80)
        logger.info(f"🌐 API: Отримано координати з WebApp")
        logger.info(f"  - user_id: {user_id}")
        logger.info(f"  - latitude: {latitude}")
        logger.info(f"  - longitude: {longitude}")
        logger.info(f"  - type: {location_type}")
        logger.info("=" * 80)
        
        # Валідація
        if not user_id or latitude is None or longitude is None or not location_type:
            logger.error("❌ API: Відсутні обов'язкові параметри")
            return web.json_response(
                {"success": False, "error": "Missing required parameters"},
                status=400
            )
        
        if location_type not in ['pickup', 'destination']:
            logger.error(f"❌ API: Невірний тип локації: {location_type}")
            return web.json_response(
                {"success": False, "error": "Invalid location type"},
                status=400
            )
        
        # Валідація координат
        if not validate_coordinates(latitude, longitude):
            logger.error(f"❌ API: Невалідні координати: lat={latitude}, lon={longitude}")
            return web.json_response(
                {"success": False, "error": "Invalid coordinates (must be -90<=lat<=90, -180<=lon<=180)"},
                status=400
            )
        
        # Отримати адресу через reverse geocoding
        logger.info(f"🌍 API: Виконую reverse geocoding...")
        address = await reverse_geocode("", latitude, longitude)
        if not address:
            address = f"📍 Координати: {latitude:.6f}, {longitude:.6f}"
        logger.info(f"✅ API: Адреса: {address}")
        
        # Отримати доступ до bot і storage
        bot: Bot = request.app['bot']
        storage = request.app['storage']  # storage передається окремо
        
        # Створити storage key для користувача
        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=user_id,
            user_id=user_id
        )
        
        # Отримати поточний FSM context
        state = FSMContext(storage=storage, key=storage_key)
        
        # Зберегти дані в state
        if location_type == 'pickup':
            await state.update_data(
                pickup=address,
                pickup_lat=latitude,
                pickup_lon=longitude,
                waiting_for=None
            )
            logger.info(f"✅ API: Pickup збережено в state для user {user_id}")
        else:  # destination
            await state.update_data(
                destination=address,
                dest_lat=latitude,
                dest_lon=longitude,
                waiting_for=None
            )
            logger.info(f"✅ API: Destination збережено в state для user {user_id}")
        
        # Відправити повідомлення користувачу
        try:
            # Отримати last_message_id з state
            data = await state.get_data()
            last_message_id = data.get('last_message_id')
            
            if location_type == 'pickup':
                from app.handlers.order import OrderStates
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
                
                await state.set_state(OrderStates.destination)
                
                # Показати кнопки для вибору destination
                from app.storage.db import get_user_saved_addresses
                saved_addresses = await get_user_saved_addresses(request.app['config'].database_path, user_id)
                
                kb_buttons = []
                
                # Кнопка карти з передачею pickup координат
                if request.app['config'].webapp_url:
                    await state.update_data(waiting_for='destination')
                    # Передати pickup координати для відображення маршруту
                    data = await state.get_data()
                    pickup_lat = data.get('pickup_lat')
                    pickup_lon = data.get('pickup_lon')
                    url = f"{request.app['config'].webapp_url}?type=destination"
                    if pickup_lat and pickup_lon:
                        url += f"&pickup_lat={pickup_lat}&pickup_lon={pickup_lon}"
                    kb_buttons.append([
                        InlineKeyboardButton(
                            text="🗺 Обрати на карті (з пошуком)",
                            web_app=WebAppInfo(url=url)
                        )
                    ])
                
                # Збережені
                if saved_addresses:
                    kb_buttons.append([InlineKeyboardButton(text="📌 Вибрати зі збережених", callback_data="order:dest:saved")])
                
                # Назад + Скасувати
                kb_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="order:back:pickup")])
                kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
                
                kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
                
                # РЕДАГУВАТИ повідомлення замість створення нового
                if last_message_id:
                    try:
                        await bot.edit_message_text(
                            chat_id=user_id,
                            message_id=last_message_id,
                            text=f"✅ <b>Місце подачі:</b>\n📍 {address}\n\n"
                                f"📍 <b>Куди їдемо?</b>\n\n"
                                f"🗺 <b>Карта з пошуком</b> - знайдіть або оберіть точку\n"
                                f"📌 <b>Збережені</b> - швидкий вибір\n\n"
                                f"💡 Оберіть спосіб:",
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        # Якщо редагування не вдалося, створити нове
                        logger.warning(f"⚠️ Не вдалося редагувати повідомлення: {e}")
                        msg = await bot.send_message(
                            user_id,
                            f"✅ <b>Місце подачі:</b>\n📍 {address}\n\n"
                            f"📍 <b>Куди їдемо?</b>\n\n"
                            f"💡 Оберіть спосіб:",
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                        await state.update_data(last_message_id=msg.message_id)
                else:
                    # Якщо немає last_message_id, створити нове
                    msg = await bot.send_message(
                        user_id,
                        f"✅ <b>Місце подачі:</b>\n📍 {address}\n\n"
                        f"📍 <b>Куди їдемо?</b>\n\n"
                        f"💡 Оберіть спосіб:",
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                    await state.update_data(last_message_id=msg.message_id)
            else:  # destination
                # РЕДАГУВАТИ повідомлення для destination
                if last_message_id:
                    try:
                        await bot.edit_message_text(
                            chat_id=user_id,
                            message_id=last_message_id,
                            text=f"✅ <b>Місце призначення:</b>\n📍 {address}\n\n"
                                f"⏳ Розраховую вартість поїздки...",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ Не вдалося редагувати повідомлення: {e}")
                        msg = await bot.send_message(
                            user_id,
                            f"✅ <b>Місце призначення:</b>\n📍 {address}\n\n"
                            f"⏳ Розраховую вартість поїздки...",
                            parse_mode="HTML"
                        )
                        last_message_id = msg.message_id
                        await state.update_data(last_message_id=last_message_id)
                else:
                    msg = await bot.send_message(
                        user_id,
                        f"✅ <b>Місце призначення:</b>\n📍 {address}\n\n"
                        f"⏳ Розраховую вартість поїздки...",
                        parse_mode="HTML"
                    )
                    last_message_id = msg.message_id
                    await state.update_data(last_message_id=last_message_id)
                
                # Імпортувати необхідні функції для розрахунку
                from app.utils.maps import get_distance_and_duration
                from app.storage.db import get_latest_tariff, get_pricing_settings, get_online_drivers_count, get_user_by_id
                from app.handlers.car_classes import calculate_base_fare, calculate_fare_with_class, get_car_class_name, CAR_CLASSES
                from app.handlers.dynamic_pricing import calculate_dynamic_price, get_surge_emoji
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
                
                # Отримати pickup з state
                data = await state.get_data()
                pickup_lat = data.get("pickup_lat")
                pickup_lon = data.get("pickup_lon")
                
                # Розрахувати відстань
                distance_km = None
                duration_minutes = None
                
                if pickup_lat and pickup_lon and latitude and longitude:
                    logger.info(f"📏 Розраховую відстань: ({pickup_lat},{pickup_lon}) → ({latitude},{longitude})")
                    result = await get_distance_and_duration("", pickup_lat, pickup_lon, latitude, longitude)
                    if result:
                        distance_m, duration_s = result
                        distance_km = distance_m / 1000.0
                        duration_minutes = duration_s / 60.0
                        await state.update_data(distance_km=distance_km, duration_minutes=duration_minutes)
                        logger.info(f"✅ Відстань: {distance_km:.1f} км, час: {duration_minutes:.0f} хв")
                
                if not distance_km:
                    # КРИТИЧНА ПОМИЛКА: не вдалося розрахувати відстань
                    logger.error(f"❌ OSRM не зміг розрахувати відстань для user {user_id}: ({pickup_lat},{pickup_lon}) → ({latitude},{longitude})")
                    await bot.send_message(
                        user_id,
                        "❌ <b>Не вдалося розрахувати відстань</b>\n\n"
                        "⚠️ Будь ласка, спробуйте:\n"
                        "• Обрати інші точки на карті\n"
                        "• Перевірити інтернет-з'єднання\n"
                        "• Звернутися до підтримки\n\n"
                        "Натисніть /order щоб спробувати знову",
                        parse_mode="HTML"
                    )
                    return web.json_response(
                        {"success": False, "error": "Could not calculate distance between points"},
                        status=400
                    )
                
                # Отримати тариф
                tariff = await get_latest_tariff(request.app['config'].database_path)
                if not tariff:
                    await bot.send_message(user_id, "❌ Помилка: тариф не налаштований.", parse_mode="HTML")
                    return web.json_response({"success": False, "error": "Tariff not configured"}, status=500)
                
                # Базовий тариф (використовуємо helper функцію)
                base_fare = calculate_base_fare(tariff, distance_km, duration_minutes)
                
                # Налаштування ціноутворення
                pricing = await get_pricing_settings(request.app['config'].database_path)
                if pricing is None:
                    from app.storage.db import PricingSettings
                    pricing = PricingSettings()
                
                custom_multipliers = {
                    "economy": pricing.economy_multiplier,
                    "standard": pricing.standard_multiplier,
                    "comfort": pricing.comfort_multiplier,
                    "business": pricing.business_multiplier
                }
                
                # Місто клієнта
                user = await get_user_by_id(request.app['config'].database_path, user_id)
                client_city = user.city if user and user.city else None
                online_count = await get_online_drivers_count(request.app['config'].database_path, client_city)
                
                # Отримати кількість pending orders для розрахунку попиту
                from app.storage.db import get_pending_orders
                pending_orders = await get_pending_orders(request.app['config'].database_path, client_city)
                pending_count = len(pending_orders)
                
                # Показати класи з цінами
                from app.handlers.order import OrderStates
                await state.set_state(OrderStates.car_class)
                await state.update_data(base_fare=base_fare)
                
                kb_buttons = []
                for car_class_id, car_class_data in CAR_CLASSES.items():
                    class_fare = calculate_fare_with_class(base_fare, car_class_id, custom_multipliers)
                    
                    # ПРАВИЛЬНИЙ розрахунок з усіма параметрами (як після вибору класу!)
                    final_fare, explanation, surge_mult = await calculate_dynamic_price(
                        class_fare, client_city, online_count, pending_count,
                        pricing.night_percent, pricing.weather_percent,
                        pricing.peak_hours_percent, pricing.weekend_percent,
                        pricing.monday_morning_percent, pricing.no_drivers_percent,
                        pricing.demand_very_high_percent, pricing.demand_high_percent,
                        pricing.demand_medium_percent, pricing.demand_low_discount_percent
                    )
                    
                    surge_emoji = get_surge_emoji(surge_mult)
                    class_name = get_car_class_name(car_class_id)  # Вже містить емоджі + назву
                    
                    button_text = f"{class_name}: {final_fare:.0f} грн"
                    if surge_mult != 1.0:
                        button_text = f"{class_name}: {final_fare:.0f} грн {surge_emoji}"
                    
                    kb_buttons.append([InlineKeyboardButton(
                        text=button_text,
                        callback_data=f"select_class:{car_class_id}"
                    )])
                
                kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
                kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
                
                # РЕДАГУВАТИ повідомлення з класами
                pickup_address = data.get('pickup', 'Не вказано')
                if last_message_id:
                    try:
                        await bot.edit_message_text(
                            chat_id=user_id,
                            message_id=last_message_id,
                            text=f"✅ <b>Місце подачі:</b>\n{pickup_address}\n\n"
                                f"✅ <b>Призначення:</b>\n{address}\n\n"
                                f"📏 Відстань: {distance_km:.1f} км\n"
                                f"⏱ Час в дорозі: ~{int(duration_minutes)} хв\n\n"
                                f"🚗 <b>Оберіть клас автомобіля:</b>",
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ Не вдалося редагувати повідомлення: {e}")
                        await bot.send_message(
                            user_id,
                            f"✅ <b>Місце подачі:</b>\n{pickup_address}\n\n"
                            f"✅ <b>Призначення:</b>\n{address}\n\n"
                            f"📏 Відстань: {distance_km:.1f} км\n"
                            f"⏱ Час в дорозі: ~{int(duration_minutes)} хв\n\n"
                            f"🚗 <b>Оберіть клас автомобіля:</b>",
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                else:
                    await bot.send_message(
                        user_id,
                        f"✅ <b>Місце подачі:</b>\n{pickup_address}\n\n"
                        f"✅ <b>Призначення:</b>\n{address}\n\n"
                        f"📏 Відстань: {distance_km:.1f} км\n"
                        f"⏱ Час в дорозі: ~{int(duration_minutes)} хв\n\n"
                        f"🚗 <b>Оберіть клас автомобіля:</b>",
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                
            logger.info(f"✅ API: Повідомлення відправлено користувачу {user_id}")
        except Exception as e:
            logger.error(f"❌ API: Помилка відправки повідомлення: {e}")
        
        # Відповідь успіху
        return web.json_response({
            "success": True,
            "address": address,
            "message": "Координати збережено успішно"
        })
        
    except Exception as e:
        logger.error(f"❌ API: Критична помилка: {e}")
        logger.error(f"📜 Traceback:", exc_info=True)
        return web.json_response(
            {"success": False, "error": str(e)},
            status=500
        )


async def webapp_order_handler(request: web.Request) -> web.Response:
    """
    НОВИЙ API: Приймає обидві координати одразу (pickup + destination)
    Розраховує відстань і показує класи авто
    """
    try:
        bot = request.app['bot']
        config = request.app['config']
        storage = request.app['storage']
        
        # Отримати дані
        data = await request.json()
        user_id = data.get('user_id')
        pickup_lat = data.get('pickup_lat')
        pickup_lon = data.get('pickup_lon')
        dest_lat = data.get('dest_lat')
        dest_lon = data.get('dest_lon')
        
        logger.info("=" * 80)
        logger.info("🌐 API ORDER: Отримано обидві координати")
        logger.info(f"  - user_id: {user_id}")
        logger.info(f"  - pickup: {pickup_lat}, {pickup_lon}")
        logger.info(f"  - destination: {dest_lat}, {dest_lon}")
        logger.info("=" * 80)
        
        # Валідація координат
        if not validate_coordinates(pickup_lat, pickup_lon):
            logger.error(f"❌ API ORDER: Невалідні pickup координати: {pickup_lat}, {pickup_lon}")
            return web.json_response(
                {"success": False, "error": "Invalid pickup coordinates"},
                status=400
            )
        
        if not validate_coordinates(dest_lat, dest_lon):
            logger.error(f"❌ API ORDER: Невалідні destination координати: {dest_lat}, {dest_lon}")
            return web.json_response(
                {"success": False, "error": "Invalid destination coordinates"},
                status=400
            )
        
        # Отримати FSM context
        from aiogram.fsm.context import FSMContext
        from aiogram.fsm.storage.base import StorageKey
        
        storage_key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
        state = FSMContext(storage=storage, key=storage_key)
        
        # Reverse geocoding для обох точок
        from app.utils.maps import reverse_geocode
        import asyncio
        logger.info("🌍 API: Виконую reverse geocoding...")
        
        # 🔄 ПОСЛІДОВНО з затримкою (щоб не заблокувати rate limit)
        pickup_address = await reverse_geocode("", pickup_lat, pickup_lon)
        if not pickup_address:
            logger.warning(f"⚠️ Pickup reverse geocoding не спрацював, retry...")
            await asyncio.sleep(2.0)  # Чекати 2 сек перед retry
            pickup_address = await reverse_geocode("", pickup_lat, pickup_lon)
        
        if not pickup_address:
            logger.error(f"❌ Pickup reverse geocoding failed після retry! Використую координати")
            pickup_address = f"📍 Координати: {pickup_lat:.6f}, {pickup_lon:.6f}"
        
        # ⏰ ЗАТРИМКА між двома reverse geocode (гарантувати rate limit)
        await asyncio.sleep(0.5)
        
        dest_address = await reverse_geocode("", dest_lat, dest_lon)
        if not dest_address:
            logger.warning(f"⚠️ Destination reverse geocoding не спрацював, retry...")
            await asyncio.sleep(2.0)  # Чекати 2 сек перед retry
            dest_address = await reverse_geocode("", dest_lat, dest_lon)
        
        if not dest_address:
            logger.error(f"❌ Destination reverse geocoding failed після retry! Використую координати")
            dest_address = f"📍 Координати: {dest_lat:.6f}, {dest_lon:.6f}"
        
        logger.info(f"✅ Pickup: {pickup_address}")
        logger.info(f"✅ Destination: {dest_address}")
        
        # Зберегти в state
        from app.handlers.order import OrderStates
        await state.set_state(OrderStates.car_class)
        await state.update_data(
            pickup=pickup_address,
            pickup_lat=pickup_lat,
            pickup_lon=pickup_lon,
            destination=dest_address,
            dest_lat=dest_lat,
            dest_lon=dest_lon,
            waiting_for=None
        )
        
        # Розрахувати відстань ПРАВИЛЬНО (тут!)
        from app.utils.maps import get_distance_and_duration
        distance_km = None
        duration_minutes = None
        
        logger.info(f"📏 Розраховую відстань: ({pickup_lat},{pickup_lon}) → ({dest_lat},{dest_lon})")
        result = await get_distance_and_duration("", pickup_lat, pickup_lon, dest_lat, dest_lon)
        if result:
            distance_m, duration_s = result
            distance_km = distance_m / 1000.0
            duration_minutes = duration_s / 60.0
            await state.update_data(distance_km=distance_km, duration_minutes=duration_minutes)
            logger.info(f"✅ Відстань: {distance_km:.1f} км, час: {duration_minutes:.0f} хв")
        
        if not distance_km:
            # КРИТИЧНА ПОМИЛКА: не вдалося розрахувати відстань
            logger.error(f"❌ OSRM не зміг розрахувати відстань для user {user_id}: ({pickup_lat},{pickup_lon}) → ({dest_lat},{dest_lon})")
            await bot.send_message(
                user_id,
                "❌ <b>Не вдалося розрахувати відстань</b>\n\n"
                "⚠️ Будь ласка, спробуйте:\n"
                "• Обрати інші точки на карті\n"
                "• Перевірити інтернет-з'єднання\n"
                "• Звернутися до підтримки\n\n"
                "Натисніть /order щоб спробувати знову",
                parse_mode="HTML"
            )
            return web.json_response(
                {"success": False, "error": "Could not calculate distance between points"},
                status=400
            )
        
        # Отримати тариф та розрахувати ціни для класів
        from app.storage.db import get_latest_tariff, get_pricing_settings, get_online_drivers_count, get_user_by_id
        from app.handlers.car_classes import calculate_base_fare, calculate_fare_with_class, get_car_class_name, CAR_CLASSES
        from app.handlers.dynamic_pricing import calculate_dynamic_price, get_surge_emoji
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        tariff = await get_latest_tariff(config.database_path)
        if not tariff:
            await bot.send_message(user_id, "❌ Помилка: тариф не налаштований.", parse_mode="HTML")
            return web.json_response({"success": False, "error": "Tariff not configured"}, status=500)
        
        # Базовий тариф (використовуємо helper функцію)
        base_fare = calculate_base_fare(tariff, distance_km, duration_minutes)
        
        # Налаштування ціноутворення
        pricing = await get_pricing_settings(config.database_path)
        if pricing is None:
            from app.storage.db import PricingSettings
            pricing = PricingSettings()
            logger.warning("⚠️ PricingSettings not found in DB, using defaults")
        else:
            logger.info(f"✅ PricingSettings loaded: night={pricing.night_percent}%, peak={pricing.peak_hours_percent}%, weather={pricing.weather_percent}%")
        
        custom_multipliers = {
            "economy": pricing.economy_multiplier,
            "standard": pricing.standard_multiplier,
            "comfort": pricing.comfort_multiplier,
            "business": pricing.business_multiplier
        }
        
        # Місто клієнта
        user = await get_user_by_id(config.database_path, user_id)
        client_city = user.city if user and user.city else None
        online_count = await get_online_drivers_count(config.database_path, client_city)
        
        # Зберегти base_fare
        await state.update_data(base_fare=base_fare)
        
        # Отримати кількість pending orders для розрахунку попиту
        from app.storage.db import get_pending_orders
        pending_orders = await get_pending_orders(config.database_path, client_city)
        pending_count = len(pending_orders)
        
        logger.info(f"📊 Pricing context: city={client_city}, online_drivers={online_count}, pending_orders={pending_count}")
        
        # Створити кнопки з класами
        kb_buttons = []
        for car_class_id, car_class_data in CAR_CLASSES.items():
            class_fare = calculate_fare_with_class(base_fare, car_class_id, custom_multipliers)
            
            # ПРАВИЛЬНИЙ розрахунок з усіма параметрами
            final_fare, explanation, surge_mult = await calculate_dynamic_price(
                class_fare, client_city, online_count, pending_count,
                pricing.night_percent, pricing.weather_percent,
                pricing.peak_hours_percent, pricing.weekend_percent,
                pricing.monday_morning_percent, pricing.no_drivers_percent,
                pricing.demand_very_high_percent, pricing.demand_high_percent,
                pricing.demand_medium_percent, pricing.demand_low_discount_percent
            )
            
            surge_emoji = get_surge_emoji(surge_mult)
            class_name = get_car_class_name(car_class_id)
            
            button_text = f"{class_name}: {final_fare:.0f} грн"
            if surge_mult != 1.0:
                button_text = f"{class_name}: {final_fare:.0f} грн {surge_emoji}"
            
            kb_buttons.append([InlineKeyboardButton(
                text=button_text,
                callback_data=f"select_class:{car_class_id}"
            )])
        
        kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        # Отримати last_message_id і редагувати повідомлення
        data_state = await state.get_data()
        last_message_id = data_state.get('last_message_id')
        
        msg_text = (
            f"✅ <b>Місце подачі:</b>\n{pickup_address}\n\n"
            f"✅ <b>Призначення:</b>\n{dest_address}\n\n"
            f"📏 Відстань: {distance_km:.1f} км\n"
            f"⏱ Час в дорозі: ~{int(duration_minutes)} хв\n\n"
            f"🚗 <b>Оберіть клас автомобіля:</b>"
        )
        
        if last_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=last_message_id,
                    text=msg_text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося редагувати: {e}")
                await bot.send_message(user_id, msg_text, reply_markup=kb, parse_mode="HTML")
        else:
            await bot.send_message(user_id, msg_text, reply_markup=kb, parse_mode="HTML")
        
        logger.info("✅ API ORDER: Повідомлення відправлено")
        
        return web.json_response({
            "success": True,
            "pickup_address": pickup_address,
            "dest_address": dest_address,
            "distance_km": distance_km,
            "duration_minutes": int(duration_minutes)
        })
        
    except Exception as e:
        logger.error(f"❌ API ORDER: Критична помилка: {e}")
        logger.error(f"📜 Traceback:", exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "TaxiBot WebApp/1.0 (support@taxi-bot.example)"


async def webapp_geocode_proxy(request: web.Request) -> web.Response:
    """Proxy запитів до Nominatim з серверного боку (із User-Agent та rate limit)."""
    try:
        # Зібрати параметри з query string
        params = dict(request.rel_url.query)

        # Якщо надіслано JSON тіло (POST), об'єднати з параметрами
        if request.can_read_body and request.method in {"POST", "PUT", "PATCH"}:
            try:
                payload = await request.json()
                if isinstance(payload, dict):
                    for key, value in payload.items():
                        if value is not None and value != "":
                            params[str(key)] = str(value)
            except json.JSONDecodeError:
                logger.warning("⚠️ Proxy geocode: не вдалося розпарсити JSON тіло")

        query = params.get("q") or params.get("query")
        if not query or not str(query).strip():
            return web.json_response({"error": "Missing required parameter 'q'"}, status=400)

        query = str(query).strip()
        
        # 🎯 SERVER-SIDE ФІЛЬТРАЦІЯ: Отримати місто користувача
        user_id = params.get("user_id")
        client_city = None
        city_coords = None
        
        if user_id:
            try:
                from app.storage.db import get_user_by_id
                user = await get_user_by_id(request.app['config'].database_path, int(user_id))
                if user and user.city:
                    client_city = user.city
                    
                    # Координати міст України (з webapp_get_user_city_handler)
                    city_coordinates = {
                        "Київ": {"lat": 50.4501, "lon": 30.5234},
                        "Харків": {"lat": 49.9935, "lon": 36.2304},
                        "Одеса": {"lat": 46.4825, "lon": 30.7233},
                        "Дніпро": {"lat": 48.4647, "lon": 35.0462},
                        "Донецьк": {"lat": 48.0159, "lon": 37.8028},
                        "Запоріжжя": {"lat": 47.8388, "lon": 35.1396},
                        "Львів": {"lat": 49.8397, "lon": 24.0297},
                        "Кривий Ріг": {"lat": 47.9088, "lon": 33.3443},
                        "Миколаїв": {"lat": 46.9750, "lon": 31.9946},
                        "Маріуполь": {"lat": 47.0956, "lon": 37.5431},
                        "Луганськ": {"lat": 48.5740, "lon": 39.3078},
                        "Вінниця": {"lat": 49.2328, "lon": 28.4681},
                        "Макіївка": {"lat": 48.0479, "lon": 37.9772},
                        "Сімферополь": {"lat": 44.9521, "lon": 34.1024},
                        "Севастополь": {"lat": 44.6167, "lon": 33.5254},
                        "Херсон": {"lat": 46.6354, "lon": 32.6169},
                        "Полтава": {"lat": 49.5883, "lon": 34.5514},
                        "Чернігів": {"lat": 51.4982, "lon": 31.2893},
                        "Черкаси": {"lat": 49.4444, "lon": 32.0598},
                        "Житомир": {"lat": 50.2547, "lon": 28.6587},
                        "Суми": {"lat": 50.9077, "lon": 34.7981},
                        "Хмельницький": {"lat": 49.4229, "lon": 26.9871},
                        "Чернівці": {"lat": 48.2921, "lon": 25.9358},
                        "Рівне": {"lat": 50.6199, "lon": 26.2516},
                        "Кропивницький": {"lat": 48.5079, "lon": 32.2623},
                        "Івано-Франківськ": {"lat": 48.9226, "lon": 24.7111},
                        "Кам'янське": {"lat": 48.5132, "lon": 34.6031},
                        "Тернопіль": {"lat": 49.5535, "lon": 25.5948},
                        "Луцьк": {"lat": 50.7472, "lon": 25.3254},
                        "Біла Церква": {"lat": 49.8097, "lon": 30.1127},
                        "Краматорськ": {"lat": 48.7233, "lon": 37.5562},
                        "Мелітополь": {"lat": 46.8489, "lon": 35.3675},
                        "Ужгород": {"lat": 48.6208, "lon": 22.2879},
                    }
                    city_coords = city_coordinates.get(client_city)
                    logger.info(f"🏙️ Місто користувача {user_id}: {client_city}")
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося отримати місто користувача: {e}")
        
        # 🎯 ДОДАТИ МІСТО ДО ЗАПИТУ (якщо його немає)
        if client_city:
            query_lower = query.lower()
            city_lower = client_city.lower()
            
            if city_lower not in query_lower:
                query = f"{query}, {client_city}, Україна"
                logger.info(f"🎯 Додано місто до запиту: '{query}'")
            elif "україна" not in query_lower and "ukraine" not in query_lower:
                query = f"{query}, Україна"
                logger.info(f"🎯 Додано країну до запиту: '{query}'")
        
        proxy_params = {
            "q": query,
            "format": "json",
            "addressdetails": params.get("addressdetails", "1"),
            "limit": params.get("limit", "15"),  # Збільшено для кращої фільтрації
        }

        # ЗАВЖДИ обмежувати Україною
        proxy_params["countrycodes"] = params.get("countrycodes", "ua")

        # 🎯 ДОДАТИ VIEWBOX якщо є координати міста (SERVER-SIDE)
        if city_coords and not params.get("viewbox"):
            lat = city_coords["lat"]
            lon = city_coords["lon"]
            box_size = 0.15  # ±15 км
            
            min_lon = lon - box_size
            min_lat = lat - box_size
            max_lon = lon + box_size
            max_lat = lat + box_size
            
            proxy_params["viewbox"] = f"{min_lon:.4f},{min_lat:.4f},{max_lon:.4f},{max_lat:.4f}"
            proxy_params["bounded"] = params.get("bounded", "1")
            logger.info(f"🎯 Додано viewbox для міста {client_city}: {proxy_params['viewbox']}")
        elif params.get("viewbox"):
            # Якщо viewbox вже є з фронтенду - використати його
            proxy_params["viewbox"] = params["viewbox"]
            if params.get("bounded"):
                proxy_params["bounded"] = params["bounded"]

        # Бажано повертати українською
        proxy_params["accept-language"] = params.get("accept-language", "uk,en")

        debug_info = {
            "query": query,
            "city": client_city,
            "params": proxy_params
        }
        logger.info(f"🛰️ Proxy geocode: {debug_info}")

        # Поважаємо rate limit Nominatim (1 запит/сек)
        await _wait_for_nominatim()

        headers = {
            "User-Agent": NOMINATIM_USER_AGENT,
        }

        # ✅ SSL FIX: використати ssl=False для повного відключення SSL верифікації
        import ssl
        
        # Спробувати з різними SSL налаштуваннями
        ssl_context = False  # Спочатку повністю вимкнути SSL верифікацію
        
        connector = aiohttp.TCPConnector(ssl=ssl_context, force_close=True, limit=10)
        
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(NOMINATIM_SEARCH_URL, params=proxy_params, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                body_text = await resp.text()

                if resp.status != 200:
                    logger.warning(
                        "⚠️ Proxy geocode: Nominatim status %s, body: %s",
                        resp.status,
                        body_text[:200]
                    )
                    return web.json_response(
                        {
                            "error": "Nominatim request failed",
                            "status": resp.status,
                            "body": body_text[:500]
                        },
                        status=resp.status
                    )

                try:
                    data = await resp.json(content_type=None)
                except Exception as e:  # noqa: BLE001
                    logger.error("❌ Proxy geocode: JSON decode error %s", e)
                    logger.debug("❌ Proxy geocode body: %s", body_text[:500])
                    return web.json_response(
                        {
                            "error": "Invalid JSON from Nominatim",
                            "status": resp.status
                        },
                        status=502
                    )

        if not isinstance(data, list):
            logger.warning("⚠️ Proxy geocode: unexpected response type: %s", type(data))
            return web.json_response(
                {
                    "error": "Unexpected response format",
                    "status": 502
                },
                status=502
            )

        logger.info(f"✅ Proxy geocode: '{query}' → {len(data)} результат(и)")
        return web.json_response(data)

    except aiohttp.ClientConnectorError as e:
        logger.error("❌ Proxy geocode: cannot connect to Nominatim: %s", e)
        
        # 🔄 FALLBACK: Спробувати з базовим SSL context
        try:
            logger.info("🔄 Retry з базовим SSL context...")
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            connector = aiohttp.TCPConnector(ssl=ssl_context, force_close=True)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(NOMINATIM_SEARCH_URL, params=proxy_params, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        logger.info(f"✅ Proxy geocode (retry): '{query}' → {len(data) if isinstance(data, list) else 0} результат(и)")
                        return web.json_response(data)
        except Exception as retry_error:
            logger.error("❌ Retry також не вдався: %s", retry_error)
        
        return web.json_response({"error": "Cannot connect to Nominatim", "details": str(e)}, status=503)
    
    except Exception as e:  # noqa: BLE001
        logger.error("❌ Proxy geocode: critical error: %s", e, exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


async def webapp_calculate_price_handler(request: web.Request) -> web.Response:
    """
    API endpoint для розрахунку ціни на карті
    
    POST /api/webapp/calculate-price
    Body: {
        "user_id": 123456,
        "distance_km": 5.2,
        "duration_minutes": 15
    }
    
    Returns: {
        "success": true,
        "price": 120.50,
        "base_fare": 100.00,
        "multiplier": 1.205,
        "explanation": "• Піковий час: +30%\n• Високий попит: +25%"
    }
    """
    try:
        data = await request.json()
        user_id = data.get("user_id")
        distance_km = data.get("distance_km")
        duration_minutes = data.get("duration_minutes")
        
        if not user_id or distance_km is None or duration_minutes is None:
            return web.json_response({
                "success": False,
                "error": "Missing required fields: user_id, distance_km, duration_minutes"
            }, status=400)
        
        # Імпорти
        from app.storage.db import (
            get_latest_tariff, get_pricing_settings, get_online_drivers_count, 
            get_user_by_id, get_pending_orders, PricingSettings
        )
        from app.handlers.car_classes import calculate_base_fare, calculate_fare_with_class
        from app.handlers.dynamic_pricing import calculate_dynamic_price
        
        # Отримати тариф
        tariff = await get_latest_tariff(request.app['config'].database_path)
        if not tariff:
            return web.json_response({
                "success": False,
                "error": "Tariff not configured"
            }, status=500)
        
        # Базова ціна (без класу авто та динаміки)
        base_fare = calculate_base_fare(tariff, distance_km, duration_minutes)
        
        # Налаштування ціноутворення (тут зберігаються всі актуальні відсотки з адмін-панелі)
        pricing = await get_pricing_settings(request.app['config'].database_path)
        if pricing is None:
            pricing = PricingSettings()
        
        # Місто користувача
        user = await get_user_by_id(request.app['config'].database_path, user_id)
        client_city = user.city if user and user.city else None
        online_count = await get_online_drivers_count(request.app['config'].database_path, client_city)
        
        # Отримати РЕАЛЬНУ кількість pending orders (так само як у боті)
        pending_orders = await get_pending_orders(request.app['config'].database_path, client_city)
        pending_orders_count = len(pending_orders)
        
        # Створити словник множників класів для передачі в calculate_fare_with_class
        custom_multipliers = {
            "economy": pricing.economy_multiplier,
            "standard": pricing.standard_multiplier,
            "comfort": pricing.comfort_multiplier,
            "business": pricing.business_multiplier
        }
        
        # Розрахувати ціну для Economy класу (стандартний клас на карті)
        # ТОЧНО ТАК САМО ЯК У БОТІ (order.py рядки 195-203)
        economy_fare = calculate_fare_with_class(base_fare, "economy", custom_multipliers)
        
        # Розрахувати динамічну ціну з ПРАВИЛЬНИМИ параметрами з pricing (не з tariff!)
        final_price, explanation, total_multiplier = await calculate_dynamic_price(
            economy_fare,  # Ціна з урахуванням economy класу
            city=client_city or "Київ",
            online_drivers=online_count,
            pending_orders=pending_orders_count,
            # ✅ ВИПРАВЛЕНО: Використовуємо pricing.night_percent замість tariff.night_tariff_percent
            night_percent=pricing.night_percent,  # З адмін панелі (45%, а не 50%)
            weather_percent=pricing.weather_percent,  # З адмін панелі
            peak_hours_percent=pricing.peak_hours_percent,
            weekend_percent=pricing.weekend_percent,
            monday_morning_percent=pricing.monday_morning_percent,
            no_drivers_percent=pricing.no_drivers_percent,
            demand_very_high_percent=pricing.demand_very_high_percent,
            demand_high_percent=pricing.demand_high_percent,
            demand_medium_percent=pricing.demand_medium_percent,
            demand_low_discount_percent=pricing.demand_low_discount_percent
        )
        
        logger.info(f"💰 Price calculated for user {user_id}: base={base_fare:.2f}, economy={economy_fare:.2f}, final={final_price:.2f}, multiplier={total_multiplier:.2f}")
        
        return web.json_response({
            "success": True,
            "price": round(final_price, 2),
            "base_fare": round(base_fare, 2),
            "economy_fare": round(economy_fare, 2),
            "multiplier": round(total_multiplier, 2),
            "explanation": explanation,
            "car_class": "economy"  # Вказуємо клас авто для якого розрахована ціна
        })
        
    except Exception as e:
        logger.error(f"❌ Error calculating price: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


async def webapp_get_user_city_handler(request: web.Request) -> web.Response:
    """
    API endpoint для отримання міста клієнта та його координат
    
    POST /api/webapp/get-user-city
    Body: {
        "user_id": 123456
    }
    
    Response: {
        "success": True,
        "city": "Київ",
        "coordinates": {
            "lat": 50.4501,
            "lon": 30.5234,
            "city": "Київ"
        }
    }
    """
    try:
        data = await request.json()
        user_id = data.get('user_id')
        
        if not user_id:
            return web.json_response({
                "success": False,
                "error": "Missing user_id"
            }, status=400)
        
        logger.info(f"🏙️ Getting city for user {user_id}")
        
        # Отримати користувача з БД
        from app.storage.db import get_user_by_id
        user = await get_user_by_id(request.app['config'].database_path, user_id)
        
        if not user or not user.city:
            logger.warning(f"⚠️ User {user_id} has no city")
            return web.json_response({
                "success": False,
                "error": "User city not found"
            }, status=404)
        
        # Координати міст України
        city_coordinates = {
            "Київ": {"lat": 50.4501, "lon": 30.5234},
            "Харків": {"lat": 49.9935, "lon": 36.2304},
            "Одеса": {"lat": 46.4825, "lon": 30.7233},
            "Дніпро": {"lat": 48.4647, "lon": 35.0462},
            "Донецьк": {"lat": 48.0159, "lon": 37.8028},
            "Запоріжжя": {"lat": 47.8388, "lon": 35.1396},
            "Львів": {"lat": 49.8397, "lon": 24.0297},
            "Кривий Ріг": {"lat": 47.9088, "lon": 33.3443},
            "Миколаїв": {"lat": 46.9750, "lon": 31.9946},
            "Маріуполь": {"lat": 47.0956, "lon": 37.5431},
            "Луганськ": {"lat": 48.5740, "lon": 39.3078},
            "Вінниця": {"lat": 49.2328, "lon": 28.4681},
            "Макіївка": {"lat": 48.0479, "lon": 37.9772},
            "Сімферополь": {"lat": 44.9521, "lon": 34.1024},
            "Севастополь": {"lat": 44.6167, "lon": 33.5254},
            "Херсон": {"lat": 46.6354, "lon": 32.6169},
            "Полтава": {"lat": 49.5883, "lon": 34.5514},
            "Чернігів": {"lat": 51.4982, "lon": 31.2893},
            "Черкаси": {"lat": 49.4444, "lon": 32.0598},
            "Житомир": {"lat": 50.2547, "lon": 28.6587},
            "Суми": {"lat": 50.9077, "lon": 34.7981},
            "Хмельницький": {"lat": 49.4229, "lon": 26.9871},
            "Чернівці": {"lat": 48.2921, "lon": 25.9358},
            "Рівне": {"lat": 50.6199, "lon": 26.2516},
            "Кропивницький": {"lat": 48.5079, "lon": 32.2623},
            "Івано-Франківськ": {"lat": 48.9226, "lon": 24.7111},
            "Кам'янське": {"lat": 48.5132, "lon": 34.6031},
            "Тернопіль": {"lat": 49.5535, "lon": 25.5948},
            "Луцьк": {"lat": 50.7472, "lon": 25.3254},
            "Біла Церква": {"lat": 49.8097, "lon": 30.1127},
            "Краматорськ": {"lat": 48.7233, "lon": 37.5562},
            "Мелітополь": {"lat": 46.8489, "lon": 35.3675},
            "Ужгород": {"lat": 48.6208, "lon": 22.2879},
        }
        
        city = user.city
        coordinates = city_coordinates.get(city)
        
        if not coordinates:
            # Якщо міста немає в списку, повертаємо Київ за замовчуванням
            logger.warning(f"⚠️ City '{city}' not found in coordinates map, using Kyiv")
            coordinates = city_coordinates["Київ"]
            city = "Київ"
        
        logger.info(f"✅ City found: {city} ({coordinates['lat']}, {coordinates['lon']})")
        
        return web.json_response({
            "success": True,
            "city": city,
            "coordinates": {
                "lat": coordinates["lat"],
                "lon": coordinates["lon"],
                "city": city
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting user city: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


def setup_webapp_api(app: web.Application, bot: Bot, config: AppConfig, storage) -> None:
    """
    Налаштувати API endpoints для WebApp
    """
    # Зберегти bot, storage і config в app для доступу в handlers
    app['bot'] = bot
    app['config'] = config
    app['storage'] = storage
    
    # Додати routes
    # webapp_location_handler ВИДАЛЕНО - використовується тільки webapp_order_handler
    app.router.add_post('/api/webapp/order', webapp_order_handler)
    app.router.add_get('/api/webapp/geocode', webapp_geocode_proxy)
    app.router.add_post('/api/webapp/geocode', webapp_geocode_proxy)
    app.router.add_post('/api/webapp/calculate-price', webapp_calculate_price_handler)
    app.router.add_post('/api/webapp/get-user-city', webapp_get_user_city_handler)
    
    logger.info("🌐 API endpoint registered: POST /api/webapp/order")
    logger.info("🌐 API endpoint registered: GET/POST /api/webapp/geocode")
    logger.info("🌐 API endpoint registered: POST /api/webapp/calculate-price")
    logger.info("🌐 API endpoint registered: POST /api/webapp/get-user-city")
