from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from aiogram import Dispatcher, Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.strategy import FSMStrategy
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
# Реферальна програма прибрана
# from app.handlers.referral import create_router as create_referral_router
from app.handlers.client_rating import create_router as create_client_rating_router
from app.handlers.voice_input import create_router as create_voice_input_router
# Розширена аналітика ПРИБРАНО - не потрібна
# from app.handlers.driver_analytics import create_router as create_driver_analytics_router
from app.handlers.webapp import create_router as create_webapp_router  # WebApp з картою
from app.storage.db import init_db
from app.utils.scheduler import start_scheduler


async def health_check(request):
    """Health check endpoint for Render"""
    return web.Response(text="OK", status=200)


async def telegram_webhook_handler(request, bot, dp):
    """
    Обробник Telegram webhook запитів
    
    Args:
        request: aiohttp request
        bot: Bot instance
        dp: Dispatcher instance
    """
    from aiogram.types import Update
    import traceback
    
    try:
        # Отримати JSON від Telegram
        data = await request.json()
        
        # Створити Update об'єкт
        update = Update(**data)
        
        # Обробити через dispatcher
        await dp.feed_update(bot, update)
        
        return web.Response(status=200)
    except Exception as e:
        # Ігнорувати помилки "message is not modified" - це нормально
        error_text = str(e)
        if "message is not modified" in error_text.lower():
            logging.debug(f"⚠️ Спроба змінити повідомлення з тим самим контентом (ігноруємо): {e}")
            return web.Response(status=200)  # OK - не критична помилка
        
        # Детальне логування з повним traceback для інших помилок
        logging.error(f"❌ Помилка обробки webhook: {e}")
        logging.error(f"📜 Traceback:\n{traceback.format_exc()}")
        return web.Response(status=500)


