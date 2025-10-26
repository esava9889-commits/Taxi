#!/usr/bin/env python3
"""
Скрипт ініціалізації налаштувань ціноутворення
Створює початкові значення в таблиці pricing_settings
"""

import asyncio
import sys
from datetime import datetime, timezone

# Додати шлях до модулів проекту
sys.path.insert(0, '/workspace')

from app.storage.db import PricingSettings, get_pricing_settings, upsert_pricing_settings


async def init_pricing_settings(db_path: str = "/workspace/taxi.db"):
    """Ініціалізувати налаштування ціноутворення"""
    
    print("🔧 Ініціалізація налаштувань ціноутворення...")
    
    # Перевірити чи вже є налаштування
    existing = await get_pricing_settings(db_path)
    
    if existing.id is not None:
        print(f"✅ Налаштування вже існують (ID: {existing.id})")
        print(f"   Класи авто: Економ={existing.economy_multiplier}, "
              f"Стандарт={existing.standard_multiplier}, "
              f"Комфорт={existing.comfort_multiplier}, "
              f"Бізнес={existing.business_multiplier}")
        return
    
    # Створити нові налаштування зі значеннями за замовчуванням
    settings = PricingSettings(
        # Класи авто
        economy_multiplier=1.0,
        standard_multiplier=1.3,
        comfort_multiplier=1.6,
        business_multiplier=2.0,
        
        # Часові націнки
        night_percent=50.0,
        peak_hours_percent=30.0,
        weekend_percent=20.0,
        monday_morning_percent=15.0,
        
        # Погода
        weather_percent=0.0,
        
        # Попит
        demand_very_high_percent=40.0,
        demand_high_percent=25.0,
        demand_medium_percent=15.0,
        demand_low_discount_percent=10.0,
        no_drivers_percent=50.0,
        
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    
    success = await upsert_pricing_settings(db_path, settings)
    
    if success:
        print("✅ Налаштування ціноутворення успішно створено!")
        print("\n📊 Початкові значення:")
        print(f"   🚗 Класи авто:")
        print(f"      • Економ: x{settings.economy_multiplier}")
        print(f"      • Стандарт: x{settings.standard_multiplier}")
        print(f"      • Комфорт: x{settings.comfort_multiplier}")
        print(f"      • Бізнес: x{settings.business_multiplier}")
        print(f"\n   ⏰ Часові націнки:")
        print(f"      • Нічний: +{settings.night_percent}%")
        print(f"      • Піковий: +{settings.peak_hours_percent}%")
        print(f"      • Вихідні: +{settings.weekend_percent}%")
        print(f"      • Понеділок: +{settings.monday_morning_percent}%")
        print(f"\n   📊 Попит:")
        print(f"      • Немає водіїв: +{settings.no_drivers_percent}%")
        print(f"      • Дуже високий: +{settings.demand_very_high_percent}%")
        print(f"      • Високий: +{settings.demand_high_percent}%")
        print(f"      • Середній: +{settings.demand_medium_percent}%")
        print(f"      • Низький: -{settings.demand_low_discount_percent}%")
    else:
        print("❌ Помилка створення налаштувань!")
        sys.exit(1)


if __name__ == "__main__":
    import os
    
    # Визначити шлях до БД
    db_path = os.environ.get("DATABASE_PATH", "/workspace/taxi.db")
    
    # Запустити ініціалізацію
    asyncio.run(init_pricing_settings(db_path))
    
    print("\n✨ Готово! Тепер ви можете налаштувати ціноутворення через панель адміна.")
