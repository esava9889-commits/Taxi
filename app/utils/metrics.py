"""
Система метрик для моніторингу бота

Збирає статистику:
- Кількість користувачів, водіїв, замовлень
- Середній час відповіді
- Кількість помилок
- Навантаження на бот
"""
import asyncio
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class BotMetrics:
    """Метрики бота"""
    # Час запуску
    start_time: float = 0.0
    
    # Користувачі
    total_users: int = 0
    total_drivers: int = 0
    active_drivers: int = 0
    
    # Замовлення
    total_orders: int = 0
    active_orders: int = 0
    completed_orders: int = 0
    cancelled_orders: int = 0
    
    # Продуктивність
    avg_response_time: float = 0.0
    total_requests: int = 0
    requests_per_minute: float = 0.0
    
    # Помилки
    total_errors: int = 0
    critical_errors: int = 0
    errors_per_hour: float = 0.0
    
    # Оновлення (для розрахунку requests_per_minute)
    _last_update_time: float = 0.0
    _requests_count: int = 0
    
    def __post_init__(self):
        """Ініціалізувати час запуску"""
        if self.start_time == 0.0:
            self.start_time = time.time()
        self._last_update_time = time.time()
    
    def get_uptime(self) -> str:
        """Отримати час роботи бота"""
        uptime_seconds = int(time.time() - self.start_time)
        
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        
        if days > 0:
            return f"{days}д {hours}г {minutes}хв"
        elif hours > 0:
            return f"{hours}г {minutes}хв"
        elif minutes > 0:
            return f"{minutes}хв {seconds}с"
        else:
            return f"{seconds}с"
    
    def get_uptime_seconds(self) -> int:
        """Отримати час роботи в секундах"""
        return int(time.time() - self.start_time)
    
    def update_response_time(self, duration: float):
        """
        Оновити середній час відповіді (exponential moving average)
        
        Args:
            duration: Час виконання запиту в секундах
        """
        # EMA з вагою 0.1 для нового значення
        if self.avg_response_time == 0:
            self.avg_response_time = duration
        else:
            self.avg_response_time = self.avg_response_time * 0.9 + duration * 0.1
        
        self.total_requests += 1
        self._requests_count += 1
        
        # Оновити requests_per_minute кожні 10 секунд
        current_time = time.time()
        time_diff = current_time - self._last_update_time
        
        if time_diff >= 10:  # Кожні 10 секунд
            self.requests_per_minute = (self._requests_count / time_diff) * 60
            self._last_update_time = current_time
            self._requests_count = 0
    
    def increment_errors(self, is_critical: bool = False):
        """Збільшити лічильник помилок"""
        self.total_errors += 1
        if is_critical:
            self.critical_errors += 1
        
        # Розрахувати помилки за годину
        uptime_hours = self.get_uptime_seconds() / 3600
        if uptime_hours > 0:
            self.errors_per_hour = self.total_errors / uptime_hours
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертувати в словник"""
        return {
            "uptime": self.get_uptime(),
            "uptime_seconds": self.get_uptime_seconds(),
            "users": {
                "total": self.total_users,
                "total_drivers": self.total_drivers,
                "active_drivers": self.active_drivers,
            },
            "orders": {
                "total": self.total_orders,
                "active": self.active_orders,
                "completed": self.completed_orders,
                "cancelled": self.cancelled_orders,
            },
            "performance": {
                "avg_response_time": round(self.avg_response_time, 3),
                "total_requests": self.total_requests,
                "requests_per_minute": round(self.requests_per_minute, 2),
            },
            "errors": {
                "total": self.total_errors,
                "critical": self.critical_errors,
                "per_hour": round(self.errors_per_hour, 2),
            }
        }
    
    def to_prometheus_format(self) -> str:
        """
        Конвертувати в Prometheus format (для інтеграції з моніторингом)
        
        Returns:
            Текст в форматі Prometheus metrics
        """
        metrics = []
        
        # Uptime
        metrics.append(f"# HELP bot_uptime_seconds Bot uptime in seconds")
        metrics.append(f"# TYPE bot_uptime_seconds gauge")
        metrics.append(f"bot_uptime_seconds {self.get_uptime_seconds()}")
        
        # Users
        metrics.append(f"# HELP bot_users_total Total number of users")
        metrics.append(f"# TYPE bot_users_total counter")
        metrics.append(f"bot_users_total {self.total_users}")
        
        metrics.append(f"# HELP bot_drivers_total Total number of drivers")
        metrics.append(f"# TYPE bot_drivers_total counter")
        metrics.append(f"bot_drivers_total {self.total_drivers}")
        
        metrics.append(f"# HELP bot_drivers_active Active drivers")
        metrics.append(f"# TYPE bot_drivers_active gauge")
        metrics.append(f"bot_drivers_active {self.active_drivers}")
        
        # Orders
        metrics.append(f"# HELP bot_orders_total Total number of orders")
        metrics.append(f"# TYPE bot_orders_total counter")
        metrics.append(f"bot_orders_total {self.total_orders}")
        
        metrics.append(f"# HELP bot_orders_active Active orders")
        metrics.append(f"# TYPE bot_orders_active gauge")
        metrics.append(f"bot_orders_active {self.active_orders}")
        
        metrics.append(f"# HELP bot_orders_completed Completed orders")
        metrics.append(f"# TYPE bot_orders_completed counter")
        metrics.append(f"bot_orders_completed {self.completed_orders}")
        
        # Performance
        metrics.append(f"# HELP bot_response_time_seconds Average response time")
        metrics.append(f"# TYPE bot_response_time_seconds gauge")
        metrics.append(f"bot_response_time_seconds {self.avg_response_time:.3f}")
        
        metrics.append(f"# HELP bot_requests_total Total requests")
        metrics.append(f"# TYPE bot_requests_total counter")
        metrics.append(f"bot_requests_total {self.total_requests}")
        
        metrics.append(f"# HELP bot_requests_per_minute Requests per minute")
        metrics.append(f"# TYPE bot_requests_per_minute gauge")
        metrics.append(f"bot_requests_per_minute {self.requests_per_minute:.2f}")
        
        # Errors
        metrics.append(f"# HELP bot_errors_total Total errors")
        metrics.append(f"# TYPE bot_errors_total counter")
        metrics.append(f"bot_errors_total {self.total_errors}")
        
        metrics.append(f"# HELP bot_errors_critical Critical errors")
        metrics.append(f"# TYPE bot_errors_critical counter")
        metrics.append(f"bot_errors_critical {self.critical_errors}")
        
        return "\n".join(metrics)
    
    def to_human_readable(self) -> str:
        """
        Конвертувати в людино-читабельний формат
        
        Returns:
            Форматований текст для відображення в Telegram
        """
        return f"""
