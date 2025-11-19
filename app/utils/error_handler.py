"""
Централізована система обробки помилок для бота

Можливості:
- Класифікація помилок по важливості
- Автоматичне логування з контекстом
- Сповіщення адміна про критичні помилки
- Збір статистики помилок
"""
import logging
import traceback
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Рівні важливості помилок"""
    LOW = "🟢"        # Не критично, просто інформація
    MEDIUM = "🟡"     # Потрібна увага, але не критично
    HIGH = "🟠"       # Серйозна помилка, потрібно виправити
    CRITICAL = "🔴"   # Критична помилка, бот може не працювати


@dataclass
class ErrorContext:
    """Контекст помилки для детального логування"""
    user_id: Optional[int] = None
    chat_id: Optional[int] = None
    handler: Optional[str] = None
    state: Optional[str] = None
    message_text: Optional[str] = None
    callback_data: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертувати в словник для логування"""
        return {
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "handler": self.handler,
            "state": self.state,
            "message_text": self.message_text,
            "callback_data": self.callback_data,
            **self.extra
        }


class ErrorStats:
    """Статистика помилок"""
    def __init__(self):
        self.errors: Dict[str, int] = {}  # {error_type: count}
        self.last_errors: list = []  # Останні 100 помилок
        self.total_errors: int = 0
        self.critical_errors: int = 0
    
    def add_error(self, error_type: str, severity: ErrorSeverity):
        """Додати помилку до статистики"""
        self.errors[error_type] = self.errors.get(error_type, 0) + 1
        self.total_errors += 1
        
        if severity == ErrorSeverity.CRITICAL:
            self.critical_errors += 1
        
        # Зберегти останні помилки (макс 100)
        self.last_errors.append({
            "type": error_type,
            "severity": severity.name,
            "timestamp": datetime.now().isoformat()
        })
        if len(self.last_errors) > 100:
            self.last_errors.pop(0)
    
    def get_stats(self) -> Dict[str, Any]:
        """Отримати статистику"""
        return {
            "total_errors": self.total_errors,
            "critical_errors": self.critical_errors,
            "errors_by_type": self.errors,
            "last_10_errors": self.last_errors[-10:]
        }


# Глобальний інстанс статистики
error_stats = ErrorStats()


def classify_error(e: Exception) -> ErrorSeverity:
    """
    Автоматично визначити важливість помилки
    
    Args:
        e: Exception об'єкт
    
    Returns:
        ErrorSeverity рівень
    """
    error_message = str(e).lower()
    error_type = type(e).__name__
    
    # КРИТИЧНІ помилки (бот може не працювати)
    critical_patterns = [
        "database",
        "connection",
        "asyncpg",
        "sqlite",
        "pool",
        "authentication",
        "token",
    ]
    
    for pattern in critical_patterns:
        if pattern in error_message or pattern in error_type.lower():
            return ErrorSeverity.CRITICAL
    
    # ВИСОКІ помилки (щось пішло не так, але бот працює)
    high_patterns = [
        "conflict",
        "timeout",
        "api",
        "network",
        "permission",
    ]
    
    for pattern in high_patterns:
        if pattern in error_message:
            return ErrorSeverity.HIGH
    
    # СЕРЕДНІ помилки (очікувані помилки користувача)
    medium_patterns = [
        "validation",
        "invalid",
        "not found",
        "bad request",
    ]
    
    for pattern in medium_patterns:
        if pattern in error_message:
            return ErrorSeverity.MEDIUM
    
    # НИЗЬКІ помилки (не критичні, просто інформація)
    low_patterns = [
        "message is not modified",
        "message can't be deleted",
        "message to delete not found",
        "chat not found",
        "blocked",
    ]
    
    for pattern in low_patterns:
        if pattern in error_message:
            return ErrorSeverity.LOW
    
    # За замовчуванням - середня важливість
    return ErrorSeverity.MEDIUM


