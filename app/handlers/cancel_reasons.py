"""Обробник причин скасування замовлення"""
from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.config.config import AppConfig
from app.storage.db import (
    get_order_by_id,
    cancel_order_by_client,
    get_user_by_id,
)

logger = logging.getLogger(__name__)


CANCEL_REASONS = {
    "wait_long": "⏰ Водій довго їде",
    "wrong_address": "📍 Помилка в адресі",
    "changed_mind": "🤷 Передумав",
    "found_other": "🚕 Знайшов інше таксі",
    "high_price": "💸 Занадто дорого",
    "other": "❓ Інше"
}


def create_router(config: AppConfig) -> Router:
    router = Router(name="cancel_reasons")

    @router.callback_query(F.data.startswith("cancel_with_reason:"))
    async def ask_cancel_reason(call: CallbackQuery) -> None:
        """Запитати причину скасування"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":", 1)[1])
        
        # Перевірка що замовлення належить клієнту
        order = await get_order_by_id(config.database_path, order_id)
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        if order.status != "pending":
            await call.answer("❌ Замовлення вже прийнято водієм, скасувати неможливо", show_alert=True)
            return
        
        # Показати причини
        buttons = []
        for reason_code, reason_text in CANCEL_REASONS.items():
            buttons.append([
                InlineKeyboardButton(
                    text=reason_text,
                    callback_data=f"confirm_cancel:{order_id}:{reason_code}"
                )
            ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await call.answer()
        await call.message.answer(
            "❌ <b>Чому ви скасовуєте замовлення?</b>\n\n"
            "Це допоможе нам покращити сервіс!",
            reply_markup=kb
        )

    @router.callback_query(F.data.startswith("confirm_cancel:"))
    async def confirm_cancel_with_reason(call: CallbackQuery) -> None:
        """Підтвердити скасування з причиною"""
        if not call.from_user:
            return
        
        parts = call.data.split(":", 2)
        order_id = int(parts[1])
        reason_code = parts[2]
        reason_text = CANCEL_REASONS.get(reason_code, "Інше")
        
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
            
            await call.answer("✅ Замовлення скасовано")
            
            # Логування причини
            logger.info(f"Order #{order_id} cancelled by client {call.from_user.id}. Reason: {reason_text}")
            
            # Оновити повідомлення
            await call.message.edit_text(
                f"❌ <b>Замовлення #{order_id} скасовано</b>\n\n"
                f"Причина: {reason_text}\n\n"
                "Дякуємо за зворотний зв'язок!"
            )
            
            # Повідомити в групу водіїв (групу міста клієнта)
            order = await get_order_by_id(config.database_path, order_id)
            if order and order.group_message_id:
                try:
                    from app.config.config import get_city_group_id
                    
                    user = await get_user_by_id(config.database_path, order.user_id)
                    client_city = user.city if user and user.city else None
                    group_id = get_city_group_id(config, client_city)
                    
                    logger.info(f"🔔 Скасування з причиною #{order_id}: group_id={group_id}, city={client_city}, msg_id={order.group_message_id}, reason={reason_text}")
                    
                    if group_id:
                        await call.bot.edit_message_text(
                            f"❌ <b>ЗАМОВЛЕННЯ #{order_id} СКАСОВАНО КЛІЄНТОМ</b>\n\n"
                            f"Причина: {reason_text}",
                            chat_id=group_id,
                            message_id=order.group_message_id
                        )
                        logger.info(f"✅ Скасування #{order_id} з причиною надіслано в групу")
                    else:
                        logger.warning(f"⚠️ Група для міста '{client_city}' не знайдена")
                except Exception as e:
                    # Якщо повідомлення вже видалене - це не помилка
                    if "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
                        logger.info(f"ℹ️ Повідомлення #{order.group_message_id} вже видалене (замовлення #{order_id})")
                    else:
                        logger.error(f"❌ Помилка оновлення групи: {e}")
        else:
            await call.answer("❌ Не вдалося скасувати замовлення", show_alert=True)

    return router
