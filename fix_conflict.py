#!/usr/bin/env python3
"""Скрипт для видалення webhook"""
import asyncio
import os
from aiogram import Bot
from dotenv import load_dotenv

async def fix():
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    bot = Bot(token=token)
    
    try:
        me = await bot.get_me()
        print(f"✅ Бот: @{me.username}")
        
        webhook = await bot.get_webhook_info()
        print(f"📡 Webhook: {webhook.url or 'Немає'}")
        
        if webhook.url:
            print("⚠️ Видаляю webhook...")
            await bot.delete_webhook(drop_pending_updates=True)
            print("✅ Webhook видалено!")
        
    finally:
        await bot.session.close()

asyncio.run(fix())
