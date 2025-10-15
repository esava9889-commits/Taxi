from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.config.config import AppConfig
from app.storage.db import (
    get_user_by_id,
    get_user_order_history,
)


def client_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚖 Замовити таксі"), KeyboardButton(text="📜 Моя історія")],
            [KeyboardButton(text="ℹ️ Допомога"), KeyboardButton(text="⭐️ Мій рейтинг")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Меню клієнта",
    )


def create_router(config: AppConfig) -> Router:
    router = Router(name="client")

    @router.message(Command("client"))
    async def client_panel(message: Message) -> None:
        if not message.from_user:
            return
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        
        if user:
            text = (
                f"👤 <b>Профіль клієнта</b>\n\n"
                f"Ім'я: {user.full_name}\n"
                f"Телефон: {user.phone}\n"
                f"Зареєстровано: {user.created_at.strftime('%Y-%m-%d')}"
            )
        else:
            text = (
                "👤 <b>Меню клієнта</b>\n\n"
                "Для повного доступу до функцій зареєструйтесь:\n"
                "/start → 'Зареєструватися'"
            )
        
        await message.answer(text, reply_markup=client_menu_keyboard())

    # Обробник "🚖 Замовити таксі" видалено - його обробляє order.py
    # Це виправляє конфлікт роутерів

    @router.message(F.text == "📜 Моя історія")
    async def show_client_history(message: Message) -> None:
        if not message.from_user:
            return
        
        orders = await get_user_order_history(config.database_path, message.from_user.id, limit=10)
        
        if not orders:
            await message.answer(
                "📜 У вас поки немає замовлень.\n\n"
                "Натисніть '🚖 Замовити таксі' або використайте /order",
                reply_markup=client_menu_keyboard()
            )
            return
        
        text = "📜 <b>Ваша історія замовлень:</b>\n\n"
        for o in orders:
            status_emoji = {
                "pending": "⏳ Очікується",
                "offered": "📤 Пропозиція водію",
                "accepted": "✅ Прийнято",
                "in_progress": "🚗 В дорозі",
                "completed": "✔️ Завершено",
                "cancelled": "❌ Скасовано"
            }.get(o.status, "❓ Невідомо")
            
            text += f"<b>Замовлення №{o.id}</b>\n"
            text += f"Статус: {status_emoji}\n"
            text += f"📍 {o.pickup_address[:30]}...\n"
            text += f"📍 {o.destination_address[:30]}...\n"
            
            if o.fare_amount:
                text += f"💰 Вартість: {o.fare_amount:.2f} грн\n"
            
            text += f"📅 {o.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        await message.answer(text, reply_markup=client_menu_keyboard())

    @router.message(F.text == "ℹ️ Допомога")
    async def show_help(message: Message) -> None:
        text = (
            "ℹ️ <b>Допомога</b>\n\n"
            "<b>Як замовити таксі:</b>\n"
            "1. Натисніть '🚖 Замовити таксі' або /order\n"
            "2. Введіть ваші дані\n"
            "3. Надішліть геолокацію або вкажіть адресу\n"
            "4. Підтвердіть замовлення\n"
            "5. Очікуйте водія!\n\n"
            "<b>Команди:</b>\n"
            "/start - Головне меню\n"
            "/order - Замовити таксі\n"
            "/client - Меню клієнта\n"
            "/my_rating - Переглянути ваш рейтинг\n\n"
            "<b>Підтримка:</b>\n"
            "З питань пишіть адміністратору"
        )
        await message.answer(text, reply_markup=client_menu_keyboard())

    return router
