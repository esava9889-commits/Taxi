"""Чат між клієнтом та водієм"""
from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config.config import AppConfig
from app.storage.db import (
    get_order_by_id,
    get_driver_by_id,
    get_driver_by_tg_user_id,
)

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="chat")

    class ChatStates(StatesGroup):
        messaging = State()

    @router.callback_query(F.data.startswith("chat:start:"))
    async def start_chat(call: CallbackQuery, state: FSMContext) -> None:
        """Почати чат"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":", 2)[2])
        
        order = await get_order_by_id(config.database_path, order_id)
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        # Перевірити що користувач - клієнт або водій цього замовлення
        is_client = order.user_id == call.from_user.id
        is_driver = False
        
        if order.driver_id:
            driver = await get_driver_by_id(config.database_path, order.driver_id)
            is_driver = driver and driver.tg_user_id == call.from_user.id
        
        if not is_client and not is_driver:
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        # Чат доступний тільки під час активного замовлення
        if order.status not in ["accepted", "in_progress"]:
            await call.answer("❌ Чат доступний тільки під час активного замовлення", show_alert=True)
            return
        
        await call.answer()
        
        # Зберегти дані для чату
        if is_client and order.driver_id:
            driver = await get_driver_by_id(config.database_path, order.driver_id)
            if driver:
                await state.update_data(
                    order_id=order_id,
                    chat_with_id=driver.tg_user_id,
                    chat_with_name=driver.full_name,
                    chat_role="driver"
                )
        else:
            await state.update_data(
                order_id=order_id,
                chat_with_id=order.user_id,
                chat_with_name=order.name,
                chat_role="client"
            )
        
        await state.set_state(ChatStates.messaging)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Завершити чат", callback_data="chat:end")]
            ]
        )
        
        data = await state.get_data()
        await call.message.answer(
            f"💬 <b>Чат з {data['chat_with_name']}</b>\n\n"
            "Надішліть повідомлення (текст, фото, локація):",
            reply_markup=kb
        )

    @router.message(ChatStates.messaging)
    async def forward_message(message: Message, state: FSMContext) -> None:
        """Переслати повідомлення"""
        if not message.from_user:
            return
        
        data = await state.get_data()
        chat_with_id = data.get("chat_with_id")
        chat_with_name = data.get("chat_with_name")
        chat_role = data.get("chat_role")
        
        if not chat_with_id:
            await message.answer("❌ Помилка чату")
            await state.clear()
            return
        
        # Визначити хто відправник
        sender_name = "Клієнт" if chat_role == "driver" else "Водій"
        
        try:
            # Переслати повідомлення
            if message.text:
                await message.bot.send_message(
                    chat_with_id,
                    f"💬 <b>Повідомлення від {sender_name}:</b>\n\n{message.text}"
                )
            elif message.photo:
                await message.bot.send_photo(
                    chat_with_id,
                    message.photo[-1].file_id,
                    caption=f"📸 Фото від {sender_name}" + (f"\n\n{message.caption}" if message.caption else "")
                )
            elif message.location:
                await message.bot.send_location(
                    chat_with_id,
                    message.location.latitude,
                    message.location.longitude
                )
                await message.bot.send_message(
                    chat_with_id,
                    f"📍 Локація від {sender_name}"
                )
            elif message.voice:
                await message.bot.send_voice(
                    chat_with_id,
                    message.voice.file_id,
                    caption=f"🎤 Голосове від {sender_name}"
                )
            else:
                await message.answer("❌ Цей тип повідомлень не підтримується")
                return
            
            await message.answer("✅ Повідомлення надіслано")
            
        except Exception as e:
            logger.error(f"Failed to forward message: {e}")
            await message.answer("❌ Не вдалося надіслати повідомлення")

    @router.callback_query(F.data == "chat:end")
    async def end_chat(call: CallbackQuery, state: FSMContext) -> None:
        """Завершити чат"""
        await call.answer("Чат завершено")
        await state.clear()
        await call.message.edit_text("💬 Чат завершено")

    return router
