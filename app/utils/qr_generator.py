"""Генерація QR-кодів для оплати"""
import qrcode
from io import BytesIO
from typing import Optional


def generate_payment_qr(card_number: str, amount: float, comment: Optional[str] = None) -> BytesIO:
    """
    Генерувати QR-код для оплати на картку
    
    Args:
        card_number: Номер картки (наприклад, "4149499901234567")
        amount: Сума оплати
        comment: Коментар до платежу (опціонально)
    
    Returns:
        BytesIO об'єкт з зображенням QR-коду
    """
    # Формат для українських банків (MonoBank, PrivatBank)
    # Можна використовувати різні формати залежно від банку
    
    # Простий формат: номер картки + сума + коментар
    payment_data = f"Card: {card_number}\nAmount: {amount:.2f} UAH"
    
    if comment:
        payment_data += f"\nComment: {comment}"
    
    # Створення QR-коду
    qr = qrcode.QRCode(
        version=1,  # Розмір QR (1-40)
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    
    qr.add_data(payment_data)
    qr.make(fit=True)
    
    # Генерація зображення
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Конвертація в BytesIO
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return buffer


def generate_monobank_qr(phone: str, amount: float) -> BytesIO:
    """
    Генерувати QR-код для оплати через MonoBank
    
    Args:
        phone: Номер телефону MonoBank (наприклад, "+380991234567")
        amount: Сума оплати
    
    Returns:
        BytesIO об'єкт з зображенням QR-коду
    """
    # Формат MonoBank: https://send.monobank.ua/{phone}/{amount}
    monobank_url = f"https://send.monobank.ua/{phone.replace('+', '')}/{amount}"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    
    qr.add_data(monobank_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return buffer


def generate_simple_qr(text: str) -> BytesIO:
    """
    Генерувати простий QR-код з довільним текстом
    
    Args:
        text: Текст для QR-коду
    
    Returns:
        BytesIO об'єкт з зображенням QR-коду
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    
    qr.add_data(text)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return buffer
