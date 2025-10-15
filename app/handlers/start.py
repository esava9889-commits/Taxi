from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import CommandStart
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


def main_menu_keyboard(is_registered: bool = False, is_driver: bool = False) -> ReplyKeyboardMarkup:
    """Головне меню з кнопками"""
    if is_driver:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚗 Панель водія")],
                [KeyboardButton(text="📊 Мій заробіток"), KeyboardButton(text="💳 Комісія")],
                [KeyboardButton(text="📜 Історія поїздок")],
                [KeyboardButton(text="ℹ️ Допомога")],
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Оберіть дію",
        )
    
    if is_registered:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚖 Замовити таксі")],
                [KeyboardButton(text="📜 Мої замовлення"), KeyboardButton(text="👤 Мій профіль")],
                [KeyboardButton(text="🚗 Стати водієм"), KeyboardButton(text="ℹ️ Допомога")],
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
        
        # Перевірка чи це водій
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        is_driver = driver is not None and driver.status == "approved"
        
        if user and user.phone and user.city:
            # Повна реєстрація
            await message.answer(
                f"З поверненням, {user.full_name}! 👋\n\n"
                f"📍 Місто: {user.city}\n"
                f"📱 Телефон: {user.phone}\n\n"
                "Оберіть дію з меню нижче:",
                reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver)
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
            text = f"✅ Ви вже зареєстровані!\n\n📍 Місто: {user.city}\n📱 Телефон: {user.phone}"
            if isinstance(event, CallbackQuery):
                await event.answer("Ви вже зареєстровані!")
                await event.message.answer(text, reply_markup=main_menu_keyboard(is_registered=True))
            else:
                await event.answer(text, reply_markup=main_menu_keyboard(is_registered=True))
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
        
        await message.answer(
            f"✅ <b>Реєстрація завершена!</b>\n\n"
            f"👤 {user.full_name}\n"
            f"📍 {city}\n"
            f"📱 {phone}\n\n"
            "Тепер ви можете замовити таксі! 🚖",
            reply_markup=main_menu_keyboard(is_registered=True)
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
        
        await message.answer(
            f"✅ <b>Реєстрація завершена!</b>\n\n"
            f"👤 {user.full_name}\n"
            f"📍 {city}\n"
            f"📱 {phone}\n\n"
            "Тепер ви можете замовити таксі! 🚖",
            reply_markup=main_menu_keyboard(is_registered=True)
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
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Змінити місто", callback_data="profile:edit:city")],
                [InlineKeyboardButton(text="📱 Змінити телефон", callback_data="profile:edit:phone")],
            ]
        )
        
        await message.answer(
            f"👤 <b>Ваш профіль</b>\n\n"
            f"Ім'я: {user.full_name}\n"
            f"📍 Місто: {user.city or 'Не вказано'}\n"
            f"📱 Телефон: {user.phone or 'Не вказано'}\n"
            f"📅 Дата реєстрації: {user.created_at.strftime('%d.%m.%Y')}",
            reply_markup=kb
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
        await message.answer(
            "❌ Скасовано.",
            reply_markup=main_menu_keyboard(is_registered=is_registered, is_driver=is_driver)
        )

    return router
