"""
Модуль з візуальними покращеннями для Telegram бота
Містить функції для красивого форматування повідомлень
"""
from typing import Optional


# ============ КОЛЬОРОВІ ЕМОДЗІ ДЛЯ СТАТУСІВ ============

def get_status_emoji(status: str) -> str:
    """
    Повертає кольорове емодзі для статусу замовлення
    
    Args:
        status: Статус замовлення
        
    Returns:
        Емодзі зі статусом
    """
    status_map = {
        'pending': '🔵',       # Синій = очікує
        'accepted': '🟢',      # Зелений = прийнято
        'in_progress': '🟡',   # Жовтий = в дорозі
        'completed': '⚪',     # Білий = завершено
        'cancelled': '🔴',     # Червоний = скасовано
        'searching': '🔵',     # Синій = пошук водія
    }
    return status_map.get(status, '⚫')


def get_status_text_with_emoji(status: str) -> str:
    """
    Повертає текст статусу з кольоровим емодзі
    
    Args:
        status: Статус замовлення
        
    Returns:
        Форматований текст статусу
    """
    emoji = get_status_emoji(status)
    status_texts = {
        'pending': f'{emoji} Очікує водія',
        'accepted': f'{emoji} Водій прийняв',
        'in_progress': f'{emoji} Водій їде',
        'completed': f'{emoji} Завершено',
        'cancelled': f'{emoji} Скасовано',
        'searching': f'{emoji} Пошук водія',
    }
    return status_texts.get(status, f'{emoji} {status}')


# ============ КАРМА З КОЛЬОРАМИ ============

def get_karma_emoji(karma: int) -> str:
    """
    Повертає кольорове емодзі для рівня карми
    
    Args:
        karma: Значення карми (0-100)
        
    Returns:
        Кольорове серце
    """
    if karma >= 90:
        return '💚'  # Зелене серце - відмінно
    elif karma >= 70:
        return '💛'  # Жовте серце - добре
    elif karma >= 50:
        return '🧡'  # Помаранчеве серце - середньо
    else:
        return '❤️'  # Червоне серце - низько


def format_karma(karma: int) -> str:
    """
    Форматує карму з кольоровим емодзі та прогрес-баром
    
    Args:
        karma: Значення карми (0-100)
        
    Returns:
        Форматована карма
    """
    emoji = get_karma_emoji(karma)
    bar = create_progress_bar(karma, 100, length=10)
    return f"{emoji} Карма: {bar} {karma}/100"


def get_karma_level_text(karma: int) -> str:
    """
    Повертає текстовий опис рівня карми
    
    Args:
        karma: Значення карми (0-100)
        
    Returns:
        Опис рівня
    """
    if karma >= 90:
        return "Ідеально"
    elif karma >= 70:
        return "Добре"
    elif karma >= 50:
        return "Середньо"
    else:
        return "Потребує покращення"


# ============ ПРОГРЕС-БАРИ ============

def create_progress_bar(value: int, max_value: int, length: int = 10, filled_char: str = '▓', empty_char: str = '░') -> str:
    """
    Створює візуальний прогрес-бар
    
    Args:
        value: Поточне значення
        max_value: Максимальне значення
        length: Довжина бару
        filled_char: Символ заповненої частини
        empty_char: Символ порожньої частини
        
    Returns:
        Прогрес-бар
    """
    if max_value == 0:
        return empty_char * length
    
    filled = int((value / max_value) * length)
    filled = max(0, min(filled, length))  # Обмежити від 0 до length
    return filled_char * filled + empty_char * (length - filled)


def create_earnings_bar(cash: float, card: float, length: int = 10) -> tuple[str, str]:
    """
    Створює прогрес-бари для готівки та картки
    
    Args:
        cash: Сума готівкою
        card: Сума карткою
        length: Довжина барів
        
    Returns:
        Tuple (cash_bar, card_bar)
    """
    total = cash + card
    if total == 0:
        return ('░' * length, '░' * length)
    
    cash_bar = create_progress_bar(int(cash), int(total), length)
    card_bar = create_progress_bar(int(card), int(total), length)
    
    return (cash_bar, card_bar)


