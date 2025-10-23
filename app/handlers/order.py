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
    increase_order_fare,
)
from app.utils.maps import get_distance_and_duration, geocode_address, reverse_geocode_with_places
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
        
        # Отримати налаштування множників з БД
        night_percent = tariff.night_tariff_percent if hasattr(tariff, 'night_tariff_percent') else 50.0
        weather_percent = tariff.weather_percent if hasattr(tariff, 'weather_percent') else 0.0
        
        for class_key in ["economy", "standard", "comfort", "business"]:
            class_fare = calculate_fare_with_class(base_fare, class_key)
            final_price, explanation, total_mult = await calculate_dynamic_price(
                class_fare, city, online_count, pending_orders_estimate, night_percent, weather_percent
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
        
        # Кнопки навігації
        buttons.append([InlineKeyboardButton(text="⬅️ Назад до адреси призначення", callback_data="order:back_to_destination")])
        buttons.append([InlineKeyboardButton(text="❌ Скасувати замовлення", callback_data="cancel_order")])
        
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
        
        # СПОЧАТКУ адреса звідки - ІНЛАЙН КНОПКИ ВИБОРУ
        await state.set_state(OrderStates.pickup)
        
        # Перевірити чи є збережені адреси
        from app.storage.db import get_user_saved_addresses
        saved_addresses = await get_user_saved_addresses(config.database_path, message.from_user.id)
        
        kb_buttons = [
            [InlineKeyboardButton(text="📍 Надіслати мою геолокацію", callback_data="order:pickup:send_location")],
            [InlineKeyboardButton(text="✏️ Ввести адресу текстом", callback_data="order:pickup:text")],
        ]
        
        if saved_addresses:
            kb_buttons.append([InlineKeyboardButton(text="📌 Вибрати зі збережених", callback_data="order:pickup:saved")])
        
        kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати замовлення", callback_data="cancel_order")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        msg = await message.answer(
            "🚖 <b>Замовлення таксі</b>\n\n"
            "📍 <b>Звідки вас забрати?</b>\n\n"
            "💡 Оберіть спосіб:",
            reply_markup=kb
        )
        
        # Зберегти message_id для подальшого редагування
        await state.update_data(last_message_id=msg.message_id)

    @router.callback_query(F.data == "order:pickup:send_location")
    async def pickup_request_location(call: CallbackQuery, state: FSMContext) -> None:
        """Попросити користувача надіслати геолокацію для pickup"""
        await call.answer()
        
        # Тут ПОТРІБЕН ReplyKeyboard для request_location
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        # Видалити попереднє повідомлення
        try:
            await call.message.delete()
        except:
            pass
        
        # Показати нове з ReplyKeyboard
        msg = await call.message.answer(
            "📍 Натисніть кнопку нижче, щоб надіслати вашу геолокацію:",
            reply_markup=kb
        )
        await state.update_data(last_message_id=msg.message_id)
    
    @router.callback_query(F.data == "order:pickup:text")
    async def pickup_request_text(call: CallbackQuery, state: FSMContext) -> None:
        """Попросити користувача ввести адресу текстом для pickup"""
        await call.answer()
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Скасувати замовлення", callback_data="cancel_order")]
            ]
        )
        
        await call.message.edit_text(
            "📍 <b>Звідки вас забрати?</b>\n\n"
            "✏️ Введіть адресу текстом:\n\n"
            "Наприклад: вул. Хрещатик, 1, Київ",
            reply_markup=kb
        )
    
    @router.callback_query(F.data == "order:pickup:saved")
    async def pickup_show_saved(call: CallbackQuery, state: FSMContext) -> None:
        """Показати збережені адреси для вибору pickup"""
        await call.answer()
        
        if not call.from_user:
            return
        
        from app.storage.db import get_user_saved_addresses
        addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
        
        if not addresses:
            await call.answer("У вас немає збережених адрес", show_alert=True)
            return
        
        buttons = []
        for addr in addresses:
            buttons.append([
                InlineKeyboardButton(
                    text=f"{addr.emoji} {addr.name}",
                    callback_data=f"order:pickup:use_saved:{addr.id}"
                )
            ])
        
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="order:pickup:back")])
        buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        text = "📍 <b>Оберіть адресу подачі:</b>\n\n"
        for addr in addresses:
            text += f"{addr.emoji} <b>{addr.name}</b>\n"
            text += f"   {addr.address[:45]}{'...' if len(addr.address) > 45 else ''}\n\n"
        
        await call.message.edit_text(text, reply_markup=kb)
    
    @router.callback_query(F.data.startswith("order:pickup:use_saved:"))
    async def pickup_use_saved_address(call: CallbackQuery, state: FSMContext) -> None:
        """Використати збережену адресу для pickup"""
        await call.answer()
        
        if not call.from_user:
            return
        
        addr_id = int(call.data.split(":", 3)[3])
        
        from app.storage.db import get_saved_address_by_id
        address = await get_saved_address_by_id(config.database_path, addr_id, call.from_user.id)
        
        if not address:
            await call.answer("❌ Адресу не знайдено", show_alert=True)
            return
        
        # Зберегти pickup
        await state.update_data(
            pickup=address.address,
            pickup_lat=address.lat,
            pickup_lon=address.lon
        )
        
        # Перейти до destination
        await state.set_state(OrderStates.destination)
        
        # Знову показати інлайн кнопки для destination
        from app.storage.db import get_user_saved_addresses
        saved_addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
        
        kb_buttons = [
            [InlineKeyboardButton(text="📍 Надіслати геолокацію", callback_data="order:dest:send_location")],
            [InlineKeyboardButton(text="✏️ Ввести адресу текстом", callback_data="order:dest:text")],
        ]
        
        if saved_addresses:
            kb_buttons.append([InlineKeyboardButton(text="📌 Вибрати зі збережених", callback_data="order:dest:saved")])
        
        kb_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="order:back:pickup")])
        kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        await call.message.edit_text(
            f"✅ <b>Місце подачі:</b> {address.emoji} {address.name}\n"
            f"   {address.address}\n\n"
            "📍 <b>Куди їдемо?</b>\n\n"
            "💡 Оберіть спосіб:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data == "order:pickup:back")
    async def pickup_back_to_menu(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до вибору способу введення pickup"""
        await call.answer()
        
        from app.storage.db import get_user_saved_addresses
        saved_addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
        
        kb_buttons = [
            [InlineKeyboardButton(text="📍 Надіслати мою геолокацію", callback_data="order:pickup:send_location")],
            [InlineKeyboardButton(text="✏️ Ввести адресу текстом", callback_data="order:pickup:text")],
        ]
        
        if saved_addresses:
            kb_buttons.append([InlineKeyboardButton(text="📌 Вибрати зі збережених", callback_data="order:pickup:saved")])
        
        kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати замовлення", callback_data="cancel_order")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        await call.message.edit_text(
            "🚖 <b>Замовлення таксі</b>\n\n"
            "📍 <b>Звідки вас забрати?</b>\n\n"
            "💡 Оберіть спосіб:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data == "show_car_classes")
    async def show_classes_callback(call: CallbackQuery, state: FSMContext) -> None:
        """Показати класи авто з цінами (викликається з saved_addresses)"""
        await call.answer()
        await show_car_class_selection_with_prices(call.message, state)
    
    @router.callback_query(F.data == "order:back:pickup")
    async def back_to_pickup(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до введення адреси подачі"""
        await call.answer()
        await state.set_state(OrderStates.pickup)
        
        from app.storage.db import get_user_saved_addresses
        saved_addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
        
        kb_buttons = [
            [InlineKeyboardButton(text="📍 Надіслати мою геолокацію", callback_data="order:pickup:send_location")],
            [InlineKeyboardButton(text="✏️ Ввести адресу текстом", callback_data="order:pickup:text")],
        ]
        
        if saved_addresses:
            kb_buttons.append([InlineKeyboardButton(text="📌 Вибрати зі збережених", callback_data="order:pickup:saved")])
        
        kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати замовлення", callback_data="cancel_order")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        await call.message.edit_text(
            "🚖 <b>Замовлення таксі</b>\n\n"
            "📍 <b>Звідки вас забрати?</b>\n\n"
            "💡 Оберіть спосіб:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data == "order:dest:send_location")
    async def dest_request_location(call: CallbackQuery, state: FSMContext) -> None:
        """Попросити користувача надіслати геолокацію для destination"""
        await call.answer()
        
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        try:
            await call.message.delete()
        except:
            pass
        
        msg = await call.message.answer(
            "📍 Натисніть кнопку нижче, щоб надіслати геолокацію призначення:",
            reply_markup=kb
        )
        await state.update_data(last_message_id=msg.message_id)
    
    @router.callback_query(F.data == "order:dest:text")
    async def dest_request_text(call: CallbackQuery, state: FSMContext) -> None:
        """Попросити користувача ввести адресу текстом для destination"""
        await call.answer()
        
        data = await state.get_data()
        pickup = data.get("pickup", "")
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="order:back:pickup")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")]
            ]
        )
        
        await call.message.edit_text(
            f"✅ <b>Місце подачі:</b>\n   {pickup}\n\n"
            "📍 <b>Куди їдемо?</b>\n\n"
            "✏️ Введіть адресу текстом:\n\n"
            "Наприклад: вул. Хрещатик, 1, Київ",
            reply_markup=kb
        )
    
    @router.callback_query(F.data == "order:dest:saved")
    async def dest_show_saved(call: CallbackQuery, state: FSMContext) -> None:
        """Показати збережені адреси для вибору destination"""
        await call.answer()
        
        if not call.from_user:
            return
        
        from app.storage.db import get_user_saved_addresses
        addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
        
        if not addresses:
            await call.answer("У вас немає збережених адрес", show_alert=True)
            return
        
        buttons = []
        for addr in addresses:
            buttons.append([
                InlineKeyboardButton(
                    text=f"{addr.emoji} {addr.name}",
                    callback_data=f"order:dest:use_saved:{addr.id}"
                )
            ])
        
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="order:dest:back")])
        buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        text = "📍 <b>Оберіть адресу призначення:</b>\n\n"
        for addr in addresses:
            text += f"{addr.emoji} <b>{addr.name}</b>\n"
            text += f"   {addr.address[:45]}{'...' if len(addr.address) > 45 else ''}\n\n"
        
        await call.message.edit_text(text, reply_markup=kb)
    
    @router.callback_query(F.data.startswith("order:dest:use_saved:"))
    async def dest_use_saved_address(call: CallbackQuery, state: FSMContext) -> None:
        """Використати збережену адресу для destination"""
        await call.answer()
        
        if not call.from_user:
            return
        
        addr_id = int(call.data.split(":", 3)[3])
        
        from app.storage.db import get_saved_address_by_id
        address = await get_saved_address_by_id(config.database_path, addr_id, call.from_user.id)
        
        if not address:
            await call.answer("❌ Адресу не знайдено", show_alert=True)
            return
        
        # Зберегти destination
        await state.update_data(
            destination=address.address,
            dest_lat=address.lat,
            dest_lon=address.lon
        )
        
        # Перейти до вибору класу авто
        await state.set_state(OrderStates.car_class)
        await call.message.answer("⏳ Розраховую вартість...")
        await show_car_class_selection_with_prices(call.message, state)
    
    @router.callback_query(F.data == "order:dest:back")
    async def dest_back_to_menu(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до вибору способу введення destination"""
        await call.answer()
        
        data = await state.get_data()
        pickup = data.get("pickup", "")
        
        from app.storage.db import get_user_saved_addresses
        saved_addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
        
        kb_buttons = [
            [InlineKeyboardButton(text="📍 Надіслати геолокацію", callback_data="order:dest:send_location")],
            [InlineKeyboardButton(text="✏️ Ввести адресу текстом", callback_data="order:dest:text")],
        ]
        
        if saved_addresses:
            kb_buttons.append([InlineKeyboardButton(text="📌 Вибрати зі збережених", callback_data="order:dest:saved")])
        
        kb_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="order:back:pickup")])
        kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        await call.message.edit_text(
            f"✅ <b>Місце подачі:</b>\n   {pickup}\n\n"
            "📍 <b>Куди їдемо?</b>\n\n"
            "💡 Оберіть спосіб:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data == "order:back_to_destination")
    async def back_to_destination(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до введення адреси призначення"""
        await call.answer()
        await state.set_state(OrderStates.destination)
        
        # Показати інлайн кнопки
        data = await state.get_data()
        pickup = data.get("pickup", "")
        
        from app.storage.db import get_user_saved_addresses
        saved_addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
        
        kb_buttons = [
            [InlineKeyboardButton(text="📍 Надіслати геолокацію", callback_data="order:dest:send_location")],
            [InlineKeyboardButton(text="✏️ Ввести адресу текстом", callback_data="order:dest:text")],
        ]
        
        if saved_addresses:
            kb_buttons.append([InlineKeyboardButton(text="📌 Вибрати зі збережених", callback_data="order:dest:saved")])
        
        kb_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="order:back:pickup")])
        kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        try:
            await call.message.edit_text(
                f"✅ <b>Місце подачі:</b>\n   {pickup}\n\n"
                "📍 <b>Куди їдемо?</b>\n\n"
                "💡 Оберіть спосіб:",
                reply_markup=kb
            )
        except:
            await call.message.answer(
                "📍 <b>Куди їдемо?</b>\n\n"
                "Надішліть адресу призначення текстом\n"
                "або поділіться геолокацією 📍"
            )
    
    @router.callback_query(F.data == "order:back_to_car_class")
    async def back_to_car_class(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до вибору класу авто"""
        await call.answer()
        await state.set_state(OrderStates.car_class)
        await show_car_class_selection_with_prices(call.message, state)
    
    @router.callback_query(F.data == "order:back_to_comment")
    async def back_to_comment(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до введення коментаря"""
        await call.answer()
        await state.set_state(OrderStates.comment)
        
        data = await state.get_data()
        car_class = data.get("car_class", "economy")
        estimated_fare = data.get("estimated_fare", 0)
        
        from app.handlers.car_classes import get_car_class_name
        class_name = get_car_class_name(car_class)
        
        comment_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏩ Без коментаря", callback_data="comment:skip")],
                [InlineKeyboardButton(text="⬅️ Назад до вибору класу", callback_data="order:back_to_car_class")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")]
            ]
        )
        
        try:
            await call.message.edit_text(
                f"✅ <b>Обрано:</b> {class_name}\n"
                f"💰 <b>Вартість:</b> {estimated_fare:.0f} грн\n\n"
                "💬 <b>Додайте коментар до замовлення</b> (опціонально):\n\n"
                "Наприклад:\n"
                "• Під'їзд 3, код домофону 123\n"
                "• Поверх 5, квартира справа\n"
                "• Зателефонуйте при приїзді\n\n"
                "Або натисніть '⏩ Без коментаря'",
                reply_markup=comment_kb
            )
        except:
            await call.message.answer(
                f"✅ <b>Обрано:</b> {class_name}\n"
                f"💰 <b>Вартість:</b> {estimated_fare:.0f} грн\n\n"
                "💬 <b>Додайте коментар до замовлення</b> (опціонально):\n\n"
                "Наприклад:\n"
                "• Під'їзд 3, код домофону 123\n"
                "• Поверх 5, квартира справа\n"
                "• Зателефонуйте при приїзді\n\n"
                "Або натисніть '⏩ Без коментаря'",
                reply_markup=comment_kb
            )
    
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
        
        # Отримати налаштування множників з БД
        night_percent = tariff.night_tariff_percent if hasattr(tariff, 'night_tariff_percent') else 50.0
        weather_percent = tariff.weather_percent if hasattr(tariff, 'weather_percent') else 0.0
        
        class_fare = calculate_fare_with_class(base_fare, car_class)
        final_price, explanation, total_mult = await calculate_dynamic_price(
            class_fare, city, online_count, 5, night_percent, weather_percent
        )
        await state.update_data(estimated_fare=final_price, fare_explanation=explanation)

        # Перейти до коментаря
        await state.set_state(OrderStates.comment)
        
        # Inline кнопки для коментаря
        comment_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏩ Без коментаря", callback_data="comment:skip")],
                [InlineKeyboardButton(text="⬅️ Назад до вибору класу", callback_data="order:back_to_car_class")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")]
            ]
        )
        
        try:
            await call.message.edit_text(
                f"✅ <b>Обрано:</b> {class_name}\n"
                f"💰 <b>Вартість:</b> {final_price:.0f} грн\n\n"
                "💬 <b>Додайте коментар до замовлення</b> (опціонально):\n\n"
                "Наприклад:\n"
                "• Під'їзд 3, код домофону 123\n"
                "• Поверх 5, квартира справа\n"
                "• Зателефонуйте при приїзді\n\n"
                "Або натисніть '⏩ Без коментаря'",
                reply_markup=comment_kb
            )
        except:
            await call.message.answer(
                f"✅ <b>Обрано:</b> {class_name}\n"
                f"💰 <b>Вартість:</b> {final_price:.0f} грн\n\n"
                "💬 <b>Додайте коментар до замовлення</b> (опціонально):\n\n"
                "Наприклад:\n"
                "• Під'їзд 3, код домофону 123\n"
                "• Поверх 5, квартира справа\n"
                "• Зателефонуйте при приїзді\n\n"
                "Або натисніть '⏩ Без коментаря'",
                reply_markup=comment_kb
            )

    @router.message(OrderStates.pickup, F.location)
    async def pickup_location(message: Message, state: FSMContext) -> None:
        if not message.location:
            return
        
        loc = message.location
        
        # ⭐ REVERSE GEOCODING + PLACES: Координати → Текстова адреса з об'єктами поруч
        pickup = f"📍 {loc.latitude:.6f}, {loc.longitude:.6f}"  # Fallback
        
        if config.google_maps_api_key:
            try:
                # Використовуємо нову функцію з Places API
                readable_address = await reverse_geocode_with_places(
                    config.google_maps_api_key,
                    loc.latitude,
                    loc.longitude
                )
                if readable_address:
                    pickup = readable_address
                    logger.info(f"✅ Reverse geocoded pickup з об'єктами: {pickup}")
                else:
                    logger.warning(f"⚠️ Reverse geocoding не вдалось, використовую координати")
            except Exception as e:
                logger.error(f"❌ Помилка reverse geocoding: {e}")
        else:
            logger.warning("⚠️ Google Maps API ключ відсутній, зберігаю координати")
        
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
        
        # ⭐ REVERSE GEOCODING + PLACES: Координати → Текстова адреса з об'єктами поруч
        destination = f"📍 {loc.latitude:.6f}, {loc.longitude:.6f}"  # Fallback
        
        if config.google_maps_api_key:
            try:
                # Використовуємо нову функцію з Places API
                readable_address = await reverse_geocode_with_places(
                    config.google_maps_api_key,
                    loc.latitude,
                    loc.longitude
                )
                if readable_address:
                    destination = readable_address
                    logger.info(f"✅ Reverse geocoded destination з об'єктами: {destination}")
                else:
                    logger.warning(f"⚠️ Reverse geocoding не вдалось, використовую координати")
            except Exception as e:
                logger.error(f"❌ Помилка reverse geocoding: {e}")
        else:
            logger.warning("⚠️ Google Maps API ключ відсутній, зберігаю координати")
        
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

    @router.callback_query(F.data == "comment:skip", OrderStates.comment)
    async def skip_comment(call: CallbackQuery, state: FSMContext) -> None:
        """Пропустити коментар (inline кнопка)"""
        await call.answer("Без коментаря")
        await state.update_data(comment=None)
        
        # Перейти до вибору способу оплати
        await state.set_state(OrderStates.payment_method)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💵 Готівка", callback_data="payment:cash")],
                [InlineKeyboardButton(text="💳 Картка", callback_data="payment:card")],
                [InlineKeyboardButton(text="⬅️ Назад до коментаря", callback_data="order:back_to_comment")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")]
            ]
        )
        
        try:
            await call.message.edit_text(
                "💰 <b>Оберіть спосіб оплати:</b>\n\n"
                "💵 <b>Готівка</b> - розрахунок з водієм після поїздки\n"
                "💳 <b>Картка</b> - переказ на картку водія (реквізити одразу після прийняття)",
                reply_markup=kb
            )
        except:
            await call.message.answer(
                "💰 <b>Оберіть спосіб оплати:</b>\n\n"
                "💵 <b>Готівка</b> - розрахунок з водієм після поїздки\n"
                "💳 <b>Картка</b> - переказ на картку водія (реквізити одразу після прийняття)",
                reply_markup=kb
            )
    
    @router.message(OrderStates.comment, F.text == SKIP_TEXT)
    async def skip_comment_text(message: Message, state: FSMContext) -> None:
        """Пропустити коментар (старий текстовий метод для сумісності)"""
        await state.update_data(comment=None)
        
        # Перейти до вибору способу оплати
        await state.set_state(OrderStates.payment_method)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💵 Готівка", callback_data="payment:cash")],
                [InlineKeyboardButton(text="💳 Картка", callback_data="payment:card")],
                [InlineKeyboardButton(text="⬅️ Назад до коментаря", callback_data="order:back_to_comment")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")]
            ]
        )
        
        await message.answer(
            "💰 <b>Оберіть спосіб оплати:</b>\n\n"
            "💵 <b>Готівка</b> - розрахунок з водієм після поїздки\n"
            "💳 <b>Картка</b> - переказ на картку водія (реквізити одразу після прийняття)",
            reply_markup=kb
        )

    @router.message(OrderStates.comment)
    async def save_comment(message: Message, state: FSMContext) -> None:
        comment = message.text.strip() if message.text else None
        
        # ВАЛІДАЦІЯ: Перевірка коментаря
        if comment:
            is_valid, cleaned_comment = validate_comment(comment, max_length=500)
            if not is_valid:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⏩ Без коментаря", callback_data="comment:skip")],
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="order:back_to_car_class")]
                    ]
                )
                await message.answer(
                    "❌ <b>Невірний формат коментаря</b>\n\n"
                    "Коментар має містити:\n"
                    "• Максимум 500 символів\n"
                    "• Тільки допустимі символи\n\n"
                    "Спробуйте ще раз або пропустіть",
                    reply_markup=kb
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
                [InlineKeyboardButton(text="💳 Картка", callback_data="payment:card")],
                [InlineKeyboardButton(text="⬅️ Назад до коментаря", callback_data="order:back_to_comment")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")]
            ]
        )
        
        await message.answer(
            f"✅ <b>Коментар додано:</b>\n{comment}\n\n"
            "💰 <b>Оберіть спосіб оплати:</b>\n\n"
            "💵 <b>Готівка</b> - розрахунок з водієм після поїздки\n"
            "💳 <b>Картка</b> - переказ на картку водія",
            reply_markup=kb
        )

    @router.callback_query(F.data.startswith("payment:"))
    async def select_payment_method(call: CallbackQuery, state: FSMContext) -> None:
        """Вибір способу оплати"""
        payment_method = call.data.split(":")[1]  # cash або card
        await state.update_data(payment_method=payment_method)
        
        payment_text = ""
        if payment_method == "card":
            await call.answer("💳 Картка")
            payment_text = "💳 <b>Оплата карткою</b>\n\n✅ Картка водія з'явиться після прийняття замовлення."
        else:
            await call.answer("💵 Готівка")
            payment_text = "💵 <b>Оплата готівкою</b>\n\n✅ Розрахунок з водієм після поїздки."
        
        try:
            await call.message.edit_text(payment_text)
        except:
            pass
        
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
            f"💰 Вартість: {data.get('estimated_fare', 0):.0f} грн\n"
            + (f"💳 Оплата: {payment_text}\n\n" if payment_text else "\n")
            + "✅ Все вірно? Підтвердіть замовлення:"
        )
        
        # Inline кнопки для підтвердження
        confirm_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Підтвердити замовлення", callback_data="order:confirm")],
                [InlineKeyboardButton(text="⬅️ Назад до способу оплати", callback_data="order:back_to_payment")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")]
            ]
        )
        
        await state.set_state(OrderStates.confirm)
        # Зберегти message_id для подальшого видалення
        confirmation_msg = await message.answer(text, reply_markup=confirm_kb)
        await state.update_data(confirmation_message_id=confirmation_msg.message_id)

    @router.callback_query(F.data == "order:back_to_payment")
    async def back_to_payment(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до вибору способу оплати"""
        await call.answer()
        await state.set_state(OrderStates.payment_method)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💵 Готівка", callback_data="payment:cash")],
                [InlineKeyboardButton(text="💳 Картка", callback_data="payment:card")],
                [InlineKeyboardButton(text="⬅️ Назад до коментаря", callback_data="order:back_to_comment")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")]
            ]
        )
        
        try:
            await call.message.edit_text(
                "💰 <b>Оберіть спосіб оплати:</b>\n\n"
                "💵 <b>Готівка</b> - розрахунок з водієм після поїздки\n"
                "💳 <b>Картка</b> - переказ на картку водія",
                reply_markup=kb
            )
        except:
            await call.message.answer(
                "💰 <b>Оберіть спосіб оплати:</b>\n\n"
                "💵 <b>Готівка</b> - розрахунок з водієм після поїздки\n"
                "💳 <b>Картка</b> - переказ на картку водія",
                reply_markup=kb
            )
    
    @router.callback_query(F.data == "order:confirm", OrderStates.confirm)
    async def confirm_order_callback(call: CallbackQuery, state: FSMContext) -> None:
        """Підтвердження замовлення (inline кнопка)"""
        await call.answer("✅ Створюємо замовлення...")
        
        # ⭐ Видалити повідомлення про перевірку даних
        try:
            await call.message.delete()
        except Exception as e:
            logger.warning(f"Не вдалося видалити повідомлення підтвердження: {e}")
        
        # Викликати основну логіку
        await process_order_confirmation(call.message, state, call.from_user.id, config)
    
    @router.message(OrderStates.confirm, F.text == CONFIRM_TEXT)
    async def confirm_order_text(message: Message, state: FSMContext) -> None:
        """Підтвердження замовлення (текстова кнопка для сумісності)"""
        if not message.from_user:
            return
        await process_order_confirmation(message, state, message.from_user.id, config)
    
    async def process_order_confirmation(message: Message, state: FSMContext, user_id: int, config: AppConfig) -> None:
        """Основна логіка створення замовлення"""
        data = await state.get_data()
        
        # Створення замовлення з координатами, відстанню, класом авто, ціною та способом оплати
        order = Order(
            id=None,
            user_id=user_id,
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

        # Визначити місто клієнта ДО очищення state (щоб мати надійний fallback)
        resolved_city = (data.get("city") or "").strip() or None

        # Отримати місто клієнта з профілю як основне джерело правди
        from app.storage.db import get_user_by_id
        user = await get_user_by_id(config.database_path, message.from_user.id)
        client_city = (user.city.strip() if (user and user.city) else None) or resolved_city

        # Очистити стан після того, як зняли всі необхідні дані
        await state.clear()
        
        # ⭐ Відправка замовлення у групу МІСТА КЛІЄНТА
        # Отримати групу міста через helper з урахуванням fallback
        from app.config.config import get_city_group_id
        city_group_id = get_city_group_id(config, client_city)

        # DEBUG: Логування для діагностики
        logger.info(
            f"🔍 DEBUG: order_confirm city resolution → user_id={message.from_user.id}, "
            f"user_city={(user.city if user else None)}, state_city={resolved_city}, resolved_city={client_city}"
        )
        logger.info(f"🔍 DEBUG: config.city_groups={config.city_groups}")
        if city_group_id:
            if client_city in config.city_groups and config.city_groups.get(client_city):
                logger.info(f"✅ Використовую групу міста '{client_city}': {city_group_id}")
            else:
                logger.warning(f"⚠️ Для міста '{client_city}' немає окремої групи, використовую fallback: {city_group_id}")
        
        if city_group_id:
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
                        
                        city = client_city or data.get('city', 'Київ')
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
                
                # Отримати онлайн водіїв для пріоритизації (лише якщо увімкнено режим пріоритету)
                from app.storage.db import get_online_drivers
                from app.handlers.driver_priority import get_top_drivers
                from app.storage.db_connection import db_manager
                
                priority_enabled = False
                async with db_manager.connect(config.database_path) as db:
                    async with db.execute("SELECT value FROM app_settings WHERE key = 'priority_mode'") as cur:
                        row = await cur.fetchone()
                        priority_enabled = bool(row and str(row[0]).lower() in ("1","true","on","yes"))

                online_drivers = await get_online_drivers(config.database_path, client_city or data.get('city'))
                top_drivers = await get_top_drivers(config.database_path, online_drivers, limit=5) if priority_enabled else []
                
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
                
                # Очистити адреси від Plus Codes
                from app.handlers.driver_panel import clean_address
                clean_pickup = clean_address(data.get('pickup', ''))
                clean_destination = clean_address(data.get('destination', ''))
                
                # Створити посилання на маршрут Google Maps
                route_link = ""
                if pickup_lat and pickup_lon and dest_lat and dest_lon:
                    route_link = (
                        f"\n🗺️ <a href='https://www.google.com/maps/dir/?api=1"
                        f"&origin={pickup_lat},{pickup_lon}"
                        f"&destination={dest_lat},{dest_lon}"
                        f"&travelmode=driving'>Відкрити маршрут на Google Maps</a>"
                    )
                
                # Форматування вартості для візуального виділення
                fare_amount = data.get('fare_amount', 0)
                fare_text = f"💰 <b>ВАРТІСТЬ: {int(fare_amount)} грн</b> 💰" if fare_amount else ""
                
                group_message = (
                    f"🚖 <b>ЗАМОВЛЕННЯ #{order_id}</b>\n\n"
                    f"{fare_text}\n"
                    f"{distance_info}"
                    f"━━━━━━━━━━━━━━━━━\n\n"
                    f"📍 <b>МАРШРУТ:</b>\n"
                    f"🔵 {clean_pickup}\n"
                    f"🔴 {clean_destination}{route_link}\n\n"
                    f"👤 {data.get('name')} • 📱 <code>{masked_phone}</code> 🔒\n"
                    f"💬 {data.get('comment') or 'Без коментарів'}\n\n"
                    f"⏰ {datetime.now(timezone.utc).strftime('%H:%M')} • 🏙 {client_city or data.get('city') or '—'}\n\n"
                    f"ℹ️ <i>Повний номер після прийняття</i>"
                )
                
                # Надіслати в обрану міську групу з автоматичним fallback на загальну
                successfully_sent = False
                used_group_id = city_group_id
                try:
                    sent_message = await message.bot.send_message(
                        city_group_id,
                        group_message,
                        reply_markup=kb,
                        disable_web_page_preview=True
                    )
                    successfully_sent = True
                except Exception as e:
                    err_text = str(e).lower()
                    logger.error(f"Failed to send order to city group {city_group_id}: {e}")
                    # Спробувати fallback якщо чат не знайдено/бот не має доступу
                    if ("chat not found" in err_text or "forbidden" in err_text) and config.driver_group_chat_id and config.driver_group_chat_id != city_group_id:
                        try:
                            logger.warning(f"⚠️ Fallback: надсилаю замовлення #{order_id} у загальну групу {config.driver_group_chat_id}")
                            sent_message = await message.bot.send_message(
                                config.driver_group_chat_id,
                                group_message,
                                reply_markup=kb,
                                disable_web_page_preview=True
                            )
                            used_group_id = config.driver_group_chat_id
                            successfully_sent = True
                        except Exception as e2:
                            logger.error(f"❌ Fallback також не вдався: {e2}")
                
                if not successfully_sent:
                    raise RuntimeError("Не вдалося надіслати повідомлення у жодну групу")
                
                # Зберегти ID повідомлення в БД
                await update_order_group_message(config.database_path, order_id, sent_message.message_id)
                
                logger.info(f"✅ Замовлення {order_id} відправлено в групу (ID: {used_group_id})")
                
                # ЗАПУСТИТИ ТАЙМЕР: Якщо замовлення не прийнято за 3 хв - перепропонувати
                await start_order_timeout(
                    message.bot,
                    order_id,
                    config.database_path,
                    used_group_id,
                    sent_message.message_id
                )
                logger.info(f"⏱️ Таймер запущено для замовлення #{order_id}")
                
                # ⭐ Відповідь клієнту (зберегти message_id для підвищення ціни)
                from app.handlers.keyboards import main_menu_keyboard
                is_admin = message.from_user.id in config.bot.admin_ids if message.from_user else False
                client_message = await message.answer(
                    f"✅ <b>Замовлення #{order_id} прийнято!</b>\n\n"
                    "🔍 Шукаємо водія...\n\n"
                    "Ваше замовлення надіслано водіям.\n"
                    "Очікуйте підтвердження! ⏱",
                    reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
                )
                
                # Зберегти message_id для пізнішого оновлення (пропозиція підняти ціну)
                await state.update_data(
                    client_waiting_message_id=client_message.message_id,
                    order_id=order_id,
                    fare_increase=0  # Скільки грн додано до ціни
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

    # Обробник "📜 Мої замовлення" прибрано - тепер доступ через профіль

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
    @router.callback_query(F.data == "cancel_order")
    async def cancel_order_creation(call: CallbackQuery, state: FSMContext) -> None:
        """Скасувати створення замовлення (під час заповнення форми)"""
        if not call.from_user:
            return
        
        await call.answer("✅ Скасовано")
        
        # Очистити FSM state
        await state.clear()
        
        # Показати головне меню
        from app.handlers.keyboards import main_menu_keyboard
        user = await get_user_by_id(config.database_path, call.from_user.id)
        is_registered = user is not None and user.phone and user.city
        is_admin = call.from_user.id in config.bot.admin_ids
        
        try:
            await call.message.edit_text(
                "❌ <b>Створення замовлення скасовано</b>\n\n"
                "Ви можете створити нове замовлення будь-коли.",
                reply_markup=None
            )
        except:
            pass
        
        await call.message.answer(
            "🏠 Головне меню:",
            reply_markup=main_menu_keyboard(is_registered=is_registered, is_admin=is_admin)
        )
        
        logger.info(f"❌ Клієнт {call.from_user.id} скасував створення замовлення")
    
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
            
            # Повідомити в групу водіїв (групу міста клієнта)
            if order.group_message_id:
                try:
                    from app.config.config import get_city_group_id
                    
                    user = await get_user_by_id(config.database_path, order.user_id)
                    client_city = user.city if user and user.city else None
                    group_id = get_city_group_id(config, client_city)

                    async def _try_edit(chat_id: int) -> bool:
                        try:
                            await call.bot.edit_message_text(
                                "❌ <b>ЗАМОВЛЕННЯ СКАСОВАНО КЛІЄНТОМ</b>\n\n"
                                f"Замовлення #{order_id} скасовано клієнтом.",
                                chat_id=chat_id,
                                message_id=order.group_message_id
                            )
                            return True
                        except Exception as ee:
                            logger.error(f"❌ Не вдалося оновити повідомлення в групі {chat_id}: {ee}")
                            return False

                    updated = False
                    if group_id:
                        updated = await _try_edit(group_id)
                    # Fallback на загальну групу, якщо міська недоступна
                    if not updated and config.driver_group_chat_id and config.driver_group_chat_id != group_id:
                        if await _try_edit(config.driver_group_chat_id):
                            logger.info(f"✅ Скасування #{order_id} оновлено у fallback групі {config.driver_group_chat_id}")
                        else:
                            logger.warning(f"⚠️ Не вдалося оновити повідомлення ні в міській, ні в fallback групі")
                except Exception as e:
                    logger.error(f"Failed to update group message about cancellation: {e}")
            
            logger.info(f"Order #{order_id} cancelled by client {call.from_user.id}")
        else:
            await call.answer("❌ Не вдалося скасувати замовлення", show_alert=True)
    
    @router.callback_query(F.data.startswith("increase_price:"))
    async def increase_price_handler(call: CallbackQuery) -> None:
        """Підвищити ціну замовлення"""
        if not call.from_user:
            return
        
        # Парсинг даних: increase_price:{order_id}:{amount}
        parts = call.data.split(":")
        order_id = int(parts[1])
        increase_amount = float(parts[2])
        
        # Отримати замовлення
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        # Перевірити що це замовлення цього користувача
        if order.user_id != call.from_user.id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        # Перевірити що замовлення ще в статусі pending
        if order.status != "pending":
            await call.answer("✅ Водій вже прийняв замовлення!", show_alert=True)
            # Видалити повідомлення з пропозицією
            try:
                await call.message.delete()
            except:
                pass
            return
        
        # Підвищити ціну в БД
        success = await increase_order_fare(config.database_path, order_id, increase_amount)
        
        if not success:
            await call.answer("❌ Помилка оновлення ціни", show_alert=True)
            return
        
        # Отримати оновлене замовлення
        order = await get_order_by_id(config.database_path, order_id)
        new_fare = order.fare_amount if order else 0
        
        await call.answer(f"✅ Ціна підвищена на +{increase_amount:.0f} грн!", show_alert=True)
        
        # ⭐ Видалити повідомлення з пропозицією підняти ціну
        try:
            await call.message.delete()
        except Exception as e:
            logger.warning(f"Не вдалося видалити повідомлення: {e}")
        
        # ⭐ Оновити повідомлення в групі водіїв з НОВОЮ ЦІНОЮ
        if order.group_message_id:
            try:
                from app.config.config import get_city_group_id
                user = await get_user_by_id(config.database_path, order.user_id)
                client_city = user.city if user and user.city else None
                group_id = get_city_group_id(config, client_city)
                
                logger.info(f"🔍 Оновлення ціни: order_id={order_id}, group_message_id={order.group_message_id}, group_id={group_id}, city={client_city}")
                
                if group_id:
                    from app.handlers.car_classes import get_car_class_name
                    car_class_name = get_car_class_name(order.car_class or 'economy')
                    
                    # Створити посилання на Google Maps якщо є координати
                    pickup_link = ""
                    dest_link = ""
                    
                    if order.pickup_lat and order.pickup_lon:
                        pickup_link = f"\n📍 <a href='https://www.google.com/maps?q={order.pickup_lat},{order.pickup_lon}'>Геолокація подачі</a>"
                    
                    if order.dest_lat and order.dest_lon:
                        dest_link = f"\n📍 <a href='https://www.google.com/maps?q={order.dest_lat},{order.dest_lon}'>Геолокація прибуття</a>"
                    
                    distance_info = ""
                    if order.distance_m:
                        km = order.distance_m / 1000.0
                        distance_info = f"📏 Відстань: {km:.1f} км\n"
                    
                    masked_phone = mask_phone_number(order.phone, show_last_digits=2)
                    
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(
                                text="✅ Прийняти замовлення",
                                callback_data=f"accept_order:{order_id}"
                            )]
                        ]
                    )
                    
                    # Очистити адреси від Plus Codes для кращої читабельності
                    from app.handlers.driver_panel import clean_address
                    clean_pickup = clean_address(order.pickup_address)
                    clean_destination = clean_address(order.destination_address)
                    
                    # Створити посилання на маршрут Google Maps
                    route_link = ""
                    if order.pickup_lat and order.pickup_lon and order.dest_lat and order.dest_lon:
                        route_link = (
                            f"\n🗺️ <a href='https://www.google.com/maps/dir/?api=1"
                            f"&origin={order.pickup_lat},{order.pickup_lon}"
                            f"&destination={order.dest_lat},{order.dest_lon}"
                            f"&travelmode=driving'>Відкрити маршрут на Google Maps</a>"
                        )
                    
                    await call.bot.edit_message_text(
                        chat_id=group_id,
                        message_id=order.group_message_id,
                        text=(
                            f"🚖 <b>ЗАМОВЛЕННЯ #{order_id}</b>\n\n"
                            f"💰 <b>ВАРТІСТЬ: {int(new_fare)} грн</b> 💰\n"
                            f"⬆️ <b>+{int(increase_amount)} грн</b> (клієнт підвищив!)\n"
                            f"{distance_info}"
                            f"━━━━━━━━━━━━━━━━━\n\n"
                            f"📍 <b>МАРШРУТ:</b>\n"
                            f"🔵 {clean_pickup}\n"
                            f"🔴 {clean_destination}{route_link}\n\n"
                            f"👤 {order.name} • 📱 <code>{masked_phone}</code> 🔒\n"
                            f"💬 {order.comment or 'Без коментарів'}\n\n"
                            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M')} • 🏙 {client_city or 'Не вказано'}\n\n"
                            f"⚠️ <b>Клієнт готовий платити більше!</b>\n"
                            f"ℹ️ <i>Повний номер після прийняття</i>"
                        ),
                        reply_markup=kb,
                        disable_web_page_preview=True
                    )
                    logger.info(f"✅ Повідомлення в групі {group_id} оновлено: нова ціна {new_fare:.0f} грн для замовлення #{order_id}")
                else:
                    logger.warning(f"⚠️ Не знайдено group_id для міста '{client_city}', замовлення #{order_id}")
            except Exception as e:
                logger.error(f"❌ Не вдалося оновити повідомлення в групі: {e}", exc_info=True)
        
        # Відправити клієнту підтвердження
        try:
            await call.bot.send_message(
                call.from_user.id,
                f"✅ <b>Ціну підвищено!</b>\n\n"
                f"💰 Нова вартість: <b>{new_fare:.0f} грн</b>\n\n"
                f"🔍 Продовжуємо пошук водія з новою ціною..."
            )
        except Exception as e:
            logger.warning(f"Не вдалося надіслати підтвердження клієнту: {e}")
    
    @router.callback_query(F.data.startswith("cancel_waiting_order:"))
    async def cancel_waiting_order_handler(call: CallbackQuery) -> None:
        """Скасувати замовлення під час очікування"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[1])
        
        # Отримати замовлення
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        # Перевірити що це замовлення цього користувача
        if order.user_id != call.from_user.id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        # Скасувати замовлення (обов'язково з user_id для безпеки)
        success = await cancel_order_by_client(config.database_path, order_id, call.from_user.id)
        
        if success:
            # Скасувати таймер
            from app.utils.order_timeout import cancel_order_timeout
            cancel_order_timeout(order_id)
            
            await call.answer("✅ Замовлення скасовано", show_alert=True)
            
            # Видалити повідомлення з пропозицією
            try:
                await call.message.delete()
            except:
                pass
            
            # Повідомити в групу
            if order.group_message_id:
                try:
                    from app.config.config import get_city_group_id
                    user = await get_user_by_id(config.database_path, order.user_id)
                    client_city = user.city if user and user.city else None
                    group_id = get_city_group_id(config, client_city)

                    async def _try_edit(chat_id: int) -> bool:
                        try:
                            await call.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=order.group_message_id,
                                text=f"❌ <b>ЗАМОВЛЕННЯ #{order_id} СКАСОВАНО КЛІЄНТОМ</b>\n\n"
                                     f"📍 Маршрут: {order.pickup_address} → {order.destination_address}"
                            )
                            return True
                        except Exception as ee:
                            logger.error(f"❌ Не вдалося оновити повідомлення в групі {chat_id}: {ee}")
                            return False

                    updated = False
                    if group_id:
                        updated = await _try_edit(group_id)
                    if not updated and config.driver_group_chat_id and config.driver_group_chat_id != group_id:
                        if await _try_edit(config.driver_group_chat_id):
                            logger.info(f"✅ Скасування #{order_id} оновлено у fallback групі {config.driver_group_chat_id}")
                        else:
                            logger.warning("⚠️ Не вдалося оновити повідомлення ні в міській, ні в fallback групі")
                except Exception as e:
                    # Якщо повідомлення вже видалене - це не помилка
                    if "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
                        logger.info(f"ℹ️ Повідомлення #{order.group_message_id} вже видалене (замовлення #{order_id})")
                    else:
                        logger.error(f"❌ Помилка оновлення групи: {e}")
            
            # Відправити підтвердження
            await call.bot.send_message(
                call.from_user.id,
                "✅ <b>Замовлення скасовано</b>\n\n"
                "Ви можете створити нове замовлення будь-коли."
            )
        else:
            await call.answer("❌ Не вдалося скасувати", show_alert=True)
    
    @router.callback_query(F.data.startswith("continue_waiting:"))
    async def continue_waiting_handler(call: CallbackQuery, state: FSMContext) -> None:
        """Продовжити очікування без підвищення ціни"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[1])
        
        # Отримати замовлення
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        # Перевірити що це замовлення цього користувача
        if order.user_id != call.from_user.id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        # Перевірити статус
        if order.status != "pending":
            await call.answer("✅ Водій вже прийняв замовлення!", show_alert=True)
            try:
                await call.message.delete()
            except:
                pass
            return
        
        await call.answer("⏳ Продовжуємо пошук на поточній ціні...", show_alert=False)
        
        # Видалити повідомлення з пропозицією підвищити ціну
        try:
            await call.message.delete()
        except Exception as e:
            logger.warning(f"Не вдалося видалити повідомлення: {e}")
        
        # Показати повідомлення "Пошук водія..." (знову)
        from app.handlers.keyboards import main_menu_keyboard
        is_admin = call.from_user.id in config.bot.admin_ids
        
        current_fare = order.fare_amount if order.fare_amount else 100.0
        
        await call.bot.send_message(
            call.from_user.id,
            f"🔍 <b>Шукаємо водія...</b>\n\n"
            f"📍 Звідки: {order.pickup_address}\n"
            f"📍 Куди: {order.destination_address}\n\n"
            f"💰 Вартість: <b>{current_fare:.0f} грн</b>\n\n"
            f"⏳ Зачекайте, будь ласка...",
            reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
        )
        
        logger.info(f"⏳ Клієнт #{call.from_user.id} вирішив продовжити очікування без підвищення ціни (замовлення #{order_id})")
    
    return router
