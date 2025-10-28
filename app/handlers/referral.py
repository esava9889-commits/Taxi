"""Реферальна програма"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config.config import AppConfig
from app.storage.db import (
    get_user_by_id,
    get_user_referral_stats,
    create_referral_code,
    get_referral_code,
    apply_referral_code,
)

logger = logging.getLogger(__name__)


def generate_referral_code(user_id: int) -> str:
    """Згенерувати реферальний код"""
    hash_str = hashlib.md5(f"taxi_{user_id}_{datetime.now().timestamp()}".encode()).hexdigest()
    return f"TAXI{hash_str[:6].upper()}"


def create_router(config: AppConfig) -> Router:
    router = Router(name="referral")

    @router.message(F.text == "🎁 Реферальна програма")
    @router.callback_query(F.data == "referral:show")
    async def show_referral_program(event) -> None:
        """Показати реферальну програму"""
        # Визначити тип події (message або callback)
        if isinstance(event, Message):
            message = event
            user_id = event.from_user.id if event.from_user else 0
        else:  # CallbackQuery
            message = event.message
            user_id = event.from_user.id if event.from_user else 0
            await event.answer()
        
        if not user_id:
            return
        
        # Перевірка реєстрації
        user = await get_user_by_id(config.database_path, user_id)
        if not user:
            await message.answer("❌ Спочатку зареєструйтесь!")
            return
        
        # Отримати або створити реферальний код
        ref_code = await get_referral_code(config.database_path, user_id)
        if not ref_code:
            ref_code = generate_referral_code(user_id)
            await create_referral_code(config.database_path, user_id, ref_code)
        
        # Статистика
        stats = await get_user_referral_stats(config.database_path, user_id)
        referred_count = stats.get('referred_count', 0)
        total_bonus = stats.get('total_bonus', 0)
        
        # Реферальне посилання
        bot_username = (await message.bot.me()).username
        referral_link = f"https://t.me/{bot_username}?start={ref_code}"
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📤 Поділитися", switch_inline_query=f"Замовляй таксі зі знижкою! {referral_link}")],
                [InlineKeyboardButton(text="🔄 Оновити статистику", callback_data="referral:show")]
            ]
        )
        
        text = (
            "🎁 <b>Реферальна програма</b>\n\n"
            f"Ваш код: <code>{ref_code}</code>\n"
            f"Посилання: {referral_link}\n\n"
            "💰 <b>Як це працює?</b>\n"
            "1️⃣ Поділіться посиланням з другом\n"
            "2️⃣ Друг реєструється і робить першу поїздку\n"
            "3️⃣ Він отримує <b>-50 грн</b> на першу поїздку\n"
            "4️⃣ Ви отримуєте <b>-30 грн</b> на наступну поїздку\n\n"
            f"📊 <b>Ваша статистика:</b>\n"
            f"👥 Запрошено друзів: {referred_count}\n"
            f"💵 Отримано бонусів: {total_bonus:.0f} грн\n\n"
            "🎉 <i>Немає ліміту на кількість запрошень!</i>"
        )
        
        await message.answer(text, reply_markup=kb, disable_web_page_preview=True)

    @router.message(F.text.startswith("/start "))
    async def handle_referral_start(message: Message) -> None:
        """Обробити реферальний код при старті"""
        if not message.from_user or not message.text:
            return
        
        ref_code = message.text.split(" ", 1)[1].strip()
        
        # Перевірити чи це реферальний код
        if ref_code.startswith("TAXI"):
            # Перевірка чи користувач новий
            user = await get_user_by_id(config.database_path, message.from_user.id)
            if user:
                await message.answer(
                    "ℹ️ Ви вже зареєстровані!\n"
                    "Реферальний код можна застосувати тільки при першій реєстрації."
                )
                return
            
            # Застосувати реферальний код
            success = await apply_referral_code(config.database_path, message.from_user.id, ref_code)
            
            if success:
                await message.answer(
                    "🎉 <b>Вітаємо!</b>\n\n"
                    "Ви зареєструвались по реферальному посиланню!\n"
                    "💰 Ви отримали <b>-50 грн</b> на першу поїздку!\n\n"
                    "Завершіть реєстрацію щоб почати користуватись 👇"
                )
            else:
                await message.answer(
                    "⚠️ Реферальний код недійсний або застарілий.\n"
                    "Продовжуйте реєстрацію звичайним способом."
                )

    return router
