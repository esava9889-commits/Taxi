"""Push-сповіщення для водіїв (розумні нагадування)"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Bot
from app.handlers.dynamic_pricing import get_surge_multiplier

logger = logging.getLogger(__name__)


async def notify_driver_peak_hours(bot: Bot, driver_id: int, city: str) -> None:
    """Нагадування про піковий час"""
    try:
        await bot.send_message(
            driver_id,
            "⏰ <b>Піковий час через 30 хвилин!</b>\n\n"
            "🔥 Очікується підвищений попит (+30%)\n"
            "💰 Виходьте онлайн для максимального заробітку!\n\n"
            f"🏙 {city}: 7:30-9:00 та 17:00-19:00",
        )
    except Exception as e:
        logger.error(f"Failed to notify driver {driver_id}: {e}")


async def notify_driver_high_demand(bot: Bot, driver_id: int, city: str, surge_percent: int) -> None:
    """Сповіщення про високий попит"""
    emoji = "🔥🔥🔥" if surge_percent > 50 else "🔥🔥" if surge_percent > 30 else "🔥"
    
    try:
        await bot.send_message(
            driver_id,
            f"{emoji} <b>ВИСОКИЙ ПОПИТ В {city.upper()}!</b> {emoji}\n\n"
            f"🔥 Зараз підвищений тариф: <b>+{surge_percent}%</b>\n"
            f"💰 Ви можете заробити на {surge_percent}% більше!\n\n"
            "⚡ Виходьте онлайн прямо зараз!"
        )
    except Exception as e:
        logger.error(f"Failed to notify driver {driver_id}: {e}")


async def notify_driver_daily_goal(bot: Bot, driver_id: int, current: float, goal: float) -> None:
    """Нагадування про денну ціль заробітку"""
    remaining = goal - current
    percent = (current / goal * 100) if goal > 0 else 0
    
    if percent >= 100:
        # Ціль досягнута
        try:
            await bot.send_message(
                driver_id,
                "🎉 <b>ВІТАЄМО!</b>\n\n"
                f"Ви досягли денної цілі: {goal:.0f} грн!\n"
                f"💰 Ваш заробіток: {current:.0f} грн\n\n"
                "Продовжуйте працювати або відпочиньте! 😊"
            )
        except Exception as e:
            logger.error(f"Failed to notify driver {driver_id}: {e}")
    
    elif percent >= 70:
        # Майже досягли
        try:
            await bot.send_message(
                driver_id,
                "💪 <b>Майже там!</b>\n\n"
                f"Ціль на сьогодні: {goal:.0f} грн\n"
                f"💰 Вже заробили: {current:.0f} грн ({percent:.0f}%)\n"
                f"⏱️ Залишилось: {remaining:.0f} грн\n\n"
                "Ще трохи! 🚀"
            )
        except Exception as e:
            logger.error(f"Failed to notify driver {driver_id}: {e}")


async def notify_driver_commission_reminder(bot: Bot, driver_id: int, amount: float, card: str) -> None:
    """Нагадування про несплачену комісію"""
    try:
        from app.utils.qr_generator import generate_payment_qr
        from aiogram.types import BufferedInputFile
        
        # Генерувати QR
        qr = generate_payment_qr(card, amount, f"Комісія водія {driver_id}")
        photo = BufferedInputFile(qr.read(), filename="commission_qr.png")
        
        await bot.send_photo(
            driver_id,
            photo=photo,
            caption=(
                "⏰ <b>НАГАДУВАННЯ ПРО КОМІСІЮ</b>\n\n"
                f"💸 До сплати: {amount:.2f} грн\n"
                f"📅 Сплатіть до 20:00 сьогодні\n\n"
                f"💳 Картка: <code>{card}</code>\n\n"
                "📱 Відскануйте QR-код для швидкої оплати\n"
                "або використайте кнопку '💳 Комісія' в меню"
            )
        )
    except Exception as e:
        logger.error(f"Failed to send commission reminder to driver {driver_id}: {e}")


async def notify_driver_earnings_milestone(bot: Bot, driver_id: int, milestone: int) -> None:
    """Сповіщення про досягнення віхи заробітку"""
    milestones = {
        500: "🎉 Перші 500 грн!",
        1000: "💰 Перша тисяча!",
        5000: "🚀 П'ять тисяч!",
        10000: "🏆 Десять тисяч!",
        50000: "💎 П'ятдесят тисяч!"
    }
    
    title = milestones.get(milestone, f"🎊 {milestone} грн!")
    
    try:
        await bot.send_message(
            driver_id,
            f"{title}\n\n"
            f"Ви заробили вже {milestone} грн за весь час!\n"
            "Продовжуйте в тому ж дусі! 💪"
        )
    except Exception as e:
        logger.error(f"Failed to notify driver {driver_id}: {e}")


async def notify_driver_low_rating_warning(bot: Bot, driver_id: int, rating: float) -> None:
    """Попередження про низький рейтинг"""
    if rating < 4.0:
        try:
            await bot.send_message(
                driver_id,
                "⚠️ <b>УВАГА: Низький рейтинг!</b>\n\n"
                f"Ваш рейтинг: {rating:.1f} ⭐\n"
                f"Норма: 4.5+ ⭐\n\n"
                "Низький рейтинг може призвести до:\n"
                "• Менше замовлень (клієнти обирають топ-водіїв)\n"
                "• Втрата пріоритету на нові замовлення\n"
                "• Блокування акаунту при <3.0\n\n"
                "💡 Як покращити:\n"
                "• Будьте ввічливі з клієнтами\n"
                "• Приїжджайте вчасно\n"
                "• Підтримуйте чистоту авто\n"
                "• Їздьте акуратно"
            )
        except Exception as e:
            logger.error(f"Failed to notify driver {driver_id}: {e}")


async def notify_driver_inactive(bot: Bot, driver_id: int, days: int) -> None:
    """Нагадування неактивному водію"""
    try:
        await bot.send_message(
            driver_id,
            f"👋 <b>Ми скучили за вами!</b>\n\n"
            f"Ви не працювали вже {days} днів.\n\n"
            "💰 <b>Спеціальна пропозиція:</b>\n"
            "• Вийдіть онлайн сьогодні\n"
            "• Отримайте бонус +10% на перші 3 поїздки\n\n"
            "🚗 Чекаємо вас на роботі!"
        )
    except Exception as e:
        logger.error(f"Failed to notify inactive driver {driver_id}: {e}")


async def notify_driver_new_area_opportunity(bot: Bot, driver_id: int, area: str, demand_percent: int) -> None:
    """Сповіщення про нові можливості в районі"""
    try:
        await bot.send_message(
            driver_id,
            f"📍 <b>МОЖЛИВІСТЬ В РАЙОНІ {area.upper()}!</b>\n\n"
            f"🔥 Підвищений попит: +{demand_percent}%\n"
            f"💰 Багато замовлень чекають водія!\n\n"
            "⚡ Поїдьте в цей район для збільшення заробітку!"
        )
    except Exception as e:
        logger.error(f"Failed to notify driver {driver_id}: {e}")
