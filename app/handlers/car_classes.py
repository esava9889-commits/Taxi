"""Класифікація авто та тарифи"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Класи авто та їх коефіцієнти до тарифу
CAR_CLASSES = {
    "economy": {
        "name_uk": "🚗 Економ",
        "name_ru": "🚗 Эконом", 
        "name_en": "🚗 Economy",
        "multiplier": 1.0,  # Базовий тариф
        "description_uk": "Бюджетний варіант",
        "description_ru": "Бюджетный вариант",
        "description_en": "Budget option"
    },
    "standard": {
        "name_uk": "🚙 Стандарт",
        "name_ru": "🚙 Стандарт",
        "name_en": "🚙 Standard",
        "multiplier": 1.3,  # +30%
        "description_uk": "Комфортне авто",
        "description_ru": "Комфортное авто",
        "description_en": "Comfortable car"
    },
    "comfort": {
        "name_uk": "🚘 Комфорт",
        "name_ru": "🚘 Комфорт",
        "name_en": "🚘 Comfort",
        "multiplier": 1.6,  # +60%
        "description_uk": "Преміум клас",
        "description_ru": "Премиум класс",
        "description_en": "Premium class"
    },
    "business": {
        "name_uk": "🏆 Бізнес",
        "name_ru": "🏆 Бизнес",
        "name_en": "🏆 Business",
        "multiplier": 2.0,  # +100%
        "description_uk": "Люксовий сервіс",
        "description_ru": "Люксовый сервис",
        "description_en": "Luxury service"
    }
}


def get_car_class_name(car_class: str, lang: str = "uk") -> str:
    """Отримати назву класу авто"""
    if car_class not in CAR_CLASSES:
        return "🚗 Економ"
    
    key = f"name_{lang}"
    return CAR_CLASSES[car_class].get(key, CAR_CLASSES[car_class]["name_uk"])


def get_car_class_description(car_class: str, lang: str = "uk") -> str:
    """Отримати опис класу авто"""
    if car_class not in CAR_CLASSES:
        return ""
    
    key = f"description_{lang}"
    return CAR_CLASSES[car_class].get(key, CAR_CLASSES[car_class]["description_uk"])


def get_car_class_multiplier(car_class: str) -> float:
    """Отримати коефіцієнт класу авто"""
    if car_class not in CAR_CLASSES:
        return 1.0
    
    return CAR_CLASSES[car_class]["multiplier"]


def calculate_fare_with_class(base_fare: float, car_class: str) -> float:
    """Розрахувати вартість з урахуванням класу авто"""
    multiplier = get_car_class_multiplier(car_class)
    return base_fare * multiplier
