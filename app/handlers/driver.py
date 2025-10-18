from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

logger = logging.getLogger(__name__)

from app.config.config import AppConfig, AVAILABLE_CITIES
from app.storage.db import (
    Driver,
    create_driver_application,
    fetch_pending_drivers,
    get_driver_by_tg_user_id,
    get_driver_by_id,
    update_driver_status,
)


CANCEL_TEXT = "❌ Скасувати"


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


class DriverRegStates(StatesGroup):
    name = State()
    phone = State()
    city = State()
    car_make = State()
    car_model = State()
    car_plate = State()
    car_class = State()
    license_photo = State()
    confirm = State()


async def show_driver_application_status(message: Message, driver: Driver, config: AppConfig) -> None:
    """Показати статус заявки водія з відповідними кнопками"""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from datetime import datetime, timezone, timedelta
    
    if driver.status == "pending":
        # Перевірити чи заявка не застаріла (>3 години)
        application_time = driver.created_at
        now = datetime.now(timezone.utc)
        hours_waiting = (now - application_time).total_seconds() / 3600
        
        buttons = []
        
        if hours_waiting > 3:
            # Більше 3 годин → дозволити скасувати
            text = (
                f"⏳ <b>Ваша заявка на розгляді</b>\n\n"
                f"📝 ПІБ: {driver.full_name}\n"
                f"📱 Телефон: {driver.phone}\n"
                f"📍 Місто: {driver.city or 'Не вказано'}\n"
                f"🚙 Авто: {driver.car_make} {driver.car_model}\n\n"
                f"⏰ Очікування: {int(hours_waiting)} год\n\n"
                f"⚠️ <b>Заявка чекає вже більше 3 годин.</b>\n\n"
                f"Ви можете:\n"
                f"• Продовжити чекати на розгляд\n"
                f"• Скасувати заявку і зареєструватися як клієнт"
            )
            buttons.append([InlineKeyboardButton(
                text="❌ Скасувати заявку", 
                callback_data=f"driver_cancel:{driver.id}"
            )])
        else:
            # Менше 3 годин → тільки інформація
            hours_left = max(0, 3 - hours_waiting)
            text = (
                f"⏳ <b>Ваша заявка на розгляді</b>\n\n"
                f"📝 ПІБ: {driver.full_name}\n"
                f"📱 Телефон: {driver.phone}\n"
                f"📍 Місто: {driver.city or 'Не вказано'}\n"
                f"🚙 Авто: {driver.car_make} {driver.car_model}\n\n"
                f"⏰ Очікування: {int(hours_waiting * 60)} хв\n"
                f"⌛️ Зачекайте ще ~{int(hours_left * 60)} хв\n\n"
                f"✅ Адміністратор розгляне вашу заявку найближчим часом.\n\n"
                f"ℹ️ Зазвичай це займає до 3 годин."
            )
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        await message.answer(text, reply_markup=kb)
    
    elif driver.status == "rejected":
        # Відхилено → дозволити подати знову
        text = (
            f"❌ <b>Вашу заявку відхилено</b>\n\n"
            f"На жаль, адміністратор відхилив вашу заявку.\n\n"
            f"Ви можете:\n"
            f"• Видалити заявку і зареєструватися як клієнт\n"
            f"• Зв'язатися з адміністратором для з'ясування причин"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🗑 Видалити заявку і стати клієнтом", 
                    callback_data=f"driver_delete:{driver.id}"
                )]
            ]
        )
        await message.answer(text, reply_markup=kb)
    
    elif driver.status == "approved":
        # Підтверджено → показати меню водія
        text = (
            f"✅ <b>Ви вже водій!</b>\n\n"
            f"📝 ПІБ: {driver.full_name}\n"
            f"📍 Місто: {driver.city or 'Не вказано'}\n"
            f"🚙 Авто: {driver.car_make} {driver.car_model} ({driver.car_plate})\n\n"
            f"Використовуйте кнопку <b>'🚗 Панель водія'</b> для роботи."
        )
        await message.answer(text)


