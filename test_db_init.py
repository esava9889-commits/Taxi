#!/usr/bin/env python3
"""
Тестування ініціалізації БД та перевірка всіх таблиць
"""
import asyncio
import aiosqlite
import os
from app.storage.db import init_db


async def test_db():
    """Тестування БД"""
    test_db_path = "/tmp/test_taxi_bot.db"
    
    # Видалити стару БД якщо є
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
        print(f"🗑️  Видалено стару БД: {test_db_path}")
    
    print("\n📊 Тестування ініціалізації БД...\n")
    
    # Ініціалізувати БД
    try:
        await init_db(test_db_path)
        print("✅ init_db() виконано успішно!\n")
    except Exception as e:
        print(f"❌ ПОМИЛКА при init_db(): {e}")
        return
    
    # Перевірити всі таблиці
    async with aiosqlite.connect(test_db_path) as db:
        # Отримати список таблиць
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cur:
            tables = await cur.fetchall()
        
        print("📋 ТАБЛИЦІ В БД:")
        print("=" * 60)
        
        for (table_name,) in tables:
            # Отримати колонки таблиці
            async with db.execute(f"PRAGMA table_info({table_name})") as cur:
                columns = await cur.fetchall()
            
            print(f"\n✅ {table_name}:")
            for col in columns:
                col_id, col_name, col_type, not_null, default, pk = col
                flags = []
                if pk:
                    flags.append("PRIMARY KEY")
                if not_null:
                    flags.append("NOT NULL")
                if default:
                    flags.append(f"DEFAULT {default}")
                
                flags_str = f" ({', '.join(flags)})" if flags else ""
                print(f"   - {col_name}: {col_type}{flags_str}")
        
        print("\n" + "=" * 60)
        
        # Перевірити DRIVERS детально
        print("\n🚗 ДЕТАЛЬНА ПЕРЕВІРКА ТАБЛИЦІ 'drivers':")
        print("=" * 60)
        
        async with db.execute("PRAGMA table_info(drivers)") as cur:
            driver_cols = await cur.fetchall()
            driver_col_names = [col[1] for col in driver_cols]
        
        required_cols = [
            'id', 'tg_user_id', 'full_name', 'phone', 
            'car_make', 'car_model', 'car_plate', 
            'license_photo_file_id', 'city', 'status', 
            'created_at', 'updated_at', 'online', 
            'last_lat', 'last_lon', 'last_seen_at',
            'car_class', 'card_number'  # Нові колонки!
        ]
        
        print(f"\nОчікувані колонки: {len(required_cols)}")
        print(f"Фактичні колонки: {len(driver_col_names)}")
        
        missing = []
        extra = []
        
        for col in required_cols:
            if col not in driver_col_names:
                missing.append(col)
        
        for col in driver_col_names:
            if col not in required_cols:
                extra.append(col)
        
        if missing:
            print(f"\n❌ ВІДСУТНІ колонки: {', '.join(missing)}")
        else:
            print("\n✅ Всі необхідні колонки присутні!")
        
        if extra:
            print(f"\n⚠️  Зайві колонки: {', '.join(extra)}")
        
        # Перевірити car_class та card_number
        print("\n🔍 Перевірка нових колонок:")
        if 'car_class' in driver_col_names:
            print("   ✅ car_class - є")
        else:
            print("   ❌ car_class - ВІДСУТНЯ!")
        
        if 'card_number' in driver_col_names:
            print("   ✅ card_number - є")
        else:
            print("   ❌ card_number - ВІДСУТНЯ!")
        
        print("\n" + "=" * 60)
        
        # Перевірити індекси
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        ) as cur:
            indexes = await cur.fetchall()
        
        print(f"\n📌 ІНДЕКСИ ({len(indexes)}):")
        for (idx_name,) in indexes:
            if not idx_name.startswith('sqlite_'):
                print(f"   ✅ {idx_name}")
        
        print("\n" + "=" * 60)
        print("\n🎉 ТЕСТУВАННЯ ЗАВЕРШЕНО!")
    
    # Очистити
    os.remove(test_db_path)
    print(f"\n🗑️  Тестову БД видалено")


if __name__ == "__main__":
    asyncio.run(test_db())
