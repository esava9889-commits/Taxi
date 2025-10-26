from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

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
    Tariff,
    get_latest_tariff,
    insert_tariff,
    fetch_recent_orders,
    fetch_pending_drivers,
    update_driver_status,
    get_driver_by_id,
    User,
    upsert_user,
    get_all_users,
    get_user_by_id,
    get_user_order_history,
    block_user,
    unblock_user,
    add_rides_to_client,
    get_driver_unpaid_commission,
    PricingSettings,
    get_pricing_settings,
    upsert_pricing_settings,
)
from app.utils.visual import (
    format_karma,
    get_karma_emoji,
    create_box,
)
from app.handlers.pricing_settings_handlers import create_pricing_handlers


CANCEL_TEXT = "Скасувати"


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Модерація водіїв")],
            [KeyboardButton(text="💰 Тарифи"), KeyboardButton(text="🚗 Водії")],
            [KeyboardButton(text="👤 Клієнти"), KeyboardButton(text="📢 Розсилка")],
            [KeyboardButton(text="⚙️ Налаштування")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Адмін-панель",
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


class TariffStates(StatesGroup):
    base_fare = State()
    per_km = State()
    per_minute = State()
    minimum = State()
    commission = State()


class SettingsStates(StatesGroup):
    """Стани для налаштувань (націнки)"""
    select_option = State()  # Вибір що налаштувати
    night_tariff = State()  # Введення % нічного тарифу
    weather = State()  # Введення % погоди
    admin_card = State()  # Введення номера картки для комісії
    
    # Класи авто
    economy_mult = State()
    standard_mult = State()
    comfort_mult = State()
    business_mult = State()
    
    # Часові націнки
    peak_hours = State()
    weekend = State()
    monday_morning = State()
    
    # Попит
    no_drivers = State()
    demand_very_high = State()
    demand_high = State()
    demand_medium = State()
    demand_low = State()
    
    # Wizard для першого налаштування (всі параметри по черзі)
    wizard_economy = State()
    wizard_standard = State()
    wizard_comfort = State()
    wizard_business = State()
    wizard_night = State()
    wizard_peak = State()
    wizard_weekend = State()
    wizard_monday = State()
    wizard_weather = State()
    wizard_no_drivers = State()
    wizard_demand_very_high = State()
    wizard_demand_high = State()
    wizard_demand_medium = State()
    wizard_demand_low = State()


class BroadcastStates(StatesGroup):
    message = State()


class ClientManageStates(StatesGroup):
    """Стани для керування клієнтами"""
    add_rides_count = State()  # Введення кількості поїздок для додавання


def create_router(config: AppConfig) -> Router:
    router = Router(name="admin")
    
    def is_admin(user_id: int) -> bool:
        return user_id in set(config.bot.admin_ids)

    # === Helpers for app_settings (priority mode) ===
    async def get_priority_mode() -> bool:
        from app.storage.db_connection import db_manager
        async with db_manager.connect(config.database_path) as db:
            row = await db.fetchone("SELECT value FROM app_settings WHERE key = 'priority_mode'")
            return (row and str(row[0]).lower() in ("1", "true", "on", "yes"))

    async def set_priority_mode(enabled: bool) -> None:
        from app.storage.db_connection import db_manager
        async with db_manager.connect(config.database_path) as db:
            await db.execute(
                "INSERT INTO app_settings(key,value) VALUES('priority_mode', ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("1" if enabled else "0",)
            )
            await db.commit()
    
    async def get_admin_payment_card() -> str:
        """Отримати номер картки адміна для сплати комісії"""
        from app.storage.db_connection import db_manager
        async with db_manager.connect(config.database_path) as db:
            row = await db.fetchone("SELECT value FROM app_settings WHERE key = 'admin_payment_card'")
            return row[0] if row else "Не вказано"
    
    async def set_admin_payment_card(card_number: str) -> None:
        """Встановити номер картки адміна для сплати комісії"""
        from app.storage.db_connection import db_manager
        async with db_manager.connect(config.database_path) as db:
            await db.execute(
                "INSERT INTO app_settings(key,value) VALUES('admin_payment_card', ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (card_number,)
            )
            await db.commit()

    @router.callback_query(F.data.startswith("admin:priority_mode_toggle:"))
    async def priority_mode_toggle(call: CallbackQuery) -> None:
        """Глобальний тумблер режиму пріоритизації водіїв"""
        if not call.from_user or not is_admin(call.from_user.id):
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        parts = (call.data or "").split(":")
        if len(parts) < 3:
            await call.answer("❌ Невірний формат", show_alert=True)
            return
        new_value = parts[2]
        enabled = str(new_value) in ("1", "true", "on", "yes")
        await set_priority_mode(enabled)
        await call.answer("✅ Глобальний пріоритет увімкнено" if enabled else "✅ Глобальний пріоритет вимкнено", show_alert=True)

        # Оновити кнопку у цьому ж повідомленні
        kb_mode = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=("🔓 Вимкнути глобальний пріоритет" if enabled else "🔒 Увімкнути глобальний пріоритет"),
                    callback_data=f"admin:priority_mode_toggle:{0 if enabled else 1}")]
            ]
        )
        try:
            base_text = call.message.text or "✅ <b>Активні водії</b>\n\n"
            if "Глобальний пріоритет:" in base_text:
                prefix = base_text.split("Глобальний пріоритет:")[0]
                new_text = prefix + f"Глобальний пріоритет: <b>{'Увімкнено' if enabled else 'Вимкнено'}</b>"
            else:
                new_text = base_text + f"\nГлобальний пріоритет: <b>{'Увімкнено' if enabled else 'Вимкнено'}</b>"
            await call.message.edit_text(new_text, reply_markup=kb_mode, parse_mode="HTML")
        except Exception:
            await call.message.edit_reply_markup(reply_markup=kb_mode)

    @router.message(Command("admin"))
    @router.message(F.text == "⚙️ Адмін-панель")
    async def admin_panel(message: Message) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            await message.answer("❌ У вас немає доступу до адмін-панелі.")
            return
        await message.answer(
            "🔐 <b>Адмін-панель</b>\n\nОберіть дію:", 
            reply_markup=admin_menu_keyboard()
        )

    @router.message(F.text == "📊 Статистика")
    async def show_statistics(message: Message) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        from app.storage.db_connection import db_manager
        
        try:
            async with db_manager.connect(config.database_path) as db:
                # Total orders
                async with db.execute("SELECT COUNT(*) FROM orders") as cur:
                    total_orders = (await cur.fetchone())[0]
                
                # Completed orders
                async with db.execute("SELECT COUNT(*) FROM orders WHERE status = 'completed'") as cur:
                    completed_orders = (await cur.fetchone())[0]
                
                # Active drivers
                async with db.execute("SELECT COUNT(*) FROM drivers WHERE status = 'approved'") as cur:
                    active_drivers = (await cur.fetchone())[0]
                
                # Pending driver applications
                async with db.execute("SELECT COUNT(*) FROM drivers WHERE status = 'pending'") as cur:
                    pending_drivers = (await cur.fetchone())[0]
                
                # Total revenue
                async with db.execute("SELECT SUM(fare_amount) FROM orders WHERE status = 'completed'") as cur:
                    row = await cur.fetchone()
                    total_revenue = row[0] if row[0] else 0.0
                
                # Total commission
                async with db.execute("SELECT SUM(commission) FROM orders WHERE status = 'completed'") as cur:
                    row = await cur.fetchone()
                    total_commission = row[0] if row[0] else 0.0
                
                # Unpaid commissions
                async with db.execute("SELECT SUM(commission) FROM payments WHERE commission_paid = 0") as cur:
                    row = await cur.fetchone()
                    unpaid_commission = row[0] if row[0] else 0.0
                
                # Total users
                async with db.execute("SELECT COUNT(*) FROM users") as cur:
                    total_users = (await cur.fetchone())[0]
                
                text = (
                    "📊 <b>Статистика системи</b>\n\n"
                    f"📦 Всього замовлень: {total_orders}\n"
                    f"✅ Виконано: {completed_orders}\n"
                    f"🚗 Активних водіїв: {active_drivers}\n"
                    f"⏳ Водіїв на модерації: {pending_drivers}\n\n"
                    f"💵 Загальний дохід: {total_revenue:.2f} грн\n"
                    f"💰 Загальна комісія: {total_commission:.2f} грн\n"
                    f"⚠️ Несплачена комісія: {unpaid_commission:.2f} грн\n"
                    f"👥 Всього користувачів: {total_users}"
                )
                
                await message.answer(text, reply_markup=admin_menu_keyboard())
        
        except Exception as e:
            logger.error(f"❌ Помилка отримання статистики: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await message.answer(
                "❌ Помилка отримання статистики. Переконайтесь що DATABASE_URL налаштовано на Render.",
                reply_markup=admin_menu_keyboard()
            )

    @router.message(F.text == "👥 Модерація водіїв")
    async def moderate_drivers(message: Message) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        drivers = await fetch_pending_drivers(config.database_path, limit=20)
        if not drivers:
            await message.answer("Немає заявок на модерації.", reply_markup=admin_menu_keyboard())
            return
        
        for d in drivers:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"drv:approve:{d.id}"),
                        InlineKeyboardButton(text="❌ Відхилити", callback_data=f"drv:reject:{d.id}"),
                    ]
                ]
            )
            text = (
                f"<b>Заявка #{d.id}</b>\n\n"
                f"👤 ПІБ: {d.full_name}\n"
                f"📱 Телефон: {d.phone}\n"
                f"🏙 Місто: {d.city or 'Не вказано'}\n"
                f"🚗 Авто: {d.car_make} {d.car_model}\n"
                f"🔢 Номер: {d.car_plate}\n"
                f"📅 Подано: {d.created_at.strftime('%Y-%m-%d %H:%M')}"
            )
            await message.answer(text, reply_markup=kb)
            if d.license_photo_file_id:
                try:
                    await message.answer_photo(
                        d.license_photo_file_id,
                        caption=f"📄 Посвідчення водія (заявка #{d.id})"
                    )
                except Exception:
                    pass

    @router.message(F.text == "💰 Тарифи")
    async def show_tariffs(message: Message, state: FSMContext) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        tariff = await get_latest_tariff(config.database_path)
        if tariff:
            text = (
                "💰 <b>Поточні тарифи</b>\n\n"
                f"Базова ціна: {tariff.base_fare:.2f} грн\n"
                f"Ціна за км: {tariff.per_km:.2f} грн\n"
                f"Ціна за хвилину: {tariff.per_minute:.2f} грн\n"
                f"Мінімальна сума: {tariff.minimum:.2f} грн\n"
                f"Комісія сервісу: {tariff.commission_percent*100:.1f}%\n\n"
                f"Встановлено: {tariff.created_at.strftime('%Y-%m-%d %H:%M')}"
            )
        else:
            text = "⚠️ Тарифи ще не встановлено."
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="✏️ Змінити тарифи", callback_data="tariff:edit")]]
        )
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "tariff:edit")
    async def start_tariff_edit(call: CallbackQuery, state: FSMContext) -> None:
        if not call.from_user or not is_admin(call.from_user.id):
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        await call.answer()
        await state.set_state(TariffStates.base_fare)
        await call.message.answer(
            "Введіть базову ціну (грн):", 
            reply_markup=cancel_keyboard()
        )

    @router.message(F.text == CANCEL_TEXT)
    async def cancel_admin_action(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Скасовано.", reply_markup=admin_menu_keyboard())

    @router.message(TariffStates.base_fare)
    async def set_base_fare(message: Message, state: FSMContext) -> None:
        try:
            base_fare = float(message.text.strip())
            if base_fare < 0:
                raise ValueError()
        except ValueError:
            await message.answer("Введіть коректне число (наприклад, 50.00)")
            return
        
        await state.update_data(base_fare=base_fare)
        await state.set_state(TariffStates.per_km)
        await message.answer("Введіть ціну за кілометр (грн), потім здасте комісію (%):", reply_markup=cancel_keyboard())

    @router.message(TariffStates.per_km)
    async def set_per_km(message: Message, state: FSMContext) -> None:
        try:
            per_km = float(message.text.strip())
            if per_km < 0:
                raise ValueError()
        except ValueError:
            await message.answer("Введіть коректне число (наприклад, 8.00)")
            return
        
        await state.update_data(per_km=per_km)
        await state.set_state(TariffStates.per_minute)
        await message.answer("Введіть ціну за хвилину очікування (грн):", reply_markup=cancel_keyboard())

    @router.message(TariffStates.per_minute)
    async def set_per_minute(message: Message, state: FSMContext) -> None:
        try:
            per_minute = float(message.text.strip())
            if per_minute < 0:
                raise ValueError()
        except ValueError:
            await message.answer("Введіть коректне число (наприклад, 2.00)")
            return
        
        await state.update_data(per_minute=per_minute)
        await state.set_state(TariffStates.minimum)
        await message.answer("Введіть мінімальну суму замовлення (грн):", reply_markup=cancel_keyboard())

    @router.message(TariffStates.minimum)
    async def set_minimum(message: Message, state: FSMContext) -> None:
        try:
            minimum = float(message.text.strip())
            if minimum < 0:
                raise ValueError()
        except ValueError:
            await message.answer("Введіть коректне число (наприклад, 60.00)")
            return
        
        # Запит комісії після мінімальної суми
        await state.update_data(minimum=minimum)
        await state.set_state(TariffStates.commission)
        await message.answer("Введіть комісію сервісу у відсотках (наприклад, 2 або 2.5):", reply_markup=cancel_keyboard())

    # Видалили callback-етап, вводимо комісію напряму у стані TariffStates.commission

    @router.message(TariffStates.commission)
    async def set_commission_percent(message: Message, state: FSMContext) -> None:
        # Перевикористання стану для вводу комісії після мінімальної суми
        try:
            commission_percent = float(message.text.strip())
            if commission_percent < 0 or commission_percent > 50:
                raise ValueError()
        except ValueError:
            await message.answer("Введіть коректний відсоток (0-50), напр. 2.0")
            return
        data = await state.get_data()
        tariff = Tariff(
            id=None,
            base_fare=data["base_fare"],
            per_km=data["per_km"],
            per_minute=data["per_minute"],
            minimum=data["minimum"],
            commission_percent=commission_percent / 100.0,
            created_at=datetime.now(timezone.utc)
        )
        await insert_tariff(config.database_path, tariff)
        await state.clear()
        await message.answer("✅ Тарифи успішно оновлено!", reply_markup=admin_menu_keyboard())

    @router.message(F.text == "🚗 Водії")
    async def show_drivers_list(message: Message) -> None:
        """Показати список всіх водіїв"""
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        from app.storage.db_connection import db_manager
        
        async with db_manager.connect(config.database_path) as db:
            # Отримати всіх водіїв (додаємо поле priority)
            async with db.execute(
                """
                SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate,
                       car_class, status, city, online, created_at, priority
                FROM drivers
                ORDER BY 
                    CASE status
                        WHEN 'approved' THEN 1
                        WHEN 'pending' THEN 2
                        WHEN 'rejected' THEN 3
                        ELSE 4
                    END,
                    created_at DESC
                """
            ) as cur:
                drivers = await cur.fetchall()
        
        if not drivers:
            await message.answer(
                "👥 <b>Водіїв немає</b>\n\n"
                "Поки що жоден водій не зареєструвався.",
                reply_markup=admin_menu_keyboard(),
                parse_mode="HTML"
            )
            return
        
        # Розділити за статусами
        approved_drivers = [d for d in drivers if d[8] == "approved"]
        pending_drivers = [d for d in drivers if d[8] == "pending"]
        rejected_drivers = [d for d in drivers if d[8] == "rejected"]
        
        # Відправити кожну категорію окремо
        if approved_drivers:
            # Показати стан глобального тумблера пріоритизації
            priority_mode = await get_priority_mode()
            kb_mode = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text=("🔓 Вимкнути глобальний пріоритет" if priority_mode else "🔒 Увімкнути глобальний пріоритет"),
                        callback_data=f"admin:priority_mode_toggle:{1 if not priority_mode else 0}")]
                ]
            )
            await message.answer(
                (
                    f"✅ <b>Активні водії ({len(approved_drivers)})</b>\n\n"
                    f"Глобальний пріоритет: <b>{'Увімкнено' if priority_mode else 'Вимкнено'}</b>"
                ),
                reply_markup=kb_mode,
                parse_mode="HTML"
            )
            for d in approved_drivers:
                (
                    driver_id,
                    tg_user_id,
                    full_name,
                    phone,
                    car_make,
                    car_model,
                    car_plate,
                    car_class,
                    status,
                    city,
                    online,
                    created_at,
                    priority,
                ) = d

                online_status = "🟢 Онлайн" if online else "🔴 Офлайн"
                priority_badge = "⭐" if (priority or 0) > 0 else ""
                toggle_text = "⭐ Вимкнути пріоритет" if (priority or 0) > 0 else "⭐ Увімкнути пріоритет"
                
                # Отримати несплачену комісію водія
                unpaid_commission = await get_driver_unpaid_commission(config.database_path, tg_user_id)

                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="🚫 Заблокувати", callback_data=f"admin_driver:block:{driver_id}"),
                            InlineKeyboardButton(text="💬 Написати", url=f"tg://user?id={tg_user_id}")
                        ],
                        [InlineKeyboardButton(text=toggle_text, callback_data=f"admin_driver:priority_toggle:{driver_id}")],
                        [InlineKeyboardButton(text="📊 Статистика", callback_data=f"admin_driver:stats:{driver_id}")],
                        [InlineKeyboardButton(text="🗑️ Видалити", callback_data=f"admin_driver:delete:{driver_id}")]
                    ]
                )

                text = (
                    f"👤 <b>{full_name}</b> {priority_badge} {online_status}\n"
                    f"📱 {phone}\n"
                    f"🏙️ {city or 'Не вказано'}\n"
                    f"🚗 {car_make} {car_model} ({car_plate})\n"
                    f"🎯 Клас: {car_class}\n"
                    f"⭐ Пріоритет: {'Увімкнено' if (priority or 0) > 0 else 'Вимкнено'}\n"
                    f"💳 Несплачена комісія: <b>{unpaid_commission:.2f} грн</b>\n"
                    f"🆔 ID: {driver_id}"
                )

                await message.answer(text, reply_markup=kb, parse_mode="HTML")
        
        if pending_drivers:
            await message.answer(
                f"⏳ <b>На модерації ({len(pending_drivers)})</b>\n\n"
                "Використовуйте '👥 Модерація водіїв' для схвалення",
                parse_mode="HTML"
            )
        
        if rejected_drivers:
            await message.answer(
                f"❌ <b>Заблоковані ({len(rejected_drivers)})</b>",
                parse_mode="HTML"
            )
            for d in rejected_drivers:
                driver_id, tg_user_id, full_name, phone, car_make, car_model, car_plate, \
                    car_class, status, city, online, created_at, priority = d
                
                # Отримати несплачену комісію водія
                unpaid_commission = await get_driver_unpaid_commission(config.database_path, tg_user_id)
                
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="✅ Розблокувати", callback_data=f"admin_driver:unblock:{driver_id}"),
                            InlineKeyboardButton(text="💬 Написати", url=f"tg://user?id={tg_user_id}")
                        ],
                        [InlineKeyboardButton(text="🗑️ Видалити", callback_data=f"admin_driver:delete:{driver_id}")]
                    ]
                )
                
                text = (
                    f"👤 <b>{full_name}</b> 🚫\n"
                    f"📱 {phone}\n"
                    f"🏙️ {city or 'Не вказано'}\n"
                    f"🚗 {car_make} {car_model} ({car_plate})\n"
                    f"💳 Несплачена комісія: <b>{unpaid_commission:.2f} грн</b>\n"
                    f"🆔 ID: {driver_id}"
                )
                
                await message.answer(text, reply_markup=kb, parse_mode="HTML")
        
        await message.answer("🔙 Головне меню:", reply_markup=admin_menu_keyboard())

    # Обробник для модерації водіїв (approve/reject)
    @router.callback_query(F.data.startswith("drv:"))
    async def handle_driver_moderation(call: CallbackQuery) -> None:
        if not call.from_user or not is_admin(call.from_user.id):
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        parts = (call.data or "").split(":")
        if len(parts) < 3:
            await call.answer("❌ Невірний формат", show_alert=True)
            return
        
        action = parts[1]
        driver_id = int(parts[2])
        
        try:
            driver = await get_driver_by_id(config.database_path, driver_id)
            if not driver:
                await call.answer("❌ Водія не знайдено", show_alert=True)
                return
            
            if action == "approve":
                await update_driver_status(config.database_path, driver_id, "approved")
                await call.answer("✅ Водія підтверджено!", show_alert=True)
                
                # ВАЖЛИВО: Перевірити чи це не бот
                bot_info = await call.bot.get_me()
                if driver.tg_user_id == bot_info.id:
                    logger.warning(f"⚠️ Skipping notification for bot driver {driver_id}")
                    if call.message:
                        await call.message.edit_text(
                            f"⚠️ <b>УВАГА: Заявку #{driver_id} схвалено, але це БОТ!</b>\n\n"
                            f"tg_user_id = {driver.tg_user_id} (ID самого бота)\n\n"
                            f"❌ Повідомлення не відправлено.\n"
                            f"Видаліть цей запис з бази даних:\n"
                            f"<code>DELETE FROM drivers WHERE id = {driver_id};</code>",
                            parse_mode="HTML"
                        )
                    return
                
                # Notify driver
                try:
                    from app.handlers.keyboards import main_menu_keyboard
                    
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
                    
                    # ✅ ПРАВИЛЬНА ЛОГІКА: Тільки група МІСТА водія, БЕЗ fallback
                    driver_city = driver.city
                    city_invite_link = None
                    
                    if driver_city and driver_city in config.city_invite_links:
                        city_invite_link = config.city_invite_links[driver_city]
                    
                    # ВАЖЛИВО: НЕ використовуємо fallback на резервну групу!
                    # Водій має отримати посилання ТІЛЬКИ на групу СВОГО міста
                    
                    if city_invite_link:
                        # Є група для міста водія
                        welcome_text += (
                            f"📱 <b>Долучайтесь до групи водіїв міста {driver_city}:</b>\n"
                            f"{city_invite_link}\n\n"
                            f"⚠️ Всі замовлення міста {driver_city} публікуються в цій групі.\n"
                            f"Обов'язково приєднайтесь!\n\n"
                        )
                        logger.info(f"✅ Водій #{driver_id} ({driver_city}) отримав посилання на групу міста: {city_invite_link}")
                    else:
                        # Немає групи для цього міста
                        welcome_text += (
                            f"⚠️ <b>УВАГА: Група для міста {driver_city} ще не налаштована!</b>\n\n"
                            f"Зверніться до адміністратора для налаштування групи.\n\n"
                            f"📧 Напишіть: @{config.admin_username or 'admin'}\n\n"
                        )
                        logger.warning(f"⚠️ Водій #{driver_id} схвалений, але група міста '{driver_city}' не налаштована!")
                    
                    welcome_text += "Натисніть кнопку нижче або напишіть боту /start"
                    
                    await call.bot.send_message(
                        driver.tg_user_id,
                        welcome_text,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                    
                    # Відправимо панель водія з ReplyKeyboardMarkup
                    # Перевірка чи водій також адмін
                    is_driver_admin = driver.tg_user_id in config.bot.admin_ids
                    
                    from app.handlers.keyboards import main_menu_keyboard
                    await call.bot.send_message(
                        driver.tg_user_id,
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
                    logger.error(f"Failed to notify driver {driver.tg_user_id}: {e}")
                
                # Update message
                if call.message:
                    await call.message.edit_text(
                        f"✅ <b>Заявку #{driver_id} СХВАЛЕНО</b>\n\n"
                        f"👤 ПІБ: {driver.full_name}\n"
                        f"📱 Телефон: {driver.phone}\n"
                        f"🏙 Місто: {driver.city or 'Не вказано'}\n"
                        f"🚗 Авто: {driver.car_make} {driver.car_model} ({driver.car_plate})"
                    )
                
                logger.info(f"Admin {call.from_user.id} approved driver {driver_id}")
            
            elif action == "reject":
                await update_driver_status(config.database_path, driver_id, "rejected")
                await call.answer("❌ Водія відхилено", show_alert=True)
                
                # Notify driver
                try:
                    await call.bot.send_message(
                        driver.tg_user_id,
                        "😔 <b>Вашу заявку відхилено</b>\n\n"
                        "На жаль, ваша заявка на водія не була схвалена.\n"
                        "Зверніться до адміністратора для уточнення деталей."
                    )
                except Exception as e:
                    logger.error(f"Failed to notify driver {driver.tg_user_id}: {e}")
                
                # Update message
                if call.message:
                    await call.message.edit_text(
                        f"❌ <b>Заявку #{driver_id} ВІДХИЛЕНО</b>\n\n"
                        f"👤 ПІБ: {driver.full_name}\n"
                        f"📱 Телефон: {driver.phone}\n"
                        f"🏙 Місто: {driver.city or 'Не вказано'}\n"
                        f"🚗 Авто: {driver.car_make} {driver.car_model} ({driver.car_plate})"
                    )
                
                logger.info(f"Admin {call.from_user.id} rejected driver {driver_id}")
        
        except Exception as e:
            logger.error(f"Error in driver moderation: {e}")
            await call.answer("❌ Помилка при обробці", show_alert=True)

    @router.message(F.text == "⚙️ Налаштування", lambda m: m.from_user and is_admin(m.from_user.id))
    async def show_settings(message: Message, state: FSMContext) -> None:
        """Показати меню налаштувань (ТІЛЬКИ для адмінів)"""
        if not message.from_user:
            return
        
        # Отримати всі налаштування ціноутворення з БД
        pricing = await get_pricing_settings(config.database_path)
        
        # Якщо налаштування НЕ існують - запустити wizard
        if pricing is None:
            await state.set_state(SettingsStates.wizard_economy)
            await message.answer(
                "🎉 <b>ПЕРШЕ НАЛАШТУВАННЯ ЦІНОУТВОРЕННЯ</b>\n\n"
                "Вітаю! Зараз ви налаштуєте всі параметри ціноутворення.\n"
                "Це займе ~2 хвилини.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🚗 <b>КРОК 1/14: Клас ЕКОНОМ</b>\n\n"
                "Введіть множник для класу Економ:\n\n"
                "💡 <b>Рекомендовано:</b> <code>1.0</code> (базовий тариф)\n\n"
                "Приклад: якщо базова ціна 100 грн, то:\n"
                "• 1.0 → 100 грн\n"
                "• 1.2 → 120 грн\n\n"
                "Введіть число від 0.5 до 5.0:",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        
        # Отримати номер картки для комісії
        admin_card = await get_admin_payment_card()
        
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
            f"• Дуже високий (&gt;3:1): +{pricing.demand_very_high_percent:.0f}%\n"
            f"• Високий (&gt;2:1): +{pricing.demand_high_percent:.0f}%\n"
            f"• Середній (&gt;1.5:1): +{pricing.demand_medium_percent:.0f}%\n"
            f"• Низький (&lt;0.3:1): -{pricing.demand_low_discount_percent:.0f}%\n\n"
            
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
        
        await message.answer(text, reply_markup=kb)
    
    @router.callback_query(F.data == "settings:night")
    async def settings_night_tariff(call: CallbackQuery, state: FSMContext) -> None:
        """Налаштувати нічний тариф"""
        if not call.from_user or not is_admin(call.from_user.id):
            return
        
        await call.answer()
        await state.set_state(SettingsStates.night_tariff)
        
        tariff = await get_latest_tariff(config.database_path)
        current = tariff.night_tariff_percent if tariff and hasattr(tariff, 'night_tariff_percent') else 50.0
        
        await call.message.edit_text(
            f"🌙 <b>НІЧНИЙ ТАРИФ</b>\n\n"
            f"Поточна надбавка: <b>+{current:.0f}%</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 Введіть нову надбавку у відсотках:\n\n"
            f"Наприклад:\n"
            f"• <code>50</code> → +50% (1.5x)\n"
            f"• <code>30</code> → +30% (1.3x)\n"
            f"• <code>0</code> → вимкнути\n\n"
            f"⏰ Діє з 23:00 до 06:00"
        )
    
    @router.callback_query(F.data == "settings:weather")
    async def settings_weather(call: CallbackQuery, state: FSMContext) -> None:
        """Налаштувати погодні умови"""
        if not call.from_user or not is_admin(call.from_user.id):
            return
        
        await call.answer()
        await state.set_state(SettingsStates.weather)
        
        tariff = await get_latest_tariff(config.database_path)
        current = tariff.weather_percent if tariff and hasattr(tariff, 'weather_percent') else 0.0
        
        await call.message.edit_text(
            f"🌧️ <b>ПОГОДНІ УМОВИ</b>\n\n"
            f"Поточна надбавка: <b>+{current:.0f}%</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 Введіть надбавку у відсотках:\n\n"
            f"Наприклад:\n"
            f"• <code>20</code> → +20% (погана погода)\n"
            f"• <code>30</code> → +30% (дуже погана погода)\n"
            f"• <code>0</code> → вимкнути\n\n"
            f"💡 Увімкніть вручну при дощі, снігу, тощо.\n"
            f"Не забудьте вимкнути коли погода покращає!"
        )
    
    @router.callback_query(F.data == "settings:admin_card")
    async def settings_admin_card(call: CallbackQuery, state: FSMContext) -> None:
        """Налаштувати номер картки для комісії"""
        if not call.from_user or not is_admin(call.from_user.id):
            return
        
        await call.answer()
        await state.set_state(SettingsStates.admin_card)
        
        current_card = await get_admin_payment_card()
        
        await call.message.edit_text(
            f"💳 <b>КАРТКА ДЛЯ СПЛАТИ КОМІСІЇ</b>\n\n"
            f"Поточний номер:\n"
            f"<code>{current_card}</code>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 Введіть новий номер картки:\n\n"
            f"Наприклад:\n"
            f"• <code>4149499012345678</code>\n"
            f"• <code>5168 7422 1234 5678</code>\n\n"
            f"💡 <b>Цей номер будуть бачити водії</b>\n"
            f"при оплаті комісії!"
        )
    
    @router.callback_query(F.data == "settings:back")
    async def settings_back(call: CallbackQuery) -> None:
        """Повернутися до меню адміна"""
        if not call.from_user or not is_admin(call.from_user.id):
            return
        
        await call.answer()
        await call.message.delete()
        await call.message.answer("🔙 Повернення до меню", reply_markup=admin_menu_keyboard())
    
    @router.message(SettingsStates.night_tariff)
    async def save_night_tariff(message: Message, state: FSMContext) -> None:
        """Зберегти нічний тариф"""
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        try:
            night_percent = float(message.text.strip())
            if night_percent < 0 or night_percent > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        # Отримати поточні налаштування
        pricing = await get_pricing_settings(config.database_path)
        pricing.night_percent = night_percent
        
        # Зберегти
        success = await upsert_pricing_settings(config.database_path, pricing)
        
        if success:
            await state.clear()
            
            # Повідомлення в групи водіїв
            notification = (
                f"🌙 <b>ОНОВЛЕНО НІЧНИЙ ТАРИФ</b>\n\n"
                f"Надбавка: <b>+{night_percent:.0f}%</b>\n"
                f"Час дії: 23:00 - 06:00\n\n"
                f"💰 Вартість замовлень збільшена!"
            )
            
            # Відправити в усі групи
            sent_count = 0
            for city, group_id in config.city_groups.items():
                if group_id:
                    try:
                        await message.bot.send_message(group_id, notification)
                        sent_count += 1
                    except Exception as e:
                        logger.error(f"Помилка відправки в групу {city}: {e}")
            
            await message.answer(
                f"✅ Нічний тариф оновлено: <b>+{night_percent:.0f}%</b>\n\n"
                f"📢 Повідомлення надіслано в {sent_count} груп водіїв",
                reply_markup=admin_menu_keyboard()
            )
        else:
            await message.answer("❌ Помилка оновлення", reply_markup=admin_menu_keyboard())
    
    @router.message(SettingsStates.weather)
    async def save_weather(message: Message, state: FSMContext) -> None:
        """Зберегти погодні умови"""
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        try:
            weather_percent = float(message.text.strip())
            if weather_percent < 0 or weather_percent > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        # Отримати поточні налаштування
        pricing = await get_pricing_settings(config.database_path)
        pricing.weather_percent = weather_percent
        
        # Зберегти
        success = await upsert_pricing_settings(config.database_path, pricing)
        
        if success:
            await state.clear()
            
            # Повідомлення в групи водіїв
            if weather_percent > 0:
                notification = (
                    f"🌧️ <b>УВІМКНЕНО НАДБАВКУ ЗА ПОГОДУ</b>\n\n"
                    f"Надбавка: <b>+{weather_percent:.0f}%</b>\n\n"
                    f"⚠️ Погодні умови погіршились!\n"
                    f"💰 Вартість замовлень збільшена"
                )
            else:
                notification = (
                    f"☀️ <b>ВИМКНЕНО НАДБАВКУ ЗА ПОГОДУ</b>\n\n"
                    f"✅ Погода покращала\n"
                    f"💰 Вартість повернута до стандартної"
                )
            
            # Відправити в усі групи
            sent_count = 0
            for city, group_id in config.city_groups.items():
                if group_id:
                    try:
                        await message.bot.send_message(group_id, notification)
                        sent_count += 1
                    except Exception as e:
                        logger.error(f"Помилка відправки в групу {city}: {e}")
            
            if weather_percent > 0:
                status_text = f"✅ Погодна надбавка увімкнена: <b>+{weather_percent:.0f}%</b>"
            else:
                status_text = "✅ Погодна надбавка вимкнена"
            
            await message.answer(
                f"{status_text}\n\n"
                f"📢 Повідомлення надіслано в {sent_count} груп водіїв",
                reply_markup=admin_menu_keyboard()
            )
        else:
            await message.answer("❌ Помилка оновлення", reply_markup=admin_menu_keyboard())
    
    @router.message(SettingsStates.admin_card)
    async def save_admin_card(message: Message, state: FSMContext) -> None:
        """Зберегти номер картки для комісії"""
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        card_number = message.text.strip()
        
        # Валідація номера картки (дозволити цифри та пробіли)
        import re
        clean_card = re.sub(r'[^\d]', '', card_number)
        
        if len(clean_card) < 13 or len(clean_card) > 19:
            await message.answer(
                "❌ Невірний формат номера картки!\n\n"
                "Номер картки має містити від 13 до 19 цифр.\n"
                "Спробуйте ще раз:"
            )
            return
        
        # Зберегти номер картки
        await set_admin_payment_card(card_number)
        await state.clear()
        
        await message.answer(
            f"✅ <b>Номер картки оновлено!</b>\n\n"
            f"Новий номер:\n"
            f"<code>{card_number}</code>\n\n"
            f"💡 Водії побачать цей номер при оплаті комісії.",
            reply_markup=admin_menu_keyboard()
        )
        
        logger.info(f"✅ Адмін #{message.from_user.id} оновив номер картки для комісії")
    
    @router.message(F.text == "👤 Клієнти")
    async def show_clients_list(message: Message) -> None:
        """Показати список всіх клієнтів"""
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        clients = await get_all_users(config.database_path, role="client")
        
        if not clients:
            await message.answer(
                "👤 <b>Клієнтів немає</b>\n\n"
                "Поки що жоден клієнт не зареєструвався.",
                reply_markup=admin_menu_keyboard(),
                parse_mode="HTML"
            )
            return
        
        # Розділити за статусом (заблоковані/активні)
        active_clients = [c for c in clients if not c.is_blocked]
        blocked_clients = [c for c in clients if c.is_blocked]
        
        # Показати активних клієнтів
        if active_clients:
            text = f"👤 <b>Активні клієнти ({len(active_clients)})</b>\n\n"
            
            for client in active_clients[:20]:  # Показати перші 20
                # Іконки для статусу
                city_emoji = f"🏙 {client.city}" if client.city else "🌍 Місто не вказано"
                karma_emoji = get_karma_emoji(client.karma)
                
                text += (
                    f"👤 <b>{client.full_name}</b>\n"
                    f"📱 {client.phone}\n"
                    f"{city_emoji}\n"
                    f"{karma_emoji} Карма: {client.karma}/100\n"
                    f"📦 Замовлень: {client.total_orders} (скасовано: {client.cancelled_orders})\n"
                    f"📅 Зареєстрований: {client.created_at.strftime('%d.%m.%Y')}\n"
                )
                
                # Кнопки керування
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="ℹ️ Детальніше",
                                callback_data=f"admin:client_info:{client.user_id}"
                            ),
                            InlineKeyboardButton(
                                text="🚫 Заблокувати",
                                callback_data=f"admin:client_block:{client.user_id}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="➕ Додати поїздки",
                                callback_data=f"admin:client_add_rides:{client.user_id}"
                            )
                        ]
                    ]
                )
                
                await message.answer(text, reply_markup=kb, parse_mode="HTML")
                text = ""  # Очистити для наступного клієнта
            
            if len(active_clients) > 20:
                await message.answer(
                    f"... і ще {len(active_clients) - 20} клієнтів",
                    parse_mode="HTML"
                )
        
        # Показати заблокованих клієнтів
        if blocked_clients:
            text = f"\n🚫 <b>Заблоковані клієнти ({len(blocked_clients)})</b>\n\n"
            
            for client in blocked_clients[:10]:
                text += (
                    f"👤 <b>{client.full_name}</b>\n"
                    f"📱 {client.phone}\n"
                    f"🚫 ЗАБЛОКОВАНИЙ\n"
                )
                
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ Розблокувати",
                                callback_data=f"admin:client_unblock:{client.user_id}"
                            )
                        ]
                    ]
                )
                
                await message.answer(text, reply_markup=kb, parse_mode="HTML")
                text = ""
        
        # Показати загальну статистику
        total_orders = sum(c.total_orders for c in clients)
        avg_karma = sum(c.karma for c in clients) / len(clients) if clients else 0
        
        stats_text = (
            f"\n📊 <b>Загальна статистика:</b>\n\n"
            f"👥 Всього клієнтів: {len(clients)}\n"
            f"✅ Активних: {len(active_clients)}\n"
            f"🚫 Заблокованих: {len(blocked_clients)}\n"
            f"📦 Всього замовлень: {total_orders}\n"
            f"⭐ Середня карма: {avg_karma:.1f}/100"
        )
        
        await message.answer(stats_text, reply_markup=admin_menu_keyboard(), parse_mode="HTML")
    
    @router.callback_query(F.data.startswith("admin:client_info:"))
    async def show_client_info(call: CallbackQuery) -> None:
        """Показати детальну інформацію про клієнта"""
        if not call.from_user or not is_admin(call.from_user.id):
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        user_id = int(call.data.split(":")[2])
        
        # Отримати клієнта з БД
        client = await get_user_by_id(config.database_path, user_id)
        
        if not client:
            await call.answer("❌ Клієнта не знайдено", show_alert=True)
            return
        
        # Отримати статистику замовлень
        from app.storage.db_connection import db_manager
        async with db_manager.connect(config.database_path) as db:
            # Останні замовлення
            async with db.execute(
                """SELECT COUNT(*), SUM(fare_amount) 
                   FROM orders 
                   WHERE user_id = ? AND status = 'completed'""",
                (user_id,)
            ) as cur:
                row = await cur.fetchone()
                completed_orders = row[0] if row else 0
                total_spent = row[1] if row and row[1] else 0
        
        karma_visual = format_karma(client.karma)
        status_emoji = "🚫" if client.is_blocked else "✅"
        
        text = (
            f"👤 <b>ІНФОРМАЦІЯ ПРО КЛІЄНТА</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>ПІБ:</b> {client.full_name}\n"
            f"<b>Телефон:</b> <code>{client.phone}</code>\n"
            f"<b>Telegram ID:</b> <code>{client.user_id}</code>\n"
            f"<b>Місто:</b> {client.city or 'Не вказано'}\n"
            f"<b>Мова:</b> {client.language}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>СТАТИСТИКА:</b>\n\n"
            f"{karma_visual}\n"
            f"📦 <b>Всього замовлень:</b> {client.total_orders}\n"
            f"✅ <b>Завершено:</b> {completed_orders}\n"
            f"❌ <b>Скасовано:</b> {client.cancelled_orders}\n"
            f"💰 <b>Витрачено:</b> {total_spent:.0f} грн\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{status_emoji} <b>Статус:</b> {'🚫 ЗАБЛОКОВАНИЙ' if client.is_blocked else '✅ Активний'}\n"
            f"📅 <b>Зареєстрований:</b> {client.created_at.strftime('%d.%m.%Y %H:%M')}"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🚫 Заблокувати" if not client.is_blocked else "✅ Розблокувати",
                        callback_data=f"admin:client_{'block' if not client.is_blocked else 'unblock'}:{user_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="➕ Додати поїздки",
                        callback_data=f"admin:client_add_rides:{user_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 Назад",
                        callback_data=f"admin:clients_back:{user_id}"
                    )
                ]
            ]
        )
        
        try:
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except:
            await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
        
        await call.answer()
    
    @router.callback_query(F.data.startswith("admin:client_block:"))
    async def block_client(call: CallbackQuery) -> None:
        """Заблокувати клієнта"""
        if not call.from_user or not is_admin(call.from_user.id):
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        user_id = int(call.data.split(":")[2])
        
        await block_user(config.database_path, user_id)
        
        await call.answer("🚫 Клієнта заблоковано!", show_alert=True)
        
        # Отримати оновлену інформацію про клієнта
        client = await get_user_by_id(config.database_path, user_id)
        if not client:
            await call.message.edit_text("❌ Клієнта не знайдено")
            return
        
        # Підрахувати замовлення
        orders = await get_user_order_history(config.database_path, user_id, limit=1000)
        
        text = (
            f"👤 <b>Клієнт</b>\n\n"
            f"🆔 ID: <code>{client.user_id}</code>\n"
            f"👤 Ім'я: {client.full_name}\n"
            f"📱 Телефон: <code>{client.phone}</code>\n"
            f"🏙️ Місто: {client.city or 'Не вказано'}\n"
            f"📅 Реєстрація: {client.created_at.strftime('%d.%m.%Y %H:%M') if client.created_at else 'N/A'}\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"🚕 Замовлень: {len(orders)}\n"
            f"⭐ Карма: {client.karma}/100\n"
            f"🚫 Статус: <b>{'🔴 ЗАБЛОКОВАНИЙ' if client.is_blocked else '🟢 Активний'}</b>"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Розблокувати",
                        callback_data=f"admin:client_unblock:{user_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 Назад",
                        callback_data=f"admin:clients_back:{user_id}"
                    )
                ]
            ]
        )
        
        try:
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except:
            pass
    
    @router.callback_query(F.data.startswith("admin:clients_back:"))
    async def clients_back_button(call: CallbackQuery) -> None:
        """Повернутися до короткої інформації про клієнта"""
        if not call.from_user or not is_admin(call.from_user.id):
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        await call.answer()
        
        # Отримати user_id з callback_data
        user_id = int(call.data.split(":")[2])
        
        # Отримати інформацію про клієнта
        client = await get_user_by_id(config.database_path, user_id)
        
        if not client:
            await call.message.edit_text("❌ Клієнта не знайдено", parse_mode="HTML")
            return
        
        # Показати коротку інформацію (як в списку)
        city_emoji = f"🏙 {client.city}" if client.city else "🌍 Місто не вказано"
        karma_emoji = get_karma_emoji(client.karma)
        status_emoji = "🔴 ЗАБЛОКОВАНИЙ" if client.is_blocked else "🟢 Активний"
        
        text = (
            f"👤 <b>{client.full_name}</b>\n"
            f"📱 <code>{client.phone}</code>\n"
            f"{city_emoji} | {karma_emoji} Карма: {client.karma}/100\n"
            f"🚕 Замовлень: {client.total_orders}\n"
            f"Статус: {status_emoji}"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="ℹ️ Детальніше",
                        callback_data=f"admin:client_info:{user_id}"
                    ),
                    InlineKeyboardButton(
                        text="🚫 Заблокувати" if not client.is_blocked else "✅ Розблокувати",
                        callback_data=f"admin:client_{'block' if not client.is_blocked else 'unblock'}:{user_id}"
                    )
                ]
            ]
        )
        
        try:
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except:
            pass
    
    @router.callback_query(F.data.startswith("admin:client_unblock:"))
    async def unblock_client(call: CallbackQuery) -> None:
        """Розблокувати клієнта"""
        if not call.from_user or not is_admin(call.from_user.id):
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        user_id = int(call.data.split(":")[2])
        
        await unblock_user(config.database_path, user_id)
        
        await call.answer("✅ Клієнта розблоковано!", show_alert=True)
        
        # Отримати оновлену інформацію про клієнта
        client = await get_user_by_id(config.database_path, user_id)
        if not client:
            await call.message.edit_text("❌ Клієнта не знайдено")
            return
        
        # Підрахувати замовлення
        orders = await get_user_order_history(config.database_path, user_id, limit=1000)
        
        text = (
            f"👤 <b>Клієнт</b>\n\n"
            f"🆔 ID: <code>{client.user_id}</code>\n"
            f"👤 Ім'я: {client.full_name}\n"
            f"📱 Телефон: <code>{client.phone}</code>\n"
            f"🏙️ Місто: {client.city or 'Не вказано'}\n"
            f"📅 Реєстрація: {client.created_at.strftime('%d.%m.%Y %H:%M') if client.created_at else 'N/A'}\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"🚕 Замовлень: {len(orders)}\n"
            f"⭐ Карма: {client.karma}/100\n"
            f"🚫 Статус: <b>{'🔴 ЗАБЛОКОВАНИЙ' if client.is_blocked else '🟢 Активний'}</b>"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🚫 Заблокувати",
                        callback_data=f"admin:client_block:{user_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 Назад",
                        callback_data=f"admin:clients_back:{user_id}"
                    )
                ]
            ]
        )
        
        try:
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except:
            pass

    @router.callback_query(F.data.startswith("admin:client_add_rides:"))
    async def start_add_rides(call: CallbackQuery, state: FSMContext) -> None:
        """Почати процес додавання поїздок клієнту"""
        if not call.from_user or not is_admin(call.from_user.id):
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        user_id = int(call.data.split(":")[2])
        
        # Зберегти user_id в state
        await state.update_data(manage_client_id=user_id)
        await state.set_state(ClientManageStates.add_rides_count)
        
        await call.answer()
        await call.message.answer(
            "➕ <b>Додати поїздки клієнту</b>\n\n"
            "Введіть кількість поїздок для додавання (1-100):\n\n"
            "💡 Це збільшить total_orders клієнта\n"
            "Наприклад: <code>5</code>",
            parse_mode="HTML"
        )
    
    @router.message(ClientManageStates.add_rides_count)
    async def process_add_rides(message: Message, state: FSMContext) -> None:
        """Обробити введену кількість поїздок"""
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        if not message.text:
            return
        
        # Валідація
        try:
            count = int(message.text.strip())
            if count < 1 or count > 100:
                await message.answer(
                    "❌ Введіть число від 1 до 100",
                    parse_mode="HTML"
                )
                return
        except ValueError:
            await message.answer(
                "❌ Введіть коректне число (1-100)",
                parse_mode="HTML"
            )
            return
        
        data = await state.get_data()
        user_id = data.get("manage_client_id")
        
        if not user_id:
            await message.answer("❌ Помилка: клієнт не знайдений")
            await state.clear()
            return
        
        # Додати поїздки
        from app.storage.db import add_rides_to_client
        success = await add_rides_to_client(config.database_path, user_id, count)
        
        if success:
            # Отримати оновлену інформацію
            client = await get_user_by_id(config.database_path, user_id)
            
            await message.answer(
                f"✅ <b>Поїздки додано!</b>\n\n"
                f"👤 Клієнт: {client.full_name if client else 'N/A'}\n"
                f"➕ Додано поїздок: <b>{count}</b>\n"
                f"📦 Загальна кількість: <b>{client.total_orders if client else 'N/A'}</b>",
                reply_markup=admin_menu_keyboard(),
                parse_mode="HTML"
            )
        else:
            await message.answer(
                "❌ Помилка додавання поїздок",
                reply_markup=admin_menu_keyboard(),
                parse_mode="HTML"
            )
        
        await state.clear()
    
    @router.message(F.text == "📢 Розсилка")
    async def start_broadcast(message: Message, state: FSMContext) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        await state.set_state(BroadcastStates.message)
        await message.answer(
            "✍️ Введіть повідомлення для розсилки всім користувачам:",
            reply_markup=cancel_keyboard()
        )

    @router.message(BroadcastStates.message)
    async def send_broadcast(message: Message, state: FSMContext) -> None:
        broadcast_text = message.text.strip()
        if not broadcast_text:
            await message.answer("Повідомлення не може бути порожнім.")
            return
        
        from app.storage.db_connection import db_manager
        
        try:
            async with db_manager.connect(config.database_path) as db:
                async with db.execute("SELECT DISTINCT user_id FROM users") as cur:
                    user_ids = [row[0] for row in await cur.fetchall()]
                async with db.execute("SELECT DISTINCT tg_user_id FROM drivers WHERE status = 'approved'") as cur:
                    driver_ids = [row[0] for row in await cur.fetchall()]
            
            all_ids = set(user_ids + driver_ids)
            success = 0
            failed = 0
            
            status_msg = await message.answer(f"📤 Розсилка... 0/{len(all_ids)}")
            
            for idx, user_id in enumerate(all_ids, 1):
                try:
                    await message.bot.send_message(user_id, f"📢 <b>Повідомлення від адміністрації:</b>\n\n{broadcast_text}")
                    success += 1
                except Exception as e:
                    logger.error(f"Failed to send broadcast to {user_id}: {e}")
                    failed += 1
                
                if idx % 10 == 0:
                    await status_msg.edit_text(f"📤 Розсилка... {idx}/{len(all_ids)}")
            
            await state.clear()
            await status_msg.edit_text(
                f"✅ Розсилка завершена!\n\n"
                f"Успішно: {success}\n"
                f"Помилки: {failed}"
            )
            await message.answer("Головне меню:", reply_markup=admin_menu_keyboard())
            
            logger.info(f"Admin {message.from_user.id} sent broadcast to {success} users")
        
        except Exception as e:
            logger.error(f"Error in broadcast: {e}")
            await message.answer("❌ Помилка при розсилці", reply_markup=admin_menu_keyboard())

    # Обробники для управління водіями
    @router.callback_query(F.data.startswith("admin_driver:"))
    async def handle_driver_management(call: CallbackQuery) -> None:
        """Управління водіями з адмін-панелі"""
        if not call.from_user or not is_admin(call.from_user.id):
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        parts = call.data.split(":")
        if len(parts) < 3:
            await call.answer("❌ Невірний формат", show_alert=True)
            return
        
        action = parts[1]
        driver_id = int(parts[2])
        
        try:
            driver = await get_driver_by_id(config.database_path, driver_id)
            if not driver:
                await call.answer("❌ Водія не знайдено", show_alert=True)
                return
            
            if action == "block":
                # Заблокувати водія (змінити статус на rejected)
                await update_driver_status(config.database_path, driver_id, "rejected")
                await call.answer("🚫 Водія заблоковано", show_alert=True)
                
                # Повідомити водія
                try:
                    await call.bot.send_message(
                        driver.tg_user_id,
                        "🚫 <b>Ваш акаунт заблоковано</b>\n\n"
                        "Адміністратор заблокував ваш доступ до системи.\n"
                        "Зверніться до підтримки для з'ясування причин.",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify driver about block: {e}")
                
                # Оновити повідомлення
                await call.message.edit_text(
                    f"🚫 <b>Водій заблокований</b>\n\n"
                    f"👤 {driver.full_name}\n"
                    f"📱 {driver.phone}\n"
                    f"🏙 Місто: {driver.city or 'Не вказано'}\n"
                    f"🚗 {driver.car_make} {driver.car_model}\n\n"
                    f"Статус змінено на: rejected",
                    parse_mode="HTML"
                )
                
                logger.info(f"Admin {call.from_user.id} blocked driver {driver_id}")
            
            elif action == "unblock":
                # Розблокувати водія (змінити статус на approved)
                await update_driver_status(config.database_path, driver_id, "approved")
                await call.answer("✅ Водія розблоковано", show_alert=True)
                
                # Повідомити водія з inline кнопкою
                try:
                    from app.handlers.keyboards import main_menu_keyboard
                    
                    kb_driver = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🚗 Відкрити панель водія", callback_data="open_driver_panel")]
                        ]
                    )
                    
                    await call.bot.send_message(
                        driver.tg_user_id,
                        "✅ <b>Ваш акаунт розблоковано!</b>\n\n"
                        "Адміністратор відновив ваш доступ до системи.\n\n"
                        "🎉 Ви знову можете:\n"
                        "• Приймати замовлення з групи водіїв\n"
                        "• Відстежувати свій заробіток\n"
                        "• Переглядати історію поїздок\n\n"
                        "Натисніть кнопку нижче для відкриття панелі водія:",
                        reply_markup=kb_driver,
                        parse_mode="HTML"
                    )
                    
                    # Відправити панель водія
                    is_driver_admin = driver.tg_user_id in config.bot.admin_ids
                    await call.bot.send_message(
                        driver.tg_user_id,
                        "🚗 <b>Панель водія активна!</b>\n\n"
                        "Використовуйте меню внизу:",
                        reply_markup=main_menu_keyboard(is_registered=True, is_driver=True, is_admin=is_driver_admin),
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify driver about unblock: {e}")
                
                # Оновити повідомлення адміна з новими кнопками
                kb_admin = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="🚫 Заблокувати знову", callback_data=f"admin_driver:block:{driver_id}"),
                            InlineKeyboardButton(text="💬 Написати", url=f"tg://user?id={driver.tg_user_id}")
                        ],
                        [InlineKeyboardButton(text="📊 Статистика", callback_data=f"admin_driver:stats:{driver_id}")]
                    ]
                )
                
                await call.message.edit_text(
                    f"✅ <b>Водій розблокований!</b>\n\n"
                    f"👤 {driver.full_name}\n"
                    f"📱 {driver.phone}\n"
                    f"🏙 Місто: {driver.city or 'Не вказано'}\n"
                    f"🚗 {driver.car_make} {driver.car_model}\n\n"
                    f"Статус змінено на: <b>approved</b>\n"
                    f"Водій отримав повідомлення і може працювати.",
                    reply_markup=kb_admin,
                    parse_mode="HTML"
                )
                
                logger.info(f"Admin {call.from_user.id} unblocked driver {driver_id}")
            
            elif action == "priority_toggle":
                # Перемикач пріоритетності водія (0/1)
                from app.storage.db_connection import db_manager
                new_priority = 0 if (driver.priority or 0) > 0 else 1
                async with db_manager.connect(config.database_path) as db:
                    await db.execute("UPDATE drivers SET priority = ? WHERE id = ?", (new_priority, driver_id))
                    await db.commit()

                await call.answer(
                    "✅ Пріоритет увімкнено" if new_priority else "✅ Пріоритет вимкнено",
                    show_alert=True,
                )

                # Оновити повідомлення з актуальним станом кнопки
                toggle_text = "⭐ Вимкнути пріоритет" if new_priority else "⭐ Увімкнути пріоритет"
                kb_updated = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="🚫 Заблокувати", callback_data=f"admin_driver:block:{driver_id}"),
                            InlineKeyboardButton(text="💬 Написати", url=f"tg://user?id={driver.tg_user_id}")
                        ],
                        [InlineKeyboardButton(text=toggle_text, callback_data=f"admin_driver:priority_toggle:{driver_id}")],
                        [InlineKeyboardButton(text="📊 Статистика", callback_data=f"admin_driver:stats:{driver_id}")],
                        [InlineKeyboardButton(text="🗑️ Видалити", callback_data=f"admin_driver:delete:{driver_id}")]
                    ]
                )

                text_updated = (
                    f"👤 <b>{driver.full_name}</b> {'⭐' if new_priority else ''} {'🟢 Онлайн' if driver.online else '🔴 Офлайн'}\n"
                    f"📱 {driver.phone}\n"
                    f"🏙️ {driver.city or 'Не вказано'}\n"
                    f"🚗 {driver.car_make} {driver.car_model}\n"
                    f"🎯 Клас: {driver.car_class}\n"
                    f"⭐ Пріоритет: {'Увімкнено' if new_priority else 'Вимкнено'}\n"
                    f"🆔 ID: {driver.id}"
                )

                try:
                    await call.message.edit_text(text_updated, reply_markup=kb_updated, parse_mode="HTML")
                except Exception:
                    # Якщо не можна редагувати (старе повідомлення), просто надішлемо нове
                    await call.message.answer(text_updated, reply_markup=kb_updated, parse_mode="HTML")

                logger.info(f"Admin {call.from_user.id} toggled priority for driver {driver_id} to {new_priority}")

            elif action == "stats":
                # Показати статистику водія
                from app.storage.db_connection import db_manager
                
                async with db_manager.connect(config.database_path) as db:
                    # Загальна кількість замовлень
                    async with db.execute(
                        "SELECT COUNT(*) FROM orders WHERE driver_id = ? AND status = 'completed'",
                        (driver_id,)
                    ) as cur:
                        completed_orders = (await cur.fetchone())[0]
                    
                    # Загальний заробіток
                    async with db.execute(
                        "SELECT SUM(fare_amount), SUM(commission) FROM orders WHERE driver_id = ? AND status = 'completed'",
                        (driver_id,)
                    ) as cur:
                        row = await cur.fetchone()
                        total_earnings = row[0] if row[0] else 0.0
                        total_commission = row[1] if row[1] else 0.0
                    
                    net_earnings = total_earnings - total_commission
                
                stats_text = (
                    f"📊 <b>Статистика водія</b>\n\n"
                    f"👤 {driver.full_name}\n"
                    f"📱 {driver.phone}\n"
                    f"🚗 {driver.car_make} {driver.car_model}\n\n"
                    f"✅ Виконано замовлень: {completed_orders}\n"
                    f"💰 Загальний заробіток: {total_earnings:.2f} грн\n"
                    f"💸 Комісія сплачена: {total_commission:.2f} грн\n"
                    f"💵 Чистий заробіток: {net_earnings:.2f} грн\n\n"
                    f"🏙️ Місто: {driver.city or 'Не вказано'}\n"
                    f"🎯 Клас авто: {driver.car_class}\n"
                    f"📅 Реєстрація: {driver.created_at.strftime('%Y-%m-%d')}"
                )
                
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 Назад", callback_data="close_stats")]
                    ]
                )
                
                await call.message.edit_text(stats_text, reply_markup=kb, parse_mode="HTML")
            
            elif action == "delete":
                # Показати підтвердження видалення
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"admin_driver:confirm_delete:{driver_id}"),
                            InlineKeyboardButton(text="❌ Скасувати", callback_data="close_stats")
                        ]
                    ]
                )
                
                await call.message.edit_text(
                    f"⚠️ <b>Підтвердження видалення</b>\n\n"
                    f"Ви дійсно хочете видалити водія?\n\n"
                    f"👤 {driver.full_name}\n"
                    f"📱 {driver.phone}\n"
                    f"🚗 {driver.car_make} {driver.car_model}\n\n"
                    f"❗️ Цю дію не можна скасувати!",
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            
            elif action == "confirm_delete":
                # Видалити водія з БД
                from app.storage.db_connection import db_manager
                
                async with db_manager.connect(config.database_path) as db:
                    await db.execute("DELETE FROM drivers WHERE id = ?", (driver_id,))
                    await db.commit()
                
                await call.answer("🗑️ Водія видалено", show_alert=True)
                await call.message.edit_text(
                    f"🗑️ <b>Водій видалений</b>\n\n"
                    f"Водія {driver.full_name} видалено з системи.",
                    parse_mode="HTML"
                )
                
                logger.info(f"Admin {call.from_user.id} deleted driver {driver_id}")
        
        except Exception as e:
            logger.error(f"Error in driver management: {e}")
            await call.answer("❌ Помилка при обробці", show_alert=True)
    
    @router.callback_query(F.data == "close_stats")
    async def close_stats(call: CallbackQuery) -> None:
        """Закрити вікно статистики"""
        await call.message.delete()
    
    @router.callback_query(F.data == "settings:refresh")
    async def refresh_settings(call: CallbackQuery) -> None:
        """Оновити налаштування"""
        if not call.from_user or not is_admin(call.from_user.id):
            await call.answer("❌ Немає доступу", show_alert=True)
            return
        
        from app.storage.db import get_online_drivers_count
        online_count = await get_online_drivers_count(config.database_path)
        
        # Отримати кількість водіїв за статусами
        from app.storage.db_connection import db_manager
        async with db_manager.connect(config.database_path) as db:
            async with db.execute("SELECT status, COUNT(*) FROM drivers GROUP BY status") as cur:
                status_counts = dict(await cur.fetchall())
            
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                users_count = (await cur.fetchone())[0]
            
            async with db.execute("SELECT COUNT(*) FROM orders") as cur:
                orders_count = (await cur.fetchone())[0]
        
        approved_count = status_counts.get("approved", 0)
        pending_count = status_counts.get("pending", 0)
        rejected_count = status_counts.get("rejected", 0)
        
        text = (
            "⚙️ <b>Налаштування системи</b>\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"   👥 Користувачів: {users_count}\n"
            f"   📦 Замовлень: {orders_count}\n\n"
            f"🚗 <b>Водії:</b>\n"
            f"   ✅ Активні: {approved_count}\n"
            f"   ⏳ На модерації: {pending_count}\n"
            f"   ❌ Заблоковані: {rejected_count}\n"
            f"   🟢 Онлайн: {online_count}\n\n"
            f"🌐 <b>Міста:</b> {', '.join(AVAILABLE_CITIES)}\n"
            f"💳 <b>Картка:</b> {config.payment_card or 'Не налаштована'}\n"
            f"👥 <b>Група:</b> {'Налаштована' if config.driver_group_chat_id else 'Не налаштована'}\n"
            f"🗺️ <b>Google Maps:</b> {'Підключено ✅' if config.google_maps_api_key else 'Не підключено ❌'}\n\n"
            f"💡 Для зміни налаштувань використовуйте ENV змінні на Render"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Оновити", callback_data="settings:refresh")]
            ]
        )
        
        await call.answer("✅ Оновлено")
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    
    # ==================== WIZARD ПЕРШОГО НАЛАШТУВАННЯ ====================
    
    @router.message(SettingsStates.wizard_economy)
    async def wizard_step_economy(message: Message, state: FSMContext) -> None:
        """Wizard крок 1: Економ"""
        try:
            value = float(message.text.strip())
            if value < 0.5 or value > 5.0:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0.5 до 5.0")
            return
        
        await state.update_data(economy_multiplier=value)
        await state.set_state(SettingsStates.wizard_standard)
        await message.answer(
            f"✅ Економ: x{value:.2f}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🚙 <b>КРОК 2/14: Клас СТАНДАРТ</b>\n\n"
            "Введіть множник для класу Стандарт:\n\n"
            "💡 <b>Рекомендовано:</b> <code>1.3</code> (+30%)\n\n"
            "Введіть число від 0.5 до 5.0:"
        )
    
    @router.message(SettingsStates.wizard_standard)
    async def wizard_step_standard(message: Message, state: FSMContext) -> None:
        """Wizard крок 2: Стандарт"""
        try:
            value = float(message.text.strip())
            if value < 0.5 or value > 5.0:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0.5 до 5.0")
            return
        
        await state.update_data(standard_multiplier=value)
        await state.set_state(SettingsStates.wizard_comfort)
        await message.answer(
            f"✅ Стандарт: x{value:.2f}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🚘 <b>КРОК 3/14: Клас КОМФОРТ</b>\n\n"
            "Введіть множник для класу Комфорт:\n\n"
            "💡 <b>Рекомендовано:</b> <code>1.6</code> (+60%)\n\n"
            "Введіть число від 0.5 до 5.0:"
        )
    
    @router.message(SettingsStates.wizard_comfort)
    async def wizard_step_comfort(message: Message, state: FSMContext) -> None:
        """Wizard крок 3: Комфорт"""
        try:
            value = float(message.text.strip())
            if value < 0.5 or value > 5.0:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0.5 до 5.0")
            return
        
        await state.update_data(comfort_multiplier=value)
        await state.set_state(SettingsStates.wizard_business)
        await message.answer(
            f"✅ Комфорт: x{value:.2f}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🏆 <b>КРОК 4/14: Клас БІЗНЕС</b>\n\n"
            "Введіть множник для класу Бізнес:\n\n"
            "💡 <b>Рекомендовано:</b> <code>2.0</code> (+100%)\n\n"
            "Введіть число від 0.5 до 5.0:"
        )
    
    @router.message(SettingsStates.wizard_business)
    async def wizard_step_business(message: Message, state: FSMContext) -> None:
        """Wizard крок 4: Бізнес"""
        try:
            value = float(message.text.strip())
            if value < 0.5 or value > 5.0:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0.5 до 5.0")
            return
        
        await state.update_data(business_multiplier=value)
        await state.set_state(SettingsStates.wizard_night)
        await message.answer(
            f"✅ Бізнес: x{value:.2f}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌙 <b>КРОК 5/14: НІЧНИЙ ТАРИФ</b>\n\n"
            "Введіть надбавку для нічного тарифу (23:00-06:00):\n\n"
            "💡 <b>Рекомендовано:</b> <code>50</code> (+50%)\n\n"
            "Введіть відсоток від 0 до 200:"
        )
    
    @router.message(SettingsStates.wizard_night)
    async def wizard_step_night(message: Message, state: FSMContext) -> None:
        """Wizard крок 5: Нічний тариф"""
        try:
            value = float(message.text.strip())
            if value < 0 or value > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        await state.update_data(night_percent=value)
        await state.set_state(SettingsStates.wizard_peak)
        await message.answer(
            f"✅ Нічний: +{value:.0f}%\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔥 <b>КРОК 6/14: ПІКОВИЙ ЧАС</b>\n\n"
            "Введіть надбавку для пікового часу (7-9, 17-19):\n\n"
            "💡 <b>Рекомендовано:</b> <code>30</code> (+30%)\n\n"
            "Введіть відсоток від 0 до 200:"
        )
    
    @router.message(SettingsStates.wizard_peak)
    async def wizard_step_peak(message: Message, state: FSMContext) -> None:
        """Wizard крок 6: Піковий час"""
        try:
            value = float(message.text.strip())
            if value < 0 or value > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        await state.update_data(peak_hours_percent=value)
        await state.set_state(SettingsStates.wizard_weekend)
        await message.answer(
            f"✅ Піковий: +{value:.0f}%\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎉 <b>КРОК 7/14: ВИХІДНІ ДНІ</b>\n\n"
            "Введіть надбавку для вихідних (Пт-Нд 18-23):\n\n"
            "💡 <b>Рекомендовано:</b> <code>20</code> (+20%)\n\n"
            "Введіть відсоток від 0 до 200:"
        )
    
    @router.message(SettingsStates.wizard_weekend)
    async def wizard_step_weekend(message: Message, state: FSMContext) -> None:
        """Wizard крок 7: Вихідні"""
        try:
            value = float(message.text.strip())
            if value < 0 or value > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        await state.update_data(weekend_percent=value)
        await state.set_state(SettingsStates.wizard_monday)
        await message.answer(
            f"✅ Вихідні: +{value:.0f}%\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📅 <b>КРОК 8/14: ПОНЕДІЛОК ВРАНЦІ</b>\n\n"
            "Введіть надбавку для понеділка вранці (7-10):\n\n"
            "💡 <b>Рекомендовано:</b> <code>15</code> (+15%)\n\n"
            "Введіть відсоток від 0 до 200:"
        )
    
    @router.message(SettingsStates.wizard_monday)
    async def wizard_step_monday(message: Message, state: FSMContext) -> None:
        """Wizard крок 8: Понеділок"""
        try:
            value = float(message.text.strip())
            if value < 0 or value > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        await state.update_data(monday_morning_percent=value)
        await state.set_state(SettingsStates.wizard_weather)
        await message.answer(
            f"✅ Понеділок: +{value:.0f}%\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌧️ <b>КРОК 9/14: ПОГОДНІ УМОВИ</b>\n\n"
            "Введіть початкову надбавку за погоду:\n\n"
            "💡 <b>Рекомендовано:</b> <code>0</code> (вимкнено, увімкнете коли буде дощ)\n\n"
            "Введіть відсоток від 0 до 200:"
        )
    
    @router.message(SettingsStates.wizard_weather)
    async def wizard_step_weather(message: Message, state: FSMContext) -> None:
        """Wizard крок 9: Погода"""
        try:
            value = float(message.text.strip())
            if value < 0 or value > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        await state.update_data(weather_percent=value)
        await state.set_state(SettingsStates.wizard_no_drivers)
        await message.answer(
            f"✅ Погода: +{value:.0f}%\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🚫 <b>КРОК 10/14: НЕМАЄ ВОДІЇВ</b>\n\n"
            "Введіть надбавку коли зовсім немає доступних водіїв:\n\n"
            "💡 <b>Рекомендовано:</b> <code>50</code> (+50%)\n\n"
            "Введіть відсоток від 0 до 200:"
        )
    
    @router.message(SettingsStates.wizard_no_drivers)
    async def wizard_step_no_drivers(message: Message, state: FSMContext) -> None:
        """Wizard крок 10: Немає водіїв"""
        try:
            value = float(message.text.strip())
            if value < 0 or value > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        await state.update_data(no_drivers_percent=value)
        await state.set_state(SettingsStates.wizard_demand_very_high)
        await message.answer(
            f"✅ Немає водіїв: +{value:.0f}%\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔥🔥🔥 <b>КРОК 11/14: ДУЖЕ ВИСОКИЙ ПОПИТ</b>\n\n"
            "Введіть надбавку коли &gt;3 замовлень на одного водія:\n\n"
            "💡 <b>Рекомендовано:</b> <code>40</code> (+40%)\n\n"
            "Введіть відсоток від 0 до 200:"
        )
    
    @router.message(SettingsStates.wizard_demand_very_high)
    async def wizard_step_demand_very_high(message: Message, state: FSMContext) -> None:
        """Wizard крок 11: Дуже високий попит"""
        try:
            value = float(message.text.strip())
            if value < 0 or value > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        await state.update_data(demand_very_high_percent=value)
        await state.set_state(SettingsStates.wizard_demand_high)
        await message.answer(
            f"✅ Дуже високий: +{value:.0f}%\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔥🔥 <b>КРОК 12/14: ВИСОКИЙ ПОПИТ</b>\n\n"
            "Введіть надбавку коли &gt;2 замовлень на одного водія:\n\n"
            "💡 <b>Рекомендовано:</b> <code>25</code> (+25%)\n\n"
            "Введіть відсоток від 0 до 200:"
        )
    
    @router.message(SettingsStates.wizard_demand_high)
    async def wizard_step_demand_high(message: Message, state: FSMContext) -> None:
        """Wizard крок 12: Високий попит"""
        try:
            value = float(message.text.strip())
            if value < 0 or value > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        await state.update_data(demand_high_percent=value)
        await state.set_state(SettingsStates.wizard_demand_medium)
        await message.answer(
            f"✅ Високий: +{value:.0f}%\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔥 <b>КРОК 13/14: СЕРЕДНІЙ ПОПИТ</b>\n\n"
            "Введіть надбавку коли &gt;1.5 замовлень на одного водія:\n\n"
            "💡 <b>Рекомендовано:</b> <code>15</code> (+15%)\n\n"
            "Введіть відсоток від 0 до 200:"
        )
    
    @router.message(SettingsStates.wizard_demand_medium)
    async def wizard_step_demand_medium(message: Message, state: FSMContext) -> None:
        """Wizard крок 13: Середній попит"""
        try:
            value = float(message.text.strip())
            if value < 0 or value > 200:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 200")
            return
        
        await state.update_data(demand_medium_percent=value)
        await state.set_state(SettingsStates.wizard_demand_low)
        await message.answer(
            f"✅ Середній: +{value:.0f}%\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💚 <b>КРОК 14/14: НИЗЬКИЙ ПОПИТ (ЗНИЖКА)</b>\n\n"
            "Введіть ЗНИЖКУ коли &lt;0.3 замовлень на одного водія:\n\n"
            "💡 <b>Рекомендовано:</b> <code>10</code> (-10% знижка)\n\n"
            "Введіть відсоток від 0 до 50:"
        )
    
    @router.message(SettingsStates.wizard_demand_low)
    async def wizard_step_demand_low(message: Message, state: FSMContext) -> None:
        """Wizard крок 14: Низький попит - ОСТАННІЙ КРОК"""
        try:
            value = float(message.text.strip())
            if value < 0 or value > 50:
                raise ValueError()
        except ValueError:
            await message.answer("❌ Введіть коректне число від 0 до 50")
            return
        
        # Отримати всі дані
        data = await state.get_data()
        
        # Створити об'єкт налаштувань
        from datetime import datetime, timezone
        pricing = PricingSettings(
            economy_multiplier=data['economy_multiplier'],
            standard_multiplier=data['standard_multiplier'],
            comfort_multiplier=data['comfort_multiplier'],
            business_multiplier=data['business_multiplier'],
            night_percent=data['night_percent'],
            peak_hours_percent=data['peak_hours_percent'],
            weekend_percent=data['weekend_percent'],
            monday_morning_percent=data['monday_morning_percent'],
            weather_percent=data['weather_percent'],
            no_drivers_percent=data['no_drivers_percent'],
            demand_very_high_percent=data['demand_very_high_percent'],
            demand_high_percent=data['demand_high_percent'],
            demand_medium_percent=data['demand_medium_percent'],
            demand_low_discount_percent=value,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        # Зберегти в БД
        success = await upsert_pricing_settings(config.database_path, pricing)
        
        if success:
            await state.clear()
            await message.answer(
                "🎉 <b>НАЛАШТУВАННЯ ЗАВЕРШЕНО!</b>\n\n"
                "✅ Всі параметри ціноутворення збережено.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "📊 <b>ВАШІ НАЛАШТУВАННЯ:</b>\n\n"
                "🚗 <b>Класи авто:</b>\n"
                f"• Економ: x{pricing.economy_multiplier:.2f}\n"
                f"• Стандарт: x{pricing.standard_multiplier:.2f}\n"
                f"• Комфорт: x{pricing.comfort_multiplier:.2f}\n"
                f"• Бізнес: x{pricing.business_multiplier:.2f}\n\n"
                "⏰ <b>Часові націнки:</b>\n"
                f"• Нічний: +{pricing.night_percent:.0f}%\n"
                f"• Піковий: +{pricing.peak_hours_percent:.0f}%\n"
                f"• Вихідні: +{pricing.weekend_percent:.0f}%\n"
                f"• Понеділок: +{pricing.monday_morning_percent:.0f}%\n\n"
                "🌧️ <b>Погода:</b> +" + f"{pricing.weather_percent:.0f}%\n\n"
                "📊 <b>Попит:</b>\n"
                f"• Немає водіїв: +{pricing.no_drivers_percent:.0f}%\n"
                f"• Дуже високий (&gt;3:1): +{pricing.demand_very_high_percent:.0f}%\n"
                f"• Високий (&gt;2:1): +{pricing.demand_high_percent:.0f}%\n"
                f"• Середній (&gt;1.5:1): +{pricing.demand_medium_percent:.0f}%\n"
                f"• Низький (&lt;0.3:1): -{pricing.demand_low_discount_percent:.0f}%\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Тепер ви можете змінювати ці параметри\n"
                "через меню ⚙️ Налаштування",
                reply_markup=admin_menu_keyboard()
            )
        else:
            await message.answer(
                "❌ Помилка збереження налаштувань.\n"
                "Спробуйте ще раз через меню ⚙️ Налаштування",
                reply_markup=admin_menu_keyboard()
            )
    
    # Додати обробники налаштувань ціноутворення
    create_pricing_handlers(
        router, config, is_admin, SettingsStates, 
        get_pricing_settings, upsert_pricing_settings, PricingSettings
    )
    
    return router
