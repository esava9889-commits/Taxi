from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher, Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.config.config import load_config
from app.handlers.order import create_router
from app.storage.db import init_db


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    config = load_config()
    await init_db(config.database_path)

    bot = Bot(token=config.bot.token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(create_router(config))

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=None)


if __name__ == "__main__":
    asyncio.run(main())
