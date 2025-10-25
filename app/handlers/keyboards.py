"""Клавіатури для різних станів бота"""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup

from app.config.config import AVAILABLE_CITIES


def main_menu_keyboard(
    is_registered: bool = False, 
    is_driver: bool = False, 
    is_admin: bool = False,
    has_driver_application: bool = False,
    is_blocked: bool = False
) -> ReplyKeyboardMarkup:
    """Головне меню з кнопками"""
    
    # 🚫 ЗАБЛОКОВАНИЙ КОРИСТУВАЧ - тільки допомога
    if is_blocked and not is_admin:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="ℹ️ Допомога")],
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="🚫 Акаунт заблоковано",
        )
    
    # АДМІН ПАНЕЛЬ (найвищий пріоритет)
    if is_admin:
        keyboard = [
            [KeyboardButton(text="⚙️ Адмін-панель")],
            [KeyboardButton(text="🚖 Замовити таксі")],
            [KeyboardButton(text="📍 Мої адреси"), KeyboardButton(text="👤 Мій профіль")],
            [KeyboardButton(text="🆘 SOS"), KeyboardButton(text="🪄")],
        ]
        
        # Якщо адмін також водій - додаємо панель водія
        if is_driver:
            keyboard.append([KeyboardButton(text="🚗 Панель водія")])
        elif not has_driver_application:
            # Показувати "Стати водієм" тільки якщо немає заявки
            keyboard.append([KeyboardButton(text="🚗 Стати водієм")])
        
        keyboard.append([KeyboardButton(text="ℹ️ Допомога")])
        
        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Оберіть дію",
        )
    
    if is_driver:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚗 Панель водія")],
                [KeyboardButton(text="⚙️ Особиста інформація"), KeyboardButton(text="💳 Комісія")],
                [KeyboardButton(text="📜 Історія поїздок"), KeyboardButton(text="💼 Гаманець")],
                [KeyboardButton(text="👤 Кабінет клієнта"), KeyboardButton(text="ℹ️ Допомога")],
                [KeyboardButton(text="📖 Правила користування"), KeyboardButton(text="🪄")],
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Оберіть дію",
        )
    
    if is_registered:
        keyboard = [
            [KeyboardButton(text="🚖 Замовити таксі")],
            [KeyboardButton(text="📍 Мої адреси"), KeyboardButton(text="👤 Мій профіль")],
            [KeyboardButton(text="🆘 SOS"), KeyboardButton(text="ℹ️ Допомога")],
            [KeyboardButton(text="📖 Правила користування"), KeyboardButton(text="🪄")]
        ]
        
        # Показувати "Стати водієм" тільки якщо немає заявки
        if not has_driver_application:
            keyboard.append([KeyboardButton(text="🚗 Стати водієм")])
        
        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Оберіть дію",
        )
    
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Зареєструватись")],
            [KeyboardButton(text="ℹ️ Допомога")],
            [KeyboardButton(text="📖 Правила користування")]  # ⭐ НОВА КНОПКА
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Оберіть дію",
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура з кнопкою 'Скасувати'"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Скасувати")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def contact_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура для надання контакту"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поділитися контактом", request_contact=True)],
            [KeyboardButton(text="❌ Скасувати")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Надішліть контакт",
    )


def city_selection_keyboard() -> InlineKeyboardMarkup:
    """Інлайн кнопки для вибору міста"""
    buttons = []
    for city in AVAILABLE_CITIES:
        buttons.append([InlineKeyboardButton(text=f"📍 {city}", callback_data=f"city:{city}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def driver_city_selection_keyboard() -> InlineKeyboardMarkup:
    """Інлайн кнопки для вибору міста (для водіїв)"""
    buttons = []
    for city in AVAILABLE_CITIES:
        buttons.append([InlineKeyboardButton(text=f"📍 {city}", callback_data=f"driver_city:{city}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
