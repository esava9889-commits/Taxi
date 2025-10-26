"""Обробники налаштувань ціноутворення для панелі адміна"""
from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


def create_pricing_handlers(router: Router, config, is_admin, SettingsStates, get_pricing_settings, upsert_pricing_settings, PricingSettings):
    """Створити всі обробники для налаштувань ціноутворення"""
    
    # ==================== КЛАСИ АВТО ====================
    
    @router.callback_query(F.data == "settings:car_classes")
    async def show_car_classes_menu(call: CallbackQuery) -> None:
        """Показати меню налаштування класів авто"""
        if not call.from_user or not is_admin(call.from_user.id):
            return
        
        await call.answer()
        pricing = await get_pricing_settings(config.database_path)
        
        text = (
            "🚗 <b>НАЛАШТУВАННЯ КЛАСІВ АВТО</b>\n\n"
            f"Поточні множники:\n\n"
            f"• Економ: <b>x{pricing.economy_multiplier:.2f}</b>\n"
            f"• Стандарт: <b>x{pricing.standard_multiplier:.2f}</b>\n"
            f"• Комфорт: <b>x{pricing.comfort_multiplier:.2f}</b>\n"
            f"• Бізнес: <b>x{pricing.business_multiplier:.2f}</b>\n\n"
            "Оберіть клас для редагування:"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚗 Економ", callback_data="carclass:economy")],
                [InlineKeyboardButton(text="🚙 Стандарт", callback_data="carclass:standard")],
                [InlineKeyboardButton(text="🚘 Комфорт", callback_data="carclass:comfort")],
                [InlineKeyboardButton(text="🏆 Бізнес", callback_data="carclass:business")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="settings:back_to_main")]
            ]
        )
        
        await call.message.edit_text(text, reply_markup=kb)
    
    @router.callback_query(F.data.startswith("carclass:"))
    async def edit_car_class(call: CallbackQuery, state: FSMContext) -> None:
        """Редагувати множник класу авто"""
        if not call.from_user or not is_admin(call.from_user.id):
            return
        
        car_class = call.data.split(":")[1]
        await call.answer()
        
        pricing = await get_pricing_settings(config.database_path)
        current = getattr(pricing, f"{car_class}_multiplier")
        
        class_names = {
            "economy": "🚗 Економ",
            "standard": "🚙 Стандарт",
            "comfort": "🚘 Комфорт",
            "business": "🏆 Бізнес"
        }
        
        await state.update_data(car_class=car_class)
        await state.set_state(SettingsStates.economy_mult)  # Використовуємо один стан
        
        await call.message.edit_text(
            f"{class_names[car_class]} <b>МНОЖНИК</b>\n\n"
            f"Поточне значення: <b>x{current:.2f}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 Введіть новий множник:\n\n"
            f"Наприклад:\n"
            f"• <code>1.0</code> → базова ціна\n"
            f"• <code>1.3</code> → +30%\n"
            f"• <code>2.0</code> → подвоєння ціни"
        )
    
    @router.message(SettingsStates.economy_mult)
    async def save_car_class_multiplier(message: Message, state: FSMContext) -> None:
        """Зберегти множник класу авто"""
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        try:
            multiplier = float(message.text.strip())
            if multiplier < 0.5 or multiplier > 5.0:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0.5 до 5.0")
            return
        
        data = await state.get_data()
        car_class = data.get("car_class")
        
        # Отримати поточні налаштування
        pricing = await get_pricing_settings(config.database_path)
        
        # Оновити відповідний множник
        setattr(pricing, f"{car_class}_multiplier", multiplier)
        
        # Зберегти
        success = await upsert_pricing_settings(config.database_path, pricing)
        
        if success:
            await state.clear()
            class_names = {
                "economy": "🚗 Економ",
                "standard": "🚙 Стандарт",
                "comfort": "🚘 Комфорт",
                "business": "🏆 Бізнес"
            }
            from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
            admin_kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="⚙️ Налаштування")]],
                resize_keyboard=True
            )
            await message.answer(
                f"✅ Множник для {class_names[car_class]} оновлено: <b>x{multiplier:.2f}</b>",
                reply_markup=admin_kb
            )
        else:
            await message.answer("❌ Помилка збереження")
    
    # ==================== ЧАСОВІ НАЦІНКИ ====================
    
    @router.callback_query(F.data == "settings:time_surges")
    async def show_time_surges_menu(call: CallbackQuery) -> None:
        """Показати меню часових націнок"""
        if not call.from_user or not is_admin(call.from_user.id):
            return
        
        await call.answer()
        pricing = await get_pricing_settings(config.database_path)
        
        text = (
            "⏰ <b>ЧАСОВІ НАЦІНКИ</b>\n\n"
            f"• 🌙 Нічний (23:00-06:00): <b>+{pricing.night_percent:.0f}%</b>\n"
            f"• 🔥 Піковий (7-9, 17-19): <b>+{pricing.peak_hours_percent:.0f}%</b>\n"
            f"• 🎉 Вихідні (Пт-Нд 18-23): <b>+{pricing.weekend_percent:.0f}%</b>\n"
            f"• 📅 Понеділок (7-10): <b>+{pricing.monday_morning_percent:.0f}%</b>\n\n"
            "Оберіть націнку для редагування:"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🌙 Нічний тариф", callback_data="timesurge:night")],
                [InlineKeyboardButton(text="🔥 Піковий час", callback_data="timesurge:peak")],
                [InlineKeyboardButton(text="🎉 Вихідні", callback_data="timesurge:weekend")],
                [InlineKeyboardButton(text="📅 Понеділок вранці", callback_data="timesurge:monday")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="settings:back_to_main")]
            ]
        )
        
        await call.message.edit_text(text, reply_markup=kb)
    
    @router.callback_query(F.data.startswith("timesurge:"))
    async def edit_time_surge(call: CallbackQuery, state: FSMContext) -> None:
        """Редагувати часову націнку"""
        if not call.from_user or not is_admin(call.from_user.id):
            return
        
        surge_type = call.data.split(":")[1]
        await call.answer()
        
        pricing = await get_pricing_settings(config.database_path)
        
        surge_info = {
            "night": ("night_percent", "🌙 Нічний тариф (23:00-06:00)", SettingsStates.night_tariff),
            "peak": ("peak_hours_percent", "🔥 Піковий час (7-9, 17-19)", SettingsStates.peak_hours),
            "weekend": ("weekend_percent", "🎉 Вихідні (Пт-Нд 18-23)", SettingsStates.weekend),
            "monday": ("monday_morning_percent", "📅 Понеділок вранці (7-10)", SettingsStates.monday_morning)
        }
        
        field_name, display_name, state_type = surge_info[surge_type]
        current = getattr(pricing, field_name)
        
        await state.update_data(surge_type=surge_type, field_name=field_name)
        await state.set_state(state_type)
        
        await call.message.edit_text(
            f"{display_name}\n\n"
            f"Поточна надбавка: <b>+{current:.0f}%</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 Введіть нову надбавку у відсотках:\n\n"
            f"Наприклад:\n"
            f"• <code>50</code> → +50% (1.5x)\n"
            f"• <code>30</code> → +30% (1.3x)\n"
            f"• <code>0</code> → вимкнути"
        )
    
    @router.message(SettingsStates.peak_hours)
    @router.message(SettingsStates.weekend)
    @router.message(SettingsStates.monday_morning)
    async def save_time_surge(message: Message, state: FSMContext) -> None:
        """Зберегти часову націнку"""
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        try:
            percent = float(message.text.strip())
            if percent < 0 or percent > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        data = await state.get_data()
        field_name = data.get("field_name")
        
        # Отримати поточні налаштування
        pricing = await get_pricing_settings(config.database_path)
        
        # Оновити значення
        setattr(pricing, field_name, percent)
        
        # Зберегти
        success = await upsert_pricing_settings(config.database_path, pricing)
        
        if success:
            await state.clear()
            from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
            admin_kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="⚙️ Налаштування")]],
                resize_keyboard=True
            )
            await message.answer(
                f"✅ Націнку оновлено: <b>+{percent:.0f}%</b>",
                reply_markup=admin_kb
            )
        else:
            await message.answer("❌ Помилка збереження")
    
    # ==================== ПОПИТ ====================
    
    @router.callback_query(F.data == "settings:demand")
    async def show_demand_menu(call: CallbackQuery) -> None:
        """Показати меню налаштування попиту"""
        if not call.from_user or not is_admin(call.from_user.id):
            return
        
        await call.answer()
        pricing = await get_pricing_settings(config.database_path)
        
        text = (
            "📊 <b>НАЛАШТУВАННЯ ПОПИТУ</b>\n\n"
            f"• Немає водіїв: <b>+{pricing.no_drivers_percent:.0f}%</b>\n"
            f"• Дуже високий (>3:1): <b>+{pricing.demand_very_high_percent:.0f}%</b>\n"
            f"• Високий (>2:1): <b>+{pricing.demand_high_percent:.0f}%</b>\n"
            f"• Середній (>1.5:1): <b>+{pricing.demand_medium_percent:.0f}%</b>\n"
            f"• Низький (<0.3:1): <b>-{pricing.demand_low_discount_percent:.0f}%</b>\n\n"
            "Співвідношення замовлень до водіїв\n\n"
            "Оберіть рівень для редагування:"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚫 Немає водіїв", callback_data="demand:no_drivers")],
                [InlineKeyboardButton(text="🔥🔥🔥 Дуже високий", callback_data="demand:very_high")],
                [InlineKeyboardButton(text="🔥🔥 Високий", callback_data="demand:high")],
                [InlineKeyboardButton(text="🔥 Середній", callback_data="demand:medium")],
                [InlineKeyboardButton(text="💚 Низький (знижка)", callback_data="demand:low")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="settings:back_to_main")]
            ]
        )
        
        await call.message.edit_text(text, reply_markup=kb)
    
    @router.callback_query(F.data.startswith("demand:"))
    async def edit_demand_level(call: CallbackQuery, state: FSMContext) -> None:
        """Редагувати рівень попиту"""
        if not call.from_user or not is_admin(call.from_user.id):
            return
        
        demand_type = call.data.split(":")[1]
        await call.answer()
        
        pricing = await get_pricing_settings(config.database_path)
        
        demand_info = {
            "no_drivers": ("no_drivers_percent", "🚫 Немає водіїв", SettingsStates.no_drivers, False),
            "very_high": ("demand_very_high_percent", "🔥🔥🔥 Дуже високий попит (>3:1)", SettingsStates.demand_very_high, False),
            "high": ("demand_high_percent", "🔥🔥 Високий попит (>2:1)", SettingsStates.demand_high, False),
            "medium": ("demand_medium_percent", "🔥 Середній попит (>1.5:1)", SettingsStates.demand_medium, False),
            "low": ("demand_low_discount_percent", "💚 Низький попит (<0.3:1)", SettingsStates.demand_low, True)
        }
        
        field_name, display_name, state_type, is_discount = demand_info[demand_type]
        current = getattr(pricing, field_name)
        
        await state.update_data(demand_type=demand_type, field_name=field_name, is_discount=is_discount)
        await state.set_state(state_type)
        
        sign = "-" if is_discount else "+"
        await call.message.edit_text(
            f"{display_name}\n\n"
            f"Поточна надбавка: <b>{sign}{current:.0f}%</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 Введіть нову надбавку у відсотках:\n\n"
            f"Наприклад:\n"
            f"• <code>40</code> → {sign}40%\n"
            f"• <code>25</code> → {sign}25%\n"
            f"• <code>0</code> → вимкнути"
        )
    
    @router.message(SettingsStates.no_drivers)
    @router.message(SettingsStates.demand_very_high)
    @router.message(SettingsStates.demand_high)
    @router.message(SettingsStates.demand_medium)
    @router.message(SettingsStates.demand_low)
    async def save_demand_level(message: Message, state: FSMContext) -> None:
        """Зберегти рівень попиту"""
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        try:
            percent = float(message.text.strip())
            if percent < 0 or percent > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        data = await state.get_data()
        field_name = data.get("field_name")
        is_discount = data.get("is_discount", False)
        
        # Отримати поточні налаштування
        pricing = await get_pricing_settings(config.database_path)
        
        # Оновити значення
        setattr(pricing, field_name, percent)
        
        # Зберегти
        success = await upsert_pricing_settings(config.database_path, pricing)
        
        if success:
            await state.clear()
            from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
            admin_kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="⚙️ Налаштування")]],
                resize_keyboard=True
            )
            sign = "-" if is_discount else "+"
            await message.answer(
                f"✅ Рівень попиту оновлено: <b>{sign}{percent:.0f}%</b>",
                reply_markup=admin_kb
            )
        else:
            await message.answer("❌ Помилка збереження")
    
    # ==================== ПОВЕРНЕННЯ ====================
    
    @router.callback_query(F.data == "settings:back_to_main")
    async def back_to_main_settings(call: CallbackQuery, state: FSMContext) -> None:
        """Повернутися до головного меню налаштувань"""
        if not call.from_user or not is_admin(call.from_user.id):
            return
        
        await state.clear()
        await call.answer()
        
        # Отримати всі налаштування ціноутворення з БД
        pricing = await get_pricing_settings(config.database_path)
        
        # Отримати номер картки для комісії
        from app.storage.db_connection import db_manager
        async with db_manager.connect(config.database_path) as db:
            row = await db.fetchone("SELECT value FROM app_settings WHERE key = 'admin_payment_card'")
            admin_card = row[0] if row else "Не налаштована"
        
        text = (
            "⚙️ <b>НАЛАШТУВАННЯ ЦІНОУТВОРЕННЯ</b>\n\n"
            
            "🚗 <b>КЛАСИ АВТО (множники):</b>\n"
            f"• Економ: x{pricing.economy_multiplier:.2f}\n"
            f"• Стандарт: x{pricing.standard_multiplier:.2f}\n"
            f"• Комфорт: x{pricing.comfort_multiplier:.2f}\n"
            f"• Бізнес: x{pricing.business_multiplier:.2f}\n\n"
            
            "⏰ <b>ЧАСОВІ НАЦІНКИ:</b>\n"
            f"• 🌙 Нічний (23:00-06:00): +{pricing.night_percent:.0f}%\n"
            f"• 🔥 Піковий час (7-9, 17-19): +{pricing.peak_hours_percent:.0f}%\n"
            f"• 🎉 Вихідні (Пт-Нд 18-23): +{pricing.weekend_percent:.0f}%\n"
            f"• 📅 Понеділок (7-10): +{pricing.monday_morning_percent:.0f}%\n\n"
            
            "🌧️ <b>ПОГОДА:</b>\n"
            f"• Погодні умови: +{pricing.weather_percent:.0f}%\n\n"
            
            "📊 <b>ПОПИТ:</b>\n"
            f"• Немає водіїв: +{pricing.no_drivers_percent:.0f}%\n"
            f"• Дуже високий (>3:1): +{pricing.demand_very_high_percent:.0f}%\n"
            f"• Високий (>2:1): +{pricing.demand_high_percent:.0f}%\n"
            f"• Середній (>1.5:1): +{pricing.demand_medium_percent:.0f}%\n"
            f"• Низький (<0.3:1): -{pricing.demand_low_discount_percent:.0f}%\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💳 <b>ПЛАТІЖНІ РЕКВІЗИТИ:</b>\n"
            f"• Картка: <code>{admin_card}</code>\n\n"
            
            "Оберіть категорію для налаштування:"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚗 Класи авто", callback_data="settings:car_classes")],
                [InlineKeyboardButton(text="⏰ Часові націнки", callback_data="settings:time_surges")],
                [InlineKeyboardButton(text="🌧️ Погода", callback_data="settings:weather")],
                [InlineKeyboardButton(text="📊 Попит", callback_data="settings:demand")],
                [InlineKeyboardButton(text="💳 Картка", callback_data="settings:admin_card")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="settings:back")]
            ]
        )
        
        await call.message.edit_text(text, reply_markup=kb)
