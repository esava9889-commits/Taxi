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
        startup_delay = 15  # Збільшено до 15 секунд!
        logging.info(f"⏳ Затримка запуску {startup_delay}s для graceful shutdown старого процесу...")
        await asyncio.sleep(startup_delay)

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

    # Видалити webhook і очистити pending updates
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("✅ Webhook видалено, pending updates очищено")
    except Exception as e:
        logging.warning(f"⚠️ Не вдалося видалити webhook: {e}")
    
    # Обробник graceful shutdown
    shutdown_event = asyncio.Event()
    
    def signal_handler(sig, frame):
        logging.info(f"📥 Отримано сигнал {sig}, graceful shutdown...")
        shutdown_event.set()
    
    # Реєстрація обробників сигналів
    if sys.platform != 'win32':
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    
    # Запустити polling з обробкою конфліктів
    try:
        logging.info("🔄 Запуск polling...")
        
        # Polling task
        polling_task = asyncio.create_task(dp.start_polling(bot, allowed_updates=None))
        
        # Чекаємо або завершення polling або shutdown
        done, pending = await asyncio.wait(
            [polling_task, asyncio.create_task(shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Якщо shutdown - зупиняємо polling
        if shutdown_event.is_set():
            logging.info("🛑 Зупинка polling...")
            await dp.stop_polling()
            try:
                await bot.session.close()
            except Exception:
                pass
            logging.info("✅ Graceful shutdown завершено")
        
    except Exception as e:
        if "Conflict" in str(e):
            logging.error(
                "🔴 КОНФЛІКТ: Інший інстанс бота вже запущений!\n"
                "Зупиніть всі інші процеси бота:\n"
                "  - Локальні запуски (на вашому комп'ютері)\n"
                "  - Інші деплої на Render/Railway/інших платформах\n"
                "Telegram дозволяє тільки ОДИН активний інстанс бота.\n\n"
                "💡 Рішення: Render Dashboard → Settings → тип 'Background Worker' замість 'Web Service'"
            )
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
