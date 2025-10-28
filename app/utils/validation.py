"""Валідація та санітизація вхідних даних"""
import re
from typing import Optional, Tuple


def validate_phone_number(phone: str) -> Tuple[bool, Optional[str]]:
    """
    Валідація номеру телефону.
    
    Підтримувані формати:
        +380671234567
        380671234567
        +38 067 123 45 67
        +38(067)123-45-67
    
    Args:
        phone: Номер телефону для валідації
    
    Returns:
        Tuple[bool, Optional[str]]: (валідний?, очищений номер або None)
    """
    if not phone:
        return False, None
    
    # Видалити всі не-цифрові символи крім +
    cleaned = re.sub(r'[^\d+]', '', phone.strip())
    
    # Перевірка на небезпечні символи (SQL injection)
    if re.search(r'[;<>\'\"\\]', phone):
        return False, None
    
    # Перевірка довжини (мінімум 10 цифр, максимум 15)
    digits_only = cleaned.replace('+', '')
    
    if len(digits_only) < 10 or len(digits_only) > 15:
        return False, None
    
    # Перевірка що починається з + або цифри
    if not cleaned[0] in ('+', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'):
        return False, None
    
    # Український номер має починатись з +380 або 380 або 0
    if cleaned.startswith('+380') or cleaned.startswith('380'):
        if len(digits_only) != 12:
            return False, None
    elif cleaned.startswith('0'):
        if len(digits_only) != 10:
            return False, None
        # Конвертувати 0671234567 → +380671234567
        cleaned = '+38' + cleaned
    
    return True, cleaned


def validate_address(address: str, min_length: int = 3, max_length: int = 200) -> Tuple[bool, Optional[str]]:
    """
    Валідація адреси.
    
    Args:
        address: Адреса для валідації
        min_length: Мінімальна довжина адреси
        max_length: Максимальна довжина адреси
    
    Returns:
        Tuple[bool, Optional[str]]: (валідна?, очищена адреса або None)
    """
    if not address:
        return False, None
    
    # Очистити від зайвих пробілів
    cleaned = address.strip()
    
    # Перевірка довжини
    if len(cleaned) < min_length or len(cleaned) > max_length:
        return False, None
    
    # Перевірка на небезпечні символи (SQL injection, XSS)
    if re.search(r'[<>\'\"\\;]', cleaned):
        return False, None
    
    # Перевірка на підозрілі паттерни (SQL injection)
    dangerous_patterns = [
        r'--',           # SQL коментар
        r'/\*',          # SQL коментар
        r'\*/',          # SQL коментар
        r'union\s+select',  # SQL injection
        r'drop\s+table',    # SQL injection
        r'<script',         # XSS
        r'javascript:',     # XSS
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return False, None
    
    # Якщо це координати (📍 lat, lon) - дозволити
    if cleaned.startswith('📍'):
        return True, cleaned
    
    return True, cleaned


def validate_name(name: str, min_length: int = 2, max_length: int = 100) -> Tuple[bool, Optional[str]]:
    """
    Валідація імені користувача.
    
    Args:
        name: Ім'я для валідації
        min_length: Мінімальна довжина імені
        max_length: Максимальна довжина імені
    
    Returns:
        Tuple[bool, Optional[str]]: (валідне?, очищене ім'я або None)
    """
    if not name:
        return False, None
    
    # Очистити від зайвих пробілів
    cleaned = name.strip()
    
    # Перевірка довжини
    if len(cleaned) < min_length or len(cleaned) > max_length:
        return False, None
    
    # Перевірка на небезпечні символи
    if re.search(r'[<>\'\"\\;]', cleaned):
        return False, None
    
    # Ім'я має містити хоча б одну букву
    if not re.search(r'[a-zA-Zа-яА-ЯіІїЇєЄґҐ]', cleaned):
        return False, None
    
    return True, cleaned


def validate_comment(comment: str, max_length: int = 500) -> Tuple[bool, Optional[str]]:
    """
    Валідація коментаря.
    
    Args:
        comment: Коментар для валідації
        max_length: Максимальна довжина коментаря
    
    Returns:
        Tuple[bool, Optional[str]]: (валідний?, очищений коментар або None)
    """
    if not comment:
        return True, None  # Коментар опціональний
    
    # Очистити від зайвих пробілів
    cleaned = comment.strip()
    
    # Перевірка довжини
    if len(cleaned) > max_length:
        return False, None
    
    # Перевірка на небезпечні символи
    if re.search(r'[<>\\;]', cleaned):
        return False, None
    
    # Перевірка на SQL injection
    dangerous_patterns = [
        r'--',
        r'/\*',
        r'\*/',
        r'union\s+select',
        r'drop\s+table',
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return False, None
    
    return True, cleaned


def sanitize_html(text: str) -> str:
    """
    Видалити HTML теги з тексту.
    
    Args:
        text: Текст для санітизації
    
    Returns:
        Текст без HTML тегів
    """
    if not text:
        return ""
    
    # Видалити HTML теги
    cleaned = re.sub(r'<[^>]+>', '', text)
    
    # Замінити HTML entities
    html_entities = {
        '&lt;': '<',
        '&gt;': '>',
        '&amp;': '&',
        '&quot;': '"',
        '&#39;': "'",
    }
    
    for entity, char in html_entities.items():
        cleaned = cleaned.replace(entity, char)
    
    return cleaned


def validate_car_plate(plate: str) -> Tuple[bool, Optional[str]]:
    """
    Валідація номерного знаку автомобіля.
    
    Українські номери: AA1234BB або AI1234AA
    
    Args:
        plate: Номерний знак для валідації
    
    Returns:
        Tuple[bool, Optional[str]]: (валідний?, очищений номер або None)
    """
    if not plate:
        return False, None
    
    # Очистити від зайвих пробілів та привести до верхнього регістру
    cleaned = plate.strip().upper()
    
    # Перевірка довжини (мінімум 6, максимум 10 символів)
    if len(cleaned) < 6 or len(cleaned) > 10:
        return False, None
    
    # Перевірка на небезпечні символи
    if re.search(r'[<>\'\"\\;]', cleaned):
        return False, None
    
    # Базова перевірка формату (літери та цифри)
    if not re.match(r'^[A-Z0-9\s-]+$', cleaned):
        return False, None
    
    return True, cleaned


def validate_card_number(card: str) -> Tuple[bool, Optional[str]]:
    """
    Валідація номеру банківської картки.
    
    Args:
        card: Номер картки для валідації
    
    Returns:
        Tuple[bool, Optional[str]]: (валідний?, форматований номер або None)
    """
    if not card:
        return False, None
    
    # Видалити всі не-цифрові символи
    digits_only = re.sub(r'\D', '', card.strip())
    
    # Перевірка довжини (13-19 цифр для банківських карток)
    if len(digits_only) < 13 or len(digits_only) > 19:
        return False, None
    
    # Базова перевірка по алгоритму Луна
    def luhn_check(card_number: str) -> bool:
        def digits_of(n):
            return [int(d) for d in str(n)]
        
        digits = digits_of(card_number)
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        checksum = sum(odd_digits)
        for d in even_digits:
            checksum += sum(digits_of(d * 2))
        return checksum % 10 == 0
    
    if not luhn_check(digits_only):
        return False, None
    
    # Форматувати як 1234 5678 9012 3456
    formatted = ' '.join([digits_only[i:i+4] for i in range(0, len(digits_only), 4)])
    
    return True, formatted