# ============ АНІМОВАНІ ЕМОДЗІ ДЛЯ ПРОЦЕСІВ ============

def get_process_emoji(process_type: str) -> str:
    """
    Повертає анімоване емодзі для процесу
    
    Args:
        process_type: Тип процесу
        
    Returns:
        Емодзі процесу
    """
    process_map = {
        'searching': '🔍',      # Пошук водія
        'calculating': '⚡',    # Розрахунок маршруту
        'processing': '🔄',    # Обробка замовлення
        'waiting': '⏳',       # Очікування
        'loading': '⏳',       # Завантаження
        'geocoding': '🗺️',    # Геокодування
    }
    return process_map.get(process_type, '⏳')


def format_process_message(process_type: str, message: str) -> str:
    """
    Форматує повідомлення процесу з емодзі
    
    Args:
        process_type: Тип процесу
        message: Текст повідомлення
        
    Returns:
        Форматоване повідомлення
    """
    emoji = get_process_emoji(process_type)
    return f"{emoji} {message}"


# ============ КАРТОЧКИ З РАМКАМИ ============

def create_box(title: str, content: str, width: int = 25) -> str:
    """
    Створює карточку з рамкою навколо контенту
    
    Args:
        title: Заголовок карточки
        content: Вміст карточки
        width: Ширина карточки
        
    Returns:
        Форматована карточка
    """
    # Адаптувати ширину під контент
    lines = content.split('\n')
    max_content_len = max(len(line) for line in lines) if lines else 0
    actual_width = max(width, max_content_len + 4, len(title) + 4)
    
    # Верхня рамка з заголовком
    top = f"┏{'━' * (actual_width - 2)}┓\n"
    
    # Заголовок (центрований)
    title_padding = actual_width - len(title) - 2
    left_pad = title_padding // 2
    right_pad = title_padding - left_pad
    header = f"┃{' ' * left_pad}{title}{' ' * right_pad}┃\n"
    
    # Роздільник
    separator = f"┣{'━' * (actual_width - 2)}┫\n"
    
    # Контент
    content_lines = []
    for line in lines:
        padding = actual_width - len(line) - 2
        content_lines.append(f"┃ {line}{' ' * padding}┃\n")
    
    # Нижня рамка
    bottom = f"┗{'━' * (actual_width - 2)}┛"
    
    return top + header + separator + ''.join(content_lines) + bottom


def create_simple_box(content: str, width: int = 25) -> str:
    """
    Створює просту карточку без заголовка
    
    Args:
        content: Вміст карточки
        width: Ширина карточки
        
    Returns:
        Форматована карточка
    """
    lines = content.split('\n')
    max_content_len = max(len(line) for line in lines) if lines else 0
    actual_width = max(width, max_content_len + 4)
    
    # Верхня рамка
    top = f"┏{'━' * (actual_width - 2)}┓\n"
    
    # Контент
    content_lines = []
    for line in lines:
        padding = actual_width - len(line) - 2
        content_lines.append(f"┃ {line}{' ' * padding}┃\n")
    
    # Нижня рамка
    bottom = f"┗{'━' * (actual_width - 2)}┛"
    
    return top + ''.join(content_lines) + bottom


def create_section_divider(title: Optional[str] = None, width: int = 30) -> str:
    """
    Створює роздільник секцій
    
    Args:
        title: Опціональний заголовок секції
        width: Ширина роздільника
        
    Returns:
        Форматований роздільник
    """
    if title:
        # Центрувати заголовок
        title_with_spaces = f" {title} "
        padding = width - len(title_with_spaces)
        left_pad = padding // 2
        right_pad = padding - left_pad
        return f"{'━' * left_pad}{title_with_spaces}{'━' * right_pad}"
    else:
        return '━' * width


# ============ ФОРМАТУВАННЯ ЗАРОБІТКУ (ІНФОГРАФІКА) ============

