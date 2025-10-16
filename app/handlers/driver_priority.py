"""Пріоритет водіїв за рейтингом"""
from __future__ import annotations

import logging
from typing import List, Tuple

from app.storage.db import Driver, get_driver_average_rating

logger = logging.getLogger(__name__)


async def sort_drivers_by_priority(db_path: str, drivers: List[Driver]) -> List[Tuple[Driver, float]]:
    """
    Сортувати водіїв за пріоритетом (рейтинг + інші фактори)
    
    Returns:
        List[(Driver, priority_score)]
    """
    driver_scores = []
    
    for driver in drivers:
        score = 0.0
        
        # 1. Рейтинг (найважливіше) - від 0 до 100 балів
        rating = await get_driver_average_rating(db_path, driver.tg_user_id)
        if rating:
            score += rating * 20  # 5 зірок = 100 балів
        else:
            score += 80  # Новий водій - середній пріоритет
        
        # 2. Онлайн статус (обов'язково)
        if driver.online:
            score += 50
        
        # 3. Наявність локації
        if driver.last_lat and driver.last_lon:
            score += 20
        
        # 4. Клас авто (вищий клас = вищий пріоритет)
        class_bonus = {
            "economy": 0,
            "standard": 10,
            "comfort": 20,
            "business": 30
        }
        score += class_bonus.get(driver.car_class, 0)
        
        driver_scores.append((driver, score))
    
    # Сортувати за спаданням балів
    driver_scores.sort(key=lambda x: x[1], reverse=True)
    
    logger.info(f"Drivers sorted by priority: {[(d.id, s) for d, s in driver_scores[:5]]}")
    
    return driver_scores


async def get_top_drivers(db_path: str, drivers: List[Driver], limit: int = 5) -> List[Driver]:
    """
    Отримати топ водіїв за пріоритетом
    
    Args:
        db_path: Шлях до БД
        drivers: Список водіїв
        limit: Кількість топ водіїв
    
    Returns:
        List[Driver] - топ водіїв
    """
    sorted_drivers = await sort_drivers_by_priority(db_path, drivers)
    return [driver for driver, score in sorted_drivers[:limit]]


async def filter_high_rating_drivers(db_path: str, drivers: List[Driver], min_rating: float = 4.5) -> List[Driver]:
    """
    Фільтрувати водіїв з високим рейтингом
    
    Args:
        min_rating: Мінімальний рейтинг (за замовчуванням 4.5)
    """
    high_rated = []
    
    for driver in drivers:
        rating = await get_driver_average_rating(db_path, driver.tg_user_id)
        if rating and rating >= min_rating:
            high_rated.append(driver)
        elif not rating:  # Новий водій - додаємо
            high_rated.append(driver)
    
    return high_rated
