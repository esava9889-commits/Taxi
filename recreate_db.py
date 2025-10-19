#!/usr/bin/env python3
"""Скрипт для повного пересоздания локальної SQLite бази даних"""
import os
import sys
import asyncio
import logging

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def recreate_database():
    """Видалити стару БД і створити нову"""
    
    # Імпортуємо конфіг
    from app.config.config import load_config
    from app.storage.db import init_db
    
    logger.info("🔧 Початок пересоздания бази даних...")
    
    # Завантажити конфігурацію
    config = load_config()
    db_path = config.database_path
    
    logger.info(f"📁 Шлях до БД: {db_path}")
    
    # Видалити старий файл якщо існує
    if os.path.exists(db_path):
        logger.info(f"🗑️  Видаляю старий файл БД: {db_path}")
        try:
            os.remove(db_path)
            logger.info("✅ Старий файл видалено")
        except Exception as e:
            logger.error(f"❌ Помилка видалення: {e}")
            return False
    else:
        logger.info("ℹ️  Старий файл БД не знайдено, створюю новий")
    
    # Перевірити що папка існує
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        logger.info(f"📁 Створюю папку: {db_dir}")
        os.makedirs(db_dir, exist_ok=True)
    
    # Створити нову БД
    logger.info("🔨 Створюю нову базу даних...")
    try:
        await init_db(db_path)
        logger.info("✅ База даних успішно створена!")
        
        # Перевірити що файл існує
        if os.path.exists(db_path):
            file_size = os.path.getsize(db_path)
            logger.info(f"✅ Файл БД створено: {db_path} ({file_size} bytes)")
            
            # Перевірити таблиці
            import aiosqlite
            async with aiosqlite.connect(db_path) as db:
                async with db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ) as cur:
                    tables = await cur.fetchall()
                    logger.info(f"📊 Створено таблиць: {len(tables)}")
                    for table in tables:
                        logger.info(f"  ✓ {table[0]}")
            
            return True
        else:
            logger.error("❌ Файл БД не створено!")
            return False
            
    except Exception as e:
        logger.error(f"❌ Помилка при створенні БД: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    result = asyncio.run(recreate_database())
    
    if result:
        print("\n" + "="*60)
        print("✅ БАЗА ДАНИХ УСПІШНО СТВОРЕНА!")
        print("="*60)
        print("\nТепер можна запускати бота:")
        print("  python app/main.py")
        print()
        sys.exit(0)
    else:
        print("\n" + "="*60)
        print("❌ ПОМИЛКА ПРИ СТВОРЕННІ БАЗИ ДАНИХ")
        print("="*60)
        print("\nПеревірте логи вище для деталей")
        print()
        sys.exit(1)
