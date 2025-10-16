"""Мультимовність (Internationalization) для бота"""
from typing import Dict, Optional

# Система перекладів
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # Головне меню
    "menu.register": {
        "uk": "📱 Зареєструватися",
        "ru": "📱 Зарегистрироваться",
        "en": "📱 Register"
    },
    "menu.order_taxi": {
        "uk": "🚖 Замовити таксі",
        "ru": "🚖 Заказать такси",
        "en": "🚖 Order Taxi"
    },
    "menu.my_orders": {
        "uk": "📜 Мої замовлення",
        "ru": "📜 Мои заказы",
        "en": "📜 My Orders"
    },
    "menu.become_driver": {
        "uk": "🚗 Стати водієм",
        "ru": "🚗 Стать водителем",
        "en": "🚗 Become Driver"
    },
    "menu.driver_panel": {
        "uk": "🚗 Панель водія",
        "ru": "🚗 Панель водителя",
        "en": "🚗 Driver Panel"
    },
    "menu.admin_panel": {
        "uk": "⚙️ Адмін-панель",
        "ru": "⚙️ Админ-панель",
        "en": "⚙️ Admin Panel"
    },
    "menu.language": {
        "uk": "🌐 Мова",
        "ru": "🌐 Язык",
        "en": "🌐 Language"
    },
    "menu.help": {
        "uk": "ℹ️ Допомога",
        "ru": "ℹ️ Помощь",
        "en": "ℹ️ Help"
    },
    
    # Вітання
    "welcome.title": {
        "uk": "Ласкаво просимо до Taxi Bot! 🚖",
        "ru": "Добро пожаловать в Taxi Bot! 🚖",
        "en": "Welcome to Taxi Bot! 🚖"
    },
    "welcome.description": {
        "uk": "Ваш надійний помічник для замовлення таксі",
        "ru": "Ваш надежный помощник для заказа такси",
        "en": "Your reliable taxi ordering assistant"
    },
    
    # Реєстрація
    "register.phone_request": {
        "uk": "📱 Поділіться номером телефону для реєстрації",
        "ru": "📱 Поделитесь номером телефона для регистрации",
        "en": "📱 Share your phone number to register"
    },
    "register.city_select": {
        "uk": "🏙 Оберіть ваше місто:",
        "ru": "🏙 Выберите ваш город:",
        "en": "🏙 Select your city:"
    },
    "register.success": {
        "uk": "✅ Реєстрацію завершено!",
        "ru": "✅ Регистрация завершена!",
        "en": "✅ Registration completed!"
    },
    
    # Замовлення
    "order.pickup_request": {
        "uk": "📍 Звідки подати таксі?\n\nНадішліть адресу або геолокацію",
        "ru": "📍 Откуда подать такси?\n\nОтправьте адрес или геолокацию",
        "en": "📍 Where to pick you up?\n\nSend address or location"
    },
    "order.destination_request": {
        "uk": "📍 Куди їдемо?\n\nНадішліть адресу або геолокацію",
        "ru": "📍 Куда едем?\n\nОтправьте адрес или геолокацию",
        "en": "📍 Where to go?\n\nSend address or location"
    },
    "order.comment_request": {
        "uk": "💬 Додайте коментар (опціонально):\n\nНаприклад: під'їзд 3, поверх 5",
        "ru": "💬 Добавьте комментарий (опционально):\n\nНапример: подъезд 3, этаж 5",
        "en": "💬 Add comment (optional):\n\nFor example: entrance 3, floor 5"
    },
    "order.confirm": {
        "uk": "📋 Перевірте дані замовлення:",
        "ru": "📋 Проверьте данные заказа:",
        "en": "📋 Check order details:"
    },
    "order.created": {
        "uk": "✅ Замовлення #{order_id} прийнято!\n\n🔍 Шукаємо водія...",
        "ru": "✅ Заказ #{order_id} принят!\n\n🔍 Ищем водителя...",
        "en": "✅ Order #{order_id} accepted!\n\n🔍 Looking for driver..."
    },
    "order.cancelled": {
        "uk": "❌ Замовлення скасовано",
        "ru": "❌ Заказ отменен",
        "en": "❌ Order cancelled"
    },
    
    # Водій
    "driver.registration_request": {
        "uk": "📝 Реєстрація водія\n\nВкажіть ваше ПІБ:",
        "ru": "📝 Регистрация водителя\n\nУкажите ваше ФИО:",
        "en": "📝 Driver registration\n\nEnter your full name:"
    },
    "driver.status_online": {
        "uk": "🟢 Онлайн",
        "ru": "🟢 Онлайн",
        "en": "🟢 Online"
    },
    "driver.status_offline": {
        "uk": "🔴 Офлайн",
        "ru": "🔴 Офлайн",
        "en": "🔴 Offline"
    },
    "driver.order_accepted": {
        "uk": "✅ Ви прийняли замовлення!",
        "ru": "✅ Вы приняли заказ!",
        "en": "✅ You accepted the order!"
    },
    
    # Статуси замовлення
    "status.pending": {
        "uk": "⏳ Очікується",
        "ru": "⏳ Ожидается",
        "en": "⏳ Pending"
    },
    "status.accepted": {
        "uk": "✅ Прийнято",
        "ru": "✅ Принято",
        "en": "✅ Accepted"
    },
    "status.in_progress": {
        "uk": "🚗 В дорозі",
        "ru": "🚗 В пути",
        "en": "🚗 In Progress"
    },
    "status.completed": {
        "uk": "✔️ Завершено",
        "ru": "✔️ Завершено",
        "en": "✔️ Completed"
    },
    "status.cancelled": {
        "uk": "❌ Скасовано",
        "ru": "❌ Отменено",
        "en": "❌ Cancelled"
    },
    
    # Кнопки
    "btn.cancel": {
        "uk": "❌ Скасувати",
        "ru": "❌ Отменить",
        "en": "❌ Cancel"
    },
    "btn.skip": {
        "uk": "⏩ Пропустити",
        "ru": "⏩ Пропустить",
        "en": "⏩ Skip"
    },
    "btn.confirm": {
        "uk": "✅ Підтвердити",
        "ru": "✅ Подтвердить",
        "en": "✅ Confirm"
    },
    "btn.send_location": {
        "uk": "📍 Надіслати геолокацію",
        "ru": "📍 Отправить геолокацию",
        "en": "📍 Send Location"
    },
    "btn.share_phone": {
        "uk": "📱 Поділитися номером",
        "ru": "📱 Поделиться номером",
        "en": "📱 Share Phone"
    },
    
    # Загальні
    "common.client": {
        "uk": "Клієнт",
        "ru": "Клиент",
        "en": "Client"
    },
    "common.driver": {
        "uk": "Водій",
        "ru": "Водитель",
        "en": "Driver"
    },
    "common.phone": {
        "uk": "Телефон",
        "ru": "Телефон",
        "en": "Phone"
    },
    "common.city": {
        "uk": "Місто",
        "ru": "Город",
        "en": "City"
    },
    "common.from": {
        "uk": "Звідки",
        "ru": "Откуда",
        "en": "From"
    },
    "common.to": {
        "uk": "Куди",
        "ru": "Куда",
        "en": "To"
    },
    "common.comment": {
        "uk": "Коментар",
        "ru": "Комментарий",
        "en": "Comment"
    },
    "common.distance": {
        "uk": "Відстань",
        "ru": "Расстояние",
        "en": "Distance"
    },
    "common.fare": {
        "uk": "Вартість",
        "ru": "Стоимость",
        "en": "Fare"
    },
    "common.rating": {
        "uk": "Рейтинг",
        "ru": "Рейтинг",
        "en": "Rating"
    },
    
    # Платежі
    "payment.commission": {
        "uk": "💳 Комісія",
        "ru": "💳 Комиссия",
        "en": "💳 Commission"
    },
    "payment.qr_title": {
        "uk": "📱 Оплата через QR-код",
        "ru": "📱 Оплата через QR-код",
        "en": "📱 Payment via QR code"
    },
    "payment.scan_qr": {
        "uk": "Відскануйте QR-код для оплати:",
        "ru": "Отсканируйте QR-код для оплаты:",
        "en": "Scan QR code to pay:"
    },
    "payment.card_number": {
        "uk": "Номер картки:",
        "ru": "Номер карты:",
        "en": "Card number:"
    },
    "payment.amount": {
        "uk": "Сума:",
        "ru": "Сумма:",
        "en": "Amount:"
    },
    
    # Збережені адреси
    "saved.home": {
        "uk": "🏠 Додому",
        "ru": "🏠 Домой",
        "en": "🏠 Home"
    },
    "saved.work": {
        "uk": "💼 На роботу",
        "ru": "💼 На работу",
        "en": "💼 To Work"
    },
    "saved.add": {
        "uk": "➕ Додати адресу",
        "ru": "➕ Добавить адрес",
        "en": "➕ Add Address"
    },
    "saved.manage": {
        "uk": "⚙️ Керувати адресами",
        "ru": "⚙️ Управлять адресами",
        "en": "⚙️ Manage Addresses"
    },
    
    # Причини скасування
    "cancel.reason_title": {
        "uk": "❌ Чому ви скасовуєте замовлення?",
        "ru": "❌ Почему вы отменяете заказ?",
        "en": "❌ Why are you cancelling?"
    },
    "cancel.reason.wait_long": {
        "uk": "⏰ Водій довго їде",
        "ru": "⏰ Водитель долго едет",
        "en": "⏰ Driver taking too long"
    },
    "cancel.reason.wrong_address": {
        "uk": "📍 Помилка в адресі",
        "ru": "📍 Ошибка в адресе",
        "en": "📍 Wrong address"
    },
    "cancel.reason.changed_mind": {
        "uk": "🤷 Передумав",
        "ru": "🤷 Передумал",
        "en": "🤷 Changed my mind"
    },
    "cancel.reason.found_other": {
        "uk": "🚕 Знайшов інше таксі",
        "ru": "🚕 Нашел другое такси",
        "en": "🚕 Found another taxi"
    },
    "cancel.reason.other": {
        "uk": "❓ Інше",
        "ru": "❓ Другое",
        "en": "❓ Other"
    },
}


def get_text(key: str, lang: str = "uk", **kwargs) -> str:
    """Отримати переклад тексту за ключем
    
    Args:
        key: Ключ перекладу (наприклад, "menu.order_taxi")
        lang: Код мови (uk, ru, en)
        **kwargs: Параметри для форматування (наприклад, order_id=123)
    
    Returns:
        Перекладений текст
    """
    if key not in TRANSLATIONS:
        return key
    
    translation = TRANSLATIONS[key].get(lang, TRANSLATIONS[key].get("uk", key))
    
    # Форматування параметрів
    if kwargs:
        try:
            translation = translation.format(**kwargs)
        except KeyError:
            pass
    
    return translation


def get_user_language(user_language_code: Optional[str]) -> str:
    """Визначити мову користувача
    
    Args:
        user_language_code: Код мови з Telegram (uk, ru, en тощо)
    
    Returns:
        Код мови (uk, ru, en)
    """
    if not user_language_code:
        return "uk"
    
    lang = user_language_code.lower()
    
    # Підтримувані мови
    if lang in ["uk", "ukr"]:
        return "uk"
    elif lang in ["ru", "rus"]:
        return "ru"
    elif lang in ["en", "eng"]:
        return "en"
    
    # За замовчуванням українська
    return "uk"
