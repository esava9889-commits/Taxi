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
        storage = bot.fsm.storage
        
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
            if location_type == 'pickup':
                from app.handlers.order import OrderStates
                await state.set_state(OrderStates.destination)
                
                await bot.send_message(
                    user_id,
                    f"✅ <b>Місце подачі:</b>\n📍 {address}\n\n"
                    f"📍 <b>Куди їдемо?</b>\n\n"
                    f"💡 Оберіть спосіб:",
                    parse_mode="HTML"
                )
            else:  # destination
                await bot.send_message(
                    user_id,
                    f"✅ <b>Місце призначення:</b>\n📍 {address}\n\n"
                    f"⏳ Розраховую вартість поїздки...",
                    parse_mode="HTML"
                )
                
                # Викликати функцію розрахунку вартості
                # (це буде зроблено в наступному кроці)
                
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


def setup_webapp_api(app: web.Application, bot: Bot, config: AppConfig) -> None:
    """
    Налаштувати API endpoints для WebApp
    """
    # Зберегти bot в app для доступу в handlers
    app['bot'] = bot
    app['config'] = config
    
    # Додати route
    app.router.add_post('/api/webapp/location', webapp_location_handler)
    
    logger.info("🌐 API endpoint registered: POST /api/webapp/location")
