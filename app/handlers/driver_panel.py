"""НОВИЙ кабінет водія - версія 3.0"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from aiogram import F, Router
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
    get_driver_by_tg_user_id,
    get_driver_by_id,
    get_order_by_id,
    accept_order,
    start_order,
    complete_order,
    get_driver_earnings_today,
    get_driver_unpaid_commission,
    get_driver_order_history,
    mark_commission_paid,
    Payment,
    insert_payment,
    get_latest_tariff,
    update_driver_location,
    set_driver_online_status,
    get_online_drivers_count,
    get_driver_tips_total,
)

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="driver_panel")

    @router.message(F.text == "🚗 Панель водія")
    async def driver_panel_main(message: Message) -> None:
        """Головна панель водія - НОВА ВЕРСІЯ 3.0"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            await message.answer(
                "❌ Ви не зареєстровані як водій або ваша заявка ще не підтверджена."
            )
            return
        
        # Заробіток
        earnings, commission = await get_driver_earnings_today(config.database_path, message.from_user.id)
        net = earnings - commission
        
        # Чайові
        tips = 0.0
        try:
            tips = await get_driver_tips_total(config.database_path, message.from_user.id)
        except:
            tips = 0.0
        
        # Статус
        status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        location = "📍 Активна" if driver.last_lat and driver.last_lon else "❌ Не встановлена"
        
        # Онлайн водії
        online = 0
        try:
            online = await get_online_drivers_count(config.database_path, driver.city)
        except:
            online = 0
        
        # ТЕКСТ з усіма полями
        text = (
            f"🚗 <b>Панель водія</b>\n\n"
            f"Статус: {status}\n"
            f"Локація: {location}\n"
            f"ПІБ: {driver.full_name}\n"
            f"🏙 Місто: {driver.city or 'Не вказано'}\n"
            f"👥 Водіїв онлайн: {online}\n"
            f"🚙 Авто: {driver.car_make} {driver.car_model}\n"
            f"🔢 Номер: {driver.car_plate}\n\n"
            f"💰 Заробіток сьогодні: {earnings:.2f} грн\n"
            f"💸 Комісія до сплати: {commission:.2f} грн\n"
            f"💵 Чистий заробіток: {net:.2f} грн\n"
            f"💝 Чайові (всього): {tips:.2f} грн\n\n"
            "ℹ️ Замовлення надходять у групу водіїв.\n\n"
            "👇 Натисніть '🚀 Почати роботу' для керування"
        )
        
        # КЛАВІАТУРА з кнопкою
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚀 Почати роботу")],
                [KeyboardButton(text="📍 Поділитися локацією", request_location=True)],
                [KeyboardButton(text="📊 Мій заробіток"), KeyboardButton(text="💳 Комісія")],
                [KeyboardButton(text="📜 Історія поїздок")],
                [KeyboardButton(text="👤 Кабінет клієнта"), KeyboardButton(text="ℹ️ Допомога")]
            ],
            resize_keyboard=True
        )
        
        await message.answer(text, reply_markup=kb)

    @router.message(F.text == "🚀 Почати роботу")
    async def start_work(message: Message) -> None:
        """Меню керування"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        
        online = 0
        try:
            online = await get_online_drivers_count(config.database_path, driver.city)
        except:
            pass
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🟢 ПОЧАТИ ПРАЦЮВАТИ" if not driver.online else "🔴 ПІТИ В ОФЛАЙН",
                    callback_data="work:toggle"
                )],
                [InlineKeyboardButton(text="📊 Статистика", callback_data="work:stats")],
                [InlineKeyboardButton(text="🔄 Оновити", callback_data="work:refresh")]
            ]
        )
        
        await message.answer(
            f"🚀 <b>Меню керування</b>\n\n"
            f"Статус: {status}\n"
            f"👥 Водіїв онлайн: {online}\n\n"
            "Оберіть дію:",
            reply_markup=kb
        )

    @router.callback_query(F.data == "work:toggle")
    async def toggle_status(call: CallbackQuery) -> None:
        """Перемкнути онлайн/офлайн"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            return
        
        new = not driver.online
        await set_driver_online_status(config.database_path, driver.id, new)
        
        online = await get_online_drivers_count(config.database_path, driver.city)
        
        if new:
            await call.answer(f"✅ Ви онлайн! Водіїв: {online}", show_alert=True)
        else:
            await call.answer("🔴 Ви офлайн", show_alert=True)
        
        # Оновити
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🟢 ПОЧАТИ ПРАЦЮВАТИ" if not driver.online else "🔴 ПІТИ В ОФЛАЙН",
                    callback_data="work:toggle"
                )],
                [InlineKeyboardButton(text="📊 Статистика", callback_data="work:stats")],
                [InlineKeyboardButton(text="🔄 Оновити", callback_data="work:refresh")]
            ]
        )
        
        if call.message:
            await call.message.edit_text(
                f"🚀 <b>Меню керування</b>\n\n"
                f"Статус: {status}\n"
                f"👥 Водіїв онлайн: {online}\n\n"
                "Оберіть дію:",
                reply_markup=kb
            )

    @router.callback_query(F.data == "work:refresh")
    async def refresh_menu(call: CallbackQuery) -> None:
        """Оновити меню"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            return
        
        status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        online = await get_online_drivers_count(config.database_path, driver.city)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🟢 ПОЧАТИ ПРАЦЮВАТИ" if not driver.online else "🔴 ПІТИ В ОФЛАЙН",
                    callback_data="work:toggle"
                )],
                [InlineKeyboardButton(text="📊 Статистика", callback_data="work:stats")],
                [InlineKeyboardButton(text="🔄 Оновити", callback_data="work:refresh")]
            ]
        )
        
        if call.message:
            await call.message.edit_text(
                f"🚀 <b>Меню керування</b>\n\n"
                f"Статус: {status}\n"
                f"👥 Водіїв онлайн: {online}\n\n"
                "Оберіть дію:",
                reply_markup=kb
            )
        await call.answer("✅ Оновлено!")

    @router.callback_query(F.data == "work:stats")
    async def show_stats_menu(call: CallbackQuery) -> None:
        """Статистика"""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📅 Сьогодні", callback_data="stats:today")],
                [InlineKeyboardButton(text="📅 Тиждень", callback_data="stats:week")],
                [InlineKeyboardButton(text="📅 Місяць", callback_data="stats:month")],
                [InlineKeyboardButton(text="« Назад", callback_data="work:refresh")]
            ]
        )
        if call.message:
            await call.message.edit_text("📊 <b>Статистика</b>\n\nОберіть період:", reply_markup=kb)
        await call.answer()

    @router.message(F.location)
    async def update_loc(message: Message) -> None:
        """Оновити локацію"""
        if not message.from_user or not message.location:
            return
        
        await update_driver_location(
            config.database_path,
            message.from_user.id,
            message.location.latitude,
            message.location.longitude
        )
        
        await message.answer("✅ Локацію оновлено!")

    @router.message(F.text == "📊 Мій заробіток")
    async def earnings(message: Message) -> None:
        """Заробіток"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        today, comm = await get_driver_earnings_today(config.database_path, message.from_user.id)
        
        await message.answer(
            f"💰 <b>Заробіток</b>\n\n"
            f"Сьогодні: {today:.2f} грн\n"
            f"Комісія: {comm:.2f} грн\n"
            f"Чистий: {today - comm:.2f} грн"
        )

    @router.message(F.text == "💳 Комісія")
    async def commission(message: Message) -> None:
        """Комісія"""
        if not message.from_user:
            return
        
        unpaid = await get_driver_unpaid_commission(config.database_path, message.from_user.id)
        
        if unpaid > 0:
            await message.answer(
                f"💳 <b>Комісія до сплати:</b> {unpaid:.2f} грн\n\n"
                f"Картка: <code>{config.payment_card or '4149499901234567'}</code>"
            )
        else:
            await message.answer("✅ Комісія сплачена!")

    @router.message(F.text == "📜 Історія поїздок")
    async def history(message: Message) -> None:
        """Історія"""
        if not message.from_user:
            return
        
        orders = await get_driver_order_history(config.database_path, message.from_user.id, limit=5)
        
        if not orders:
            await message.answer("📜 Поки немає поїздок")
            return
        
        text = "📜 <b>Останні 5 поїздок:</b>\n\n"
        for i, o in enumerate(orders, 1):
            text += f"{i}. {o.pickup_address[:20]}... → {o.destination_address[:20]}...\n"
            text += f"   💰 {o.fare_amount or 0:.0f} грн\n\n"
        
        await message.answer(text)

    # Обробники замовлень
    @router.callback_query(F.data.startswith("accept_order:"))
    async def accept(call: CallbackQuery) -> None:
        """Прийняти замовлення"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            return
        
        order_id = int(call.data.split(":")[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.status != "pending":
            await call.answer("❌ Вже прийнято", show_alert=True)
            return
        
        success = await accept_order(config.database_path, order_id, driver.id)
        
        if success:
            await call.answer("✅ Прийнято!", show_alert=True)
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📍 Я на місці", callback_data=f"arrived:{order_id}")],
                    [InlineKeyboardButton(text="🚗 Почати поїздку", callback_data=f"start:{order_id}")]
                ]
            )
            
            if call.message:
                await call.message.edit_text(
                    f"✅ <b>Замовлення #{order_id}</b>\n\n"
                    f"📍 Від: {order.pickup_address}\n"
                    f"📍 До: {order.destination_address}",
                    reply_markup=kb
                )

    @router.callback_query(F.data.startswith("arrived:"))
    async def driver_arrived(call: CallbackQuery) -> None:
        """Водій на місці"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver or driver.id != order.driver_id:
            await call.answer("❌ Це не ваше замовлення", show_alert=True)
            return
        
        await call.answer("📍 Повідомлення надіслано клієнту!", show_alert=True)
        
        # Повідомити клієнта
        try:
            await call.bot.send_message(
                order.user_id,
                f"📍 <b>Водій на місці!</b>\n\n"
                f"🚗 {driver.full_name}\n"
                f"📱 <code>{driver.phone}</code>\n\n"
                f"Водій чекає на вас!"
            )
        except Exception as e:
            logger.error(f"Failed to notify client: {e}")
        
        # Оновити кнопки
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚗 Почати поїздку", callback_data=f"start:{order_id}")]
            ]
        )
        
        if call.message:
            await call.message.edit_reply_markup(reply_markup=kb)
    
    @router.callback_query(F.data.startswith("start:"))
    async def start_trip(call: CallbackQuery) -> None:
        """Почати поїздку"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[1])
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        await start_order(config.database_path, order_id, driver.id)
        
        await call.answer("🚗 Поїздка почалась!", show_alert=True)
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Завершити", callback_data=f"complete:{order_id}")]
            ]
        )
        
        if call.message:
            await call.message.edit_reply_markup(reply_markup=kb)

    @router.callback_query(F.data.startswith("complete:"))
    async def complete_trip(call: CallbackQuery) -> None:
        """Завершити"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[1])
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        # Розрахунок вартості з БД (якщо є) або базова
        fare = order.fare_amount if order.fare_amount else 100.0
        distance_m = order.distance_m if order.distance_m else 0
        duration_s = order.duration_s if order.duration_s else 0
        commission = fare * 0.02  # 2%
        
        await complete_order(
            config.database_path,
            order_id,
            driver.id,
            fare,
            distance_m,
            duration_s,
            commission
        )
        
        await call.answer(f"✅ Завершено! {fare:.0f} грн", show_alert=True)
        
        if call.message:
            await call.message.edit_text(f"✅ Поїздка завершена!\n💰 {fare:.0f} грн")

    return router
