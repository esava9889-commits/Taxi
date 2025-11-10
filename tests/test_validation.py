"""
Тести для модуля validation.py

Перевіряють валідацію телефонів, адрес, імен, коментарів, номерів карток
"""
import pytest
from app.utils.validation import (
    validate_phone_number,
    validate_address,
    validate_name,
    validate_comment,
    validate_card_number,
    validate_car_plate,
    sanitize_html,
)


class TestPhoneValidation:
    """Тести валідації телефонів"""
    
    def test_valid_phone_numbers(self, sample_phone_numbers):
        """Перевірити що валідні номери приймаються"""
        for phone in sample_phone_numbers["valid"]:
            valid, cleaned = validate_phone_number(phone)
            assert valid, f"Номер {phone} має бути валідним"
            assert cleaned is not None
            assert cleaned.startswith("+38")
    
    def test_invalid_phone_numbers(self, sample_phone_numbers):
        """Перевірити що невалідні номери відхиляються"""
        for phone in sample_phone_numbers["invalid"]:
            valid, cleaned = validate_phone_number(phone)
            assert not valid, f"Номер {phone} має бути невалідним"
            assert cleaned is None
    
    def test_phone_normalization(self):
        """Перевірити нормалізацію номерів"""
        # 0671234567 → +380671234567
        valid, cleaned = validate_phone_number("0671234567")
        assert valid
        assert cleaned == "+380671234567"
        
        # +380671234567 залишається без змін
        valid, cleaned = validate_phone_number("+380671234567")
        assert valid
        assert cleaned == "+380671234567"
    
    def test_phone_sql_injection(self):
        """Перевірити захист від SQL injection"""
        malicious_phones = [
            "'; DROP TABLE users--",
            "123'; DELETE FROM orders--",
            "<script>alert('xss')</script>",
        ]
        
        for phone in malicious_phones:
            valid, cleaned = validate_phone_number(phone)
            assert not valid, f"Зловмисний номер {phone} має бути відхилений"


class TestAddressValidation:
    """Тести валідації адрес"""
    
    def test_valid_addresses(self, sample_addresses):
        """Перевірити що валідні адреси приймаються"""
        for address in sample_addresses["valid"]:
            valid, cleaned = validate_address(address)
            assert valid, f"Адреса {address} має бути валідною"
            assert cleaned is not None
    
    def test_invalid_addresses(self, sample_addresses):
        """Перевірити що невалідні адреси відхиляються"""
        for address in sample_addresses["invalid"]:
            valid, cleaned = validate_address(address)
            assert not valid, f"Адреса {address} має бути невалідною"
    
    def test_address_length_limits(self):
        """Перевірити обмеження довжини адреси"""
        # Занадто коротка
        valid, _ = validate_address("ab")
        assert not valid
        
        # Занадто довга
        valid, _ = validate_address("a" * 201)
        assert not valid
        
        # Нормальна довжина
        valid, _ = validate_address("Київ, вул. Хрещатик, 1")
        assert valid
    
    def test_address_sql_injection(self):
        """Перевірити захист від SQL injection"""
        malicious = [
            "'; DROP TABLE orders--",
            "union select * from users",
            "/* comment */ DROP TABLE",
        ]
        
        for address in malicious:
            valid, _ = validate_address(address)
            assert not valid


class TestNameValidation:
    """Тести валідації імен"""
    
    def test_valid_names(self):
        """Перевірити що валідні імена приймаються"""
        valid_names = [
            "Іван",
            "Іван Петрович",
            "John Doe",
            "Марія-Олена",
        ]
        
        for name in valid_names:
            valid, cleaned = validate_name(name)
            assert valid, f"Ім'я {name} має бути валідним"
            assert cleaned is not None
    
    def test_invalid_names(self):
        """Перевірити що невалідні імена відхиляються"""
        invalid_names = [
            "",
            "a",  # занадто коротке
            "123",  # тільки цифри
            "a" * 101,  # занадто довге
            "<script>",
            "'; DROP TABLE",
        ]
        
        for name in invalid_names:
            valid, _ = validate_name(name)
            assert not valid, f"Ім'я {name} має бути невалідним"
    
    def test_name_requires_letters(self):
        """Перевірити що ім'я містить букви"""
        # Тільки цифри - невалідно
        valid, _ = validate_name("123456")
        assert not valid
        
        # Букви + цифри - валідно
        valid, _ = validate_name("Іван123")
        assert valid


