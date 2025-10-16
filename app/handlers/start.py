from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import CommandStart, Command
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

from app.config.config import AppConfig, AVAILABLE_CITIES
from app.storage.db import User, upsert_user, get_user_by_id

logger = logging.getLogger(__name__)


class ClientRegStates(StatesGroup):
    phone = State()
    city = State()


class SavedAddressStates(StatesGroup):
    name = State()
    emoji = State()
    address = State()


def main_menu_keyboard(is_registered: bool = False, is_driver: bool = False, is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Головне меню з кнопками"""
    # АДМІН ПАНЕЛЬ (найвищий пріоритет)
    if is_admin:
        keyboard = [
            [KeyboardButton(text="⚙️ Адмін-панель")],
            [KeyboardButton(text="🚖 Замовити таксі")],
            [KeyboardButton(text="📜 Мої замовлення"), KeyboardButton(text="📍 Мої адреси")],
            [KeyboardButton(text="👤 Мій профіль"), KeyboardButton(text="🆘 SOS")],
        ]
        
        # Якщо адмін також водій - додаємо панель водія
        if is_driver:
            keyboard.append([KeyboardButton(text="🚗 Панель водія")])
        else:
            keyboard.append([KeyboardButton(text="🚗 Стати водієм")])
        
        keyboard.append([KeyboardButton(text="ℹ️ Допомога")])
        
        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Оберіть дію",
        )
    
    if is_driver:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚗 Панель водія")],
                [KeyboardButton(text="📊 Мій заробіток"), KeyboardButton(text="💳 Комісія")],
                [KeyboardButton(text="📜 Історія поїздок")],
                [KeyboardButton(text="👤 Кабінет клієнта"), KeyboardButton(text="ℹ️ Допомога")],
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Оберіть дію",
        )
    
    if is_registered:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚖 Замовити таксі")],
                [KeyboardButton(text="📜 Мої замовлення"), KeyboardButton(text="📍 Мої адреси")],
                [KeyboardButton(text="👤 Мій профіль"), KeyboardButton(text="🎁 Реферальна програма")],
                [KeyboardButton(text="🆘 SOS"), KeyboardButton(text="ℹ️ Допомога")],
                [KeyboardButton(text="🚗 Стати водієм")],
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Оберіть дію",
        )
    
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Зареєструватись")],
            [KeyboardButton(text="ℹ️ Допомога")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Оберіть дію",
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Скасувати")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поділитися контактом", request_contact=True)],
            [KeyboardButton(text="❌ Скасувати")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Надішліть контакт",
    )


def city_selection_keyboard() -> InlineKeyboardMarkup:
    """Інлайн кнопки для вибору міста"""
    buttons = []
    for city in AVAILABLE_CITIES:
        buttons.append([InlineKeyboardButton(text=f"📍 {city}", callback_data=f"city:{city}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def is_valid_phone(text: str) -> bool:
    return bool(re.fullmatch(r"[+]?[\d\s\-()]{7,18}", text.strip()))


def create_router(config: AppConfig) -> Router:
    router = Router(name="start")

    @router.message(CommandStart())
    async def on_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        
        if not message.from_user:
            return
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        
        # Перевірка чи це АДМІН (найвищий пріоритет)
        is_admin = message.from_user.id in config.bot.admin_ids
        
        # Перевірка чи це водій
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        is_driver = driver is not None and driver.status == "approved"
        
        if user and user.phone and user.city:
            # Повна реєстрація
            greeting = "З поверненням, "
            if is_admin:
                greeting = "З поверненням, Адміністратор "
            
            await message.answer(
                f"{greeting}{user.full_name}! 👋\n\n"
                f"📍 Місто: {user.city}\n"
                f"📱 Телефон: {user.phone}\n\n"
                "Оберіть дію з меню нижче:",
                reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin)
            )
        elif user:
            # Неповна реєстрація - пропонуємо завершити
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📱 Завершити реєстрацію", callback_data="register:start")],
                    [InlineKeyboardButton(text="ℹ️ Допомога", callback_data="help:show")],
                ]
            )
            await message.answer(
                f"Вітаємо, {user.full_name}! 👋\n\n"
                "Для замовлення таксі завершіть реєстрацію:\n"
                "• Вкажіть ваше місто\n"
                "• Додайте номер телефону\n\n"
                "Це займе менше хвилини! ⏱",
                reply_markup=kb
            )
        else:
            # Новий користувач
            new_user = User(
                user_id=message.from_user.id,
                full_name=message.from_user.full_name or "Користувач",
                phone="",
                role="client",
                created_at=datetime.now(timezone.utc),
                city=None,
            )
            await upsert_user(config.database_path, new_user)
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📱 Почати реєстрацію", callback_data="register:start")],
                    [InlineKeyboardButton(text="ℹ️ Як це працює?", callback_data="help:show")],
                ]
            )
            
            await message.answer(
                f"Вітаємо в таксі-боті! 🚖\n\n"
                f"Привіт, {message.from_user.full_name}!\n\n"
                "🚕 Швидке замовлення таксі\n"
                "💰 Прозорі ціни\n"
                "⭐️ Перевірені водії\n\n"
                "Почніть з реєстрації - це займе 1 хвилину!",
                reply_markup=kb
            )

    @router.callback_query(F.data == "register:start")
    @router.message(F.text == "📱 Зареєструватись")
    async def start_registration(event, state: FSMContext) -> None:
        # Обробка як callback, так і message
        user_id = event.from_user.id if event.from_user else None
        if not user_id:
            return
        
        user = await get_user_by_id(config.database_path, user_id)
        if user and user.phone and user.city:
            # Перевірка чи це адмін
            is_admin = user_id in config.bot.admin_ids
            from app.storage.db import get_driver_by_tg_user_id
            driver = await get_driver_by_tg_user_id(config.database_path, user_id)
            is_driver = driver is not None and driver.status == "approved"
            
            text = f"✅ Ви вже зареєстровані!\n\n📍 Місто: {user.city}\n📱 Телефон: {user.phone}"
            if isinstance(event, CallbackQuery):
                await event.answer("Ви вже зареєстровані!")
                await event.message.answer(text, reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin))
            else:
                await event.answer(text, reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin))
            return
        
        if isinstance(event, CallbackQuery):
            await event.answer()
        
        # Вибір міста
        text = "📍 <b>Крок 1/2: Оберіть ваше місто</b>\n\nВиберіть місто, в якому ви плануєте користуватися таксі:"
        kb = city_selection_keyboard()
        
        await state.set_state(ClientRegStates.city)
        
        if isinstance(event, CallbackQuery):
            await event.message.answer(text, reply_markup=kb)
        else:
            await event.answer(text, reply_markup=kb)

    @router.callback_query(F.data.startswith("city:"), ClientRegStates.city)
    async def select_city(call: CallbackQuery, state: FSMContext) -> None:
        city = call.data.split(":", 1)[1]
        await state.update_data(city=city)
        await call.answer(f"Обрано: {city}")
        
        await state.set_state(ClientRegStates.phone)
        await call.message.answer(
            f"✅ Місто: {city}\n\n"
            "📱 <b>Крок 2/2: Надайте номер телефону</b>\n\n"
            "Це потрібно щоб водій міг з вами зв'язатись.",
            reply_markup=contact_keyboard()
        )

    @router.message(ClientRegStates.phone, F.contact)
    async def save_phone_contact(message: Message, state: FSMContext) -> None:
        if not message.from_user or not message.contact:
            return
        
        data = await state.get_data()
        city = data.get("city")
        phone = message.contact.phone_number
        
        user = User(
            user_id=message.from_user.id,
            full_name=message.from_user.full_name or "Користувач",
            phone=phone,
            role="client",
            city=city,
            created_at=datetime.now(timezone.utc),
        )
        await upsert_user(config.database_path, user)
        await state.clear()
        
        # Перевірка чи це адмін
        is_admin = message.from_user.id in config.bot.admin_ids
        
        await message.answer(
            f"✅ <b>Реєстрація завершена!</b>\n\n"
            f"👤 {user.full_name}\n"
            f"📍 {city}\n"
            f"📱 {phone}\n\n"
            "Тепер ви можете замовити таксі! 🚖",
            reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
        )
        logger.info(f"User {message.from_user.id} registered in {city}")

    @router.message(ClientRegStates.phone)
    async def save_phone_text(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        
        phone = message.text.strip() if message.text else ""
        if not is_valid_phone(phone):
            await message.answer("❌ Невірний формат номеру.\n\nПриклад: +380 67 123 45 67")
            return
        
        data = await state.get_data()
        city = data.get("city")
        
        user = User(
            user_id=message.from_user.id,
            full_name=message.from_user.full_name or "Користувач",
            phone=phone,
            role="client",
            city=city,
            created_at=datetime.now(timezone.utc),
        )
        await upsert_user(config.database_path, user)
        await state.clear()
        
        # Перевірка чи це адмін
        is_admin = message.from_user.id in config.bot.admin_ids
        
        await message.answer(
            f"✅ <b>Реєстрація завершена!</b>\n\n"
            f"👤 {user.full_name}\n"
            f"📍 {city}\n"
            f"📱 {phone}\n\n"
            "Тепер ви можете замовити таксі! 🚖",
            reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
        )
        logger.info(f"User {message.from_user.id} registered in {city}")

    @router.callback_query(F.data == "help:show")
    @router.message(F.text == "ℹ️ Допомога")
    async def show_help(event) -> None:
        help_text = (
            "ℹ️ <b>Як користуватися ботом?</b>\n\n"
            "<b>Для клієнтів:</b>\n"
            "1️⃣ Зареєструйтесь (вкажіть місто та телефон)\n"
            "2️⃣ Натисніть 🚖 Замовити таксі\n"
            "3️⃣ Вкажіть адресу подачі та призначення\n"
            "4️⃣ Підтвердіть замовлення\n"
            "5️⃣ Очікуйте водія!\n\n"
            "<b>Для водіїв:</b>\n"
            "• Подайте заявку через кнопку 🚗 Стати водієм\n"
            "• Після підтвердження адміністратором отримаєте доступ\n"
            "• Замовлення надходять у групу водіїв\n"
            "• Перший хто прийме - отримує замовлення\n\n"
            "💰 <b>Тарифи:</b>\n"
            "• Базова ціна + відстань + час\n"
            "• Комісія сервісу: 2%\n\n"
            "📞 <b>Підтримка:</b> Напишіть адміністратору"
        )
        
        if isinstance(event, CallbackQuery):
            await event.answer()
            await event.message.answer(help_text)
        else:
            await event.answer(help_text)

    @router.message(F.text == "👤 Мій профіль")
    async def show_profile(message: Message) -> None:
        if not message.from_user:
            return
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        if not user:
            await message.answer("❌ Профіль не знайдено. Зареєструйтесь спочатку.")
            return
        
        # Перевірка активного замовлення
        from app.storage.db import get_user_active_order
        active_order = await get_user_active_order(config.database_path, message.from_user.id)
        
        # Формування кнопок
        buttons = []
        
        if active_order:
            # Якщо є активне замовлення
            if active_order.status == "pending":
                # Замовлення ще не прийняте - можна скасувати
                buttons.append([
                    InlineKeyboardButton(text="🔍 Статус замовлення", callback_data=f"order:status:{active_order.id}"),
                    InlineKeyboardButton(text="❌ Скасувати замовлення", callback_data=f"order:cancel_confirm:{active_order.id}")
                ])
            elif active_order.status in ("accepted", "in_progress"):
                # Замовлення прийняте або виконується - можна відстежити водія
                buttons.append([
                    InlineKeyboardButton(text="🚗 Відстежити водія", callback_data=f"order:track:{active_order.id}"),
                    InlineKeyboardButton(text="📞 Зв'язатись з водієм", callback_data=f"order:contact:{active_order.id}")
                ])
                buttons.append([InlineKeyboardButton(text="🔍 Статус замовлення", callback_data=f"order:status:{active_order.id}")])
        
        # Загальні кнопки
        buttons.append([InlineKeyboardButton(text="📍 Збережені адреси", callback_data="profile:saved_addresses")])
        buttons.append([InlineKeyboardButton(text="📜 Історія замовлень", callback_data="profile:history")])
        buttons.append([
            InlineKeyboardButton(text="✏️ Змінити місто", callback_data="profile:edit:city"),
            InlineKeyboardButton(text="📱 Змінити телефон", callback_data="profile:edit:phone")
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        # Текст профілю
        profile_text = (
            f"👤 <b>Ваш профіль</b>\n\n"
            f"Ім'я: {user.full_name}\n"
            f"📍 Місто: {user.city or 'Не вказано'}\n"
            f"📱 Телефон: {user.phone or 'Не вказано'}\n"
            f"📅 Дата реєстрації: {user.created_at.strftime('%d.%m.%Y')}"
        )
        
        if active_order:
            status_emoji = {
                "pending": "⏳",
                "accepted": "✅",
                "in_progress": "🚗"
            }.get(active_order.status, "❓")
            
            status_text = {
                "pending": "Очікує водія",
                "accepted": "Водія призначено",
                "in_progress": "В дорозі"
            }.get(active_order.status, "Невідомо")
            
            profile_text += f"\n\n{status_emoji} <b>Активне замовлення #{active_order.id}</b>\n"
            profile_text += f"Статус: {status_text}\n"
            profile_text += f"📍 Звідки: {active_order.pickup_address}\n"
            profile_text += f"📍 Куди: {active_order.destination_address}"
        
        await message.answer(profile_text, reply_markup=kb)

    # Обробники кнопок профілю
    @router.callback_query(F.data.startswith("order:status:"))
    async def show_order_status(call: CallbackQuery) -> None:
        """Показати статус замовлення"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[-1])
        
        from app.storage.db import get_order_by_id, get_driver_by_id
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        status_emoji = {
            "pending": "⏳",
            "accepted": "✅",
            "in_progress": "🚗",
            "completed": "✅",
            "cancelled": "❌"
        }.get(order.status, "❓")
        
        status_text = {
            "pending": "Очікує водія",
            "accepted": "Водія призначено",
            "in_progress": "В дорозі",
            "completed": "Завершено",
            "cancelled": "Скасовано"
        }.get(order.status, "Невідомо")
        
        text = (
            f"{status_emoji} <b>Замовлення #{order.id}</b>\n\n"
            f"Статус: <b>{status_text}</b>\n"
            f"📍 Звідки: {order.pickup_address}\n"
            f"📍 Куди: {order.destination_address}\n"
            f"📅 Створено: {order.created_at.strftime('%d.%m.%Y %H:%M')}"
        )
        
        if order.distance_m:
            text += f"\n📏 Відстань: {order.distance_m / 1000:.1f} км"
        
        if order.fare_amount:
            text += f"\n💰 Вартість: {order.fare_amount:.2f} грн"
        
        if order.driver_id:
            driver = await get_driver_by_id(config.database_path, order.driver_id)
            if driver:
                text += f"\n\n🚗 <b>Водій:</b>\n"
                text += f"👤 {driver.full_name}\n"
                text += f"🚙 {driver.car_make} {driver.car_model}\n"
                text += f"🔢 {driver.car_plate}\n"
                text += f"📱 {driver.phone}"
        
        if order.comment:
            text += f"\n\n💬 Коментар: {order.comment}"
        
        await call.answer()
        await call.message.answer(text)
    
    @router.callback_query(F.data.startswith("order:cancel_confirm:"))
    async def confirm_order_cancellation(call: CallbackQuery) -> None:
        """Підтвердження скасування замовлення"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[-1])
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Так, скасувати", callback_data=f"order:cancel_yes:{order_id}"),
                    InlineKeyboardButton(text="❌ Ні, залишити", callback_data="order:cancel_no")
                ]
            ]
        )
        
        await call.answer()
        await call.message.answer(
            "❓ <b>Скасувати замовлення?</b>\n\n"
            "Ви впевнені, що хочете скасувати це замовлення?",
            reply_markup=kb
        )
    
    @router.callback_query(F.data.startswith("order:cancel_yes:"))
    async def cancel_order_confirmed(call: CallbackQuery) -> None:
        """Скасування замовлення підтверджено"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[-1])
        
        from app.storage.db import cancel_order_by_client, get_order_by_id
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if order.status != "pending":
            await call.answer("❌ Замовлення вже не можна скасувати", show_alert=True)
            return
        
        success = await cancel_order_by_client(config.database_path, order_id, call.from_user.id)
        
        if success:
            await call.answer("✅ Замовлення скасовано", show_alert=True)
            await call.message.answer("✅ <b>Замовлення скасовано</b>\n\nВи можете створити нове замовлення будь-коли.")
            
            # Повідомити в групу водіїв
            if order.group_message_id and config.driver_group_chat_id:
                try:
                    await call.bot.edit_message_text(
                        chat_id=config.driver_group_chat_id,
                        message_id=order.group_message_id,
                        text=f"❌ <b>ЗАМОВЛЕННЯ #{order.id} СКАСОВАНО КЛІЄНТОМ</b>\n\n"
                             f"📍 Маршрут: {order.pickup_address} → {order.destination_address}"
                    )
                except Exception as e:
                    logger.error(f"Failed to update group message: {e}")
        else:
            await call.answer("❌ Не вдалося скасувати замовлення", show_alert=True)
    
    @router.callback_query(F.data == "order:cancel_no")
    async def cancel_order_declined(call: CallbackQuery) -> None:
        """Скасування відхилено"""
        await call.answer("✅ Замовлення залишається активним")
        await call.message.delete()
    
    @router.callback_query(F.data.startswith("order:track:"))
    async def track_driver(call: CallbackQuery) -> None:
        """Відстежити водія"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[-1])
        
        from app.storage.db import get_order_by_id, get_driver_by_id
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if not order.driver_id:
            await call.answer("❌ Водія ще не призначено", show_alert=True)
            return
        
        driver = await get_driver_by_id(config.database_path, order.driver_id)
        
        if not driver:
            await call.answer("❌ Інформація про водія недоступна", show_alert=True)
            return
        
        text = (
            f"🚗 <b>Ваш водій:</b>\n\n"
            f"👤 {driver.full_name}\n"
            f"🚙 {driver.car_make} {driver.car_model}\n"
            f"🔢 Номер: {driver.car_plate}\n"
            f"📱 Телефон: {driver.phone}\n\n"
            f"📍 <b>Маршрут:</b>\n"
            f"Звідки: {order.pickup_address}\n"
            f"Куди: {order.destination_address}"
        )
        
        if order.distance_m:
            text += f"\n\n📏 Відстань: {order.distance_m / 1000:.1f} км"
        
        if order.status == "in_progress":
            text += "\n\n🚗 <b>Статус: В дорозі</b>"
        elif order.status == "accepted":
            text += "\n\n✅ <b>Статус: Водій їде до вас</b>"
        
        await call.answer()
        await call.message.answer(text)
    
    @router.callback_query(F.data.startswith("order:contact:"))
    async def contact_driver(call: CallbackQuery) -> None:
        """Зв'язатись з водієм"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[-1])
        
        from app.storage.db import get_order_by_id, get_driver_by_id
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if not order.driver_id:
            await call.answer("❌ Водія ще не призначено", show_alert=True)
            return
        
        driver = await get_driver_by_id(config.database_path, order.driver_id)
        
        if not driver:
            await call.answer("❌ Інформація про водія недоступна", show_alert=True)
            return
        
        await call.answer()
        await call.message.answer(
            f"📞 <b>Контакт водія:</b>\n\n"
            f"👤 {driver.full_name}\n"
            f"📱 {driver.phone}\n\n"
            f"Ви можете зателефонувати водієві за цим номером."
        )
    
    @router.callback_query(F.data == "profile:saved_addresses")
    async def show_saved_addresses(call: CallbackQuery) -> None:
        """Показати збережені адреси"""
        if not call.from_user:
            return
        
        from app.storage.db import get_user_saved_addresses
        addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
        
        if not addresses:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")]
                ]
            )
            await call.answer()
            await call.message.answer(
                "📍 <b>Збережені адреси</b>\n\n"
                "У вас поки немає збережених адрес.\n"
                "Додайте часто використовувані місця для швидкого замовлення!",
                reply_markup=kb
            )
            return
        
        buttons = []
        for addr in addresses:
            buttons.append([InlineKeyboardButton(
                text=f"{addr.emoji} {addr.name}",
                callback_data=f"address:view:{addr.id}"
            )])
        
        buttons.append([InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await call.answer()
        await call.message.answer(
            f"📍 <b>Збережені адреси ({len(addresses)}/10)</b>\n\n"
            "Оберіть адресу для перегляду або додайте нову:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data.startswith("address:view:"))
    async def view_saved_address(call: CallbackQuery) -> None:
        """Переглянути збережену адресу"""
        if not call.from_user:
            return
        
        address_id = int(call.data.split(":")[-1])
        
        from app.storage.db import get_saved_address_by_id
        address = await get_saved_address_by_id(config.database_path, address_id, call.from_user.id)
        
        if not address:
            await call.answer("❌ Адресу не знайдено", show_alert=True)
            return
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📍 Використати звідки", callback_data=f"address:use:pickup:{address_id}"),
                    InlineKeyboardButton(text="📍 Використати куди", callback_data=f"address:use:dest:{address_id}")
                ],
                [InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"address:edit:{address_id}")],
                [InlineKeyboardButton(text="🗑️ Видалити", callback_data=f"address:delete_confirm:{address_id}")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile:saved_addresses")]
            ]
        )
        
        await call.answer()
        await call.message.answer(
            f"{address.emoji} <b>{address.name}</b>\n\n"
            f"📍 Адреса: {address.address}\n"
            f"📅 Додано: {address.created_at.strftime('%d.%m.%Y')}",
            reply_markup=kb
        )
    
    @router.callback_query(F.data.startswith("address:delete_confirm:"))
    async def confirm_delete_address(call: CallbackQuery) -> None:
        """Підтвердження видалення адреси"""
        if not call.from_user:
            return
        
        address_id = int(call.data.split(":")[-1])
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"address:delete_yes:{address_id}"),
                    InlineKeyboardButton(text="❌ Скасувати", callback_data=f"address:view:{address_id}")
                ]
            ]
        )
        
        await call.answer()
        await call.message.answer(
            "❓ <b>Видалити адресу?</b>\n\n"
            "Ви впевнені, що хочете видалити цю адресу?",
            reply_markup=kb
        )
    
    @router.callback_query(F.data.startswith("address:delete_yes:"))
    async def delete_address_confirmed(call: CallbackQuery) -> None:
        """Видалення адреси підтверджено"""
        if not call.from_user:
            return
        
        address_id = int(call.data.split(":")[-1])
        
        from app.storage.db import delete_saved_address
        success = await delete_saved_address(config.database_path, address_id, call.from_user.id)
        
        if success:
            await call.answer("✅ Адресу видалено", show_alert=True)
            # Показати список адрес знову
            await show_saved_addresses(call)
        else:
            await call.answer("❌ Помилка видалення", show_alert=True)
    
    @router.callback_query(F.data == "address:add")
    async def start_add_address(call: CallbackQuery, state: FSMContext) -> None:
        """Початок додавання адреси"""
        if not call.from_user:
            return
        
        await call.answer()
        await state.set_state(SavedAddressStates.name)
        
        await call.message.answer(
            "📍 <b>Додавання нової адреси</b>\n\n"
            "Крок 1/3: Введіть назву адреси\n"
            "Наприклад: Додому, На роботу, Вокзал\n\n"
            "Або натисніть ❌ Скасувати",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="❌ Скасувати")]],
                resize_keyboard=True
            )
        )
    
    @router.message(SavedAddressStates.name)
    async def process_address_name(message: Message, state: FSMContext) -> None:
        """Обробка назви адреси"""
        if not message.from_user or not message.text:
            return
        
        if message.text == "❌ Скасувати":
            await state.clear()
            user = await get_user_by_id(config.database_path, message.from_user.id)
            is_admin = message.from_user.id in config.bot.admin_ids
            from app.storage.db import get_driver_by_tg_user_id
            driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
            is_driver = driver is not None and driver.status == "approved"
            
            await message.answer(
                "❌ Скасовано",
                reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin)
            )
            return
        
        name = message.text.strip()
        if len(name) > 50:
            await message.answer("❌ Назва занадто довга. Максимум 50 символів.")
            return
        
        await state.update_data(name=name)
        await state.set_state(SavedAddressStates.emoji)
        
        # Емодзі на вибір
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🏠", callback_data="emoji:🏠"),
                    InlineKeyboardButton(text="💼", callback_data="emoji:💼"),
                    InlineKeyboardButton(text="🚉", callback_data="emoji:🚉"),
                    InlineKeyboardButton(text="🏪", callback_data="emoji:🏪")
                ],
                [
                    InlineKeyboardButton(text="🏥", callback_data="emoji:🏥"),
                    InlineKeyboardButton(text="🏫", callback_data="emoji:🏫"),
                    InlineKeyboardButton(text="⭐", callback_data="emoji:⭐"),
                    InlineKeyboardButton(text="📍", callback_data="emoji:📍")
                ]
            ]
        )
        
        await message.answer(
            f"✅ Назва: {name}\n\n"
            "Крок 2/3: Оберіть емодзі для адреси:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data.startswith("emoji:"))
    async def process_address_emoji(call: CallbackQuery, state: FSMContext) -> None:
        """Обробка емодзі адреси"""
        if not call.from_user:
            return
        
        emoji = call.data.split(":")[-1]
        await state.update_data(emoji=emoji)
        await state.set_state(SavedAddressStates.address)
        
        await call.answer()
        
        # Кнопка для відправки локації
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Надіслати локацію", request_location=True)],
                [KeyboardButton(text="❌ Скасувати")]
            ],
            resize_keyboard=True
        )
        
        await call.message.answer(
            f"✅ Емодзі: {emoji}\n\n"
            "Крок 3/3: Введіть адресу або надішліть локацію\n\n"
            "Наприклад: вул. Соборна, 15",
            reply_markup=kb
        )
    
    @router.message(SavedAddressStates.address, F.location)
    async def process_address_location(message: Message, state: FSMContext) -> None:
        """Обробка локації для адреси"""
        if not message.from_user or not message.location:
            return
        
        from app.utils.maps import geocode_address
        
        # Спробувати отримати адресу з координат (reverse geocoding)
        # Для спрощення використаємо координати як адресу
        address = f"Координати: {message.location.latitude:.6f}, {message.location.longitude:.6f}"
        
        data = await state.get_data()
        
        from app.storage.db import SavedAddress, save_address
        from datetime import datetime, timezone
        
        saved_addr = SavedAddress(
            id=None,
            user_id=message.from_user.id,
            name=data.get('name', 'Нова адреса'),
            emoji=data.get('emoji', '📍'),
            address=address,
            lat=message.location.latitude,
            lon=message.location.longitude,
            created_at=datetime.now(timezone.utc)
        )
        
        await save_address(config.database_path, saved_addr)
        await state.clear()
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        is_admin = message.from_user.id in config.bot.admin_ids
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        is_driver = driver is not None and driver.status == "approved"
        
        await message.answer(
            f"✅ <b>Адресу збережено!</b>\n\n"
            f"{saved_addr.emoji} {saved_addr.name}\n"
            f"📍 {address}",
            reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin)
        )
    
    @router.message(SavedAddressStates.address, F.text)
    async def process_address_text(message: Message, state: FSMContext) -> None:
        """Обробка текстової адреси"""
        if not message.from_user or not message.text:
            return
        
        if message.text == "❌ Скасувати":
            await state.clear()
            user = await get_user_by_id(config.database_path, message.from_user.id)
            is_admin = message.from_user.id in config.bot.admin_ids
            from app.storage.db import get_driver_by_tg_user_id
            driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
            is_driver = driver is not None and driver.status == "approved"
            
            await message.answer(
                "❌ Скасовано",
                reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin)
            )
            return
        
        address = message.text.strip()
        
        # Спробувати геокодувати адресу
        from app.utils.maps import geocode_address
        lat, lon = None, None
        
        if config.google_maps_api_key:
            result = await geocode_address(address, config.google_maps_api_key)
            if result:
                lat, lon = result
        
        data = await state.get_data()
        
        from app.storage.db import SavedAddress, save_address
        from datetime import datetime, timezone
        
        saved_addr = SavedAddress(
            id=None,
            user_id=message.from_user.id,
            name=data.get('name', 'Нова адреса'),
            emoji=data.get('emoji', '📍'),
            address=address,
            lat=lat,
            lon=lon,
            created_at=datetime.now(timezone.utc)
        )
        
        await save_address(config.database_path, saved_addr)
        await state.clear()
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        is_admin = message.from_user.id in config.bot.admin_ids
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        is_driver = driver is not None and driver.status == "approved"
        
        await message.answer(
            f"✅ <b>Адресу збережено!</b>\n\n"
            f"{saved_addr.emoji} {saved_addr.name}\n"
            f"📍 {address}",
            reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin)
        )
    
    @router.callback_query(F.data == "profile:history")
    async def show_profile_history(call: CallbackQuery) -> None:
        """Показати історію замовлень"""
        if not call.from_user:
            return
        
        from app.storage.db import get_user_order_history
        orders = await get_user_order_history(config.database_path, call.from_user.id, limit=10)
        
        if not orders:
            await call.answer("📜 У вас поки немає замовлень", show_alert=True)
            return
        
        text = "📜 <b>Історія замовлень</b>\n\n"
        
        for order in orders:
            status_emoji = {
                "pending": "⏳",
                "accepted": "✅",
                "in_progress": "🚗",
                "completed": "✅",
                "cancelled": "❌"
            }.get(order.status, "❓")
            
            text += f"{status_emoji} <b>Замовлення #{order.id}</b>\n"
            text += f"📍 {order.pickup_address} → {order.destination_address}\n"
            text += f"📅 {order.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            
            if order.fare_amount:
                text += f"💰 {order.fare_amount:.2f} грн\n"
            
            text += "\n"
        
        await call.answer()
        await call.message.answer(text)
    
    @router.callback_query(F.data == "open_driver_panel")
    async def open_driver_panel(call: CallbackQuery) -> None:
        """Обробник для відкриття панелі водія після підтвердження"""
        if not call.from_user:
            return
        
        await call.answer()
        
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        
        if not driver or driver.status != "approved":
            await call.message.answer("❌ Ви не є підтвердженим водієм.")
            return
        
        from app.storage.db import get_driver_earnings_today, get_driver_unpaid_commission
        
        earnings, commission_owed = await get_driver_earnings_today(config.database_path, call.from_user.id)
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
        
        # Перевірка чи це адмін
        is_admin = call.from_user.id in config.bot.admin_ids
        
        await call.message.answer(
            text,
            reply_markup=main_menu_keyboard(is_registered=True, is_driver=True, is_admin=is_admin)
        )

    # Команди для швидкого переходу
    @router.message(Command("driver"))
    @router.message(F.text == "🚗 Панель водія")
    async def quick_driver_panel(message: Message) -> None:
        """Швидкий перехід до панелі водія"""
        if not message.from_user:
            return
        
        from app.storage.db import get_driver_by_tg_user_id, get_driver_earnings_today
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        
        if not driver:
            await message.answer("❌ Ви не зареєстровані як водій.\n\nНатисніть 🚗 Стати водієм для реєстрації.")
            return
        
        if driver.status != "approved":
            await message.answer(
                "⏳ Вашу заявку на роль водія ще не схвалено.\n\n"
                "Очікуйте на підтвердження від адміністратора."
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
        
        # Перевірка чи адмін
        is_admin = message.from_user.id in config.bot.admin_ids
        
        await message.answer(
            text,
            reply_markup=main_menu_keyboard(is_registered=True, is_driver=True, is_admin=is_admin)
        )
    
    @router.message(Command("client"))
    @router.message(F.text == "👤 Кабінет клієнта")
    async def quick_client_panel(message: Message) -> None:
        """Швидкий перехід до кабінету клієнта"""
        if not message.from_user:
            return
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        if not user or not user.phone or not user.city:
            await message.answer("❌ Завершіть реєстрацію для доступу до кабінету клієнта.\n\nНатисніть 📱 Зареєструватись")
            return
        
        # Перевірка чи адмін
        is_admin = message.from_user.id in config.bot.admin_ids
        
        # Перевірка чи водій
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        is_driver = driver is not None and driver.status == "approved"
        
        await message.answer(
            f"👤 <b>Кабінет клієнта</b>\n\n"
            f"Вітаємо, {user.full_name}!\n\n"
            f"📍 Місто: {user.city}\n"
            f"📱 Телефон: {user.phone}\n\n"
            "Оберіть дію з меню нижче:",
            reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin)
        )
    
    @router.message(F.text == "❌ Скасувати")
    async def cancel(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        is_registered = user is not None and user.phone and user.city
        
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        is_driver = driver is not None and driver.status == "approved"
        
        await state.clear()
        # Перевірка чи це адмін
        is_admin = message.from_user.id in config.bot.admin_ids if message.from_user else False
        
        await message.answer(
            "❌ Скасовано.",
            reply_markup=main_menu_keyboard(is_registered=is_registered, is_driver=is_driver, is_admin=is_admin)
        )

    return router