def create_router(config: AppConfig) -> Router:
    router = Router(name="driver")

    # Public: entrypoint for driver registration
    @router.message(F.text == "🚗 Стати водієм")
    @router.message(Command("register_driver"))
    async def start_driver_registration(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        
        # ВАЖЛИВО: Заборонити ботам реєструватися як водії
        if message.from_user.is_bot:
            await message.answer(
                "❌ <b>Помилка</b>\n\n"
                "Боти не можуть реєструватися як водії.\n"
                "Використовуйте особистий акаунт Telegram.",
                parse_mode="HTML"
            )
            logger.warning(f"Bot {message.from_user.id} tried to register as driver")
            return
        
        # Check if already a driver
        existing = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if existing:
            # Показати ДЕТАЛЬНИЙ статус з кнопками
            await show_driver_application_status(message, existing, config)
            return
        
        # ВАЖЛИВЕ ПОПЕРЕДЖЕННЯ: якщо клієнт стає водієм
        from app.storage.db import get_user_by_id, delete_user
        import logging
        logger = logging.getLogger(__name__)
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        if user and user.role == "client":
            # Показати попередження
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Так, продовжити", callback_data="driver_reg:confirm")],
                    [InlineKeyboardButton(text="❌ Ні, скасувати", callback_data="driver_reg:cancel")]
                ]
            )
            
            await message.answer(
                "⚠️ <b>ВАЖЛИВО!</b>\n\n"
                "Ви зараз зареєстровані як <b>клієнт</b>.\n\n"
                "Якщо ви станете <b>водієм</b>:\n"
                "• Ви втратите доступ до панелі клієнта\n"
                "• Не зможете створювати замовлення\n"
                "• Будете тільки приймати замовлення як водій\n\n"
                "⚠️ <b>Одна людина = одна роль!</b>\n"
                "(або клієнт, або водій)\n\n"
                "Продовжити реєстрацію водія?",
                reply_markup=kb
            )
            return
        
        await state.set_state(DriverRegStates.name)
        await message.answer(
            "🚗 <b>Реєстрація водія</b>\n\n"
            "📝 Крок 1/7: Введіть ваше ПІБ:",
            reply_markup=cancel_keyboard()
        )
    
    @router.callback_query(F.data == "driver_reg:confirm")
    async def driver_reg_confirm(call: CallbackQuery, state: FSMContext) -> None:
        """Підтвердження переходу з клієнта на водія"""
        if not call.from_user:
            return
        
        from app.storage.db import delete_user
        import logging
        logger = logging.getLogger(__name__)
        
        # Видалити користувача з таблиці users
        deleted = await delete_user(config.database_path, call.from_user.id)
        if deleted:
            logger.info(f"✅ Користувач {call.from_user.id} видалений з clients (стає водієм)")
        
        await call.answer("✅ Переходимо до реєстрації водія")
        await call.message.delete()
        
        await state.set_state(DriverRegStates.name)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
            ]
        )
        
        msg = await call.message.answer(
            "🚗 <b>Реєстрація водія</b>\n\n"
            "📝 <b>Крок 1/8: Введіть ваше ПІБ</b>\n\n"
            "Приклад: Іванов Іван Іванович",
            reply_markup=kb
        )
        await state.update_data(reg_message_id=msg.message_id)
    
    @router.callback_query(F.data == "driver_reg:cancel")
    @router.callback_query(F.data == "driver_reg:cancel_start")
    async def driver_reg_cancel_callback(call: CallbackQuery, state: FSMContext) -> None:
        """Скасування реєстрації водія"""
        if not call.from_user:
            return
        
        await call.answer("❌ Реєстрацію скасовано")
        await state.clear()
        
        try:
            await call.message.delete()
        except:
            pass
        
        from app.handlers.keyboards import main_menu_keyboard
        is_admin = call.from_user.id in config.bot.admin_ids
        
        await call.message.answer(
            "❌ Реєстрацію водія скасовано.\n\n"
            "Ви залишаєтесь клієнтом.",
            reply_markup=main_menu_keyboard(is_registered=True, is_driver=False, is_admin=is_admin)
        )
    
    # Обробники кнопок "Назад" для реєстрації водія
    @router.callback_query(F.data == "driver:back_to_name")
    async def back_to_name(call: CallbackQuery, state: FSMContext) -> None:
        """Назад до введення ПІБ"""
        await call.answer()
        await state.set_state(DriverRegStates.name)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
            ]
        )
        
        try:
            await call.message.edit_text(
                "🚗 <b>Реєстрація водія</b>\n\n"
                "📝 <b>Крок 1/8: Введіть ваше ПІБ</b>\n\n"
                "Приклад: Іванов Іван Іванович",
                reply_markup=kb
            )
        except:
            await call.message.answer(
                "🚗 <b>Реєстрація водія</b>\n\n"
                "📝 <b>Крок 1/8: Введіть ваше ПІБ</b>\n\n"
                "Приклад: Іванов Іван Іванович",
                reply_markup=kb
            )
    
    @router.callback_query(F.data == "driver:back_to_phone")
    async def back_to_phone(call: CallbackQuery, state: FSMContext) -> None:
        """Назад до введення телефону"""
        await call.answer()
        await state.set_state(DriverRegStates.phone)
        
        data = await state.get_data()
        full_name = data.get("full_name", "")
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад до ПІБ", callback_data="driver:back_to_name")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
            ]
        )
        
        try:
            await call.message.edit_text(
                f"✅ <b>ПІБ:</b> {full_name}\n\n"
                "📱 <b>Крок 2/8: Номер телефону</b>\n\n"
                "Введіть ваш номер телефону:\n\n"
                "Приклад: +380 67 123 45 67",
                reply_markup=kb
            )
        except:
            await call.message.answer(
                f"✅ <b>ПІБ:</b> {full_name}\n\n"
                "📱 <b>Крок 2/8: Номер телефону</b>\n\n"
                "Введіть ваш номер телефону:\n\n"
                "Приклад: +380 67 123 45 67",
                reply_markup=kb
            )
    
    @router.callback_query(F.data == "driver:back_to_city")
    async def back_to_city(call: CallbackQuery, state: FSMContext) -> None:
        """Назад до вибору міста"""
        await call.answer()
        await state.set_state(DriverRegStates.city)
        
        from app.handlers.keyboards import driver_city_selection_keyboard
        
        try:
            await call.message.edit_text(
                "🏙 <b>Крок 3/8: Місто роботи</b>\n\n"
                "Оберіть місто, в якому ви будете працювати:",
                reply_markup=driver_city_selection_keyboard()
            )
        except:
            await call.message.answer(
                "🏙 <b>Крок 3/8: Місто роботи</b>\n\n"
                "Оберіть місто, в якому ви будете працювати:",
                reply_markup=driver_city_selection_keyboard()
            )
    
    @router.callback_query(F.data == "driver:back_to_make")
    async def back_to_make(call: CallbackQuery, state: FSMContext) -> None:
        """Назад до введення марки"""
        await call.answer()
        await state.set_state(DriverRegStates.car_make)
        
        data = await state.get_data()
        city = data.get("city", "")
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад до міста", callback_data="driver:back_to_city")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
            ]
        )
        
        try:
            await call.message.edit_text(
                f"✅ <b>Місто:</b> {city}\n\n"
                "🚗 <b>Крок 4/8: Марка автомобіля</b>\n\n"
                "Введіть марку вашого авто:\n\n"
                "Приклад: Toyota, Volkswagen, BMW",
                reply_markup=kb
            )
        except:
            await call.message.answer(
                f"✅ <b>Місто:</b> {city}\n\n"
                "🚗 <b>Крок 4/8: Марка автомобіля</b>\n\n"
                "Введіть марку вашого авто:\n\n"
                "Приклад: Toyota, Volkswagen, BMW",
                reply_markup=kb
            )
    
    @router.callback_query(F.data == "driver:back_to_model")
    async def back_to_model(call: CallbackQuery, state: FSMContext) -> None:
        """Назад до введення моделі"""
        await call.answer()
        await state.set_state(DriverRegStates.car_model)
        
        data = await state.get_data()
        car_make = data.get("car_make", "")
        reg_message_id = data.get("reg_message_id")
        
        # Видалити попереднє повідомлення
        if reg_message_id:
            try:
                await call.message.bot.delete_message(call.message.chat.id, reg_message_id)
            except:
                pass
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад до марки", callback_data="driver:back_to_make")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
            ]
        )
        
        msg = await call.message.answer(
            f"✅ <b>Марка:</b> {car_make}\n\n"
            "🚙 <b>Крок 5/8: Модель автомобіля</b>\n\n"
            "Введіть модель вашого авто:\n\n"
            "Приклад: Camry, Passat, X5",
            reply_markup=kb
        )
        await state.update_data(reg_message_id=msg.message_id)
    
    @router.callback_query(F.data == "driver:back_to_plate")
    async def back_to_plate(call: CallbackQuery, state: FSMContext) -> None:
        """Назад до введення номерного знаку"""
        await call.answer()
        await state.set_state(DriverRegStates.car_plate)
        
        data = await state.get_data()
        car_make = data.get("car_make", "")
        car_model = data.get("car_model", "")
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад до моделі", callback_data="driver:back_to_model")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
            ]
        )
        
        msg = await call.message.answer(
            f"✅ <b>Авто:</b> {car_make} {car_model}\n\n"
            "🔢 <b>Крок 6/8: Номерний знак</b>\n\n"
            "Введіть номерний знак авто:\n\n"
            "Приклад: АА1234ВВ, КА5678ІН",
            reply_markup=kb
        )
        await state.update_data(reg_message_id=msg.message_id)
    
    @router.callback_query(F.data.startswith("driver_cancel:"))
    async def cancel_pending_application(call: CallbackQuery) -> None:
        """Скасувати заявку що очікує (>3 год)"""
        if not call.from_user:
            return
        
        driver_id = int(call.data.split(":", 1)[1])
        
        # Перевірити що це заявка користувача
        driver = await get_driver_by_id(config.database_path, driver_id)
        if not driver or driver.tg_user_id != call.from_user.id:
            await call.answer("❌ Це не ваша заявка", show_alert=True)
            return
        
        # Видалити заявку
        import aiosqlite
        async with aiosqlite.connect(config.database_path) as db:
            await db.execute("DELETE FROM drivers WHERE id = ?", (driver_id,))
            await db.commit()
        
        await call.answer("✅ Заявку скасовано")
        await call.message.delete()
        
        from app.handlers.keyboards import main_menu_keyboard
        is_admin = call.from_user.id in config.bot.admin_ids
        
        await call.message.answer(
            "❌ <b>Заявку водія скасовано</b>\n\n"
            "Тепер ви можете:\n"
            "• Зареєструватися як клієнт\n"
            "• Подати нову заявку водія",
            reply_markup=main_menu_keyboard(is_registered=False, is_driver=False, is_admin=is_admin)
        )
    
    @router.callback_query(F.data.startswith("driver_delete:"))
    async def delete_rejected_application(call: CallbackQuery) -> None:
        """Видалити відхилену заявку"""
        if not call.from_user:
            return
        
        driver_id = int(call.data.split(":", 1)[1])
        
        # Перевірити що це заявка користувача
        driver = await get_driver_by_id(config.database_path, driver_id)
        if not driver or driver.tg_user_id != call.from_user.id:
            await call.answer("❌ Це не ваша заявка", show_alert=True)
            return
        
        if driver.status != "rejected":
            await call.answer("❌ Заявка не відхилена", show_alert=True)
            return
        
        # Видалити заявку
        import aiosqlite
        async with aiosqlite.connect(config.database_path) as db:
            await db.execute("DELETE FROM drivers WHERE id = ?", (driver_id,))
            await db.commit()
        
        await call.answer("✅ Заявку видалено")
        await call.message.delete()
        
        from app.handlers.keyboards import main_menu_keyboard
        is_admin = call.from_user.id in config.bot.admin_ids
        
        await call.message.answer(
            "🗑 <b>Заявку водія видалено</b>\n\n"
            "Тепер ви можете зареєструватися як клієнт.",
            reply_markup=main_menu_keyboard(
                is_registered=False, 
                is_driver=False, 
                is_admin=is_admin,
                has_driver_application=False
            )
        )
    
    @router.callback_query(F.data == "driver_status:check")
    async def check_driver_status(call: CallbackQuery) -> None:
        """Перевірити статус заявки водія"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Заявка не знайдена", show_alert=True)
            return
        
        await call.answer()
        await call.message.delete()
        
        # Показати актуальний статус
        from aiogram import types
        await show_driver_application_status(
            types.Message(
                message_id=call.message.message_id,
                date=call.message.date,
                chat=call.message.chat,
                from_user=call.from_user,
                bot=call.bot
            ),
            driver,
            config
        )

    @router.message(F.text == CANCEL_TEXT)
    async def cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        from app.handlers.keyboards import main_menu_keyboard
        is_admin = message.from_user.id in config.bot.admin_ids if message.from_user else False
        await message.answer(
            "❌ Реєстрацію скасовано.",
            reply_markup=main_menu_keyboard(is_registered=False, is_driver=False, is_admin=is_admin)
        )

    @router.message(DriverRegStates.name)
    async def take_name(message: Message, state: FSMContext) -> None:
        full_name = message.text.strip() if message.text else ""
        if len(full_name) < 3:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
                ]
            )
            await message.answer(
                "❌ <b>Невірний формат</b>\n\n"
                "ПІБ має містити мінімум 3 символи.\n\n"
                "Спробуйте ще раз:",
                reply_markup=kb
            )
            return
        await state.update_data(full_name=full_name)
        await state.set_state(DriverRegStates.phone)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад до ПІБ", callback_data="driver:back_to_name")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
            ]
        )
        
        # Видалити попереднє повідомлення та повідомлення користувача
        data = await state.get_data()
        reg_message_id = data.get("reg_message_id")
        if reg_message_id:
            try:
                await message.bot.delete_message(message.chat.id, reg_message_id)
            except:
                pass
        
        try:
            await message.delete()
        except:
            pass
        
        msg = await message.answer(
            f"✅ <b>ПІБ:</b> {full_name}\n\n"
            "📱 <b>Крок 2/8: Номер телефону</b>\n\n"
            "Введіть ваш номер телефону:\n\n"
            "Приклад: +380 67 123 45 67",
            reply_markup=kb
        )
        await state.update_data(reg_message_id=msg.message_id)

    @router.message(DriverRegStates.phone)
    async def take_phone(message: Message, state: FSMContext) -> None:
        phone = message.text.strip() if message.text else ""
        if len(phone) < 7:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад до ПІБ", callback_data="driver:back_to_name")],
                    [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
                ]
            )
            await message.answer(
                "❌ <b>Невірний формат</b>\n\n"
                "Номер телефону має містити мінімум 7 символів.\n\n"
                "Спробуйте ще раз:",
                reply_markup=kb
            )
            return
        await state.update_data(phone=phone)
        
        # City selection with inline buttons
        from app.handlers.keyboards import driver_city_selection_keyboard
        await state.set_state(DriverRegStates.city)
        
        # Видалити попереднє та поточне повідомлення користувача
        data = await state.get_data()
        reg_message_id = data.get("reg_message_id")
        if reg_message_id:
            try:
                await message.bot.delete_message(message.chat.id, reg_message_id)
            except:
                pass
        
        try:
            await message.delete()
        except:
            pass
        
        msg = await message.answer(
            f"✅ <b>Телефон:</b> {phone}\n\n"
            "🏙 <b>Крок 3/8: Місто роботи</b>\n\n"
            "Оберіть місто, в якому ви будете працювати:",
            reply_markup=driver_city_selection_keyboard()
        )
        await state.update_data(reg_message_id=msg.message_id)

    @router.callback_query(F.data.startswith("driver_city:"), DriverRegStates.city)
    async def take_city(call: CallbackQuery, state: FSMContext) -> None:
        city = call.data.split(":", 1)[1]
        await state.update_data(city=city)
        await call.answer(f"✅ {city}")
        
        await state.set_state(DriverRegStates.car_make)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад до телефону", callback_data="driver:back_to_phone")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
            ]
        )
        
        try:
            await call.message.edit_text(
                f"✅ <b>Місто:</b> {city}\n\n"
                "🚗 <b>Крок 4/8: Марка автомобіля</b>\n\n"
                "Введіть марку вашого авто:\n\n"
                "Приклад: Toyota, Volkswagen, BMW",
                reply_markup=kb
            )
        except:
            await call.message.answer(
                f"✅ <b>Місто:</b> {city}\n\n"
                "🚗 <b>Крок 4/8: Марка автомобіля</b>\n\n"
                "Введіть марку вашого авто:\n\n"
                "Приклад: Toyota, Volkswagen, BMW",
                reply_markup=kb
            )

    @router.message(DriverRegStates.car_make)
    async def take_car_make(message: Message, state: FSMContext) -> None:
        car_make = message.text.strip() if message.text else ""
        if len(car_make) < 2:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад до міста", callback_data="driver:back_to_city")],
                    [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
                ]
            )
            await message.answer(
                "❌ <b>Невірний формат</b>\n\n"
                "Марка авто має містити мінімум 2 символи.\n\n"
                "Спробуйте ще раз:",
                reply_markup=kb
            )
            return
        await state.update_data(car_make=car_make)
        await state.set_state(DriverRegStates.car_model)
        
        # Видалити попереднє та поточне повідомлення користувача
        data = await state.get_data()
        reg_message_id = data.get("reg_message_id")
        if reg_message_id:
            try:
                await message.bot.delete_message(message.chat.id, reg_message_id)
            except:
                pass
        
        try:
            await message.delete()
        except:
            pass
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад до міста", callback_data="driver:back_to_city")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
            ]
        )
        
        msg = await message.answer(
            f"✅ <b>Марка:</b> {car_make}\n\n"
            "🚙 <b>Крок 5/8: Модель автомобіля</b>\n\n"
            "Введіть модель вашого авто:\n\n"
            "Приклад: Camry, Passat, X5",
            reply_markup=kb
        )
        await state.update_data(reg_message_id=msg.message_id)

    @router.message(DriverRegStates.car_model)
    async def take_car_model(message: Message, state: FSMContext) -> None:
        car_model = message.text.strip() if message.text else ""
        if len(car_model) < 2:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад до марки", callback_data="driver:back_to_make")],
                    [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
                ]
            )
            await message.answer(
                "❌ <b>Невірний формат</b>\n\n"
                "Модель авто має містити мінімум 2 символи.\n\n"
                "Спробуйте ще раз:",
                reply_markup=kb
            )
            return
        await state.update_data(car_model=car_model)
        await state.set_state(DriverRegStates.car_plate)
        
        data = await state.get_data()
        car_make = data.get("car_make", "")
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад до марки", callback_data="driver:back_to_make")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
            ]
        )
        
        await message.answer(
            f"✅ <b>Авто:</b> {car_make} {car_model}\n\n"
            "🔢 <b>Крок 6/8: Номерний знак</b>\n\n"
            "Введіть номерний знак авто:\n\n"
            "Приклад: АА1234ВВ, КА5678ІН",
            reply_markup=kb
        )

    @router.message(DriverRegStates.car_plate)
    async def take_car_plate(message: Message, state: FSMContext) -> None:
        car_plate = message.text.strip().upper()
        if len(car_plate) < 4:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад до моделі", callback_data="driver:back_to_model")],
                    [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
                ]
            )
            await message.answer(
                "❌ <b>Невірний формат</b>\n\n"
                "Номерний знак має містити мінімум 4 символи.\n\n"
                "Спробуйте ще раз:",
                reply_markup=kb
            )
            return
        
        await state.update_data(car_plate=car_plate)
        await state.set_state(DriverRegStates.car_class)
        
        data = await state.get_data()
        car_make = data.get("car_make", "")
        car_model = data.get("car_model", "")
        
        # Вибір класу авто
        from app.handlers.car_classes import CAR_CLASSES
        
        buttons = []
        for class_code, class_info in CAR_CLASSES.items():
            mult_percent = int((class_info['multiplier']-1)*100)
            mult_text = f"+{mult_percent}%" if mult_percent > 0 else "базовий"
            buttons.append([
                InlineKeyboardButton(
                    text=f"{class_info['name_uk']} ({mult_text})",
                    callback_data=f"driver_car_class:{class_code}"
                )
            ])
        
        # Додати кнопку "Назад"
        buttons.append([InlineKeyboardButton(text="⬅️ Назад до моделі", callback_data="driver:back_to_model")])
        buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        # Видалити попереднє повідомлення
        reg_message_id = data.get("reg_message_id")
        if reg_message_id:
            try:
                await message.bot.delete_message(message.chat.id, reg_message_id)
            except:
                pass
        
        # Видалити повідомлення користувача
        try:
            await message.delete()
        except:
            pass
        
        msg = await message.answer(
            f"✅ <b>Авто:</b> {car_make} {car_model} ({car_plate})\n\n"
            "🚗 <b>Крок 7/8: Клас автомобіля</b>\n\n"
            "Оберіть клас вашого авто:\n\n"
            "• 🚗 Економ - базовий тариф\n"
            "• 🚙 Стандарт - +30% до тарифу\n"
            "• 🚘 Комфорт - +60% до тарифу\n"
            "• 🏆 Бізнес - +100% до тарифу\n\n"
            "Це вплине на вартість поїздок та ваш заробіток.",
            reply_markup=kb
        )
        await state.update_data(reg_message_id=msg.message_id)

    @router.callback_query(F.data.startswith("driver_car_class:"))
    async def save_driver_car_class(call: CallbackQuery, state: FSMContext) -> None:
        car_class = call.data.split(":", 1)[1]
        await state.update_data(car_class=car_class)
        await state.set_state(DriverRegStates.license_photo)
        
        from app.handlers.car_classes import get_car_class_name
        class_name = get_car_class_name(car_class)
        
        await call.answer(f"✅ {class_name}")
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏩ Пропустити фото", callback_data="driver:skip_photo")],
                [InlineKeyboardButton(text="⬅️ Назад до номерного знаку", callback_data="driver:back_to_plate")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_reg:cancel_start")]
            ]
        )
        
        # Видалити попереднє повідомлення
        data = await state.get_data()
        reg_message_id = data.get("reg_message_id")
        if reg_message_id:
            try:
                await call.message.bot.delete_message(call.message.chat.id, reg_message_id)
            except:
                pass
        
        msg = await call.message.answer(
            f"✅ <b>Клас авто:</b> {class_name}\n\n"
            "📸 <b>Крок 8/8: Фото посвідчення водія</b>\n\n"
            "Надішліть фото посвідчення водія або пропустіть цей крок.\n\n"
            "💡 Фото допоможе адміну швидше розглянути заявку.",
            reply_markup=kb
        )
        await state.update_data(reg_message_id=msg.message_id)

    @router.callback_query(F.data == "driver:skip_photo", DriverRegStates.license_photo)
    async def skip_license_callback(call: CallbackQuery, state: FSMContext) -> None:
        """Пропустити фото (inline кнопка)"""
        if not call.from_user:
            return
        await call.answer("⏩ Без фото")
        await state.update_data(license_photo_file_id=None)
        # ВАЖЛИВО: Передати ID користувача, який натиснув кнопку (call.from_user.id)
        await finalize_application(call.message, state, call.from_user.id)
    
    @router.message(Command("skip"), DriverRegStates.license_photo)
    async def skip_license(message: Message, state: FSMContext) -> None:
        """Пропустити фото (команда для сумісності)"""
        if not message.from_user:
            return
        await state.update_data(license_photo_file_id=None)
        await finalize_application(message, state, message.from_user.id)

    @router.message(DriverRegStates.license_photo, F.photo)
    async def take_license_photo(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        file_id = message.photo[-1].file_id  # biggest size
        
        # Видалити попереднє повідомлення та фото користувача
        data = await state.get_data()
        reg_message_id = data.get("reg_message_id")
        if reg_message_id:
            try:
                await message.bot.delete_message(message.chat.id, reg_message_id)
            except:
                pass
        
        try:
            await message.delete()
        except:
            pass
        
        await state.update_data(license_photo_file_id=file_id)
        await finalize_application(message, state, message.from_user.id)

    async def finalize_application(message: Message, state: FSMContext, user_id: int) -> None:
        """
        Завершити реєстрацію водія
        
        Args:
            message: Повідомлення для відповіді
            state: FSM state
            user_id: ID користувача (ВАЖЛИВО: НЕ message.from_user.id!)
        """
        data = await state.get_data()
        
        from app.handlers.car_classes import get_car_class_name
        car_class = data.get("car_class", "economy")
        
        driver = Driver(
            id=None,
            tg_user_id=user_id,  # ✅ Використовуємо переданий user_id
            full_name=str(data.get("full_name")),
            phone=str(data.get("phone")),
            car_make=str(data.get("car_make")),
            car_model=str(data.get("car_model")),
            car_plate=str(data.get("car_plate")),
            car_class=car_class,
            license_photo_file_id=(data.get("license_photo_file_id") or None),
            status="pending",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        driver_id = await create_driver_application(config.database_path, driver)
        await state.clear()
        # Notify admin(s)
        for admin_id in set(config.bot.admin_ids):
            try:
                await message.bot.send_message(
                    admin_id,
                    (
                        "Нова заявка водія:\n"
                        f"ID заявки: {driver_id}\n"
                        f"ПІБ: {driver.full_name}\n"
                        f"Телефон: {driver.phone}\n"
                        f"Авто: {driver.car_make} {driver.car_model} ({driver.car_plate})\n"
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Підтвердити",
                                    callback_data=f"drv:approve:{driver_id}",
                                ),
                                InlineKeyboardButton(
                                    text="Відхилити",
                                    callback_data=f"drv:reject:{driver_id}",
                                ),
                            ]
                        ]
                    ),
                )
                if driver.license_photo_file_id:
                    await message.bot.send_photo(
                        admin_id,
                        driver.license_photo_file_id,
                        caption=f"Посвідчення водія (заявка #{driver_id})",
                    )
            except Exception:
                # Ignore delivery errors to some admins
                pass

        # Видалити попереднє повідомлення якщо є
        reg_message_id = data.get("reg_message_id")
        if reg_message_id:
            try:
                await message.bot.delete_message(message.chat.id, reg_message_id)
            except:
                pass
        
        from app.handlers.keyboards import main_menu_keyboard
        is_admin = message.from_user.id in config.bot.admin_ids if message.from_user else False
        # Показати статус "на розгляді"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="📊 Перевірити статус заявки", 
                    callback_data="driver_status:check"
                )]
            ]
        )
        
        # Відправити повідомлення і зберегти його ID для подальшого видалення
        pending_msg = await message.answer(
            f"✅ <b>Заявку успішно подано!</b>\n\n"
            f"📋 Номер заявки: #{driver_id}\n"
            f"📝 ПІБ: {data.get('full_name')}\n"
            f"📱 Телефон: {data.get('phone')}\n"
            f"🏙 Місто: {data.get('city', 'Не вказано')}\n"
            f"🚙 Авто: {data.get('car_make')} {data.get('car_model')}\n\n"
            f"⏳ <b>Статус: На розгляді</b>\n\n"
            f"Очікуйте підтвердження від адміністратора.\n"
            f"Зазвичай це займає до 3 годин.\n\n"
            f"Ми повідомимо вас, коли заявку розглянуть.",
            reply_markup=kb
        )

    # Admin moderation callbacks
    # Обробник "open_driver_panel" знаходиться в start.py
    @router.callback_query(F.data.startswith("drv:"))
    async def on_driver_callback(call: CallbackQuery) -> None:
        data = (call.data or "").split(":")
        if len(data) != 3:
            await call.answer("Невірні дані", show_alert=True)
            return
        _, action, sid = data
        try:
            driver_id = int(sid)
        except ValueError:
            await call.answer("Помилка ID", show_alert=True)
            return
        # Only admins can moderate
        if not call.from_user or call.from_user.id not in set(config.bot.admin_ids):
            await call.answer("Недостатньо прав", show_alert=True)
            return

        if action == "approve":
            await update_driver_status(config.database_path, driver_id, "approved")
            await call.answer("✅ Водія підтверджено!", show_alert=True)
            drv = await get_driver_by_id(config.database_path, driver_id)
            if drv:
                # ВАЖЛИВО: Перевірити чи це не бот
                bot_info = await call.bot.get_me()
                if drv.tg_user_id == bot_info.id:
                    logger.warning(f"⚠️ Skipping notification for bot driver {driver_id}")
                    await call.message.edit_text(
                        f"⚠️ <b>УВАГА: Заявку #{driver_id} схвалено, але це БОТ!</b>\n\n"
                        f"tg_user_id = {drv.tg_user_id} (ID самого бота)\n\n"
                        f"❌ Повідомлення не відправлено.\n"
                        f"Видаліть цей запис з бази даних:\n"
                        f"<code>DELETE FROM drivers WHERE id = {driver_id};</code>",
                        parse_mode="HTML"
                    )
                    return
                
                try:
                    from app.handlers.keyboards import main_menu_keyboard
                    
                    # Inline кнопка для швидкого доступу
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🚗 Відкрити панель водія", callback_data="open_driver_panel")]
                        ]
                    )
                    
                    # Формуємо текст повідомлення з посиланням на групу
                    welcome_text = (
                        "🎉 <b>Вітаємо!</b>\n\n"
                        "Вашу заявку схвалено! Ви тепер водій нашого сервісу.\n\n"
                        "✅ Тепер ви можете:\n"
                        "• Приймати замовлення з групи водіїв\n"
                        "• Відстежувати свій заробіток\n"
                        "• Переглядати історію поїздок\n\n"
                    )
                    
                    # Додати посилання на групу водіїв, якщо воно є
                    if config.driver_group_invite_link:
                        welcome_text += (
                            f"📱 <b>Долучайтесь до групи водіїв:</b>\n"
                            f"{config.driver_group_invite_link}\n\n"
                            "⚠️ Всі замовлення публікуються в цій групі. "
                            "Обов'язково приєднайтесь!\n\n"
                        )
                    
                    welcome_text += "Натисніть кнопку нижче або напишіть боту /start"
                    
                    # Відправити повідомлення з inline кнопкою (parse_mode=HTML)
                    await call.message.bot.send_message(
                        drv.tg_user_id,
                        welcome_text,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                    
                    # Відправити панель водія з ReplyKeyboardMarkup
                    is_driver_admin = drv.tg_user_id in config.bot.admin_ids
                    await call.message.bot.send_message(
                        drv.tg_user_id,
                        "🚗 <b>Панель водія активована!</b>\n\n"
                        "Тепер ви можете:\n"
                        "• Отримувати замовлення в групі водіїв\n"
                        "• Переглядати свій заробіток\n"
                        "• Відстежувати статистику\n\n"
                        "Оберіть дію з меню нижче:",
                        reply_markup=main_menu_keyboard(is_registered=True, is_driver=True, is_admin=is_driver_admin),
                        parse_mode="HTML"
                    )
                    
                    logger.info(f"✅ Driver {driver_id} approved, notification sent to {drv.tg_user_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to notify driver {drv.tg_user_id}: {e}")
            
            # Оновити повідомлення адміна
            try:
                await call.message.edit_text(
                    f"✅ <b>Заявку #{driver_id} СХВАЛЕНО</b>\n\n"
                    f"👤 ПІБ: {drv.full_name if drv else 'N/A'}\n"
                    f"📱 Телефон: {drv.phone if drv else 'N/A'}\n"
                    f"🚗 Авто: {drv.car_make if drv else ''} {drv.car_model if drv else ''} ({drv.car_plate if drv else ''})"
                )
            except Exception:
                pass
        elif action == "reject":
            await update_driver_status(config.database_path, driver_id, "rejected")
            await call.answer("Заявку відхилено")
            drv = await get_driver_by_id(config.database_path, driver_id)
            if drv:
                try:
                    await call.message.bot.send_message(
                        drv.tg_user_id,
                        "Вашу заявку водія відхилено. Зв'яжіться з підтримкою.",
                    )
                except Exception:
                    pass
        else:
            await call.answer("Невірна дія", show_alert=True)
            return

    # Helper: driver status check
    @router.message(Command("my_driver_status"))
    async def my_driver_status(message: Message) -> None:
        if not message.from_user:
            return
        drv = await get_driver_by_tg_user_id(
            config.database_path, message.from_user.id
        )
        if not drv:
            await message.answer("Заявок не знайдено.")
            return
        await message.answer(
            f"Статус заявки: {drv.status}\nАвто: {drv.car_make} {drv.car_model} ({drv.car_plate})"
        )

    # Admin commands
    @router.message(Command("pending_drivers"))
    async def list_pending_drivers(message: Message) -> None:
        if not message.from_user or message.from_user.id not in set(config.bot.admin_ids):
            return
        drivers = await fetch_pending_drivers(config.database_path, limit=20)
        if not drivers:
            await message.answer("Немає заявок, що очікують.")
            return
        for d in drivers:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Підтвердити", callback_data=f"drv:approve:{d.id}"),
                        InlineKeyboardButton(text="Відхилити", callback_data=f"drv:reject:{d.id}"),
                    ]
                ]
            )
            await message.answer(
                (
                    f"#{d.id} {d.full_name} ({d.phone})\n"
                    f"Авто: {d.car_make} {d.car_model} ({d.car_plate})\n"
                    f"Статус: {d.status}"
                ),
                reply_markup=kb,
            )

    @router.message(Command("approve_driver"))
    async def approve_driver_cmd(message: Message) -> None:
        if not message.from_user or message.from_user.id not in set(config.bot.admin_ids):
            return
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer("Використання: /approve_driver <id>")
            return
        driver_id = int(parts[1])
        await update_driver_status(config.database_path, driver_id, "approved")
        await message.answer(f"Водія #{driver_id} підтверджено.")
        drv = await get_driver_by_id(config.database_path, driver_id)
        if drv:
            # ВАЖЛИВО: Перевірити чи це не бот
            bot_info = await message.bot.get_me()
            if drv.tg_user_id == bot_info.id:
                logger.warning(f"⚠️ Skipping notification for bot driver {driver_id}")
                await message.answer(
                    f"⚠️ <b>УВАГА: Водія #{driver_id} підтверджено, але це БОТ!</b>\n\n"
                    f"tg_user_id = {drv.tg_user_id} (ID самого бота)\n\n"
                    f"❌ Повідомлення не відправлено.\n"
                    f"Видаліть цей запис з бази даних:\n"
                    f"<code>DELETE FROM drivers WHERE id = {driver_id};</code>",
                    parse_mode="HTML"
                )
                return
            
            try:
                # Формуємо текст повідомлення з посиланням на групу
                welcome_text = (
                    "🎉 <b>Вітаємо!</b>\n\n"
                    "Вашу заявку схвалено! Ви тепер водій нашого сервісу.\n\n"
                    "✅ Тепер ви можете:\n"
                    "• Приймати замовлення з групи водіїв\n"
                    "• Відстежувати свій заробіток\n"
                    "• Переглядати історію поїздок\n\n"
                )
                
                # Додати посилання на групу водіїв, якщо воно є
                if config.driver_group_invite_link:
                    welcome_text += (
                        f"📱 <b>Долучайтесь до групи водіїв:</b>\n"
                        f"{config.driver_group_invite_link}\n\n"
                        "⚠️ Всі замовлення публікуються в цій групі. "
                        "Обов'язково приєднайтесь!\n\n"
                    )
                
                welcome_text += "Натисніть кнопку нижче або напишіть боту /start"
                
                # Inline кнопка для швидкого доступу
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🚗 Відкрити панель водія", callback_data="open_driver_panel")]
                    ]
                )
                
                await message.bot.send_message(
                    drv.tg_user_id,
                    welcome_text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
                
                # Відправити панель водія з ReplyKeyboardMarkup
                from app.handlers.keyboards import main_menu_keyboard
                is_driver_admin = drv.tg_user_id in config.bot.admin_ids
                await message.bot.send_message(
                    drv.tg_user_id,
                    "🚗 <b>Панель водія активована!</b>\n\n"
                    "Тепер ви можете:\n"
                    "• Отримувати замовлення в групі водіїв\n"
                    "• Переглядати свій заробіток\n"
                    "• Відстежувати статистику\n\n"
                    "Оберіть дію з меню нижче:",
                    reply_markup=main_menu_keyboard(is_registered=True, is_driver=True, is_admin=is_driver_admin),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"❌ Failed to notify driver via /approve_driver: {e}")

    @router.message(Command("reject_driver"))
    async def reject_driver_cmd(message: Message) -> None:
        if not message.from_user or message.from_user.id not in set(config.bot.admin_ids):
            return
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer("Використання: /reject_driver <id>")
            return
        driver_id = int(parts[1])
        await update_driver_status(config.database_path, driver_id, "rejected")
        await message.answer(f"Заявку #{driver_id} відхилено.")
        drv = await get_driver_by_id(config.database_path, driver_id)
        if drv:
            try:
                await message.bot.send_message(drv.tg_user_id, "Вашу заявку водія відхилено. Зв'яжіться з підтримкою.")
            except Exception:
                pass

    return router
