from __future__ import annotations

import re
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.config.config import AppConfig
from app.storage.db import User, upsert_user


ORDER_TEXT = "Замовити таксі"
REGISTER_TEXT = "Зареєструватися"
DRIVER_TEXT = "Стати водієм"
HELP_TEXT = "Допомога"
CANCEL_TEXT = "Скасувати"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
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
        await message.answer(
            "Вітаємо у таксі-боті! Ось головне меню.", reply_markup=main_menu_keyboard()
        )

    @router.message(F.text == HELP_TEXT)
    async def on_help(message: Message) -> None:
        await message.answer(
            "Натисніть 'Замовити таксі' щоб оформити поїздку.\n"
            "'Зареєструватися' — створити профіль клієнта.\n"
            "'Стати водієм' — подати заявку водія.",
            reply_markup=main_menu_keyboard(),
        )

    @router.message(F.text == REGISTER_TEXT)
    async def start_client_registration(message: Message, state: FSMContext) -> None:
        await state.set_state(ClientRegStates.phone)
        await message.answer(
            "Надішліть ваш номер телефону або поділіться контактом.",
            reply_markup=contact_or_cancel_keyboard(),
        )

    @router.message(F.text == CANCEL_TEXT)
    async def cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Скасовано.", reply_markup=main_menu_keyboard())

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
            "Реєстрацію успішно завершено!", reply_markup=main_menu_keyboard()
        )

    return router
