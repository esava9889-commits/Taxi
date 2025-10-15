#!/usr/bin/env python3
"""
Скрипт для видалення webhook і очищення pending updates
Запустіть локально один раз
"""
import asyncio
import os
from aiogram import Bot

async def delete_webhook():
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("❌ Встановіть BOT_TOKEN в .env")
        return
    
    bot = Bot(token=token)
    
    # Видалити webhook
    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Webhook видалено!")
    print("✅ Pending updates очищено!")
    
    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(delete_webhook())
