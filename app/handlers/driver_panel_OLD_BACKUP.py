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
    set_driver_online_status,
    get_online_drivers_count,
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
        
        # Чайові (з обробкою помилок)
        tips_total = 0.0
        try:
            from app.storage.db import get_driver_tips_total
            tips_total = await get_driver_tips_total(config.database_path, message.from_user.id)
        except Exception as e:
            logger.error(f"Помилка отримання чайових: {e}")
        
        online_status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        location_status = "📍 Активна" if driver.last_lat and driver.last_lon else "❌ Не встановлена"
        
        # Підрахунок онлайн водіїв (з обробкою помилок)
        online_count = 0
        try:
            online_count = await get_online_drivers_count(config.database_path, driver.city)
        except Exception as e:
            logger.error(f"Помилка підрахунку онлайн водіїв: {e}")
        
        text = (
            f"🚗 <b>Панель водія</b>\n\n"
            f"Статус: {online_status}\n"
            f"Локація: {location_status}\n"
            f"ПІБ: {driver.full_name}\n"
            f"🏙 Місто: {driver.city or 'Не вказано'}\n"
            f"👥 Водіїв онлайн: {online_count}\n"
            f"🚙 Авто: {driver.car_make} {driver.car_model}\n"
            f"🔢 Номер: {driver.car_plate}\n\n"
            f"💰 Заробіток сьогодні: {earnings:.2f} грн\n"
            f"💸 Комісія до сплати: {commission_owed:.2f} грн\n"
            f"💵 Чистий заробіток: {net_earnings:.2f} грн\n"
            f"💝 Чайові (всього): {tips_total:.2f} грн\n\n"
            "ℹ️ Замовлення надходять у групу водіїв.\n"
            "Прийміть замовлення першим, щоб його отримати!\n\n"
            "💡 <i>Поділіться локацією щоб клієнти могли бачити де ви</i>"
        )
        
        # Інлайн кнопки для статусу та статистики
        inline_buttons = []
        
        # Велика кнопка статусу
        if driver.online:
            inline_buttons.append([
                InlineKeyboardButton(
                    text="🔴 ПІТИ В ОФЛАЙН", 
                    callback_data="driver:status:offline"
                )
            ])
        else:
            inline_buttons.append([
                InlineKeyboardButton(
                    text="🟢 ПОЧАТИ ПРАЦЮВАТИ", 
                    callback_data="driver:status:online"
                )
            ])
        
        inline_buttons.append([
            InlineKeyboardButton(text="📊 Статистика за період", callback_data="driver:stats:period")
        ])
        inline_buttons.append([
            InlineKeyboardButton(text="🔄 Оновити панель", callback_data="driver:refresh")
        ])
        
        inline_kb = InlineKeyboardMarkup(inline_keyboard=inline_buttons)
        
        # Кнопка для надсилання локації
        from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Поділитися локацією", request_location=True)],
                [KeyboardButton(text="📊 Мій заробіток"), KeyboardButton(text="💳 Комісія")],
                [KeyboardButton(text="📜 Історія поїздок"), KeyboardButton(text="📊 Розширена аналітика")],
                [KeyboardButton(text="👤 Кабінет клієнта"), KeyboardButton(text="ℹ️ Допомога")]
            ],
            resize_keyboard=True
        )
        
        # Спочатку відправити з inline кнопками
        await message.answer(text, reply_markup=inline_kb)
        # Потім окреме повідомлення з reply клавіатурою (щоб не перезаписувати inline)
        await message.answer(
            "👇 <b>Меню водія:</b>",
            reply_markup=kb
        )

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
                [InlineKeyboardButton(text="📱 Показати QR-код", callback_data=f"commission:qr:{unpaid_commission}")],
                [InlineKeyboardButton(text="✅ Я сплатив комісію", callback_data="commission:paid")]
            ]
        )
        
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data.startswith("commission:qr:"))
    async def show_qr_code(call: CallbackQuery) -> None:
        """Показати QR-код для оплати"""
        if not call.from_user:
            return
        
        amount = float(call.data.split(":", 2)[2])
        
        # Генерувати QR-код
        from app.utils.qr_generator import generate_payment_qr
        from aiogram.types import BufferedInputFile
        
        qr_image = generate_payment_qr(
            card_number=config.payment_card,
            amount=amount,
            comment=f"Комісія водія {call.from_user.id}"
        )
        
        photo = BufferedInputFile(qr_image.read(), filename="payment_qr.png")
        
        await call.answer()
        await call.bot.send_photo(
            call.from_user.id,
            photo=photo,
            caption=(
                f"📱 <b>QR-код для оплати</b>\n\n"
                f"💰 Сума: {amount:.2f} грн\n"
                f"💳 Картка: <code>{config.payment_card}</code>\n\n"
                f"Відскануйте QR-код у вашому банківському додатку"
            )
        )

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
            
            # Розрахувати ETA
            eta_minutes = None
            if driver.last_lat and driver.last_lon and order.pickup_lat and order.pickup_lon and config.google_maps_api_key:
                result = await get_distance_and_duration(
                    config.google_maps_api_key,
                    driver.last_lat, driver.last_lon,
                    order.pickup_lat, order.pickup_lon
                )
                if result:
                    _, duration_s = result
                    eta_minutes = int(duration_s / 60.0)
            
            # Повідомити клієнта (використовуємо нову систему сповіщень)
            from app.handlers.notifications import notify_client_driver_accepted
            await notify_client_driver_accepted(
                call.bot,
                order.user_id,
                order_id,
                driver.full_name,
                f"{driver.car_make} {driver.car_model}",
                driver.car_plate,
                driver.phone,
                eta_minutes
            )
            
            # Замінити повідомлення в групі на "вже виконується"
            if call.message:
                try:
                    await call.message.edit_text(
                        f"✅ <b>ЗАМОВЛЕННЯ #{order_id} ВЖЕ ВИКОНУЄТЬСЯ</b>\n\n"
                        f"👤 Водій: {driver.full_name}\n"
                        f"🚙 {driver.car_make} {driver.car_model} ({driver.car_plate})\n"
                        f"📱 {driver.phone}",
                        reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text="🚗 Почати поїздку", callback_data=f"start_trip:{order_id}")],
                                [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"cancel_trip:{order_id}")]
                            ]
                        )
                    )
                    logger.info(f"Group message updated: order {order_id} is now being executed")
                except Exception as e:
                    logger.error(f"Failed to edit group message: {e}")
            
            logger.info(f"Driver {driver.id} accepted order {order_id}")
        else:
            await call.answer("❌ Не вдалося прийняти замовлення. Можливо його вже прийняли.", show_alert=True)
            
            # Якщо не вдалося прийняти - показати що вже зайнято
            if call.message:
                try:
                    await call.message.edit_text(
                        "⚠️ <b>ЗАМОВЛЕННЯ ВЖЕ ВИКОНУЄТЬСЯ ІНШИМ ВОДІЄМ</b>\n\n"
                        "Це замовлення вже прийняте іншим водієм.",
                        reply_markup=None
                    )
                except Exception as e:
                    logger.error(f"Failed to update group message: {e}")

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
            
            # Повідомити клієнта (використовуємо нову систему)
            from app.handlers.notifications import notify_client_trip_started
            await notify_client_trip_started(
                call.bot,
                order.user_id,
                order_id,
                order.destination_address
            )
            
            # Оновити кнопки
            if call.message:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="📍 Я на місці", callback_data=f"driver_arrived:{order_id}")],
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
            
            # Повідомити клієнта (використовуємо нову систему)
            from app.handlers.notifications import notify_client_trip_completed
            await notify_client_trip_completed(
                call.bot,
                order.user_id,
                order_id,
                driver.tg_user_id,
                fare,
                km,
                int(minutes)
            )
            
            # Запропонувати оцінити клієнта
            kb_rate_client = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⭐️ Оцінити клієнта", callback_data=f"rate:client:{order_id}")]
                ]
            )
            
            try:
                await call.bot.send_message(
                    call.from_user.id,
                    f"✅ <b>Поїздку завершено!</b>\n\n"
                    f"💰 Ви заробили: {fare:.2f} грн\n"
                    f"💸 Комісія: {commission:.2f} грн\n\n"
                    "Оцініть клієнта:",
                    reply_markup=kb_rate_client
                )
            except Exception as e:
                logger.error(f"Failed to ask driver to rate client: {e}")
            
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

    # Онлайн/Офлайн статус
    @router.callback_query(F.data == "driver:status:online")
    async def set_online(call: CallbackQuery) -> None:
        """Увімкнути онлайн статус"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        await set_driver_online_status(config.database_path, driver.id, True)
        
        online_count = await get_online_drivers_count(config.database_path, driver.city)
        
        await call.answer(f"✅ Ви онлайн! Водіїв онлайн у {driver.city}: {online_count}", show_alert=True)
        
        # Оновити повідомлення з новим статусом
        updated_text = call.message.text.replace("🔴 Офлайн", "🟢 Онлайн")
        
        await call.message.edit_text(
            updated_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔴 ПІТИ В ОФЛАЙН", callback_data="driver:status:offline")],
                    [InlineKeyboardButton(text="📊 Статистика за період", callback_data="driver:stats:period")],
                    [InlineKeyboardButton(text="🔄 Оновити панель", callback_data="driver:refresh")]
                ]
            )
        )
    
    @router.callback_query(F.data == "driver:status:offline")
    async def set_offline(call: CallbackQuery) -> None:
        """Вимкнути онлайн статус"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        await set_driver_online_status(config.database_path, driver.id, False)
        
        await call.answer("🔴 Ви офлайн. Ви не отримуватимете нові замовлення.", show_alert=True)
        
        # Оновити повідомлення з новим статусом
        updated_text = call.message.text.replace("🟢 Онлайн", "🔴 Офлайн")
        
        await call.message.edit_text(
            updated_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🟢 ПОЧАТИ ПРАЦЮВАТИ", callback_data="driver:status:online")],
                    [InlineKeyboardButton(text="📊 Статистика за період", callback_data="driver:stats:period")],
                    [InlineKeyboardButton(text="🔄 Оновити панель", callback_data="driver:refresh")]
                ]
            )
        )
    
    # Оновити панель
    @router.callback_query(F.data == "driver:refresh")
    async def refresh_panel(call: CallbackQuery) -> None:
        """Оновити панель водія"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.status != "approved":
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        earnings, commission_owed = await get_driver_earnings_today(config.database_path, call.from_user.id)
        net_earnings = earnings - commission_owed
        
        # Чайові
        from app.storage.db import get_driver_tips_total
        tips_total = await get_driver_tips_total(config.database_path, call.from_user.id)
        
        online_status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        location_status = "📍 Активна" if driver.last_lat and driver.last_lon else "❌ Не встановлена"
        
        # Підрахунок онлайн водіїв
        online_count = await get_online_drivers_count(config.database_path, driver.city)
        
        text = (
            f"🚗 <b>Панель водія</b>\n\n"
            f"Статус: {online_status}\n"
            f"Локація: {location_status}\n"
            f"ПІБ: {driver.full_name}\n"
            f"🏙 Місто: {driver.city or 'Не вказано'}\n"
            f"👥 Водіїв онлайн: {online_count}\n"
            f"🚙 Авто: {driver.car_make} {driver.car_model}\n"
            f"🔢 Номер: {driver.car_plate}\n\n"
            f"💰 Заробіток сьогодні: {earnings:.2f} грн\n"
            f"💸 Комісія до сплати: {commission_owed:.2f} грн\n"
            f"💵 Чистий заробіток: {net_earnings:.2f} грн\n"
            f"💝 Чайові (всього): {tips_total:.2f} грн\n\n"
            "ℹ️ Замовлення надходять у групу водіїв.\n"
            "Прийміть замовлення першим, щоб його отримати!\n\n"
            "💡 <i>Поділіться локацією щоб клієнти могли бачити де ви</i>"
        )
        
        # Кнопки
        inline_buttons = []
        if driver.online:
            inline_buttons.append([
                InlineKeyboardButton(text="🔴 ПІТИ В ОФЛАЙН", callback_data="driver:status:offline")
            ])
        else:
            inline_buttons.append([
                InlineKeyboardButton(text="🟢 ПОЧАТИ ПРАЦЮВАТИ", callback_data="driver:status:online")
            ])
        
        inline_buttons.append([
            InlineKeyboardButton(text="📊 Статистика за період", callback_data="driver:stats:period")
        ])
        inline_buttons.append([
            InlineKeyboardButton(text="🔄 Оновити панель", callback_data="driver:refresh")
        ])
        
        await call.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_buttons)
        )
        await call.answer("✅ Оновлено!")
    
    # Статистика за період
    @router.callback_query(F.data == "driver:stats:period")
    async def show_period_stats(call: CallbackQuery) -> None:
        """Показати вибір періоду для статистики"""
        if not call.from_user:
            return
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📅 Сьогодні", callback_data="driver:stats:today"),
                    InlineKeyboardButton(text="📅 Тиждень", callback_data="driver:stats:week")
                ],
                [
                    InlineKeyboardButton(text="📅 Місяць", callback_data="driver:stats:month"),
                    InlineKeyboardButton(text="📅 Весь час", callback_data="driver:stats:all")
                ]
            ]
        )
        
        await call.answer()
        await call.message.answer("📊 <b>Виберіть період:</b>", reply_markup=kb)
    
    @router.callback_query(F.data.startswith("driver:stats:"))
    async def show_stats_for_period(call: CallbackQuery) -> None:
        """Показати статистику за обраний період"""
        if not call.from_user:
            return
        
        period = call.data.split(":")[-1]
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        # Розрахунок дат періоду
        from datetime import datetime, timedelta
        now = datetime.now(timezone.utc)
        
        if period == "today":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            period_name = "Сьогодні"
        elif period == "week":
            start_date = now - timedelta(days=7)
            period_name = "Тиждень"
        elif period == "month":
            start_date = now - timedelta(days=30)
            period_name = "Місяць"
        else:  # all
            start_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
            period_name = "Весь час"
        
        # Отримати замовлення за період
        orders = await get_driver_order_history(config.database_path, call.from_user.id, limit=1000)
        
        # Фільтрувати за періодом
        period_orders = [o for o in orders if o.created_at >= start_date and o.status == 'completed']
        
        if not period_orders:
            await call.answer()
            await call.message.answer(
                f"📊 <b>Статистика: {period_name}</b>\n\n"
                "📭 Немає завершених поїздок за цей період"
            )
            return
        
        # Розрахунки
        total_earnings = sum(o.fare_amount or 0 for o in period_orders)
        total_commission = sum(o.commission or 0 for o in period_orders)
        net_earnings = total_earnings - total_commission
        total_distance = sum(o.distance_m or 0 for o in period_orders) / 1000  # км
        avg_fare = total_earnings / len(period_orders) if period_orders else 0
        
        # Підрахунок по днях
        from collections import defaultdict
        daily_earnings = defaultdict(float)
        for order in period_orders:
            day = order.created_at.strftime('%d.%m')
            daily_earnings[day] += order.fare_amount or 0
        
        # Графік (ASCII)
        graph = ""
        if daily_earnings:
            max_earning = max(daily_earnings.values())
            for day, earning in sorted(daily_earnings.items())[-7:]:  # Останні 7 днів
                bar_length = int((earning / max_earning) * 20) if max_earning > 0 else 0
                graph += f"{day}: {'█' * bar_length} {earning:.0f} грн\n"
        
        text = (
            f"📊 <b>Статистика: {period_name}</b>\n\n"
            f"💰 Заробіток: {total_earnings:.2f} грн\n"
            f"💸 Комісія: {total_commission:.2f} грн\n"
            f"💵 Чистий: {net_earnings:.2f} грн\n\n"
            f"📊 Поїздок: {len(period_orders)}\n"
            f"💵 Середній чек: {avg_fare:.2f} грн\n"
            f"📏 Пробіг: {total_distance:.1f} км\n\n"
        )
        
        if graph:
            text += f"📈 <b>Графік заробітку:</b>\n<code>{graph}</code>"
        
        await call.answer()
        await call.message.answer(text)
    
    return router
