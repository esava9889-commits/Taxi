"""Перевірка блокування водіїв"""
from aiogram.types import Message, CallbackQuery
from app.storage.db import get_driver_by_tg_user_id


async def is_driver_blocked(db_path: str, user_id: int) -> bool:
    """
    Перевірити чи заблокований водій.
    
    Водій вважається заблокованим, якщо:
    - Статус = "rejected" (заблокований адміністратором)
    """
    driver = await get_driver_by_tg_user_id(db_path, user_id)
    if driver and driver.status == "rejected":
        return True
    return False


async def send_driver_blocked_message(event: Message | CallbackQuery) -> bool:
    """
    Відправити повідомлення про блокування водія.
    
    Returns:
        True якщо водій заблокований (повідомлення відправлено)
        False якщо водій не заблокований
    """
    blocked_text = (
        "🚫 <b>ВАШ АКАУНТ ВОДІЯ ЗАБЛОКОВАНО</b>\n\n"
        "❌ На жаль, ви не можете:\n"
        "• Приймати замовлення\n"
        "• Працювати як водій\n"
        "• Отримувати доступ до панелі водія\n\n"
        "📞 Якщо вважаєте це помилкою, зверніться до адміністратора.\n\n"
        "💡 Ви можете користуватися ботом як клієнт."
    )
    
    if isinstance(event, CallbackQuery):
        await event.answer(blocked_text, show_alert=True)
        return True
    elif isinstance(event, Message):
        await event.answer(blocked_text, parse_mode="HTML")
        return True
    
    return False


async def check_driver_blocked_and_notify(db_path: str, event: Message | CallbackQuery) -> bool:
    """
    Перевірити блокування водія та відправити повідомлення якщо заблокований.
    
    Returns:
        True якщо водій заблокований
        False якщо водій не заблокований
    """
    if isinstance(event, CallbackQuery):
        user_id = event.from_user.id if event.from_user else None
    elif isinstance(event, Message):
        user_id = event.from_user.id if event.from_user else None
    else:
        return False
    
    if not user_id:
        return False
    
    if await is_driver_blocked(db_path, user_id):
        await send_driver_blocked_message(event)
        return True
    
    return False