📊 <b>Статистика бота</b>

⏱ <b>Час роботи:</b> {self.get_uptime()}

👥 <b>Користувачі:</b>
  • Всього: {self.total_users}
  • Водіїв: {self.total_drivers}
  • Онлайн водіїв: {self.active_drivers}

🚖 <b>Замовлення:</b>
  • Всього: {self.total_orders}
  • Активних: {self.active_orders}
  • Завершено: {self.completed_orders}
  • Скасовано: {self.cancelled_orders}

⚡ <b>Продуктивність:</b>
  • Середній час відповіді: {self.avg_response_time:.2f}с
  • Запитів всього: {self.total_requests}
  • Запитів/хвилину: {self.requests_per_minute:.1f}

❌ <b>Помилки:</b>
  • Всього: {self.total_errors}
  • Критичних: {self.critical_errors}
  • За годину: {self.errors_per_hour:.1f}
""".strip()


class MetricsCollector:
    """Збирач метрик"""
    
    def __init__(self, db_path: str):
        self.metrics = BotMetrics()
        self.db_path = db_path
        self._update_task: Optional[asyncio.Task] = None
    
    async def start_background_updates(self):
        """Запустити фонове оновлення метрик з БД"""
        self._update_task = asyncio.create_task(self._update_loop())
        logger.info("📊 Метрики: фонове оновлення запущено")
    
    async def stop_background_updates(self):
        """Зупинити фонове оновлення"""
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
            logger.info("📊 Метрики: фонове оновлення зупинено")
    
    async def _update_loop(self):
        """Оновлювати метрики кожні 30 секунд"""
        while True:
            try:
                await asyncio.sleep(30)  # Кожні 30 секунд
                await self.update_from_db()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Помилка оновлення метрик: {e}")
    
    async def update_from_db(self):
        """Оновити метрики з бази даних"""
        try:
            from app.storage.db import (
                count_users,
                count_drivers,
                count_online_drivers,
                count_orders,
                count_orders_by_status,
            )
            
            # Оновити користувачів
            self.metrics.total_users = await count_users(self.db_path)
            self.metrics.total_drivers = await count_drivers(self.db_path)
            self.metrics.active_drivers = await count_online_drivers(self.db_path)
            
            # Оновити замовлення
            self.metrics.total_orders = await count_orders(self.db_path)
            self.metrics.active_orders = await count_orders_by_status(
                self.db_path, 
                ["pending", "offered", "accepted", "in_progress"]
            )
            self.metrics.completed_orders = await count_orders_by_status(
                self.db_path, 
                ["completed"]
            )
            self.metrics.cancelled_orders = await count_orders_by_status(
                self.db_path, 
                ["cancelled"]
            )
            
            logger.debug("📊 Метрики оновлено з БД")
        
        except Exception as e:
            logger.error(f"Помилка оновлення метрик з БД: {e}")
    
    def get_metrics(self) -> BotMetrics:
        """Отримати поточні метрики"""
        return self.metrics


# Глобальний інстанс (ініціалізується в main.py)
_metrics_collector: Optional[MetricsCollector] = None


def initialize_metrics(db_path: str) -> MetricsCollector:
    """
    Ініціалізувати систему метрик
    
    Args:
        db_path: Шлях до БД
    
    Returns:
        MetricsCollector instance
    """
    global _metrics_collector
    _metrics_collector = MetricsCollector(db_path)
    logger.info("📊 Система метрик ініціалізована")
    return _metrics_collector


def get_metrics_collector() -> Optional[MetricsCollector]:
    """Отримати глобальний collector"""
    return _metrics_collector


# Middleware для вимірювання часу відповіді
async def metrics_middleware(handler, event, data):
    """
    Middleware для збору метрик продуктивності
    
    Використання:
        dp.update.middleware(metrics_middleware)
    """
    start_time = time.time()
    
    try:
        result = await handler(event, data)
        return result
    finally:
        # Виміряти час виконання
        duration = time.time() - start_time
        
        # Оновити метрики
        if _metrics_collector:
            _metrics_collector.metrics.update_response_time(duration)
