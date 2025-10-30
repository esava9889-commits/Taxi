"""
API endpoint для WebApp карти
Приймає координати з карти і зберігає в FSM state користувача
"""
from __future__ import annotations

import logging
from typing import Optional

from aiohttp import web
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey

from app.config.config import AppConfig
from app.utils.maps import reverse_geocode

logger = logging.getLogger(__name__)


async def webapp_location_handler(request: web.Request) -> web.Response:
    """
    API endpoint для отримання координат з WebApp карти
    
    POST /api/webapp/location
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
        if not user_id or not latitude or not longitude or not location_type:
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
                
                # Кнопка карти
                if request.app['config'].webapp_url:
                    await state.update_data(waiting_for='destination')
                    kb_buttons.append([
                        InlineKeyboardButton(
                            text="🗺 Обрати на карті (з пошуком)",
                            web_app=WebAppInfo(url=f"{request.app['config'].webapp_url}?type=destination")
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
                from app.handlers.car_classes import calculate_fare_with_class, get_car_class_name, CAR_CLASSES
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
                    distance_km = 5.0
                    duration_minutes = 15
                    await state.update_data(distance_km=distance_km, duration_minutes=duration_minutes)
                
                # Отримати тариф
                tariff = await get_latest_tariff(request.app['config'].database_path)
                if not tariff:
                    await bot.send_message(user_id, "❌ Помилка: тариф не налаштований.", parse_mode="HTML")
                    return web.json_response({"success": False, "error": "Tariff not configured"}, status=500)
                
                # Базовий тариф
                base_fare = max(
                    tariff.minimum,
                    tariff.base_fare + (distance_km * tariff.per_km) + (duration_minutes * tariff.per_minute)
                )
                
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
                
                # Показати класи з цінами
                from app.handlers.order import OrderStates
                await state.set_state(OrderStates.car_class)
                await state.update_data(base_fare=base_fare)
                
                kb_buttons = []
                for car_class_id, car_class_data in CAR_CLASSES.items():
                    class_fare = calculate_fare_with_class(base_fare, car_class_id, custom_multipliers)
                    final_fare, explanation, surge_mult = await calculate_dynamic_price(class_fare, client_city, online_count, 0)
                    
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
                pickup_address = data.get('pickup', '📍 Не вказано')
                if last_message_id:
                    try:
                        await bot.edit_message_text(
                            chat_id=user_id,
                            message_id=last_message_id,
                            text=f"✅ <b>Місце подачі:</b> {pickup_address}\n"
                                f"✅ <b>Призначення:</b> {address}\n\n"
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
                            f"✅ <b>Місце подачі:</b> {pickup_address}\n"
                            f"✅ <b>Призначення:</b> {address}\n\n"
                            f"📏 Відстань: {distance_km:.1f} км\n"
                            f"⏱ Час в дорозі: ~{int(duration_minutes)} хв\n\n"
                            f"🚗 <b>Оберіть клас автомобіля:</b>",
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                else:
                    await bot.send_message(
                        user_id,
                        f"✅ <b>Місце подачі:</b> {pickup_address}\n"
                        f"✅ <b>Призначення:</b> {address}\n\n"
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


def setup_webapp_api(app: web.Application, bot: Bot, config: AppConfig, storage) -> None:
    """
    Налаштувати API endpoints для WebApp
    """
    # Зберегти bot, storage і config в app для доступу в handlers
    app['bot'] = bot
    app['config'] = config
    app['storage'] = storage
    
    # Додати route
    app.router.add_post('/api/webapp/location', webapp_location_handler)
    
    logger.info("🌐 API endpoint registered: POST /api/webapp/location")
