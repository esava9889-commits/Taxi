"""Модуль реєстрації клієнтів - оптимізований"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove

from app.config.config import AppConfig
from app.storage.db import User, upsert_user, get_user_by_id
from app.utils.validation import validate_phone_number, validate_name
from app.handlers.keyboards import main_menu_keyboard, contact_keyboard, city_selection_keyboard

logger = logging.getLogger(__name__)


class ClientRegStates(StatesGroup):
    """Стани реєстрації клієнта"""
    phone = State()
    city = State()


def create_registration_router(config: AppConfig) -> Router:
    """Створити роутер для реєстрації"""
    router = Router(name="registration")
    
    @router.callback_query(F.data == "register:start")
    @router.message(F.text == "📱 Зареєструватись")
    async def start_registration(event, state: FSMContext) -> None:
        """Початок реєстрації"""
        # Обробка як callback, так і message
        user_id = event.from_user.id if event.from_user else None
        if not user_id:
            return
        
        user = await get_user_by_id(config.database_path, user_id)
        if user and user.phone and user.city:
            # Перевірка чи це адмін
            is_admin = user_id in config.bot.admin_ids
            from app.storage.db import get_driver_by_tg_user_id
            driver = await get_driver_by_tg_user_id(config.database_path, user_id)
            is_driver = driver is not None and driver.status == "approved"
            
            text = f"✅ Ви вже зареєстровані!\n\n📍 Місто: {user.city}\n📱 Телефон: {user.phone}"
            if isinstance(event, CallbackQuery):
                await event.answer("Ви вже зареєстровані!")
                try:
                    await event.message.edit_text(text)
                except:
                    await event.message.answer(text)
                await event.message.answer("Головне меню:", reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin))
            else:
                await event.answer(text, reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin))
            return
        
        if isinstance(event, CallbackQuery):
            await event.answer()
        
        # Вибір міста
        text = "📍 <b>Крок 1/2: Оберіть ваше місто</b>\n\nВиберіть місто, в якому ви плануєте користуватися таксі:"
        kb = city_selection_keyboard()
        
        await state.set_state(ClientRegStates.city)
        
        if isinstance(event, CallbackQuery):
            # Зберегти message_id для редагування
            await state.update_data(reg_message_id=event.message.message_id)
            try:
                await event.message.edit_text(text, reply_markup=kb)
            except:
                msg = await event.message.answer(text, reply_markup=kb)
                await state.update_data(reg_message_id=msg.message_id)
        else:
            msg = await event.answer(text, reply_markup=kb)
            await state.update_data(reg_message_id=msg.message_id)
    
    @router.callback_query(F.data.startswith("city:"), ClientRegStates.city)
    async def select_city(call: CallbackQuery, state: FSMContext) -> None:
        """Вибір міста"""
        city = call.data.split(":", 1)[1]
        await state.update_data(city=city)
        await call.answer(f"✅ {city}")
        
        # Видалити попереднє повідомлення
        data = await state.get_data()
        reg_message_id = data.get("reg_message_id")
        if reg_message_id:
            try:
                await call.message.bot.delete_message(call.message.chat.id, reg_message_id)
            except:
                pass
        
        text = (
            f"✅ <b>Місто обрано:</b> {city}\n\n"
            "📱 <b>Крок 2/2: Надайте номер телефону</b>\n\n"
            "Це потрібно щоб водій міг з вами зв'язатись.\n\n"
            "Ви можете:\n"
            "• Поділитися контактом (кнопка нижче)\n"
            "• Ввести номер вручну"
        )
        
        # Кнопки: Назад + інструкція
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📝 Ввести номер вручну", callback_data="phone:manual")],
                [InlineKeyboardButton(text="⬅️ Назад до вибору міста", callback_data="register:back_to_city")]
            ]
        )
        
        await state.set_state(ClientRegStates.phone)
        
        msg = await call.message.answer(text, reply_markup=kb)
        await state.update_data(reg_message_id=msg.message_id)
        
        # Надіслати contact keyboard
        contact_msg = await call.message.answer(
            "👇 Натисніть кнопку нижче:",
            reply_markup=contact_keyboard()
        )
        await state.update_data(contact_message_id=contact_msg.message_id)
    
    @router.callback_query(F.data == "phone:manual", ClientRegStates.phone)
    async def phone_manual_entry(call: CallbackQuery, state: FSMContext) -> None:
        """Ручне введення номеру"""
        await call.answer()
        
        # Видалити попередні повідомлення
        data = await state.get_data()
        reg_message_id = data.get("reg_message_id")
        contact_message_id = data.get("contact_message_id")
        
        if reg_message_id:
            try:
                await call.message.bot.delete_message(call.message.chat.id, reg_message_id)
            except:
                pass
        if contact_message_id:
            try:
                await call.message.bot.delete_message(call.message.chat.id, contact_message_id)
            except:
                pass
        
        city = data.get("city", "Місто")
        
        text = (
            f"✅ <b>Місто:</b> {city}\n\n"
            "📱 <b>Введіть номер телефону</b>\n\n"
            "<b>Приклади правильних форматів:</b>\n"
            "• +380 67 123 45 67\n"
            "• +380671234567\n"
            "• 0671234567"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="register:back_to_phone")]
            ]
        )
        
        msg = await call.message.answer(text, reply_markup=kb)
        await state.update_data(reg_message_id=msg.message_id, contact_message_id=None)
        
        # Прибрати contact keyboard
        await call.message.answer("✍️ Введіть номер:", reply_markup=ReplyKeyboardRemove())
    
    @router.callback_query(F.data == "register:back_to_city", ClientRegStates.phone)
    async def back_to_city(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до вибору міста"""
        await call.answer()
        
        # Видалити попередні повідомлення
        data = await state.get_data()
        reg_message_id = data.get("reg_message_id")
        contact_message_id = data.get("contact_message_id")
        
        if reg_message_id:
            try:
                await call.message.bot.delete_message(call.message.chat.id, reg_message_id)
            except:
                pass
        if contact_message_id:
            try:
                await call.message.bot.delete_message(call.message.chat.id, contact_message_id)
            except:
                pass
        
        await state.set_state(ClientRegStates.city)
        
        text = "📍 <b>Крок 1/2: Оберіть ваше місто</b>\n\nВиберіть місто, в якому ви плануєте користуватися таксі:"
        kb = city_selection_keyboard()
        
        msg = await call.message.answer(text, reply_markup=kb)
        await state.update_data(reg_message_id=msg.message_id, contact_message_id=None)
    
    @router.callback_query(F.data == "register:back_to_phone")
    async def back_to_phone_choice(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до вибору способу введення телефону"""
        await call.answer()
        
        # Видалити попереднє повідомлення
        data = await state.get_data()
        reg_message_id = data.get("reg_message_id")
        if reg_message_id:
            try:
                await call.message.bot.delete_message(call.message.chat.id, reg_message_id)
            except:
                pass
        
        city = data.get("city", "Місто")
        
        text = (
            f"✅ <b>Місто обрано:</b> {city}\n\n"
            "📱 <b>Крок 2/2: Надайте номер телефону</b>\n\n"
            "Це потрібно щоб водій міг з вами зв'язатись.\n\n"
            "Ви можете:\n"
            "• Поділитися контактом (кнопка нижче)\n"
            "• Ввести номер вручну"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📝 Ввести номер вручну", callback_data="phone:manual")],
                [InlineKeyboardButton(text="⬅️ Назад до вибору міста", callback_data="register:back_to_city")]
            ]
        )
        
        msg = await call.message.answer(text, reply_markup=kb)
        await state.update_data(reg_message_id=msg.message_id)
        
        # Повернути contact keyboard
        contact_msg = await call.message.answer(
            "👇 Або поділіться контактом:",
            reply_markup=contact_keyboard()
        )
        await state.update_data(contact_message_id=contact_msg.message_id)
    
    @router.message(ClientRegStates.phone, F.contact)
    async def save_phone_contact(message: Message, state: FSMContext) -> None:
        """Збереження телефону через контакт"""
        if not message.from_user or not message.contact:
            return
        
        data = await state.get_data()
        city = data.get("city")
        phone = message.contact.phone_number
        
        # ВАЛІДАЦІЯ: Перевірка номеру телефону
        is_valid, cleaned_phone = validate_phone_number(phone)
        if not is_valid:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="register:back_to_phone")]
                ]
            )
            await message.answer(
                "❌ <b>Невірний формат номеру телефону</b>\n\n"
                "Спробуйте ще раз або введіть вручну.\n"
                "Приклад: +380 67 123 45 67",
                reply_markup=kb
            )
            logger.warning(f"Invalid phone number from contact: {phone}")
            return
        
        # Валідація імені
        user_name = message.from_user.full_name or "Користувач"
        is_valid_name, cleaned_name = validate_name(user_name)
        if not is_valid_name:
            cleaned_name = "Користувач"
            logger.warning(f"Invalid name: {user_name}, using default")
        
        user = User(
            user_id=message.from_user.id,
            full_name=cleaned_name,
            phone=cleaned_phone,
            role="client",
            city=city,
            created_at=datetime.now(timezone.utc),
        )
        await upsert_user(config.database_path, user)
        
        # Видалити всі повідомлення реєстрації
        data = await state.get_data()
        reg_message_id = data.get("reg_message_id")
        contact_message_id = data.get("contact_message_id")
        
        # Видалити повідомлення "Крок 2/2"
        if reg_message_id:
            try:
                await message.bot.delete_message(message.chat.id, reg_message_id)
            except:
                pass
        
        # Видалити повідомлення "👇 Натисніть кнопку"
        if contact_message_id:
            try:
                await message.bot.delete_message(message.chat.id, contact_message_id)
            except:
                pass
        
        # Видалити повідомлення користувача з контактом
        try:
            await message.delete()
        except:
            pass
        
        await state.clear()
        
        # Перевірка чи це адмін
        is_admin = message.from_user.id in config.bot.admin_ids
        
        await message.answer(
            f"✅ <b>Реєстрація завершена!</b>\n\n"
            f"🎉 Ласкаво просимо, {cleaned_name}!\n\n"
            f"📱 Телефон: {cleaned_phone}\n"
            f"📍 Місто: {city}\n\n"
            "Тепер ви можете замовити таксі через меню внизу 👇",
            reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin),
            parse_mode="HTML"
        )
        logger.info(f"User {message.from_user.id} registered in {city} with phone {cleaned_phone}")
    
    @router.message(ClientRegStates.phone)
    async def save_phone_text(message: Message, state: FSMContext) -> None:
        """Збереження телефону текстом"""
        if not message.from_user:
            return
        
        phone = message.text.strip() if message.text else ""
        
        # ВАЛІДАЦІЯ: Перевірка номеру телефону
        is_valid, cleaned_phone = validate_phone_number(phone)
        if not is_valid:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="register:back_to_phone")]
                ]
            )
            await message.answer(
                "❌ <b>Невірний формат номеру телефону</b>\n\n"
                "Перевірте формат та спробуйте ще раз.\n\n"
                "<b>Приклади правильних форматів:</b>\n"
                "• +380 67 123 45 67\n"
                "• +380671234567\n"
                "• 0671234567\n\n"
                "❗️ Номер має містити 10-12 цифр",
                reply_markup=kb
            )
            logger.warning(f"Invalid phone number: {phone}")
            return
        
        data = await state.get_data()
        city = data.get("city")
        
        # Валідація імені
        user_name = message.from_user.full_name or "Користувач"
        is_valid_name, cleaned_name = validate_name(user_name)
        if not is_valid_name:
            cleaned_name = "Користувач"
            logger.warning(f"Invalid name: {user_name}, using default")
        
        user = User(
            user_id=message.from_user.id,
            full_name=cleaned_name,
            phone=cleaned_phone,
            role="client",
            city=city,
            created_at=datetime.now(timezone.utc),
        )
        await upsert_user(config.database_path, user)
        
        # Видалити всі повідомлення реєстрації
        data = await state.get_data()
        reg_message_id = data.get("reg_message_id")
        contact_message_id = data.get("contact_message_id")
        
        if reg_message_id:
            try:
                await message.bot.delete_message(message.chat.id, reg_message_id)
            except:
                pass
        if contact_message_id:
            try:
                await message.bot.delete_message(message.chat.id, contact_message_id)
            except:
                pass
        
        # Видалити повідомлення користувача з номером
        try:
            await message.delete()
        except:
            pass
        
        await state.clear()
        
        # Перевірка чи це адмін
        is_admin = message.from_user.id in config.bot.admin_ids
        
        await message.answer(
            f"✅ <b>Реєстрація завершена!</b>\n\n"
            f"🎉 Ласкаво просимо, {cleaned_name}!\n\n"
            f"📱 Телефон: {cleaned_phone}\n"
            f"📍 Місто: {city}\n\n"
            "Тепер ви можете замовити таксі через меню внизу 👇",
            reply_markup=main_menu_keyboard(is_registered=True, is_admin=is_admin),
            parse_mode="HTML"
        )
        logger.info(f"User {message.from_user.id} registered in {city} with phone {cleaned_phone}")
    
    return router