async def handle_error(
    e: Exception,
    context: Optional[ErrorContext] = None,
    bot = None
) -> None:
    """
    Централізована обробка помилок
    
    Args:
        e: Exception що стався
        context: Контекст помилки (користувач, хендлер, тощо)
        bot: Bot instance для сповіщень адміна
    """
    # Визначити важливість
    severity = classify_error(e)
    
    # Отримати тип помилки
    error_type = type(e).__name__
    
    # Додати до статистики
    error_stats.add_error(error_type, severity)
    
    # Підготувати контекст для логування
    context_dict = context.to_dict() if context else {}
    
    # Логування залежно від важливості
    log_level = logging.ERROR if severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL] else logging.WARNING
    
    log_message = f"{severity.value} [{error_type}] {e}"
    
    # Логувати з контекстом
    extra = {
        "severity": severity.name,
        "error_type": error_type,
        **context_dict
    }
    
    logger.log(log_level, log_message, extra=extra)
    
    # Для критичних та високих помилок - детальний traceback
    if severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
        logger.error(f"📜 Traceback:\n{traceback.format_exc()}")
    
    # Сповістити адміна про критичні помилки
    if severity == ErrorSeverity.CRITICAL and bot:
        await notify_admin_about_critical_error(bot, e, context)


async def notify_admin_about_critical_error(
    bot,
    e: Exception,
    context: Optional[ErrorContext] = None
) -> None:
    """
    Сповістити адміна про критичну помилку
    
    Args:
        bot: Bot instance
        e: Exception
        context: Контекст помилки
    """
    try:
        from app.config.config import load_config
        
        config = load_config()
        
        # Підготувати повідомлення
        message = f"""
🔴 <b>КРИТИЧНА ПОМИЛКА В БОТІ</b>

<b>Тип:</b> {type(e).__name__}
<b>Повідомлення:</b> {str(e)[:200]}

<b>Час:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        # Додати контекст якщо є
        if context:
            if context.user_id:
                message += f"\n<b>Користувач:</b> {context.user_id}"
            if context.handler:
                message += f"\n<b>Хендлер:</b> {context.handler}"
            if context.state:
                message += f"\n<b>Стан:</b> {context.state}"
        
        message += f"\n\n<code>{traceback.format_exc()[:500]}</code>"
        
        # Відправити всім адмінам
        for admin_id in config.bot.admin_ids:
            try:
                await bot.send_message(admin_id, message, parse_mode="HTML")
            except Exception as notify_error:
                logger.error(f"Не вдалося сповістити адміна {admin_id}: {notify_error}")
    
    except Exception as notify_error:
        logger.error(f"Помилка при сповіщенні адміна: {notify_error}")


def get_error_stats() -> Dict[str, Any]:
    """Отримати статистику помилок"""
    return error_stats.get_stats()


# Middleware для aiogram
async def error_middleware(handler, event, data):
    """
    Middleware для автоматичної обробки помилок в хендлерах
    
    Використання:
        dp.update.middleware(error_middleware)
    """
    try:
        return await handler(event, data)
    except Exception as e:
        # Витягти контекст з event
        context = ErrorContext()
        
        # Спробувати отримати інформацію про користувача
        if hasattr(event, 'from_user') and event.from_user:
            context.user_id = event.from_user.id
        
        if hasattr(event, 'chat') and event.chat:
            context.chat_id = event.chat.id
        
        if hasattr(event, 'message') and event.message:
            if hasattr(event.message, 'text'):
                context.message_text = event.message.text[:100]
        
        if hasattr(event, 'data'):
            context.callback_data = str(event.data)[:50]
        
        # Отримати назву хендлера
        if hasattr(handler, '__name__'):
            context.handler = handler.__name__
        
        # Обробити помилку
        bot = data.get('bot')
        await handle_error(e, context, bot)
        
        # Не re-raise для некритичних помилок
        severity = classify_error(e)
        if severity != ErrorSeverity.LOW:
            raise
