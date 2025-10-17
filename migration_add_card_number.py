#!/usr/bin/env python3
"""
Міграція: додати card_number до drivers
"""
import asyncio
import aiosqlite
import sys


async def migrate(db_path: str):
    """Додати card_number колонку до таблиці drivers"""
    async with aiosqlite.connect(db_path) as db:
        # Перевірити чи існує колонка
        async with db.execute("PRAGMA table_info(drivers)") as cur:
            columns = await cur.fetchall()
            col_names = [c[1] for c in columns]
        
        if 'card_number' in col_names:
            print("✅ Колонка card_number вже існує")
        else:
            print("⚙️  Додаю колонку card_number...")
            await db.execute("ALTER TABLE drivers ADD COLUMN card_number TEXT")
            await db.commit()
            print("✅ Колонка card_number додана")
        
        # Перевірити car_class
        if 'car_class' not in col_names:
            print("⚙️  Додаю колонку car_class...")
            await db.execute("ALTER TABLE drivers ADD COLUMN car_class TEXT NOT NULL DEFAULT 'economy'")
            await db.commit()
            print("✅ Колонка car_class додана")
        else:
            print("✅ Колонка car_class вже існує")
    
    print("\n🎉 Міграція завершена успішно!")


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/taxi.db"
    print(f"📊 База даних: {db_path}\n")
    asyncio.run(migrate(db_path))
