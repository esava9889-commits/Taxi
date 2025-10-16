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
    get_driver_by_tg_user_id,
    get_driver_by_id,
    get_order_by_id,
    accept_order,
    start_order,
    complete_order,
    get_driver_earnings_today,
    get_driver_unpaid_commission,
    get_driver_order_history,
    mark_commission_paid,
    Payment,
    insert_payment,
    get_latest_tariff,
    update_driver_location,
)
from app.utils.maps import generate_static_map_url, get_distance_and_duration

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="driver_panel")

    @router.message(F.text == "🚗 Панель водія")
    async def driver_menu(message: Message) -> None:
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            await message.answer(
                "❌ Ви не зареєстровані як водій або ваша заявка ще не підтверджена.\n\n"
                "Використайте кнопку '🚗 Стати водієм' для подання заявки."
            )
            return
        
        earnings, commission_owed = await get_driver_earnings_today(config.database_path, message.from_user.id)
        net_earnings = earnings - commission_owed
        
        online_status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        
        text = (
            f"🚗 <b>Панель водія</b>\n\n"
            f"Статус: {online_status}\n"
            f"ПІБ: {driver.full_name}\n"
            f"🏙 Місто: {driver.city or 'Не вказано'}\n"
            f"🚙 Авто: {driver.car_make} {driver.car_model}\n"
            f"🔢 Номер: {driver.car_plate}\n\n"
            f"💰 Заробіток сьогодні: {earnings:.2f} грн\n"
            f"💸 Комісія до сплати: {commission_owed:.2f} грн\n"
            f"💵 Чистий заробіток: {net_earnings:.2f} грн\n\n"
            "ℹ️ Замовлення надходять у групу водіїв.\n"
            "Прийміть замовлення першим, щоб його отримати!"
        )
        
        await message.answer(text)

    @router.message(F.text == "📊 Мій заробіток")
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
        
        await message.answer(text)

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

    @router.message(F.text == "📜 Історія поїздок")
    async def show_driver_history(message: Message) -> None:
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            return
        
        orders = await get_driver_order_history(config.database_path, message.from_user.id, limit=10)
        
        if not orders:
            await message.answer("📜 У вас поки немає виконаних замовлень.")
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
                f"📍 {o.pickup_address[:25]}...\n"
                f"   → {o.destination_address[:25]}...\n"
            )
            if o.fare_amount:
                text += f"💰 {o.fare_amount:.2f} грн\n"
            text += f"📅 {o.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        await message.answer(text)

    # Обробник прийняття замовлення з групи
    @router.callback_query(F.data.startswith("accept_order:"))
    async def accept_order_from_group(call: CallbackQuery) -> None:
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.status != "approved":
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        order_id = int(call.data.split(":", 1)[1])
        
        order = await get_order_by_id(config.database_path, order_id)
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if order.status != "pending":
            await call.answer("❌ Замовлення вже прийнято іншим водієм", show_alert=True)
            return
        
        # Прийняти замовлення
        success = await accept_order(config.database_path, order_id, driver.id)
        
        if success:
            await call.answer("✅ Ви прийняли замовлення!", show_alert=True)
            
            # Повідомити клієнта з кнопкою відстеження
            try:
                tracking_kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="📍 Де водій?", callback_data=f"track_driver:{order_id}"),
                            InlineKeyboardButton(text="📞 Зателефонувати", url=f"tel:{driver.phone}")
                        ]
                    ]
                )
                await call.bot.send_message(
                    order.user_id,
                    f"🚗 <b>Водій знайдено!</b>\n\n"
                    f"👤 ПІБ: {driver.full_name}\n"
                    f"🚙 Авто: {driver.car_make} {driver.car_model}\n"
                    f"🔢 Номер: {driver.car_plate}\n"
                    f"📱 Телефон: <code>{driver.phone}</code>\n\n"
                    f"Водій їде до вас!",
                    reply_markup=tracking_kb
                )
            except Exception as e:
                logger.error(f"Failed to notify client {order.user_id}: {e}")
            
            # Оновити повідомлення в групі
            if call.message:
                try:
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🚗 Почати поїздку", callback_data=f"start_trip:{order_id}")],
                            [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"cancel_trip:{order_id}")]
                        ]
                    )
                    await call.message.edit_text(
                        f"{call.message.text}\n\n"
                        f"✅ <b>Прийнято водієм:</b> {driver.full_name}\n"
                        f"🚙 {driver.car_make} {driver.car_model} ({driver.car_plate})",
                        reply_markup=kb
                    )
                except Exception as e:
                    logger.error(f"Failed to edit group message: {e}")
            
            logger.info(f"Driver {driver.id} accepted order {order_id}")
        else:
            await call.answer("❌ Не вдалося прийняти замовлення. Можливо його вже прийняли.", show_alert=True)

    # Початок поїздки
    @router.callback_query(F.data.startswith("start_trip:"))
    async def start_trip(call: CallbackQuery) -> None:
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.status != "approved":
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        order_id = int(call.data.split(":", 1)[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.driver_id != driver.id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        success = await start_order(config.database_path, order_id, driver.id)
        
        if success:
            await call.answer("🚗 Поїздку розпочато!")
            
            # Повідомити клієнта
            try:
                await call.bot.send_message(
                    order.user_id,
                    "🚗 <b>Поїздку розпочато!</b>\n\n"
                    "Водій вже в дорозі. Приємної подорожі!"
                )
            except Exception as e:
                logger.error(f"Failed to notify client: {e}")
            
            # Оновити кнопки
            if call.message:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Завершити поїздку", callback_data=f"complete_trip:{order_id}")]
                    ]
                )
                await call.message.edit_reply_markup(reply_markup=kb)
        else:
            await call.answer("❌ Помилка", show_alert=True)

    # Завершення поїздки
    @router.callback_query(F.data.startswith("complete_trip:"))
    async def complete_trip(call: CallbackQuery) -> None:
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.status != "approved":
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        order_id = int(call.data.split(":", 1)[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.driver_id != driver.id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        # Розрахунок вартості
        tariff = await get_latest_tariff(config.database_path)
        if not tariff:
            await call.answer("❌ Тарифи не налаштовані", show_alert=True)
            return
        
        # Використовуємо РЕАЛЬНУ відстань з БД
        distance_m = order.distance_m if order.distance_m else 5000  # fallback
        duration_s = order.duration_s if order.duration_s else 600   # fallback
        
        # Якщо немає відстані в БД, але є координати - розрахувати зараз
        if not order.distance_m and order.pickup_lat and order.dest_lat and config.google_maps_api_key:
            from app.utils.maps import get_distance_and_duration as calc_distance
            result = await calc_distance(
                config.google_maps_api_key,
                order.pickup_lat, order.pickup_lon,
                order.dest_lat, order.dest_lon
            )
            if result:
                distance_m, duration_s = result
                logger.info(f"📏 Розраховано відстань для замовлення #{order_id}: {distance_m/1000:.1f} км")
        
        km = distance_m / 1000.0
        minutes = duration_s / 60.0
        
        fare = max(
            tariff.minimum,
            tariff.base_fare + (km * tariff.per_km) + (minutes * tariff.per_minute)
        )
        
        commission_rate = 0.02  # 2%
        commission = fare * commission_rate
        
        logger.info(f"Order #{order_id}: Distance={km:.1f}km, Duration={minutes:.0f}min, Fare={fare:.2f}грн")
        
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
            # Записати платіж
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
            
            # Повідомити клієнта
            try:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="⭐️ 5", callback_data=f"rate:driver:{driver.tg_user_id}:5:{order_id}"),
                            InlineKeyboardButton(text="⭐️ 4", callback_data=f"rate:driver:{driver.tg_user_id}:4:{order_id}"),
                        ],
                        [
                            InlineKeyboardButton(text="⭐️ 3", callback_data=f"rate:driver:{driver.tg_user_id}:3:{order_id}"),
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
            except Exception as e:
                logger.error(f"Failed to notify client: {e}")
            
            # Оновити повідомлення в групі
            if call.message:
                await call.message.edit_text(
                    f"{call.message.text}\n\n"
                    f"✔️ <b>ЗАВЕРШЕНО</b>\n"
                    f"💰 Вартість: {fare:.2f} грн\n"
                    f"💸 Комісія: {commission:.2f} грн"
                )
        else:
            await call.answer("❌ Помилка", show_alert=True)

    # Обробник кнопки "Де водій?"
    @router.callback_query(F.data.startswith("track_driver:"))
    async def track_driver_location(call: CallbackQuery) -> None:
        if not call.from_user or not call.message:
            return
        
        order_id = int(call.data.split(":", 1)[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or not order.driver_id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        # Отримати водія (driver_id це DB id, не tg_user_id)
        driver = await get_driver_by_id(config.database_path, order.driver_id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        # Перевірка що це замовлення належить клієнту
        if order.user_id != call.from_user.id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        # Якщо водій має координати
        if driver.last_lat and driver.last_lon and order.pickup_lat and order.pickup_lon:
            # Розрахувати відстань до клієнта
            distance_text = ""
            if config.google_maps_api_key:
                result = await get_distance_and_duration(
                    config.google_maps_api_key,
                    driver.last_lat, driver.last_lon,
                    order.pickup_lat, order.pickup_lon
                )
                if result:
                    distance_m, duration_s = result
                    km = distance_m / 1000.0
                    minutes = duration_s / 60.0
                    distance_text = f"\n\n📏 Відстань: {km:.1f} км\n⏱️ Прибуде через: ~{int(minutes)} хв"
            
            # Згенерувати карту
            if config.google_maps_api_key:
                map_url = generate_static_map_url(
                    config.google_maps_api_key,
                    driver.last_lat, driver.last_lon,
                    order.pickup_lat, order.pickup_lon,
                    width=600, height=400
                )
                
                # Посилання на Google Maps
                gmaps_link = f"https://www.google.com/maps/dir/?api=1&origin={driver.last_lat},{driver.last_lon}&destination={order.pickup_lat},{order.pickup_lon}&travelmode=driving"
                
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🗺️ Відкрити в Google Maps", url=gmaps_link)],
                        [InlineKeyboardButton(text="🔄 Оновити локацію", callback_data=f"track_driver:{order_id}")]
                    ]
                )
                
                # Надіслати карту
                try:
                    await call.bot.send_photo(
                        call.from_user.id,
                        photo=map_url,
                        caption=f"📍 <b>Локація водія</b>\n\n"
                                f"🚗 {driver.full_name}\n"
                                f"🚙 {driver.car_make} {driver.car_model} ({driver.car_plate})"
                                f"{distance_text}\n\n"
                                f"<i>Оновлено: {datetime.now().strftime('%H:%M:%S')}</i>",
                        reply_markup=kb
                    )
                    await call.answer("📍 Карта надіслана!")
                except Exception as e:
                    logger.error(f"Failed to send map: {e}")
                    # Fallback: просто посилання
                    await call.bot.send_message(
                        call.from_user.id,
                        f"📍 <b>Локація водія</b>\n\n"
                        f"🚗 {driver.full_name}{distance_text}\n\n"
                        f"🗺️ <a href='{gmaps_link}'>Відкрити в Google Maps</a>",
                        reply_markup=kb
                    )
                    await call.answer("📍 Локація надіслана!")
            else:
                await call.answer("⚠️ Google Maps API не налаштований", show_alert=True)
        else:
            await call.answer(
                "⚠️ Водій ще не надав свою локацію.\n"
                "Спробуйте пізніше або зателефонуйте водію.",
                show_alert=True
            )
    
    # Кнопка для водія щоб поділитися локацією
    @router.message(F.text == "📍 Поділитися локацією")
    async def share_location_button(message: Message) -> None:
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            return
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📍 Надіслати геолокацію", request_location=True)]
            ]
        )
        await message.answer(
            "📍 <b>Поділитися локацією</b>\n\n"
            "Надішліть свою поточну геолокацію, щоб клієнти могли бачити де ви.\n\n"
            "Натисніть кнопку нижче:",
            reply_markup=kb
        )
    
    # Обробка геолокації від водія
    @router.message(F.location)
    async def driver_location_update(message: Message) -> None:
        if not message.from_user or not message.location:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            return
        
        # Оновити локацію водія в БД
        await update_driver_location(
            config.database_path,
            message.from_user.id,
            message.location.latitude,
            message.location.longitude
        )
        
        await message.answer("✅ Локацію оновлено! Клієнти можуть бачити де ви.")

    return router
