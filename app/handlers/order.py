from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.config.config import AppConfig
from app.storage.db import (
    Order,
    insert_order,
    get_user_by_id,
    get_user_order_history,
    get_latest_tariff,
    update_order_group_message,
    cancel_order_by_client,
    get_order_by_id,
)
from app.utils.maps import get_distance_and_duration, geocode_address

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="order")

    CANCEL_TEXT = "❌ Скасувати"
    SKIP_TEXT = "⏩ Пропустити"
    CONFIRM_TEXT = "✅ Підтвердити"

    class OrderStates(StatesGroup):
        car_class = State()
        pickup = State()
        destination = State()
        comment = State()
        confirm = State()

    def cancel_keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=CANCEL_TEXT)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    def skip_or_cancel_keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=SKIP_TEXT)],
                [KeyboardButton(text=CANCEL_TEXT)]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    def confirm_keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=CONFIRM_TEXT)],
                [KeyboardButton(text=CANCEL_TEXT)]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    def location_keyboard(text: str) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
                [KeyboardButton(text="🎤 Голосом")],
                [KeyboardButton(text=CANCEL_TEXT)],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
            input_field_placeholder=text,
        )

    @router.message(F.text == "🚖 Замовити таксі")
    async def start_order(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        
        # Перевірка реєстрації
        user = await get_user_by_id(config.database_path, message.from_user.id)
        if not user or not user.phone or not user.city:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📱 Завершити реєстрацію", callback_data="register:start")]
                ]
            )
            await message.answer(
                "❌ Спочатку завершіть реєстрацію!\n\n"
                "Це потрібно щоб водій міг з вами зв'язатись.",
                reply_markup=kb
            )
            return
        
        # Зберігаємо дані користувача
        await state.update_data(
            user_id=message.from_user.id,
            name=user.full_name,
            phone=user.phone,
            city=user.city,
        )
        
        # Вибір класу авто
        from app.handlers.car_classes import CAR_CLASSES
        
        buttons = []
        for class_code, class_info in CAR_CLASSES.items():
            mult_percent = int((class_info['multiplier']-1)*100)
            mult_text = f" (+{mult_percent}%)" if mult_percent > 0 else ""
            buttons.append([
                InlineKeyboardButton(
                    text=f"{class_info['name_uk']}{mult_text}",
                    callback_data=f"order_car_class:{class_code}"
                )
            ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await state.set_state(OrderStates.car_class)
        await message.answer(
            "🚗 <b>Оберіть клас авто:</b>\n\n"
            "• 🚗 Економ - базовий тариф\n"
            "• 🚙 Стандарт - +30%\n"
            "• 🚘 Комфорт - +60%\n"
            "• 🏆 Бізнес - +100%",
            reply_markup=kb
        )

    @router.callback_query(F.data.startswith("order_car_class:"))
    async def save_order_car_class(call: CallbackQuery, state: FSMContext) -> None:
        car_class = call.data.split(":", 1)[1]
        await state.update_data(car_class=car_class)
        await state.set_state(OrderStates.pickup)
        
        from app.handlers.car_classes import get_car_class_name
        class_name = get_car_class_name(car_class)
        
        await call.answer()
        await call.message.answer(
            f"✅ Клас авто: {class_name}\n\n"
            "📍 <b>Звідки подати таксі?</b>\n\n"
            "Надішліть адресу або геолокацію",
            reply_markup=location_keyboard("Вкажіть адресу подачі")
        )

    @router.message(OrderStates.pickup, F.location)
    async def pickup_location(message: Message, state: FSMContext) -> None:
        if not message.location:
            return
        
        loc = message.location
        pickup = f"📍 {loc.latitude:.6f}, {loc.longitude:.6f}"
        await state.update_data(pickup=pickup, pickup_lat=loc.latitude, pickup_lon=loc.longitude)
        
        await state.set_state(OrderStates.destination)
        await message.answer(
            "✅ Місце подачі зафіксовано!\n\n"
            "📍 <b>Куди їдемо?</b>\n\n"
            "Надішліть адресу або геолокацію",
            reply_markup=location_keyboard("Вкажіть куди їхати")
        )

    @router.message(OrderStates.pickup, F.text == "🎤 Голосом")
    async def pickup_voice_instruction(message: Message, state: FSMContext) -> None:
        """Інструкція для голосового вводу"""
        await message.answer(
            "🎤 <b>Голосовий ввід адреси</b>\n\n"
            "Натисніть 🎤 в Telegram та чітко скажіть адресу:\n\n"
            "Приклад:\n"
            "🗣️ \"вулиця Хрещатик будинок п'ятнадцять\"\n"
            "🗣️ \"проспект Перемоги сто двадцять три\"\n\n"
            "⚠️ <i>Функція в бета-версії. Якщо не спрацює - введіть текстом.</i>"
        )
    
    @router.message(OrderStates.pickup)
    async def pickup_text(message: Message, state: FSMContext) -> None:
        pickup = message.text.strip() if message.text else ""
        if len(pickup) < 3:
            await message.answer("❌ Адреса занадто коротка. Вкажіть точніше.")
            return
        
        # Спроба геокодувати адресу в координати
        coords = None
        if config.google_maps_api_key:
            logger.info(f"🔍 Геокодую адресу: {pickup}")
            coords = await geocode_address(config.google_maps_api_key, pickup)
            if coords:
                lat, lon = coords
                await state.update_data(pickup=pickup, pickup_lat=lat, pickup_lon=lon)
                logger.info(f"✅ Геокодовано адресу: {pickup} → {lat},{lon}")
            else:
                logger.warning(f"❌ Не вдалося геокодувати адресу: {pickup}")
                await state.update_data(pickup=pickup)
                await message.answer(
                    "⚠️ Не вдалося визначити координати адреси.\n"
                    "Для точного розрахунку використовуйте геолокацію 📍"
                )
        else:
            logger.warning(f"⚠️ Google Maps API не налаштований, адреса не геокодується: {pickup}")
            await state.update_data(pickup=pickup)
        
        await state.set_state(OrderStates.destination)
        await message.answer(
            "✅ Місце подачі зафіксовано!\n\n"
            "📍 <b>Куди їдемо?</b>\n\n"
            "Надішліть адресу або геолокацію",
            reply_markup=location_keyboard("Вкажіть куди їхати")
        )

    @router.message(OrderStates.destination, F.location)
    async def destination_location(message: Message, state: FSMContext) -> None:
        if not message.location:
            return
        
        loc = message.location
        destination = f"📍 {loc.latitude:.6f}, {loc.longitude:.6f}"
        await state.update_data(
            destination=destination,
            dest_lat=loc.latitude,
            dest_lon=loc.longitude
        )
        
        await state.set_state(OrderStates.comment)
        await message.answer(
            "✅ Пункт призначення зафіксовано!\n\n"
            "💬 <b>Додайте коментар</b> (опціонально):\n\n"
            "Наприклад: під'їзд 3, поверх 5, код домофону 123\n\n"
            "Або натисніть 'Пропустити'",
            reply_markup=skip_or_cancel_keyboard()
        )

    @router.message(OrderStates.destination)
    async def destination_text(message: Message, state: FSMContext) -> None:
        destination = message.text.strip() if message.text else ""
        if len(destination) < 3:
            await message.answer("❌ Адреса занадто коротка. Вкажіть точніше.")
            return
        
        # Спроба геокодувати адресу в координати
        coords = None
        if config.google_maps_api_key:
            logger.info(f"🔍 Геокодую адресу: {destination}")
            coords = await geocode_address(config.google_maps_api_key, destination)
            if coords:
                lat, lon = coords
                await state.update_data(destination=destination, dest_lat=lat, dest_lon=lon)
                logger.info(f"✅ Геокодовано адресу: {destination} → {lat},{lon}")
            else:
                logger.warning(f"❌ Не вдалося геокодувати адресу: {destination}")
                await state.update_data(destination=destination)
                # Попередити користувача
                await message.answer(
                    "⚠️ Не вдалося визначити координати адреси.\n"
                    "Відстань буде розрахована приблизно.\n\n"
                    "Для точного розрахунку використовуйте геолокацію 📍"
                )
        else:
            logger.warning(f"⚠️ Google Maps API не налаштований, адреса не геокодується: {destination}")
            await state.update_data(destination=destination)
        
        await state.set_state(OrderStates.comment)
        await message.answer(
            "✅ Пункт призначення зафіксовано!\n\n"
            "💬 <b>Додайте коментар</b> (опціонально):\n\n"
            "Наприклад: під'їзд 3, поверх 5, код домофону 123\n\n"
            "Або натисніть 'Пропустити'",
            reply_markup=skip_or_cancel_keyboard()
        )

    @router.message(OrderStates.comment, F.text == SKIP_TEXT)
    async def skip_comment(message: Message, state: FSMContext) -> None:
        await state.update_data(comment=None)
        await show_confirmation(message, state, config)

    @router.message(OrderStates.comment)
    async def save_comment(message: Message, state: FSMContext) -> None:
        comment = message.text.strip() if message.text else None
        await state.update_data(comment=comment)
        await show_confirmation(message, state, config)

    async def show_confirmation(message: Message, state: FSMContext, config: AppConfig) -> None:
        data = await state.get_data()
        
        # Розрахунок відстані і вартості
        pickup_lat = data.get('pickup_lat')
        pickup_lon = data.get('pickup_lon')
        dest_lat = data.get('dest_lat')
        dest_lon = data.get('dest_lon')
        
        distance_text = ""
        fare_estimate = ""
        
        # Якщо немає координат але є текстові адреси - геокодувати
        if (not pickup_lat or not dest_lat) and config.google_maps_api_key:
            pickup_addr = data.get('pickup')
            dest_addr = data.get('destination')
            
            if pickup_addr and dest_addr and '📍' not in str(pickup_addr):
                # Геокодувати адреси
                pickup_coords = await geocode_address(config.google_maps_api_key, str(pickup_addr))
                dest_coords = await geocode_address(config.google_maps_api_key, str(dest_addr))
                
                if pickup_coords and dest_coords:
                    pickup_lat, pickup_lon = pickup_coords
                    dest_lat, dest_lon = dest_coords
                    await state.update_data(
                        pickup_lat=pickup_lat, pickup_lon=pickup_lon,
                        dest_lat=dest_lat, dest_lon=dest_lon
                    )
        
        # Якщо є координати - розрахувати відстань
        if pickup_lat and pickup_lon and dest_lat and dest_lon:
            if config.google_maps_api_key:
                logger.info(f"📏 Розраховую відстань: ({pickup_lat},{pickup_lon}) → ({dest_lat},{dest_lon})")
                result = await get_distance_and_duration(
                    config.google_maps_api_key,
                    pickup_lat, pickup_lon,
                    dest_lat, dest_lon
                )
                if result:
                    distance_m, duration_s = result
                    # Зберегти в state для пізнішого використання
                    await state.update_data(distance_m=distance_m, duration_s=duration_s)
                    
                    km = distance_m / 1000.0
                    minutes = duration_s / 60.0
                    distance_text = f"📏 Відстань: {km:.1f} км (~{int(minutes)} хв)\n\n"
                    logger.info(f"✅ Розраховано відстань: {km:.1f} км, {int(minutes)} хв")
                    
                    # Розрахунок орієнтовної вартості з урахуванням класу
                    tariff = await get_latest_tariff(config.database_path)
                    if tariff:
                        base_fare = max(
                            tariff.minimum,
                            tariff.base_fare + (km * tariff.per_km) + (minutes * tariff.per_minute)
                        )
                        
                        # Застосувати множник класу авто
                        from app.handlers.car_classes import calculate_fare_with_class, get_car_class_name
                        car_class = data.get('car_class', 'economy')
                        class_fare = calculate_fare_with_class(base_fare, car_class)
                        
                        # Динамічне ціноутворення
                        from app.handlers.dynamic_pricing import calculate_dynamic_price, get_surge_emoji
                        from app.storage.db import get_online_drivers_count
                        
                        city = data.get('city', 'Київ')
                        online_count = await get_online_drivers_count(config.database_path, city)
                        
                        estimated_fare, surge_reason, surge_mult = await calculate_dynamic_price(
                            class_fare, city, online_count, 5  # 5 pending orders (приблизно)
                        )
                        
                        class_name = get_car_class_name(car_class)
                        surge_emoji = get_surge_emoji(surge_mult)
                        
                        if surge_mult != 1.0:
                            surge_percent = int((surge_mult - 1) * 100)
                            surge_text = f" {surge_emoji} +{surge_percent}%" if surge_percent > 0 else f" {surge_emoji} {surge_percent}%"
                            fare_estimate = f"💰 Орієнтовна вартість ({class_name}{surge_text}): {estimated_fare:.0f} грн\n"
                            if surge_reason:
                                fare_estimate += f"<i>{surge_reason}</i>\n\n"
                        else:
                            fare_estimate = f"💰 Орієнтовна вартість ({class_name}): {estimated_fare:.0f} грн\n\n"
                        
                        logger.info(f"💰 Розрахована вартість: {estimated_fare:.0f} грн (клас: {car_class}, surge: {surge_mult})")
                else:
                    logger.warning(f"❌ Google Maps Distance Matrix API не повернув результат")
            else:
                logger.warning(f"⚠️ Google Maps API не налаштований, відстань не розраховується")
        else:
            logger.warning(f"⚠️ Немає всіх координат для розрахунку: pickup({pickup_lat},{pickup_lon}), dest({dest_lat},{dest_lon})")
        
        from app.handlers.car_classes import get_car_class_name
        car_class_name = get_car_class_name(data.get('car_class', 'economy'))
        
        text = (
            "📋 <b>Перевірте дані замовлення:</b>\n\n"
            f"👤 Клієнт: {data.get('name')}\n"
            f"📱 Телефон: {data.get('phone')}\n"
            f"🏙 Місто: {data.get('city')}\n"
            f"🚗 Клас: {car_class_name}\n\n"
            f"📍 Звідки: {data.get('pickup')}\n"
            f"📍 Куди: {data.get('destination')}\n"
            f"💬 Коментар: {data.get('comment') or '—'}\n\n"
            f"{distance_text}"
            f"{fare_estimate}"
            "Все вірно?"
        )
        
        await state.set_state(OrderStates.confirm)
        await message.answer(text, reply_markup=confirm_keyboard())

    @router.message(OrderStates.confirm, F.text == CONFIRM_TEXT)
    async def confirm_order(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        
        data = await state.get_data()
        
        # Створення замовлення з координатами, відстанню та класом авто
        order = Order(
            id=None,
            user_id=message.from_user.id,
            name=str(data.get("name")),
            phone=str(data.get("phone")),
            pickup_address=str(data.get("pickup")),
            destination_address=str(data.get("destination")),
            comment=data.get("comment"),
            created_at=datetime.now(timezone.utc),
            pickup_lat=data.get("pickup_lat"),
            pickup_lon=data.get("pickup_lon"),
            dest_lat=data.get("dest_lat"),
            dest_lon=data.get("dest_lon"),
            distance_m=data.get("distance_m"),
            duration_s=data.get("duration_s"),
            car_class=data.get("car_class", "economy"),
        )
        
        order_id = await insert_order(config.database_path, order)
        await state.clear()
        
        # Відправка замовлення у групу водіїв
        if config.driver_group_chat_id:
            try:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(
                            text="✅ Прийняти замовлення",
                            callback_data=f"accept_order:{order_id}"
                        )]
                    ]
                )
                
                # Додати інформацію про відстань якщо є
                distance_info = ""
                if data.get('distance_m'):
                    km = data.get('distance_m') / 1000.0
                    minutes = (data.get('duration_s') or 0) / 60.0
                    distance_info = f"📏 Відстань: {km:.1f} км (~{int(minutes)} хв)\n"
                    logger.info(f"📤 Відправка в групу: відстань {km:.1f} км")
                    
                    # Розрахунок орієнтовної вартості
                    tariff = await get_latest_tariff(config.database_path)
                    if tariff:
                        estimated_fare = max(
                            tariff.minimum,
                            tariff.base_fare + (km * tariff.per_km) + (minutes * tariff.per_minute)
                        )
                        distance_info += f"💰 Орієнтовна вартість: ~{estimated_fare:.0f} грн\n"
                        logger.info(f"💰 Відправка в групу: вартість ~{estimated_fare:.0f} грн")
                else:
                    logger.warning(f"⚠️ Відстань не розрахована, відправка в групу без distance_info")
                
                # Отримати онлайн водіїв для пріоритизації
                from app.storage.db import get_online_drivers