class TestCommentValidation:
    """Тести валідації коментарів"""
    
    def test_comment_optional(self):
        """Перевірити що коментар опціональний"""
        valid, cleaned = validate_comment("")
        assert valid
        assert cleaned is None
        
        valid, cleaned = validate_comment(None)
        assert valid
        assert cleaned is None
    
    def test_valid_comments(self):
        """Перевірити валідні коментарі"""
        comments = [
            "Будь ласка, зателефонуйте за 5 хвилин",
            "Зустріч біля головного входу",
            "Маю багаж",
        ]
        
        for comment in comments:
            valid, cleaned = validate_comment(comment)
            assert valid
            assert cleaned is not None
    
    def test_comment_length_limit(self):
        """Перевірити ліміт довжини коментаря"""
        # Нормальний
        valid, _ = validate_comment("Звичайний коментар")
        assert valid
        
        # Занадто довгий (>500 символів)
        valid, _ = validate_comment("a" * 501)
        assert not valid
    
    def test_comment_sql_injection(self):
        """Перевірити захист від SQL injection в коментарях"""
        malicious = [
            "'; DROP TABLE orders--",
            "union select",
        ]
        
        for comment in malicious:
            valid, _ = validate_comment(comment)
            assert not valid


class TestCardNumberValidation:
    """Тести валідації номерів карток"""
    
    def test_valid_card_numbers(self, sample_card_numbers):
        """Перевірити валідні номери карток"""
        for card in sample_card_numbers["valid"]:
            valid, formatted = validate_card_number(card)
            assert valid, f"Картка {card} має бути валідною"
            assert formatted is not None
    
    def test_invalid_card_numbers(self, sample_card_numbers):
        """Перевірити невалідні номери карток"""
        for card in sample_card_numbers["invalid"]:
            valid, _ = validate_card_number(card)
            assert not valid, f"Картка {card} має бути невалідною"
    
    def test_card_formatting(self):
        """Перевірити форматування номера картки"""
        valid, formatted = validate_card_number("4532015112830366")
        assert valid
        assert formatted == "4532 0151 1283 0366"
    
    def test_luhn_algorithm(self):
        """Перевірити алгоритм Луна"""
        # Валідний номер (пройде Luhn)
        valid, _ = validate_card_number("4532015112830366")
        assert valid
        
        # Невалідний номер (не пройде Luhn)
        valid, _ = validate_card_number("1234567890123456")
        assert not valid


class TestCarPlateValidation:
    """Тести валідації номерних знаків"""
    
    def test_valid_car_plates(self):
        """Перевірити валідні номерні знаки"""
        valid_plates = [
            "AA1234BB",
            "AI5678CD",
            "AB 1234 CC",
        ]
        
        for plate in valid_plates:
            valid, cleaned = validate_car_plate(plate)
            assert valid, f"Номер {plate} має бути валідним"
    
    def test_invalid_car_plates(self):
        """Перевірити невалідні номерні знаки"""
        invalid_plates = [
            "",
            "AB",  # занадто короткий
            "ABC123456789",  # занадто довгий
            "'; DROP TABLE",
        ]
        
        for plate in invalid_plates:
            valid, _ = validate_car_plate(plate)
            assert not valid


class TestHtmlSanitization:
    """Тести санітизації HTML"""
    
    def test_remove_html_tags(self):
        """Перевірити видалення HTML тегів"""
        text = "<b>Bold</b> and <i>italic</i>"
        cleaned = sanitize_html(text)
        assert cleaned == "Bold and italic"
    
    def test_html_entities(self):
        """Перевірити заміну HTML entities"""
        text = "&lt;script&gt;alert('xss')&lt;/script&gt;"
        cleaned = sanitize_html(text)
        assert "<script>" in cleaned
        assert "&lt;" not in cleaned
    
    def test_empty_input(self):
        """Перевірити обробку порожнього вводу"""
        assert sanitize_html("") == ""
        assert sanitize_html(None) == ""
