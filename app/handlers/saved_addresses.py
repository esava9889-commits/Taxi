"""Обробник збережених адрес"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.config.config import AppConfig
from app.storage.db import (
    SavedAddress,
    save_address,
    get_user_saved_addresses,
    get_saved_address_by_id,
    delete_saved_address,
    update_saved_address,
)

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="saved_addresses")
    logger = logging.getLogger(__name__)

    class SaveAddressStates(StatesGroup):
        name = State()
        emoji = State()
        address = State()

    async def _show_addresses_list(user_id: int, edit_message=None, send_to_chat=None) -> None:
        """Допоміжна функція для показу списку адрес (інлайн)"""
        addresses = await get_user_saved_addresses(config.database_path, user_id)
        
        if not addresses:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")]
                ]
            )
            text = ("📍 <b>Збережені адреси</b>\n\n"
                   "У вас поки немає збережених адрес.\n\n"
                   "Збережіть часто використовувані адреси для швидкого замовлення!")
        else:
            buttons = []
            text = "📍 <b>Збережені адреси</b>\n\n"
            for addr in addresses:
                text += f"{addr.emoji} <b>{addr.name}</b>\n"
                text += f"   {addr.address[:50]}{'...' if len(addr.address) > 50 else ''}\n\n"
                buttons.append([
                    InlineKeyboardButton(
                        text=f"{addr.emoji} {addr.name}",
                        callback_data=f"address:view:{addr.id}"
                    )
                ])
            
            buttons.append([InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        if edit_message:
            await edit_message.edit_text(text, reply_markup=kb)
        elif send_to_chat:
            await send_to_chat.answer(text, reply_markup=kb)
    
    @router.message(F.text == "📍 Мої адреси")
    async def show_saved_addresses(message: Message) -> None:
        """Показати збережені адреси (з Reply keyboard)"""
        if not message.from_user:
            return
        
        # 🚫 Перевірка блокування
        from app.handlers.blocked_check import is_user_blocked, send_blocked_message
        if await is_user_blocked(config.database_path, message.from_user.id):
            await send_blocked_message(message)
            return
        
        await _show_addresses_list(message.from_user.id, send_to_chat=message)
    
    @router.callback_query(F.data == "address:list")
    async def show_saved_addresses_inline(call: CallbackQuery) -> None:
        """Показати збережені адреси (з Inline кнопки)"""
        await call.answer()
        if not call.from_user:
            return
        await _show_addresses_list(call.from_user.id, edit_message=call.message)

    @router.callback_query(F.data == "address:add")
    async def start_add_address(call: CallbackQuery, state: FSMContext) -> None:
        """Почати додавання адреси"""
        await call.answer()
        await state.set_state(SaveAddressStates.name)
        
        # Інлайн кнопка для скасування
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="address:cancel")]
        ])
        
        # Оновити повідомлення (не створювати нове!)
        try:
            msg = await call.message.edit_text(
                "📝 <b>Додавання адреси</b>\n\n"
                "Введіть назву адреси (наприклад: Додому, На роботу, До батьків):",
                reply_markup=kb
            )
            # Зберегти message_id для подальшого редагування
            await state.update_data(last_message_id=msg.message_id)
        except:
            msg = await call.message.answer(
                "📝 <b>Додавання адреси</b>\n\n"
                "Введіть назву адреси (наприклад: Додому, На роботу, До батьків):",
                reply_markup=kb
            )
            await state.update_data(last_message_id=msg.message_id)

    @router.message(SaveAddressStates.name)
    async def save_name(message: Message, state: FSMContext) -> None:
        """Зберегти назву адреси"""
        logger.info(f"📝 Отримано назву адреси від користувача {message.from_user.id if message.from_user else 'Unknown'}: {message.text}")
        
        name = message.text.strip() if message.text else ""
        if len(name) < 2:
            # Не створювати нове повідомлення - просто показати помилку коротко
            error_msg = await message.answer("❌ Назва занадто коротка. Спробуйте ще раз:")
            # Видалити повідомлення помилки через 3 секунди
            import asyncio
            asyncio.create_task(asyncio.sleep(3))
            try:
                await message.delete()
                asyncio.create_task(asyncio.sleep(3).then(lambda: error_msg.delete()))
            except:
                pass
            return
        
        # Видалити повідомлення користувача щоб чат був чистий
        try:
            await message.delete()
        except:
            pass
        
        # Перевірити чи це редагування
        data = await state.get_data()
        is_editing = 'editing_address_id' in data
        
        logger.info(f"📝 Режим: {'Редагування' if is_editing else 'Створення нової адреси'}")
        
        await state.update_data(name=name)
        await state.set_state(SaveAddressStates.emoji)
        
        # Запропонувати емодзі з кнопкою "Назад"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🏠", callback_data="emoji:🏠"),
                    InlineKeyboardButton(text="💼", callback_data="emoji:💼"),
                    InlineKeyboardButton(text="🏥", callback_data="emoji:🏥"),
                    InlineKeyboardButton(text="🏫", callback_data="emoji:🏫"),
                ],
                [
                    InlineKeyboardButton(text="🛒", callback_data="emoji:🛒"),
                    InlineKeyboardButton(text="🏋️", callback_data="emoji:🏋️"),
                    InlineKeyboardButton(text="☕", callback_data="emoji:☕"),
                    InlineKeyboardButton(text="📍", callback_data="emoji:📍"),
                ],
                [InlineKeyboardButton(text="⏩ Пропустити", callback_data="emoji:📍")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="address:back:name")]
            ]
        )
        
        # Оновити попереднє повідомлення бота
        data = await state.get_data()
        last_msg_id = data.get('last_message_id')
        
        if last_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=last_msg_id,
                    text=f"✅ Назва: <b>{name}</b>\n\n"
                         "Оберіть емодзі для адреси:",
                    reply_markup=kb
                )
            except:
                msg = await message.answer(
                    f"✅ Назва: <b>{name}</b>\n\n"
                    "Оберіть емодзі для адреси:",
                    reply_markup=kb
                )
                await state.update_data(last_message_id=msg.message_id)
        else:
            msg = await message.answer(
                f"✅ Назва: <b>{name}</b>\n\n"
                "Оберіть емодзі для адреси:",
                reply_markup=kb
            )
            await state.update_data(last_message_id=msg.message_id)

    @router.callback_query(F.data.startswith("emoji:"))
    async def save_emoji(call: CallbackQuery, state: FSMContext) -> None:
        """Зберегти емодзі"""
        emoji = call.data.split(":", 1)[1]
        logger.info(f"✨ Обрано емодзі: {emoji}")
        
        await state.update_data(emoji=emoji)
        
        # Перевірити чи це редагування
        data = await state.get_data()
        is_editing = 'editing_address_id' in data
        
        if is_editing:
            # Режим редагування - зберегти зміни
            addr_id = data.get('editing_address_id')
            new_name = data.get('name')
            new_emoji = emoji
            
            logger.info(f"✏️ Редагування адреси #{addr_id}: нова назва={new_name}, емодзі={new_emoji}")
            
            success = await update_saved_address(config.database_path, addr_id, call.from_user.id, new_name, new_emoji)
            
            await state.clear()
            
            if success:
                await call.answer("✅ Адресу оновлено!", show_alert=True)
                # Показати оновлений список
                await _show_addresses_list(call.from_user.id, edit_message=call.message)
            else:
                await call.answer("❌ Помилка оновлення", show_alert=True)
            
            return
        
        # Режим створення нової адреси
        await state.set_state(SaveAddressStates.address)
        
        await call.answer()
        
        # Інлайн кнопки для вибору способу введення адреси
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📍 Надіслати геолокацію", callback_data="address:send_location")],
                [InlineKeyboardButton(text="✏️ Ввести адресу текстом", callback_data="address:text_input")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="address:back:emoji")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="address:cancel")]
            ]
        )
        
        # Оновити повідомлення
        try:
            await call.message.edit_text(
                f"✅ Емодзі: {emoji}\n\n"
                "Тепер надішліть адресу або геолокацію:\n\n"
                "💡 Оберіть спосіб:",
                reply_markup=kb
            )
        except:
            await call.message.answer(
                f"✅ Емодзі: {emoji}\n\n"
                "Тепер надішліть адресу або геолокацію:\n\n"
                "💡 Оберіть спосіб:",
                reply_markup=kb
            )

    # Нові обробники для інлайн-навігації
    @router.callback_query(F.data == "address:cancel")
    async def cancel_add_address(call: CallbackQuery, state: FSMContext) -> None:
        """Скасувати додавання адреси"""
        await call.answer()
        await state.clear()
        
        # Повернутися до списку адрес
        if not call.from_user:
            return
        
        addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
        
        if not addresses:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")]
                ]
            )
            await call.message.edit_text(
                "📍 <b>Збережені адреси</b>\n\n"
                "У вас поки немає збережених адрес.",
                reply_markup=kb
            )
        else:
            buttons = []
            text = "📍 <b>Збережені адреси</b>\n\n"
            for addr in addresses:
                text += f"{addr.emoji} <b>{addr.name}</b>\n   {addr.address[:50]}{'...' if len(addr.address) > 50 else ''}\n\n"
                buttons.append([InlineKeyboardButton(text=f"{addr.emoji} {addr.name}", callback_data=f"address:view:{addr.id}")])
            
            buttons.append([InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")])
            await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    
    @router.callback_query(F.data == "address:back:name")
    async def back_to_name(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до введення назви"""
        await call.answer()
        await state.set_state(SaveAddressStates.name)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="address:cancel")]
        ])
        
        await call.message.edit_text(
            "📝 <b>Додавання адреси</b>\n\n"
            "Введіть назву адреси (наприклад: Додому, На роботу, До батьків):",
            reply_markup=kb
        )
    
    @router.callback_query(F.data == "address:back:emoji")
    async def back_to_emoji(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до вибору емодзі"""
        await call.answer()
        
        data = await state.get_data()
        name = data.get("name", "")
        
        await state.set_state(SaveAddressStates.emoji)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🏠", callback_data="emoji:🏠"),
                    InlineKeyboardButton(text="💼", callback_data="emoji:💼"),
                    InlineKeyboardButton(text="🏥", callback_data="emoji:🏥"),
                    InlineKeyboardButton(text="🏫", callback_data="emoji:🏫"),
                ],
                [
                    InlineKeyboardButton(text="🛒", callback_data="emoji:🛒"),
                    InlineKeyboardButton(text="🏋️", callback_data="emoji:🏋️"),
                    InlineKeyboardButton(text="☕", callback_data="emoji:☕"),
                    InlineKeyboardButton(text="📍", callback_data="emoji:📍"),
                ],
                [InlineKeyboardButton(text="⏩ Пропустити", callback_data="emoji:📍")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="address:back:name")]
            ]
        )
        
        await call.message.edit_text(
            f"✅ Назва: <b>{name}</b>\n\n"
            "Оберіть емодзі для адреси:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data == "address:send_location")
    async def request_location_for_address(call: CallbackQuery, state: FSMContext) -> None:
        """Попросити користувача надіслати геолокацію"""
        await call.answer()
        
        # Тут ПОТРІБЕН ReplyKeyboard для request_location
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        data = await state.get_data()
        last_msg_id = data.get('last_message_id')
        
        # Видалити попереднє повідомлення
        try:
            await call.message.delete()
        except:
            pass
        
        # Показати нове з ReplyKeyboard
        msg = await call.message.answer(
            "📍 Натисніть кнопку нижче, щоб надіслати вашу геолокацію:",
            reply_markup=kb
        )
        await state.update_data(last_message_id=msg.message_id)
    
    @router.callback_query(F.data == "address:text_input")
    async def request_text_address(call: CallbackQuery, state: FSMContext) -> None:
        """Попросити користувача ввести адресу текстом"""
        await call.answer()
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="address:back:emoji")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="address:cancel")]
            ]
        )
        
        await call.message.edit_text(
            "✏️ Введіть адресу текстом:\n\n"
            "Наприклад: вул. Хрещатик, 1, Київ",
            reply_markup=kb
        )

    @router.message(SaveAddressStates.address, F.location)
    async def save_address_location(message: Message, state: FSMContext) -> None:
        """Зберегти адресу з геолокації"""
        logger.info(f"📍 Отримано геолокацію для збереження адреси від користувача {message.from_user.id if message.from_user else 'Unknown'}")
        
        if not message.from_user or not message.location:
            logger.warning("⚠️ Немає from_user або location")
            return
        
        logger.info(f"📍 Координати: {message.location.latitude}, {message.location.longitude}")
        
        # Видалити повідомлення користувача
        try:
            await message.delete()
        except:
            pass
        
        data = await state.get_data()
        logger.info(f"📊 State data: {data}")
        loc = message.location
        
        # Reverse geocoding - отримати адресу з координат
        address = f"📍 {loc.latitude:.6f}, {loc.longitude:.6f}"
        
        if config.google_maps_api_key:
            logger.info(f"🔑 API ключ присутній, reverse geocoding: {loc.latitude}, {loc.longitude}")
            from app.utils.maps import reverse_geocode
            readable_address = await reverse_geocode(
                config.google_maps_api_key,
                loc.latitude,
                loc.longitude
            )
            if readable_address:
                address = readable_address
                logger.info(f"✅ Reverse geocoded: {address}")
            else:
                logger.warning(f"⚠️ Reverse geocoding не вдалось")
        else:
            logger.warning("⚠️ Google Maps API ключ відсутній для reverse geocoding")
        
        saved_addr = SavedAddress(
            id=None,
            user_id=message.from_user.id,
            name=data.get("name", "Адреса"),
            emoji=data.get("emoji", "📍"),
            address=address,
            lat=loc.latitude,
            lon=loc.longitude,
            created_at=datetime.now(timezone.utc)
        )
        
        addr_id = await save_address(config.database_path, saved_addr)
        
        # Видалити last_message_id щоб створити нове повідомлення
        last_msg_id = data.get('last_message_id')
        await state.clear()
        
        # Показати успіх і повернутися до списку адрес (інлайн!)
        addresses = await get_user_saved_addresses(config.database_path, message.from_user.id)
        
        buttons = []
        text = f"✅ <b>Адресу збережено!</b>\n\n"
        text += f"{saved_addr.emoji} <b>{saved_addr.name}</b>\n{address}\n\n"
        text += "━━━━━━━━━━━━━━━━━\n\n"
        text += "📍 <b>Ваші збережені адреси:</b>\n\n"
        
        for addr in addresses:
            text += f"{addr.emoji} <b>{addr.name}</b>\n   {addr.address[:45]}{'...' if len(addr.address) > 45 else ''}\n\n"
            buttons.append([InlineKeyboardButton(text=f"{addr.emoji} {addr.name}", callback_data=f"address:view:{addr.id}")])
        
        buttons.append([InlineKeyboardButton(text="➕ Додати ще адресу", callback_data="address:add")])
        
        # Оновити попереднє повідомлення або створити нове
        if last_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=last_msg_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )
                # Прибрати ReplyKeyboard
                from app.handlers.keyboards import main_menu_keyboard
                from app.storage.db import get_driver_by_tg_user_id
                
                is_admin = message.from_user.id in config.bot.admin_ids
                driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
                is_driver = driver is not None and driver.status == "approved"
                
                await message.answer(
                    "✅",
                    reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin)
                )
                return
            except:
                pass
        
        # Fallback - створити нове
        from app.handlers.keyboards import main_menu_keyboard
        from app.storage.db import get_driver_by_tg_user_id
        
        is_admin = message.from_user.id in config.bot.admin_ids
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        is_driver = driver is not None and driver.status == "approved"
        
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        
        await message.answer(
            "👌",
            reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin)
        )

    @router.message(SaveAddressStates.address)
    async def save_address_text(message: Message, state: FSMContext) -> None:
        """Зберегти текстову адресу"""
        if not message.from_user or not message.text:
            return
        
        # Видалити повідомлення користувача
        try:
            await message.delete()
        except:
            pass
        
        data = await state.get_data()
        address = message.text.strip()
        
        if len(address) < 5:
            error_msg = await message.answer("❌ Адреса занадто коротка. Спробуйте ще раз:")
            # Видалити помилку через 3 секунди
            import asyncio
            async def delete_after_delay():
                await asyncio.sleep(3)
                try:
                    await error_msg.delete()
                except:
                    pass
            asyncio.create_task(delete_after_delay())
            return
        
        # Спроба геокодувати
        lat, lon = None, None
        if config.google_maps_api_key:
            logger.info(f"🔑 API ключ присутній, геокодую: {address}")
            from app.utils.maps import geocode_address
            coords = await geocode_address(config.google_maps_api_key, address)
            if coords:
                lat, lon = coords
                logger.info(f"✅ Геокодування успішне: {lat}, {lon}")
            else:
                logger.warning(f"⚠️ Геокодування не вдалось для: {address}")
        else:
            logger.warning("⚠️ Google Maps API ключ відсутній")
        
        saved_addr = SavedAddress(
            id=None,
            user_id=message.from_user.id,
            name=data.get("name", "Адреса"),
            emoji=data.get("emoji", "📍"),
            address=address,
            lat=lat,
            lon=lon,
            created_at=datetime.now(timezone.utc)
        )
        
        await save_address(config.database_path, saved_addr)
        
        last_msg_id = data.get('last_message_id')
        await state.clear()
        
        # Показати успіх і повернутися до списку адрес (інлайн!)
        addresses = await get_user_saved_addresses(config.database_path, message.from_user.id)
        
        buttons = []
        text = f"✅ <b>Адресу збережено!</b>\n\n"
        text += f"{saved_addr.emoji} <b>{saved_addr.name}</b>\n{address}\n\n"
        text += "━━━━━━━━━━━━━━━━━\n\n"
        text += "📍 <b>Ваші збережені адреси:</b>\n\n"
        
        for addr in addresses:
            text += f"{addr.emoji} <b>{addr.name}</b>\n   {addr.address[:45]}{'...' if len(addr.address) > 45 else ''}\n\n"
            buttons.append([InlineKeyboardButton(text=f"{addr.emoji} {addr.name}", callback_data=f"address:view:{addr.id}")])
        
        buttons.append([InlineKeyboardButton(text="➕ Додати ще адресу", callback_data="address:add")])
        
        # Оновити попереднє повідомлення або створити нове
        if last_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=last_msg_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )
                return
            except:
                pass
        
        # Fallback - створити нове
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @router.callback_query(F.data.startswith("address:view:"))
    async def view_address(call: CallbackQuery) -> None:
        """Переглянути адресу"""
        if not call.from_user:
            return
        
        addr_id = int(call.data.split(":", 2)[2])
        address = await get_saved_address_by_id(config.database_path, addr_id, call.from_user.id)
        
        if not address:
            await call.answer("❌ Адресу не знайдено", show_alert=True)
            return
        
        await call.answer()
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🚖 Подати сюди", callback_data=f"use_address:pickup:{addr_id}"),
                    InlineKeyboardButton(text="🎯 Їхати сюди", callback_data=f"use_address:dest:{addr_id}")
                ],
                [
                    InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"address:edit:{addr_id}"),
                    InlineKeyboardButton(text="🗑️ Видалити", callback_data=f"address:delete:{addr_id}")
                ],
                [
                    InlineKeyboardButton(text="⬅️ Назад до списку", callback_data="address:list")
                ]
            ]
        )
        
        await call.message.edit_text(
            f"{address.emoji} <b>{address.name}</b>\n\n"
            f"📍 {address.address}\n\n"
            f"💡 Оберіть дію:",
            reply_markup=kb
        )

    @router.callback_query(F.data.startswith("address:edit:"))
    async def edit_address(call: CallbackQuery, state: FSMContext) -> None:
        """Редагувати адресу"""
        if not call.from_user:
            return
        
        addr_id = int(call.data.split(":", 2)[2])
        address = await get_saved_address_by_id(config.database_path, addr_id, call.from_user.id)
        
        if not address:
            await call.answer("❌ Адресу не знайдено", show_alert=True)
            return
        
        await call.answer()
        
        # Зберегти ID адреси для редагування
        await state.update_data(editing_address_id=addr_id, editing_address_current=address)
        await state.set_state(SaveAddressStates.name)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="address:cancel")]
        ])
        
        await call.message.edit_text(
            f"✏️ <b>Редагування адреси</b>\n\n"
            f"Поточна назва: <b>{address.name}</b>\n\n"
            f"Введіть нову назву або відправте ту саму:",
            reply_markup=kb
        )
    
    @router.callback_query(F.data.startswith("address:delete:"))
    async def delete_address(call: CallbackQuery) -> None:
        """Видалити адресу"""
        if not call.from_user:
            return
        
        addr_id = int(call.data.split(":", 2)[2])
        success = await delete_saved_address(config.database_path, addr_id, call.from_user.id)
        
        if success:
            await call.answer("✅ Адресу видалено", show_alert=True)
            
            # Оновити список
            addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
            
            if not addresses:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")]
                    ]
                )
                await call.message.edit_text(
                    "📍 <b>Збережені адреси</b>\n\n"
                    "У вас поки немає збережених адрес.",
                    reply_markup=kb
                )
            else:
                buttons = []
                text = "📍 <b>Збережені адреси</b>\n\n"
                for addr in addresses:
                    text += f"{addr.emoji} <b>{addr.name}</b>\n   {addr.address[:50]}{'...' if len(addr.address) > 50 else ''}\n\n"
                    buttons.append([InlineKeyboardButton(text=f"{addr.emoji} {addr.name}", callback_data=f"address:view:{addr.id}")])
                
                buttons.append([InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")])
                await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else:
            await call.answer("❌ Помилка", show_alert=True)

    @router.callback_query(F.data.startswith("use_address:"))
    async def use_saved_address(call: CallbackQuery, state: FSMContext) -> None:
        """Використати збережену адресу для замовлення"""
        if not call.from_user:
            return
        
        parts = call.data.split(":", 2)
        address_type = parts[1]  # pickup або dest
        addr_id = int(parts[2])
        
        address = await get_saved_address_by_id(config.database_path, addr_id, call.from_user.id)
        
        if not address:
            await call.answer("❌ Адресу не знайдено", show_alert=True)
            return
        
        await call.answer()
        
        # Перейти до замовлення з цією адресою
        from app.handlers.order import OrderStates
        
        if address_type == "pickup":
            # Використати як точку подачі
            await state.update_data(
                pickup=address.address,
                pickup_lat=address.lat,
                pickup_lon=address.lon
            )
            await state.set_state(OrderStates.destination)
            await call.message.answer(
                f"✅ Місце подачі: {address.emoji} {address.name}\n\n"
                "📍 <b>Куди їдемо?</b>\n\n"
                "Надішліть адресу або геолокацію"
            )
        else:
            # Використати як пункт призначення
            await state.update_data(
                destination=address.address,
                dest_lat=address.lat,
                dest_lon=address.lon
            )
            
            # Якщо є pickup - перейти до вибору класу авто
            data = await state.get_data()
            if data.get("pickup"):
                # Перейти до вибору класу (ціни покажуться в order.py)
                from app.handlers.order import OrderStates
                await state.set_state(OrderStates.car_class)
                await call.message.answer(
                    f"✅ Пункт призначення: {address.emoji} {address.name}\n\n"
                    "🚗 <b>Тепер оберіть клас авто</b>\n\n"
                    "Натисніть на кнопку нижче:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🚗 Обрати клас авто", callback_data="show_car_classes")]
                    ])
                )
            else:
                await state.set_state(OrderStates.pickup)
                await call.message.answer(
                    f"✅ Пункт призначення: {address.emoji} {address.name}\n\n"
                    "📍 <b>Звідки подати таксі?</b>\n\n"
                    "Надішліть адресу або геолокацію"
                )

    return router
