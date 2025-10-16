"""Push-сповіщення для клієнтів та водіїв"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


async def notify_client_driver_accepted(
    bot: Bot,
    client_id: int,
    order_id: int,
    driver_name: str,
    car_info: str,
    car_plate: str,
    driver_phone: str,
    eta_minutes: Optional[int] = None
) -> None:
    """Сповіщення: Водій прийняв замовлення"""
    eta_text = f"\n⏱️ Прибуде через: ~{eta_minutes} хв" if eta_minutes else ""
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📍 Де водій?", callback_data=f"track_driver:{order_id}"),
                InlineKeyboardButton(text="💬 Написати", callback_data=f"chat:start:{order_id}")
            ],
            [InlineKeyboardButton(text="📞 Зателефонувати", url=f"tel:{driver_phone}")]
        ]
    )
    
    try:
        await bot.send_message(
            client_id,
            f"✅ <b>Водій прийняв замовлення!</b>\n\n"
            f"👤 Водій: {driver_name}\n"
            f"🚗 Авто: {car_info}\n"
            f"🔢 Номер: {car_plate}\n"
            f"📱 Телефон: <code>{driver_phone}</code>{eta_text}\n\n"
            f"🚗 <b>Водій їде до вас!</b>",
            reply_markup=kb
        )
    except Exception as e:
        logger.error(f"Failed to notify client {client_id}: {e}")


async def notify_client_driver_arrived(
    bot: Bot,
    client_id: int,
    order_id: int,
    driver_name: str
) -> None:
    """Сповіщення: Водій на місці"""
    try:
        await bot.send_message(
            client_id,
            f"📍 <b>Водій вже біля вас!</b>\n\n"
            f"👤 {driver_name} чекає на вас.\n"
            f"Виходьте будь ласка! 🚶"
        )
    except Exception as e:
        logger.error(f"Failed to notify client {client_id}: {e}")


async def notify_client_trip_started(
    bot: Bot,
    client_id: int,
    order_id: int,
    destination: str
) -> None:
    """Сповіщення: Поїздка розпочалась"""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆘 SOS", callback_data="sos:confirm")]
        ]
    )
    
    try:
        await bot.send_message(
            client_id,
            f"🚗 <b>Поїздка розпочалась!</b>\n\n"
            f"📍 Їдемо: {destination}\n\n"
            f"Приємної подорожі! ✨",
            reply_markup=kb
        )
    except Exception as e:
        logger.error(f"Failed to notify client {client_id}: {e}")


async def notify_client_trip_completed(
    bot: Bot,
    client_id: int,
    order_id: int,
    driver_tg_id: int,
    fare: float,
    distance_km: float,
    duration_min: int
) -> None:
    """Сповіщення: Поїздка завершена"""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐️ 5", callback_data=f"rate:driver:{driver_tg_id}:5:{order_id}"),
                InlineKeyboardButton(text="⭐️ 4", callback_data=f"rate:driver:{driver_tg_id}:4:{order_id}"),
            ],
            [
                InlineKeyboardButton(text="⭐️ 3", callback_data=f"rate:driver:{driver_tg_id}:3:{order_id}"),
                InlineKeyboardButton(text="⭐️ 2", callback_data=f"rate:driver:{driver_tg_id}:2:{order_id}"),
                InlineKeyboardButton(text="⭐️ 1", callback_data=f"rate:driver:{driver_tg_id}:1:{order_id}"),
            ]
        ]
    )
    
    try:
        await bot.send_message(
            client_id,
            f"✅ <b>Поїздку завершено!</b>\n\n"
            f"💰 Вартість: {fare:.2f} грн\n"
            f"📏 Відстань: {distance_km:.1f} км\n"
            f"⏱️ Час: {duration_min} хв\n\n"
            f"Будь ласка, оцініть водія:",
            reply_markup=kb
        )
    except Exception as e:
        logger.error(f"Failed to notify client {client_id}: {e}")


async def notify_driver_new_order(
    bot: Bot,
    driver_id: int,
    order_id: int,
    client_name: str,
    pickup_address: str,
    destination_address: str,
    distance_km: Optional[float] = None,
    estimated_fare: Optional[float] = None
) -> None:
    """Сповіщення водію про нове замовлення"""
    distance_text = f"\n📏 Відстань: {distance_km:.1f} км" if distance_km else ""
    fare_text = f"\n💰 Орієнтовна вартість: ~{estimated_fare:.0f} грн" if estimated_fare else ""
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Прийняти", callback_data=f"accept_order:{order_id}"),
                InlineKeyboardButton(text="❌ Відхилити", callback_data=f"reject_order:{order_id}")
            ]
        ]
    )
    
    try:
        await bot.send_message(
            driver_id,
            f"🔔 <b>НОВЕ ЗАМОВЛЕННЯ #{order_id}</b>\n\n"
            f"👤 Клієнт: {client_name}\n"
            f"📍 Звідки: {pickup_address}\n"
            f"📍 Куди: {destination_address}{distance_text}{fare_text}\n\n"
            f"⏰ Прийміть замовлення швидше за інших!",
            reply_markup=kb
        )
    except Exception as e:
        logger.error(f"Failed to notify driver {driver_id}: {e}")
