"""Перевірка блокування користувачів"""
from aiogram.types import Message, CallbackQuery
from app.storage.db import get_user_by_id


async def is_user_blocked(db_path: str, user_id: int) -> bool:
    """Перевірити чи заблокований користувач"""
    user = await get_user_by_id(db_path, user_id)
    if user and user.is_blocked:
        return True
    return False


async def send_blocked_message(event: Message | CallbackQuery) -> bool:
    """
    Відправити повідомлення про блокування користувача.
    
    Returns:
        True якщо користувач заблокований (повідомлення відправлено)
        False якщо користувач не заблокований
    """
    blocked_text = (
        "🚫 <b>ВАШ АКАУНТ ЗАБЛОКОВАНО</b>\n\n"
        "На жаль, ви не можете створювати замовлення.\n"
        "Якщо вважаєте це помилкою, зверніться до адміністратора."
    )
    
    if isinstance(event, CallbackQuery):
        await event.answer(blocked_text, show_alert=True)
        return True
    elif isinstance(event, Message):
        await event.answer(blocked_text, parse_mode="HTML")
        return True
    
    return False
