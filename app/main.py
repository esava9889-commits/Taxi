from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher, Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.config.config import load_config
from app.handlers.order import create_router as create_order_router
from app.handlers.start import create_router as create_start_router
from app.handlers.driver import create_router as create_driver_router
from app.handlers.admin import create_router as create_admin_router
from app.handlers.driver_panel import create_router as create_driver_panel_router
from app.handlers.client import create_router as create_client_router
from app.handlers.ratings import create_router as create_ratings_router
from app.storage.db import init_db
from app.utils.scheduler import start_scheduler


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    config = load_config()
    await init_db(config.database_path)

    bot = Bot(token=config.bot.token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    # Include all routers
    dp.include_router(create_start_router(config))
    dp.include_router(create_client_router(config))
    dp.include_router(create_order_router(config))
    dp.include_router(create_driver_router(config))
    dp.include_router(create_driver_panel_router(config))
    dp.include_router(create_admin_router(config))
    dp.include_router(create_ratings_router(config))

    # Start scheduled tasks
    await start_scheduler(bot, config.database_path, config.payment_card)
    
    logging.info("🚀 Bot started successfully!")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=None)


if __name__ == "__main__":
    asyncio.run(main())
