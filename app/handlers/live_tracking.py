"""Живе відстеження водія"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config.config import AppConfig
from app.storage.db import (
    get_order_by_id,
    get_driver_by_id,
)
from app.utils.maps import get_distance_and_duration

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="live_tracking")

    @router.callback_query(F.data.startswith("live_track:"))
    async def start_live_tracking(call: CallbackQuery) -> None:
        """Почати живе відстеження водія"""
        if not call.from_user or not call.message:
            return
        
        order_id = int(call.data.split(":", 1)[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or not order.driver_id:
            await call.answer("❌ Водія ще не призначено", show_alert=True)
            return
        
        if order.user_id != call.from_user.id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        driver = await get_driver_by_id(config.database_path, order.driver_id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        await call.answer()
        
        # Відправити Live Location
        if driver.last_lat and driver.last_lon:
            try:
                # Надіслати живу локацію (оновлюється автоматично)
                sent_msg = await call.bot.send_location(
                    call.from_user.id,
                    latitude=driver.last_lat,
                    longitude=driver.last_lon,
                    live_period=900,  # 15 хвилин live tracking
                )
                
                # Розрахувати ETA
                eta_text = ""
                if order.pickup_lat and order.pickup_lon and config.google_maps_api_key:
                    result = await get_distance_and_duration(
                        config.google_maps_api_key,
                        driver.last_lat, driver.last_lon,
                        order.pickup_lat, order.pickup_lon
                    )
                    if result:
                        distance_m, duration_s = result
                        km = distance_m / 1000.0
                        minutes = int(duration_s / 60.0)
                        eta_text = f"\n\n📏 Відстань: {km:.1f} км\n⏱️ Прибуде через: ~{minutes} хв"
                
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(
                            text="🗺️ Відкрити в Google Maps",
                            url=f"https://www.google.com/maps/dir/?api=1&destination={driver.last_lat},{driver.last_lon}"
                        )],
                        [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"live_track:{order_id}")]
                    ]
                )
                
                await call.bot.send_message(
                    call.from_user.id,
                    f"📍 <b>Живе відстеження водія</b>\n\n"
                    f"🚗 {driver.full_name}\n"
                    f"🚙 {driver.car_make} {driver.car_model} ({driver.car_plate}){eta_text}\n\n"
                    f"<i>Локація оновлюється автоматично</i>",
                    reply_markup=kb
                )
                
            except Exception as e:
                logger.error(f"Failed to send live location: {e}")
                await call.message.answer("❌ Не вдалося почати відстеження")
        else:
            await call.message.answer(
                "⚠️ Водій ще не надав свою локацію.\n"
                "Спробуйте пізніше або зателефонуйте."
            )

    @router.callback_query(F.data.startswith("driver_arrived:"))
    async def driver_arrived(call: CallbackQuery) -> None:
        """Водій повідомляє що прибув"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":", 1)[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        # Перевірка що це водій цього замовлення
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.id != order.driver_id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        await call.answer()
        
        # Повідомити клієнта
        from app.handlers.notifications import notify_client_driver_arrived
        await notify_client_driver_arrived(
            call.bot,
            order.user_id,
            order_id,
            driver.full_name
        )
        
        await call.message.edit_text(
            f"{call.message.text}\n\n"
            f"✅ Клієнта повідомлено що ви на місці"
        )

    return router
