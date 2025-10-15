#!/usr/bin/env python3
"""
Скрипт для ініціалізації тарифів

Запустіть один раз після створення БД:
python init_tariffs.py
"""
import asyncio
from datetime import datetime, timezone
from app.config.config import load_config
from app.storage.db import init_db, Tariff, insert_tariff, get_latest_tariff


async def main():
    config = load_config()
    await init_db(config.database_path)
    
    # Перевірити чи є тарифи
    existing = await get_latest_tariff(config.database_path)
    if existing:
        print(f"✅ Тариф вже існує:")
        print(f"   Базова ставка: {existing.base_fare} грн")
        print(f"   За км: {existing.per_km} грн/км")
        print(f"   За хвилину: {existing.per_minute} грн/хв")
        print(f"   Мінімум: {existing.minimum} грн")
        return
    
    # Створити тариф
    tariff = Tariff(
        id=None,
        base_fare=50.0,      # Базова ставка: 50 грн
        per_km=8.0,          # За кілометр: 8 грн
        per_minute=1.0,      # За хвилину: 1 грн
        minimum=80.0,        # Мінімальна вартість: 80 грн
        created_at=datetime.now(timezone.utc)
    )
    
    tariff_id = await insert_tariff(config.database_path, tariff)
    
    print(f"✅ Тариф створено (ID: {tariff_id}):")
    print(f"   Базова ставка: {tariff.base_fare} грн")
    print(f"   За км: {tariff.per_km} грн/км")
    print(f"   За хвилину: {tariff.per_minute} грн/хв")
    print(f"   Мінімум: {tariff.minimum} грн")
    print()
    print("Приклади розрахунку:")
    print(f"   5 км (~10 хв): {max(tariff.minimum, tariff.base_fare + 5*tariff.per_km + 10*tariff.per_minute):.0f} грн")
    print(f"   50 км (~60 хв): {max(tariff.minimum, tariff.base_fare + 50*tariff.per_km + 60*tariff.per_minute):.0f} грн")
    print(f"   450 км (~360 хв): {max(tariff.minimum, tariff.base_fare + 450*tariff.per_km + 360*tariff.per_minute):.0f} грн")


if __name__ == "__main__":
    asyncio.run(main())
