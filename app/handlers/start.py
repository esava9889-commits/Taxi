from __future__ import annotations

import re
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.config.config import AppConfig
from app.storage.db import User, upsert_user, get_user_by_id


ORDER_TEXT = "Замовити таксі"
REGISTER_TEXT = "Зареєструватися"
DRIVER_TEXT = "Стати водієм"
HELP_TEXT = "Допомога"
CANCEL_TEXT = "Скасувати"


def main_menu_keyboard(is_registered: bool = False) -> ReplyKeyboardMarkup:
    if is_registered:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=ORDER_TEXT)],
                [KeyboardButton(text=DRIVER_TEXT), KeyboardButton(text=HELP_TEXT)],
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Оберіть дію",
        )
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ORDER_TEXT), KeyboardButton(text=REGISTER_TEXT)],
            [KeyboardButton(text=DRIVER_TEXT), KeyboardButton(text=HELP_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Оберіть дію",
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def contact_or_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Поділитися контактом", request_contact=True)],
            [KeyboardButton(text=CANCEL_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Надішліть контакт або введіть номер",
    )


def is_valid_phone(text: str) -> bool:
    return bool(re.fullmatch(r"[+]?[\d\s\-()]{7,18}", text.strip()))


class ClientRegStates(StatesGroup):
    phone = State()


def create_router(config: AppConfig) -> Router:
    router = Router(name="start")

    @router.message(CommandStart())
    async def on_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        
        if not message.from_user:
            return
        
        # Перевірка чи користувач вже зареєстрований
        user = await get_user_by_id(config.database_path, message.from_user.id)
        
        if user:
            # Користувач вже зареєстрований
            await message.answer(
                f"З поверненням, {user.full_name}! 👋\n\n"
                "Оберіть дію з меню нижче:",
                reply_markup=main_menu_keyboard(is_registered=True)
            )
        else:
            # Новий користувач - автоматично створюємо базовий профіль
            new_user = User(
                user_id=message.from_user.id,
                full_name=message.from_user.full_name or "Користувач",
                phone="",  # Буде заповнено при реєстрації
                role="client",
                created_at=datetime.now(timezone.utc),
            )
            await upsert_user(config.database_path, new_user)
            
            # Пропонуємо завершити реєстрацію
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📱 Завершити реєстрацію", callback_data="register:complete")],
                    [InlineKeyboardButton(text="ℹ️ Довідка", callback_data="help:show")],
                ]
            )
            
            await message.answer(
                f"Вітаємо у таксі-боті, {message.from_user.full_name}! 🚖\n\n"
                "Ми автоматично створили ваш профіль.\n"
                "Для замовлення таксі потрібно завершити реєстрацію та надати номер телефону.",
                reply_markup=kb
            )

    @router.callback_query(F.data == "register:complete")
    async def complete_registration_inline(call, state: FSMContext) -> None:
        await call.answer()
        await state.set_state(ClientRegStates.phone)
        await call.message.answer(
            "📱 Надішліть ваш номер телефону або поділіться контактом.",
            reply_markup=contact_or_cancel_keyboard(),
        )
    
    @router.callback_query(F.data == "help:show")
    async def show_help_inline(call) -> None:
        await call.answer()
        help_text = (
            "ℹ️ <b>Довідка</b>\n\n"
            "🚖 <b>Замовити таксі</b> — оформити поїздку\n"
            "📱 <b>Завершити реєстрацію</b> — додати номер телефону\n"
            "🚗 <b>Стати водієм</b> — подати заявку водія\n\n"
            "Для замовлення таксі потрібно завершити реєстрацію."
        )
        await call.message.answer(help_text, reply_markup=main_menu_keyboard())
    
    @router.message(F.text == HELP_TEXT)
    async def on_help(message: Message) -> None:
        if not message.from_user:
            return
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        is_registered = user is not None and user.phone
        
        help_text = (
            "ℹ️ <b>Довідка</b>\n\n"
            "🚖 <b>Замовити таксі</b> — оформити поїздку\n"
            "📱 <b>Зареєструватися</b> — додати номер телефону\n"
            "🚗 <b>Стати водієм</b> — подати заявку водія\n\n"
        )
        
        if not is_registered:
            help_text += "⚠️ Для замовлення таксі потрібно завершити реєстрацію."
        
        await message.answer(help_text, reply_markup=main_menu_keyboard(is_registered))

    @router.message(F.text == REGISTER_TEXT)
    async def start_client_registration(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        
        # Перевірка чи вже зареєстрований
        user = await get_user_by_id(config.database_path, message.from_user.id)
        if user and user.phone:
            await message.answer(
                "✅ Ви вже зареєстровані!\n\n"
                f"Ім'я: {user.full_name}\n"
                f"Телефон: {user.phone}",
                reply_markup=main_menu_keyboard(is_registered=True)
            )
            return
        
        await state.set_state(ClientRegStates.phone)
        await message.answer(
            "📱 Надішліть ваш номер телефону або поділіться контактом.",
            reply_markup=contact_or_cancel_keyboard(),
        )

    @router.message(F.text == CANCEL_TEXT)
    async def cancel(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        is_registered = user is not None and user.phone
        
        await state.clear()
        await message.answer("Скасовано.", reply_markup=main_menu_keyboard(is_registered))

    @router.message(ClientRegStates.phone, F.contact)
    async def take_phone_from_contact(message: Message, state: FSMContext) -> None:
        contact = message.contact
        phone = contact.phone_number
        full_name = message.from_user.full_name if message.from_user else ""
        user = User(
            user_id=message.from_user.id if message.from_user else 0,
            full_name=full_name,
            phone=phone,
            role="client",
            created_at=datetime.now(timezone.utc),
        )
        await upsert_user(config.database_path, user)
        await state.clear()
        await message.answer(
            "Реєстрацію успішно завершено!", reply_markup=main_menu_keyboard()
        )

    @router.message(ClientRegStates.phone)
    async def take_phone_text(message: Message, state: FSMContext) -> None:
        phone = message.text.strip()
        if not is_valid_phone(phone):
            await message.answer("Введіть коректний номер, напр.: +380 67 123 45 67")
            return
        full_name = message.from_user.full_name if message.from_user else ""
        user = User(
            user_id=message.from_user.id if message.from_user else 0,
            full_name=full_name,
            phone=phone,
            role="client",
            created_at=datetime.now(timezone.utc),
        )
        await upsert_user(config.database_path, user)
        await state.clear()
        await message.answer(
            "✅ Реєстрацію успішно завершено!\n\n"
            "Тепер ви можете замовити таксі 🚖", 
            reply_markup=main_menu_keyboard(is_registered=True)
        )

    return router
