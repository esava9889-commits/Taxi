"""SOS кнопка для безпеки"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.config.config import AppConfig
from app.storage.db import get_user_active_order, get_driver_by_id

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="sos")

    @router.message(F.text == "🆘 SOS")
    async def sos_button(message: Message) -> None:
        """Кнопка SOS"""
        if not message.from_user:
            return
        
        # Отримати активне замовлення
        order = await get_user_active_order(config.database_path, message.from_user.id)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🚨 Підтвердити SOS", callback_data="sos:confirm"),
                    InlineKeyboardButton(text="❌ Скасувати", callback_data="sos:cancel")
                ]
            ]
        )
        
        await message.answer(
            "🆘 <b>SOS Тривога</b>\n\n"
            "Це екстрена кнопка допомоги!\n\n"
            "При підтвердженні:\n"
            "• Адміністратор отримає сповіщення\n"
            "• Буде надіслана ваша локація\n"
            "• Інформація про поїздку\n\n"
            "Використовуйте тільки в екстрених випадках!",
            reply_markup=kb
        )

    @router.callback_query(F.data == "sos:confirm")
    async def sos_confirm(call: CallbackQuery) -> None:
        """Підтвердити SOS"""
        if not call.from_user:
            return
        
        await call.answer()
        
        # Отримати активне замовлення
        order = await get_user_active_order(config.database_path, call.from_user.id)
        
        # Повідомлення для адміна
        admin_message = (
            "🚨 <b>SOS ТРИВОГА!</b> 🚨\n\n"
            f"Від: {call.from_user.full_name or 'Користувач'}\n"
            f"ID: <code>{call.from_user.id}</code>\n"
            f"Username: @{call.from_user.username or 'немає'}\n"
            f"Час: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
        )
        
        if order:
            admin_message += (
                f"📋 <b>Замовлення #{order.id}</b>\n"
                f"Статус: {order.status}\n"
                f"📍 Звідки: {order.pickup_address}\n"
                f"📍 Куди: {order.destination_address}\n\n"
            )
            
            if order.driver_id:
                driver = await get_driver_by_id(config.database_path, order.driver_id)
                if driver:
                    admin_message += (
                        f"🚗 <b>Водій:</b>\n"
                        f"ПІБ: {driver.full_name}\n"
                        f"Телефон: {driver.phone}\n"
                        f"Авто: {driver.car_make} {driver.car_model} ({driver.car_plate})\n\n"
                    )
        else:
            admin_message += "⚠️ Немає активного замовлення\n\n"
        
        admin_message += "❗️ ТЕРМІНОВО ЗВЕРНІТЬСЯ ДО КОРИСТУВАЧА!"
        
        # Надіслати адміну
        for admin_id in config.bot.admin_ids:
            try:
                await call.bot.send_message(admin_id, admin_message)
                logger.critical(f"SOS ALERT from user {call.from_user.id}")
            except Exception as e:
                logger.error(f"Failed to send SOS to admin {admin_id}: {e}")
        
        # Повідомити користувача
        await call.message.edit_text(
            "✅ <b>SOS сигнал надіслано!</b>\n\n"
            "Адміністратор отримав повідомлення.\n"
            "Ми з вами зв'яжемось найближчим часом.\n\n"
            "📞 Якщо небезпека - дзвоніть 102!"
        )

    @router.callback_query(F.data == "sos:cancel")
    async def sos_cancel(call: CallbackQuery) -> None:
        """Скасувати SOS"""
        await call.answer()
        await call.message.edit_text("❌ SOS скасовано")

    return router
