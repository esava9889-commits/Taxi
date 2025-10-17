"""Панель водія - НОВА ВЕРСІЯ"""
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
from app.utils.maps import generate_static_map_url, get_distance_and_duration

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="driver_panel")

    @router.message(F.text == "🚗 Панель водія")
    async def driver_menu(message: Message) -> None:
        """Головна панель водія"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            await message.answer(
                "❌ Ви не зареєстровані як водій або ваша заявка ще не підтверджена.\n\n"
                "Використайте кнопку '🚗 Стати водієм' для подання заявки."
            )
            return
        
        # Заробіток
        earnings, commission_owed = await get_driver_earnings_today(config.database_path, message.from_user.id)
        net_earnings = earnings - commission_owed
        
        # Чайові
        tips_total = 0.0
        try:
            tips_total = await get_driver_tips_total(config.database_path, message.from_user.id)
        except Exception as e:
            logger.error(f"Помилка чайових: {e}")
        
        # Статус
        online_status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        location_status = "📍 Активна" if driver.last_lat and driver.last_lon else "❌ Не встановлена"
        
        # Онлайн водії
        online_count = 0
        try:
            online_count = await get_online_drivers_count(config.database_path, driver.city)
        except Exception as e:
            logger.error(f"Помилка підрахунку: {e}")
        
        # Текст панелі
        text = (
            f"🚗 <b>Панель водія</b>\n\n"
            f"Статус: {online_status}\n"
            f"Локація: {location_status}\n"
            f"ПІБ: {driver.full_name}\n"
            f"🏙 Місто: {driver.city or 'Не вказано'}\n"
            f"👥 Водіїв онлайн: {online_count}\n"
            f"🚙 Авто: {driver.car_make} {driver.car_model}\n"
            f"🔢 Номер: {driver.car_plate}\n\n"
            f"💰 Заробіток сьогодні: {earnings:.2f} грн\n"
            f"💸 Комісія до сплати: {commission_owed:.2f} грн\n"
            f"💵 Чистий заробіток: {net_earnings:.2f} грн\n"
            f"💝 Чайові (всього): {tips_total:.2f} грн\n\n"
            "ℹ️ Замовлення надходять у групу водіїв.\n"
            "Прийміть замовлення першим, щоб його отримати!\n\n"
            "💡 <i>Поділіться локацією щоб клієнти могли бачити де ви</i>"
        )
        
        # INLINE кнопки (під повідомленням)
        inline_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🟢 ПОЧАТИ ПРАЦЮВАТИ" if not driver.online else "🔴 ПІТИ В ОФЛАЙН",
                    callback_data="driver:toggle_online"
                )],
                [InlineKeyboardButton(text="📊 Статистика", callback_data="driver:stats")],
                [InlineKeyboardButton(text="🔄 Оновити", callback_data="driver:refresh")]
            ]
        )
        
        # REPLY клавіатура (внизу екрану)
        reply_kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Поділитися локацією", request_location=True)],
                [KeyboardButton(text="📊 Мій заробіток"), KeyboardButton(text="💳 Комісія")],
                [KeyboardButton(text="📜 Історія поїздок"), KeyboardButton(text="📊 Розширена аналітика")],
                [KeyboardButton(text="👤 Кабінет клієнта"), KeyboardButton(text="ℹ️ Допомога")]
            ],
            resize_keyboard=True
        )
        
        # Відправити
        await message.answer(text, reply_markup=inline_kb)
        await message.answer("👇 <b>Меню:</b>", reply_markup=reply_kb)

    @router.callback_query(F.data == "driver:toggle_online")
    async def toggle_online(call: CallbackQuery) -> None:
        """Перемкнути онлайн/офлайн"""
        if not call.from_user or not call.message:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        # Перемкнути статус
        new_status = not driver.online
        await set_driver_online_status(config.database_path, driver.id, new_status)
        
        # Повідомлення
        if new_status:
            online_count = await get_online_drivers_count(config.database_path, driver.city)
            await call.answer(f"✅ Ви онлайн! Водіїв онлайн: {online_count}", show_alert=True)
        else:
            await call.answer("🔴 Ви офлайн", show_alert=True)
        
        # Оновити панель
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        
        earnings, commission_owed = await get_driver_earnings_today(config.database_path, call.from_user.id)
        net_earnings = earnings - commission_owed
        
        tips_total = 0.0
        try:
            tips_total = await get_driver_tips_total(config.database_path, call.from_user.id)
        except:
            pass
        
        online_status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        location_status = "📍 Активна" if driver.last_lat and driver.last_lon else "❌ Не встановлена"
        
        online_count = 0
        try:
            online_count = await get_online_drivers_count(config.database_path, driver.city)
        except:
            pass
        
        text = (
            f"🚗 <b>Панель водія</b>\n\n"
            f"Статус: {online_status}\n"
            f"Локація: {location_status}\n"
            f"ПІБ: {driver.full_name}\n"
            f"🏙 Місто: {driver.city or 'Не вказано'}\n"
            f"👥 Водіїв онлайн: {online_count}\n"
            f"🚙 Авто: {driver.car_make} {driver.car_model}\n"
            f"🔢 Номер: {driver.car_plate}\n\n"
            f"💰 Заробіток сьогодні: {earnings:.2f} грн\n"
            f"💸 Комісія до сплати: {commission_owed:.2f} грн\n"
            f"💵 Чистий заробіток: {net_earnings:.2f} грн\n"
            f"💝 Чайові (всього): {tips_total:.2f} грн\n\n"
            "ℹ️ Замовлення надходять у групу водіїв.\n"
            "Прийміть замовлення першим, щоб його отримати!\n\n"
            "💡 <i>Поділіться локацією щоб клієнти могли бачити де ви</i>"
        )
        
        inline_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🟢 ПОЧАТИ ПРАЦЮВАТИ" if not driver.online else "🔴 ПІТИ В ОФЛАЙН",
                    callback_data="driver:toggle_online"
                )],
                [InlineKeyboardButton(text="📊 Статистика", callback_data="driver:stats")],
                [InlineKeyboardButton(text="🔄 Оновити", callback_data="driver:refresh")]
            ]
        )
        
        await call.message.edit_text(text, reply_markup=inline_kb)

    @router.callback_query(F.data == "driver:refresh")
    async def refresh_panel(call: CallbackQuery) -> None:
        """Оновити панель"""
        if not call.from_user or not call.message:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        earnings, commission_owed = await get_driver_earnings_today(config.database_path, call.from_user.id)
        net_earnings = earnings - commission_owed
        
        tips_total = 0.0
        try:
            tips_total = await get_driver_tips_total(config.database_path, call.from_user.id)
        except:
            pass
        
        online_status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        location_status = "📍 Активна" if driver.last_lat and driver.last_lon else "❌ Не встановлена"
        
        online_count = 0
        try:
            online_count = await get_online_drivers_count(config.database_path, driver.city)
        except:
            pass
        
        text = (
            f"🚗 <b>Панель водія</b>\n\n"
            f"Статус: {online_status}\n"
            f"Локація: {location_status}\n"
            f"ПІБ: {driver.full_name}\n"
            f"🏙 Місто: {driver.city or 'Не вказано'}\n"
            f"👥 Водіїв онлайн: {online_count}\n"
            f"🚙 Авто: {driver.car_make} {driver.car_model}\n"
            f"🔢 Номер: {driver.car_plate}\n\n"
            f"💰 Заробіток сьогодні: {earnings:.2f} грн\n"
            f"💸 Комісія до сплати: {commission_owed:.2f} грн\n"
            f"💵 Чистий заробіток: {net_earnings:.2f} грн\n"
            f"💝 Чайові (всього): {tips_total:.2f} грн\n\n"
            "ℹ️ Замовлення надходять у групу водіїв.\n"
            "Прийміть замовлення першим, щоб його отримати!\n\n"
            "💡 <i>Поділіться локацією щоб клієнти могли бачити де ви</i>"
        )
        
        inline_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🟢 ПОЧАТИ ПРАЦЮВАТИ" if not driver.online else "🔴 ПІТИ В ОФЛАЙН",
                    callback_data="driver:toggle_online"
                )],
                [InlineKeyboardButton(text="📊 Статистика", callback_data="driver:stats")],
                [InlineKeyboardButton(text="🔄 Оновити", callback_data="driver:refresh")]
            ]
        )
        
        await call.message.edit_text(text, reply_markup=inline_kb)
        await call.answer("✅ Оновлено!")

    @router.callback_query(F.data == "driver:stats")
    async def show_stats(call: CallbackQuery) -> None:
        """Показати статистику"""
        if not call.from_user:
            return
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📅 Сьогодні", callback_data="stats:today")],
                [InlineKeyboardButton(text="📅 Тиждень", callback_data="stats:week")],
                [InlineKeyboardButton(text="📅 Місяць", callback_data="stats:month")],
                [InlineKeyboardButton(text="« Назад", callback_data="driver:refresh")]
            ]
        )
        
        await call.message.edit_text(
            "📊 <b>Статистика</b>\n\nОберіть період:",
            reply_markup=kb
        )
        await call.answer()

    @router.callback_query(F.data.startswith("stats:"))
    async def show_period_stats(call: CallbackQuery) -> None:
        """Статистика за період"""
        if not call.from_user or not call.message:
            return
        
        period = call.data.split(":")[1]
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        # Визначити період
        now = datetime.now(timezone.utc)
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            period_name = "сьогодні"
        elif period == "week":
            start = now - timedelta(days=7)
            period_name = "за тиждень"
        elif period == "month":
            start = now - timedelta(days=30)
            period_name = "за місяць"
        else:
            start = now
            period_name = "всього часу"
        
        # Отримати замовлення
        orders = await get_driver_order_history(config.database_path, call.from_user.id, limit=1000)
        period_orders = [o for o in orders if o.created_at >= start and o.status == 'completed']
        
        total_earnings = sum(o.fare_amount or 0 for o in period_orders)
        total_trips = len(period_orders)
        avg_fare = total_earnings / total_trips if total_trips > 0 else 0
        
        text = (
            f"📊 <b>Статистика {period_name}</b>\n\n"
            f"🚗 Поїздок: {total_trips}\n"
            f"💰 Заробіток: {total_earnings:.2f} грн\n"
            f"📈 Середній чек: {avg_fare:.2f} грн\n"
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data="driver:stats")]
            ]
        )
        
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()

    # Решта обробників (заробіток, комісія, локація і т.д.) залишаються зі старого файлу
    # Додаю тільки найважливіші:

    @router.message(F.location)
    async def update_location(message: Message) -> None:
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
    async def show_earnings(message: Message) -> None:
        """Показати заробіток"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            await message.answer("❌ Доступно тільки для водіїв")
            return
        
        earnings_today, commission_today = await get_driver_earnings_today(config.database_path, message.from_user.id)
        net_today = earnings_today - commission_today
        
        # За тиждень
        orders = await get_driver_order_history(config.database_path, message.from_user.id, limit=1000)
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        week_orders = [o for o in orders if o.created_at >= week_ago and o.status == 'completed']
        earnings_week = sum(o.fare_amount or 0 for o in week_orders)
        
        # За місяць
        month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        month_orders = [o for o in orders if o.created_at >= month_ago and o.status == 'completed']
        earnings_month = sum(o.fare_amount or 0 for o in month_orders)
        
        text = (
            f"💰 <b>Ваш заробіток</b>\n\n"
            f"📅 <b>Сьогодні:</b>\n"
            f"Заробіток: {earnings_today:.2f} грн\n"
            f"Комісія: -{commission_today:.2f} грн\n"
            f"Чистий: {net_today:.2f} грн\n\n"
            f"📅 <b>За тиждень:</b> {earnings_week:.2f} грн\n"
            f"📅 <b>За місяць:</b> {earnings_month:.2f} грн\n"
        )
        
        await message.answer(text)

    @router.message(F.text == "💳 Комісія")
    async def show_commission(message: Message) -> None:
        """Показати комісію"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            await message.answer("❌ Доступно тільки для водіїв")
            return
        
        unpaid = await get_driver_unpaid_commission(config.database_path, message.from_user.id)
        
        if unpaid > 0:
            # QR код
            try:
                from app.utils.qr_generator import generate_payment_qr
                from aiogram.types import BufferedInputFile
                
                qr = generate_payment_qr(config.payment_card or "4149499901234567", unpaid, f"Комісія водія")
                photo = BufferedInputFile(qr.read(), filename="commission_qr.png")
                
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Я сплатив", callback_data="mark_commission_paid")]
                    ]
                )
                
                await message.answer_photo(
                    photo=photo,
                    caption=(
                        f"💳 <b>Комісія до сплати</b>\n\n"
                        f"💸 Сума: {unpaid:.2f} грн\n\n"
                        f"📱 Відскануйте QR-код для оплати\n"
                        f"або перерахуйте на картку:\n"
                        f"<code>{config.payment_card or '4149499901234567'}</code>\n\n"
                        "Після оплати натисніть '✅ Я сплатив'"
                    ),
                    reply_markup=kb
                )
            except Exception as e:
                logger.error(f"QR error: {e}")
                await message.answer(
                    f"💳 <b>Комісія до сплати:</b> {unpaid:.2f} грн\n\n"
                    f"Перерахуйте на картку:\n<code>{config.payment_card or '4149499901234567'}</code>"
                )
        else:
            await message.answer("✅ Комісія сплачена!")

    @router.callback_query(F.data == "mark_commission_paid")
    async def mark_paid(call: CallbackQuery) -> None:
        """Відмітити комісію сплаченою"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        unpaid = await get_driver_unpaid_commission(config.database_path, call.from_user.id)
        
        if unpaid > 0:
            payment = Payment(
                id=None,
                driver_id=driver.id,
                amount=unpaid,
                payment_type="commission",
                created_at=datetime.now(timezone.utc)
            )
            await insert_payment(config.database_path, payment)
            await mark_commission_paid(config.database_path, call.from_user.id)
            
            await call.answer("✅ Комісію відмічено як сплачену!", show_alert=True)
            if call.message:
                await call.message.answer("✅ Дякуємо за оплату!")
        else:
            await call.answer("Комісія вже сплачена", show_alert=True)

    @router.message(F.text == "📜 Історія поїздок")
    async def show_history(message: Message) -> None:
        """Історія поїздок"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            await message.answer("❌ Доступно тільки для водіїв")
            return
        
        orders = await get_driver_order_history(config.database_path, message.from_user.id, limit=10)
        
        if not orders:
            await message.answer("📜 Поки немає поїздок")
            return
        
        text = "📜 <b>Останні 10 поїздок:</b>\n\n"
        
        for i, order in enumerate(orders, 1):
            status_emoji = {
                'completed': '✅',
                'cancelled_by_client': '❌',
                'cancelled_by_driver': '❌'
            }.get(order.status, '⏳')
            
            text += (
                f"{i}. {status_emoji} {order.pickup_address[:30]}... → {order.destination_address[:30]}...\n"
                f"   💰 {order.fare_amount or 0:.0f} грн | "
                f"{order.created_at.strftime('%d.%m %H:%M')}\n\n"
            )
        
        await message.answer(text)

    @router.message(F.text == "📊 Розширена аналітика")
    async def show_analytics_menu(message: Message) -> None:
        """Меню розширеної аналітики"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            await message.answer("❌ Доступно тільки для водіїв")
            return
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏰ Кращі години", callback_data="analytics:best_hours")],
                [InlineKeyboardButton(text="🗺️ Топ-маршрути", callback_data="analytics:top_routes")],
                [InlineKeyboardButton(text="💰 Прогноз заробітку", callback_data="analytics:forecast")]
            ]
        )
        
        await message.answer("📊 <b>Розширена аналітика</b>\n\nОберіть:", reply_markup=kb)

    return router

