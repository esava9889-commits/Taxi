from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

logger = logging.getLogger(__name__)

from app.config.config import AppConfig
from app.storage.db import (
    get_driver_by_tg_user_id,
    set_driver_online,
    update_driver_location,
    get_order_by_id,
    accept_order,
    reject_order,
    add_rejected_driver,
    get_rejected_drivers_for_order,
    start_order,
    complete_order,
    get_driver_earnings_today,
    get_driver_unpaid_commission,
    get_driver_order_history,
    mark_commission_paid,
    Payment,
    insert_payment,
    get_latest_tariff,
)


def driver_menu_keyboard(online: bool = False) -> ReplyKeyboardMarkup:
    status_btn = "🟢 Онлайн" if online else "🔴 Офлайн"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=status_btn), KeyboardButton(text="📊 Заробіток")],
            [KeyboardButton(text="📜 Історія"), KeyboardButton(text="💳 Комісія")],
            [KeyboardButton(text="📍 Оновити геолокацію", request_location=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Меню водія",
    )


def create_router(config: AppConfig) -> Router:
    router = Router(name="driver_panel")

    @router.message(Command("driver"))
    async def driver_menu(message: Message) -> None:
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            await message.answer(
                "❌ Ви не зареєстровані як водій або ваша заявка ще не підтверджена.\n"
                "Використайте /register_driver для реєстрації."
            )
            return
        
        earnings, commission_owed = await get_driver_earnings_today(config.database_path, message.from_user.id)
        net_earnings = earnings - commission_owed
        
        online_status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        
        text = (
            f"🚗 <b>Панель водія</b>\n\n"
            f"Статус: {online_status}\n"
            f"ПІБ: {driver.full_name}\n"
            f"Авто: {driver.car_make} {driver.car_model} ({driver.car_plate})\n\n"
            f"💰 Заробіток сьогодні: {earnings:.2f} грн\n"
            f"💸 Комісія до сплати: {commission_owed:.2f} грн\n"
            f"💵 Чистий заробіток: {net_earnings:.2f} грн"
        )
        
        await message.answer(text, reply_markup=driver_menu_keyboard(driver.online == 1))

    @router.message(F.text.in_(["🟢 Онлайн", "🔴 Офлайн"]))
    async def toggle_online_status(message: Message) -> None:
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            return
        
        new_status = not driver.online
        await set_driver_online(config.database_path, message.from_user.id, new_status)
        
        status_text = "🟢 Ви тепер ОНЛАЙН. Можете приймати замовлення!" if new_status else "🔴 Ви тепер ОФЛАЙН."
        await message.answer(status_text, reply_markup=driver_menu_keyboard(new_status))

    @router.message(F.location)
    async def update_location(message: Message) -> None:
        if not message.from_user or not message.location:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            return
        
        await update_driver_location(
            config.database_path, 
            message.from_user.id,
            message.location.latitude,
            message.location.longitude
        )
        await message.answer("✅ Геолокацію оновлено!", reply_markup=driver_menu_keyboard(driver.online == 1))

    @router.message(F.text == "📊 Заробіток")
    async def show_earnings(message: Message) -> None:
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            return
        
        earnings, commission_owed = await get_driver_earnings_today(config.database_path, message.from_user.id)
        net_earnings = earnings - commission_owed
        unpaid_commission = await get_driver_unpaid_commission(config.database_path, message.from_user.id)
        
        text = (
            "💰 <b>Калькулятор заробітку</b>\n\n"
            f"💵 Заробіток сьогодні: {earnings:.2f} грн\n"
            f"💸 Комісія сьогодні: {commission_owed:.2f} грн\n"
            f"💚 Чистий заробіток: {net_earnings:.2f} грн\n\n"
            f"⚠️ Всього несплаченої комісії: {unpaid_commission:.2f} грн\n\n"
            f"<i>Нагадування: Сплачуйте комісію щодня до 20:00</i>"
        )
        
        await message.answer(text, reply_markup=driver_menu_keyboard(driver.online == 1))

    @router.message(F.text == "💳 Комісія")
    async def show_commission(message: Message) -> None:
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            return
        
        unpaid_commission = await get_driver_unpaid_commission(config.database_path, message.from_user.id)
        
        text = (
            "💳 <b>Інформація про комісію</b>\n\n"
            f"⚠️ До сплати: {unpaid_commission:.2f} грн\n\n"
            f"📌 <b>Реквізити для переказу:</b>\n"
            f"<code>{config.payment_card}</code>\n\n"
            f"<i>Після переказу натисніть кнопку нижче</i>"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я сплатив комісію", callback_data="commission:paid")]
            ]
        )
        
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "commission:paid")
    async def mark_commission_as_paid(call: CallbackQuery) -> None:
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.status != "approved":
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        await mark_commission_paid(config.database_path, call.from_user.id)
        await call.answer("✅ Дякуємо! Комісію відмічено як сплачену.", show_alert=True)
        
        if call.message:
            await call.message.edit_text(
                "✅ <b>Комісію сплачено</b>\n\n"
                "Дякуємо за співпрацю!"
            )

    @router.message(F.text == "📜 Історія")
    async def show_driver_history(message: Message) -> None:
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            return
        
        orders = await get_driver_order_history(config.database_path, message.from_user.id, limit=10)
        
        if not orders:
            await message.answer("📜 У вас поки немає виконаних замовлень.", reply_markup=driver_menu_keyboard(driver.online == 1))
            return
        
        text = "📜 <b>Ваша історія замовлень:</b>\n\n"
        for o in orders:
            status_emoji = {
                "pending": "⏳",
                "offered": "📤",
                "accepted": "✅",
                "in_progress": "🚗",
                "completed": "✔️",
                "cancelled": "❌"
            }.get(o.status, "❓")
            
            text += (
                f"{status_emoji} <b>№{o.id}</b> ({o.status})\n"
                f"Маршрут: {o.pickup_address[:25]}... → {o.destination_address[:25]}...\n"
            )
            if o.fare_amount:
                text += f"Вартість: {o.fare_amount:.2f} грн\n"
            text += f"Дата: {o.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        await message.answer(text, reply_markup=driver_menu_keyboard(driver.online == 1))

    # Order callbacks for drivers
    @router.callback_query(F.data.startswith("order:"))
    async def handle_order_action(call: CallbackQuery) -> None:
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.status != "approved":
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        parts = (call.data or "").split(":")
        if len(parts) < 3:
            await call.answer("❌ Невірний формат", show_alert=True)
            return
        
        action = parts[1]
        order_id = int(parts[2])
        
        order = await get_order_by_id(config.database_path, order_id)
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if action == "accept":
            success = await accept_order(config.database_path, order_id, driver.id)
            if success:
                await call.answer("✅ Замовлення прийнято!")
                
                # Notify client
                try:
                    await call.bot.send_message(
                        order.user_id,
                        f"🚗 <b>Водій знайдено!</b>\n\n"
                        f"ПІБ: {driver.full_name}\n"
                        f"Авто: {driver.car_make} {driver.car_model}\n"
                        f"Номер: {driver.car_plate}\n"
                        f"Телефон: {driver.phone}\n\n"
                        f"Водій їде до вас!"
                    )
                except Exception:
                    pass
                
                # Update driver's message
                if call.message:
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🚗 Почати поїздку", callback_data=f"order:start:{order_id}")],
                            [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"order:cancel:{order_id}")]
                        ]
                    )
                    await call.message.edit_reply_markup(reply_markup=kb)
            else:
                await call.answer("❌ Не вдалося прийняти замовлення", show_alert=True)
        
        elif action == "reject":
            # Add current driver to rejected list
            await add_rejected_driver(config.database_path, order_id, driver.id)
            
            # Reject order (set back to pending)
            success = await reject_order(config.database_path, order_id)
            
            if success:
                await call.answer("❌ Ви відхилили замовлення")
                if call.message:
                    await call.message.edit_text("❌ Замовлення відхилено")
                
                # Try to offer to next driver
                try:
                    from app.utils.matching import find_nearest_driver, parse_geo_coordinates
                    
                    pickup_coords = parse_geo_coordinates(order.pickup_address)
                    if pickup_coords:
                        pickup_lat, pickup_lon = pickup_coords
                        
                        # Get list of drivers who already rejected
                        rejected_ids = await get_rejected_drivers_for_order(config.database_path, order_id)
                        
                        # Find next nearest driver (excluding rejected ones)
                        from app.storage.db import fetch_online_drivers
                        all_drivers = await fetch_online_drivers(config.database_path, limit=50)
                        
                        # Filter out rejected drivers and current driver
                        available_drivers = [
                            d for d in all_drivers 
                            if d.id not in rejected_ids and d.id != driver.id 
                            and d.last_lat is not None and d.last_lon is not None
                        ]
                        
                        if available_drivers:
                            # Find nearest
                            from app.utils.matching import calculate_distance
                            nearest = min(
                                available_drivers,
                                key=lambda d: calculate_distance(pickup_lat, pickup_lon, d.last_lat, d.last_lon)
                            )
                            
                            # Offer to next driver
                            from app.storage.db import offer_order_to_driver
                            offer_success = await offer_order_to_driver(config.database_path, order_id, nearest.id)
                            
                            if offer_success:
                                # Notify next driver
                                dest_coords = parse_geo_coordinates(order.destination_address)
                                distance_info = ""
                                
                                if dest_coords and config.google_maps_api_key:
                                    from app.utils.maps import get_distance_and_duration
                                    result = await get_distance_and_duration(
                                        config.google_maps_api_key,
                                        pickup_lat, pickup_lon,
                                        dest_coords[0], dest_coords[1]
                                    )
                                    if result:
                                        distance_m, duration_s = result
                                        distance_info = f"\n📍 Відстань: {distance_m/1000:.1f} км\n⏱ Час: ~{duration_s//60} хв"
                                
                                kb = InlineKeyboardMarkup(
                                    inline_keyboard=[
                                        [
                                            InlineKeyboardButton(text="✅ Прийняти", callback_data=f"order:accept:{order_id}"),
                                            InlineKeyboardButton(text="❌ Відхилити", callback_data=f"order:reject:{order_id}"),
                                        ]
                                    ]
                                )
                                
                                await call.bot.send_message(
                                    nearest.tg_user_id,
                                    f"🔔 <b>Нове замовлення #{order_id}</b>\n\n"
                                    f"👤 Клієнт: {order.name}\n"
                                    f"📱 Телефон: {order.phone}\n"
                                    f"📍 Звідки: {order.pickup_address}\n"
                                    f"📍 Куди: {order.destination_address}\n"
                                    f"{distance_info}\n"
                                    f"💬 Коментар: {order.comment or '—'}",
                                    reply_markup=kb
                                )
                                logger.info(f"Order {order_id} offered to next driver {nearest.id}")
                        else:
                            # No more drivers available
                            try:
                                await call.bot.send_message(
                                    order.user_id,
                                    "⚠️ На жаль, всі водії зайняті.\n"
                                    "Ваше замовлення в черзі, очікуйте будь ласка..."
                                )
                            except Exception as e:
                                logger.error(f"Failed to notify client {order.user_id}: {e}")
                            
                            logger.warning(f"No more drivers available for order {order_id}")
                
                except Exception as e:
                    logger.error(f"Error offering order to next driver: {e}")
            else:
                await call.answer("❌ Помилка при відхиленні", show_alert=True)
        
        elif action == "start":
            success = await start_order(config.database_path, order_id, driver.id)
            if success:
                await call.answer("🚗 Поїздку розпочато!")
                
                # Notify client
                try:
                    await call.bot.send_message(
                        order.user_id,
                        "🚗 <b>Поїздку розпочато!</b>\n\n"
                        "Водій вже в дорозі. Приємної подорожі!"
                    )
                except Exception:
                    pass
                
                # Update driver's message
                if call.message:
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="✅ Завершити поїздку", callback_data=f"order:complete:{order_id}")]
                        ]
                    )
                    await call.message.edit_reply_markup(reply_markup=kb)
            else:
                await call.answer("❌ Помилка", show_alert=True)
        
        elif action == "complete":
            # Calculate fare
            tariff = await get_latest_tariff(config.database_path)
            if not tariff:
                await call.answer("❌ Тарифи не налаштовані", show_alert=True)
                return
            
            # Simple calculation (can be enhanced with actual distance/time)
            distance_m = order.distance_m or 5000  # default 5km
            duration_s = order.duration_s or 600   # default 10 min
            
            km = distance_m / 1000.0
            minutes = duration_s / 60.0
            
            fare = max(
                tariff.minimum,
                tariff.base_fare + (km * tariff.per_km) + (minutes * tariff.per_minute)
            )
            
            commission_rate = 0.02  # 2% commission
            commission = fare * commission_rate
            
            success = await complete_order(
                config.database_path,
                order_id,
                driver.id,
                fare,
                distance_m,
                duration_s,
                commission
            )
            
            if success:
                # Record payment
                payment = Payment(
                    id=None,
                    order_id=order_id,
                    driver_id=driver.id,
                    amount=fare,
                    commission=commission,
                    commission_paid=False,
                    payment_method="cash",
                    created_at=datetime.now(timezone.utc)
                )
                await insert_payment(config.database_path, payment)
                
                await call.answer(f"✅ Поїздку завершено! Вартість: {fare:.2f} грн", show_alert=True)
                
                # Notify client
                try:
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(text="⭐️ 5", callback_data=f"rate:driver:{driver.tg_user_id}:5:{order_id}"),
                                InlineKeyboardButton(text="⭐️ 4", callback_data=f"rate:driver:{driver.tg_user_id}:4:{order_id}"),
                                InlineKeyboardButton(text="⭐️ 3", callback_data=f"rate:driver:{driver.tg_user_id}:3:{order_id}"),
                            ],
                            [
                                InlineKeyboardButton(text="⭐️ 2", callback_data=f"rate:driver:{driver.tg_user_id}:2:{order_id}"),
                                InlineKeyboardButton(text="⭐️ 1", callback_data=f"rate:driver:{driver.tg_user_id}:1:{order_id}"),
                            ]
                        ]
                    )
                    await call.bot.send_message(
                        order.user_id,
                        f"✅ <b>Поїздку завершено!</b>\n\n"
                        f"💰 Вартість: {fare:.2f} грн\n"
                        f"📍 Відстань: {km:.1f} км\n"
                        f"⏱ Час: {int(minutes)} хв\n\n"
                        f"Будь ласка, оцініть водія:",
                        reply_markup=kb
                    )
                except Exception:
                    pass
                
                # Update driver's message
                if call.message:
                    await call.message.edit_text(
                        f"✅ <b>Поїздку завершено!</b>\n\n"
                        f"Замовлення №{order_id}\n"
                        f"Вартість: {fare:.2f} грн\n"
                        f"Ваша комісія: {commission:.2f} грн\n"
                        f"Ваш заробіток: {fare - commission:.2f} грн"
                    )
            else:
                await call.answer("❌ Помилка", show_alert=True)

    return router
