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

from app.config.config import AppConfig
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
            [KeyboardButton(text="💰 Тарифи"), KeyboardButton(text="📋 Замовлення")],
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
        
        import aiosqlite
        
        async with aiosqlite.connect(config.database_path) as db:
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
        
        text = (
            "📊 <b>Статистика системи</b>\n\n"
            f"📦 Всього замовлень: {total_orders}\n"
            f"✅ Виконано: {completed_orders}\n"
            f"🚗 Активних водіїв: {active_drivers}\n"
            f"⏳ Водіїв на модерації: {pending_drivers}\n\n"
            f"💵 Загальний дохід: {total_revenue:.2f} грн\n"
            f"💰 Загальна комісія: {total_commission:.2f} грн\n"
            f"⚠️ Несплачена комісія: {unpaid_commission:.2f} грн"
        )
        await message.answer(text, reply_markup=admin_menu_keyboard())

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
                f"Мінімальна сума: {tariff.minimum:.2f} грн\n\n"
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
        await message.answer("Введіть ціну за кілометр (грн):", reply_markup=cancel_keyboard())

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
        
        data = await state.get_data()
        tariff = Tariff(
            id=None,
            base_fare=data["base_fare"],
            per_km=data["per_km"],
            per_minute=data["per_minute"],
            minimum=minimum,
            created_at=datetime.now(timezone.utc)
        )
        await insert_tariff(config.database_path, tariff)
        await state.clear()
        await message.answer(
            "✅ Тарифи успішно оновлено!", 
            reply_markup=admin_menu_keyboard()
        )

    @router.message(F.text == "📋 Замовлення")
    async def show_recent_orders(message: Message) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        
        orders = await fetch_recent_orders(config.database_path, limit=10)
        if not orders:
            await message.answer("Замовлень поки немає.", reply_markup=admin_menu_keyboard())
            return
        
        text = "<b>📋 Останні замовлення:</b>\n\n"
        for o in orders:
            status_emoji = {
                "pending": "⏳",
                "offered": "📤",
                "accepted": "✅",
                "in_progress": "🚗",
                "completed": "✔️",
                "cancelled": "❌"
            }.get(o.status, "❓")
            
            text += (
                f"{status_emoji} <b>№{o.id}</b> ({o.status})\n"
                f"Клієнт: {o.name} ({o.phone})\n"
                f"Маршрут: {o.pickup_address[:30]}... → {o.destination_address[:30]}...\n"
                f"Створено: {o.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            )
            if o.fare_amount:
                text += f"Вартість: {o.fare_amount:.2f} грн\n"
            text += "\n"
        
        await message.answer(text, reply_markup=admin_menu_keyboard())

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
                
                # Notify driver
                try:
                    from app.handlers.start import main_menu_keyboard
                    
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🚗 Відкрити панель водія", callback_data="open_driver_panel")]
                        ]
                    )
                    
                    await call.bot.send_message(
                        driver.tg_user_id,
                        "🎉 <b>Вітаємо!</b>\n\n"
                        "Вашу заявку схвалено! Ви тепер водій нашого сервісу.\n\n"
                        "✅ Тепер ви можете:\n"
                        "• Приймати замовлення з групи водіїв\n"
                        "• Відстежувати свій заробіток\n"
                        "• Переглядати історію поїздок\n\n"
                        "Натисніть кнопку нижче або напишіть боту /start",
                        reply_markup=kb
                    )
                    
                    # Також відправимо меню водія
                    await call.bot.send_message(
                        driver.tg_user_id,
                        "🚗 <b>Панель водія активована!</b>\n\n"
                        "Оберіть дію з меню:",
                        reply_markup=main_menu_keyboard(is_registered=True, is_driver=True)
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
        
        import aiosqlite
        
        try:
            async with aiosqlite.connect(config.database_path) as db:
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

    return router
