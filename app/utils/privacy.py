"""Функції для захисту приватних даних користувачів"""


def mask_phone_number(phone: str, show_last_digits: int = 2) -> str:
    """
    Маскує номер телефону, показуючи тільки останні N цифр.
    
    Приклад:
        +380671234567 -> +380*******67
        380671234567 -> 380*******67
        +38 067 123 45 67 -> +38 *** *** ** 67
    
    Args:
        phone: Номер телефону для маскування
        show_last_digits: Кількість останніх цифр для показу (за замовчуванням 2)
    
    Returns:
        Замаскований номер телефону
    """
    if not phone:
        return "***"
    
    # Видалити всі не-цифрові символи для підрахунку
    digits_only = ''.join(c for c in phone if c.isdigit())
    
    if len(digits_only) < show_last_digits:
        return "*" * len(phone)
    
    # Отримати останні N цифр
    last_digits = digits_only[-show_last_digits:]
    
    # Замінити всі цифри крім останніх на *
    masked = ""
    digit_count = 0
    digits_from_end = len(digits_only) - show_last_digits
    
    for char in phone:
        if char.isdigit():
            if digit_count < digits_from_end:
                masked += "*"
            else:
                masked += char
            digit_count += 1
        else:
            # Зберегти формат (пробіли, дефіси, дужки, +)
            masked += char if char in " -()+" else ""
    
    return masked


def mask_email(email: str) -> str:
    """
    Маскує email адресу.
    
    Приклад:
        user@example.com -> u***@example.com
        john.doe@gmail.com -> j***@gmail.com
    
    Args:
        email: Email адреса для маскування
    
    Returns:
        Замаскована email адреса
    """
    if not email or '@' not in email:
        return "***@***"
    
    local, domain = email.split('@', 1)
    
    if len(local) <= 1:
        masked_local = "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 1)
    
    return f"{masked_local}@{domain}"


def mask_name(full_name: str) -> str:
    """
    Маскує ім'я, показуючи тільки першу букву і прізвище.
    
    Приклад:
        Іван Петрович Сидоренко -> І. П. Сидоренко
        John Doe -> J. Doe
    
    Args:
        full_name: Повне ім'я для маскування
    
    Returns:
        Замасковане ім'я
    """
    if not full_name:
        return "***"
    
    parts = full_name.strip().split()
    
    if len(parts) == 0:
        return "***"
    elif len(parts) == 1:
        return parts[0][0] + "." if parts[0] else "***"
    else:
        # Перші частини (ім'я, по батькові) - тільки ініціали
        initials = [f"{part[0]}." for part in parts[:-1] if part]
        # Остання частина (прізвище) - повністю
        last_name = parts[-1]
        
        return " ".join(initials + [last_name])
