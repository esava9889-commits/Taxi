"""Rate limiting для захисту від спаму та зловживань"""
import time
from typing import Dict, Tuple
from datetime import datetime, timedelta


class RateLimiter:
    """
    Простий rate limiter на основі sliding window.
    
    Використання:
        limiter = RateLimiter()
        
        if not limiter.check_rate_limit(user_id, "order", max_requests=5, window_seconds=3600):
            # Користувач перевищив ліміт
            return "Забагато запитів. Спробуйте пізніше."
    """
    
    def __init__(self):
        # Формат: {(user_id, action): [(timestamp1, timestamp2, ...)]}
        self._requests: Dict[Tuple[int, str], list] = {}
        self._cleanup_interval = 3600  # Очищати старі дані кожну годину
        self._last_cleanup = time.time()
    
    def check_rate_limit(
        self,
        user_id: int,
        action: str,
        max_requests: int,
        window_seconds: int = 3600
    ) -> bool:
        """
        Перевірити чи користувач не перевищив ліміт.
        
        Args:
            user_id: ID користувача
            action: Назва дії (наприклад, "order", "accept_order")
            max_requests: Максимальна кількість запитів за вікно
            window_seconds: Розмір вікна в секундах (за замовчуванням 1 година)
        
        Returns:
            True якщо запит дозволений, False якщо ліміт перевищено
        """
        current_time = time.time()
        key = (user_id, action)
        
        # Періодично очищати старі дані
        if current_time - self._last_cleanup > self._cleanup_interval:
            self._cleanup_old_requests(current_time)
            self._last_cleanup = current_time
        
        # Отримати список запитів для цього користувача та дії
        if key not in self._requests:
            self._requests[key] = []
        
        requests = self._requests[key]
        
        # Видалити запити старіші за вікно
        cutoff_time = current_time - window_seconds
        requests = [t for t in requests if t > cutoff_time]
        self._requests[key] = requests
        
        # Перевірити чи не перевищено ліміт
        if len(requests) >= max_requests:
            return False
        
        # Додати поточний запит
        requests.append(current_time)
        
        return True
    
    def get_remaining_requests(
        self,
        user_id: int,
        action: str,
        max_requests: int,
        window_seconds: int = 3600
    ) -> int:
        """
        Отримати кількість залишених запитів.
        
        Returns:
            Кількість запитів що залишилась до ліміту
        """
        current_time = time.time()
        key = (user_id, action)
        
        if key not in self._requests:
            return max_requests
        
        requests = self._requests[key]
        cutoff_time = current_time - window_seconds
        recent_requests = [t for t in requests if t > cutoff_time]
        
        return max(0, max_requests - len(recent_requests))
    
    def get_time_until_reset(
        self,
        user_id: int,
        action: str,
        window_seconds: int = 3600
    ) -> int:
        """
        Отримати час до скидання ліміту (в секундах).
        
        Returns:
            Кількість секунд до моменту коли найстаріший запит вийде з вікна
        """
        current_time = time.time()
        key = (user_id, action)
        
        if key not in self._requests or not self._requests[key]:
            return 0
        
        requests = self._requests[key]
        cutoff_time = current_time - window_seconds
        recent_requests = [t for t in requests if t > cutoff_time]
        
        if not recent_requests:
            return 0
        
        oldest_request = min(recent_requests)
        time_until_expire = window_seconds - (current_time - oldest_request)
        
        return max(0, int(time_until_expire))
    
    def reset_user_limits(self, user_id: int, action: str = None) -> None:
        """
        Скинути ліміти для користувача.
        
        Args:
            user_id: ID користувача
            action: Назва дії (якщо None - скинути всі дії)
        """
        if action:
            key = (user_id, action)
            if key in self._requests:
                del self._requests[key]
        else:
            # Скинути всі дії для цього користувача
            keys_to_delete = [k for k in self._requests.keys() if k[0] == user_id]
            for key in keys_to_delete:
                del self._requests[key]
    
    def _cleanup_old_requests(self, current_time: float) -> None:
        """
        Видалити старі запити для звільнення пам'яті.
        
        Args:
            current_time: Поточний час
        """
        # Видалити всі запити старіші за 24 години
        cutoff = current_time - 86400  # 24 години
        
        for key in list(self._requests.keys()):
            requests = self._requests[key]
            requests = [t for t in requests if t > cutoff]
            
            if not requests:
                # Видалити ключ якщо немає запитів
                del self._requests[key]
            else:
                self._requests[key] = requests


# Глобальний екземпляр rate limiter
_global_rate_limiter = RateLimiter()


def check_rate_limit(
    user_id: int,
    action: str,
    max_requests: int,
    window_seconds: int = 3600
) -> bool:
    """
    Перевірити rate limit через глобальний екземпляр.
    
    Args:
        user_id: ID користувача
        action: Назва дії
        max_requests: Максимальна кількість запитів
        window_seconds: Розмір вікна в секундах
    
    Returns:
        True якщо запит дозволений, False якщо ліміт перевищено
    """
    return _global_rate_limiter.check_rate_limit(
        user_id, action, max_requests, window_seconds
    )


def get_remaining_requests(
    user_id: int,
    action: str,
    max_requests: int,
    window_seconds: int = 3600
) -> int:
    """Отримати кількість залишених запитів"""
    return _global_rate_limiter.get_remaining_requests(
        user_id, action, max_requests, window_seconds
    )


def get_time_until_reset(
    user_id: int,
    action: str,
    window_seconds: int = 3600
) -> int:
    """Отримати час до скидання ліміту"""
    return _global_rate_limiter.get_time_until_reset(
        user_id, action, window_seconds
    )


def reset_user_limits(user_id: int, action: str = None) -> None:
    """Скинути ліміти для користувача"""
    _global_rate_limiter.reset_user_limits(user_id, action)


def format_time_remaining(seconds: int) -> str:
    """
    Форматувати час у зручний для читання вигляд.
    
    Args:
        seconds: Кількість секунд
    
    Returns:
        Відформатований рядок (наприклад, "15 хв", "2 год")
    """
    if seconds < 60:
        return f"{seconds} сек"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} хв"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes > 0:
            return f"{hours} год {minutes} хв"
        return f"{hours} год"
