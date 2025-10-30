"""Динамічне ціноутворення"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Tuple

from app.config.config import AppConfig

logger = logging.getLogger(__name__)


def get_surge_multiplier(
    city: str = "Київ", 
    night_percent: float = 50.0,
    peak_hours_percent: float = 30.0,
    weekend_percent: float = 20.0,
    monday_morning_percent: float = 15.0
) -> Tuple[float, str]:
    """
    Отримати множник підвищення та причину
    
    Args:
        city: Місто
        night_percent: % надбавки за нічний тариф (з БД)
        peak_hours_percent: % надбавки за піковий час (з БД)
        weekend_percent: % надбавки за вихідні (з БД)
        monday_morning_percent: % надбавки за понеділок вранці (з БД)
    
    Returns:
        (multiplier, reason) - множник та текст причини
    """
    now = datetime.now()
    hour = now.hour
    day_of_week = now.weekday()  # 0 = Monday, 6 = Sunday
    
    multiplier = 1.0
    reasons = []
    
    # 1. Піковий час (ранок та вечір)
    if (7 <= hour <= 9) or (17 <= hour <= 19):
        peak_mult = 1.0 + (peak_hours_percent / 100.0)
        multiplier *= peak_mult
        reasons.append(f"Піковий час (+{peak_hours_percent:.0f}%)")
    
    # 2. Нічний тариф (з БД!)
    if hour >= 23 or hour < 6:
        night_mult = 1.0 + (night_percent / 100.0)  # 50% → 1.5
        multiplier *= night_mult
        reasons.append(f"Нічний тариф (+{night_percent:.0f}%)")
    
    # 3. Вихідні (п'ятниця-неділя ввечері)
    if day_of_week >= 4 and 18 <= hour <= 23:  # Пт-Нд вечір
        weekend_mult = 1.0 + (weekend_percent / 100.0)
        multiplier *= weekend_mult
        reasons.append(f"Вихідний день (+{weekend_percent:.0f}%)")
    
    # 4. Понеділок вранці (всі поспішають)
    if day_of_week == 0 and 7 <= hour <= 10:
        monday_mult = 1.0 + (monday_morning_percent / 100.0)
        multiplier *= monday_mult
        reasons.append(f"Понеділок вранці (+{monday_morning_percent:.0f}%)")
    
    # Об'єднати причини
    reason_text = " + ".join(reasons) if reasons else "Базовий тариф"
    
    return multiplier, reason_text


def get_weather_multiplier(weather_percent: float = 0.0) -> Tuple[float, str]:
    """
    Множник за погодою
    
    Args:
        weather_percent: % надбавки за погодні умови (з БД)
    
    Returns:
        (multiplier, reason) - множник та текст причини
    """
    if weather_percent > 0:
        weather_mult = 1.0 + (weather_percent / 100.0)  # 20% → 1.2
        return weather_mult, f"Погодні умови (+{weather_percent:.0f}%)"
    
    return 1.0, ""


def get_demand_multiplier(
    online_drivers_count: int, 
    pending_orders_count: int,
    no_drivers_percent: float = 50.0,
    demand_very_high_percent: float = 40.0,
    demand_high_percent: float = 25.0,
    demand_medium_percent: float = 15.0,
    demand_low_discount_percent: float = 10.0
) -> Tuple[float, str]:
    """
    Множник за попитом (мало водіїв, багато замовлень)
    """
    if online_drivers_count == 0:
        no_drivers_mult = 1.0 + (no_drivers_percent / 100.0)
        return no_drivers_mult, f"Немає доступних водіїв (+{no_drivers_percent:.0f}%)"
    
    # Співвідношення замовлень до водіїв
    ratio = pending_orders_count / online_drivers_count if online_drivers_count > 0 else 0
    
    if ratio > 3:  # Більше 3 замовлень на водія
        very_high_mult = 1.0 + (demand_very_high_percent / 100.0)
        return very_high_mult, f"Дуже високий попит (+{demand_very_high_percent:.0f}%)"
    elif ratio > 2:
        high_mult = 1.0 + (demand_high_percent / 100.0)
        return high_mult, f"Високий попит (+{demand_high_percent:.0f}%)"
    elif ratio > 1.5:
        medium_mult = 1.0 + (demand_medium_percent / 100.0)
        return medium_mult, f"Підвищений попит (+{demand_medium_percent:.0f}%)"
    elif ratio < 0.3:  # Мало замовлень - знижка
        low_mult = 1.0 - (demand_low_discount_percent / 100.0)
        return low_mult, f"Низький попит (знижка -{demand_low_discount_percent:.0f}%)"
    
    return 1.0, ""


async def calculate_dynamic_price(
    base_fare: float,
    city: str = "Київ",
    online_drivers: int = 10,
    pending_orders: int = 5,
    night_percent: float = 50.0,
    weather_percent: float = 0.0,
    peak_hours_percent: float = 30.0,
    weekend_percent: float = 20.0,
    monday_morning_percent: float = 15.0,
    no_drivers_percent: float = 50.0,
    demand_very_high_percent: float = 40.0,
    demand_high_percent: float = 25.0,
    demand_medium_percent: float = 15.0,
    demand_low_discount_percent: float = 10.0
) -> Tuple[float, str, float]:
    """
    Розрахувати вартість з урахуванням всіх факторів
    
    Args:
        base_fare: Базова вартість
        city: Місто
        online_drivers: Кількість онлайн водіїв
        pending_orders: Кількість очікуючих замовлень
        night_percent: % надбавки за нічний тариф (з БД)
        weather_percent: % надбавки за погодні умови (з БД)
        peak_hours_percent: % надбавки за піковий час (з БД)
        weekend_percent: % надбавки за вихідні (з БД)
        monday_morning_percent: % надбавки за понеділок вранці (з БД)
        no_drivers_percent: % надбавки коли немає водіїв (з БД)
        demand_very_high_percent: % надбавки за дуже високий попит (з БД)
        demand_high_percent: % надбавки за високий попит (з БД)
        demand_medium_percent: % надбавки за середній попит (з БД)
        demand_low_discount_percent: % знижки за низький попит (з БД)
    
    Returns:
        (final_price, explanation, total_multiplier)
    """
    # 1. Час доби та день тижня
    time_mult, time_reason = get_surge_multiplier(
        city, night_percent, peak_hours_percent, weekend_percent, monday_morning_percent
    )
    
    # 2. Погода
    weather_mult, weather_reason = get_weather_multiplier(weather_percent)
    
    # 3. Попит
    demand_mult, demand_reason = get_demand_multiplier(
        online_drivers, pending_orders, no_drivers_percent,
        demand_very_high_percent, demand_high_percent, 
        demand_medium_percent, demand_low_discount_percent
    )
    
    # Загальний множник
    total_multiplier = time_mult * weather_mult * demand_mult
    
    # Фінальна ціна
    final_price = base_fare * total_multiplier
    
    # Пояснення
    reasons = []
    if time_reason:
        reasons.append(f"• {time_reason}: +{int((time_mult-1)*100)}%")
    if weather_reason:
        reasons.append(f"• {weather_reason}: +{int((weather_mult-1)*100)}%")
    if demand_reason:
        change = int((demand_mult-1)*100)
        sign = "+" if change > 0 else ""
        reasons.append(f"• {demand_reason}: {sign}{change}%")
    
    if not reasons:
        explanation = "Базовий тариф"
    else:
        explanation = "\n".join(reasons)
    
    logger.info(f"Dynamic pricing: base={base_fare}, final={final_price}, multiplier={total_multiplier}")
    
    return final_price, explanation, total_multiplier


def get_surge_emoji(multiplier: float) -> str:
    """Отримати емодзі для відображення попиту (тільки при націнках)"""
    if multiplier >= 1.5:
        return "🔥🔥🔥"
    elif multiplier >= 1.3:
        return "🔥🔥"
    elif multiplier >= 1.15:
        return "🔥"
    # Знижки без емодзі
    return ""
