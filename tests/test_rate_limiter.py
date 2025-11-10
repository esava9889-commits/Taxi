"""
Тести для модуля rate_limiter.py

Перевіряють rate limiting для захисту від спаму
"""
import pytest
import time
from app.utils.rate_limiter import (
    RateLimiter,
    check_rate_limit,
    get_remaining_requests,
    get_time_until_reset,
    reset_user_limits,
    format_time_remaining,
)


class TestRateLimiter:
    """Тести класу RateLimiter"""
    
    def test_first_request_allowed(self):
        """Перший запит завжди дозволений"""
        limiter = RateLimiter()
        
        user_id = 12345
        action = "test_action"
        
        result = limiter.check_rate_limit(user_id, action, max_requests=5, window_seconds=60)
        assert result is True
    
    def test_within_limit(self):
        """Запити в межах ліміту дозволені"""
        limiter = RateLimiter()
        
        user_id = 12345
        action = "order"
        
        # Виконати 5 запитів (ліміт = 5)
        for i in range(5):
            result = limiter.check_rate_limit(user_id, action, max_requests=5, window_seconds=60)
            assert result is True, f"Запит {i+1}/5 має бути дозволений"
    
    def test_exceeds_limit(self):
        """Запити понад ліміт відхиляються"""
        limiter = RateLimiter()
        
        user_id = 12345
        action = "order"
        
        # Виконати 5 запитів (ліміт = 5)
        for i in range(5):
            limiter.check_rate_limit(user_id, action, max_requests=5, window_seconds=60)
        
        # 6-й запит має бути відхилений
        result = limiter.check_rate_limit(user_id, action, max_requests=5, window_seconds=60)
        assert result is False
    
    def test_different_users_independent(self):
        """Ліміти для різних користувачів незалежні"""
        limiter = RateLimiter()
        
        user1 = 111
        user2 = 222
        action = "order"
        
        # user1 виконує 5 запитів
        for i in range(5):
            limiter.check_rate_limit(user1, action, max_requests=5, window_seconds=60)
        
        # user2 має мати свій ліміт
        result = limiter.check_rate_limit(user2, action, max_requests=5, window_seconds=60)
        assert result is True
    
    def test_different_actions_independent(self):
        """Ліміти для різних дій незалежні"""
        limiter = RateLimiter()
        
        user_id = 12345
        
        # Вичерпати ліміт для "order"
        for i in range(5):
            limiter.check_rate_limit(user_id, "order", max_requests=5, window_seconds=60)
        
        # "accept_order" має мати свій ліміт
        result = limiter.check_rate_limit(user_id, "accept_order", max_requests=5, window_seconds=60)
        assert result is True
    
    def test_window_expiration(self):
        """Старі запити виходять з вікна"""
        limiter = RateLimiter()
        
        user_id = 12345
        action = "order"
        
        # Вичерпати ліміт
        for i in range(3):
            limiter.check_rate_limit(user_id, action, max_requests=3, window_seconds=1)
        
        # Почекати щоб вікно минуло
        time.sleep(1.1)
        
        # Тепер запит має бути дозволений
        result = limiter.check_rate_limit(user_id, action, max_requests=3, window_seconds=1)
        assert result is True
    
    def test_get_remaining_requests(self):
        """Перевірити підрахунок залишених запитів"""
        limiter = RateLimiter()
        
        user_id = 12345
        action = "order"
        max_requests = 5
        
        # Спочатку всі 5 доступні
        remaining = limiter.get_remaining_requests(user_id, action, max_requests, window_seconds=60)
        assert remaining == 5
        
        # Після 2 запитів - залишилось 3
        limiter.check_rate_limit(user_id, action, max_requests, window_seconds=60)
        limiter.check_rate_limit(user_id, action, max_requests, window_seconds=60)
        
        remaining = limiter.get_remaining_requests(user_id, action, max_requests, window_seconds=60)
        assert remaining == 3
    
    def test_reset_user_limits(self):
        """Перевірити скидання лімітів"""
        limiter = RateLimiter()
        
        user_id = 12345
        action = "order"
        
        # Вичерпати ліміт
        for i in range(5):
            limiter.check_rate_limit(user_id, action, max_requests=5, window_seconds=60)
        
        # Перевірити що ліміт вичерпано
        result = limiter.check_rate_limit(user_id, action, max_requests=5, window_seconds=60)
        assert result is False
        
        # Скинути ліміт
        limiter.reset_user_limits(user_id, action)
        
        # Тепер запит має бути дозволений
        result = limiter.check_rate_limit(user_id, action, max_requests=5, window_seconds=60)
        assert result is True
    
    def test_get_time_until_reset(self):
        """Перевірити підрахунок часу до скидання"""
        limiter = RateLimiter()
        
        user_id = 12345
        action = "order"
        window_seconds = 10
        
        # Виконати запит
        limiter.check_rate_limit(user_id, action, max_requests=5, window_seconds=window_seconds)
        
        # Час до скидання має бути ~10 секунд
        time_until_reset = limiter.get_time_until_reset(user_id, action, window_seconds=window_seconds)
        assert 9 <= time_until_reset <= 10


class TestGlobalRateLimiter:
    """Тести глобального rate limiter"""
    
    def test_global_check_rate_limit(self):
        """Перевірити глобальну функцію check_rate_limit"""
        user_id = 99999
        action = "test_global"
        
        result = check_rate_limit(user_id, action, max_requests=3, window_seconds=60)
        assert result is True
    
    def test_global_get_remaining_requests(self):
        """Перевірити глобальну функцію get_remaining_requests"""
        user_id = 99998
        action = "test_global_remaining"
        max_requests = 5
        
        # Виконати 2 запити
        check_rate_limit(user_id, action, max_requests, window_seconds=60)
        check_rate_limit(user_id, action, max_requests, window_seconds=60)
        
        remaining = get_remaining_requests(user_id, action, max_requests, window_seconds=60)
        assert remaining == 3
    
    def test_global_reset_user_limits(self):
        """Перевірити глобальну функцію reset_user_limits"""
        user_id = 99997
        action = "test_reset"
        
        # Вичерпати ліміт
        for i in range(3):
            check_rate_limit(user_id, action, max_requests=3, window_seconds=60)
        
        # Скинути
        reset_user_limits(user_id, action)
        
        # Перевірити що ліміт скинуто
        result = check_rate_limit(user_id, action, max_requests=3, window_seconds=60)
        assert result is True


class TestFormatTimeRemaining:
    """Тести форматування часу"""
    
    def test_format_seconds(self):
        """Форматування секунд"""
        assert format_time_remaining(30) == "30 сек"
        assert format_time_remaining(45) == "45 сек"
    
    def test_format_minutes(self):
        """Форматування хвилин"""
        assert format_time_remaining(60) == "1 хв"
        assert format_time_remaining(120) == "2 хв"
        assert format_time_remaining(90) == "1 хв"
    
    def test_format_hours(self):
        """Форматування годин"""
        assert format_time_remaining(3600) == "1 год"
        assert format_time_remaining(7200) == "2 год"
        assert format_time_remaining(3660) == "1 год 1 хв"
        assert format_time_remaining(7320) == "2 год 2 хв"
    
    def test_format_edge_cases(self):
        """Граничні випадки"""
        assert format_time_remaining(0) == "0 сек"
        assert format_time_remaining(59) == "59 сек"
        assert format_time_remaining(3599) == "59 хв"
