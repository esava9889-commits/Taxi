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

    @router.message(F.text == "📍 Мої адреси")
    async def show_saved_addresses(message: Message) -> None:
        """Показати збережені адреси"""
        if not message.from_user:
            return
        
        addresses = await get_user_saved_addresses(config.database_path, message.from_user.id)
        
        if not addresses:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")]
                ]
            )
            await message.answer(
                "📍 <b>Збережені адреси</b>\n\n"
                "У вас поки немає збережених адрес.\n\n"
                "Збережіть часто використовувані адреси для швидкого замовлення!",
                reply_markup=kb
            )
            return
        
        # Кнопки для кожної адреси
        buttons = []
        for addr in addresses:
            buttons.append([
                InlineKeyboardButton(
                    text=f"{addr.emoji} {addr.name}",
                    callback_data=f"address:view:{addr.id}"
                )
            ])
        
        buttons.append([InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        text = "📍 <b>Збережені адреси</b>\n\n"
        for addr in addresses:
            text += f"{addr.emoji} <b>{addr.name}</b>\n"
            text += f"   {addr.address[:50]}{'...' if len(addr.address) > 50 else ''}\n\n"
        
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "address:add")
    async def start_add_address(call: CallbackQuery, state: FSMContext) -> None:
        """Почати додавання адреси"""
        await call.answer()
        await state.set_state(SaveAddressStates.name)
        await call.message.answer(
            "📝 <b>Додавання адреси</b>\n\n"
            "Введіть назву адреси (наприклад: Додому, На роботу, До батьків):"
        )

    @router.message(SaveAddressStates.name)
    async def save_name(message: Message, state: FSMContext) -> None:
        """Зберегти назву адреси"""
        name = message.text.strip() if message.text else ""
        if len(name) < 2:
            await message.answer("❌ Назва занадто коротка. Спробуйте ще раз:")
            return
        
        await state.update_data(name=name)
        await state.set_state(SaveAddressStates.emoji)
        
        # Запропонувати емодзі
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
                [InlineKeyboardButton(text="⏩ Пропустити", callback_data="emoji:📍")]
            ]
        )
        await message.answer(
            f"✅ Назва: <b>{name}</b>\n\n"
            "Оберіть емодзі для адреси:",
            reply_markup=kb
        )

    @router.callback_query(F.data.startswith("emoji:"))
    async def save_emoji(call: CallbackQuery, state: FSMContext) -> None:
        """Зберегти емодзі"""
        emoji = call.data.split(":", 1)[1]
        await state.update_data(emoji=emoji)
        await state.set_state(SaveAddressStates.address)
        
        await call.answer()
        
        # Кнопка для надсилання локації
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
                [KeyboardButton(text="❌ Скасувати")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await call.message.answer(
            f"✅ Емодзі: {emoji}\n\n"
            "Тепер надішліть адресу або геолокацію:",
            reply_markup=kb
        )

    @router.message(SaveAddressStates.address, F.location)
    async def save_address_location(message: Message, state: FSMContext) -> None:
        """Зберегти адресу з геолокації"""
        if not message.from_user or not message.location:
            return
        
        data = await state.get_data()
        loc = message.location
        
        # Reverse geocoding - отримати адресу з координат
        address = f"📍 {loc.latitude:.6f}, {loc.longitude:.6f}"
        
        if config.google_maps_api_key:
            from app.utils.maps import reverse_geocode
            readable_address = await reverse_geocode(
                config.google_maps_api_key,
                loc.latitude,
                loc.longitude
            )
            if readable_address:
                address = readable_address
                logger.info(f"✅ Reverse geocoded: {address}")
        
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
        await state.clear()
        
        # Повернути головне меню
        from app.handlers.start import main_menu_keyboard
        user_data = await state.get_data()
        is_admin = message.from_user.id in config.bot.admin_ids
        
        await message.answer(
            f"✅ Адресу збережено!\n\n"
            f"{saved_addr.emoji} <b>{saved_addr.name}</b>\n"
            f"{address}",
            reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
        )

    @router.message(SaveAddressStates.address)
    async def save_address_text(message: Message, state: FSMContext) -> None:
        """Зберегти текстову адресу"""
        if not message.from_user or not message.text:
            return
        
        if message.text == "❌ Скасувати":
            await state.clear()
            from app.handlers.start import main_menu_keyboard
            is_admin = message.from_user.id in config.bot.admin_ids
            await message.answer(
                "❌ Скасовано",
                reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
            )
            return
        
        data = await state.get_data()
        address = message.text.strip()
        
        if len(address) < 5:
            await message.answer("❌ Адреса занадто коротка. Спробуйте ще раз:")
            return
        
        # Спроба геокодувати
        lat, lon = None, None
        if config.google_maps_api_key:
            from app.utils.maps import geocode_address
            coords = await geocode_address(config.google_maps_api_key, address)
            if coords:
                lat, lon = coords
        
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
        await state.clear()
        
        from app.handlers.start import main_menu_keyboard
        is_admin = message.from_user.id in config.bot.admin_ids
        
        await message.answer(
            f"✅ Адресу збережено!\n\n"
            f"{saved_addr.emoji} <b>{saved_addr.name}</b>\n"
            f"{address}",
            reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin)
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
                ]
            ]
        )
        
        await call.message.edit_text(
            f"{address.emoji} <b>{address.name}</b>\n\n"
            f"📍 {address.address}\n\n"
            f"💡 Оберіть дію:",
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
            
            # Якщо є pickup - перейти до коментаря
            data = await state.get_data()
            if data.get("pickup"):
                await state.set_state(OrderStates.comment)
                await call.message.answer(
                    f"✅ Пункт призначення: {address.emoji} {address.name}\n\n"
                    "💬 <b>Додайте коментар</b> (опціонально):\n\n"
                    "Або натисніть 'Пропустити'"
                )
            else:
                await state.set_state(OrderStates.pickup)
                await call.message.answer(
                    f"✅ Пункт призначення: {address.emoji} {address.name}\n\n"
                    "📍 <b>Звідки подати таксі?</b>\n\n"
                    "Надішліть адресу або геолокацію"
                )

    return router
