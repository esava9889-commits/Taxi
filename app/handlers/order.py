from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (KeyboardButton, Message, ReplyKeyboardMarkup,
                           ReplyKeyboardRemove)

from app.config.config import AppConfig
from app.storage.db import Order, insert_order, fetch_recent_orders


def create_router(config: AppConfig) -> Router:
    router = Router(name="order")

    CANCEL_TEXT = "Скасувати"
    SKIP_TEXT = "Пропустити"
    CONFIRM_TEXT = "Підтвердити"

    class OrderStates(StatesGroup):
        name = State()
        phone = State()
        pickup = State()
        destination = State()
        comment = State()
        confirm = State()

    def cancel_keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=CANCEL_TEXT)]],
            resize_keyboard=True,
            one_time_keyboard=True,
            input_field_placeholder="Ви можете скасувати замовлення",
        )

    def skip_or_cancel_keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=SKIP_TEXT)], [KeyboardButton(text=CANCEL_TEXT)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    def confirm_keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=CONFIRM_TEXT)], [KeyboardButton(text=CANCEL_TEXT)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    def is_valid_phone(text: str) -> bool:
        return bool(re.fullmatch(r"[+]?[\d\s\-()]{7,18}", text.strip()))

    @router.message(CommandStart())
    async def on_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(
            "Вітаємо у таксі-боті! Натисніть /order, щоб оформити замовлення."
        )

    @router.message(Command("order"))
    async def start_order(message: Message, state: FSMContext) -> None:
        await state.set_state(OrderStates.name)
        await message.answer(
            "Як до вас звертатися?", reply_markup=cancel_keyboard()
        )

    @router.message(F.text == CANCEL_TEXT)
    async def cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Замовлення скасовано.", reply_markup=ReplyKeyboardRemove())

    @router.message(OrderStates.name)
    async def ask_phone(message: Message, state: FSMContext) -> None:
        full_name = message.text.strip()
        if not full_name:
            await message.answer("Будь ласка, введіть ім'я.")
            return
        await state.update_data(name=full_name)
        await state.set_state(OrderStates.phone)
        await message.answer(
            "Ваш номер телефону?", reply_markup=cancel_keyboard()
        )

    @router.message(OrderStates.phone)
    async def ask_pickup(message: Message, state: FSMContext) -> None:
        phone = message.text.strip()
        if not is_valid_phone(phone):
            await message.answer("Введіть коректний номер, напр.: +380 67 123 45 67")
            return
        await state.update_data(phone=phone)
        await state.set_state(OrderStates.pickup)
        await message.answer(
            "Адреса подачі авто?", reply_markup=cancel_keyboard()
        )

    @router.message(OrderStates.pickup)
    async def ask_destination(message: Message, state: FSMContext) -> None:
        pickup = message.text.strip()
        if len(pickup) < 3:
            await message.answer("Будь ласка, уточніть адресу подачі.")
            return
        await state.update_data(pickup=pickup)
        await state.set_state(OrderStates.destination)
        await message.answer(
            "Куди їдемо? Вкажіть адресу призначення.", reply_markup=cancel_keyboard()
        )

    @router.message(OrderStates.destination)
    async def ask_comment(message: Message, state: FSMContext) -> None:
        destination = message.text.strip()
        if len(destination) < 3:
            await message.answer("Будь ласка, уточніть адресу призначення.")
            return
        await state.update_data(destination=destination)
        await state.set_state(OrderStates.comment)
        await message.answer(
            "Коментар до замовлення? (наприклад, під'їзд/поверх)\n"
            "Можете натиснути 'Пропустити'.",
            reply_markup=skip_or_cancel_keyboard(),
        )

    @router.message(OrderStates.comment, F.text == SKIP_TEXT)
    async def skip_comment(message: Message, state: FSMContext) -> None:
        await state.update_data(comment=None)
        await show_confirmation(message, state)

    @router.message(OrderStates.comment)
    async def take_comment(message: Message, state: FSMContext) -> None:
        comment = message.text.strip()
        await state.update_data(comment=comment)
        await show_confirmation(message, state)

    async def show_confirmation(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        text = (
            "Будь ласка, підтвердіть замовлення:\n\n"
            f"Ім'я: {data.get('name')}\n"
            f"Телефон: {data.get('phone')}\n"
            f"Звідки: {data.get('pickup')}\n"
            f"Куди: {data.get('destination')}\n"
            f"Коментар: {data.get('comment') or '—'}\n"
        )
        await state.set_state(OrderStates.confirm)
        await message.answer(text, reply_markup=confirm_keyboard())

    @router.message(OrderStates.confirm, F.text == CONFIRM_TEXT)
    async def confirm_order(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = Order(
            id=None,
            user_id=message.from_user.id if message.from_user else 0,
            name=str(data.get("name")),
            phone=str(data.get("phone")),
            pickup_address=str(data.get("pickup")),
            destination_address=str(data.get("destination")),
            comment=(None if data.get("comment") in (None, "") else str(data.get("comment"))),
            created_at=datetime.utcnow(),
        )
        order_id = await insert_order(config.database_path, order)
        await state.clear()
        await message.answer(
            f"Дякуємо! Ваше замовлення №{order_id} прийнято.",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.message(OrderStates.confirm)
    async def confirm_unknown(message: Message, state: FSMContext) -> None:
        await message.answer("Будь ласка, натисніть 'Підтвердити' або 'Скасувати'.")

    @router.message(Command("orders"))
    async def list_recent_orders(message: Message) -> None:
        if not message.from_user or message.from_user.id not in set(config.bot.admin_ids):
            return
        orders = await fetch_recent_orders(config.database_path, limit=5)
        if not orders:
            await message.answer("Замовлень поки немає.")
            return
        lines = []
        for o in orders:
            lines.append(
                "\n".join([
                    f"№{o.id} від {o.created_at.strftime('%Y-%m-%d %H:%M')}",
                    f"Клієнт: {o.name} ({o.phone})",
                    f"Маршрут: {o.pickup_address} → {o.destination_address}",
                    f"Коментар: {o.comment or '—'}",
                ])
            )
        await message.answer("\n\n".join(lines))

    return router
