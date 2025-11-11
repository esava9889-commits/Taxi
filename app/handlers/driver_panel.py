"""НОВИЙ кабінет водія - версія 3.0"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

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

# Глобальний set для захисту від подвійного натискання "Завершити поїздку"
_finishing_orders = set()

# Глобальний словник для збереження message_id повідомлень водія по замовленню
# Формат: {order_id: [message_id1, message_id2, ...]}
_order_messages: dict[int, list[int]] = {}


def add_order_message(order_id: int, message_id: int) -> None:
    """Додати message_id до списку повідомлень замовлення"""
    if order_id not in _order_messages:
        _order_messages[order_id] = []
    _order_messages[order_id].append(message_id)
    logger.debug(f"📝 Збережено message_id={message_id} для замовлення #{order_id}")


async def clear_order_messages(bot, chat_id: int, order_id: int) -> None:
    """Видалити всі повідомлення замовлення з чату водія"""
    if order_id not in _order_messages:
        logger.debug(f"🔍 Немає збережених повідомлень для замовлення #{order_id}")
        return
    
    message_ids = _order_messages.pop(order_id)
    logger.info(f"🧹 Очищення {len(message_ids)} повідомлень для замовлення #{order_id}")
    
    deleted_count = 0
    for msg_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            deleted_count += 1
        except Exception as e:
            logger.debug(f"⚠️ Не вдалося видалити message_id={msg_id}: {e}")
    
    logger.info(f"✅ Видалено {deleted_count}/{len(message_ids)} повідомлень з чату водія")
from app.storage.db import (
    get_driver_by_tg_user_id,
    get_driver_by_id,
    get_order_by_id,
    accept_order,
    start_order,
    complete_order,
    get_driver_earnings_today,
    get_driver_detailed_earnings_today,
    get_active_order_for_driver,
    cancel_order_by_driver,
    get_driver_unpaid_commission,
    get_driver_order_history,
    mark_commission_paid,
    Payment,
    insert_payment,
    get_latest_tariff,
    update_driver_location,
    set_driver_online_status,
    get_online_drivers_count,
    get_driver_tips_total,
)
from app.utils.rate_limiter import check_rate_limit, get_time_until_reset, format_time_remaining
from app.utils.order_timeout import cancel_order_timeout
from app.utils.visual import (
    format_earnings_infographic,
    format_driver_stats,
    format_karma,
    get_karma_emoji,
    create_box,
    get_status_emoji,
    get_status_text_with_emoji,
    format_process_message,
)

logger = logging.getLogger(__name__)


def clean_address(address: str) -> str:
    """
    Очистити адресу від Plus Codes та зайвих символів.
    
    Plus Code - це коди типу "PMQC+G9" які Google додає до адрес.
    Вони не потрібні для читабельності.
    """
    import re
    
    if not address:
        return "Не вказано"
    
    # Видалити Plus Codes (формат: 4-8 символів + '+' + 2-3 символи)
    # Приклади: PMQC+G9, 8FWX+23, ABCD+EF
    address = re.sub(r'\b[A-Z0-9]{4,8}\+[A-Z0-9]{2,3}\b', '', address)
    
    # Видалити зайві пробіли
    address = re.sub(r'\s+', ' ', address)
    
    # Видалити пробіли на початку і в кінці
    address = address.strip()
    
    # Видалити коми на початку (якщо залишились після видалення Plus Code)
    address = re.sub(r'^[,\s]+', '', address)
    
    return address if address else "Не вказано"


def driver_panel_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура панелі водія - НОВА ВЕРСІЯ З КАРМОЮ"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Почати роботу")],
            [KeyboardButton(text="⚙️ Особиста інформація"), KeyboardButton(text="💳 Комісія")],
            [KeyboardButton(text="📜 Історія поїздок"), KeyboardButton(text="💼 Гаманець")],
            [KeyboardButton(text="👤 Кабінет клієнта"), KeyboardButton(text="ℹ️ Допомога")],
            [KeyboardButton(text="📖 Правила користування")]
        ],
        resize_keyboard=True
    )


# FSM стани для заповнення профілю водія
class DriverProfileStates(StatesGroup):
    waiting_for_city = State()
    waiting_for_color = State()
    waiting_for_card = State()
    waiting_for_location = State()  # Очікування геолокації для оновлення
    waiting_for_location_to_accept = State()  # Очікування геолокації для прийняття замовлення


def create_router(config: AppConfig) -> Router:
    router = Router(name="driver_panel")

    @router.message(F.text == "🚗 Панель водія")
    async def driver_panel_main(message: Message) -> None:
        """Головна панель водія - НОВА ВЕРСІЯ 3.0"""
        if not message.from_user:
            return
        
        # 🚫 ПЕРЕВІРКА БЛОКУВАННЯ
        from app.handlers.driver_blocked_check import check_driver_blocked_and_notify
        if await check_driver_blocked_and_notify(config.database_path, message):
            return
        
        # Видалити повідомлення користувача для чистого чату
        try:
            await message.delete()
        except:
            pass
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            await message.answer(
                "❌ Ви не зареєстровані як водій або ваша заявка ще не підтверджена."
            )
            return
        
        # ⭐ ПЕРЕВІРКА АКТИВНОГО ЗАМОВЛЕННЯ
        active_order = await get_active_order_for_driver(config.database_path, driver.id)
        
        # Заробіток
        earnings, commission = await get_driver_earnings_today(config.database_path, message.from_user.id)
        net = earnings - commission
        
        # Чайові
        tips = 0.0
        try:
            tips = await get_driver_tips_total(config.database_path, message.from_user.id)
        except:
            tips = 0.0
        
        # Статус
        status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        
        # Статус локації з віком
        from app.utils.location_tracker import check_driver_location_status
        loc_status = await check_driver_location_status(config.database_path, message.from_user.id)
        
        if not loc_status['has_location']:
            location = "❌ Не встановлена"
        else:
            age = loc_status['age_minutes']
            if loc_status['status'] == 'fresh':
                location = f"📍 Активна ({age} хв тому)"
            elif loc_status['status'] == 'warning':
                location = f"⚠️ Потребує оновлення ({age} хв тому)"
            else:
                location = f"🔴 Застаріла ({age} хв тому)"
        
        # Онлайн водії
        online = 0
        try:
            online = await get_online_drivers_count(config.database_path, driver.city)
        except:
            online = 0
        
        # ТЕКСТ з усіма полями
        text = (
            f"🚗 <b>Панель водія</b>\n\n"
            f"Статус: {status}\n"
            f"Локація: {location}\n"
            f"ПІБ: {driver.full_name}\n"
            f"🏙 Місто: {driver.city or 'Не вказано'}\n"
            f"👥 Водіїв онлайн: {online}\n"
            f"🚙 Авто: {driver.car_make} {driver.car_model}\n"
            f"🔢 Номер: {driver.car_plate}\n\n"
            f"💰 Заробіток сьогодні: {earnings:.2f} грн\n"
            f"💸 Комісія до сплати: {commission:.2f} грн\n"
            f"💵 Чистий заробіток: {net:.2f} грн\n"
            f"💝 Чайові (всього): {tips:.2f} грн\n\n"
        )
        
        # ⭐ ЯКЩО Є АКТИВНЕ ЗАМОВЛЕННЯ - показати попередження
        if active_order:
            order_status_emoji = "✅" if active_order.status == "accepted" else "🚗"
            order_status_text = "Прийнято" if active_order.status == "accepted" else "В дорозі"
            
            text += (
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⚠️ <b>У ВАС Є АКТИВНЕ ЗАМОВЛЕННЯ!</b>\n\n"
                f"{order_status_emoji} Замовлення #{active_order.id}\n"
                f"📊 Статус: {order_status_text}\n"
                f"👤 Клієнт: {active_order.name}\n"
                f"💰 Вартість: {int(active_order.fare_amount):.0f} грн\n\n"
                f"👇 <b>Натисніть кнопку нижче для керування!</b>"
            )
        else:
            text += "ℹ️ Замовлення надходять у групу водіїв.\n\n👇 Натисніть '🚀 Почати роботу' для керування"
        
        # ⭐ КЛАВІАТУРА - різна для активного замовлення і без
        if active_order:
            kb = ReplyKeyboardMarkup(
                keyboard=[
                    # ВЕЛИКА КНОПКА для повернення до замовлення
                    [KeyboardButton(text="🚗 КЕРУВАТИ ЗАМОВЛЕННЯМ")],
                    [KeyboardButton(text="⚙️ Особиста інформація"), KeyboardButton(text="💳 Комісія")],
                    [KeyboardButton(text="📜 Історія поїздок"), KeyboardButton(text="💼 Гаманець")],
                    [KeyboardButton(text="👤 Кабінет клієнта"), KeyboardButton(text="ℹ️ Допомога")]
                ],
                resize_keyboard=True
            )
        else:
            kb = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="🚀 Почати роботу")],
                    [KeyboardButton(text="⚙️ Особиста інформація"), KeyboardButton(text="💳 Комісія")],
                    [KeyboardButton(text="📜 Історія поїздок"), KeyboardButton(text="💼 Гаманець")],
                    [KeyboardButton(text="👤 Кабінет клієнта"), KeyboardButton(text="ℹ️ Допомога")]
                ],
                resize_keyboard=True
            )
        
        await message.answer(text, reply_markup=kb)

    @router.message(F.text == "🚗 КЕРУВАТИ ЗАМОВЛЕННЯМ")
    async def manage_active_order(message: Message) -> None:
        """Повернутися до керування активним замовленням"""
        if not message.from_user:
            return
        
        # Видалити повідомлення користувача
        try:
            await message.delete()
        except:
            pass
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            await message.answer("❌ Водія не знайдено")
            return
        
        # Отримати активне замовлення
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer(
                "❌ У вас немає активного замовлення.\n\n"
                "Замовлення надходять у групу водіїв."
            )
            return
        
        # ⭐ Очистити адреси і створити посилання
        clean_pickup = clean_address(order.pickup_address)
        clean_destination = clean_address(order.destination_address)
        
        pickup_link = ""
        destination_link = ""
        
        if order.pickup_lat and order.pickup_lon:
            pickup_link = f"<a href='https://www.google.com/maps?q={order.pickup_lat},{order.pickup_lon}'>📍 Відкрити на карті</a>"
        
        if order.dest_lat and order.dest_lon:
            destination_link = f"<a href='https://www.google.com/maps?q={order.dest_lat},{order.dest_lon}'>📍 Відкрити на карті</a>"
        
        # Відстань
        distance_text = ""
        if order.distance_m:
            km = order.distance_m / 1000.0
            distance_text = f"\n📏 Відстань: {km:.1f} км"
        
        # Спосіб оплати
        payment_emoji = "💵" if order.payment_method == "cash" else "💳"
        payment_text = "Готівка" if order.payment_method == "cash" else "Картка"
        
        # Статус замовлення
        status_emoji = "✅" if order.status == "accepted" else "🚗"
        status_text = "Прийнято" if order.status == "accepted" else "В дорозі"
        
        # ПОВІДОМЛЕННЯ
        text = (
            f"{status_emoji} <b>АКТИВНЕ ЗАМОВЛЕННЯ #{order.id}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>📋 ІНФОРМАЦІЯ:</b>\n\n"
            f"📊 Статус: <b>{status_text}</b>\n"
            f"👤 Клієнт: {order.name}\n"
            f"📱 Телефон: <code>{order.phone}</code>\n\n"
            f"📍 <b>Звідки забрати:</b>\n{clean_pickup}\n"
            f"{pickup_link}\n\n"
            f"🎯 <b>Куди везти:</b>\n{clean_destination}\n"
            f"{destination_link}{distance_text}\n\n"
            f"💰 Вартість: <b>{int(order.fare_amount):.0f} грн</b>\n"
            f"{payment_emoji} Оплата: {payment_text}\n"
        )
        
        if order.comment:
            text += f"\n💬 <b>Коментар клієнта:</b>\n<i>{order.comment}</i>\n"
        
        text += (
            f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>📍 ЕТАПИ ВИКОНАННЯ:</b>\n\n"
            f"1️⃣ <b>Їдьте до клієнта</b>\n"
            f"   Натисніть: <b>📍 Я НА МІСЦІ ПОДАЧІ</b>\n\n"
            f"2️⃣ <b>Клієнт сів в авто</b>\n"
            f"   Натисніть: <b>✅ КЛІЄНТ В АВТО</b>\n\n"
            f"3️⃣ <b>Довезли до місця призначення</b>\n"
            f"   Натисніть: <b>🏁 ЗАВЕРШИТИ ПОЇЗДКУ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 <b>Використовуйте кнопки внизу для керування!</b>"
        )
        
        # КЛАВІАТУРА для керування
        kb = ReplyKeyboardMarkup(
            keyboard=[
                # ======== ОСНОВНЕ КЕРУВАННЯ ========
                [KeyboardButton(text="📍 Я НА МІСЦІ ПОДАЧІ")],
                [KeyboardButton(text="✅ КЛІЄНТ В АВТО")],
                [KeyboardButton(text="🏁 ЗАВЕРШИТИ ПОЇЗДКУ")],
                
                # ======== ДОДАТКОВІ ФУНКЦІЇ ========
                [
                    KeyboardButton(text="📞 Клієнт"),
                    KeyboardButton(text="🗺️ Маршрут")
                ],
                [
                    KeyboardButton(text="❌ Скасувати замовлення"),
                    KeyboardButton(text="🚗 Панель водія")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Керування поїздкою"
        )
        
        # Відправити повідомлення і зберегти message_id для подальшого видалення
        sent_msg = await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
        add_order_message(order.id, sent_msg.message_id)

    @router.message(F.text == "🚀 Почати роботу")
    async def start_work(message: Message) -> None:
        """Меню керування роботою - розширена версія"""
        if not message.from_user:
            return
        
        # 🚫 ПЕРЕВІРКА БЛОКУВАННЯ
        from app.handlers.driver_blocked_check import check_driver_blocked_and_notify
        if await check_driver_blocked_and_notify(config.database_path, message):
            return
        
        # Видалити повідомлення користувача для чистого чату
        try:
            await message.delete()
        except:
            pass
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        status_emoji = "🟢" if driver.online else "🔴"
        
        # Статистика
        online = 0
        try:
            online = await get_online_drivers_count(config.database_path, driver.city)
        except:
            pass
        
        # Активне замовлення
        active_order = await get_active_order_for_driver(config.database_path, driver.id)
        
        # Заробіток сьогодні
        earnings_today = 0
        commission_today = 0
        try:
            earnings_today, commission_today = await get_driver_earnings_today(
                config.database_path, 
                message.from_user.id
            )
        except:
            pass
        
        # Текст статусу
        if active_order:
            order_status = (
                f"📦 <b>Активне замовлення:</b> #{active_order.id}\n"
                f"📍 {active_order.pickup_address[:30]}... → {active_order.destination_address[:30]}...\n"
                f"💰 {int(active_order.fare_amount):.0f} грн\n\n"
            )
        else:
            order_status = ""
        
        # Кнопки (прибрано "📍 Оновити геолокацію" - тепер геолокація запитується при прийнятті замовлення)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{status_emoji} УВІМКНУТИ ОНЛАЙН" if not driver.online else "🔴 ПІТИ В ОФЛАЙН",
                    callback_data="work:toggle"
                )],
                [
                    InlineKeyboardButton(text="📊 Статистика", callback_data="work:stats"),
                    InlineKeyboardButton(text="💰 Заробіток", callback_data="work:earnings")
                ],
                [InlineKeyboardButton(text="🔄 Оновити", callback_data="work:refresh")]
            ]
        )
        
        # Посилання на групу водіїв для міста
        city_invite_link = None
        city_group_id = None
        if driver.city:
            city_invite_link = config.city_invite_links.get(driver.city)
            city_group_id = config.city_groups.get(driver.city)
        
        # Текст про групу
        if city_invite_link:
            group_text = f"📢 <a href=\"{city_invite_link}\">Група водіїв {driver.city}</a>\n"
        elif city_group_id:
            group_text = f"📢 Група: {driver.city} (налаштована)\n"
        else:
            group_text = f"📢 Група: {driver.city or 'не налаштовано'}\n"
        
        text = (
            f"🚀 <b>МЕНЮ КЕРУВАННЯ РОБОТОЮ</b>\n\n"
            f"{group_text}"
            f"📊 <b>Статус:</b> {status}\n\n"
            f"Оберіть дію:"
        )
        
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "work:toggle")
    async def toggle_status(call: CallbackQuery) -> None:
        """Перемкнути онлайн/офлайн"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            return
        
        # ВАЛІДАЦІЯ ПРОФІЛЮ перед увімкненням онлайн (БЕЗ геолокації!)
        if not driver.online:  # Якщо намагається увімкнути онлайн
            car_color = getattr(driver, 'car_color', None)
            missing = []
            if not driver.city:
                missing.append("🏙 Місто")
            if not driver.card_number:
                missing.append("💳 Картка для переказів")
            if not car_color:
                missing.append("🎨 Колір авто")
            # ❌ ВИДАЛЕНО: Перевірка геолокації - не обов'язкова для онлайн
            
            if missing:
                await call.answer(
                    f"❌ ПРОФІЛЬ НЕ ЗАПОВНЕНИЙ!\n\n"
                    f"Відсутні:\n" + "\n".join(f"• {m}" for m in missing) + 
                    f"\n\n👉 Заповніть дані!",
                    show_alert=True
                )
                # Відправити повідомлення з кнопкою "Оновити"
                kb_refresh = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Оновити", callback_data="work:refresh")]
                    ]
                )
                await call.bot.send_message(
                    call.from_user.id,
                    f"⚠️ <b>НЕ МОЖНА УВІМКНУТИ ОНЛАЙН</b>\n\n"
                    f"Для роботи необхідно заповнити профіль!\n\n"
                    f"<b>Відсутні дані:</b>\n" +
                    "\n".join(f"• {m}" for m in missing) +
                    f"\n\n💡 Додайте картку в <b>💼 Гаманець</b>\n"
                    f"Вкажіть місто в <b>⚙️ Особиста інформація</b>",
                    reply_markup=kb_refresh
                )
                return
        
        new = not driver.online
        await set_driver_online_status(config.database_path, driver.id, new)
        
        online = await get_online_drivers_count(config.database_path, driver.city)
        
        # Push-повідомлення при зміні статусу
        if new:
            await call.answer(f"✅ Ви онлайн! Водіїв: {online}", show_alert=True)
            # Відправити push-повідомлення про статус онлайн
            try:
                city_name = driver.city if driver.city else "вашому місті"
                await call.bot.send_message(
                    call.from_user.id,
                    f"🟢 <b>Статус: ОНЛАЙН</b>\n\n"
                    f"Ви тепер онлайн і готові приймати замовлення!\n\n"
                    f"👥 Онлайн водіїв у {city_name}: {online}\n\n"
                    f"📢 Замовлення надходять у групу водіїв.\n"
                    f"Прийміть замовлення першим!",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Failed to send online status push: {e}")
        else:
            await call.answer("🔴 Ви офлайн", show_alert=True)
            # Відправити push-повідомлення про статус офлайн
            try:
                await call.bot.send_message(
                    call.from_user.id,
                    f"🔴 <b>Статус: ОФЛАЙН</b>\n\n"
                    f"Ви пішли в офлайн.\n\n"
                    f"Ви не будете отримувати нові замовлення.\n\n"
                    f"💡 Щоб почати працювати знову, увімкніть статус онлайн.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Failed to send offline status push: {e}")
        
        # Оновити
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🟢 ПОЧАТИ ПРАЦЮВАТИ" if not driver.online else "🔴 ПІТИ В ОФЛАЙН",
                    callback_data="work:toggle"
                )],
                [InlineKeyboardButton(text="📊 Статистика", callback_data="work:stats")],
                [InlineKeyboardButton(text="🔄 Оновити", callback_data="work:refresh")]
            ]
        )
        
        if call.message:
            await call.message.edit_text(
                f"🚀 <b>Меню керування</b>\n\n"
                f"Статус: {status}\n"
                f"👥 Водіїв онлайн: {online}\n\n"
                "Оберіть дію:",
                reply_markup=kb
            )

    @router.callback_query(F.data == "work:refresh")
    async def refresh_menu(call: CallbackQuery) -> None:
        """Оновити меню - РОЗШИРЕНА ВЕРСІЯ"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            return
        
        status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        status_emoji = "🟢" if driver.online else "🔴"
        
        online = 0
        try:
            online = await get_online_drivers_count(config.database_path, driver.city)
        except:
            pass
        
        # Активне замовлення
        active_order = await get_active_order_for_driver(config.database_path, driver.id)
        
        # Заробіток сьогодні
        earnings_today = 0
        commission_today = 0
        try:
            earnings_today, commission_today = await get_driver_earnings_today(
                config.database_path, 
                call.from_user.id
            )
        except:
            pass
        
        if active_order:
            order_status = (
                f"📦 <b>Активне замовлення:</b> #{active_order.id}\n"
                f"📍 {active_order.pickup_address[:30]}... → {active_order.destination_address[:30]}...\n"
                f"💰 {int(active_order.fare_amount):.0f} грн\n\n"
            )
        else:
            order_status = ""
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{status_emoji} УВІМКНУТИ ОНЛАЙН" if not driver.online else "🔴 ПІТИ В ОФЛАЙН",
                    callback_data="work:toggle"
                )],
                [
                    InlineKeyboardButton(text="📊 Статистика", callback_data="work:stats"),
                    InlineKeyboardButton(text="💰 Заробіток", callback_data="work:earnings")
                ],
                [InlineKeyboardButton(text="🔄 Оновити", callback_data="work:refresh")]
            ]
        )
        
        # Посилання на групу водіїв для міста
        city_invite_link = None
        city_group_id = None
        if driver.city:
            city_invite_link = config.city_invite_links.get(driver.city)
            city_group_id = config.city_groups.get(driver.city)
        
        # Текст про групу
        if city_invite_link:
            group_text = f"📢 <a href=\"{city_invite_link}\">Група водіїв {driver.city}</a>\n"
        elif city_group_id:
            group_text = f"📢 Група: {driver.city} (налаштована)\n"
        else:
            group_text = f"📢 Група: {driver.city or 'не налаштовано'}\n"
        
        text = (
            f"🚀 <b>МЕНЮ КЕРУВАННЯ РОБОТОЮ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Водій:</b> {driver.full_name}\n"
            f"🏙 <b>Місто:</b> {driver.city or '❌ Не вказано'}\n"
            f"{group_text}"
            f"📊 <b>Статус:</b> {status}\n\n"
            f"👥 <b>Водіїв онлайн:</b> {online} чол.\n"
            f"💰 <b>Заробіток сьогодні:</b> {earnings_today:.0f} грн\n"
            f"💳 <b>Комісія:</b> {commission_today:.0f} грн\n\n"
            f"{order_status}"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 <b>Швидкі дії:</b>\n"
            f"• Увімкніть 🟢 Онлайн щоб отримувати замовлення\n"
            f"• Замовлення надходять в групу <b>{driver.city or 'вашого міста'}</b>\n"
            f"• Перший хто натисне ✅ Прийняти - отримує замовлення\n\n"
            f"Оберіть дію:"
        )
        
        if call.message:
            await call.message.edit_text(text, reply_markup=kb)
        await call.answer("✅ Оновлено!")

    @router.callback_query(F.data == "work:update_location")
    async def update_location_request(call: CallbackQuery, state: FSMContext) -> None:
        """Запит на оновлення геолокації водія"""
        if not call.from_user:
            return
        
        # 🚫 ПЕРЕВІРКА БЛОКУВАННЯ
        from app.handlers.driver_blocked_check import check_driver_blocked_and_notify
        if await check_driver_blocked_and_notify(config.database_path, call):
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        # Встановити FSM стан
        await state.set_state(DriverProfileStates.waiting_for_location)
        
        # Створити Reply клавіатуру з кнопкою геолокації
        location_kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
                [KeyboardButton(text="❌ Скасувати")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await call.answer()
        
        # Відправити запит на геолокацію
        location_request_msg = await call.bot.send_message(
            call.from_user.id,
            "📍 <b>Оновлення геолокації</b>\n\n"
            "Натисніть кнопку 📍 <b>Надіслати геолокацію</b> нижче,\n"
            "щоб оновити вашу поточну позицію.\n\n"
            "💡 Геолокація потрібна для:\n"
            "• Розрахунку відстані до клієнта\n"
            "• Трансляції вашого руху клієнту\n"
            "• Автоматичного підбору замовлень",
            reply_markup=location_kb
        )
        
        # Зберегти ID повідомлення для подальшого видалення
        await state.update_data(location_request_msg_id=location_request_msg.message_id)
    
    @router.message(DriverProfileStates.waiting_for_location, F.location)
    async def handle_location_update(message: Message, state: FSMContext) -> None:
        """Обробка отриманої геолокації"""
        if not message.from_user or not message.location:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            await message.answer("❌ Водія не знайдено")
            await state.clear()
            return
        
        lat = message.location.latitude
        lon = message.location.longitude
        
        # Оновити геолокацію в БД (використовуємо tg_user_id, а не driver.id)
        await update_driver_location(config.database_path, message.from_user.id, lat, lon)
        
        logger.info(f"📍 Геолокацію водія {driver.full_name} оновлено: {lat}, {lon}")
        
        # Отримати ID повідомлення з запитом
        data = await state.get_data()
        location_request_msg_id = data.get("location_request_msg_id")
        
        # Відправити підтвердження
        success_msg = await message.answer(
            "✅ <b>Геолокацію оновлено!</b>\n\n"
            f"📍 Координати: {lat:.6f}, {lon:.6f}\n\n"
            "Тепер ви можете поділитися своїм рухом з клієнтами під час поїздки.",
            reply_markup=driver_panel_keyboard()
        )
        
        # Видалити повідомлення для чистоти чату
        try:
            # Видалити запит на геолокацію
            if location_request_msg_id:
                await message.bot.delete_message(message.from_user.id, location_request_msg_id)
            # Видалити повідомлення з геолокацією
            await message.delete()
            # Видалити підтвердження через 3 секунди
            import asyncio
            await asyncio.sleep(3)
            await success_msg.delete()
        except Exception as e:
            logger.debug(f"Не вдалося видалити повідомлення: {e}")
        
        # Очистити FSM стан
        await state.clear()
    
    @router.message(DriverProfileStates.waiting_for_location, F.text == "❌ Скасувати")
    async def cancel_location_update(message: Message, state: FSMContext) -> None:
        """Скасування оновлення геолокації"""
        if not message.from_user:
            return
        
        # Отримати ID повідомлення з запитом
        data = await state.get_data()
        location_request_msg_id = data.get("location_request_msg_id")
        
        # Видалити повідомлення
        try:
            if location_request_msg_id:
                await message.bot.delete_message(message.from_user.id, location_request_msg_id)
            await message.delete()
        except Exception as e:
            logger.debug(f"Не вдалося видалити повідомлення: {e}")
        
        await message.answer(
            "❌ Оновлення геолокації скасовано",
            reply_markup=driver_panel_keyboard()
        )
        
        # Очистити FSM стан
        await state.clear()
    
    @router.callback_query(F.data == "work:stats")
    async def show_stats_menu(call: CallbackQuery) -> None:
        """Статистика"""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📅 Сьогодні", callback_data="stats:today")],
                [InlineKeyboardButton(text="📅 Тиждень", callback_data="stats:week")],
                [InlineKeyboardButton(text="📅 Місяць", callback_data="stats:month")],
                [InlineKeyboardButton(text="« Назад", callback_data="work:refresh")]
            ]
        )
        if call.message:
            await call.message.edit_text("📊 <b>Статистика</b>\n\nОберіть період:", reply_markup=kb)
        await call.answer()
    
    @router.callback_query(F.data == "stats:today")
    async def show_stats_today(call: CallbackQuery) -> None:
        """Статистика за сьогодні"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        # Отримати статистику за сьогодні
        from datetime import datetime, timedelta, timezone
        from app.storage.db import get_driver_order_history
        
        # Сьогодні з початку дня
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Всі замовлення водія
        all_orders = await get_driver_order_history(config.database_path, driver.tg_user_id, limit=100)
        
        # Фільтрувати за сьогодні
        today_orders = []
        for order in all_orders:
            if order.created_at:
                order_time = order.created_at
                if isinstance(order_time, str):
                    try:
                        order_time = datetime.fromisoformat(order_time)
                    except:
                        continue
                
                if isinstance(order_time, datetime):
                    if order_time.replace(tzinfo=timezone.utc) >= today_start:
                        today_orders.append(order)
        
        # Підрахунок
        total_orders = len(today_orders)
        completed_orders = len([o for o in today_orders if o.status == 'completed'])
        cancelled_orders = len([o for o in today_orders if o.status == 'cancelled'])
        
        earnings = sum(o.fare_amount for o in today_orders if o.status == 'completed' and o.fare_amount)
        
        # Отримати комісію з тарифу
        from app.storage.db import get_latest_tariff
        tariff = await get_latest_tariff(config.database_path)
        commission_rate = tariff.commission_percent if tariff else 0.02
        commission = earnings * commission_rate
        net = earnings - commission
        commission_percent = int(commission_rate * 100)
        
        text = (
            f"📊 <b>СТАТИСТИКА ЗА СЬОГОДНІ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 <b>Всього замовлень:</b> {total_orders}\n"
            f"✅ <b>Виконано:</b> {completed_orders}\n"
            f"❌ <b>Скасовано:</b> {cancelled_orders}\n\n"
            f"💰 <b>Заробіток:</b> {earnings:.0f} грн\n"
            f"💳 <b>Комісія ({commission_percent}%):</b> {commission:.0f} грн\n"
            f"💵 <b>Чистий:</b> {net:.0f} грн\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📅 Дата: {datetime.now().strftime('%d.%m.%Y')}"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data="work:stats")]
            ]
        )
        
        if call.message:
            await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    
    @router.callback_query(F.data == "stats:week")
    async def show_stats_week(call: CallbackQuery) -> None:
        """Статистика за тиждень"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        from datetime import datetime, timedelta, timezone
        from app.storage.db import get_driver_order_history
        
        # 7 днів тому
        week_start = datetime.now(timezone.utc) - timedelta(days=7)
        
        all_orders = await get_driver_order_history(config.database_path, driver.tg_user_id, limit=200)
        
        week_orders = []
        for order in all_orders:
            if order.created_at:
                order_time = order.created_at
                if isinstance(order_time, str):
                    try:
                        order_time = datetime.fromisoformat(order_time)
                    except:
                        continue
                
                if isinstance(order_time, datetime):
                    if order_time.replace(tzinfo=timezone.utc) >= week_start:
                        week_orders.append(order)
        
        total_orders = len(week_orders)
        completed_orders = len([o for o in week_orders if o.status == 'completed'])
        cancelled_orders = len([o for o in week_orders if o.status == 'cancelled'])
        
        earnings = sum(o.fare_amount for o in week_orders if o.status == 'completed' and o.fare_amount)
        
        # Отримати комісію з тарифу
        from app.storage.db import get_latest_tariff
        tariff = await get_latest_tariff(config.database_path)
        commission_rate = tariff.commission_percent if tariff else 0.02
        commission = earnings * commission_rate
        net = earnings - commission
        commission_percent = int(commission_rate * 100)
        
        # Середнє за день
        avg_per_day = earnings / 7 if earnings > 0 else 0
        
        text = (
            f"📊 <b>СТАТИСТИКА ЗА ТИЖДЕНЬ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 <b>Всього замовлень:</b> {total_orders}\n"
            f"✅ <b>Виконано:</b> {completed_orders}\n"
            f"❌ <b>Скасовано:</b> {cancelled_orders}\n\n"
            f"💰 <b>Заробіток:</b> {earnings:.0f} грн\n"
            f"💳 <b>Комісія ({commission_percent}%):</b> {commission:.0f} грн\n"
            f"💵 <b>Чистий:</b> {net:.0f} грн\n\n"
            f"📈 <b>Середнє/день:</b> {avg_per_day:.0f} грн\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📅 Період: останні 7 днів"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data="work:stats")]
            ]
        )
        
        if call.message:
            await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    
    @router.callback_query(F.data == "stats:month")
    async def show_stats_month(call: CallbackQuery) -> None:
        """Статистика за місяць"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        from datetime import datetime, timedelta, timezone
        from app.storage.db import get_driver_order_history
        
        # 30 днів тому
        month_start = datetime.now(timezone.utc) - timedelta(days=30)
        
        all_orders = await get_driver_order_history(config.database_path, driver.tg_user_id, limit=500)
        
        month_orders = []
        for order in all_orders:
            if order.created_at:
                order_time = order.created_at
                if isinstance(order_time, str):
                    try:
                        order_time = datetime.fromisoformat(order_time)
                    except:
                        continue
                
                if isinstance(order_time, datetime):
                    if order_time.replace(tzinfo=timezone.utc) >= month_start:
                        month_orders.append(order)
        
        total_orders = len(month_orders)
        completed_orders = len([o for o in month_orders if o.status == 'completed'])
        cancelled_orders = len([o for o in month_orders if o.status == 'cancelled'])
        
        earnings = sum(o.fare_amount for o in month_orders if o.status == 'completed' and o.fare_amount)
        
        # Отримати комісію з тарифу
        from app.storage.db import get_latest_tariff
        tariff = await get_latest_tariff(config.database_path)
        commission_rate = tariff.commission_percent if tariff else 0.02
        commission = earnings * commission_rate
        net = earnings - commission
        commission_percent = int(commission_rate * 100)
        
        # Середнє за день
        avg_per_day = earnings / 30 if earnings > 0 else 0
        
        text = (
            f"📊 <b>СТАТИСТИКА ЗА МІСЯЦЬ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 <b>Всього замовлень:</b> {total_orders}\n"
            f"✅ <b>Виконано:</b> {completed_orders}\n"
            f"❌ <b>Скасовано:</b> {cancelled_orders}\n\n"
            f"💰 <b>Заробіток:</b> {earnings:.0f} грн\n"
            f"💳 <b>Комісія ({commission_percent}%):</b> {commission:.0f} грн\n"
            f"💵 <b>Чистий:</b> {net:.0f} грн\n\n"
            f"📈 <b>Середнє/день:</b> {avg_per_day:.0f} грн\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📅 Період: останні 30 днів"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data="work:stats")]
            ]
        )
        
        if call.message:
            await call.message.edit_text(text, reply_markup=kb)
        await call.answer()

    # ⭐ ЛОГІКА LIVE LOCATION:
    # - Live location відправляється АВТОМАТИЧНО при прийнятті замовлення
    # - Водій надає геолокацію коли натискає "Прийняти замовлення"
    # - Завжди свіжі координати (запитуються зараз, не з БД)
    # - Після надання геолокації відразу показується меню керування замовленням

    # ⛔ ВИДАЛЕНО: "Мій заробіток" - тепер в "⚙️ Особиста інформація"

    @router.message(F.text == "💳 Комісія")
    async def commission(message: Message) -> None:
        """Комісія"""
        if not message.from_user:
            return
        
        # 🚫 ПЕРЕВІРКА БЛОКУВАННЯ
        from app.handlers.driver_blocked_check import check_driver_blocked_and_notify
        if await check_driver_blocked_and_notify(config.database_path, message):
            return
        
        # Видалити повідомлення користувача для чистого чату
        try:
            await message.delete()
        except:
            pass
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        unpaid = await get_driver_unpaid_commission(config.database_path, message.from_user.id)
        
        if unpaid > 0:
            # Отримати номер картки адміна з БД
            from app.storage.db_connection import db_manager
            admin_card = "Не вказано"
            try:
                async with db_manager.connect(config.database_path) as db:
                    row = await db.fetchone("SELECT value FROM app_settings WHERE key = 'admin_payment_card'")
                    if row:
                        admin_card = row[0]
            except Exception as e:
                logger.error(f"Помилка отримання номера картки: {e}")
            
            # Показати інлайн кнопку для підтвердження оплати
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Комісію сплачено", callback_data=f"commission:paid:{driver.id}")]
                ]
            )
            
            await message.answer(
                f"💳 <b>Комісія до сплати:</b> {unpaid:.2f} грн\n\n"
                f"📋 <b>Реквізити для оплати:</b>\n"
                f"💳 Картка: <code>{admin_card}</code>\n\n"
                f"⚠️ <b>УВАГА:</b>\n"
                f"1. Переведіть комісію на вказану картку\n"
                f"2. Тільки після переказу натисніть кнопку нижче\n"
                f"3. Адміністратор перевірить платіж\n"
                f"4. Після підтвердження комісія буде анульована\n\n"
                f"💡 Не натискайте кнопку до здійснення оплати!",
                reply_markup=kb
            )
        else:
            await message.answer("✅ Комісія сплачена!")

    @router.callback_query(F.data.startswith("commission:paid:"))
    async def commission_paid_request(call: CallbackQuery) -> None:
        """Водій повідомляє що сплатив комісію"""
        if not call.from_user:
            return
        
        await call.answer()
        
        driver_id = int(call.data.split(":", 2)[2])
        
        driver = await get_driver_by_id(config.database_path, driver_id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        # Перевірити що це той самий водій
        if driver.tg_user_id != call.from_user.id:
            await call.answer("❌ Помилка доступу", show_alert=True)
            return
        
        unpaid = await get_driver_unpaid_commission(config.database_path, call.from_user.id)
        
        if unpaid <= 0:
            await call.answer("✅ У вас немає боргу", show_alert=True)
            return
        
        # Оновити повідомлення водію
        try:
            await call.message.edit_text(
                f"⏳ <b>Запит на підтвердження надіслано</b>\n\n"
                f"💳 Сума: {unpaid:.2f} грн\n\n"
                f"Очікуйте підтвердження від адміністратора.\n"
                f"Це може зайняти деякий час."
            )
        except:
            pass
        
        # Відправити повідомлення всім адмінам
        admin_ids = config.bot.admin_ids
        
        # Отримати картку адміна з БД (налаштування)
        from app.handlers.admin import get_admin_payment_card
        admin_payment_card = await get_admin_payment_card(config.database_path)
        
        for admin_id in admin_ids:
            try:
                # Кнопки для адміна
                admin_kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"commission:confirm:{driver.id}:{call.from_user.id}"),
                            InlineKeyboardButton(text="❌ Відхилити", callback_data=f"commission:reject:{driver.id}:{call.from_user.id}")
                        ]
                    ]
                )
                
                await call.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"💳 <b>ЗАПИТ НА ПІДТВЕРДЖЕННЯ ОПЛАТИ КОМІСІЇ</b>\n\n"
                        f"👤 Водій: {driver.full_name}\n"
                        f"📱 Телефон: {driver.phone}\n"
                        f"🏙 Місто: {driver.city or 'Не вказано'}\n"
                        f"🚗 Авто: {driver.car_model} ({driver.car_plate})\n"
                        f"💳 Сума комісії: <b>{unpaid:.2f} грн</b>\n\n"
                        f"📋 Реквізити (куди мав переказати):\n"
                        f"💳 <code>{admin_payment_card}</code>\n\n"
                        f"⚠️ <b>Перевірте надходження коштів</b>\n"
                        f"та підтвердіть або відхиліть платіж:"
                    ),
                    reply_markup=admin_kb
                )
                
                logger.info(f"✅ Надіслано запит на підтвердження комісії {unpaid:.2f} грн від водія {driver.id} адміну {admin_id}")
            except Exception as e:
                logger.error(f"❌ Помилка відправки повідомлення адміну {admin_id}: {e}")
        
        await call.answer("✅ Запит надіслано адміністратору", show_alert=True)
    
    @router.callback_query(F.data.startswith("commission:confirm:"))
    async def commission_confirm(call: CallbackQuery) -> None:
        """Адмін підтверджує оплату комісії"""
        if not call.from_user:
            return
        
        # Перевірити що це адмін
        if call.from_user.id not in config.bot.admin_ids:
            await call.answer("❌ Тільки для адміністраторів", show_alert=True)
            return
        
        await call.answer()
        
        parts = call.data.split(":", 3)
        driver_id = int(parts[2])
        driver_tg_id = int(parts[3])
        
        driver = await get_driver_by_id(config.database_path, driver_id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        unpaid = await get_driver_unpaid_commission(config.database_path, driver_tg_id)
        
        if unpaid <= 0:
            await call.answer("ℹ️ Комісія вже сплачена", show_alert=True)
            try:
                await call.message.edit_text(
                    f"ℹ️ <b>Комісія вже була сплачена раніше</b>\n\n"
                    f"👤 Водій: {driver.full_name}"
                )
            except:
                pass
            return
        
        # АНУЛЮВАТИ КОМІСІЮ В БД
        await mark_commission_paid(config.database_path, driver_tg_id)
        
        logger.info(f"✅ Адмін {call.from_user.id} підтвердив оплату комісії {unpaid:.2f} грн від водія {driver.id}")
        
        # Оновити повідомлення адміна
        try:
            await call.message.edit_text(
                f"✅ <b>ОПЛАТУ ПІДТВЕРДЖЕНО</b>\n\n"
                f"👤 Водій: {driver.full_name}\n"
                f"💳 Сума: {unpaid:.2f} грн\n"
                f"👨‍💼 Підтвердив: @{call.from_user.username or call.from_user.first_name}\n"
                f"⏰ Час: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
                f"✅ Комісія анульована в системі"
            )
        except:
            pass
        
        # Сповістити водія про підтвердження
        try:
            await call.bot.send_message(
                chat_id=driver_tg_id,
                text=(
                    f"✅ <b>ОПЛАТУ КОМІСІЇ ПІДТВЕРДЖЕНО!</b>\n\n"
                    f"💳 Сума: {unpaid:.2f} грн\n\n"
                    f"Дякуємо! Ваша комісія анульована.\n"
                    f"Можете продовжувати роботу! 🚗"
                )
            )
        except Exception as e:
            logger.error(f"❌ Помилка сповіщення водія {driver_tg_id}: {e}")
        
        await call.answer("✅ Оплату підтверджено та комісію анульовано", show_alert=True)
    
    @router.callback_query(F.data.startswith("commission:reject:"))
    async def commission_reject(call: CallbackQuery) -> None:
        """Адмін відхиляє оплату комісії"""
        if not call.from_user:
            return
        
        # Перевірити що це адмін
        if call.from_user.id not in config.bot.admin_ids:
            await call.answer("❌ Тільки для адміністраторів", show_alert=True)
            return
        
        await call.answer()
        
        parts = call.data.split(":", 3)
        driver_id = int(parts[2])
        driver_tg_id = int(parts[3])
        
        driver = await get_driver_by_id(config.database_path, driver_id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        unpaid = await get_driver_unpaid_commission(config.database_path, driver_tg_id)
        
        logger.info(f"❌ Адмін {call.from_user.id} відхилив оплату комісії від водія {driver.id}")
        
        # Оновити повідомлення адміна
        try:
            await call.message.edit_text(
                f"❌ <b>ОПЛАТУ ВІДХИЛЕНО</b>\n\n"
                f"👤 Водій: {driver.full_name}\n"
                f"💳 Сума: {unpaid:.2f} грн\n"
                f"👨‍💼 Відхилив: @{call.from_user.username or call.from_user.first_name}\n"
                f"⏰ Час: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
                f"⚠️ Водія буде сповіщено"
            )
        except:
            pass
        
        # Сповістити водія про відхилення
        try:
            await call.bot.send_message(
                chat_id=driver_tg_id,
                text=(
                    f"❌ <b>ОПЛАТУ КОМІСІЇ ВІДХИЛЕНО</b>\n\n"
                    f"💳 Сума: {unpaid:.2f} грн\n\n"
                    f"⚠️ Причини можливого відхилення:\n"
                    f"• Оплата не надійшла на картку\n"
                    f"• Неправильна сума\n"
                    f"• Інша помилка\n\n"
                    f"📞 Зв'яжіться з адміністратором для уточнення.\n\n"
                    f"Після здійснення правильної оплати\n"
                    f"надішліть запит знову через меню '💳 Комісія'"
                )
            )
        except Exception as e:
            logger.error(f"❌ Помилка сповіщення водія {driver_tg_id}: {e}")
        
        await call.answer("❌ Оплату відхилено, водія сповіщено", show_alert=True)

    @router.message(F.text == "📜 Історія поїздок")
    async def history(message: Message) -> None:
        """Історія"""
        if not message.from_user:
            return
        
        # 🚫 ПЕРЕВІРКА БЛОКУВАННЯ
        from app.handlers.driver_blocked_check import check_driver_blocked_and_notify
        if await check_driver_blocked_and_notify(config.database_path, message):
            return
        
        orders = await get_driver_order_history(config.database_path, message.from_user.id, limit=5)
        
        if not orders:
            await message.answer(
                "📜 Поки немає поїздок",
                reply_markup=driver_panel_keyboard()
            )
            return
        
        text = "📜 <b>Останні 5 поїздок:</b>\n\n"
        for i, o in enumerate(orders, 1):
            text += f"{i}. {o.pickup_address[:20]}... → {o.destination_address[:20]}...\n"
            text += f"   💰 {o.fare_amount or 0:.0f} грн\n\n"
        
        await message.answer(text, reply_markup=driver_panel_keyboard())

    # FSM для геолокації водія
    class DriverLocationStates(StatesGroup):
        waiting_location = State()
    
    # Обробник геолокації після прийняття замовлення
    # ⭐ ВИДАЛЕНО: driver_location_for_live_tracking та skip_driver_location
    # Тепер live location надсилається АВТОМАТИЧНО при прийнятті замовлення
    # використовуючи збережену геолокацію водія (driver.last_lat, driver.last_lon)
    
    # Обробники замовлень
    @router.callback_query(F.data.startswith("accept_order:"))
    async def accept(call: CallbackQuery, state: FSMContext) -> None:
        """Прийняти замовлення (з запитом геолокації)"""
        if not call.from_user:
            logger.error("❌ accept_order: call.from_user is None")
            return
        
        logger.info(f"🔔 accept_order callback from user {call.from_user.id} (username: @{call.from_user.username})")
        
        # 🚫 ПЕРЕВІРКА БЛОКУВАННЯ: Перевірити чи не заблокований водій
        from app.handlers.driver_blocked_check import check_driver_blocked_and_notify
        if await check_driver_blocked_and_notify(config.database_path, call):
            logger.warning(f"🚫 Blocked driver {call.from_user.id} tried to accept order")
            return
        
        # RATE LIMITING: Перевірка ліміту прийняття замовлень (максимум 20 спроб на годину)
        if not check_rate_limit(call.from_user.id, "accept_order", max_requests=20, window_seconds=3600):
            time_until_reset = get_time_until_reset(call.from_user.id, "accept_order", window_seconds=3600)
            await call.answer(
                f"⏳ Занадто багато спроб прийняти замовлення.\n"
                f"Спробуйте через: {format_time_remaining(time_until_reset)}",
                show_alert=True
            )
            logger.warning(f"⏱️ Driver {call.from_user.id} exceeded accept_order rate limit")
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            logger.error(f"❌ Driver not found for user {call.from_user.id}")
            await call.answer(
                "❌ Ви не зареєстровані як водій.\n"
                "Зареєструйтесь через /start → Стати водієм",
                show_alert=True
            )
            return
        
        # ⚠️ ПЕРЕВІРКА: Водій має бути ОНЛАЙН щоб прийняти замовлення
        if not driver.online:
            logger.warning(f"⚠️ Driver {call.from_user.id} tried to accept order while OFFLINE")
            await call.answer(
                "❌ Ви не можете прийняти замовлення!\n\n"
                "Причина: Ви в статусі 🔴 ОФЛАЙН\n\n"
                "💡 Увімкніть 🟢 Онлайн в меню:\n"
                "🚗 Панель водія → 🚀 Почати роботу → 🟢 УВІМКНУТИ ОНЛАЙН",
                show_alert=True
            )
            return
        
        order_id = int(call.data.split(":")[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.status != "pending":
            await call.answer("❌ Вже прийнято", show_alert=True)
            return
        
        # Перевірка відповідності класу авто до клієнтського
        driver_class = (driver.car_class or 'economy')
        order_class = (order.car_class or 'economy')
        if driver_class != order_class:
            # Повідомлення з підказкою змінити клас авто в налаштуваннях
            from app.handlers.car_classes import get_car_class_name
            d_name = get_car_class_name(driver_class)
            o_name = get_car_class_name(order_class)
            await call.answer(
                "❌ Це замовлення для іншого класу авто\n\n"
                f"🔘 Ваш клас: {d_name}\n"
                f"🎯 Потрібний клас: {o_name}\n\n"
                "Якщо бажаєте приймати такі замовлення — змініть клас авто в Особистій інформації (🚗 Змінити клас авто)",
                show_alert=True
            )
            return

        # ⭐ ВИДАЛИТИ повідомлення з групи ОДРАЗУ (щоб інші водії не натискали)
        if order.group_message_id:
            try:
                # Отримати ID групи міста клієнта
                from app.config.config import get_city_group_id
                from app.storage.db import get_user_by_id
                
                user = await get_user_by_id(config.database_path, order.user_id)
                client_city = user.city if user and user.city else None
                
                group_id = get_city_group_id(config, client_city)
                
                if group_id:
                    # Видалити повідомлення з групи водіїв
                    await call.bot.delete_message(
                        chat_id=group_id,
                        message_id=order.group_message_id
                    )
                    logger.info(f"✅ Повідомлення про замовлення #{order_id} видалено з групи {group_id} (місто: {client_city})")
                else:
                    logger.warning(f"⚠️ Не знайдено ID групи для міста {client_city}")
            except Exception as e:
                logger.error(f"❌ Не вдалося видалити повідомлення з групи: {e}", exc_info=True)
        else:
            logger.warning(f"⚠️ Замовлення не має group_message_id, пропускаю видалення")

        # ⭐ НОВА ЛОГІКА: Запитати геолокацію ПЕРЕД прийняттям замовлення
        # Зберегти order_id в FSM state
        await state.set_state(DriverProfileStates.waiting_for_location_to_accept)
        await state.update_data(accept_order_id=order_id)
        
        logger.info(f"✅ FSM стан встановлено: waiting_for_location_to_accept для order #{order_id}")
        
        # Створити Reply клавіатуру з кнопкою геолокації
        location_kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Надіслати геолокацію для прийняття", request_location=True)],
                [KeyboardButton(text="⏭️ Прийняти БЕЗ геолокації")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await call.answer()
        
        # Відправити запит на геолокацію в приватний чат водія
        try:
            location_request_msg = await call.bot.send_message(
                driver.tg_user_id,
                "📍 <b>Підтвердження прийняття замовлення</b>\n\n"
                f"Ви збираєтесь прийняти замовлення #{order_id}\n\n"
                "Натисніть кнопку 📍 <b>Надіслати геолокацію</b>,\n"
                "щоб прийняти замовлення і автоматично поділитися\n"
                "своїм рухом з клієнтом.\n\n"
                "💡 Це допоможе клієнту:\n"
                "• Бачити де ви зараз\n"
                "• Відстежити ваш рух до нього\n"
                "• Знати коли ви прибудете",
                reply_markup=location_kb
            )
            
            # Зберегти ID повідомлення для подальшого видалення
            await state.update_data(location_request_msg_id=location_request_msg.message_id)
        except Exception as e:
            logger.error(f"❌ Помилка відправки запиту на геолокацію: {e}")
            # Fallback: прийняти без геолокації (якщо помилка відправки запиту)
            await state.clear()
            success = await accept_order(config.database_path, order_id, driver.id)
            logger.warning(f"⚠️ Замовлення #{order_id} прийнято БЕЗ геолокації через помилку")
    
    @router.message(DriverProfileStates.waiting_for_location_to_accept, F.location)
    async def handle_location_for_accept_order(message: Message, state: FSMContext) -> None:
        """Обробка геолокації для прийняття замовлення"""
        logger.info(f"🟢 handle_location_for_accept_order викликано для user {message.from_user.id if message.from_user else 'unknown'}")
        
        if not message.from_user or not message.location:
            logger.warning(f"⚠️ Відхилено: from_user або location відсутні")
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            await message.answer("❌ Водія не знайдено")
            await state.clear()
            return
        
        # Отримати order_id з FSM
        data = await state.get_data()
        order_id = data.get("accept_order_id")
        location_request_msg_id = data.get("location_request_msg_id")
        
        if not order_id:
            await message.answer("❌ Помилка: замовлення не знайдено")
            await state.clear()
            return
        
        order = await get_order_by_id(config.database_path, order_id)
        if not order or order.status != "pending":
            await message.answer("❌ Замовлення вже прийнято іншим водієм")
            await state.clear()
            return
        
        lat = message.location.latitude
        lon = message.location.longitude
        
        # Зберегти геолокацію в БД
        await update_driver_location(config.database_path, message.from_user.id, lat, lon)
        
        logger.info(f"📍 Водій {driver.full_name} надіслав геолокацію {lat}, {lon} для прийняття замовлення #{order_id}")
        
        # ПРИЙНЯТИ ЗАМОВЛЕННЯ
        success = await accept_order(config.database_path, order_id, driver.id)
        
        if not success:
            await message.answer(
                "❌ Не вдалося прийняти замовлення\n"
                "(Можливо, хтось вас випередив)",
                reply_markup=driver_panel_keyboard()
            )
            await state.clear()
            return
        
        # СКАСУВАТИ ТАЙМЕРИ
        cancel_order_timeout(order_id)
        from app.utils.priority_order_manager import PriorityOrderManager
        PriorityOrderManager.cancel_priority_timer(order_id)
        
        logger.info(f"✅ Замовлення #{order_id} прийнято водієм {driver.id}")
        
        # Відправити live location клієнту
        try:
            logger.info(f"📍 Відправка live location клієнту {order.user_id} для замовлення #{order_id}")
            
            location_message = await message.bot.send_location(
                chat_id=order.user_id,
                latitude=lat,
                longitude=lon,
                live_period=900,  # 15 хвилин
                disable_notification=False
            )
            
            logger.info(f"✅ Live location відправлено! Message ID: {location_message.message_id}")
            
            # Запустити автоматичне оновлення геопозиції
            from app.utils.live_location_manager import LiveLocationManager
            await LiveLocationManager.start_tracking(
                bot=message.bot,
                order_id=order_id,
                user_id=order.user_id,
                driver_id=driver.id,
                message_id=location_message.message_id,
                db_path=config.database_path
            )
            
            logger.info(f"✅ LiveLocationManager запущено для замовлення #{order_id}")
            
            # Повідомлення клієнту про прийняття замовлення + live location
            # Створити кнопки для клієнта
            client_buttons = []
            if order.payment_method == "card" and driver.card_number:
                client_buttons.append([
                    InlineKeyboardButton(text="💳 Картка водія для оплати", callback_data=f"show_card:{order_id}")
                ])
            
            client_kb = InlineKeyboardMarkup(inline_keyboard=client_buttons) if client_buttons else None
            
            await message.bot.send_message(
                order.user_id,
                "✅ <b>Водій прийняв ваше замовлення!</b>\n\n"
                f"🚗 {driver.full_name}\n"
                f"🚙 {driver.car_make} {driver.car_model} ({driver.car_plate})\n"
                f"📱 {driver.phone}\n\n"
                "📍 <b>Водій поділився геопозицією!</b>\n"
                "Ви можете бачити його рух в реальному часі.\n"
                "Геопозиція оновлюється кожні 20 секунд протягом 15 хвилин.\n\n"
                "🚗 Водій їде до вас!",
                reply_markup=client_kb
            )
            
            logger.info(f"✅ Повідомлення клієнту відправлено для замовлення #{order_id}")
            
        except Exception as e:
            logger.error(f"❌ Помилка відправки live location: {e}", exc_info=True)
        
        # Видалити технічні повідомлення
        try:
            if location_request_msg_id:
                await message.bot.delete_message(message.from_user.id, location_request_msg_id)
                logger.debug(f"✅ Видалено запит на геолокацію")
            await message.delete()
            logger.debug(f"✅ Видалено геолокацію водія з чату")
        except Exception as e:
            logger.debug(f"⚠️ Не вдалося видалити технічні повідомлення: {e}")
        
        # Створити клавіатуру керування замовленням
        kb_trip = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Я НА МІСЦІ ПОДАЧІ")],
                [KeyboardButton(text="✅ КЛІЄНТ В АВТО")],
                [KeyboardButton(text="🏁 ЗАВЕРШИТИ ПОЇЗДКУ")],
                [
                    KeyboardButton(text="📞 Клієнт", request_contact=False),
                    KeyboardButton(text="🗺️ Маршрут")
                ],
                [
                    KeyboardButton(text="❌ Скасувати замовлення"),
                    KeyboardButton(text="🚗 Панель водія")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Керування поїздкою"
        )
        
        # Очистити адреси
        clean_pickup = clean_address(order.pickup_address)
        clean_destination = clean_address(order.destination_address)
        
        # Посилання на карти
        pickup_link = ""
        destination_link = ""
        distance_text = ""
        
        if order.pickup_lat and order.pickup_lon:
            pickup_link = f"\n📍 <a href='https://www.google.com/maps?q={order.pickup_lat},{order.pickup_lon}'>Відкрити на карті</a>"
        
        if order.dest_lat and order.dest_lon:
            destination_link = f"\n📍 <a href='https://www.google.com/maps?q={order.dest_lat},{order.dest_lon}'>Відкрити на карті</a>"
        
        if order.distance_m:
            km = order.distance_m / 1000.0
            distance_text = f"\n📏 Відстань: {km:.1f} км"
        
        payment_emoji = "💵" if order.payment_method == "cash" else "💳"
        
        # Створити inline кнопку для WebApp карти
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
        # Використовуємо config.webapp_url як базу і додаємо шлях до driver_map.html
        base_url = config.webapp_url.replace('/index.html', '') if config.webapp_url else "https://your-app.onrender.com/webapp"
        webapp_url = f"{base_url}/driver_map.html?order_id={order_id}&driver_id={driver.id}"
        kb_webapp = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗺️ Керувати поїздкою 🚕", web_app=WebAppInfo(url=webapp_url))]
        ])
        
        # Відправити підтвердження водію з клавіатурою і зберегти message_id
        sent_msg = await message.answer(
            f"✅ <b>ЗАМОВЛЕННЯ #{order_id} ПРИЙНЯТО</b>\n\n"
            f"👤 {order.name} • <code>{order.phone}</code>\n\n"
            f"📍 <b>Звідки:</b> {clean_pickup}{pickup_link}\n\n"
            f"🎯 <b>Куди:</b> {clean_destination}{destination_link}{distance_text}\n\n"
            f"💰 <b>{int(order.fare_amount):.0f} грн</b> {payment_emoji}\n\n"
            "🚗 Використовуйте кнопки для керування поїздкою:",
            reply_markup=kb_trip
        )
        # Відправити кнопку WebApp окремим повідомленням
        webapp_msg = await message.answer(
            "📲 <b>Або керуйте поїздкою через карту:</b>",
            reply_markup=kb_webapp
        )
        add_order_message(order_id, sent_msg.message_id)
        add_order_message(order_id, webapp_msg.message_id)  # Зберегти WebApp кнопку також
        
        # Очистити FSM стан
        await state.clear()
    
    @router.message(DriverProfileStates.waiting_for_location_to_accept, F.text == "⏭️ Прийняти БЕЗ геолокації")
    async def skip_location_and_accept(message: Message, state: FSMContext) -> None:
        """Відмова від надсилання геолокації - ПРИЙНЯТИ ЗАМОВЛЕННЯ БЕЗ LIVE LOCATION"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            await message.answer("❌ Водія не знайдено", reply_markup=driver_panel_keyboard())
            await state.clear()
            return
        
        # Отримати дані з FSM
        data = await state.get_data()
        location_request_msg_id = data.get("location_request_msg_id")
        order_id = data.get("accept_order_id")
        
        if not order_id:
            await message.answer("❌ Помилка: замовлення не знайдено", reply_markup=driver_panel_keyboard())
            await state.clear()
            return
        
        order = await get_order_by_id(config.database_path, order_id)
        if not order or order.status != "pending":
            await message.answer("❌ Замовлення вже прийнято іншим водієм", reply_markup=driver_panel_keyboard())
            await state.clear()
            return
        
        logger.info(f"⚠️ Водій {driver.id} відмовився від надсилання геолокації для замовлення #{order_id}")
        
        # ПРИЙНЯТИ ЗАМОВЛЕННЯ БЕЗ ГЕОЛОКАЦІЇ
        success = await accept_order(config.database_path, order_id, driver.id)
        
        if not success:
            await message.answer(
                "❌ Не вдалося прийняти замовлення\n"
                "(Можливо, хтось вас випередив)",
                reply_markup=driver_panel_keyboard()
            )
            await state.clear()
            return
        
        # СКАСУВАТИ ТАЙМЕРИ
        cancel_order_timeout(order_id)
        from app.utils.priority_order_manager import PriorityOrderManager
        PriorityOrderManager.cancel_priority_timer(order_id)
        
        logger.info(f"✅ Замовлення #{order_id} прийнято водієм {driver.id} БЕЗ live location")
        
        # Повідомити клієнта (БЕЗ live location)
        try:
            # Створити кнопки для клієнта
            client_buttons = []
            if order.payment_method == "card" and driver.card_number:
                client_buttons.append([
                    InlineKeyboardButton(text="💳 Картка водія для оплати", callback_data=f"show_card:{order_id}")
                ])
            
            client_kb = InlineKeyboardMarkup(inline_keyboard=client_buttons) if client_buttons else None
            
            await message.bot.send_message(
                order.user_id,
                "✅ <b>Водій прийняв ваше замовлення!</b>\n\n"
                f"🚗 {driver.full_name}\n"
                f"🚙 {driver.car_make} {driver.car_model} ({driver.car_plate})\n"
                f"📱 {driver.phone}\n\n"
                "🚗 Водій їде до вас!",
                reply_markup=client_kb
            )
            logger.info(f"✅ Повідомлення клієнту відправлено (БЕЗ live location)")
        except Exception as e:
            logger.error(f"❌ Помилка відправки повідомлення клієнту: {e}")
        
        # Видалити технічні повідомлення
        try:
            if location_request_msg_id:
                await message.bot.delete_message(message.from_user.id, location_request_msg_id)
            await message.delete()
        except Exception as e:
            logger.debug(f"⚠️ Не вдалося видалити технічні повідомлення: {e}")
        
        # Створити клавіатуру керування замовленням
        kb_trip = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Я НА МІСЦІ ПОДАЧІ")],
                [KeyboardButton(text="✅ КЛІЄНТ В АВТО")],
                [KeyboardButton(text="🏁 ЗАВЕРШИТИ ПОЇЗДКУ")],
                [
                    KeyboardButton(text="📞 Клієнт", request_contact=False),
                    KeyboardButton(text="🗺️ Маршрут")
                ],
                [
                    KeyboardButton(text="❌ Скасувати замовлення"),
                    KeyboardButton(text="🚗 Панель водія")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Керування поїздкою"
        )
        
        # Очистити адреси
        clean_pickup = clean_address(order.pickup_address)
        clean_destination = clean_address(order.destination_address)
        
        # Посилання на карти
        pickup_link = ""
        destination_link = ""
        distance_text = ""
        
        if order.pickup_lat and order.pickup_lon:
            pickup_link = f"\n📍 <a href='https://www.google.com/maps?q={order.pickup_lat},{order.pickup_lon}'>Відкрити на карті</a>"
        
        if order.dest_lat and order.dest_lon:
            destination_link = f"\n📍 <a href='https://www.google.com/maps?q={order.dest_lat},{order.dest_lon}'>Відкрити на карті</a>"
        
        if order.distance_m:
            km = order.distance_m / 1000.0
            distance_text = f"\n📏 Відстань: {km:.1f} км"
        
        payment_emoji = "💵" if order.payment_method == "cash" else "💳"
        
        # Створити inline кнопку для WebApp карти
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
        # Використовуємо config.webapp_url як базу і додаємо шлях до driver_map.html
        base_url = config.webapp_url.replace('/index.html', '') if config.webapp_url else "https://your-app.onrender.com/webapp"
        webapp_url = f"{base_url}/driver_map.html?order_id={order_id}&driver_id={driver.id}"
        kb_webapp = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗺️ Керувати поїздкою 🚕", web_app=WebAppInfo(url=webapp_url))]
        ])
        
        # Відправити підтвердження водію з клавіатурою і зберегти message_id
        sent_msg = await message.answer(
            f"✅ <b>ЗАМОВЛЕННЯ #{order_id} ПРИЙНЯТО</b>\n\n"
            f"👤 {order.name} • <code>{order.phone}</code>\n\n"
            f"📍 <b>Звідки:</b> {clean_pickup}{pickup_link}\n\n"
            f"🎯 <b>Куди:</b> {clean_destination}{destination_link}{distance_text}\n\n"
            f"💰 <b>{int(order.fare_amount):.0f} грн</b> {payment_emoji}\n\n"
            "🚗 Використовуйте кнопки для керування поїздкою:",
            reply_markup=kb_trip
        )
        # Відправити кнопку WebApp окремим повідомленням
        webapp_msg = await message.answer(
            "📲 <b>Або керуйте поїздкою через карту:</b>",
            reply_markup=kb_webapp
        )
        add_order_message(order_id, sent_msg.message_id)
        add_order_message(order_id, webapp_msg.message_id)  # Зберегти WebApp кнопку також
        
        # Очистити FSM стан
        await state.clear()
    
    @router.callback_query(F.data.startswith("reject_order:"))
    async def reject_order_handler(call: CallbackQuery) -> None:
        """Водій відхиляє замовлення"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            return
        
        order_id = int(call.data.split(":")[1])
        
        # Додати водія до списку відхилених для цього замовлення
        from app.storage.db import add_rejected_driver, get_rejected_drivers_for_order
        await add_rejected_driver(config.database_path, order_id, driver.id)
        
        await call.answer("❌ Ви відхилили замовлення", show_alert=False)
        
        # Видалити повідомлення для цього водія
        if call.message:
            try:
                await call.message.delete()
            except:
                pass
        
        logger.info(f"❌ Водій {driver.full_name} (ID: {driver.id}) відхилив замовлення #{order_id}")
        
        # Перевірити чи замовлення все ще pending (тобто пріоритетне)
        order = await get_order_by_id(config.database_path, order_id)
        if order and order.status == "pending" and not order.group_message_id:
            # Отримати всіх пріоритетних водіїв для цього міста/класу авто
            from app.storage.db import get_user_by_id, get_drivers_by_city
            
            user = await get_user_by_id(config.database_path, order.user_id)
            client_city = user.city if user and user.city else None
            
            if client_city:
                # Отримати всіх онлайн водіїв з пріоритетом для цього міста
                all_drivers = await get_drivers_by_city(config.database_path, client_city)
                # Безпечне порівняння: priority може бути строкою або None
                priority_drivers = [d for d in all_drivers if d.online and hasattr(d, 'priority') and int(d.priority or 0) > 0]
                
                # Відфільтрувати водіїв за класом авто
                order_class = order.car_class or 'economy'
                priority_drivers = [d for d in priority_drivers if (d.car_class or 'economy') == order_class]
                
                # Отримати список водіїв що відхилили це замовлення
                rejected_driver_ids = await get_rejected_drivers_for_order(config.database_path, order_id)
                
                logger.info(f"📊 Замовлення #{order_id}: пріоритетних водіїв={len(priority_drivers)}, відхилили={len(rejected_driver_ids)}")
                
                # Перевірити чи ВСІ пріоритетні водії відхилили
                all_rejected = len(priority_drivers) > 0 and len(rejected_driver_ids) >= len(priority_drivers)
                
                if all_rejected:
                    # ВСІ пріоритетні водії відхилили - відправити в групу
                    logger.info(f"📢 ВСІ пріоритетні водії відхилили замовлення #{order_id}, відправляю в групу")
                    
                    # Скасувати пріоритетний таймер
                    from app.utils.priority_order_manager import PriorityOrderManager
                    PriorityOrderManager.cancel_priority_timer(order_id)
                    
                    # Відправити в групу
                    from app.config.config import get_city_group_id
                    city_group_id = get_city_group_id(config, client_city)
                    
                    if city_group_id:
                        from app.utils.priority_order_manager import _send_to_group
                        order_details = {
                            'name': order.name,
                            'phone': order.phone,
                            'pickup': order.pickup_address,
                            'destination': order.destination_address,
                            'comment': order.comment,
                            'pickup_lat': order.pickup_lat,
                            'pickup_lon': order.pickup_lon,
                            'dest_lat': order.dest_lat,
                            'dest_lon': order.dest_lon,
                            'distance_m': order.distance_m,
                            'duration_s': order.duration_s,
                            'estimated_fare': order.fare_amount,
                            'car_class': order.car_class,
                            'db_path': config.database_path,
                        }
                        await _send_to_group(call.bot, order_id, city_group_id, order_details)
                else:
                    # Ще є пріоритетні водії що не відхилили - вони все ще бачать замовлення
                    remaining = len(priority_drivers) - len(rejected_driver_ids)
                    logger.info(f"✅ Замовлення #{order_id} все ще доступне для {remaining} пріоритетних водіїв")

    @router.callback_query(F.data.startswith("arrived:"))
    async def driver_arrived(call: CallbackQuery) -> None:
        """Водій приїхав на місце подачі"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.id != order.driver_id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        await call.answer("📍 Клієнт отримав повідомлення!", show_alert=True)
        
        # Повідомити клієнта
        try:
            await call.bot.send_message(
                order.user_id,
                f"📍 <b>Водій на місці!</b>\n\n"
                f"🚗 {driver.full_name}\n"
                f"📱 <code>{driver.phone}</code>\n\n"
                f"Водій чекає на вас!"
            )
        except Exception as e:
            logger.error(f"Failed to notify client: {e}")
        
        # ⭐ Оновити текст і показати велику червону кнопку "ЗАВЕРШИТИ"
        distance_text = ""
        if order.distance_m:
            km = order.distance_m / 1000.0
            distance_text = f"\n📏 Відстань: {km:.1f} км"
        
        payment_emoji = "💵" if order.payment_method == "cash" else "💳"
        payment_text = "Готівка" if order.payment_method == "cash" else "Картка"
        
        updated_text = (
            f"🚗 <b>ЗАМОВЛЕННЯ #{order_id}</b>\n"
            f"━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Клієнт:</b> {order.name}\n"
            f"📱 <b>Телефон:</b> <code>{order.phone}</code>\n\n"
            f"📍 <b>Звідки:</b>\n   {clean_address(order.pickup_address)}\n\n"
            f"📍 <b>Куди:</b>\n   {clean_address(order.destination_address)}{distance_text}\n\n"
            f"💰 <b>Вартість:</b> {int(order.fare_amount):.0f} грн\n"
            f"{payment_emoji} <b>Оплата:</b> {payment_text}\n"
        )
        
        if order.comment:
            updated_text += f"\n💬 <b>Коментар:</b>\n   {order.comment}\n"
        
        updated_text += (
            f"\n━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Статус:</b> 📍 На місці подачі\n\n"
            f"👇 <i>Коли клієнт сяде - натисніть кнопку завершення</i>"
        )
        
        # Велика червона кнопка "ЗАВЕРШИТИ ПОЇЗДКУ"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏁 ЗАВЕРШИТИ ПОЇЗДКУ - Фініш", callback_data=f"complete:{order_id}")],
                [InlineKeyboardButton(text="📋 Деталі", callback_data=f"manage:{order_id}")]
            ]
        )
        
        if call.message:
            try:
                await call.message.edit_text(updated_text, reply_markup=kb)
            except:
                await call.message.answer(updated_text, reply_markup=kb)
    
    @router.callback_query(F.data.startswith("start:"))
    async def start_trip(call: CallbackQuery) -> None:
        """Почати поїздку - водій рухається до клієнта"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        await start_order(config.database_path, order_id, driver.id)
        
        await call.answer("🚗 В дорозі до клієнта!", show_alert=True)
        
        # ⭐ Оновити текст повідомлення і показати велику кнопку "Я НА МІСЦІ"
        distance_text = ""
        if order.distance_m:
            km = order.distance_m / 1000.0
            distance_text = f"\n📏 Відстань: {km:.1f} км"
        
        payment_emoji = "💵" if order.payment_method == "cash" else "💳"
        payment_text = "Готівка" if order.payment_method == "cash" else "Картка"
        
        updated_text = (
            f"🚗 <b>ЗАМОВЛЕННЯ #{order_id}</b>\n"
            f"━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Клієнт:</b> {order.name}\n"
            f"📱 <b>Телефон:</b> <code>{order.phone}</code>\n\n"
            f"📍 <b>Звідки:</b>\n   {clean_address(order.pickup_address)}\n\n"
            f"📍 <b>Куди:</b>\n   {clean_address(order.destination_address)}{distance_text}\n\n"
            f"💰 <b>Вартість:</b> {int(order.fare_amount):.0f} грн\n"
            f"{payment_emoji} <b>Оплата:</b> {payment_text}\n"
        )
        
        if order.comment:
            updated_text += f"\n💬 <b>Коментар:</b>\n   {order.comment}\n"
        
        updated_text += (
            f"\n━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Статус:</b> 🚗 В дорозі\n\n"
            f"👇 <i>Натисніть коли приїдете до клієнта</i>"
        )
        
        # Велика помаранчева кнопка "Я НА МІСЦІ"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📍 Я НА МІСЦІ - Приїхав", callback_data=f"arrived:{order_id}")],
                [InlineKeyboardButton(text="📋 Деталі", callback_data=f"manage:{order_id}")]
            ]
        )
        
        if call.message:
            try:
                await call.message.edit_text(updated_text, reply_markup=kb)
            except:
                await call.message.answer(updated_text, reply_markup=kb)

    @router.callback_query(F.data.startswith("complete:"))
    async def complete_trip(call: CallbackQuery) -> None:
        """Завершити"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        # Розрахунок вартості: використовуємо збережену, інакше мінімум 100
        fare = order.fare_amount if order.fare_amount else 100.0
        distance_m = order.distance_m if order.distance_m else 0
        duration_s = order.duration_s if order.duration_s else 0
        # Отримати поточний тариф для комісії
        from app.storage.db import get_latest_tariff, insert_payment, Payment
        tariff = await get_latest_tariff(config.database_path)
        commission_rate = tariff.commission_percent if tariff else 0.02
        commission = fare * commission_rate
        
        await complete_order(
            config.database_path,
            order_id,
            driver.id,
            fare,
            distance_m,
            duration_s,
            commission
        )
        
        # 🛑 Зупинити всі менеджери для цього замовлення
        from app.utils.live_location_manager import LiveLocationManager
        from app.utils.priority_order_manager import PriorityOrderManager
        from app.utils.order_timeout import cancel_order_timeout
        
        await LiveLocationManager.stop_tracking(order_id)
        PriorityOrderManager.cancel_priority_timer(order_id)
        cancel_order_timeout(order_id)
        
        # Запис у payments для обліку комісії
        payment = Payment(
            id=None,
            order_id=order_id,
            driver_id=driver.id,
            amount=fare,
            commission=commission,
            commission_paid=False,
            payment_method=order.payment_method or 'cash',
            created_at=datetime.now(timezone.utc),
        )
        await insert_payment(config.database_path, payment)
        
        await call.answer(f"✅ Завершено! {fare:.0f} грн", show_alert=True)
        
        # 🧹 ОЧИСТИТИ ЧАТ ВОДІЯ - видалити всі повідомлення про замовлення
        if call.from_user:
            await clear_order_messages(call.bot, call.from_user.id, order_id)
        
        if call.message:
            await call.message.edit_text(f"✅ Поїздка завершена!\n💰 {fare:.0f} грн")
        
        # 🌟 НОВА ФУНКЦІЯ: Відправити клієнту запит на оцінку водія
        try:
            # Створити інлайн кнопки з зірками
            rating_buttons = [
                [
                    InlineKeyboardButton(text="⭐", callback_data=f"rate:driver:{driver.tg_user_id}:1:{order_id}"),
                    InlineKeyboardButton(text="⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:2:{order_id}"),
                    InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:3:{order_id}"),
                ],
                [
                    InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:4:{order_id}"),
                    InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:5:{order_id}"),
                ],
                [
                    InlineKeyboardButton(text="⏩ Пропустити", callback_data=f"rate:skip:{order_id}")
                ]
            ]
            
            rating_kb = InlineKeyboardMarkup(inline_keyboard=rating_buttons)
            
            # Відправити повідомлення клієнту
            await call.bot.send_message(
                chat_id=order.user_id,
                text=(
                    "✅ <b>Поїздка завершена!</b>\n\n"
                    f"💰 Вартість: {fare:.0f} грн\n"
                    f"🚗 Спосіб оплати: {'💳 Картка' if order.payment_method == 'card' else '💵 Готівка'}\n\n"
                    "⭐ <b>Будь ласка, оцініть водія:</b>\n"
                    "Це допоможе покращити якість сервісу!"
                ),
                reply_markup=rating_kb
            )
            logger.info(f"✅ Надіслано запит на оцінку водія {driver.id} клієнту {order.user_id} для замовлення #{order_id}")
        except Exception as e:
            logger.error(f"❌ Помилка відправки запиту на оцінку: {e}")

    @router.message(F.text == "💼 Гаманець")
    async def show_wallet(message: Message) -> None:
        """Гаманець водія - картка для отримання оплати"""
        if not message.from_user:
            return
        
        # 🚫 ПЕРЕВІРКА БЛОКУВАННЯ
        from app.handlers.driver_blocked_check import check_driver_blocked_and_notify
        if await check_driver_blocked_and_notify(config.database_path, message):
            return
        
        # Видалити повідомлення користувача для чистого чату
        try:
            await message.delete()
        except:
            pass
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            await message.answer("❌ Доступно тільки для водіїв")
            return
        
        if driver.card_number:
            text = (
                f"💼 <b>Ваш гаманець</b>\n\n"
                f"💳 Картка для оплати:\n"
                f"<code>{driver.card_number}</code>\n\n"
                f"ℹ️ Ця картка показується клієнтам,\n"
                f"які обирають оплату карткою."
            )
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Змінити картку", callback_data="wallet:edit")]
                ]
            )
        else:
            text = (
                f"💼 <b>Ваш гаманець</b>\n\n"
                f"❌ Картка не додана\n\n"
                f"Додайте картку, щоб клієнти могли\n"
                f"переказувати вам оплату."
            )
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Додати картку", callback_data="wallet:add")]
                ]
            )
        
        await message.answer(text, reply_markup=kb)
    
    @router.callback_query(F.data.in_(["wallet:add", "wallet:edit"]))
    async def wallet_add_edit(call: CallbackQuery) -> None:
        """Додати/змінити картку"""
        await call.answer()
        await call.message.answer(
            "💳 <b>Введіть номер картки</b>\n\n"
            "Формат: 1234 5678 9012 3456\n"
            "або: 1234567890123456\n\n"
            "Ця картка буде показуватись клієнтам\n"
            "для оплати поїздки."
        )
        # Тут можна додати FSM, але для простоти зробимо через текстовий обробник
    
    @router.message(F.text.regexp(r'^\d{4}\s?\d{4}\s?\d{4}\s?\d{4}$'))
    async def save_card_number(message: Message) -> None:
        """Зберегти номер картки"""
        if not message.from_user or not message.text:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            return
        
        card_number = message.text.strip().replace(" ", "")
        # Форматувати як 1234 5678 9012 3456
        formatted_card = f"{card_number[0:4]} {card_number[4:8]} {card_number[8:12]} {card_number[12:16]}"
        
        # Оновити в БД
        import aiosqlite
        import logging
        logger = logging.getLogger(__name__)
        
        from app.storage.db_connection import db_manager
        async with db_manager.connect(config.database_path) as db:
            cursor = await db.execute(
                "UPDATE drivers SET card_number = ? WHERE tg_user_id = ?",
                (formatted_card, message.from_user.id)
            )
            await db.commit()
            
            # Перевірити що UPDATE спрацював
            if cursor.rowcount > 0:
                logger.info(f"✅ Картку збережено для водія {message.from_user.id}: {formatted_card}")
            else:
                logger.error(f"❌ UPDATE не спрацював для водія {message.from_user.id}")
        
        # Перевірити що картка дійсно збереглася
        driver_check = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if driver_check and driver_check.card_number:
            logger.info(f"✅ Перевірка: картка в БД = {driver_check.card_number}")
        else:
            logger.error(f"❌ Перевірка: картка НЕ збереглася в БД!")
        
        await message.answer(
            f"✅ <b>Картку збережено!</b>\n\n"
            f"💳 {formatted_card}\n\n"
            f"Тепер клієнти зможуть переказувати\n"
            f"оплату на цю картку.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="🚗 Панель водія"), KeyboardButton(text="🚀 Почати роботу")],
                    [KeyboardButton(text="⚙️ Особиста інформація"), KeyboardButton(text="💳 Комісія")],
                    [KeyboardButton(text="📜 Історія поїздок"), KeyboardButton(text="💼 Гаманець")],
                    [KeyboardButton(text="👤 Кабінет клієнта"), KeyboardButton(text="ℹ️ Допомога")]
                ],
                resize_keyboard=True
            )
        )
    
    @router.callback_query(F.data.startswith("manage:"))
    async def manage_order(call: CallbackQuery) -> None:
        """Керування замовленням - показати всі деталі та кнопки"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.id != order.driver_id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        # Сформувати текст з усіма деталями
        from app.storage.db import get_user_by_id
        client = await get_user_by_id(config.database_path, order.user_id)
        
        distance_text = ""
        if order.distance_m:
            km = order.distance_m / 1000.0
            distance_text = f"\n📏 Відстань: {km:.1f} км"
        
        payment_text = "💵 Готівка" if order.payment_method == "cash" else "💳 Картка"
        
        fare_text = f"{order.fare_amount:.0f} грн" if isinstance(order.fare_amount, (int, float)) else "уточнюється"
        text = (
            f"🚗 <b>Замовлення #{order_id}</b>\n\n"
            f"👤 Клієнт: {client.full_name if client else 'Невідомо'}\n"
            f"📱 Телефон: <code>{order.phone}</code>\n\n"
            f"📍 <b>Звідки:</b> {clean_address(order.pickup_address)}\n"
            f"📍 <b>Куди:</b> {clean_address(order.destination_address)}{distance_text}\n\n"
            f"💰 Вартість: {fare_text}\n"
            f"💳 Оплата: {payment_text}\n"
        )
        
        if order.comment:
            text += f"\n💬 Коментар: {order.comment}"
        
        text += f"\n\n📊 Статус: "
        
        # Кнопки залежно від статусу
        kb = None
        
        if order.status == "accepted":
            text += "✅ Прийнято\n\n"
            text += "💡 <i>Клієнт вже бачить вашу локацію (якщо ви її надсилали)</i>"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📍 Я на місці", callback_data=f"arrived:{order_id}")],
                    [InlineKeyboardButton(text="🚗 Почати поїздку", callback_data=f"start:{order_id}")],
                    [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"manage:{order_id}")]
                ]
            )
            
        elif order.status == "in_progress":
            text += "🚗 В дорозі\n\n"
            text += "💡 <i>Оновіть локацію щоб клієнт бачив де ви</i>"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Завершити поїздку", callback_data=f"complete:{order_id}")],
                    [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"manage:{order_id}")]
                ]
            )
        elif order.status == "completed":
            text += "✔️ Завершено"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад", callback_data="driver:panel")]
                ]
            )
        
        await call.answer()
        
        if kb:
            try:
                await call.message.edit_text(text, reply_markup=kb)
            except:
                await call.message.answer(text, reply_markup=kb)
        else:
            await call.message.answer(text)

    # ⭐ НОВІ ОБРОБНИКИ ДЛЯ REPLY KEYBOARD (велика кнопка що змінюється)
    
    @router.message(F.text == "🚗 В дорозі")
    async def trip_in_progress_button(message: Message) -> None:
        """Водій натиснув кнопку 'В дорозі' → змінити на 'На місці'"""
        if not message.from_user:
            return
        
        # Отримати активне замовлення водія
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            await message.answer("❌ Водія не знайдено")
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        # Оновити статус на "in_progress"
        await start_order(config.database_path, order.id, driver.id)
        
        # ⭐ Очистити адресу і створити посилання
        clean_pickup = clean_address(order.pickup_address)
        pickup_link = ""
        
        if order.pickup_lat and order.pickup_lon:
            pickup_link = f"\n📍 <a href='https://www.google.com/maps?q={order.pickup_lat},{order.pickup_lon}'>Відкрити на карті</a>"
        
        # ⭐ ЗМІНИТИ КНОПКУ на "📍 На місці"
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        
        kb_trip = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 На місці")],
                [
                    KeyboardButton(text="❌ Відмовитися"),
                    KeyboardButton(text="📞 Зв'язатися з клієнтом")
                ],
                [
                    KeyboardButton(text="ℹ️ Допомога"),
                    KeyboardButton(text="💬 Підтримка")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        await message.answer(
            f"✅ <b>В дорозі до клієнта!</b>\n\n"
            f"🚗 <b>Рухайтесь до адреси подачі:</b>\n"
            f"{clean_pickup}{pickup_link}\n\n"
            f"👇 Натисніть кнопку коли приїдете",
            reply_markup=kb_trip
        )
    
    @router.message(F.text == "📍 На місці")
    async def trip_arrived_button(message: Message) -> None:
        """Водій натиснув кнопку 'На місці' → змінити на 'Виконую замовлення'"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        # Повідомити клієнта
        try:
            await message.bot.send_message(
                order.user_id,
                f"📍 <b>Водій на місці!</b>\n\n"
                f"🚗 {driver.full_name}\n"
                f"📱 <code>{driver.phone}</code>\n\n"
                f"Водій чекає на вас!"
            )
        except Exception as e:
            logger.error(f"Failed to notify client: {e}")
        
        # ⭐ Очистити адресу призначення і створити посилання
        clean_destination = clean_address(order.destination_address)
        destination_link = ""
        
        if order.dest_lat and order.dest_lon:
            destination_link = f"\n📍 <a href='https://www.google.com/maps?q={order.dest_lat},{order.dest_lon}'>Відкрити на карті</a>"
        
        # ⭐ ЗМІНИТИ КНОПКУ на "🚀 Виконую замовлення"
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        
        kb_trip = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚀 Виконую замовлення")],
                [
                    KeyboardButton(text="❌ Відмовитися"),
                    KeyboardButton(text="📞 Зв'язатися з клієнтом")
                ],
                [
                    KeyboardButton(text="ℹ️ Допомога"),
                    KeyboardButton(text="💬 Підтримка")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        await message.answer(
            f"✅ <b>На місці подачі!</b>\n\n"
            f"👋 <b>Зустрічайте клієнта:</b>\n"
            f"👤 {order.name}\n"
            f"📱 <code>{order.phone}</code>\n\n"
            f"📍 <b>Їдете до:</b>\n"
            f"{clean_destination}{destination_link}\n\n"
            f"👇 Натисніть кнопку коли почнете поїздку",
            reply_markup=kb_trip
        )
    
    @router.message(F.text == "🚀 Виконую замовлення")
    async def trip_executing_button(message: Message) -> None:
        """Водій натиснув кнопку 'Виконую замовлення' → змінити на 'Завершити'"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        # ⭐ Очистити адресу призначення і створити посилання
        clean_destination = clean_address(order.destination_address)
        destination_link = ""
        
        if order.dest_lat and order.dest_lon:
            destination_link = f"\n📍 <a href='https://www.google.com/maps?q={order.dest_lat},{order.dest_lon}'>Відкрити на карті</a>"
        
        # ⭐ ЗМІНИТИ КНОПКУ на "🏁 Завершити"
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        
        kb_trip = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🏁 Завершити")],
                [
                    KeyboardButton(text="❌ Відмовитися"),
                    KeyboardButton(text="📞 Зв'язатися з клієнтом")
                ],
                [
                    KeyboardButton(text="ℹ️ Допомога"),
                    KeyboardButton(text="💬 Підтримка")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        await message.answer(
            f"🚀 <b>Виконуєте замовлення!</b>\n\n"
            f"🎯 <b>Напрямок:</b>\n"
            f"{clean_destination}{destination_link}\n\n"
            f"💰 <b>Вартість:</b> {int(order.fare_amount):.0f} грн\n\n"
            f"👇 Натисніть кнопку коли доїдете до призначення",
            reply_markup=kb_trip
        )
    
    @router.message(F.text == "🏁 Завершити")
    async def trip_complete_button(message: Message) -> None:
        """Водій натиснув кнопку 'Завершити' → завершити замовлення"""
        if not message.from_user:
            return
        
        logger.info(f"🏁 Водій {message.from_user.id} натиснув 'Завершити'")
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            logger.error(f"❌ Водія {message.from_user.id} не знайдено в БД")
            await message.answer("❌ Водія не знайдено")
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            logger.warning(f"⚠️ У водія {driver.id} немає активного замовлення")
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        logger.info(f"✅ Завершення замовлення #{order.id} водієм {driver.id}")
        
        # Розрахунок вартості та комісії
        fare = order.fare_amount if order.fare_amount else 100.0
        distance_m = order.distance_m if order.distance_m else 0
        duration_s = order.duration_s if order.duration_s else 0
        
        from app.storage.db import get_latest_tariff, insert_payment, Payment
        tariff = await get_latest_tariff(config.database_path)
        commission_rate = tariff.commission_percent if tariff else 0.02
        commission = fare * commission_rate
        
        await complete_order(
            config.database_path,
            order.id,
            driver.id,
            fare,
            distance_m,
            duration_s,
            commission
        )
        
        # 🛑 Зупинити всі менеджери для цього замовлення
        from app.utils.live_location_manager import LiveLocationManager
        from app.utils.priority_order_manager import PriorityOrderManager
        from app.utils.order_timeout import cancel_order_timeout
        
        await LiveLocationManager.stop_tracking(order.id)
        PriorityOrderManager.cancel_priority_timer(order.id)
        cancel_order_timeout(order.id)
        
        # Запис у payments
        payment = Payment(
            id=None,
            order_id=order.id,
            driver_id=driver.id,
            amount=fare,
            commission=commission,
            commission_paid=False,
            payment_method=order.payment_method or 'cash',  # ✅ ДОДАНО
            created_at=datetime.now(timezone.utc)
        )
        await insert_payment(config.database_path, payment)
        
        # 🌟 Відправити запит на оцінку водія клієнту
        try:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            # ✅ ПРАВИЛЬНИЙ ФОРМАТ: rate:driver:{driver_id}:{rating}:{order_id}
            rating_buttons = [
                [
                    InlineKeyboardButton(text="⭐", callback_data=f"rate:driver:{driver.tg_user_id}:1:{order.id}"),
                    InlineKeyboardButton(text="⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:2:{order.id}"),
                    InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:3:{order.id}"),
                ],
                [
                    InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:4:{order.id}"),
                    InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:5:{order.id}"),
                ],
                [InlineKeyboardButton(text="⏩ Пропустити", callback_data=f"rate:skip:{order.id}")]
            ]
            
            rating_kb = InlineKeyboardMarkup(inline_keyboard=rating_buttons)
            
            fare_text = f"{fare:.0f} грн" if fare else "Уточнюється"
            distance_text = f"{distance_m / 1000:.1f} км" if distance_m else "Не вказано"
            
            await message.bot.send_message(
                chat_id=order.user_id,
                text=(
                    f"🏁 <b>Поїздка завершена!</b>\n\n"
                    f"🚗 Водій: {driver.full_name}\n"
                    f"📏 Відстань: {distance_text}\n"
                    f"💰 Вартість: {fare_text}\n\n"
                    f"⭐ <b>Будь ласка, оцініть водія:</b>\n"
                    f"Ваша оцінка допоможе покращити сервіс!"
                ),
                reply_markup=rating_kb
            )
            logger.info(f"✅ Запит на оцінку надіслано клієнту #{order.user_id}")
        except Exception as e:
            logger.error(f"❌ Помилка відправки запиту на оцінку: {e}")
        
        # ⭐ ПОВЕРНУТИСЯ ДО ПАНЕЛІ ВОДІЯ
        logger.info(f"🔄 Повернення водія {driver.id} до панелі після завершення замовлення #{order.id}")
        
        await message.answer(
            f"✅ <b>Замовлення #{order.id} завершено!</b>\n\n"
            f"💰 Заробіток: {fare:.2f} грн\n"
            f"💳 Комісія: {commission:.2f} грн\n"
            f"💵 Чистий дохід: {fare - commission:.2f} грн\n\n"
            f"🎉 Дякуємо за роботу!",
            reply_markup=driver_panel_keyboard()
        )
        
        logger.info(f"✅ Замовлення #{order.id} повністю завершено. Водій {driver.id} повернувся до панелі.")
    
    @router.message(F.text == "❌ Скасувати замовлення")
    @router.message(F.text == "❌ Відмовитися")
    async def trip_cancel_button(message: Message) -> None:
        """Водій відмовляється від замовлення"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        # Скасувати замовлення
        success = await cancel_order_by_driver(config.database_path, order.id, driver.id, "Водій відмовився")
        
        if success:
            # 🛑 Зупинити всі менеджери для цього замовлення
            from app.utils.live_location_manager import LiveLocationManager
            from app.utils.priority_order_manager import PriorityOrderManager
            from app.utils.order_timeout import cancel_order_timeout
            
            await LiveLocationManager.stop_tracking(order.id)
            PriorityOrderManager.cancel_priority_timer(order.id)
            cancel_order_timeout(order.id)
            logger.info(f"✅ Всі менеджери зупинено для скасованого замовлення #{order.id}")
            
            # ⚠️ ЗМЕНШИТИ КАРМУ ВОДІЯ за відмову
            from app.storage.db import decrease_driver_karma
            await decrease_driver_karma(config.database_path, driver.id, amount=5)
            logger.warning(f"⚠️ Водій #{driver.id} відмовився від замовлення #{order.id}, карма -5")
            
            # Повідомити клієнта
            try:
                from app.handlers.keyboards import main_menu_keyboard
                from app.storage.db import get_user_by_id
                
                user = await get_user_by_id(config.database_path, order.user_id)
                is_blocked = user.is_blocked if user else False
                
                await message.bot.send_message(
                    order.user_id,
                    f"❌ <b>Водій відмовився від замовлення</b>\n\n"
                    f"🚗 {driver.full_name}\n\n"
                    f"На жаль, водій не зміг виконати ваше замовлення.\n"
                    f"Замовлення скасовано.\n\n"
                    f"💡 Спробуйте створити нове замовлення.\n"
                    f"⭐ Ваша карма не змінилася (скасував водій, не ви).",
                    reply_markup=main_menu_keyboard(
                        is_registered=True,
                        is_driver=False,
                        is_admin=False,
                        is_blocked=is_blocked
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to notify client: {e}")
            
            logger.warning(f"⚠️ Водій {driver.full_name} відмовився від замовлення #{order.id}")
            
            await message.answer(
                "❌ <b>Ви відмовилися від замовлення</b>\n\n"
                "Замовлення повернуто іншим водіям.",
                reply_markup=driver_panel_keyboard()
            )
        else:
            await message.answer("❌ Не вдалося скасувати замовлення")
    
    @router.message(F.text == "📍 Я НА МІСЦІ ПОДАЧІ")
    async def driver_arrived_at_pickup(message: Message) -> None:
        """Водій прибув на місце подачі"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        # Зберегти message_id повідомлення водія (текст кнопки)
        add_order_message(order.id, message.message_id)
        
        # Повідомити клієнта (коротке повідомлення)
        try:
            await message.bot.send_message(
                order.user_id,
                "🚗 <b>Водій вже на місці</b>"
            )
            logger.info(f"✅ Клієнту {order.user_id} надіслано повідомлення про прибуття водія")
        except Exception as e:
            logger.error(f"Failed to notify client: {e}")
        
        # Оновлена клавіатура - прибрати кнопку "Я на місці"
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ КЛІЄНТ В АВТО")],
                [KeyboardButton(text="🏁 ЗАВЕРШИТИ ПОЇЗДКУ")],
                [
                    KeyboardButton(text="📞 Клієнт"),
                    KeyboardButton(text="🗺️ Маршрут")
                ],
                [
                    KeyboardButton(text="❌ Скасувати замовлення"),
                    KeyboardButton(text="🚗 Панель водія")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        # Відправити повідомлення і зберегти message_id
        sent_msg = await message.answer(
            f"✅ <b>Клієнт отримав повідомлення про ваше прибуття</b>",
            reply_markup=kb
        )
        add_order_message(order.id, sent_msg.message_id)
    
    @router.message(F.text == "✅ КЛІЄНТ В АВТО")
    async def client_in_car(message: Message) -> None:
        """Клієнт сів в авто - початок поїздки"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        # Зберегти message_id повідомлення водія (текст кнопки)
        add_order_message(order.id, message.message_id)
        
        # Оновити статус на "in_progress"
        await start_order(config.database_path, order.id, driver.id)
        
        # Повідомити клієнта (коротке повідомлення)
        try:
            await message.bot.send_message(
                order.user_id,
                "🚗 <b>Гарної поїздки!</b> 🌟"
            )
            logger.info(f"✅ Клієнту {order.user_id} надіслано повідомлення 'Гарної поїздки'")
        except Exception as e:
            logger.error(f"❌ Помилка відправки повідомлення клієнту: {e}")
        
        # Оновлена клавіатура - прибрати "Клієнт в авто"
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🏁 ЗАВЕРШИТИ ПОЇЗДКУ")],
                [
                    KeyboardButton(text="📞 Клієнт"),
                    KeyboardButton(text="🗺️ Маршрут")
                ],
                [
                    KeyboardButton(text="❌ Скасувати замовлення"),
                    KeyboardButton(text="🚗 Панель водія")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        # Відправити повідомлення і зберегти message_id
        sent_msg = await message.answer(
            f"✅ <b>Клієнт отримав повідомлення про початок поїздки</b>",
            reply_markup=kb
        )
        add_order_message(order.id, sent_msg.message_id)
    
    @router.message(F.text == "🏁 ЗАВЕРШИТИ ПОЇЗДКУ")
    async def finish_trip(message: Message) -> None:
        """Завершити поїздку"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        # Захист від подвійного натискання
        if driver.id in _finishing_orders:
            logger.warning(f"⚠️ Водій {driver.id} вже завершує замовлення, ігноруємо повторне натискання")
            return
        
        _finishing_orders.add(driver.id)
        
        try:
            logger.info(f"🏁 Водій {driver.id} ({driver.full_name}) натиснув 'Завершити поїздку'")
            
            # Отримати замовлення для збереження message_id
            order = await get_active_order_for_driver(config.database_path, driver.id)
            if order:
                # Зберегти message_id повідомлення водія (текст кнопки)
                add_order_message(order.id, message.message_id)
            
            # Спочатку перевірити чи є взагалі замовлення у водія (для діагностики)
            from app.storage.db_connection import db_manager
            async with db_manager.connect(config.database_path) as db:
                async with db.execute(
                    "SELECT id, status, driver_id FROM orders WHERE driver_id = ? ORDER BY created_at DESC LIMIT 5",
                    (driver.id,)
                ) as cursor:
                    all_orders = await cursor.fetchall()
                    if all_orders:
                        logger.info(f"🔍 Останні замовлення водія {driver.id}:")
                        for o in all_orders:
                            logger.info(f"  - Order #{o[0]}, status: {o[1]}, driver_id: {o[2]}")
                    else:
                        logger.warning(f"⚠️ У водія {driver.id} немає жодних замовлень в БД")
            
            order = await get_active_order_for_driver(config.database_path, driver.id)
            if not order:
                logger.warning(f"⚠️ Водій {driver.id} не має активного замовлення (accepted/in_progress) при спробі завершити")
                await message.answer("❌ У вас немає активного замовлення для завершення")
                return
            
            logger.info(f"📋 Знайдено активне замовлення #{order.id}, статус: {order.status}")
            
            # Розрахунок
            fare = order.fare_amount if order.fare_amount else 100.0
            tariff = await get_latest_tariff(config.database_path)
            commission_percent = tariff.commission_percent if tariff else 0.02
            commission = fare * commission_percent
            net_earnings = fare - commission
            
            # Дані для завершення
            distance_m = order.distance_m if order.distance_m else 0
            duration_s = 0  # Можна додати розрахунок тривалості пізніше
            
            # Завершити замовлення
            logger.info(f"💾 Спроба завершити замовлення #{order.id} (поточний статус: {order.status})")
            success = await complete_order(
                config.database_path,
                order.id,
                driver.id,
                fare,
                distance_m,
                duration_s,
                commission
            )
            
            if not success:
                logger.error(f"❌ Не вдалося завершити замовлення #{order.id}. Можливо статус вже змінений або замовлення не належить водію.")
                await message.answer("❌ Не вдалося завершити замовлення. Спробуйте ще раз.")
                return
            
            logger.info(f"✅ Замовлення #{order.id} успішно завершено")
            
            # 🛑 Зупинити всі менеджери для цього замовлення
            from app.utils.live_location_manager import LiveLocationManager
            from app.utils.priority_order_manager import PriorityOrderManager
            from app.utils.order_timeout import cancel_order_timeout
            
            await LiveLocationManager.stop_tracking(order.id)
            PriorityOrderManager.cancel_priority_timer(order.id)
            cancel_order_timeout(order.id)
            logger.info(f"✅ Всі менеджери зупинено для замовлення #{order.id}")
            
            # Зберегти платіж
            payment = Payment(
                id=None,
                driver_id=driver.id,
                order_id=order.id,
                amount=fare,
                commission=commission,
                commission_paid=False,
                payment_method=order.payment_method or 'cash',
                created_at=datetime.now(timezone.utc)
            )
            await insert_payment(config.database_path, payment)
            
            # ⭐ ЗБІЛЬШИТИ КАРМУ ВОДІЯ за успішне замовлення
            from app.storage.db import increase_driver_karma
            await increase_driver_karma(config.database_path, driver.id)
            
            # Повідомити клієнта з кнопками оцінки
            try:
                payment_emoji = "💵" if order.payment_method == "cash" else "💳"
                payment_text = "готівкою" if order.payment_method == "cash" else "на картку"
                
                # Кнопки для оцінки водія
                kb_rating = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="⭐", callback_data=f"rate:driver:{driver.tg_user_id}:1:{order.id}"),
                            InlineKeyboardButton(text="⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:2:{order.id}"),
                            InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:3:{order.id}"),
                        ],
                        [
                            InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:4:{order.id}"),
                            InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:5:{order.id}"),
                        ],
                        [InlineKeyboardButton(text="⏩ Пропустити", callback_data=f"rate:skip:{order.id}")]
                    ]
                )
                
                await message.bot.send_message(
                    order.user_id,
                    f"🏁 <b>Поїздка завершена!</b>\n\n"
                    f"💰 До оплати: <b>{int(fare):.0f} грн</b>\n"
                    f"{payment_emoji} Оплата: {payment_text}\n\n"
                    f"⭐ <b>Будь ласка, оцініть водія:</b>",
                    reply_markup=kb_rating
                )
            except Exception as e:
                logger.error(f"Failed to notify client: {e}")
            
            # 🧹 ОЧИСТИТИ ЧАТ ВОДІЯ - видалити всі повідомлення про замовлення
            await clear_order_messages(message.bot, message.chat.id, order.id)
            
            # Повернути панель водія
            commission_percent = int(commission_percent * 100)
            await message.answer(
                f"✅ <b>Поїздку завершено!</b>\n\n"
                f"💰 Заробіток: {int(fare):.0f} грн\n"
                f"💸 Комісія ({commission_percent}%): {int(commission):.0f} грн\n"
                f"💵 Чистий: {int(net_earnings):.0f} грн\n\n"
                f"🌟 Дякуємо за роботу!",
                reply_markup=driver_panel_keyboard()
            )
        finally:
            # Завжди видаляємо з set, навіть якщо була помилка
            _finishing_orders.discard(driver.id)
    
    @router.message(F.text == "📞 Зв'язатися з клієнтом")
    @router.message(F.text == "📞 Клієнт")
    async def trip_contact_client_button(message: Message) -> None:
        """Показати контакти клієнта"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        await message.answer(
            f"📞 <b>Контакти клієнта:</b>\n\n"
            f"👤 Ім'я: {order.name}\n"
            f"📱 Телефон: <code>{order.phone}</code>\n\n"
            f"💡 Натисніть на номер щоб скопіювати"
        )
    
    @router.message(F.text == "🗺️ Маршрут")
    async def show_route_map(message: Message) -> None:
        """Показати маршрут на карті"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        # Створити посилання на Google Maps маршрут
        if order.pickup_lat and order.pickup_lon and order.dest_lat and order.dest_lon:
            maps_url = (
                f"https://www.google.com/maps/dir/?api=1"
                f"&origin={order.pickup_lat},{order.pickup_lon}"
                f"&destination={order.dest_lat},{order.dest_lon}"
                f"&travelmode=driving"
            )
            
            clean_pickup = clean_address(order.pickup_address)
            clean_destination = clean_address(order.destination_address)
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🗺️ Відкрити маршрут на Google Maps", url=maps_url)]
                ]
            )
            
            await message.answer(
                f"🗺️ <b>Маршрут поїздки:</b>\n\n"
                f"📍 <b>Звідки:</b>\n{clean_pickup}\n\n"
                f"🎯 <b>Куди:</b>\n{clean_destination}\n\n"
                f"💡 Натисніть кнопку нижче щоб відкрити маршрут",
                reply_markup=kb
            )
        else:
            await message.answer(
                "⚠️ Координати маршруту відсутні.\n\n"
                "Використовуйте адреси:\n"
                f"📍 Звідки: {clean_address(order.pickup_address)}\n"
                f"🎯 Куди: {clean_address(order.destination_address)}"
            )
    
    @router.message(F.text == "ℹ️ Допомога")
    async def trip_help_button(message: Message) -> None:
        """Інструкції для водія (універсальна - працює завжди)"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        
        # Перевірити чи є активне замовлення
        active_order = None
        if driver:
            active_order = await get_active_order_for_driver(config.database_path, driver.id)
        
        if active_order:
            # Допомога під час поїздки
            help_text = (
                "ℹ️ <b>Допомога - Керування поїздкою</b>\n\n"
                "<b>Крок 1:</b> 🚗 <b>В дорозі</b>\n"
                "Натисніть коли почнете рух до клієнта\n\n"
                "<b>Крок 2:</b> 📍 <b>На місці</b>\n"
                "Натисніть коли приїдете на адресу подачі\n\n"
                "<b>Крок 3:</b> 🚀 <b>Виконую замовлення</b>\n"
                "Натисніть коли клієнт сів і ви почали поїздку\n\n"
                "<b>Крок 4:</b> 🏁 <b>Завершити</b>\n"
                "Натисніть коли доїхали до призначення\n\n"
                "━━━━━━━━━━━━━━━\n\n"
                "<b>Додаткові кнопки:</b>\n\n"
                "❌ <b>Відмовитися</b> - скасувати замовлення\n"
                "📞 <b>Зв'язатися</b> - номер телефону клієнта\n"
                "💬 <b>Підтримка</b> - зв'язок з адміністрацією"
            )
        else:
            # Допомога на головній панелі
            help_text = (
                "ℹ️ <b>ДОПОМОГА ДЛЯ ВОДІЯ</b>\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "🚀 <b>ПОЧАТИ РОБОТУ:</b>\n"
                "1. Натисніть 🚀 Почати роботу\n"
                "2. Увімкніть статус 🟢 Онлайн\n"
                "3. Замовлення надходять в групу вашого міста\n"
                "4. Натисніть ✅ Прийняти на замовленні\n\n"
                
                "📱 <b>ПРИЙНЯТТЯ ЗАМОВЛЕННЯ:</b>\n"
                "• Замовлення з'являється в групі\n"
                "• Перший хто натисне ✅ Прийняти - отримує\n"
                "• Якщо не успіли - чекайте наступне\n\n"
                
                "🎯 <b>ВИКОНАННЯ ЗАМОВЛЕННЯ:</b>\n"
                "1. 🚗 В дорозі - рухайтесь до клієнта\n"
                "2. 📍 На місці - прибули на адресу\n"
                "3. 🚀 Виконую - клієнт сів, їдете\n"
                "4. 🏁 Завершити - доїхали, оплата\n\n"
                
                "💰 <b>ЗАРОБІТОК:</b>\n"
                "• 📊 Мій заробіток - сьогодні\n"
                "• 💳 Комісія - нарахована комісія\n"
                "• 📜 Історія - всі поїздки\n"
                "• 💼 Гаманець - картка для переказів\n\n"
                
                "📊 <b>СТАТИСТИКА:</b>\n"
                "• 📊 Розширена аналітика - детально\n\n"
                
                "⚠️ <b>ПРОБЛЕМИ:</b>\n"
                "• Не приходять замовлення → перевірте статус (має бути 🟢 Онлайн)\n"
                "• Кнопка не працює → спробуйте ще раз через 1 хв\n"
                "• Технічні питання → 💬 Підтримка\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                "💡 Для детальних інструкцій натисніть:\n"
                "📖 Правила користування"
            )
        
        # Inline кнопка "Зрозуміло"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Зрозуміло", callback_data="help:close")]
            ]
        )
        
        await message.answer(help_text, reply_markup=kb)
    
    @router.callback_query(F.data == "help:close")
    async def close_help(call: CallbackQuery) -> None:
        """Закрити допомогу"""
        await call.answer("✅")
        try:
            await call.message.delete()
        except:
            pass
    
    @router.callback_query(F.data == "dismiss_msg")
    async def dismiss_message_handler(call: CallbackQuery) -> None:
        """Видалити повідомлення про завершення поїздки"""
        await call.answer("✅")
        try:
            await call.message.delete()
        except:
            pass
    
    @router.message(F.text == "💬 Підтримка")
    async def trip_support_button(message: Message) -> None:
        """Зв'язок з адміністрацією"""
        admin_ids = config.bot.admin_ids
        
        if admin_ids and len(admin_ids) > 0:
            admin_id = admin_ids[0]  # Перший адмін зі списку
            admin_link = f"tg://user?id={admin_id}"
            
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📨 Написати адміну", url=admin_link)]
                ]
            )
            
            await message.answer(
                "💬 <b>Зв'язок з підтримкою</b>\n\n"
                "Натисніть кнопку нижче щоб написати адміністратору:\n\n"
                "💡 Опишіть вашу проблему детально",
                reply_markup=kb
            )
        else:
            await message.answer(
                "💬 <b>Зв'язок з підтримкою</b>\n\n"
                "❌ Контакт адміністратора не налаштовано"
            )
    
    @router.message(F.text == "📖 Правила користування")
    async def show_driver_rules(message: Message) -> None:
        """Показати правила користування для водіїв"""
        if not message.from_user:
            return
        
        # Видалити повідомлення користувача
        try:
            await message.delete()
        except:
            pass
        
        rules_text = (
            "📖 <b>ПРАВИЛА ДЛЯ ВОДІЇВ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "🚀 <b>1. ПОЧАТОК РОБОТИ</b>\n"
            "   • Натисніть 🚗 Панель водія\n"
            "   • Переконайтесь що статус: 🟢 Онлайн\n"
            "   • Якщо 🔴 Офлайн - натисніть 📋 Почати роботу\n"
            "   • Замовлення надходять в групу вашого міста\n\n"
            
            "📱 <b>2. ПРИЙНЯТТЯ ЗАМОВЛЕННЯ</b>\n"
            "   • В групі з'явиться нове замовлення:\n"
            "      - Інформація про клієнта (ім'я, телефон)\n"
            "      - Звідки та куди їхати\n"
            "      - Вартість поїздки\n"
            "   • Натисніть ✅ Прийняти замовлення\n"
            "   • Перший хто натисне - отримає замовлення\n\n"
            
            "🎯 <b>3. ВИКОНАННЯ ЗАМОВЛЕННЯ (4 ЕТАПИ)</b>\n\n"
            "   <b>Етап 1: 🚗 В дорозі</b>\n"
            "   • Натисніть коли починаєте рух до клієнта\n"
            "   • Використовуйте посилання \"📍 Відкрити на карті\"\n"
            "   • Їдьте до адреси подачі\n\n"
            
            "   <b>Етап 2: 📍 На місці</b>\n"
            "   • Натисніть коли приїхали на адресу подачі\n"
            "   • Клієнт отримає повідомлення \"Водій на місці\"\n"
            "   • Зустрічайте клієнта\n\n"
            
            "   <b>Етап 3: 🚀 Виконую замовлення</b>\n"
            "   • Натисніть коли клієнт сів в авто\n"
            "   • Використовуйте навігацію до призначення\n"
            "   • Їдьте безпечно!\n\n"
            
            "   <b>Етап 4: 🏁 Завершити</b>\n"
            "   • Натисніть коли доїхали до призначення\n"
            "   • Клієнт отримає запит на оцінку\n"
            "   • Ви повернетесь до панелі водія\n"
            "   • Заробіток та комісія будуть нараховані\n\n"
            
            "🔧 <b>4. ДОДАТКОВІ КНОПКИ</b>\n\n"
            "   ❌ <b>Відмовитися</b>\n"
            "   • Якщо не можете виконати замовлення\n"
            "   • Замовлення повернеться іншим водіям\n"
            "   • Клієнт буде повідомлений\n\n"
            
            "   📞 <b>Зв'язатися з клієнтом</b>\n"
            "   • Показує ім'я та телефон клієнта\n"
            "   • Можна передзвонити для уточнення\n\n"
            
            "   ℹ️ <b>Допомога</b>\n"
            "   • Покрокові інструкції\n"
            "   • Пояснення всіх кнопок\n\n"
            
            "   💬 <b>Підтримка</b>\n"
            "   • Прямий зв'язок з адміністратором\n"
            "   • Швидке вирішення проблем\n\n"
            
            "💰 <b>5. ОПЛАТА ТА КОМІСІЯ</b>\n\n"
            "   • <b>Готівка:</b> Отримуєте від клієнта\n"
            "   • <b>Картка:</b> Клієнт переводить на вашу картку\n"
            "   • <b>Комісія:</b> Нараховується автоматично\n"
            "      - Перегляд: 💳 Комісія\n"
            "      - Сплата: На вказану картку в боті\n"
            "      - Після сплати: натисніть \"✅ Комісію сплачено\"\n"
            "      - Адмін підтвердить → комісія анулюється\n\n"
            
            "📊 <b>6. СТАТИСТИКА</b>\n\n"
            "   • 📊 Мій заробіток - сьогоднішні доходи\n"
            "   • 📜 Історія поїздок - всі ваші поїздки\n"
            "   • 📊 Розширена аналітика - детальна статистика\n"
            "   • 💼 Гаманець - управління карткою для переказів\n\n"
            
            "⭐ <b>7. РЕЙТИНГ</b>\n\n"
            "   • Клієнти оцінюють вас після кожної поїздки\n"
            "   • Високий рейтинг = більше замовлень\n"
            "   • Середній рейтинг показується в профілі\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "💡 <b>ВАЖЛИВІ ПОРАДИ:</b>\n\n"
            "✅ Будьте ввічливими з клієнтами\n"
            "✅ Приїжджайте вчасно\n"
            "✅ Підтримуйте чистоту в авто\n"
            "✅ Дотримуйтесь ПДР\n"
            "✅ Оновлюйте геолокацію для live tracking\n"
            "✅ Сплачуйте комісію вчасно\n\n"
            
            "⚠️ <b>ЗАБОРОНЕНО:</b>\n\n"
            "❌ Відмовлятися без причини\n"
            "❌ Просити додаткову оплату\n"
            "❌ Неввічлива поведінка\n"
            "❌ Порушення ПДР\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "🎉 <b>Успішної роботи!</b> 🚗"
        )
        
        # Inline кнопка "Зрозуміло"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Зрозуміло", callback_data="driver_rules:close")]
            ]
        )
        
        await message.answer(rules_text, reply_markup=kb)
        logger.info(f"📖 Водій {message.from_user.id} переглядає правила користування")
    
    @router.callback_query(F.data == "driver_rules:close")
    async def close_driver_rules(call: CallbackQuery) -> None:
        """Закрити правила водія"""
        await call.answer("✅")
        
        try:
            await call.message.delete()
        except:
            pass
    
    @router.callback_query(F.data == "driver:panel")
    async def back_to_driver_panel(call: CallbackQuery) -> None:
        """Повернення до панелі водія"""
        if not call.from_user:
            return
        
        await call.answer("✅")
        
        # Видалити поточне повідомлення
        try:
            await call.message.delete()
        except:
            pass
        
        # Отримати інформацію про водія
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.status != "approved":
            await call.message.answer(
                "❌ Ви не зареєстровані як водій або ваша заявка ще не підтверджена."
            )
            return
        
        # Перевірка активного замовлення
        active_order = await get_active_order_for_driver(config.database_path, driver.id)
        
        # Заробіток
        earnings, commission = await get_driver_earnings_today(config.database_path, call.from_user.id)
        net = earnings - commission
        
        # Чайові
        tips = 0.0
        try:
            tips = await get_driver_tips_total(config.database_path, call.from_user.id)
        except:
            tips = 0.0
        
        # Статус
        status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        
        # Текст повідомлення
        text = (
            f"🚗 <b>ПАНЕЛЬ ВОДІЯ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Водій:</b> {driver.full_name}\n"
            f"📱 <b>Телефон:</b> {driver.phone}\n"
            f"🏙 <b>Місто:</b> {driver.city or 'Не вказано'}\n"
            f"🚗 <b>Авто:</b> {driver.car_make} {driver.car_model}\n"
            f"🔖 <b>Номер:</b> {driver.car_plate}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 <b>Статус:</b> {status}\n\n"
            f"💰 <b>Заробіток сьогодні:</b>\n"
            f"   • Загальний: {earnings:.2f} грн\n"
            f"   • Комісія: {commission:.2f} грн\n"
            f"   • Чистий: {net:.2f} грн\n"
            f"   • Чайові: {tips:.2f} грн\n\n"
        )
        
        if active_order:
            text += (
                f"🔴 <b>АКТИВНЕ ЗАМОВЛЕННЯ #{active_order.id}</b>\n"
                f"Статус: {active_order.status}\n\n"
            )
        
        # Клавіатура
        await call.message.answer(text, reply_markup=driver_panel_keyboard())
    
    @router.callback_query(F.data.startswith("show_card:"))
    async def show_card_to_client(call: CallbackQuery) -> None:
        """Показати картку водія клієнту"""
        if not call.from_user:
            return
        
        try:
            order_id = int(call.data.split(":")[1])
        except:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        order = await get_order_by_id(config.database_path, order_id)
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if not order.driver_id:
            await call.answer("❌ Водій не призначений", show_alert=True)
            return
        
        driver = await get_driver_by_id(config.database_path, order.driver_id)
        if not driver or not driver.card_number:
            await call.answer("❌ Картка водія недоступна", show_alert=True)
            return
        
        await call.answer()
        
        card_message = (
            f"💳 <b>КАРТКА ДЛЯ ОПЛАТИ ПОЇЗДКИ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Водій:</b> {driver.full_name}\n"
            f"💳 <b>Номер картки:</b>\n"
            f"<code>{driver.card_number}</code>\n\n"
            f"💰 <b>До сплати:</b> {int(order.fare_amount):.0f} грн\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 <b>Інструкція:</b>\n"
            f"1. Натисніть на номер картки щоб скопіювати\n"
            f"2. Перейдіть в свій банківський додаток\n"
            f"3. Виконайте переказ на цю картку\n"
            f"4. Після оплати натисніть 'Я оплатив'\n\n"
            f"⚠️ Водій отримає повідомлення про оплату"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я оплатив(ла) поїздку", callback_data=f"paid:confirm:{order_id}")]
            ]
        )
        
        await call.message.edit_text(card_message, reply_markup=kb)
    
    @router.callback_query(F.data.startswith("back_to_order:"))
    async def back_to_order_info(call: CallbackQuery) -> None:
        """Повернутися до інформації про замовлення"""
        if not call.from_user:
            return
        
        try:
            order_id = int(call.data.split(":")[1])
        except:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        order = await get_order_by_id(config.database_path, order_id)
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if not order.driver_id:
            await call.answer("❌ Водій не призначений", show_alert=True)
            return
        
        driver = await get_driver_by_id(config.database_path, order.driver_id)
        if not driver:
            await call.answer("❌ Водій не знайдений", show_alert=True)
            return
        
        await call.answer()
        
        # Відобразити інформацію про замовлення з водієм
        payment_emoji = "💵" if order.payment_method == "cash" else "💳"
        
        # Кнопки для клієнта
        kb_client_buttons = []
        
        # Кнопка картки (якщо оплата карткою)
        if order.payment_method == "card" and driver.card_number:
            kb_client_buttons.append([
                InlineKeyboardButton(text="💳 Картка водія", callback_data=f"show_card:{order_id}")
            ])
        
        # Кнопка маршруту
        if order.pickup_lat and order.pickup_lon and order.dest_lat and order.dest_lon:
            kb_client_buttons.append([
                InlineKeyboardButton(
                    text="🗺️ Маршрут на карті",
                    url=f"https://www.google.com/maps/dir/?api=1&origin={order.pickup_lat},{order.pickup_lon}&destination={order.dest_lat},{order.dest_lon}"
                )
            ])
        
        # Кнопка де зараз водій
        if driver.last_lat and driver.last_lon:
            kb_client_buttons.append([
                InlineKeyboardButton(
                    text="📍 Де зараз водій?",
                    url=f"https://www.google.com/maps?q={driver.last_lat},{driver.last_lon}"
                )
            ])
        
        kb_client = InlineKeyboardMarkup(inline_keyboard=kb_client_buttons)
        
        # Компактне повідомлення
        client_message = (
            f"✅ <b>ВОДІЙ ПРИЙНЯВ ЗАМОВЛЕННЯ!</b>\n\n"
            f"👤 <b>{driver.full_name}</b>\n"
            f"🚗 {driver.car_make} {driver.car_model} • {driver.car_plate}\n"
            f"📱 {driver.phone}\n"
            f"⭐ {driver.total_orders} успішних поїздок\n\n"
            f"💰 <b>До сплати:</b> {int(order.fare_amount):.0f} грн {payment_emoji}\n\n"
            f"📍 <b>Водій їде до вас!</b>\n"
            f"Геолокація водія надіслана нижче ⬇️"
        )
        
        await call.message.edit_text(client_message, reply_markup=kb_client)
    
    @router.callback_query(F.data.startswith("paid:confirm:"))
    async def confirm_payment(call: CallbackQuery) -> None:
        """Клієнт підтвердив оплату"""
        if not call.from_user:
            return
        
        try:
            order_id = int(call.data.split(":")[2])
        except:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        order = await get_order_by_id(config.database_path, order_id)
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        # Сповістити водія
        if order.driver_id:
            driver = await get_driver_by_id(config.database_path, order.driver_id)
            if driver:
                try:
                    await call.bot.send_message(
                        driver.tg_user_id,
                        f"💳 <b>КЛІЄНТ ПІДТВЕРДИВ ОПЛАТУ!</b>\n\n"
                        f"Замовлення #{order_id}\n"
                        f"💰 Сума: {int(order.fare_amount):.0f} грн\n\n"
                        f"⚠️ Перевірте надходження коштів на картку!"
                    )
                except:
                    pass
        
        # Повернути компактне повідомлення про замовлення
        driver = await get_driver_by_id(config.database_path, order.driver_id) if order.driver_id else None
        
        if driver:
            # Компактна інформація про замовлення після оплати
            order_info = (
                f"✅ <b>Водій прийняв ваше замовлення</b>\n\n"
                f"🚗 {driver.full_name}\n"
                f"🚙 {driver.car_make} {driver.car_model} ({driver.car_plate})\n"
                f"📱 {driver.phone}\n\n"
                f"💳 <b>Оплата підтверджена!</b>\n"
                f"💰 {int(order.fare_amount):.0f} грн\n\n"
                f"🚗 Гарної поїздки!"
            )
            
            await call.message.edit_text(order_info)
        else:
            await call.message.edit_text(
                "✅ <b>ДЯКУЄМО ЗА ОПЛАТУ!</b>\n\n"
                "Водій отримав повідомлення.\n"
                "Гарної поїздки! 🚗"
            )
        
        await call.answer("✅ Дякуємо! Оплату підтверджено", show_alert=True)
    
    @router.callback_query(F.data == "work:earnings")
    async def show_work_earnings(call: CallbackQuery) -> None:
        """📊 Детальна інфографіка заробітку"""
        if not call.from_user:
            return
        
        await call.answer()
        
        # Отримати детальну статистику
        earnings_data = await get_driver_detailed_earnings_today(
            config.database_path, 
            call.from_user.id
        )
        
        # Створити інфографіку
        infographic = format_earnings_infographic(
            total=earnings_data['total'],
            cash=earnings_data['cash'],
            card=earnings_data['card'],
            commission=earnings_data['commission'],
            trips_count=earnings_data['trips_count'],
            hours_worked=earnings_data['hours_worked']
        )
        
        # Додати кнопку оновлення
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Оновити", callback_data="work:earnings")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="work:refresh")]
            ]
        )
        
        await call.bot.send_message(
            call.from_user.id,
            infographic,
            reply_markup=kb
        )
    
    
    @router.callback_query(F.data == "settings:update_location")
    async def update_location_prompt(call: CallbackQuery) -> None:
        """Попросити водія оновити геолокацію"""
        await call.answer()
        
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Надіслати мою геолокацію", request_location=True)]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await call.bot.send_message(
            call.from_user.id,
            "📍 <b>Оновлення геолокації</b>\n\n"
            "Натисніть кнопку нижче щоб надіслати вашу поточну геолокацію.\n\n"
            "💡 Це допоможе клієнтам бачити вашу позицію під час поїздки.",
            reply_markup=kb
        )
    
    @router.message(F.text == "⚙️ Особиста інформація")
    async def driver_settings_menu(message: Message) -> None:
        """Особиста інформація водія - КАРМА, СТАТИСТИКА, ЗАРОБІТОК"""
        logger.info(f"🔧 Налаштування: отримано запит від {message.from_user.id if message.from_user else 'Unknown'}")
        
        if not message.from_user:
            logger.error("❌ Налаштування: message.from_user is None!")
            return
        
        # 🚫 ПЕРЕВІРКА БЛОКУВАННЯ
        from app.handlers.driver_blocked_check import check_driver_blocked_and_notify
        if await check_driver_blocked_and_notify(config.database_path, message):
            return
        
        # Видалити повідомлення користувача
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"⚠️ Не вдалося видалити повідомлення: {e}")
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        
        # Якщо НЕ водій → помилка
        if not driver:
            logger.warning(f"❌ Користувач {message.from_user.id} не є водієм")
            await message.answer(
                "❌ Ви не зареєстровані як водій",
                reply_markup=driver_panel_keyboard()
            )
            return
        
        logger.info(f"✅ Водій {driver.id} ({driver.full_name}) - генерую налаштування")
        logger.info(f"📊 Водій дані: city={driver.city}, card={driver.card_number}, karma={getattr(driver, 'karma', None)}")
        
        # Отримати заробіток сьогодні
        earnings_today, commission_today = await get_driver_earnings_today(
            config.database_path,
            message.from_user.id
        )
        net_today = earnings_today - commission_today
        
        # Карма (100 - ідеально, мінусується за відмови)
        karma = driver.karma if hasattr(driver, 'karma') else 100
        
        # Статистика
        total_orders = driver.total_orders if hasattr(driver, 'total_orders') else 0
        rejected_orders = driver.rejected_orders if hasattr(driver, 'rejected_orders') else 0
        completed_orders = total_orders - rejected_orders
        
        # Відсоток відмов
        reject_percent = (rejected_orders / total_orders * 100) if total_orders > 0 else 0
        
        # Візуальна карма з кольорами
        karma_visual = format_karma(karma)
        
        # Перевірка геолокації
        from app.utils.location_tracker import check_driver_location_status
        loc_status = await check_driver_location_status(config.database_path, message.from_user.id)
        
        if not loc_status['has_location']:
            location_text = "📍 Геолокація: ❌ Не встановлена"
        elif loc_status['status'] == 'stale':
            age = loc_status['age_minutes']
            hours = age / 60.0
            location_text = f"📍 Геолокація: ⚠️ Застаріла ({hours:.1f}год)"
        elif loc_status['status'] == 'warning':
            age = loc_status['age_minutes']
            location_text = f"📍 Геолокація: ⚠️ Потребує оновлення ({age}хв)"
        else:  # fresh
            age = loc_status['age_minutes']
            location_text = f"📍 Геолокація: ✅ Актуальна ({age}хв)"
        
        # Перевірка повноти профілю
        car_color = getattr(driver, 'car_color', None)
        
        missing_fields = []
        if not driver.city:
            missing_fields.append("🏙 Місто")
        if not driver.card_number:
            missing_fields.append("💳 Картка")
        if not car_color:
            missing_fields.append("🎨 Колір авто")
        # ❌ ВИДАЛЕНО: Геолокація не обов'язкова для онлайн
        
        # Попередження якщо профіль неповний
        profile_warning = ""
        if missing_fields:
            profile_warning = (
                f"⚠️ <b>ПРОФІЛЬ НЕ ЗАПОВНЕНИЙ</b>\n\n"
                f"Відсутні дані:\n"
                + "\n".join(f"• {field}" for field in missing_fields) +
                f"\n\n❌ Ви не зможете приймати замовлення!\n"
                f"👇 Заповніть профіль нижче\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
        
        # Формуємо текст по частинах для кращої діагностики
        try:
            text = (
                f"⚙️ <b>ОСОБИСТА ІНФОРМАЦІЯ ВОДІЯ</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{profile_warning}"
                f"👤 <b>ОСОБИСТА ІНФОРМАЦІЯ:</b>\n\n"
                f"👨‍✈️ ПІБ: {driver.full_name}\n"
                f"📱 Телефон: {driver.phone}\n"
                f"🏙 Місто: {driver.city or '❌ Не вказано'}\n"
                f"🚗 Авто: {driver.car_make} {driver.car_model}\n"
                f"🔢 Номер: {driver.car_plate}\n"
                f"🎨 Колір: {car_color or '❌ Не вказано'}\n"
                f"💳 Картка: {driver.card_number or '❌ Не додана'}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 <b>РЕЙТИНГ:</b>\n\n"
                f"{karma_visual}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 <b>СТАТИСТИКА:</b>\n\n"
                f"📦 Всього замовлень: {total_orders}\n"
                f"✅ Виконано: {completed_orders}\n"
                f"❌ Відмов: {rejected_orders} ({reject_percent:.1f}%)\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 <b>ЗАРОБІТОК СЬОГОДНІ:</b>\n\n"
                f"💵 Заробіток: {earnings_today:.0f} грн\n"
                f"💳 Комісія ({int((commission_today / earnings_today * 100) if earnings_today > 0 else 0)}%): {commission_today:.0f} грн\n"
                f"💰 Чистий: {net_today:.0f} грн\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"💡 <b>ЯК ПРАЦЮЄ КАРМА:</b>\n"
                f"• Старт: 100 балів\n"
                f"• Відмова: -5 балів\n"
                f"• Успіх: +1 бал (макс 100)\n"
                f"• Низька (&lt;50): ⚠️ Попередження"
            )
            logger.info(f"✅ Текст сформовано, довжина: {len(text)}")
        except Exception as e:
            logger.error(f"❌ Помилка формування тексту: {e}", exc_info=True)
            await message.answer(
                "❌ Помилка формування даних профілю",
                reply_markup=driver_panel_keyboard()
            )
            return
        
        # Кнопки з підсвічуванням відсутніх полів
        buttons = []
        
        if missing_fields:
            # Якщо профіль неповний - показати кнопки заповнення
            if not driver.city:
                buttons.append([InlineKeyboardButton(text="🏙 ⚠️ ВКАЗАТИ МІСТО", callback_data="settings:set_city")])
            # ❌ ПРИБРАНО: Кнопки для картки і кольору - редагуються через Гаманець
            buttons.append([InlineKeyboardButton(text="━━━━━━━━━━━━━━━━━━", callback_data="noop")])
        
        # Завжди показати основні налаштування
        buttons.extend([
            [InlineKeyboardButton(text="🚗 Змінити клас авто", callback_data="settings:car_class")],
            [InlineKeyboardButton(text="🏙 Місто роботи", callback_data="settings:set_city")],
            [InlineKeyboardButton(text="🔄 Оновити інформацію", callback_data="settings:refresh")]
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        logger.info(f"📤 Надсилаю налаштування водію {driver.id}, довжина тексту: {len(text)} символів")
        
        try:
            sent = await message.answer(text, reply_markup=kb)
            logger.info(f"✅ Налаштування надіслано успішно, message_id={sent.message_id}")
        except Exception as e:
            logger.error(f"❌ ПОМИЛКА надсилання налаштувань: {e}", exc_info=True)
            await message.answer(
                "❌ Помилка завантаження налаштувань. Спробуйте ще раз.",
                reply_markup=driver_panel_keyboard()
            )
    
    @router.callback_query(F.data == "settings:refresh")
    async def refresh_settings(call: CallbackQuery) -> None:
        """Оновити налаштування - викликати driver_settings_menu"""
        if not call.from_user:
            return
        
        await call.answer("🔄 Оновлюю...")
        
        # Видалити попереднє повідомлення
        try:
            await call.message.delete()
        except:
            pass
        
        # Створити fake message для виклику driver_settings_menu
        fake_msg = Message(
            message_id=call.message.message_id if call.message else 0,
            date=call.message.date if call.message else datetime.now(timezone.utc),
            chat=call.message.chat if call.message else call.from_user,
            from_user=call.from_user,
            text="⚙️ Особиста інформація"
        )
        
        # Викликати основний обробник налаштувань
        await driver_settings_menu(fake_msg)
    
    # ==================== ЗАПОВНЕННЯ ПРОФІЛЮ ====================
    
    @router.callback_query(F.data == "noop")
    async def noop_handler(call: CallbackQuery) -> None:
        """Порожній обробник для роздільників"""
        await call.answer()
    
    @router.callback_query(F.data == "settings:set_city")
    async def prompt_city(call: CallbackQuery, state: FSMContext) -> None:
        """Попросити вказати місто"""
        await call.answer()
        await state.set_state(DriverProfileStates.waiting_for_city)
        
        # Використовуємо офіційний список міст з config
        from app.config.config import AVAILABLE_CITIES
        
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Київ"), KeyboardButton(text="Дніпро")],
                [KeyboardButton(text="Кривий Ріг"), KeyboardButton(text="Харків")],
                [KeyboardButton(text="Одеса")],
                [KeyboardButton(text="❌ Скасувати")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await call.bot.send_message(
            call.from_user.id,
            "🏙 <b>Вкажіть місто роботи</b>\n\n"
            "Оберіть місто зі списку:",
            reply_markup=kb
        )
    
    @router.message(DriverProfileStates.waiting_for_city)
    async def process_city(message: Message, state: FSMContext) -> None:
        """Зберегти місто"""
        if not message.text or message.text == "❌ Скасувати":
            await state.clear()
            await message.answer(
                "❌ Скасовано",
                reply_markup=driver_panel_keyboard()
            )
            return
        
        city = message.text.strip()
        
        # Оновити місто в БД
        from app.storage.db import db_manager
        async with db_manager.connect(config.database_path) as db:
            await db.execute(
                "UPDATE drivers SET city = ? WHERE tg_user_id = ?",
                (city, message.from_user.id)
            )
            await db.commit()
        
        await state.clear()
        
        # Повідомлення про необхідність звернутися до адміна
        admin_username = config.admin_username or "адміністратора"
        admin_link = f"@{admin_username}" if config.admin_username else "адміністратора"
        
        await message.answer(
            f"✅ <b>Місто збережено: {city}</b>\n\n"
            f"📢 <b>Для доступу до групи водіїв міста {city}</b>\n"
            f"зверніться за допомогою до адміна: {admin_link}\n\n"
            f"💡 Адмін додасть вас до групи вашого міста,\n"
            f"де ви зможете отримувати замовлення.",
            reply_markup=driver_panel_keyboard()
        )
        
        logger.info(f"✅ Водій {message.from_user.id} встановив місто: {city}")
    
    # ❌ ВИДАЛЕНО: Обробники settings:set_color та process_color
    # Колір авто вказується тільки при реєстрації і не редагується
    
    @router.callback_query(F.data == "settings:car_class")
    async def prompt_car_class(call: CallbackQuery, state: FSMContext) -> None:
        """Попросити вибрати клас автомобіля"""
        await call.answer()
        
        # Отримати поточний клас
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        current_class = driver.car_class if driver else "economy"
        
        # Маппінг класів на українські назви
        class_names = {
            "economy": "Економ",
            "standard": "Стандарт",
            "comfort": "Комфорт",
            "business": "Бізнес"
        }
        
        # Створити inline клавіатуру з вибором класу
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{'✅ ' if current_class == 'economy' else ''}{class_names['economy']}",
                    callback_data="set_car_class:economy"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if current_class == 'standard' else ''}{class_names['standard']}",
                    callback_data="set_car_class:standard"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if current_class == 'comfort' else ''}{class_names['comfort']}",
                    callback_data="set_car_class:comfort"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if current_class == 'business' else ''}{class_names['business']}",
                    callback_data="set_car_class:business"
                )],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="settings:refresh")]
            ]
        )
        
        await call.message.edit_text(
            "🚗 <b>Оберіть клас автомобіля</b>\n\n"
            f"Поточний клас: <b>{class_names.get(current_class, 'Економ')}</b>\n\n"
            "Виберіть новий клас із списку:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data.startswith("set_car_class:"))
    async def save_car_class(call: CallbackQuery) -> None:
        """Зберегти вибраний клас автомобіля"""
        if not call.from_user:
            return
        
        try:
            car_class = call.data.split(":")[1]
        except:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        # Перевірка валідності класу
        valid_classes = ["economy", "standard", "comfort", "business"]
        if car_class not in valid_classes:
            await call.answer("❌ Невірний клас автомобіля", show_alert=True)
            return
        
        # Оновити клас авто в БД
        from app.storage.db import db_manager
        async with db_manager.connect(config.database_path) as db:
            await db.execute(
                "UPDATE drivers SET car_class = ? WHERE tg_user_id = ?",
                (car_class, call.from_user.id)
            )
            await db.commit()
        
        # Маппінг класів на українські назви
        class_names = {
            "economy": "Економ",
            "standard": "Стандарт",
            "comfort": "Комфорт",
            "business": "Бізнес"
        }
        
        await call.answer(f"✅ Клас змінено на {class_names[car_class]}", show_alert=True)
        
        # Оновити налаштування
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            return
        
        # Перевірити обов'язкові поля
        car_color = driver.car_color if hasattr(driver, 'car_color') else None
        
        text = (
            f"⚙️ <b>ОСОБИСТА ІНФОРМАЦІЯ ВОДІЯ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Ім'я:</b> {driver.full_name}\n"
            f"📱 <b>Телефон:</b> {driver.phone}\n"
            f"🏙 <b>Місто:</b> {driver.city or '❌ Не вказано'}\n"
            f"🚗 <b>Авто:</b> {driver.car_make} {driver.car_model}\n"
            f"🎨 <b>Колір:</b> {car_color or '❌ Не вказано'}\n"
            f"🔖 <b>Номер:</b> {driver.car_plate}\n"
            f"🚗 <b>Клас:</b> {class_names.get(driver.car_class, 'Економ')}\n"
            f"💳 <b>Картка:</b> {driver.card_number or '❌ Не вказано'}\n\n"
        )
        
        # Кнопки налаштувань
        buttons = []
        
        # Перевірка обов'язкових полів
        if not driver.city or not driver.card_number or not car_color:
            text += "⚠️ <b>УВАГА! Потрібно заповнити:</b>\n"
            if not driver.city:
                text += "   • Місто роботи\n"
                buttons.append([InlineKeyboardButton(text="🏙 ⚠️ ВКАЗАТИ МІСТО", callback_data="settings:set_city")])
            if not driver.card_number:
                text += "   • Картку для переказів (додайте в 💼 Гаманець)\n"
            # ❌ ПРИБРАНО: Колір авто - редагується тільки при реєстрації
            buttons.append([InlineKeyboardButton(text="━━━━━━━━━━━━━━━━━━", callback_data="noop")])
        
        # Показати тільки основні налаштування
        buttons.extend([
            [InlineKeyboardButton(text="🚗 Змінити клас авто", callback_data="settings:car_class")],
            [InlineKeyboardButton(text="🏙 Місто роботи", callback_data="settings:set_city")],
            [InlineKeyboardButton(text="🔄 Оновити інформацію", callback_data="settings:refresh")]
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except:
            await call.message.answer(text, reply_markup=kb)
        
        logger.info(f"✅ Водій {call.from_user.id} змінив клас авто на: {car_class}")
    
    @router.callback_query(F.data == "settings:card")
    async def prompt_card(call: CallbackQuery, state: FSMContext) -> None:
        """Попросити вказати номер картки"""
        await call.answer()
        await state.set_state(DriverProfileStates.waiting_for_card)
        
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Скасувати")]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await call.bot.send_message(
            call.from_user.id,
            "💳 <b>Введіть номер картки для переказів</b>\n\n"
            "Формат: 16 цифр (можна з пробілами)\n"
            "Приклад: 4149 4999 1234 5678\n\n"
            "💡 На цю картку буде переводитись комісія 2%",
            reply_markup=kb
        )
    
    @router.message(DriverProfileStates.waiting_for_card)
    async def process_card(message: Message, state: FSMContext) -> None:
        """Зберегти номер картки"""
        if not message.text or message.text == "❌ Скасувати":
            await state.clear()
            await message.answer(
                "❌ Скасовано",
                reply_markup=driver_panel_keyboard()
            )
            return
        
        card = message.text.strip()
        
        # Валідація номера картки (тільки цифри, 16 символів)
        card_digits = ''.join(filter(str.isdigit, card))
        if len(card_digits) != 16:
            await message.answer(
                "❌ Невірний номер картки!\n\n"
                "Має бути 16 цифр. Спробуйте ще раз:"
            )
            return
        
        # Форматувати 4149 4999 1234 5678
        formatted_card = ' '.join([card_digits[i:i+4] for i in range(0, 16, 4)])
        
        # Оновити в БД
        from app.storage.db import db_manager
        async with db_manager.connect(config.database_path) as db:
            await db.execute(
                "UPDATE drivers SET card_number = ? WHERE tg_user_id = ?",
                (formatted_card, message.from_user.id)
            )
            await db.commit()
        
        await state.clear()
        await message.answer(
            f"✅ Картка збережена:\n<code>{formatted_card}</code>\n\n"
            f"💡 На цю картку переводиться комісія 2%",
            reply_markup=driver_panel_keyboard()
        )
        
        logger.info(f"✅ Водій {message.from_user.id} встановив картку: {formatted_card}")
    
    return router