def format_earnings_infographic(
    total: float,
    cash: float,
    card: float,
    commission: float,
    trips_count: int,
    hours_worked: float
) -> str:
    """
    Створює інфографіку заробітку для водія
    
    Args:
        total: Загальний заробіток
        cash: Готівка
        card: Картка
        commission: Комісія
        trips_count: Кількість поїздок
        hours_worked: Відпрацьовано годин
        
    Returns:
        Форматована інфографіка
    """
    net = total - commission
    
    # Прогрес-бари для готівки та картки
    cash_bar, card_bar = create_earnings_bar(cash, card, length=10)
    
    # Середній заробіток за годину
    per_hour = net / hours_worked if hours_worked > 0 else 0
    
    # Формування інфографіки
    infographic = f"""📊 <b>ЗАРОБІТОК СЬОГОДНІ</b>

💰 <b>Загальний:</b>     {total:>7.0f} грн
{create_section_divider(width=25)}
💵 Готівка:        {cash:>7.0f} грн {cash_bar}
💳 Картка:         {card:>7.0f} грн {card_bar}
{create_section_divider(width=25)}
📉 Комісія:        {commission:>7.0f} грн
{create_section_divider(width=25)}
✅ <b>Чистий:</b>       {net:>7.0f} грн

🚕 Поїздок: <b>{trips_count}</b> | ⏱️ Години: <b>{hours_worked:.1f}</b>
💰 За годину: <b>~{per_hour:.0f} грн/год</b>"""
    
    return infographic


def format_driver_stats(
    total_trips: int,
    rating: float,
    karma: int,
    completed_today: int = 0
) -> str:
    """
    Форматує статистику водія з візуальними елементами
    
    Args:
        total_trips: Загальна кількість поїздок
        rating: Рейтинг водія
        karma: Карма водія
        completed_today: Завершено поїздок сьогодні
        
    Returns:
        Форматована статистика
    """
    # Зірки для рейтингу
    stars = '⭐' * int(rating)
    empty_stars = '☆' * (5 - int(rating))
    rating_visual = f"{stars}{empty_stars} {rating:.1f}"
    
    # Карма з кольором
    karma_formatted = format_karma(karma)
    
    stats = f"""📊 <b>ВАША СТАТИСТИКА</b>

🚕 <b>Поїздок загалом:</b> {total_trips}
📅 <b>Сьогодні:</b> {completed_today}

{rating_visual}

{karma_formatted}
{get_karma_level_text(karma)}"""
    
    return stats


# ============ РЕЙТИНГ З ВІЗУАЛІЗАЦІЄЮ ============

def format_rating_stars(rating: float) -> str:
    """
    Форматує рейтинг зірками
    
    Args:
        rating: Рейтинг (0-5)
        
    Returns:
        Візуальний рейтинг
    """
    full_stars = int(rating)
    stars = '⭐' * full_stars
    empty = '☆' * (5 - full_stars)
    return f"{stars}{empty} {rating:.1f}"


# ============ ФОРМАТУВАННЯ ПОВІДОМЛЕНЬ З ВІЗУАЛЬНИМИ ЕЛЕМЕНТАМИ ============

def format_order_status_message(
    order_id: int,
    status: str,
    pickup: str,
    destination: str,
    price: float,
    driver_name: Optional[str] = None,
    driver_phone: Optional[str] = None,
    car_info: Optional[str] = None
) -> str:
    """
    Форматує повідомлення про статус замовлення з візуальними елементами
    
    Args:
        order_id: ID замовлення
        status: Статус
        pickup: Звідки
        destination: Куди
        price: Ціна
        driver_name: Ім'я водія (опційно)
        driver_phone: Телефон водія (опційно)
        car_info: Інфо про авто (опційно)
        
    Returns:
        Форматоване повідомлення
    """
    status_text = get_status_text_with_emoji(status)
    
    message = f"""<b>Замовлення #{order_id}</b>

{status_text}

📍 <b>Маршрут:</b>
   🅰️  {pickup}
   🅱️  {destination}

💰 <b>Вартість:</b> {price:.0f} грн"""
    
    if driver_name and status in ['accepted', 'in_progress']:
        message += f"""

{create_section_divider('ВОДІЙ', 25)}
👤 {driver_name}"""
        
        if car_info:
            message += f"\n🚗 {car_info}"
        
        if driver_phone:
            message += f"\n📱 {driver_phone}"
    
    return message