from app.handlers.driver_priority import get_top_drivers
                
                online_drivers = await get_online_drivers(config.database_path, data.get('city'))
                top_drivers = await get_top_drivers(config.database_path, online_drivers, limit=5)
                
                # Якщо є топ водії - надіслати їм особисто перші
                for driver in top_drivers[:3]:  # Топ 3 отримують особисто
                    from app.handlers.notifications import notify_driver_new_order
                    await notify_driver_new_order(
                        message.bot,
                        driver.tg_user_id,
                        order_id,
                        data.get('name'),
                        data.get('pickup'),
                        data.get('destination'),
                        (data.get('distance_m') / 1000.0) if data.get('distance_m') else None,
                        estimated_fare if 'estimated_fare' in locals() else None
                    )
                
                from app.handlers.car_classes import get_car_class_name
                car_class_name = get_car_class_name(data.get('car_class', 'economy'))
                
                group_message = (
                    f"🔔 <b>НОВЕ ЗАМОВЛЕННЯ #{order_id}</b>\n\n"
                    f"🏙 Місто: {data.get('city')}\n"
                    f"🚗 Клас: {car_class_name}\n"
                    f"👤 Клієнт: {data.get('name')}\n"
                    f"📱 Телефон: <code>{data.get('phone')}</code>\n\n"
                    f"📍 Звідки: {data.get('pickup')}\n"
                    f"📍 Куди: {data.get('destination')}\n"
                    f"{distance_info}\n"
                    f"💬 Коментар: {data.get('comment') or '—'}\n\n"
                    f"⏰ Час: {datetime.now(timezone.utc).strftime('%H:%M')}\n\n"
                    f"🏆 <i>Топ-водії вже отримали сповіщення</i>"
                )
                
                await message.bot.send_message(
                    config.driver_group_chat_id,
                    group_message,
                    reply_markup=kb
                )
                
                logger.info(f"Order {order_id} sent to driver group {config.driver_group_chat_id}")
                
                # Відповідь клієнту
                from app.handlers.start import main_menu_keyboard
                is_admin = message.from_user.id in config.bot.admin_ids if message.from_user else False
                await message.answer(
                    f"✅ <b>Замовлення #{order_id} прийнято!</b>\n\n"
                    "🔍 Шукаємо водія...\n\n"
                    "Ваше замовлення надіслано водіям.\n"
                    "Очікуйте підтвердження! ⏱",
                    reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
                )
                
            except Exception as e:
                logger.error(f"Failed to send order to group: {e}")
                from app.handlers.start import main_menu_keyboard
                is_admin = message.from_user.id in config.bot.admin_ids if message.from_user else False
                await message.answer(
                    f"⚠️ Замовлення #{order_id} створено, але виникла помилка при відправці водіям.\n"
                    "Зверніться до адміністратора.",
                    reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
                )
        else:
            # Якщо група не налаштована
            from app.handlers.start import main_menu_keyboard
            is_admin = message.from_user.id in config.bot.admin_ids if message.from_user else False
            await message.answer(
                f"✅ Замовлення #{order_id} створено!\n\n"
                "⚠️ Група водіїв не налаштована.\n"
                "Зверніться до адміністратора.",
                reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
            )

    @router.message(F.text == "📜 Мої замовлення")
    async def show_my_orders(message: Message) -> None:
        if not message.from_user:
            return
        
        orders = await get_user_order_history(config.database_path, message.from_user.id, limit=10)
        
        if not orders:
            await message.answer("📜 У вас поки немає замовлень.")
            return
        
        text = "📜 <b>Ваші останні замовлення:</b>\n\n"
        
        for o in orders:
            status_emoji = {
                "pending": "⏳ Очікує",
                "offered": "📤 Запропоновано",
                "accepted": "✅ Прийнято",
                "in_progress": "🚗 В дорозі",
                "completed": "✔️ Завершено",
                "cancelled": "❌ Скасовано",
            }.get(o.status, "❓")
            
            text += (
                f"<b>#{o.id}</b> - {status_emoji}\n"
                f"📍 {o.pickup_address[:30]}...\n"
                f"   → {o.destination_address[:30]}...\n"
            )
            if o.fare_amount:
                text += f"💰 {o.fare_amount:.0f} грн\n"
            text += f"📅 {o.created_at.strftime('%d.%m %H:%M')}\n\n"
        
        await message.answer(text)

    @router.message(F.text == CANCEL_TEXT)
    async def cancel(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        
        await state.clear()
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        is_registered = user is not None and user.phone and user.city
        is_admin = message.from_user.id in config.bot.admin_ids
        
        from app.handlers.start import main_menu_keyboard
        await message.answer(
            "❌ Замовлення скасовано.",
            reply_markup=main_menu_keyboard(is_registered=is_registered, is_admin=is_admin)
        )

    # Скасування замовлення клієнтом
    @router.callback_query(F.data.startswith("cancel_order:"))
    async def cancel_order_handler(call: CallbackQuery) -> None:
        if not call.from_user or not call.message:
            return
        
        order_id = int(call.data.split(":", 1)[1])
        
        # Перевірка що замовлення належить клієнту
        order = await get_order_by_id(config.database_path, order_id)
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        if order.status != "pending":
            await call.answer("❌ Замовлення вже прийнято водієм, скасувати неможливо", show_alert=True)
            return
        
        # Скасувати замовлення
        success = await cancel_order_by_client(config.database_path, order_id, call.from_user.id)
        
        if success:
            await call.answer("✅ Замовлення скасовано")
            
            # Оновити повідомлення клієнта
            await call.message.edit_text(
                "❌ <b>Замовлення скасовано</b>\n\n"
                "Ви скасували замовлення."
            )
            
            # Повідомити в групу водіїв
            if config.driver_group_chat_id and order.group_message_id:
                try:
                    await call.bot.edit_message_text(
                        "❌ <b>ЗАМОВЛЕННЯ СКАСОВАНО КЛІЄНТОМ</b>\n\n"
                        f"Замовлення #{order_id} скасовано клієнтом.",
                        chat_id=config.driver_group_chat_id,
                        message_id=order.group_message_id
                    )
                    logger.info(f"Order #{order_id} cancellation sent to group")
                except Exception as e:
                    logger.error(f"Failed to update group message about cancellation: {e}")
            
            logger.info(f"Order #{order_id} cancelled by client {call.from_user.id}")
        else:
            await call.answer("❌ Не вдалося скасувати замовлення", show_alert=True)
    
    return router
