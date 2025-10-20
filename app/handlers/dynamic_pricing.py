"""Динамічне ціноутворення"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Tuple

from app.config.config import AppConfig

logger = logging.getLogger(__name__)


def get_surge_multiplier(city: str = "Київ", night_percent: float = 50.0) -> Tuple[float, str]:
    """
    Отримати множник підвищення та причину
    
    Args:
        city: Місто
        night_percent: % надбавки за нічний тариф (з БД)
    
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
        multiplier *= 1.3
        reasons.append("Піковий час")
    
    # 2. Нічний тариф (з БД!)
    if hour >= 23 or hour < 6:
        night_mult = 1.0 + (night_percent / 100.0)  # 50% → 1.5
        multiplier *= night_mult
        reasons.append(f"Нічний тариф (+{night_percent:.0f}%)")
    
    # 3. Вихідні (п'ятниця-неділя ввечері)
    if day_of_week >= 4 and 18 <= hour <= 23:  # Пт-Нд вечір
        multiplier *= 1.2
        reasons.append("Вихідний день")
    
    # 4. Понеділок вранці (всі поспішають)
    if day_of_week == 0 and 7 <= hour <= 10:
        multiplier *= 1.15
        reasons.append("Понеділок вранці")
    
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


def get_demand_multiplier(online_drivers_count: int, pending_orders_count: int) -> Tuple[float, str]:
    """
    Множник за попитом (мало водіїв, багато замовлень)
    """
    if online_drivers_count == 0:
        return 1.5, "Немає доступних водіїв"
    
    # Співвідношення замовлень до водіїв
    ratio = pending_orders_count / online_drivers_count if online_drivers_count > 0 else 0
    
    if ratio > 3:  # Більше 3 замовлень на водія
        return 1.4, "Дуже високий попит"
    elif ratio > 2:
        return 1.25, "Високий попит"
    elif ratio > 1.5:
        return 1.15, "Підвищений попит"
    elif ratio < 0.3:  # Мало замовлень - знижка
        return 0.9, "Низький попит (знижка -10%)"
    
    return 1.0, ""


async def calculate_dynamic_price(
    base_fare: float,
    city: str = "Київ",
    online_drivers: int = 10,
    pending_orders: int = 5,
    night_percent: float = 50.0,
    weather_percent: float = 0.0
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
    
    Returns:
        (final_price, explanation, total_multiplier)
    """
    # 1. Час доби та день тижня
    time_mult, time_reason = get_surge_multiplier(city, night_percent)
    
    # 2. Погода
    weather_mult, weather_reason = get_weather_multiplier(weather_percent)
    
    # 3. Попит
    demand_mult, demand_reason = get_demand_multiplier(online_drivers, pending_orders)
    
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
    """Отримати емодзі для відображення попиту"""
    if multiplier >= 1.5:
        return "🔥🔥🔥"
    elif multiplier >= 1.3:
        return "🔥🔥"
    elif multiplier >= 1.15:
        return "🔥"
    elif multiplier < 1.0:
        return "💚"  # Знижка
    return ""
