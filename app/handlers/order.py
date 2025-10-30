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
from app.utils.maps import get_distance_and_duration, geocode_address, reverse_geocode_with_places, reverse_geocode
from app.utils.privacy import mask_phone_number
from app.utils.validation import validate_address, validate_comment
from app.utils.rate_limiter import check_rate_limit, get_time_until_reset, format_time_remaining
from app.utils.order_timeout import start_order_timeout
from app.handlers.car_classes import CAR_CLASSES, calculate_fare_with_class
from app.utils.visual import (
    format_process_message,
    get_status_emoji,
    get_status_text_with_emoji,
    create_box,
)

logger = logging.getLogger(__name__)


async def clean_chat_history(bot, chat_id: int, current_message_id: int, count: int = 20) -> None:
    """
    Видалити попередні повідомлення для чистоти чату
    
    Args:
        bot: Bot instance
        chat_id: ID чату
        current_message_id: ID поточного повідомлення
        count: Скільки попередніх повідомлень видалити (за замовчуванням 20)
    """
    deleted = 0
    for i in range(1, count + 1):
        try:
            await bot.delete_message(
                chat_id=chat_id,
                message_id=current_message_id - i
            )
            deleted += 1
        except Exception:
            # Ігноруємо помилки (повідомлення може бути вже видалене)
            pass
    
    if deleted > 0:
        logger.info(f"🧹 Очищено {deleted} повідомлень в чаті {chat_id}")


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
        
        if pickup_lat and pickup_lon and dest_lat and dest_lon:
            logger.info(f"📏 Розраховую відстань через OSRM: ({pickup_lat},{pickup_lon}) → ({dest_lat},{dest_lon})")
            result = await get_distance_and_duration(
                "",  # api_key не потрібен для OSRM
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
        
        # Якщо не вдалося розрахувати - ПОМИЛКА (не використовуємо fallback!)
        if distance_km is None:
            logger.error(f"❌ Не вдалося розрахувати відстань для user {call.from_user.id if call.from_user else 'unknown'}")
            await call.message.answer(
                "❌ <b>Не вдалося розрахувати відстань</b>\n\n"
                "⚠️ Будь ласка, спробуйте:\n"
                "• Обрати інші точки\n"
                "• Ввести адреси текстом\n"
                "• Звернутися до підтримки\n\n"
                "Натисніть /order щоб спробувати знову",
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        # Отримати тариф
        tariff = await get_latest_tariff(config.database_path)
        if not tariff:
            await message.answer("❌ Помилка: тариф не налаштований. Зверніться до адміністратора.")
            await state.clear()
            return
        
        # Розрахувати базову ціну (використовуємо helper функцію)
        from app.handlers.car_classes import calculate_base_fare
        base_fare = calculate_base_fare(tariff, distance_km, duration_minutes)
        
        # Розрахувати ЦІНУ З УРАХУВАННЯМ ДИНАМІКИ для КОЖНОГО класу
        car_class_prices = {}
        car_class_explanations = {}
        from app.handlers.dynamic_pricing import calculate_dynamic_price, get_surge_emoji
        from app.storage.db import get_online_drivers_count, get_pricing_settings, get_pending_orders
        city = data.get('city', 'Київ') or 'Київ'
        online_count = await get_online_drivers_count(config.database_path, city)
        
        # Отримати РЕАЛЬНУ кількість pending orders
        pending_orders = await get_pending_orders(config.database_path, city)
        pending_orders_estimate = len(pending_orders)
        
        # Отримати всі налаштування ціноутворення з БД
        pricing = await get_pricing_settings(config.database_path)
        
        # Якщо налаштування не знайдено - використати дефолтні значення
        if pricing is None:
            from app.storage.db import PricingSettings
            pricing = PricingSettings()
        
        # Створити словник множників класів для передачі в calculate_fare_with_class
        custom_multipliers = {
            "economy": pricing.economy_multiplier,
            "standard": pricing.standard_multiplier,
            "comfort": pricing.comfort_multiplier,
            "business": pricing.business_multiplier
        }
        
        for class_key in ["economy", "standard", "comfort", "business"]:
            class_fare = calculate_fare_with_class(base_fare, class_key, custom_multipliers)
            final_price, explanation, total_mult = await calculate_dynamic_price(
                class_fare, city, online_count, pending_orders_estimate,
                pricing.night_percent, pricing.weather_percent,
                pricing.peak_hours_percent, pricing.weekend_percent,
                pricing.monday_morning_percent, pricing.no_drivers_percent,
                pricing.demand_very_high_percent, pricing.demand_high_percent,
                pricing.demand_medium_percent, pricing.demand_low_discount_percent
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
        calc_message = format_process_message('calculating', 'Розрахунок маршруту')
        info_text = (
            f"{calc_message}\n\n"
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
        
        # 🚫 Перевірка блокування
        from app.handlers.blocked_check import is_user_blocked, send_blocked_message
        if await is_user_blocked(config.database_path, message.from_user.id):
            await send_blocked_message(message)
            return
        
        # ЗАХИСТ: Перевірка чи клієнт заблокований
        from app.storage.db import get_user_by_id
        user = await get_user_by_id(config.database_path, message.from_user.id)
        if user and user.is_blocked:
            await message.answer(
                "🚫 <b>ВАШІ АКАУНТ ЗАБЛОКОВАНО</b>\n\n"
                "На жаль, ви не можете створювати замовлення.\n"
                "Якщо вважаєте це помилкою, зверніться до адміністратора.",
                parse_mode="HTML"
            )
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
        
        # 🗺️ СПРОЩЕНІ КНОПКИ: карта + збережені + скасувати
        kb_buttons = []
        
        # 1. Кнопка карти (НОВА ЛОГІКА: обирає обидві точки в одній сесії)
        if config.webapp_url:
            from aiogram.types import WebAppInfo
            kb_buttons.append([
                InlineKeyboardButton(
                    text="🗺 Обрати на інтерактивній карті",
                    web_app=WebAppInfo(url=config.webapp_url)
                )
            ])
        
        # 2. Збережені адреси (якщо є)
        if saved_addresses:
            kb_buttons.append([
                InlineKeyboardButton(
                    text="📌 Вибрати зі збережених", 
                    callback_data="order:pickup:saved"
                )
            ])
        
        # 3. Скасувати замовлення
        kb_buttons.append([
            InlineKeyboardButton(
                text="❌ Скасувати замовлення", 
                callback_data="cancel_order"
            )
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        msg = await message.answer(
            "🚖 <b>Замовлення таксі</b>\n\n"
            "📍 <b>Як бажаєте обрати адреси?</b>\n\n"
            "🗺 <b>Інтерактивна карта</b>\n"
            "   • Оберіть місце посадки\n"
            "   • Оберіть місце призначення\n"
            "   • Побачите маршрут\n"
            "   • Все в одному вікні!\n\n"
            "📌 <b>Збережені адреси</b> - швидкий вибір\n\n"
            "💡 Оберіть спосіб:",
            reply_markup=kb
        )
        
        # Зберегти message_id для подальшого редагування
        await state.update_data(last_message_id=msg.message_id)

    @router.callback_query(F.data == "order:pickup:send_location")
    async def pickup_request_location(call: CallbackQuery, state: FSMContext) -> None:
        """Показати вибір: карта або GPS геолокація для pickup"""
        await call.answer()
        
        # Зберегти що ми чекаємо pickup
        await state.update_data(waiting_for='pickup')
        
        # Створити інлайн кнопки з вибором
        kb_buttons = []
        
        # Додати кнопку карти, якщо WEBAPP_URL налаштовано
        if config.webapp_url:
            from aiogram.types import WebAppInfo
            # Для InlineKeyboard використовуємо web_app
            kb_buttons.append([
                InlineKeyboardButton(
                    text="🗺 Обрати на інтерактивній карті",
                    web_app=WebAppInfo(url=f"{config.webapp_url}?type=pickup")
                )
            ])
        
        # Кнопка GPS геолокації (через callback → ReplyKeyboard)
        kb_buttons.append([
            InlineKeyboardButton(
                text="📍 Надіслати мої координати GPS",
                callback_data="order:pickup:gps"
            )
        ])
        
        kb_buttons.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data="order:pickup:back"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        await call.message.edit_text(
            "📍 <b>Звідки вас забрати?</b>\n\n"
            "🗺 <b>Інтерактивна карта</b> - оберіть точку на карті\n"
            "📍 <b>GPS координати</b> - ваше поточне місцезнаходження\n\n"
            "💡 Оберіть спосіб:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data == "order:pickup:gps")
    async def pickup_request_gps(call: CallbackQuery, state: FSMContext) -> None:
        """Попросити GPS геолокацію для pickup"""
        await call.answer()
        
        # Тут ПОТРІБЕН ReplyKeyboard для request_location
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Надіслати мої GPS координати", request_location=True)],
                [KeyboardButton(text="❌ Скасувати")],
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        # Видалити попереднє повідомлення
        try:
            await call.message.delete()
        except Exception as e:
            pass
        
        # Показати нове з ReplyKeyboard
        msg = await call.message.answer(
            "📍 <b>Надішліть GPS координати</b>\n\n"
            "Натисніть кнопку нижче, щоб поділитися вашим поточним місцезнаходженням:",
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
        
        # 🗺️ СПРОЩЕНІ КНОПКИ для destination
        kb_buttons = []
        
        # 1. Кнопка карти з передачею pickup координат
        if config.webapp_url:
            from aiogram.types import WebAppInfo
            await state.update_data(waiting_for='destination')
            # Передати pickup координати для відображення маршруту
            data = await state.get_data()
            pickup_lat = data.get('pickup_lat')
            pickup_lon = data.get('pickup_lon')
            url = f"{config.webapp_url}?type=destination"
            if pickup_lat and pickup_lon:
                url += f"&pickup_lat={pickup_lat}&pickup_lon={pickup_lon}"
            kb_buttons.append([
                InlineKeyboardButton(
                    text="🗺 Обрати на карті (з пошуком)",
                    web_app=WebAppInfo(url=url)
                )
            ])
        
        # 2. Збережені адреси
        if saved_addresses:
            kb_buttons.append([InlineKeyboardButton(text="📌 Вибрати зі збережених", callback_data="order:dest:saved")])
        
        # 3. Назад + Скасувати
        kb_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="order:back:pickup")])
        kb_buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        await call.message.edit_text(
            f"✅ <b>Місце подачі:</b> {address.emoji} {address.name}\n"
            f"   {address.address}\n\n"
            "📍 <b>Куди їдемо?</b>\n\n"
            "🗺 <b>Карта з пошуком</b> - знайдіть або оберіть точку\n"
            "📌 <b>Збережені</b> - швидкий вибір\n\n"
            "💡 Оберіть спосіб:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data == "order:pickup:back")
    async def pickup_back_to_menu(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до вибору способу введення pickup"""
        await call.answer()
        
        from app.storage.db import get_user_saved_addresses
        saved_addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
        
        # 🗺️ СПРОЩЕНІ КНОПКИ для pickup
        kb_buttons = []
        
        # 1. Кнопка карти
        if config.webapp_url:
            from aiogram.types import WebAppInfo
            await state.update_data(waiting_for='pickup')
            kb_buttons.append([
                InlineKeyboardButton(
                    text="🗺 Обрати на карті (з пошуком)",
                    web_app=WebAppInfo(url=f"{config.webapp_url}?type=pickup")
                )
            ])
        
        # 2. Збережені адреси
        if saved_addresses:
            kb_buttons.append([InlineKeyboardButton(text="📌 Вибрати зі збережених", callback_data="order:pickup:saved")])
        
        # 3. Скасувати
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
        """Показати вибір: карта або GPS геолокація для destination"""
        await call.answer()
        
        # Зберегти що ми чекаємо destination
        await state.update_data(waiting_for='destination')
        
        # Створити інлайн кнопки з вибором
        kb_buttons = []
        
        # Додати кнопку карти з pickup координатами
        if config.webapp_url:
            from aiogram.types import WebAppInfo
            # Передати pickup координати для відображення маршруту
            data = await state.get_data()
            pickup_lat = data.get('pickup_lat')
            pickup_lon = data.get('pickup_lon')
            url = f"{config.webapp_url}?type=destination"
            if pickup_lat and pickup_lon:
                url += f"&pickup_lat={pickup_lat}&pickup_lon={pickup_lon}"
            kb_buttons.append([
                InlineKeyboardButton(
                    text="🗺 Обрати на інтерактивній карті",
                    web_app=WebAppInfo(url=url)
                )
            ])
        
        # Кнопка GPS геолокації
        kb_buttons.append([
            InlineKeyboardButton(
                text="📍 Надіслати мої координати GPS",
                callback_data="order:dest:gps"
            )
        ])
        
        kb_buttons.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data="order:back:pickup"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_order")
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        # Отримати pickup адресу для відображення
        data = await state.get_data()
        pickup_address = data.get('pickup', 'Не вказано')
        
        await call.message.edit_text(
            f"✅ <b>Місце подачі:</b>\n{pickup_address}\n\n"
            "📍 <b>Куди їдемо?</b>\n\n"
            "🗺 <b>Інтерактивна карта</b> - оберіть точку на карті\n"
            "📍 <b>GPS координати</b> - місце призначення\n\n"
            "💡 Оберіть спосіб:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data == "order:dest:gps")
    async def dest_request_gps(call: CallbackQuery, state: FSMContext) -> None:
        """Попросити GPS геолокацію для destination"""
        await call.answer()
        
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Надіслати GPS координати", request_location=True)],
                [KeyboardButton(text="❌ Скасувати")],
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        try:
            await call.message.delete()
        except Exception as e:
            pass
        
        msg = await call.message.answer(
            "📍 <b>Надішліть координати місця призначення</b>\n\n"
            "Натисніть кнопку нижче:",
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
        except Exception as e:
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
        except Exception as e:
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
    
    @router.callback_query(F.data.startswith("select_car_class:") | F.data.startswith("select_class:"))
    async def select_car_class_handler(call: CallbackQuery, state: FSMContext) -> None:
        """Вибір класу авто після перегляду цін (обробляє select_car_class: та select_class:)"""
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
        # Використовуємо helper функцію
        from app.handlers.car_classes import calculate_base_fare
        base_fare = calculate_base_fare(tariff, distance_km, duration_minutes)
        from app.handlers.dynamic_pricing import calculate_dynamic_price
        from app.storage.db import get_online_drivers_count, get_pricing_settings, get_pending_orders
        city = data.get('city', 'Київ') or 'Київ'
        online_count = await get_online_drivers_count(config.database_path, city)
        
        # Отримати кількість pending orders для розрахунку попиту (РЕАЛЬНЕ значення!)
        pending_orders = await get_pending_orders(config.database_path, city)
        pending_count = len(pending_orders)
        
        # Отримати всі налаштування ціноутворення з БД
        pricing = await get_pricing_settings(config.database_path)
        
        # Якщо налаштування не знайдено - використати дефолтні значення
        if pricing is None:
            from app.storage.db import PricingSettings
            pricing = PricingSettings()
        
        custom_multipliers = {
            "economy": pricing.economy_multiplier,
            "standard": pricing.standard_multiplier,
            "comfort": pricing.comfort_multiplier,
            "business": pricing.business_multiplier
        }
        
        class_fare = calculate_fare_with_class(base_fare, car_class, custom_multipliers)
        final_price, explanation, total_mult = await calculate_dynamic_price(
            class_fare, city, online_count, pending_count,  # <-- РЕАЛЬНЕ значення!
            pricing.night_percent, pricing.weather_percent,
            pricing.peak_hours_percent, pricing.weekend_percent,
            pricing.monday_morning_percent, pricing.no_drivers_percent,
            pricing.demand_very_high_percent, pricing.demand_high_percent,
            pricing.demand_medium_percent, pricing.demand_low_discount_percent
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
        except Exception as e:
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
        
        # ⭐ REVERSE GEOCODING через Nominatim (OpenStreetMap) - БЕЗКОШТОВНО!
        try:
            # Nominatim не потребує API ключа!
            readable_address = await reverse_geocode(
                "",  # api_key не потрібен
                loc.latitude,
                loc.longitude
            )
            if readable_address:
                pickup = readable_address
                logger.info(f"✅ Nominatim reverse geocoded pickup: {pickup}")
            else:
                # Якщо не вдалось - використати координати як fallback
                pickup = f"📍 {loc.latitude:.6f}, {loc.longitude:.6f}"
                logger.warning(f"⚠️ Reverse geocoding не вдалось для pickup, використовую координати")
        except Exception as e:
            pickup = f"📍 {loc.latitude:.6f}, {loc.longitude:.6f}"
            logger.error(f"❌ Помилка reverse geocoding pickup: {e}")
        
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
        
        # 🛡️ ІГНОРУВАТИ кнопки меню (щоб не геокодувати їх як адреси)
        MENU_BUTTONS = {
            "📍 Мої адреси", "👤 Мій профіль", "ℹ️ Допомога",
            "📖 Правила користування", "❌ Скасувати", "⚙️ Адмін-панель",
            "🚗 Панель водія", "🎤 Голосом"
        }
        if pickup in MENU_BUTTONS:
            # Кнопка з меню - не обробляти як адресу
            return
        
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
        
        # Спроба геокодувати адресу в координати через Nominatim (безкоштовно!)
        geo_message = format_process_message('geocoding', f'Геокодую адресу: {pickup}')
        logger.info(geo_message)
        coords = await geocode_address("", pickup)  # api_key не потрібен для Nominatim
        
        if coords:
            lat, lon = coords
            await state.update_data(pickup=pickup, pickup_lat=lat, pickup_lon=lon)
            logger.info(f"✅ Nominatim геокодував адресу: {pickup} → {lat},{lon}")
        else:
            logger.warning(f"❌ Не вдалося геокодувати адресу: {pickup}")
            await state.update_data(pickup=pickup)
            await message.answer(
                "⚠️ Не вдалося визначити координати адреси.\n"
                "Для точного розрахунку використовуйте геолокацію 📍"
            )
        
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
        
        # ⭐ REVERSE GEOCODING через Nominatim (OpenStreetMap) - БЕЗКОШТОВНО!
        try:
            # Nominatim не потребує API ключа!
            readable_address = await reverse_geocode(
                "",  # api_key не потрібен
                loc.latitude,
                loc.longitude
            )
            if readable_address:
                destination = readable_address
                logger.info(f"✅ Nominatim reverse geocoded destination: {destination}")
            else:
                # Якщо не вдалось - використати координати як fallback
                destination = f"📍 {loc.latitude:.6f}, {loc.longitude:.6f}"
                logger.warning(f"⚠️ Reverse geocoding не вдалось для destination, використовую координати")
        except Exception as e:
            destination = f"📍 {loc.latitude:.6f}, {loc.longitude:.6f}"
            logger.error(f"❌ Помилка reverse geocoding destination: {e}")
        
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
        
        # 🛡️ ІГНОРУВАТИ кнопки меню (щоб не геокодувати їх як адреси)
        MENU_BUTTONS = {
            "📍 Мої адреси", "👤 Мій профіль", "ℹ️ Допомога",
            "📖 Правила користування", "❌ Скасувати", "⚙️ Адмін-панель",
            "🚗 Панель водія", "🎤 Голосом"
        }
        if destination in MENU_BUTTONS:
            # Кнопка з меню - не обробляти як адресу
            return
        
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
        except Exception as e:
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
        except Exception as e:
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
        
        # Якщо немає координат але є текстові адреси - геокодувати через Nominatim
        if not pickup_lat or not dest_lat:
            pickup_addr = data.get('pickup')
            dest_addr = data.get('destination')
            
            if pickup_addr and dest_addr and '📍' not in str(pickup_addr):
                # Геокодувати адреси через Nominatim (безкоштовно!)
                logger.info(f"🔍 Геокодую адреси через Nominatim...")
                pickup_coords = await geocode_address("", str(pickup_addr))
                dest_coords = await geocode_address("", str(dest_addr))
                
                if pickup_coords and dest_coords:
                    pickup_lat, pickup_lon = pickup_coords
                    dest_lat, dest_lon = dest_coords
                    await state.update_data(
                        pickup_lat=pickup_lat, pickup_lon=pickup_lon,
                        dest_lat=dest_lat, dest_lon=dest_lon
                    )
                    logger.info(f"✅ Обидві адреси геокодовані через Nominatim")
        
        # Якщо є координати - розрахувати відстань через OSRM (безкоштовно!)
        if pickup_lat and pickup_lon and dest_lat and dest_lon:
            logger.info(f"📏 Розраховую відстань через OSRM: ({pickup_lat},{pickup_lon}) → ({dest_lat},{dest_lon})")
            result = await get_distance_and_duration(
                "",  # api_key не потрібен для OSRM
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
                logger.info(f"✅ OSRM розрахував відстань: {km:.1f} км, {int(minutes)} хв")
            else:
                logger.warning(f"❌ OSRM не повернув результат")
        else:
            logger.warning(f"⚠️ Немає всіх координат для розрахунку: pickup({pickup_lat},{pickup_lon}), dest({dest_lat},{dest_lon})")
        
        from app.handlers.car_classes import get_car_class_name
        car_class_name = get_car_class_name(data.get('car_class', 'economy'))
        
        # Відобразити спосіб оплати, якщо вибрано
        payment_method = data.get('payment_method')
        payment_text = "💵 Готівка" if payment_method == "cash" else ("💳 Картка" if payment_method == "card" else None)

        # ⭐ ПЕРЕТВОРИТИ КООРДИНАТИ В АДРЕСИ (якщо є координати)
        from app.handlers.driver_panel import clean_address
        from app.utils.maps import reverse_geocode
        
        pickup_display = data.get('pickup', '')
        destination_display = data.get('destination', '')
        
        # Якщо є координати - спробувати геокодувати в адресу
        pickup_lat = data.get('pickup_lat')
        pickup_lon = data.get('pickup_lon')
        dest_lat = data.get('dest_lat')
        dest_lon = data.get('dest_lon')
        
        if pickup_lat and pickup_lon:
            # Перевірити чи pickup_display містить координати замість адреси
            # Формат координат: "📍 12.345678, 67.890123" або просто числа з комою
            pickup_str = str(pickup_display)
            is_coordinates = (
                '📍 Координати:' in pickup_str or 
                (pickup_str.count('.') >= 2 and pickup_str.count(',') == 1 and len(pickup_str) < 40)
            )
            
            if is_coordinates:
                logger.info(f"🔄 Координати виявлені в pickup, геокодую: {pickup_display}")
                try:
                    readable_address = await reverse_geocode("", float(pickup_lat), float(pickup_lon))
                    if readable_address:
                        pickup_display = readable_address
                        # ЗБЕРЕГТИ В STATE!
                        await state.update_data(pickup=readable_address)
                        logger.info(f"✅ Pickup геокодовано і збережено: {pickup_display}")
                except Exception as e:
                    logger.error(f"❌ Помилка геокодування pickup: {e}")
        
        if dest_lat and dest_lon:
            # Перевірити чи destination_display містить координати замість адреси
            dest_str = str(destination_display)
            is_coordinates = (
                '📍 Координати:' in dest_str or 
                (dest_str.count('.') >= 2 and dest_str.count(',') == 1 and len(dest_str) < 40)
            )
            
            if is_coordinates:
                logger.info(f"🔄 Координати виявлені в destination, геокодую: {destination_display}")
                try:
                    readable_address = await reverse_geocode("", float(dest_lat), float(dest_lon))
                    if readable_address:
                        destination_display = readable_address
                        # ЗБЕРЕГТИ В STATE!
                        await state.update_data(destination=readable_address)
                        logger.info(f"✅ Destination геокодовано і збережено: {destination_display}")
                except Exception as e:
                    logger.error(f"❌ Помилка геокодування destination: {e}")
        
        # Очистити адреси від Plus Codes (якщо залишились)
        clean_pickup = clean_address(pickup_display)
        clean_destination = clean_address(destination_display)

        text = (
            "📋 <b>Перевірте дані замовлення:</b>\n\n"
            f"👤 Клієнт: {data.get('name')}\n"
            f"📱 Телефон: {data.get('phone')}\n"
            f"🏙 Місто: {data.get('city')}\n"
            f"🚗 Клас: {car_class_name}\n\n"
            f"📍 Звідки: {clean_pickup}\n"
            f"📍 Куди: {clean_destination}\n"
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
        except Exception as e:
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
        
        # 🛡️ RATE LIMITING: Захист від спаму замовлень (перевірка ПЕРЕД створенням)
        can_order = check_rate_limit(
            user_id=user_id,
            action="create_order",
            max_requests=3,  # Максимум 3 замовлення
            window_seconds=3600  # За 1 годину
        )
        
        if not can_order:
            # Перевірити чи є бонусні поїздки від адміна
            from app.storage.db import use_bonus_ride
            has_bonus = await use_bonus_ride(config.database_path, user_id)
            
            if has_bonus:
                # Бонусна поїздка використана, продовжуємо створення замовлення
                logger.info(f"✅ Клієнт #{user_id} використав бонусну поїздку (понад ліміт 3/год)")
            else:
                # Немає бонусних поїздок, показуємо повідомлення про ліміт
                wait_time = get_time_until_reset(
                    user_id=user_id,
                    action="create_order",
                    window_seconds=3600
                )
                remaining = format_time_remaining(wait_time)
                await message.answer(
                    f"⏱ <b>Забагато замовлень</b>\n\n"
                    f"Ви створили 3 замовлення за останню годину.\n"
                    f"Це максимум для захисту системи від зловживань.\n\n"
                    f"⏰ Спробуйте знову через: <b>{remaining}</b>\n\n"
                    f"💡 Якщо це помилка, зверніться до підтримки.",
                    parse_mode="HTML"
                )
                # Очистити state та повернути в головне меню
                await state.clear()
                return
        
        # 🧹 Очистити всі попередні повідомлення процесу замовлення
        if message and message.message_id:
            await clean_chat_history(message.bot, user_id, message.message_id, count=50)
        
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

        # Логування вибору групи міста
        logger.info(
            f"📍 Вибір групи для міста '{client_city}' → "
            f"user_city={(user.city if user else None)}, resolved={resolved_city}"
        )
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
                        # Базовий тариф (використовуємо helper функцію)
                        from app.handlers.car_classes import calculate_base_fare
                        base_fare = calculate_base_fare(tariff, km, minutes)
                        
                        # Застосувати клас авто (ТАК ЯК ДЛЯ КЛІЄНТА!)
                        from app.handlers.car_classes import calculate_fare_with_class, get_car_class_name
                        from app.storage.db import get_online_drivers_count, get_pricing_settings
                        
                        # Отримати налаштування ціноутворення
                        pricing = await get_pricing_settings(config.database_path)
                        
                        # Якщо налаштування не знайдено - використати дефолтні значення
                        if pricing is None:
                            from app.storage.db import PricingSettings
                            pricing = PricingSettings()
                        
                        custom_multipliers = {
                            "economy": pricing.economy_multiplier,
                            "standard": pricing.standard_multiplier,
                            "comfort": pricing.comfort_multiplier,
                            "business": pricing.business_multiplier
                        }
                        
                        car_class = data.get('car_class', 'economy')
                        class_fare = calculate_fare_with_class(base_fare, car_class, custom_multipliers)
                        
                        # Динамічне ціноутворення (ТАК ЯК ДЛЯ КЛІЄНТА!)
                        from app.handlers.dynamic_pricing import calculate_dynamic_price, get_surge_emoji
                        
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
                
                # ⭐ СИСТЕМА ПРІОРИТЕТНИХ ЗАМОВЛЕНЬ ⭐
                from app.storage.db import get_online_drivers
                from app.storage.db_connection import db_manager
                from app.utils.priority_order_manager import PriorityOrderManager
                
                # Отримати онлайн водіїв міста
                online_drivers = await get_online_drivers(config.database_path, client_city or data.get('city'))
                
                # Перевірити чи є водії з увімкненим пріоритетом (priority > 0)
                # Якщо є - використовувати пріоритетну систему автоматично
                # Безпечне порівняння: priority може бути строкою
                priority_drivers_count = len([d for d in online_drivers if hasattr(d, 'priority') and int(d.priority or 0) > 0])
                
                logger.info(f"🎯 Онлайн водіїв: {len(online_drivers)}")
                logger.info(f"🎯 Водіїв з пріоритетом (priority > 0): {priority_drivers_count}")
                logger.info(f"🎯 Клас авто замовлення: {data.get('car_class', 'economy')}")
                logger.info(f"🎯 Місто клієнта: {client_city}")
                
                # Підготувати деталі замовлення для відправки
                order_details = {
                    'name': data.get('name'),
                    'phone': data.get('phone'),
                    'pickup': data.get('pickup'),
                    'destination': data.get('destination'),
                    'comment': data.get('comment'),
                    'pickup_lat': data.get('pickup_lat'),
                    'pickup_lon': data.get('pickup_lon'),
                    'dest_lat': data.get('dest_lat'),
                    'dest_lon': data.get('dest_lon'),
                    'distance_m': data.get('distance_m'),
                    'duration_s': data.get('duration_s'),
                    'estimated_fare': estimated_fare if 'estimated_fare' in locals() else None,
                    'car_class': data.get('car_class', 'economy'),
                    'db_path': config.database_path,
                }
                
                # Спробувати відправити пріоритетним водіям якщо є хоча б один з priority > 0
                from app.utils.priority_order_manager import PriorityOrderManager
                sent_to_priority = False
                if priority_drivers_count > 0 and online_drivers:
                    sent_to_priority = await PriorityOrderManager.send_to_priority_drivers(
                        bot=message.bot,
                        order_id=order_id,
                        drivers=online_drivers,
                        order_details=order_details,
                        db_path=config.database_path,
                        city_group_id=city_group_id
                    )
                
                # Якщо не відправлено пріоритетним - відправити в групу одразу
                if not sent_to_priority:
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
                    
                    # ⭐ ПЕРЕТВОРИТИ КООРДИНАТИ В АДРЕСИ (для групи водіїв)
                    from app.handlers.driver_panel import clean_address
                    from app.utils.maps import reverse_geocode
                    
                    pickup_display = data.get('pickup', '')
                    destination_display = data.get('destination', '')
                    
                    # Якщо є координати - спробувати геокодувати в адресу
                    if pickup_lat and pickup_lon:
                        # Перевірити чи це координати (містить числа з крапкою)
                        if '.' in str(pickup_display) and any(char.isdigit() for char in str(pickup_display)):
                            logger.info(f"🔄 [GROUP] Координати виявлені в pickup, геокодую: {pickup_display}")
                            try:
                                readable_address = await reverse_geocode("", float(pickup_lat), float(pickup_lon))
                                if readable_address:
                                    pickup_display = readable_address
                                    logger.info(f"✅ [GROUP] Pickup геокодовано: {pickup_display}")
                            except Exception as e:
                                logger.error(f"❌ [GROUP] Помилка геокодування pickup: {e}")
                    
                    if dest_lat and dest_lon:
                        # Перевірити чи це координати
                        if '.' in str(destination_display) and any(char.isdigit() for char in str(destination_display)):
                            logger.info(f"🔄 [GROUP] Координати виявлені в destination, геокодую: {destination_display}")
                            try:
                                readable_address = await reverse_geocode("", float(dest_lat), float(dest_lon))
                                if readable_address:
                                    destination_display = readable_address
                                    logger.info(f"✅ [GROUP] Destination геокодовано: {destination_display}")
                            except Exception as e:
                                logger.error(f"❌ [GROUP] Помилка геокодування destination: {e}")
                    
                    # Очистити адреси від Plus Codes (якщо залишились)
                    clean_pickup = clean_address(pickup_display)
                    clean_destination = clean_address(destination_display)
                    
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
                            logger.error(f"Failed to send order to city group {city_group_id} (City: {client_city}): {e}")
                            
                            # Повідомити адміну про проблему
                            for admin_id in config.bot.admin_ids:
                                try:
                                    await message.bot.send_message(
                                        admin_id,
                                        f"⚠️ <b>ПОМИЛКА ВІДПРАВКИ ЗАМОВЛЕННЯ</b>\n\n"
                                        f"📍 Місто: {client_city}\n"
                                        f"🆔 ID групи: <code>{city_group_id}</code>\n"
                                        f"❌ Помилка: {e}\n\n"
                                        f"💡 Перевірте налаштування групи:\n"
                                        f"• Використайте команду /check_groups\n"
                                        f"• Переконайтесь що бот доданий до групи\n"
                                        f"• Перевірте ID групи в ENV змінних",
                                        parse_mode="HTML"
                                    )
                                except Exception as e:
                                    pass
                            
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
                                    
                                    # Повідомити адміну що fallback спрацював
                                    for admin_id in config.bot.admin_ids:
                                        try:
                                            await message.bot.send_message(
                                                admin_id,
                                                f"✅ <b>Fallback спрацював</b>\n\n"
                                                f"Замовлення #{order_id} відправлено в загальну групу\n"
                                                f"🆔 ID: <code>{config.driver_group_chat_id}</code>",
                                                parse_mode="HTML"
                                            )
                                        except Exception as e:
                                            pass
                                except Exception as e2:
                                    logger.error(f"❌ Fallback також не вдався: {e2}")
                                    # Повідомити адміну що fallback теж не спрацював
                                    for admin_id in config.bot.admin_ids:
                                        try:
                                            await message.bot.send_message(
                                                admin_id,
                                                f"🚨 <b>КРИТИЧНА ПОМИЛКА</b>\n\n"
                                                f"Замовлення #{order_id} НЕ ВІДПРАВЛЕНО!\n"
                                                f"❌ Fallback група також недоступна\n\n"
                                                f"🆔 Fallback ID: <code>{config.driver_group_chat_id}</code>\n"
                                                f"❌ Помилка: {e2}\n\n"
                                                f"⚠️ ТЕРМІНОВО перевірте /check_groups",
                                                parse_mode="HTML"
                                            )
                                        except Exception as e:
                                            pass
                        
                        if not successfully_sent:
                            raise RuntimeError("Не вдалося надіслати повідомлення у жодну групу")
                        
                        # Зберегти ID повідомлення в БД
                        await update_order_group_message(config.database_path, order_id, sent_message.message_id)
                        logger.info(f"💾 group_message_id збережено: order_id={order_id}, message_id={sent_message.message_id}, group_id={used_group_id}")
                        
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
                        
                        # ⭐ СПОЧАТКУ відправити Reply клавіатуру
                        from app.storage.db import get_driver_by_tg_user_id
                        driver = await get_driver_by_tg_user_id(config.database_path, user_id)
                        is_driver = driver is not None and driver.status == "approved"
                        
                        kb_reply = main_menu_keyboard(
                            is_registered=True,
                            is_driver=is_driver,
                            is_admin=is_admin
                        )
                        
                        # Inline кнопка для скасування замовлення
                        kb_cancel = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text="❌ Скасувати замовлення", callback_data=f"cancel_waiting_order:{order_id}")]
                            ]
                        )
                        
                        # Відправити ОДНЕ повідомлення з ОБОМА клавіатурами (inline + reply)
                        status_message = format_process_message('searching', 'Шукаємо водія...')
                        client_message = await message.answer(
                            f"{get_status_emoji('pending')} <b>Замовлення #{order_id} прийнято!</b>\n\n"
                            f"{status_message}\n\n"
                            "Ваше замовлення надіслано водіям.\n"
                            "Очікуйте підтвердження! ⏳",
                            reply_markup=kb_cancel
                        )
                        
                        # Відправити клавіатуру окремим повідомленням (для надійності)
                        await message.bot.send_message(
                            chat_id=user_id,
                            text="📱",
                            reply_markup=kb_reply
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
                
                # Відправити зрозуміле повідомлення користувачу
                await message.answer(
                    f"✅ <b>Замовлення #{order_id} створено!</b>\n\n"
                    f"⚠️ Наразі виникли технічні проблеми з відправкою водіям.\n\n"
                    f"📞 <b>Що робити:</b>\n"
                    f"1. Зачекайте кілька хвилин\n"
                    f"2. Спробуйте створити замовлення ще раз\n"
                    f"3. Зверніться до адміністратора якщо проблема повторюється\n\n"
                    f"💡 Адміністратор вже повідомлений про проблему.",
                    reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin),
                    parse_mode="HTML"
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
        except Exception as e:
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
            # 🛑 Зупинити всі менеджери для цього замовлення
            from app.utils.live_location_manager import LiveLocationManager
            from app.utils.priority_order_manager import PriorityOrderManager
            from app.utils.order_timeout import cancel_order_timeout
            
            await LiveLocationManager.stop_tracking(order_id)
            PriorityOrderManager.cancel_priority_timer(order_id)
            cancel_order_timeout(order_id)
            
            # 🚗 ПОВІДОМИТИ ВОДІЯ якщо замовлення було прийнято
            if order.driver_id and order.status == 'accepted':
                try:
                    from app.storage.db import get_driver_by_id
                    from app.handlers.keyboards import driver_panel_keyboard
                    
                    driver = await get_driver_by_id(config.database_path, order.driver_id)
                    if driver:
                        await call.bot.send_message(
                            driver.tg_user_id,
                            f"❌ <b>Замовлення #{order.id} скасовано клієнтом</b>\n\n"
                            f"📍 Маршрут: {order.pickup_address} → {order.destination_address}\n\n"
                            f"ℹ️ Клієнт відмовився від замовлення.\n"
                            f"Ваша карма не змінилася.",
                            reply_markup=driver_panel_keyboard()
                        )
                        logger.info(f"✅ Водій {driver.full_name} повідомлений про скасування #{order.id}")
                except Exception as e:
                    logger.error(f"❌ Не вдалося повідомити водія: {e}")
            
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
                            # Ігноруємо помилку якщо повідомлення вже видалене
                            if "message to edit not found" in str(ee).lower() or "message can't be edited" in str(ee).lower():
                                logger.warning(f"⚠️ Повідомлення #{order.group_message_id} в групі {chat_id} не знайдено (можливо вже видалене)")
                            else:
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
            except Exception as e:
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
                    
                    # ⭐ ПЕРЕТВОРИТИ КООРДИНАТИ В АДРЕСИ (для оновлення групи)
                    from app.handlers.driver_panel import clean_address
                    from app.utils.maps import reverse_geocode
                    
                    pickup_display = order.pickup_address
                    destination_display = order.destination_address
                    
                    # Якщо є координати - спробувати геокодувати в адресу
                    if order.pickup_lat and order.pickup_lon:
                        # Перевірити чи це координати
                        if '.' in str(pickup_display) and any(char.isdigit() for char in str(pickup_display)):
                            logger.info(f"🔄 [GROUP UPDATE] Координати в pickup, геокодую: {pickup_display}")
                            try:
                                readable_address = await reverse_geocode("", float(order.pickup_lat), float(order.pickup_lon))
                                if readable_address:
                                    pickup_display = readable_address
                                    logger.info(f"✅ [GROUP UPDATE] Pickup геокодовано: {pickup_display}")
                            except Exception as e:
                                logger.error(f"❌ [GROUP UPDATE] Помилка геокодування pickup: {e}")
                    
                    if order.dest_lat and order.dest_lon:
                        # Перевірити чи це координати
                        if '.' in str(destination_display) and any(char.isdigit() for char in str(destination_display)):
                            logger.info(f"🔄 [GROUP UPDATE] Координати в destination, геокодую: {destination_display}")
                            try:
                                readable_address = await reverse_geocode("", float(order.dest_lat), float(order.dest_lon))
                                if readable_address:
                                    destination_display = readable_address
                                    logger.info(f"✅ [GROUP UPDATE] Destination геокодовано: {destination_display}")
                            except Exception as e:
                                logger.error(f"❌ [GROUP UPDATE] Помилка геокодування destination: {e}")
                    
                    # Очистити адреси від Plus Codes для кращої читабельності
                    clean_pickup = clean_address(pickup_display)
                    clean_destination = clean_address(destination_display)
                    
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
                # Ігноруємо помилку якщо повідомлення вже видалене
                if "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
                    logger.warning(f"⚠️ Повідомлення в групі не знайдено (можливо вже видалене): {e}")
                else:
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
            # 🛑 Зупинити всі менеджери для цього замовлення
            from app.utils.live_location_manager import LiveLocationManager
            from app.utils.priority_order_manager import PriorityOrderManager
            from app.utils.order_timeout import cancel_order_timeout
            
            await LiveLocationManager.stop_tracking(order_id)
            PriorityOrderManager.cancel_priority_timer(order_id)
            cancel_order_timeout(order_id)
            
            await call.answer("✅ Замовлення скасовано", show_alert=True)
            
            # Видалити повідомлення з пропозицією
            try:
                await call.message.delete()
            except Exception as e:
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
                            # Ігноруємо помилку якщо повідомлення вже видалене
                            if "message to edit not found" in str(ee).lower() or "message can't be edited" in str(ee).lower():
                                logger.warning(f"⚠️ Повідомлення #{order.group_message_id} в групі {chat_id} не знайдено (можливо вже видалене)")
                            else:
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
            
            # Відправити підтвердження з клавіатурою
            from app.handlers.keyboards import main_menu_keyboard
            from app.storage.db import get_driver_by_tg_user_id
            
            user = await get_user_by_id(config.database_path, call.from_user.id)
            driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
            
            is_driver = driver is not None and driver.status == "approved"
            is_admin = user and call.from_user.id in config.bot.admin_ids if user else False
            is_blocked = user.is_blocked if user else False
            is_registered = user is not None and user.role == "client"
            
            kb = main_menu_keyboard(
                is_registered=is_registered,
                is_driver=is_driver,
                is_admin=is_admin,
                is_blocked=is_blocked
            )
            
            await call.bot.send_message(
                call.from_user.id,
                "✅ <b>Замовлення скасовано</b>\n\n"
                "Ви можете створити нове замовлення будь-коли.",
                reply_markup=kb
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
            except Exception as e:
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
        
        status_message = format_process_message('searching', 'Шукаємо водія...')
        await call.bot.send_message(
            call.from_user.id,
            f"{status_message}\n\n"
            f"📍 Звідки: {order.pickup_address}\n"
            f"📍 Куди: {order.destination_address}\n\n"
            f"💰 Вартість: <b>{current_fare:.0f} грн</b>\n\n"
            f"⏳ Зачекайте, будь ласка...",
            reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
        )
        
        logger.info(f"⏳ Клієнт #{call.from_user.id} вирішив продовжити очікування без підвищення ціни (замовлення #{order_id})")
    
    return router
