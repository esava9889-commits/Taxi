"""
Pytest fixtures для тестів

Тут визначаються спільні fixtures які можна використовувати в усіх тестах
"""
import pytest
import sys
import os

# Додати app до Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def sample_phone_numbers():
    """Приклади номерів телефонів для тестування"""
    return {
        "valid": [
            "+380671234567",
            "+380501234567",
            "380671234567",
            "0671234567",
            "+38 067 123 45 67",
            "+38(067)123-45-67",
        ],
        "invalid": [
            "123",
            "+38067",
            "abc",
            "+380 12",
            "++380671234567",
            "380671234567890123",  # занадто довгий
            "",
            None,
        ]
    }


@pytest.fixture
def sample_addresses():
    """Приклади адрес для тестування"""
    return {
        "valid": [
            "вул. Хрещатик, 1",
            "Київ, проспект Перемоги, 50",
            "Дніпро, вул. Набережна, 25",
            "📍 50.4501, 30.5234",
        ],
        "invalid": [
            "",
            "ab",  # занадто коротка
            "a" * 201,  # занадто довга
            "<script>alert('xss')</script>",
            "DROP TABLE users;",
            "'; DROP TABLE orders--",
        ]
    }


@pytest.fixture
def sample_card_numbers():
    """Приклади номерів банківських карток"""
    return {
        "valid": [
            "4532015112830366",  # Visa
            "5425233430109903",  # Mastercard
            "4532 0151 1283 0366",
        ],
        "invalid": [
            "1234567890123456",  # не проходить Luhn
            "123",
            "abc",
            "",
            "4532-0151-1283-0366-1234",  # занадто довгий
        ]
    }
