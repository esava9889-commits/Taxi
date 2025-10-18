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
    get_user_active_order,
)
from app.utils.maps import get_distance_and_duration, geocode_address
from app.utils.privacy import mask_phone_number
from app.utils.validation import validate_address, validate_comment
from app.utils.rate_limiter import check_rate_limit, get_time_until_reset, format_time_remaining
from app.utils.order_timeout import start_order_timeout
from app.handlers.car_classes import CAR_CLASSES, calculate_fare_with_class

logger = logging.getLogger(__name__)


# Експортовані класи для використання в інших модулях
class OrderStates(StatesGroup):
    pickup = State()  # Спочатку звідки
    destination = State()  # Потім куди
    car_class = State()  # Після розрахунку - вибір класу (з цінами!)
    comment = State()  # Після вибору класу
    payment_method = State()  # Спосіб оплати
    confirm = State()


def create_router(config: AppConfig) -> Router:
    router = Router(name="order")

    CANCEL_TEXT = "❌ Скасувати"
    SKIP_TEXT = "⏩ Пропустити"
    CONFIRM_TEXT = "✅ Підтвердити"

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
    
    async def show_car_class_selection_with_prices(message: Message, state: FSMContext) -> None:
        """
        Розрахувати відстань, час та показати всі класи авто з цінами
        """
        data = await state.get_data()
        
        pickup_lat = data.get("pickup_lat")
        pickup_lon = data.get("pickup_lon")
        dest_lat = data.get("dest_lat")
        dest_lon = data.get("dest_lon")
        
        # Якщо є координати - розрахуємо точно
        distance_km = None
        duration_minutes = None
        
        if pickup_lat and pickup_lon and dest_lat and dest_lon and config.google_maps_api_key:
            logger.info(f"📏 Розраховую відстань: ({pickup_lat},{pickup_lon}) → ({dest_lat},{dest_lon})")
            result = await get_distance_and_duration(
                config.google_maps_api_key,
                pickup_lat, pickup_lon,
                dest_lat, dest_lon
            )
            if result:
                distance_m, duration_s = result  # API повертає МЕТРИ і СЕКУНДИ!
                distance_km = distance_m / 1000.0  # Конвертувати в км
                duration_minutes = duration_s / 60.0  # Конвертувати в хвилини
                await state.update_data(distance_km=distance_km, duration_minutes=duration_minutes)
                logger.info(f"✅ Відстань: {distance_km:.1f} км, час: {duration_minutes:.0f} хв (API: {distance_m}m, {duration_s}s)")
            else:
                logger.warning("⚠️ Не вдалося розрахувати відстань через Google Maps API")
        
        # Якщо не вдалося розрахувати - беремо приблизну відстань
        if distance_km is None:
            distance_km = 5.0  # Приблизна відстань за замовчуванням
            duration_minutes = 15
            await state.update_data(distance_km=distance_km, duration_minutes=duration_minutes)
            logger.warning(f"⚠️ Використовую приблизну відстань: {distance_km} км")
        
        # Отримати тариф
        tariff = await get_latest_tariff(config.database_path)
        if not tariff:
            await message.answer("❌ Помилка: тариф не налаштований. Зверніться до адміністратора.")
            await state.clear()
            return
        
        # Розрахувати базову ціну (для економ класу)
        base_fare = tariff.base_fare + (distance_km * tariff.per_km) + (duration_minutes * tariff.per_minute)
        if base_fare < tariff.minimum:
            base_fare = tariff.minimum
        
        # Розрахувати ЦІНУ З УРАХУВАННЯМ ДИНАМІКИ для КОЖНОГО класу
        car_class_prices = {}
        car_class_explanations = {}
        from app.handlers.dynamic_pricing import calculate_dynamic_price, get_surge_emoji
        from app.storage.db import get_online_drivers_count
        city = data.get('city', 'Київ') or 'Київ'
        online_count = await get_online_drivers_count(config.database_path, city)
        pending_orders_estimate = 5
        for class_key in ["economy", "standard", "comfort", "business"]:
            class_fare = calculate_fare_with_class(base_fare, class_key)
            final_price, explanation, total_mult = await calculate_dynamic_price(
                class_fare, city, online_count, pending_orders_estimate
            )
            car_class_prices[class_key] = round(final_price, 2)
            emoji = get_surge_emoji(total_mult)
            car_class_explanations[class_key] = (emoji, explanation)
        
        # Створити кнопки з цінами для кожного класу
        buttons = []
        for class_key in ["economy", "standard", "comfort", "business"]:
            class_info = CAR_CLASSES[class_key]
            class_name = class_info["name_uk"]
            class_price = car_class_prices[class_key]
            class_desc = class_info["description_uk"]
            
            emoji, explanation = car_class_explanations[class_key]
            button_text = f"{class_name} - {class_price:.0f} грн {emoji}"
            buttons.append([InlineKeyboardButton(
                text=button_text,
                callback_data=f"select_car_class:{class_key}"
            )])
        
        # Кнопка "Скасувати"
        buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        # Показати інформацію з цінами
        info_text = (
            f"📏 <b>Розрахунок маршруту:</b>\n\n"
            f"📍 Відстань: <b>{distance_km:.1f} км</b>\n"
            f"⏱ Час в дорозі: <b>~{duration_minutes:.0f} хв</b>\n\n"
            f"💰 <b>Оберіть клас авто:</b>\n\n"
            f"ℹ️ Ціни вже включають динамічні націнки/знижки (нічний тариф, попит).\n"
            f"Натисніть клас, ціна буде зафіксована."
        )
        
        await state.set_state(OrderStates.car_class)
        await message.answer(info_text, reply_markup=kb)

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
        
        # ЗАХИСТ: Перевірка чи є вже активне замовлення
        existing_order = await get_user_active_order(config.database_path, message.from_user.id)
        if existing_order:
            from app.handlers.keyboards import main_menu_keyboard
            is_admin = message.from_user.id in config.bot.admin_ids
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Скасувати поточне замовлення", callback_data=f"cancel_order:{existing_order.id}")]
                ]
            )
            
            status_emoji = {
                "pending": "⏳",
                "accepted": "✅",
                "in_progress": "🚗"
            }.get(existing_order.status, "📋")
            
            status_text = {
                "pending": "очікує на водія",
                "accepted": "прийнято водієм",
                "in_progress": "виконується"
            }.get(existing_order.status, existing_order.status)
            
            await message.answer(
                f"{status_emoji} <b>У вас вже є активне замовлення!</b>\n\n"
                f"📍 Звідки: {existing_order.pickup_address}\n"
                f"📍 Куди: {existing_order.destination_address}\n"
                f"📊 Статус: {status_text}\n\n"
                f"⚠️ <b>Не можна створити нове замовлення</b>\n"
                f"поки є активне.\n\n"
                f"Щоб зробити нове замовлення:\n"
                f"1. Скасуйте поточне замовлення ↓\n"
                f"2. Або дочекайтесь завершення",
                reply_markup=kb
            )
            logger.warning(f"User {message.from_user.id} намагається створити замовлення, але має активне #{existing_order.id}")
            return
        
        # RATE LIMITING: Перевірка ліміту замовлень (максимум 5 замовлень на годину)
        if not check_rate_limit(message.from_user.id, "create_order", max_requests=5, window_seconds=3600):
            time_until_reset = get_time_until_reset(message.from_user.id, "create_order", window_seconds=3600)
            await message.answer(
                "⏳ <b>Занадто багато замовлень</b>\n\n"
                f"Ви перевищили ліміт замовлень (максимум 5 на годину).\n\n"
                f"⏰ Спробуйте через: {format_time_remaining(time_until_reset)}\n\n"
                "ℹ️ Це обмеження захищає від спаму."
            )
            logger.warning(f"User {message.from_user.id} exceeded order rate limit")
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
        
        # СПОЧАТКУ адреса звідки
        await state.set_state(OrderStates.pickup)
        await message.answer(
            "📍 <b>Звідки вас забрати?</b>\n\n"
            "Надішліть адресу текстом або поділіться геолокацією 📍",
            reply_markup=location_keyboard("Вкажіть адресу подачі")
        )

    @router.callback_query(F.data == "show_car_classes")
    async def show_classes_callback(call: CallbackQuery, state: FSMContext) -> None:
        """Показати класи авто з цінами (викликається з saved_addresses)"""
        await call.answer()
        await show_car_class_selection_with_prices(call.message, state)
    
    @router.callback_query(F.data.startswith("select_car_class:"))
    async def select_car_class_handler(call: CallbackQuery, state: FSMContext) -> None:
        """Вибір класу авто після перегляду цін"""
        car_class = call.data.split(":", 1)[1]
        await state.update_data(car_class=car_class)
        await call.answer()
        
        # Отримати назву обраного класу
        from app.handlers.car_classes import get_car_class_name
        class_name = get_car_class_name(car_class)
        # Зафіксувати обрану суму (перерахунок як при відображенні)
        data = await state.get_data()
        tariff = await get_latest_tariff(config.database_path)
        distance_km = data.get("distance_km", 5.0)
        duration_minutes = data.get("duration_minutes", 15.0)
        base_fare = tariff.base_fare + (distance_km * tariff.per_km) + (duration_minutes * tariff.per_minute)
        if base_fare < tariff.minimum:
            base_fare = tariff.minimum
        from app.handlers.dynamic_pricing import calculate_dynamic_price
        from app.storage.db import get_online_drivers_count
        city = data.get('city', 'Київ') or 'Київ'
        online_count = await get_online_drivers_count(config.database_path, city)
        class_fare = calculate_fare_with_class(base_fare, car_class)
        final_price, explanation, total_mult = await calculate_dynamic_price(
            class_fare, city, online_count, 5
        )
        await state.update_data(estimated_fare=final_price, fare_explanation=explanation)

        # Перейти до коментаря
        await state.set_state(OrderStates.comment)
        await call.message.answer(
            f"✅ Обрано: <b>{class_name}</b>\n"
            f"💰 Вартість: <b>{final_price:.0f} грн</b>\n"
            f"Причини: \n{explanation if explanation else 'Базовий тариф'}\n\n"
            "💬 <b>Додайте коментар до замовлення</b> (опціонально):\n\n"
            "Наприклад: під'їзд 3, поверх 5, код домофону 123\n\n"
            "Або натисніть 'Пропустити'",
            reply_markup=skip_or_cancel_keyboard()
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
        
        # ВАЛІДАЦІЯ: Перевірка адреси
        is_valid, cleaned_address = validate_address(pickup, min_length=3, max_length=200)
        if not is_valid:
            await message.answer(
                "❌ <b>Невірний формат адреси</b>\n\n"
                "Адреса має містити:\n"
                "• Від 3 до 200 символів\n"
                "• Тільки допустимі символи\n\n"
                "Приклад: вул. Хрещатик, 15"
            )
            logger.warning(f"Invalid pickup address: {pickup}")
            return
        
        pickup = cleaned_address
        
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
        
        # Показати класи авто з цінами
        await show_car_class_selection_with_prices(message, state)

    @router.message(OrderStates.destination)
    async def destination_text(message: Message, state: FSMContext) -> None:
        destination = message.text.strip() if message.text else ""
        
        # ВАЛІДАЦІЯ: Перевірка адреси
        is_valid, cleaned_address = validate_address(destination, min_length=3, max_length=200)
        if not is_valid:
            await message.answer(
                "❌ <b>Невірний формат адреси</b>\n\n"
                "Адреса має містити:\n"
                "• Від 3 до 200 символів\n"
                "• Тільки допустимі символи\n\n"
                "Приклад: пр. Перемоги, 100"
            )
            logger.warning(f"Invalid destination address: {destination}")
            return
        
        destination = cleaned_address
        
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
        
        # Показати класи авто з цінами
        await show_car_class_selection_with_prices(message, state)

    @router.message(OrderStates.comment, F.text == SKIP_TEXT)
    async def skip_comment(message: Message, state: FSMContext) -> None:
        await state.update_data(comment=None)
        
        # Перейти до вибору способу оплати
        await state.set_state(OrderStates.payment_method)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💵 Готівка", callback_data="payment:cash")],
                [InlineKeyboardButton(text="💳 Картка", callback_data="payment:card")]
            ]
        )
        
        await message.answer(
            "💰 <b>Оберіть спосіб оплати:</b>\n\n"
            "💵 Готівка - розрахунок з водієм\n"
            "💳 Картка - переказ на картку водія",
            reply_markup=kb
        )

    @router.message(OrderStates.comment)
    async def save_comment(message: Message, state: FSMContext) -> None:
        comment = message.text.strip() if message.text else None
        
        # ВАЛІДАЦІЯ: Перевірка коментаря
        if comment:
            is_valid, cleaned_comment = validate_comment(comment, max_length=500)
            if not is_valid:
                await message.answer(
                    "❌ <b>Невірний формат коментаря</b>\n\n"
                    "Коментар має містити:\n"
                    "• Максимум 500 символів\n"
                    "• Тільки допустимі символи\n\n"
                    "Спробуйте ще раз або натисніть 'Пропустити'"
                )
                logger.warning(f"Invalid comment: {comment}")
                return
            comment = cleaned_comment
        
        await state.update_data(comment=comment)
        
        # Перейти до вибору способу оплати
        await state.set_state(OrderStates.payment_method)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💵 Готівка", callback_data="payment:cash")],
                [InlineKeyboardButton(text="💳 Картка", callback_data="payment:card")]
            ]
        )
        
        await message.answer(
            "💰 <b>Оберіть спосіб оплати:</b>\n\n"
            "💵 Готівка - розрахунок з водієм\n"
            "💳 Картка - переказ на картку водія",
            reply_markup=kb
        )

    @router.callback_query(F.data.startswith("payment:"))
    async def select_payment_method(call: CallbackQuery, state: FSMContext) -> None:
        """Вибір способу оплати"""
        payment_method = call.data.split(":")[1]  # cash або card
        await state.update_data(payment_method=payment_method)
        
        if payment_method == "card":
            await call.answer()
            await call.message.edit_text(
                "💳 <b>Оплата карткою</b>\n\n"
                "✅ Спосіб оплати обрано!\n\n"
                "📌 Картка водія з'явиться одразу після того,\n"
                "як він прийме ваше замовлення."
            )
        else:
            await call.answer()
            await call.message.edit_text(
                "💵 <b>Оплата готівкою</b>\n\n"
                "✅ Розрахунок з водієм після поїздки."
            )
        
        # Перейти до підтвердження
        await show_confirmation(call.message, state, config)
    
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
        
        # Якщо є координати - розрахувати відстань (ціна вже зафіксована в estimated_fare)
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
                    # Ціну вже було зафіксовано при виборі класу, не перераховуємо
                else:
                    logger.warning(f"❌ Google Maps Distance Matrix API не повернув результат")
            else:
                logger.warning(f"⚠️ Google Maps API не налаштований, відстань не розраховується")
        else:
            logger.warning(f"⚠️ Немає всіх координат для розрахунку: pickup({pickup_lat},{pickup_lon}), dest({dest_lat},{dest_lon})")
        
        from app.handlers.car_classes import get_car_class_name
        car_class_name = get_car_class_name(data.get('car_class', 'economy'))
        
        # Відобразити спосіб оплати, якщо вибрано
        payment_method = data.get('payment_method')
        payment_text = "💵 Готівка" if payment_method == "cash" else ("💳 Картка" if payment_method == "card" else None)

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
            f"💰 Вартість: {data.get('estimated_fare', 0):.0f} грн\n\n"
            + (f"💳 Оплата: {payment_text}\n\n" if payment_text else "")
            + "Все вірно?"
        )
        
        await state.set_state(OrderStates.confirm)
        await message.answer(text, reply_markup=confirm_keyboard())

    @router.message(OrderStates.confirm, F.text == CONFIRM_TEXT)
    async def confirm_order(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        
        data = await state.get_data()
        
        # Створення замовлення з координатами, відстанню, класом авто, ціною та способом оплати
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
            fare_amount=float(data.get("estimated_fare")) if data.get("estimated_fare") is not None else None,
            car_class=data.get("car_class", "economy"),
            payment_method=str(data.get("payment_method")) if data.get("payment_method") else "cash",
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
                        )],
                        [InlineKeyboardButton(
                            text="❌ Не можу взяти",
                            callback_data=f"reject_order:{order_id}"
                        )]
                    ]
                )
                
                # Додати інформацію про відстань якщо є
                distance_info = ""
                estimated_fare = None
                
                if data.get('distance_m'):
                    km = data.get('distance_m') / 1000.0
                    minutes = (data.get('duration_s') or 0) / 60.0
                    distance_info = f"📏 Відстань: {km:.1f} км (~{int(minutes)} хв)\n"
                    logger.info(f"📤 Відправка в групу: відстань {km:.1f} км")
                    
                    # Розрахунок з ТІЄЮ Ж ЛОГІКОЮ що і для клієнта
                    tariff = await get_latest_tariff(config.database_path)
                    if tariff:
                        # Базовий тариф
                        base_fare = max(
                            tariff.minimum,
                            tariff.base_fare + (km * tariff.per_km) + (minutes * tariff.per_minute)
                        )
                        
                        # Застосувати клас авто (ТАК ЯК ДЛЯ КЛІЄНТА!)
                        from app.handlers.car_classes import calculate_fare_with_class, get_car_class_name
                        car_class = data.get('car_class', 'economy')
                        class_fare = calculate_fare_with_class(base_fare, car_class)
                        
                        # Динамічне ціноутворення (ТАК ЯК ДЛЯ КЛІЄНТА!)
                        from app.handlers.dynamic_pricing import calculate_dynamic_price, get_surge_emoji
                        from app.storage.db import get_online_drivers_count
                        
                        city = data.get('city', 'Київ')
                        online_count = await get_online_drivers_count(config.database_path, city)
                        
                        # НЕ перераховуємо ціну — беремо зафіксовану
                        estimated_fare = data.get('estimated_fare') or class_fare
                        surge_mult = 1.0
                        
                        class_name = get_car_class_name(car_class)
                        surge_emoji = get_surge_emoji(surge_mult)
                        
                        if surge_mult != 1.0:
                            surge_percent = int((surge_mult - 1) * 100)
                            surge_text = f" {surge_emoji} +{surge_percent}%" if surge_percent > 0 else f" {surge_emoji} {surge_percent}%"
                            distance_info += f"💰 Вартість ({class_name}{surge_text}): {estimated_fare:.0f} грн\n"
                        else:
                            distance_info += f"💰 Вартість ({class_name}): {estimated_fare:.0f} грн\n"
                        
                        logger.info(f"💰 Відправка в групу: вартість {estimated_fare:.0f} грн (клас: {car_class}, surge: {surge_mult})")
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
                
                # Створити посилання на Google Maps
                pickup_lat = data.get('pickup_lat')
                pickup_lon = data.get('pickup_lon')
                dest_lat = data.get('dest_lat')
                dest_lon = data.get('dest_lon')
                
                pickup_link = ""
                dest_link = ""
                
                if pickup_lat and pickup_lon:
                    pickup_link = f"\n📍 <a href='https://www.google.com/maps?q={pickup_lat},{pickup_lon}'>Геолокація подачі (відкрити карту)</a>"
                
                if dest_lat and dest_lon:
                    dest_link = f"\n📍 <a href='https://www.google.com/maps?q={dest_lat},{dest_lon}'>Геолокація прибуття (відкрити карту)</a>"
                
                # БЕЗПЕКА: Маскуємо номер телефону в групі (показуємо тільки останні 2 цифри)
                masked_phone = mask_phone_number(str(data.get('phone', '')), show_last_digits=2)
                
                group_message = (
                    f"🔔 <b>НОВЕ ЗАМОВЛЕННЯ #{order_id}</b>\n\n"
                    f"🏙 Місто: {data.get('city')}\n"
                    f"🚗 Клас: {car_class_name}\n"
                    f"👤 Клієнт: {data.get('name')}\n"
                    f"📱 Телефон: <code>{masked_phone}</code> 🔒\n\n"
                    f"📍 Звідки: {data.get('pickup')}{pickup_link}\n"
                    f"📍 Куди: {data.get('destination')}{dest_link}\n"
                    f"{distance_info}\n"
                    f"💬 Коментар: {data.get('comment') or '—'}\n\n"
                    f"⏰ Час: {datetime.now(timezone.utc).strftime('%H:%M')}\n\n"
                    f"🏆 <i>Топ-водії вже отримали сповіщення</i>\n"
                    f"ℹ️ <i>Повний номер буде доступний після прийняття</i>"
                )
                
                sent_message = await message.bot.send_message(
                    config.driver_group_chat_id,
                    group_message,
                    reply_markup=kb,
                    disable_web_page_preview=True
                )
                
                # Зберегти ID повідомлення в БД
                await update_order_group_message(config.database_path, order_id, sent_message.message_id)
                
                logger.info(f"Order {order_id} sent to driver group {config.driver_group_chat_id}")
                
                # ЗАПУСТИТИ ТАЙМЕР: Якщо замовлення не прийнято за 3 хв - перепропонувати
                await start_order_timeout(
                    message.bot,
                    order_id,
                    config.database_path,
                    config.driver_group_chat_id,
                    sent_message.message_id
                )
                logger.info(f"⏱️ Таймер запущено для замовлення #{order_id}")
                
                # Відповідь клієнту
                from app.handlers.keyboards import main_menu_keyboard
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
                from app.handlers.keyboards import main_menu_keyboard
                is_admin = message.from_user.id in config.bot.admin_ids if message.from_user else False
                await message.answer(
                    f"⚠️ Замовлення #{order_id} створено, але виникла помилка при відправці водіям.\n"
                    "Зверніться до адміністратора.",
                    reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
                )
        else:
            # Якщо група не налаштована
            from app.handlers.keyboards import main_menu_keyboard
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
        
        from app.handlers.keyboards import main_menu_keyboard
        await message.answer(
            "❌ Замовлення скасовано.",
            reply_markup=main_menu_keyboard(is_registered=is_registered, is_admin=is_admin)
        )

    # Скасування замовлення клієнтом
    @router.callback_query(F.data.startswith("cancel_order:"))
    async def cancel_order_handler(call: CallbackQuery, state: FSMContext) -> None:
        if not call.from_user or not call.message:
            return
        
        order_id = int(call.data.split(":", 1)[1])
        
        # Перевірка що замовлення належить клієнту
        order = await get_order_by_id(config.database_path, order_id)
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        # Дозволити скасування якщо статус pending або accepted
        if order.status not in ["pending", "accepted"]:
            status_text = {
                "in_progress": "вже виконується",
                "completed": "вже завершене",
                "cancelled": "вже скасоване"
            }.get(order.status, f"має статус {order.status}")
            await call.answer(f"❌ Замовлення {status_text}, скасувати неможливо", show_alert=True)
            return
        
        # Скасувати замовлення
        success = await cancel_order_by_client(config.database_path, order_id, call.from_user.id)
        
        if success:
            await call.answer("✅ Замовлення скасовано")
            
            # Очистити FSM state якщо був в процесі створення
            await state.clear()
            
            # Отримати головне меню
            from app.handlers.keyboards import main_menu_keyboard
            user = await get_user_by_id(config.database_path, call.from_user.id)
            is_registered = user is not None and user.phone and user.city
            is_admin = call.from_user.id in config.bot.admin_ids
            
            # Оновити повідомлення клієнта
            await call.message.edit_text(
                "❌ <b>Замовлення скасовано</b>\n\n"
                f"📍 Звідки: {order.pickup_address}\n"
                f"📍 Куди: {order.destination_address}\n\n"
                "✅ Тепер ви можете створити нове замовлення."
            )
            
            # Надіслати головне меню
            await call.message.answer(
                "🏠 Головне меню:",
                reply_markup=main_menu_keyboard(is_registered=is_registered, is_admin=is_admin)
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
