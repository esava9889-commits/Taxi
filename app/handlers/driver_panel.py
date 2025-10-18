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
from app.utils.rate_limiter import check_rate_limit, get_time_until_reset, format_time_remaining
from app.utils.order_timeout import cancel_order_timeout

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
        
        # Статус локації з віком
        from app.utils.location_tracker import check_driver_location_status
        loc_status = await check_driver_location_status(config.database_path, message.from_user.id)
        
        if not loc_status['has_location']:
            location = "❌ Не встановлена"
        else:
            age = loc_status['age_minutes']
            if loc_status['status'] == 'fresh':
                location = f"📍 Активна ({age} хв тому)"
            elif loc_status['status'] == 'warning':
                location = f"⚠️ Потребує оновлення ({age} хв тому)"
            else:
                location = f"🔴 Застаріла ({age} хв тому)"
        
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
                [KeyboardButton(text="📜 Історія поїздок"), KeyboardButton(text="💼 Гаманець")],
                [KeyboardButton(text="📊 Розширена аналітика")],
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
        
        # RATE LIMITING: Перевірка ліміту прийняття замовлень (максимум 20 спроб на годину)
        if not check_rate_limit(call.from_user.id, "accept_order", max_requests=20, window_seconds=3600):
            time_until_reset = get_time_until_reset(call.from_user.id, "accept_order", window_seconds=3600)
            await call.answer(
                f"⏳ Занадто багато спроб прийняти замовлення.\n"
                f"Спробуйте через: {format_time_remaining(time_until_reset)}",
                show_alert=True
            )
            logger.warning(f"Driver {call.from_user.id} exceeded accept_order rate limit")
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
            # СКАСУВАТИ ТАЙМЕР: Замовлення прийнято водієм
            cancel_order_timeout(order_id)
            logger.info(f"✅ Таймер скасовано для замовлення #{order_id} (прийнято водієм)")
            
            await call.answer("✅ Прийнято!", show_alert=True)
            
            # Повідомити клієнта що замовлення прийнято
            # Якщо оплата карткою - показати картку водія
            if order.payment_method == "card" and driver.card_number:
                kb_client = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Сплатити поїздку", callback_data=f"pay:{order_id}")]
                    ]
                )
                await call.bot.send_message(
                    order.user_id,
                    f"✅ <b>Водій прийняв замовлення!</b>\n\n"
                    f"🚗 {driver.full_name}\n"
                    f"🚙 {driver.car_make} {driver.car_model} ({driver.car_plate})\n"
                    f"📱 <code>{driver.phone}</code>\n\n"
                    f"💳 <b>Картка для оплати:</b>\n"
                    f"<code>{driver.card_number}</code>\n\n"
                    f"💰 До сплати: {int(order.fare_amount):.0f} грн" if order.fare_amount is not None else "💰 Вартість: уточнюється",
                    reply_markup=kb_client
                )
            else:
                await call.bot.send_message(
                    order.user_id,
                    (
                        f"✅ <b>Водій прийняв замовлення!</b>\n\n"
                        f"🚗 {driver.full_name}\n"
                        f"🚙 {driver.car_make} {driver.car_model} ({driver.car_plate})\n"
                        f"📱 <code>{driver.phone}</code>\n\n"
                        f"💵 Оплата готівкою\n\n"
                        f"🚗 Водій уже в дорозі. Очікуйте!"
                    )
                )
            
            # ВИДАЛИТИ повідомлення з групи (для приватності)
            if call.message and order.group_message_id:
                try:
                    # Відредагувати повідомлення в групі
                    await call.bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=order.group_message_id,
                        text="✅ <b>Замовлення вже виконується</b>\n\n"
                             f"Водій: {driver.full_name}\n"
                             f"Статус: В роботі"
                    )
                except Exception as e:
                    logger.error(f"Не вдалося відредагувати повідомлення в групі: {e}")
            
            # Надіслати водію ОСОБИСТЕ повідомлення з ПОВНИМ номером телефону
            kb_driver = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🚗 Керувати замовленням", callback_data=f"manage:{order_id}")]
                ]
            )
            
            await call.bot.send_message(
                driver.tg_user_id,
                f"✅ <b>Ви прийняли замовлення #{order_id}</b>\n\n"
                f"👤 Клієнт: {order.name}\n"
                f"📱 Телефон: <code>{order.phone}</code> 🔓\n\n"
                f"📍 Звідки: {order.pickup_address}\n"
                f"📍 Куди: {order.destination_address}\n\n"
                f"ℹ️ <i>Повний номер телефону доступний тільки вам</i>\n\n"
                f"Натисніть кнопку нижче для керування замовленням",
                reply_markup=kb_driver
            )
            
            # Видалити повідомлення в групі (якщо це група)
            if call.message:
                try:
                    await call.message.delete()
                except:
                    pass
    
    @router.callback_query(F.data.startswith("reject_order:"))
    async def reject_order_handler(call: CallbackQuery) -> None:
        """Водій відхиляє замовлення"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            return
        
        order_id = int(call.data.split(":")[1])
        
        # Додати водія до списку відхилених для цього замовлення
        from app.storage.db import add_rejected_driver
        await add_rejected_driver(config.database_path, order_id, driver.id)
        
        await call.answer("❌ Ви відхилили замовлення", show_alert=False)
        
        # Видалити повідомлення для цього водія
        if call.message:
            try:
                await call.message.delete()
            except:
                pass
        
        logger.info(f"❌ Водій {driver.full_name} відхилив замовлення #{order_id}")

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
        
        # Розрахунок вартості: використовуємо збережену, інакше мінімум 100
        fare = order.fare_amount if order.fare_amount else 100.0
        distance_m = order.distance_m if order.distance_m else 0
        duration_s = order.duration_s if order.duration_s else 0
        # Отримати поточний тариф для комісії
        from app.storage.db import get_latest_tariff, insert_payment, Payment
        tariff = await get_latest_tariff(config.database_path)
        commission_rate = tariff.commission_percent if tariff else 0.02
        commission = fare * commission_rate
        
        await complete_order(
            config.database_path,
            order_id,
            driver.id,
            fare,
            distance_m,
            duration_s,
            commission
        )
        # Запис у payments для обліку комісії
        payment = Payment(
            id=None,
            order_id=order_id,
            driver_id=driver.id,
            amount=fare,
            commission=commission,
            commission_paid=False,
            payment_method=order.payment_method or 'cash',
            created_at=datetime.now(timezone.utc),
        )
        await insert_payment(config.database_path, payment)
        
        await call.answer(f"✅ Завершено! {fare:.0f} грн", show_alert=True)
        
        if call.message:
            await call.message.edit_text(f"✅ Поїздка завершена!\n💰 {fare:.0f} грн")

    @router.message(F.text == "💼 Гаманець")
    async def show_wallet(message: Message) -> None:
        """Гаманець водія - картка для отримання оплати"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            await message.answer("❌ Доступно тільки для водіїв")
            return
        
        if driver.card_number:
            text = (
                f"💼 <b>Ваш гаманець</b>\n\n"
                f"💳 Картка для оплати:\n"
                f"<code>{driver.card_number}</code>\n\n"
                f"ℹ️ Ця картка показується клієнтам,\n"
                f"які обирають оплату карткою."
            )
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Змінити картку", callback_data="wallet:edit")]
                ]
            )
        else:
            text = (
                f"💼 <b>Ваш гаманець</b>\n\n"
                f"❌ Картка не додана\n\n"
                f"Додайте картку, щоб клієнти могли\n"
                f"переказувати вам оплату."
            )
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Додати картку", callback_data="wallet:add")]
                ]
            )
        
        await message.answer(text, reply_markup=kb)
    
    @router.callback_query(F.data.in_(["wallet:add", "wallet:edit"]))
    async def wallet_add_edit(call: CallbackQuery) -> None:
        """Додати/змінити картку"""
        await call.answer()
        await call.message.answer(
            "💳 <b>Введіть номер картки</b>\n\n"
            "Формат: 1234 5678 9012 3456\n"
            "або: 1234567890123456\n\n"
            "Ця картка буде показуватись клієнтам\n"
            "для оплати поїздки."
        )
        # Тут можна додати FSM, але для простоти зробимо через текстовий обробник
    
    @router.message(F.text.regexp(r'^\d{4}\s?\d{4}\s?\d{4}\s?\d{4}$'))
    async def save_card_number(message: Message) -> None:
        """Зберегти номер картки"""
        if not message.from_user or not message.text:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            return
        
        card_number = message.text.strip().replace(" ", "")
        # Форматувати як 1234 5678 9012 3456
        formatted_card = f"{card_number[0:4]} {card_number[4:8]} {card_number[8:12]} {card_number[12:16]}"
        
        # Оновити в БД
        import aiosqlite
        import logging
        logger = logging.getLogger(__name__)
        
        async with aiosqlite.connect(config.database_path) as db:
            cursor = await db.execute(
                "UPDATE drivers SET card_number = ? WHERE tg_user_id = ?",
                (formatted_card, message.from_user.id)
            )
            await db.commit()
            
            # Перевірити що UPDATE спрацював
            if cursor.rowcount > 0:
                logger.info(f"✅ Картку збережено для водія {message.from_user.id}: {formatted_card}")
            else:
                logger.error(f"❌ UPDATE не спрацював для водія {message.from_user.id}")
        
        # Перевірити що картка дійсно збереглася
        driver_check = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if driver_check and driver_check.card_number:
            logger.info(f"✅ Перевірка: картка в БД = {driver_check.card_number}")
        else:
            logger.error(f"❌ Перевірка: картка НЕ збереглася в БД!")
        
        await message.answer(
            f"✅ <b>Картку збережено!</b>\n\n"
            f"💳 {formatted_card}\n\n"
            f"Тепер клієнти зможуть переказувати\n"
            f"оплату на цю картку.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="🚗 Панель водія"), KeyboardButton(text="🚀 Почати роботу")],
                    [KeyboardButton(text="📊 Мій заробіток"), KeyboardButton(text="💳 Комісія")],
                    [KeyboardButton(text="📜 Історія поїздок"), KeyboardButton(text="💼 Гаманець")],
                    [KeyboardButton(text="📊 Розширена аналітика")],
                    [KeyboardButton(text="👤 Кабінет клієнта"), KeyboardButton(text="ℹ️ Допомога")]
                ],
                resize_keyboard=True
            )
        )
    
    @router.callback_query(F.data.startswith("manage:"))
    async def manage_order(call: CallbackQuery) -> None:
        """Керування замовленням - показати всі деталі та кнопки"""
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
        
        # Сформувати текст з усіма деталями
        from app.storage.db import get_user_by_id
        client = await get_user_by_id(config.database_path, order.user_id)
        
        distance_text = ""
        if order.distance_m:
            km = order.distance_m / 1000.0
            distance_text = f"\n📏 Відстань: {km:.1f} км"
        
        payment_text = "💵 Готівка" if order.payment_method == "cash" else "💳 Картка"
        
        fare_text = f"{order.fare_amount:.0f} грн" if isinstance(order.fare_amount, (int, float)) else "уточнюється"
        text = (
            f"🚗 <b>Замовлення #{order_id}</b>\n\n"
            f"👤 Клієнт: {client.full_name if client else 'Невідомо'}\n"
            f"📱 Телефон: <code>{order.phone}</code>\n\n"
            f"📍 <b>Звідки:</b> {order.pickup_address}\n"
            f"📍 <b>Куди:</b> {order.destination_address}{distance_text}\n\n"
            f"💰 Вартість: {fare_text}\n"
            f"💳 Оплата: {payment_text}\n"
        )
        
        if order.comment:
            text += f"\n💬 Коментар: {order.comment}"
        
        text += f"\n\n📊 Статус: "
        
        # Кнопки залежно від статусу
        kb = None
        
        if order.status == "accepted":
            text += "✅ Прийнято"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📍 Я на місці", callback_data=f"arrived:{order_id}")],
                    [InlineKeyboardButton(text="🚗 Почати поїздку", callback_data=f"start:{order_id}")],
                    [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"manage:{order_id}")]
                ]
            )
        elif order.status == "in_progress":
            text += "🚗 В дорозі"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Завершити поїздку", callback_data=f"complete:{order_id}")],
                    [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"manage:{order_id}")]
                ]
            )
        elif order.status == "completed":
            text += "✔️ Завершено"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад", callback_data="driver:panel")]
                ]
            )
        
        await call.answer()
        
        if kb:
            try:
                await call.message.edit_text(text, reply_markup=kb)
            except:
                await call.message.answer(text, reply_markup=kb)
        else:
            await call.message.answer(text)

    return router
