from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from aiogram import Dispatcher, Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

from app.config.config import load_config
from app.handlers.order import create_router as create_order_router
from app.handlers.start import create_router as create_start_router
from app.handlers.registration import create_registration_router
from app.handlers.driver import create_router as create_driver_router
from app.handlers.admin import create_router as create_admin_router
from app.handlers.driver_panel import create_router as create_driver_panel_router
from app.handlers.client import create_router as create_client_router
from app.handlers.ratings import create_router as create_ratings_router
from app.handlers.saved_addresses import create_router as create_saved_addresses_router
from app.handlers.cancel_reasons import create_router as create_cancel_reasons_router
from app.handlers.chat import create_router as create_chat_router
from app.handlers.promocodes import create_router as create_promocodes_router
from app.handlers.sos import create_router as create_sos_router
from app.handlers.live_tracking import create_router as create_live_tracking_router
from app.handlers.tips import create_router as create_tips_router
from app.handlers.referral import create_router as create_referral_router
from app.handlers.client_rating import create_router as create_client_rating_router
from app.handlers.voice_input import create_router as create_voice_input_router
from app.handlers.driver_analytics import create_router as create_driver_analytics_router
from app.storage.db import init_db
from app.utils.scheduler import start_scheduler


async def health_check(request):
    """Health check endpoint for Render"""
    return web.Response(text="OK", status=200)


async def start_webhook_server():
    """Start simple HTTP server for Render health checks"""
    app = web.Application()
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)
    
    port = int(os.getenv('PORT', 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"🌐 Health check server started on port {port}")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Затримка при запуску щоб старий процес встиг завершитись
    if os.getenv('RENDER'):
        startup_delay = 60  # Збільшено до 60 секунд для PostgreSQL + міграції!
        logging.info(f"⏳ Затримка запуску {startup_delay}s для graceful shutdown старого процесу...")
        for i in range(startup_delay):
            if i % 10 == 0:
                logging.info(f"⏳ Очікування... {startup_delay - i}s залишилось")
            await asyncio.sleep(1)

    config = load_config()
    await init_db(config.database_path)

    bot = Bot(token=config.bot.token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    # Include all routers (порядок важливий!)
    dp.include_router(create_start_router(config))
    dp.include_router(create_registration_router(config))  # Registration module
    dp.include_router(create_order_router(config))  # Order перед Client!
    dp.include_router(create_driver_panel_router(config))
    dp.include_router(create_driver_router(config))
    dp.include_router(create_admin_router(config))
    dp.include_router(create_ratings_router(config))
    dp.include_router(create_saved_addresses_router(config))  # Збережені адреси
    dp.include_router(create_cancel_reasons_router(config))  # Причини скасування
    dp.include_router(create_chat_router(config))  # Чат
    dp.include_router(create_promocodes_router(config))  # Промокоди
    dp.include_router(create_sos_router(config))  # SOS
    dp.include_router(create_live_tracking_router(config))  # Живе відстеження
    dp.include_router(create_tips_router(config))  # Чайові
    dp.include_router(create_referral_router(config))  # Реферальна програма
    dp.include_router(create_client_rating_router(config))  # Рейтинг клієнтів
    dp.include_router(create_voice_input_router(config))  # Голосовий ввід
    dp.include_router(create_driver_analytics_router(config))  # Аналітика водія
    dp.include_router(create_client_router(config))  # Client останній

    # Start scheduled tasks
    await start_scheduler(bot, config.database_path, config.payment_card)
    
    # Start health check server for Render (if on Render)
    if os.getenv('RENDER'):
        asyncio.create_task(start_webhook_server())
        logging.info("🏥 Health check server enabled for Render")
    
    logging.info("🚀 Bot started successfully!")

    # Видалити webhook і очистити pending updates перед запуском
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("✅ Webhook видалено, pending updates очищено")
        await asyncio.sleep(3)  # Почекати поки Telegram обробить
    except Exception as e:
        logging.warning(f"⚠️ Не вдалося видалити webhook: {e}")
    
    # Перевірка чи немає іншого бота - спробувати getMe
    try:
        me = await bot.get_me()
        logging.info(f"✅ Бот @{me.username} готовий до запуску")
        await asyncio.sleep(2)
    except Exception as e:
        logging.warning(f"⚠️ Не вдалося отримати інфо про бота: {e}")
    
    # Простий запуск polling з retry при конфлікті
    max_retries = 3
    retry_delay = 10
    
    try:
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logging.info(f"🔄 Спроба {attempt + 1}/{max_retries} запуску polling...")
                    await asyncio.sleep(retry_delay * attempt)  # Експоненціальна затримка
                else:
                    logging.info("🔄 Запуск polling...")
                
                await dp.start_polling(bot, allowed_updates=None)
                break  # Якщо успішно - вийти з циклу
                
            except Exception as e:
                if "Conflict" in str(e):
                    if attempt < max_retries - 1:
                        logging.warning(
                            f"⚠️ Конфлікт на спробі {attempt + 1}/{max_retries}. "
                            f"Чекаю {retry_delay * (attempt + 1)}s перед наступною спробою..."
                        )
                        continue
                    else:
                        logging.error(
                            "🔴 КРИТИЧНИЙ КОНФЛІКТ: Старий процес все ще працює після всіх спроб!\n"
                            "📋 РІШЕННЯ:\n"
                            "1. Зайдіть в Render Dashboard\n"
                            "2. Натисніть 'Suspend' щоб зупинити сервіс\n"
                            "3. Зачекайте 30 секунд\n"
                            "4. Натисніть 'Resume' для запуску\n"
                            "Або видаліть старий deploy і зробіть новий."
                        )
                logging.error(f"❌ Помилка: {e}")
                if attempt == max_retries - 1:
                    raise
    finally:
        # Cleanup
        try:
            await bot.session.close()
        except Exception:
            pass
        logging.info("👋 Бот зупинено")


if __name__ == "__main__":
    asyncio.run(main())