async def start_webhook_server(bot=None, dp=None):
    """
    Запустити HTTP сервер для Webhook, health checks та статичних файлів
    
    Args:
        bot: Bot instance (для webhook)
        dp: Dispatcher instance (для webhook)
    """
    app = web.Application()
    
    # Health check endpoints
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)
    
    # ═══════════════════════════════════════════════════════════════
    # 🗺️ СТАТИЧНІ ФАЙЛИ (WebApp карта)
    # ═══════════════════════════════════════════════════════════════
    # Визначити шлях до webapp папки
    # main.py знаходиться в app/, webapp/ на рівень вище
    webapp_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'webapp')
    
    if os.path.exists(webapp_dir):
        # Додати статичний роут для webapp файлів
        app.router.add_static('/webapp/', webapp_dir, name='webapp')
        logging.info(f"🗺️ Static files (WebApp) enabled: /webapp/ → {webapp_dir}")
        logging.info(f"✅ WebApp доступний за адресою: https://your-app.onrender.com/webapp/index.html")
    else:
        logging.warning(f"⚠️ WebApp directory not found: {webapp_dir}")
    
    # Webhook endpoint (якщо передано bot і dp)
    if bot and dp:
        webhook_token = bot.token.split(':')[1]  # Використовуємо частину токену як secret
        webhook_path = f'/webhook/{webhook_token}'
        
        # Додати webhook handler
        app.router.add_post(
            webhook_path,
            lambda req: telegram_webhook_handler(req, bot, dp)
        )
        logging.info(f"🎯 Webhook endpoint: {webhook_path}")
    
    port = int(os.getenv('PORT', 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"🌐 HTTP server started on port {port}")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)

    # Перевірка DATABASE_URL на Render
    if os.getenv('RENDER'):
        database_url = os.getenv('DATABASE_URL')
        logger.info("="*60)
        logger.info("🔍 ПЕРЕВІРКА НАЛАШТУВАНЬ НА RENDER")
        logger.info("="*60)
        
        if database_url:
            # Приховати пароль для безпеки
            safe_url = database_url.split('@')[0].split('://')[0] + "://***@" + database_url.split('@')[1] if '@' in database_url else "***"
            logger.info(f"✅ DATABASE_URL встановлено: {safe_url}")
            
            if database_url.startswith("postgres://") or database_url.startswith("postgresql://"):
                logger.info("✅ DATABASE_URL починається з postgres:// - використовую PostgreSQL")
            else:
                logger.warning(f"⚠️  DATABASE_URL НЕ починається з postgres:// (починається з: {database_url.split('://')[0]}://)")
                logger.warning("⚠️  Буде використано SQLite, що НЕ рекомендовано на Render!")
        else:
            logger.error("❌ DATABASE_URL НЕ ВСТАНОВЛЕНО на Render!")
            logger.error("❌ Налаштуйте PostgreSQL в Render Dashboard:")
            logger.error("   1. Dashboard → Services → New → PostgreSQL")
            logger.error("   2. Скопіюйте Internal Database URL")
            logger.error("   3. Environment → Add DATABASE_URL")
            logger.warning("⚠️  Використовую SQLite (дані будуть втрачені при рестарті!)")
        
        logger.info("="*60)
        
        startup_delay = 60  # Збільшено до 60 секунд для PostgreSQL + міграції!
        logging.info(f"⏳ Затримка запуску {startup_delay}s для graceful shutdown старого процесу...")
        for i in range(startup_delay):
            if i % 10 == 0:
                logging.info(f"⏳ Очікування... {startup_delay - i}s залишилось")
            await asyncio.sleep(1)

    config = load_config()
    await init_db(config.database_path)

    bot = Bot(token=config.bot.token, default=DefaultBotProperties(parse_mode="HTML"))
    
    # ⭐ FSM Strategy: GLOBAL_USER - зберігати стан тільки по user_id (не chat_id)
    # Це дозволяє водію натискати "Прийняти" в групі, а надсилати геолокацію в приватний чат
    dp = Dispatcher(
        storage=MemoryStorage(),
        fsm_strategy=FSMStrategy.GLOBAL_USER  # Тільки user_id, без прив'язки до chat_id
    )

    # Include all routers (порядок важливий!)
    dp.include_router(create_webapp_router(config))  # WebApp ПЕРШИМ (обробляє web_app_data!)
    dp.include_router(create_start_router(config))
    dp.include_router(create_registration_router(config))  # Registration module
    dp.include_router(create_saved_addresses_router(config))  # Збережені адреси - ПЕРЕД order (state має пріоритет!)
    dp.include_router(create_order_router(config))  # Order перед Client!
    dp.include_router(create_admin_router(config))  # Admin ПЕРЕД driver_panel (пріоритет адміна!)
    dp.include_router(create_driver_panel_router(config))
    dp.include_router(create_driver_router(config))
    dp.include_router(create_ratings_router(config))
    dp.include_router(create_cancel_reasons_router(config))  # Причини скасування
    dp.include_router(create_chat_router(config))  # Чат
    dp.include_router(create_promocodes_router(config))  # Промокоди
    dp.include_router(create_sos_router(config))  # SOS
    dp.include_router(create_live_tracking_router(config))  # Живе відстеження
    dp.include_router(create_tips_router(config))  # Чайові
    # dp.include_router(create_referral_router(config))  # Реферальна програма - ПРИБРАНО
    dp.include_router(create_client_rating_router(config))  # Рейтинг клієнтів
    dp.include_router(create_voice_input_router(config))  # Голосовий ввід
    # dp.include_router(create_driver_analytics_router(config))  # Аналітика водія - ПРИБРАНО
    dp.include_router(create_client_router(config))  # Client останній

    # Start scheduled tasks
    await start_scheduler(bot, config.database_path, config.payment_card)
    
    logging.info("🚀 Bot started successfully!")
    
    # Перевірка інформації про бота
    try:
        me = await bot.get_me()
        logging.info(f"✅ Бот @{me.username} (ID: {me.id}) готовий до запуску")
    except Exception as e:
        logging.warning(f"⚠️ Не вдалося отримати інфо про бота: {e}")
    
    # === ВИЗНАЧЕННЯ РЕЖИМУ: WEBHOOK або POLLING ===
    use_webhook = bool(
        os.getenv('WEBHOOK_URL') or 
        os.getenv('RENDER') or 
        os.getenv('PRODUCTION')
    )
    
    if use_webhook:
        # ========================================
        # 🎯 WEBHOOK MODE (Production)
        # ========================================
        logging.info("=" * 60)
        logging.info("🎯 РЕЖИМ: WEBHOOK (Production)")
        logging.info("=" * 60)
        
        # Отримати URL для webhook
        webhook_base_url = os.getenv('WEBHOOK_URL')
        
        if not webhook_base_url:
            # Автоматично визначити URL на Render
            render_service = os.getenv('RENDER_SERVICE_NAME', 'taxi-bot')
            webhook_base_url = f"https://{render_service}.onrender.com"
            logging.info(f"🔍 WEBHOOK_URL не встановлено, використовую: {webhook_base_url}")
        
        # Створити webhook URL з секретним токеном
        webhook_token = bot.token.split(':')[1]
        webhook_url = f"{webhook_base_url}/webhook/{webhook_token}"
        
        try:
            # Встановити webhook в Telegram
            await bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True,
                allowed_updates=dp.resolve_used_update_types()
            )
            
            # Перевірити що webhook встановлено
            webhook_info = await bot.get_webhook_info()
            
            logging.info("✅ Webhook налаштовано успішно!")
            logging.info(f"📍 URL: {webhook_info.url}")
            logging.info(f"📊 Pending updates: {webhook_info.pending_update_count}")
            
            if webhook_info.last_error_date:
                logging.warning(f"⚠️ Остання помилка: {webhook_info.last_error_message}")
            
        except Exception as e:
            logging.error(f"❌ Помилка налаштування webhook: {e}")
            logging.error("Перемикаюсь на Polling...")
            use_webhook = False
        
        if use_webhook:
            # Запустити HTTP сервер з webhook handler
            await start_webhook_server(bot, dp)
            
            logging.info("🎯 Webhook сервер запущено!")
            logging.info("⚡ Бот отримуватиме оновлення МИТТЄВО")
            logging.info("💰 Економія ресурсів: ~90%")
            
            # Тримати сервер запущеним
            try:
                # Чекати безкінечно (сервер працює в фоні)
                await asyncio.Event().wait()
            except (KeyboardInterrupt, SystemExit):
                logging.info("🛑 Отримано сигнал зупинки")
            finally:
                # Видалити webhook при зупинці
                try:
                    await bot.delete_webhook()
                    logging.info("✅ Webhook видалено")
                except Exception:
                    pass
    
    if not use_webhook:
        # ========================================
        # 🔄 POLLING MODE (Development)
        # ========================================
        logging.info("=" * 60)
        logging.info("🔄 РЕЖИМ: POLLING (Development)")
        logging.info("=" * 60)
        logging.info("⚠️ Для production рекомендовано використовувати WEBHOOK")
        logging.info("💡 Встановіть WEBHOOK_URL або PRODUCTION=1 для webhook")
        
        # Видалити webhook якщо був встановлений раніше
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logging.info("✅ Webhook видалено, перемикаюсь на Polling")
            await asyncio.sleep(2)
        except Exception as e:
            logging.warning(f"⚠️ Не вдалося видалити webhook: {e}")
        
        # ⭐ Запустити HTTP сервер БЕЗ webhook handler (тільки для статичних файлів)
        asyncio.create_task(start_webhook_server(bot=None, dp=None))
        logging.info("🌐 HTTP сервер запущено для статичних файлів (WebApp)")
        
        # Запуск polling з retry при конфлікті
        max_retries = 3
        retry_delay = 10
        
        try:
            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        logging.info(f"🔄 Спроба {attempt + 1}/{max_retries} запуску polling...")
                        await asyncio.sleep(retry_delay * attempt)
                    else:
                        logging.info("🔄 Запуск polling...")
                    
                    await dp.start_polling(bot, allowed_updates=None)
                    break
                    
                except Exception as e:
                    if "Conflict" in str(e):
                        if attempt < max_retries - 1:
                            logging.warning(
                                f"⚠️ Конфлікт на спробі {attempt + 1}/{max_retries}. "
                                f"Чекаю {retry_delay * (attempt + 1)}s..."
                            )
                            continue
                        else:
                            logging.error("🔴 КРИТИЧНИЙ КОНФЛІКТ!")
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
