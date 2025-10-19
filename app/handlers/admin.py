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
)


CANCEL_TEXT = "Скасувати"


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Модерація водіїв")],
            [KeyboardButton(text="💰 Тарифи"), KeyboardButton(text="🚗 Водії")],
            [KeyboardButton(text="📢 Розсилка"), KeyboardButton(text="⚙️ Налаштування")],
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


class BroadcastStates(StatesGroup):
    message = State()


def create_router(config: AppConfig) -> Router:
    router = Router(name="admin")
    
    def is_admin(user_id: int) -> bool:
        return user_id in set(config.bot.admin_ids)

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
            # Отримати всіх водіїв
            async with db.execute(
                """
                SELECT id, tg_user_id, full_name, phone, car_make, car_model, car_plate, 
                       car_class, status, city, online, created_at
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
            await message.answer(
                f"✅ <b>Активні водії ({len(approved_drivers)})</b>\n\n"
                "Натисніть на водія для управління:",
                parse_mode="HTML"
            )
            for d in approved_drivers:
                driver_id, tg_user_id, full_name, phone, car_make, car_model, car_plate, \
                    car_class, status, city, online, created_at = d
                
                online_status = "🟢 Онлайн" if online else "🔴 Офлайн"
                
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="🚫 Заблокувати", callback_data=f"admin_driver:block:{driver_id}"),
                            InlineKeyboardButton(text="💬 Написати", url=f"tg://user?id={tg_user_id}")
                        ],
                        [InlineKeyboardButton(text="📊 Статистика", callback_data=f"admin_driver:stats:{driver_id}")],
                        [InlineKeyboardButton(text="🗑️ Видалити", callback_data=f"admin_driver:delete:{driver_id}")]
                    ]
                )
                
                text = (
                    f"👤 <b>{full_name}</b> {online_status}\n"
                    f"📱 {phone}\n"
                    f"🏙️ {city or 'Не вказано'}\n"
                    f"🚗 {car_make} {car_model} ({car_plate})\n"
                    f"🎯 Клас: {car_class}\n"
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
                    car_class, status, city, online, created_at = d
                
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
                    
                    # Додати посилання на групу водіїв, якщо воно є
                    if config.driver_group_invite_link:
                        welcome_text += (
                            f"📱 <b>Долучайтесь до групи водіїв:</b>\n"
                            f"{config.driver_group_invite_link}\n\n"
                            "⚠️ Всі замовлення публікуються в цій групі. "
                            "Обов'язково приєднайтесь!\n\n"
                        )
                    
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
                        f"🚗 Авто: {driver.car_make} {driver.car_model} ({driver.car_plate})"
                    )
                
                logger.info(f"Admin {call.from_user.id} rejected driver {driver_id}")
        
        except Exception as e:
            logger.error(f"Error in driver moderation: {e}")
            await call.answer("❌ Помилка при обробці", show_alert=True)

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
                    f"🚗 {driver.car_make} {driver.car_model}\n\n"
                    f"Статус змінено на: <b>approved</b>\n"
                    f"Водій отримав повідомлення і може працювати.",
                    reply_markup=kb_admin,
                    parse_mode="HTML"
                )
                
                logger.info(f"Admin {call.from_user.id} unblocked driver {driver_id}")
            
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
    
    @router.message(F.text == "⚙️ Налаштування")
    async def show_settings(message: Message) -> None:
        """Налаштування системи"""
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        from app.storage.db import get_online_drivers_count
        online_count = await get_online_drivers_count(config.database_path)
        
        # Отримати кількість водіїв за статусами
        from app.storage.db_connection import db_manager
        async with db_manager.connect(config.database_path) as db:
            async with db.execute("SELECT status, COUNT(*) FROM drivers GROUP BY status") as cur:
                status_counts = dict(await cur.fetchall())
            
            # Загальна кількість користувачів
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                users_count = (await cur.fetchone())[0]
            
            # Загальна кількість замовлень
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
        
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    
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
    
    return router
