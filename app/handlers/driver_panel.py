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
    get_active_order_for_driver,
    cancel_order_by_driver,
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


def clean_address(address: str) -> str:
    """
    Очистити адресу від Plus Codes та зайвих символів.
    
    Plus Code - це коди типу "PMQC+G9" які Google додає до адрес.
    Вони не потрібні для читабельності.
    """
    import re
    
    if not address:
        return "Не вказано"
    
    # Видалити Plus Codes (формат: 4-8 символів + '+' + 2-3 символи)
    # Приклади: PMQC+G9, 8FWX+23, ABCD+EF
    address = re.sub(r'\b[A-Z0-9]{4,8}\+[A-Z0-9]{2,3}\b', '', address)
    
    # Видалити зайві пробіли
    address = re.sub(r'\s+', ' ', address)
    
    # Видалити пробіли на початку і в кінці
    address = address.strip()
    
    # Видалити коми на початку (якщо залишились після видалення Plus Code)
    address = re.sub(r'^[,\s]+', '', address)
    
    return address if address else "Не вказано"


def driver_panel_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура панелі водія"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Почати роботу")],
            [KeyboardButton(text="📊 Мій заробіток"), KeyboardButton(text="💳 Комісія")],
            [KeyboardButton(text="📜 Історія поїздок"), KeyboardButton(text="💼 Гаманець")],
            [KeyboardButton(text="📊 Розширена аналітика")],
            [KeyboardButton(text="👤 Кабінет клієнта"), KeyboardButton(text="ℹ️ Допомога")],
            [KeyboardButton(text="📖 Правила користування")]  # ⭐ НОВА КНОПКА
        ],
        resize_keyboard=True
    )


def create_router(config: AppConfig) -> Router:
    router = Router(name="driver_panel")

    @router.message(F.text == "🚗 Панель водія")
    async def driver_panel_main(message: Message) -> None:
        """Головна панель водія - НОВА ВЕРСІЯ 3.0"""
        if not message.from_user:
            return
        
        # Видалити повідомлення користувача для чистого чату
        try:
            await message.delete()
        except:
            pass
        
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
        
        # КЛАВІАТУРА БЕЗ кнопки поділитися локацією (вона тепер в активному замовленні)
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚀 Почати роботу")],
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
        
        # Видалити повідомлення користувача для чистого чату
        try:
            await message.delete()
        except:
            pass
        
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
        
        # Push-повідомлення при зміні статусу
        if new:
            await call.answer(f"✅ Ви онлайн! Водіїв: {online}", show_alert=True)
            # Відправити push-повідомлення про статус онлайн
            try:
                city_name = driver.city if driver.city else "вашому місті"
                await call.bot.send_message(
                    call.from_user.id,
                    f"🟢 <b>Статус: ОНЛАЙН</b>\n\n"
                    f"Ви тепер онлайн і готові приймати замовлення!\n\n"
                    f"👥 Онлайн водіїв у {city_name}: {online}\n\n"
                    f"📢 Замовлення надходять у групу водіїв.\n"
                    f"Прийміть замовлення першим!",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Failed to send online status push: {e}")
        else:
            await call.answer("🔴 Ви офлайн", show_alert=True)
            # Відправити push-повідомлення про статус офлайн
            try:
                await call.bot.send_message(
                    call.from_user.id,
                    f"🔴 <b>Статус: ОФЛАЙН</b>\n\n"
                    f"Ви пішли в офлайн.\n\n"
                    f"Ви не будете отримувати нові замовлення.\n\n"
                    f"💡 Щоб почати працювати знову, увімкніть статус онлайн.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Failed to send offline status push: {e}")
        
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
    async def share_location_with_client(message: Message) -> None:
        """Поділитися локацією з клієнтом (для активного замовлення)"""
        if not message.from_user or not message.location:
            return
        
        # Перевірити чи це водій
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver or driver.status != "approved":
            return
        
        # Знайти активне замовлення водія
        from app.storage.db import get_driver_order_history
        orders = await get_driver_order_history(config.database_path, driver.tg_user_id, limit=5)
        
        active_order = None
        for order in orders:
            if order.status in ["accepted", "in_progress"] and order.driver_id == driver.id:
                active_order = order
                break
        
        if not active_order:
            await message.answer(
                "❌ <b>Немає активного замовлення</b>\n\n"
                "Щоб поділитися локацією з клієнтом,\n"
                "спочатку прийміть замовлення."
            )
            return
        
        lat = message.location.latitude
        lon = message.location.longitude
        
        # Оновити локацію водія в БД
        await update_driver_location(
            config.database_path,
            message.from_user.id,
            lat,
            lon
        )
        
        try:
            # Надіслати live location клієнту (оновлюється автоматично 15 хвилин)
            await message.bot.send_location(
                active_order.user_id,
                latitude=lat,
                longitude=lon,
                live_period=900,  # 15 хвилин
            )
            
            # Надіслати повідомлення з інформацією
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🗺️ Відкрити в Google Maps",
                        url=f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
                    )]
                ]
            )
            
            await message.bot.send_message(
                active_order.user_id,
                f"📍 <b>Водій поділився локацією!</b>\n\n"
                f"🚗 {driver.full_name}\n"
                f"🚙 {driver.car_make} {driver.car_model}\n"
                f"📱 <code>{driver.phone}</code>\n\n"
                f"Ви можете відстежувати його переміщення\n"
                f"протягом наступних 15 хвилин.",
                reply_markup=kb
            )
            
            await message.answer(
                f"✅ <b>Локацію надіслано клієнту!</b>\n\n"
                f"👤 Клієнт: {active_order.name}\n"
                f"📱 {active_order.phone}\n\n"
                f"Клієнт тепер бачить вашу локацію в реальному часі.\n"
                f"⏱️ Live tracking активний: 15 хвилин"
            )
            
            logger.info(f"Driver {driver.tg_user_id} shared location with client for order #{active_order.id}")
            
        except Exception as e:
            logger.error(f"Failed to share location with client: {e}")
            await message.answer(
                "❌ Не вдалося надіслати локацію клієнту.\n"
                "Спробуйте ще раз."
            )

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
        
        # Видалити повідомлення користувача для чистого чату
        try:
            await message.delete()
        except:
            pass
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        unpaid = await get_driver_unpaid_commission(config.database_path, message.from_user.id)
        
        if unpaid > 0:
            # Показати інлайн кнопку для підтвердження оплати
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Комісію сплачено", callback_data=f"commission:paid:{driver.id}")]
                ]
            )
            
            await message.answer(
                f"💳 <b>Комісія до сплати:</b> {unpaid:.2f} грн\n\n"
                f"📋 <b>Реквізити для оплати:</b>\n"
                f"💳 Картка: <code>{config.payment_card or '4149499901234567'}</code>\n\n"
                f"⚠️ <b>УВАГА:</b>\n"
                f"1. Переведіть комісію на вказану картку\n"
                f"2. Тільки після переказу натисніть кнопку нижче\n"
                f"3. Адміністратор перевірить платіж\n"
                f"4. Після підтвердження комісія буде анульована\n\n"
                f"💡 Не натискайте кнопку до здійснення оплати!",
                reply_markup=kb
            )
        else:
            await message.answer("✅ Комісія сплачена!")

    @router.callback_query(F.data.startswith("commission:paid:"))
    async def commission_paid_request(call: CallbackQuery) -> None:
        """Водій повідомляє що сплатив комісію"""
        if not call.from_user:
            return
        
        await call.answer()
        
        driver_id = int(call.data.split(":", 2)[2])
        
        driver = await get_driver_by_id(config.database_path, driver_id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        # Перевірити що це той самий водій
        if driver.tg_user_id != call.from_user.id:
            await call.answer("❌ Помилка доступу", show_alert=True)
            return
        
        unpaid = await get_driver_unpaid_commission(config.database_path, call.from_user.id)
        
        if unpaid <= 0:
            await call.answer("✅ У вас немає боргу", show_alert=True)
            return
        
        # Оновити повідомлення водію
        try:
            await call.message.edit_text(
                f"⏳ <b>Запит на підтвердження надіслано</b>\n\n"
                f"💳 Сума: {unpaid:.2f} грн\n\n"
                f"Очікуйте підтвердження від адміністратора.\n"
                f"Це може зайняти деякий час."
            )
        except:
            pass
        
        # Відправити повідомлення всім адмінам
        admin_ids = config.bot.admin_ids
        
        for admin_id in admin_ids:
            try:
                # Кнопки для адміна
                admin_kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"commission:confirm:{driver.id}:{call.from_user.id}"),
                            InlineKeyboardButton(text="❌ Відхилити", callback_data=f"commission:reject:{driver.id}:{call.from_user.id}")
                        ]
                    ]
                )
                
                await call.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"💳 <b>ЗАПИТ НА ПІДТВЕРДЖЕННЯ ОПЛАТИ КОМІСІЇ</b>\n\n"
                        f"👤 Водій: {driver.full_name}\n"
                        f"📱 Телефон: {driver.phone}\n"
                        f"🏙 Місто: {driver.city or 'Не вказано'}\n"
                        f"🚗 Авто: {driver.car_model} ({driver.car_plate})\n"
                        f"💳 Сума комісії: <b>{unpaid:.2f} грн</b>\n\n"
                        f"📋 Реквізити (куди мав переказати):\n"
                        f"💳 {config.payment_card or '4149499901234567'}\n\n"
                        f"⚠️ <b>Перевірте надходження коштів</b>\n"
                        f"та підтвердіть або відхиліть платіж:"
                    ),
                    reply_markup=admin_kb
                )
                
                logger.info(f"✅ Надіслано запит на підтвердження комісії {unpaid:.2f} грн від водія {driver.id} адміну {admin_id}")
            except Exception as e:
                logger.error(f"❌ Помилка відправки повідомлення адміну {admin_id}: {e}")
        
        await call.answer("✅ Запит надіслано адміністратору", show_alert=True)
    
    @router.callback_query(F.data.startswith("commission:confirm:"))
    async def commission_confirm(call: CallbackQuery) -> None:
        """Адмін підтверджує оплату комісії"""
        if not call.from_user:
            return
        
        # Перевірити що це адмін
        if call.from_user.id not in config.bot.admin_ids:
            await call.answer("❌ Тільки для адміністраторів", show_alert=True)
            return
        
        await call.answer()
        
        parts = call.data.split(":", 3)
        driver_id = int(parts[2])
        driver_tg_id = int(parts[3])
        
        driver = await get_driver_by_id(config.database_path, driver_id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        unpaid = await get_driver_unpaid_commission(config.database_path, driver_tg_id)
        
        if unpaid <= 0:
            await call.answer("ℹ️ Комісія вже сплачена", show_alert=True)
            try:
                await call.message.edit_text(
                    f"ℹ️ <b>Комісія вже була сплачена раніше</b>\n\n"
                    f"👤 Водій: {driver.full_name}"
                )
            except:
                pass
            return
        
        # АНУЛЮВАТИ КОМІСІЮ В БД
        await mark_commission_paid(config.database_path, driver_tg_id)
        
        logger.info(f"✅ Адмін {call.from_user.id} підтвердив оплату комісії {unpaid:.2f} грн від водія {driver.id}")
        
        # Оновити повідомлення адміна
        try:
            await call.message.edit_text(
                f"✅ <b>ОПЛАТУ ПІДТВЕРДЖЕНО</b>\n\n"
                f"👤 Водій: {driver.full_name}\n"
                f"💳 Сума: {unpaid:.2f} грн\n"
                f"👨‍💼 Підтвердив: @{call.from_user.username or call.from_user.first_name}\n"
                f"⏰ Час: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
                f"✅ Комісія анульована в системі"
            )
        except:
            pass
        
        # Сповістити водія про підтвердження
        try:
            await call.bot.send_message(
                chat_id=driver_tg_id,
                text=(
                    f"✅ <b>ОПЛАТУ КОМІСІЇ ПІДТВЕРДЖЕНО!</b>\n\n"
                    f"💳 Сума: {unpaid:.2f} грн\n\n"
                    f"Дякуємо! Ваша комісія анульована.\n"
                    f"Можете продовжувати роботу! 🚗"
                )
            )
        except Exception as e:
            logger.error(f"❌ Помилка сповіщення водія {driver_tg_id}: {e}")
        
        await call.answer("✅ Оплату підтверджено та комісію анульовано", show_alert=True)
    
    @router.callback_query(F.data.startswith("commission:reject:"))
    async def commission_reject(call: CallbackQuery) -> None:
        """Адмін відхиляє оплату комісії"""
        if not call.from_user:
            return
        
        # Перевірити що це адмін
        if call.from_user.id not in config.bot.admin_ids:
            await call.answer("❌ Тільки для адміністраторів", show_alert=True)
            return
        
        await call.answer()
        
        parts = call.data.split(":", 3)
        driver_id = int(parts[2])
        driver_tg_id = int(parts[3])
        
        driver = await get_driver_by_id(config.database_path, driver_id)
        if not driver:
            await call.answer("❌ Водія не знайдено", show_alert=True)
            return
        
        unpaid = await get_driver_unpaid_commission(config.database_path, driver_tg_id)
        
        logger.info(f"❌ Адмін {call.from_user.id} відхилив оплату комісії від водія {driver.id}")
        
        # Оновити повідомлення адміна
        try:
            await call.message.edit_text(
                f"❌ <b>ОПЛАТУ ВІДХИЛЕНО</b>\n\n"
                f"👤 Водій: {driver.full_name}\n"
                f"💳 Сума: {unpaid:.2f} грн\n"
                f"👨‍💼 Відхилив: @{call.from_user.username or call.from_user.first_name}\n"
                f"⏰ Час: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
                f"⚠️ Водія буде сповіщено"
            )
        except:
            pass
        
        # Сповістити водія про відхилення
        try:
            await call.bot.send_message(
                chat_id=driver_tg_id,
                text=(
                    f"❌ <b>ОПЛАТУ КОМІСІЇ ВІДХИЛЕНО</b>\n\n"
                    f"💳 Сума: {unpaid:.2f} грн\n\n"
                    f"⚠️ Причини можливого відхилення:\n"
                    f"• Оплата не надійшла на картку\n"
                    f"• Неправильна сума\n"
                    f"• Інша помилка\n\n"
                    f"📞 Зв'яжіться з адміністратором для уточнення.\n\n"
                    f"Після здійснення правильної оплати\n"
                    f"надішліть запит знову через меню '💳 Комісія'"
                )
            )
        except Exception as e:
            logger.error(f"❌ Помилка сповіщення водія {driver_tg_id}: {e}")
        
        await call.answer("❌ Оплату відхилено, водія сповіщено", show_alert=True)

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
            
            # ⭐ ЗАПРОСИТИ У ВОДІЯ ГЕОЛОКАЦІЮ (обов'язково для відправки клієнту)
            # Надіслати повідомлення водію з проханням поділитися локацією
            location_shared = False
            if driver.last_lat and driver.last_lon:
                try:
                    # Надіслати live location клієнту
                    await call.bot.send_location(
                        order.user_id,
                        latitude=driver.last_lat,
                        longitude=driver.last_lon,
                        live_period=900,  # 15 хвилин
                    )
                    location_shared = True
                    logger.info(f"📍 Auto-sent live location to client for order #{order_id}")
                except Exception as e:
                    logger.error(f"Failed to send live location: {e}")
            
            # Якщо геолокація не надіслана - попросити водія поділитися
            if not location_shared:
                logger.warning(f"⚠️ Водій #{driver.id} не має збереженої геолокації для замовлення #{order_id}")
                # Клієнт все одно отримає повідомлення, але без live location
            
            # Якщо оплата карткою - показати картку водія
            if order.payment_method == "card" and driver.card_number:
                kb_client = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(
                            text="🗺️ Відкрити в Google Maps",
                            url=f"https://www.google.com/maps/dir/?api=1&destination={driver.last_lat},{driver.last_lon}"
                        )] if driver.last_lat and driver.last_lon else [],
                        [InlineKeyboardButton(text="💳 Сплатити поїздку", callback_data=f"pay:{order_id}")]
                    ]
                )
                location_text = "\n📍 <b>Локація водія надіслана вище</b>\n" if driver.last_lat and driver.last_lon else ""
                await call.bot.send_message(
                    order.user_id,
                    f"✅ <b>Водій прийняв замовлення!</b>\n\n"
                    f"🚗 {driver.full_name}\n"
                    f"🚙 {driver.car_make} {driver.car_model} ({driver.car_plate})\n"
                    f"📱 <code>{driver.phone}</code>\n\n"
                    f"{location_text}\n"
                    f"💳 <b>Картка для оплати:</b>\n"
                    f"<code>{driver.card_number}</code>\n\n"
                    f"💰 До сплати: {int(order.fare_amount):.0f} грн" if order.fare_amount is not None else "💰 Вартість: уточнюється",
                    reply_markup=kb_client
                )
            else:
                kb_client = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(
                            text="🗺️ Відкрити в Google Maps",
                            url=f"https://www.google.com/maps/dir/?api=1&destination={driver.last_lat},{driver.last_lon}"
                        )]
                    ]
                ) if driver.last_lat and driver.last_lon else None
                
                location_text = "\n📍 <b>Локація водія надіслана вище</b>\n" if driver.last_lat and driver.last_lon else ""
                
                await call.bot.send_message(
                    order.user_id,
                    (
                        f"✅ <b>Водій прийняв замовлення!</b>\n\n"
                        f"🚗 {driver.full_name}\n"
                        f"🚙 {driver.car_make} {driver.car_model} ({driver.car_plate})\n"
                        f"📱 <code>{driver.phone}</code>\n\n"
                        f"{location_text}\n"
                        f"💵 Оплата готівкою\n\n"
                        f"🚗 Водій уже в дорозі. Очікуйте!"
                    ),
                    reply_markup=kb_client
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
            
            # ⭐ НОВА ЛОГІКА: Видалити попередні повідомлення і показати ОДНЕ меню з Reply Keyboard
            
            # 1. Спробувати видалити останні повідомлення в чаті водія
            try:
                # Видалити останні 20 повідомлень (очистити чат)
                for i in range(1, 21):
                    try:
                        await call.bot.delete_message(
                            chat_id=driver.tg_user_id,
                            message_id=call.message.message_id - i if call.message else 0
                        )
                    except:
                        pass  # Ігноруємо помилки видалення
            except Exception as e:
                logger.warning(f"Не вдалося видалити попередні повідомлення: {e}")
            
            # 2. Відобразити відстань якщо є
            distance_text = ""
            if order.distance_m:
                km = order.distance_m / 1000.0
                distance_text = f"\n📏 Відстань: {km:.1f} км"
            
            payment_emoji = "💵" if order.payment_method == "cash" else "💳"
            payment_text = "Готівка" if order.payment_method == "cash" else "Картка"
            
            # ⭐ Очистити адреси від Plus Codes
            clean_pickup = clean_address(order.pickup_address)
            clean_destination = clean_address(order.destination_address)
            
            # ⭐ Створити посилання на Google Maps якщо є координати
            pickup_link = ""
            destination_link = ""
            
            if order.pickup_lat and order.pickup_lon:
                pickup_link = f"<a href='https://www.google.com/maps?q={order.pickup_lat},{order.pickup_lon}'>📍 Відкрити на карті</a>"
            
            if order.dest_lat and order.dest_lon:
                destination_link = f"<a href='https://www.google.com/maps?q={order.dest_lat},{order.dest_lon}'>📍 Відкрити на карті</a>"
            
            # 3. Відправити ОДНЕ повідомлення з інформацією про замовлення
            trip_info_text = (
                f"🚗 <b>ЗАМОВЛЕННЯ #{order_id}</b>\n"
                f"━━━━━━━━━━━━━━━━━\n\n"
                f"👤 <b>Клієнт:</b> {order.name}\n"
                f"📱 <b>Телефон:</b> <code>{order.phone}</code>\n\n"
                f"📍 <b>Звідки:</b>\n   {clean_pickup}\n"
                f"   {pickup_link}\n\n"
                f"📍 <b>Куди:</b>\n   {clean_destination}\n"
                f"   {destination_link}{distance_text}\n\n"
                f"💰 <b>Вартість:</b> {int(order.fare_amount):.0f} грн\n"
                f"{payment_emoji} <b>Оплата:</b> {payment_text}\n"
            )
            
            if order.comment:
                trip_info_text += f"\n💬 <b>Коментар:</b>\n   {order.comment}\n"
            
            trip_info_text += (
                f"\n━━━━━━━━━━━━━━━━━\n"
                f"📊 <b>Статус:</b> ✅ Прийнято\n\n"
                f"👇 <i>Натисніть кнопку внизу для керування поїздкою</i>"
            )
            
            # 4. ⭐ REPLY KEYBOARD з великою кнопкою зверху і меншими знизу
            from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
            
            kb_trip = ReplyKeyboardMarkup(
                keyboard=[
                    # ВЕЛИКА КНОПКА (перший ряд - займає всю ширину)
                    [KeyboardButton(text="🚗 В дорозі")],
                    # МЕНШІ КНОПКИ (по 2 в ряд)
                    [
                        KeyboardButton(text="❌ Відмовитися"),
                        KeyboardButton(text="📞 Зв'язатися з клієнтом")
                    ],
                    [
                        KeyboardButton(text="ℹ️ Допомога"),
                        KeyboardButton(text="💬 Підтримка")
                    ]
                ],
                resize_keyboard=True,  # Автоматично підігнати розмір кнопок
                one_time_keyboard=False  # Не ховати клавіатуру після натискання
            )
            
            await call.bot.send_message(
                driver.tg_user_id,
                trip_info_text,
                reply_markup=kb_trip
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
        """Водій приїхав на місце подачі"""
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
        
        await call.answer("📍 Клієнт отримав повідомлення!", show_alert=True)
        
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
        
        # ⭐ Оновити текст і показати велику червону кнопку "ЗАВЕРШИТИ"
        distance_text = ""
        if order.distance_m:
            km = order.distance_m / 1000.0
            distance_text = f"\n📏 Відстань: {km:.1f} км"
        
        payment_emoji = "💵" if order.payment_method == "cash" else "💳"
        payment_text = "Готівка" if order.payment_method == "cash" else "Картка"
        
        updated_text = (
            f"🚗 <b>ЗАМОВЛЕННЯ #{order_id}</b>\n"
            f"━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Клієнт:</b> {order.name}\n"
            f"📱 <b>Телефон:</b> <code>{order.phone}</code>\n\n"
            f"📍 <b>Звідки:</b>\n   {order.pickup_address}\n\n"
            f"📍 <b>Куди:</b>\n   {order.destination_address}{distance_text}\n\n"
            f"💰 <b>Вартість:</b> {int(order.fare_amount):.0f} грн\n"
            f"{payment_emoji} <b>Оплата:</b> {payment_text}\n"
        )
        
        if order.comment:
            updated_text += f"\n💬 <b>Коментар:</b>\n   {order.comment}\n"
        
        updated_text += (
            f"\n━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Статус:</b> 📍 На місці подачі\n\n"
            f"👇 <i>Коли клієнт сяде - натисніть кнопку завершення</i>"
        )
        
        # Велика червона кнопка "ЗАВЕРШИТИ ПОЇЗДКУ"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏁 ЗАВЕРШИТИ ПОЇЗДКУ - Фініш", callback_data=f"complete:{order_id}")],
                [InlineKeyboardButton(text="📋 Деталі", callback_data=f"manage:{order_id}")]
            ]
        )
        
        if call.message:
            try:
                await call.message.edit_text(updated_text, reply_markup=kb)
            except:
                await call.message.answer(updated_text, reply_markup=kb)
    
    @router.callback_query(F.data.startswith("start:"))
    async def start_trip(call: CallbackQuery) -> None:
        """Почати поїздку - водій рухається до клієнта"""
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
        
        await start_order(config.database_path, order_id, driver.id)
        
        await call.answer("🚗 В дорозі до клієнта!", show_alert=True)
        
        # ⭐ Оновити текст повідомлення і показати велику кнопку "Я НА МІСЦІ"
        distance_text = ""
        if order.distance_m:
            km = order.distance_m / 1000.0
            distance_text = f"\n📏 Відстань: {km:.1f} км"
        
        payment_emoji = "💵" if order.payment_method == "cash" else "💳"
        payment_text = "Готівка" if order.payment_method == "cash" else "Картка"
        
        updated_text = (
            f"🚗 <b>ЗАМОВЛЕННЯ #{order_id}</b>\n"
            f"━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Клієнт:</b> {order.name}\n"
            f"📱 <b>Телефон:</b> <code>{order.phone}</code>\n\n"
            f"📍 <b>Звідки:</b>\n   {order.pickup_address}\n\n"
            f"📍 <b>Куди:</b>\n   {order.destination_address}{distance_text}\n\n"
            f"💰 <b>Вартість:</b> {int(order.fare_amount):.0f} грн\n"
            f"{payment_emoji} <b>Оплата:</b> {payment_text}\n"
        )
        
        if order.comment:
            updated_text += f"\n💬 <b>Коментар:</b>\n   {order.comment}\n"
        
        updated_text += (
            f"\n━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Статус:</b> 🚗 В дорозі\n\n"
            f"👇 <i>Натисніть коли приїдете до клієнта</i>"
        )
        
        # Велика помаранчева кнопка "Я НА МІСЦІ"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📍 Я НА МІСЦІ - Приїхав", callback_data=f"arrived:{order_id}")],
                [InlineKeyboardButton(text="📋 Деталі", callback_data=f"manage:{order_id}")]
            ]
        )
        
        if call.message:
            try:
                await call.message.edit_text(updated_text, reply_markup=kb)
            except:
                await call.message.answer(updated_text, reply_markup=kb)

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
        
        # 🌟 НОВА ФУНКЦІЯ: Відправити клієнту запит на оцінку водія
        try:
            # Створити інлайн кнопки з зірками
            rating_buttons = [
                [
                    InlineKeyboardButton(text="⭐", callback_data=f"rate:driver:{driver.tg_user_id}:1:{order_id}"),
                    InlineKeyboardButton(text="⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:2:{order_id}"),
                    InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:3:{order_id}"),
                ],
                [
                    InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:4:{order_id}"),
                    InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:5:{order_id}"),
                ],
                [
                    InlineKeyboardButton(text="⏩ Пропустити", callback_data=f"rate:skip:{order_id}")
                ]
            ]
            
            rating_kb = InlineKeyboardMarkup(inline_keyboard=rating_buttons)
            
            # Відправити повідомлення клієнту
            await call.bot.send_message(
                chat_id=order.user_id,
                text=(
                    "✅ <b>Поїздка завершена!</b>\n\n"
                    f"💰 Вартість: {fare:.0f} грн\n"
                    f"🚗 Спосіб оплати: {'💳 Картка' if order.payment_method == 'card' else '💵 Готівка'}\n\n"
                    "⭐ <b>Будь ласка, оцініть водія:</b>\n"
                    "Це допоможе покращити якість сервісу!"
                ),
                reply_markup=rating_kb
            )
            logger.info(f"✅ Надіслано запит на оцінку водія {driver.id} клієнту {order.user_id} для замовлення #{order_id}")
        except Exception as e:
            logger.error(f"❌ Помилка відправки запиту на оцінку: {e}")

    @router.message(F.text == "💼 Гаманець")
    async def show_wallet(message: Message) -> None:
        """Гаманець водія - картка для отримання оплати"""
        if not message.from_user:
            return
        
        # Видалити повідомлення користувача для чистого чату
        try:
            await message.delete()
        except:
            pass
        
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
        
        from app.storage.db_connection import db_manager
        async with db_manager.connect(config.database_path) as db:
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
            text += "✅ Прийнято\n\n"
            text += "💡 <i>Клієнт вже бачить вашу локацію (якщо ви її надсилали)</i>"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📍 Я на місці", callback_data=f"arrived:{order_id}")],
                    [InlineKeyboardButton(text="🚗 Почати поїздку", callback_data=f"start:{order_id}")],
                    [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"manage:{order_id}")]
                ]
            )
            
        elif order.status == "in_progress":
            text += "🚗 В дорозі\n\n"
            text += "💡 <i>Оновіть локацію щоб клієнт бачив де ви</i>"
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

    # ⭐ НОВІ ОБРОБНИКИ ДЛЯ REPLY KEYBOARD (велика кнопка що змінюється)
    
    @router.message(F.text == "🚗 В дорозі")
    async def trip_in_progress_button(message: Message) -> None:
        """Водій натиснув кнопку 'В дорозі' → змінити на 'На місці'"""
        if not message.from_user:
            return
        
        # Отримати активне замовлення водія
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            await message.answer("❌ Водія не знайдено")
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        # Оновити статус на "in_progress"
        await start_order(config.database_path, order.id, driver.id)
        
        # ⭐ Очистити адресу і створити посилання
        clean_pickup = clean_address(order.pickup_address)
        pickup_link = ""
        
        if order.pickup_lat and order.pickup_lon:
            pickup_link = f"\n📍 <a href='https://www.google.com/maps?q={order.pickup_lat},{order.pickup_lon}'>Відкрити на карті</a>"
        
        # ⭐ ЗМІНИТИ КНОПКУ на "📍 На місці"
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        
        kb_trip = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 На місці")],
                [
                    KeyboardButton(text="❌ Відмовитися"),
                    KeyboardButton(text="📞 Зв'язатися з клієнтом")
                ],
                [
                    KeyboardButton(text="ℹ️ Допомога"),
                    KeyboardButton(text="💬 Підтримка")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        await message.answer(
            f"✅ <b>В дорозі до клієнта!</b>\n\n"
            f"🚗 <b>Рухайтесь до адреси подачі:</b>\n"
            f"{clean_pickup}{pickup_link}\n\n"
            f"👇 Натисніть кнопку коли приїдете",
            reply_markup=kb_trip
        )
    
    @router.message(F.text == "📍 На місці")
    async def trip_arrived_button(message: Message) -> None:
        """Водій натиснув кнопку 'На місці' → змінити на 'Виконую замовлення'"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        # Повідомити клієнта
        try:
            await message.bot.send_message(
                order.user_id,
                f"📍 <b>Водій на місці!</b>\n\n"
                f"🚗 {driver.full_name}\n"
                f"📱 <code>{driver.phone}</code>\n\n"
                f"Водій чекає на вас!"
            )
        except Exception as e:
            logger.error(f"Failed to notify client: {e}")
        
        # ⭐ Очистити адресу призначення і створити посилання
        clean_destination = clean_address(order.destination_address)
        destination_link = ""
        
        if order.dest_lat and order.dest_lon:
            destination_link = f"\n📍 <a href='https://www.google.com/maps?q={order.dest_lat},{order.dest_lon}'>Відкрити на карті</a>"
        
        # ⭐ ЗМІНИТИ КНОПКУ на "🚀 Виконую замовлення"
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        
        kb_trip = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚀 Виконую замовлення")],
                [
                    KeyboardButton(text="❌ Відмовитися"),
                    KeyboardButton(text="📞 Зв'язатися з клієнтом")
                ],
                [
                    KeyboardButton(text="ℹ️ Допомога"),
                    KeyboardButton(text="💬 Підтримка")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        await message.answer(
            f"✅ <b>На місці подачі!</b>\n\n"
            f"👋 <b>Зустрічайте клієнта:</b>\n"
            f"👤 {order.name}\n"
            f"📱 <code>{order.phone}</code>\n\n"
            f"📍 <b>Їдете до:</b>\n"
            f"{clean_destination}{destination_link}\n\n"
            f"👇 Натисніть кнопку коли почнете поїздку",
            reply_markup=kb_trip
        )
    
    @router.message(F.text == "🚀 Виконую замовлення")
    async def trip_executing_button(message: Message) -> None:
        """Водій натиснув кнопку 'Виконую замовлення' → змінити на 'Завершити'"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        # ⭐ Очистити адресу призначення і створити посилання
        clean_destination = clean_address(order.destination_address)
        destination_link = ""
        
        if order.dest_lat and order.dest_lon:
            destination_link = f"\n📍 <a href='https://www.google.com/maps?q={order.dest_lat},{order.dest_lon}'>Відкрити на карті</a>"
        
        # ⭐ ЗМІНИТИ КНОПКУ на "🏁 Завершити"
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        
        kb_trip = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🏁 Завершити")],
                [
                    KeyboardButton(text="❌ Відмовитися"),
                    KeyboardButton(text="📞 Зв'язатися з клієнтом")
                ],
                [
                    KeyboardButton(text="ℹ️ Допомога"),
                    KeyboardButton(text="💬 Підтримка")
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        await message.answer(
            f"🚀 <b>Виконуєте замовлення!</b>\n\n"
            f"🎯 <b>Напрямок:</b>\n"
            f"{clean_destination}{destination_link}\n\n"
            f"💰 <b>Вартість:</b> {int(order.fare_amount):.0f} грн\n\n"
            f"👇 Натисніть кнопку коли доїдете до призначення",
            reply_markup=kb_trip
        )
    
    @router.message(F.text == "🏁 Завершити")
    async def trip_complete_button(message: Message) -> None:
        """Водій натиснув кнопку 'Завершити' → завершити замовлення"""
        if not message.from_user:
            return
        
        logger.info(f"🏁 Водій {message.from_user.id} натиснув 'Завершити'")
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            logger.error(f"❌ Водія {message.from_user.id} не знайдено в БД")
            await message.answer("❌ Водія не знайдено")
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            logger.warning(f"⚠️ У водія {driver.id} немає активного замовлення")
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        logger.info(f"✅ Завершення замовлення #{order.id} водієм {driver.id}")
        
        # Розрахунок вартості та комісії
        fare = order.fare_amount if order.fare_amount else 100.0
        distance_m = order.distance_m if order.distance_m else 0
        duration_s = order.duration_s if order.duration_s else 0
        
        from app.storage.db import get_latest_tariff, insert_payment, Payment
        tariff = await get_latest_tariff(config.database_path)
        commission_rate = tariff.commission_percent if tariff else 0.02
        commission = fare * commission_rate
        
        await complete_order(
            config.database_path,
            order.id,
            driver.id,
            fare,
            distance_m,
            duration_s,
            commission
        )
        
        # Запис у payments
        payment = Payment(
            id=None,
            order_id=order.id,
            driver_id=driver.id,
            amount=fare,
            commission=commission,
            commission_paid=False,
            payment_method=order.payment_method or 'cash',  # ✅ ДОДАНО
            created_at=datetime.now(timezone.utc)
        )
        await insert_payment(config.database_path, payment)
        
        # 🌟 Відправити запит на оцінку водія клієнту
        try:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            # ✅ ПРАВИЛЬНИЙ ФОРМАТ: rate:driver:{driver_id}:{rating}:{order_id}
            rating_buttons = [
                [
                    InlineKeyboardButton(text="⭐", callback_data=f"rate:driver:{driver.tg_user_id}:1:{order.id}"),
                    InlineKeyboardButton(text="⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:2:{order.id}"),
                    InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:3:{order.id}"),
                ],
                [
                    InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:4:{order.id}"),
                    InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data=f"rate:driver:{driver.tg_user_id}:5:{order.id}"),
                ],
                [InlineKeyboardButton(text="⏩ Пропустити", callback_data=f"rate:skip:{order.id}")]
            ]
            
            rating_kb = InlineKeyboardMarkup(inline_keyboard=rating_buttons)
            
            fare_text = f"{fare:.0f} грн" if fare else "Уточнюється"
            distance_text = f"{distance_m / 1000:.1f} км" if distance_m else "Не вказано"
            
            await message.bot.send_message(
                chat_id=order.user_id,
                text=(
                    f"🏁 <b>Поїздка завершена!</b>\n\n"
                    f"🚗 Водій: {driver.full_name}\n"
                    f"📏 Відстань: {distance_text}\n"
                    f"💰 Вартість: {fare_text}\n\n"
                    f"⭐ <b>Будь ласка, оцініть водія:</b>\n"
                    f"Ваша оцінка допоможе покращити сервіс!"
                ),
                reply_markup=rating_kb
            )
            logger.info(f"✅ Запит на оцінку надіслано клієнту #{order.user_id}")
        except Exception as e:
            logger.error(f"❌ Помилка відправки запиту на оцінку: {e}")
        
        # ⭐ ПОВЕРНУТИСЯ ДО ПАНЕЛІ ВОДІЯ
        logger.info(f"🔄 Повернення водія {driver.id} до панелі після завершення замовлення #{order.id}")
        
        await message.answer(
            f"✅ <b>Замовлення #{order.id} завершено!</b>\n\n"
            f"💰 Заробіток: {fare:.2f} грн\n"
            f"💳 Комісія: {commission:.2f} грн\n"
            f"💵 Чистий дохід: {fare - commission:.2f} грн\n\n"
            f"🎉 Дякуємо за роботу!",
            reply_markup=driver_panel_keyboard()
        )
        
        logger.info(f"✅ Замовлення #{order.id} повністю завершено. Водій {driver.id} повернувся до панелі.")
    
    @router.message(F.text == "❌ Відмовитися")
    async def trip_cancel_button(message: Message) -> None:
        """Водій відмовляється від замовлення"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        # Скасувати замовлення
        success = await cancel_order_by_driver(config.database_path, order.id, driver.id, "Водій відмовився")
        
        if success:
            # Повідомити клієнта
            try:
                await message.bot.send_message(
                    order.user_id,
                    f"❌ <b>Водій відмовився від замовлення</b>\n\n"
                    f"🚗 {driver.full_name}\n\n"
                    f"Ваше замовлення повернуто в загальну чергу.\n"
                    f"Шукаємо іншого водія..."
                )
            except Exception as e:
                logger.error(f"Failed to notify client: {e}")
            
            # Оновити статистику водія (відмова)
            # Це можна додати до бази даних для аналітики
            logger.warning(f"⚠️ Водій {driver.full_name} відмовився від замовлення #{order.id}")
            
            await message.answer(
                "❌ <b>Ви відмовилися від замовлення</b>\n\n"
                "Замовлення повернуто іншим водіям.",
                reply_markup=driver_panel_keyboard()
            )
        else:
            await message.answer("❌ Не вдалося скасувати замовлення")
    
    @router.message(F.text == "📞 Зв'язатися з клієнтом")
    async def trip_contact_client_button(message: Message) -> None:
        """Показати контакти клієнта"""
        if not message.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        if not driver:
            return
        
        order = await get_active_order_for_driver(config.database_path, driver.id)
        if not order:
            await message.answer("❌ У вас немає активного замовлення")
            return
        
        await message.answer(
            f"📞 <b>Контакти клієнта:</b>\n\n"
            f"👤 Ім'я: {order.name}\n"
            f"📱 Телефон: <code>{order.phone}</code>\n\n"
            f"💡 Натисніть на номер щоб скопіювати"
        )
    
    @router.message(F.text == "ℹ️ Допомога")
    async def trip_help_button(message: Message) -> None:
        """Інструкції для водія під час поїздки"""
        await message.answer(
            "ℹ️ <b>Допомога - Керування поїздкою</b>\n\n"
            "<b>Крок 1:</b> 🚗 <b>В дорозі</b>\n"
            "Натисніть коли почнете рух до клієнта\n\n"
            "<b>Крок 2:</b> 📍 <b>На місці</b>\n"
            "Натисніть коли приїдете на адресу подачі\n\n"
            "<b>Крок 3:</b> 🚀 <b>Виконую замовлення</b>\n"
            "Натисніть коли клієнт сів і ви почали поїздку\n\n"
            "<b>Крок 4:</b> 🏁 <b>Завершити</b>\n"
            "Натисніть коли доїхали до призначення\n\n"
            "━━━━━━━━━━━━━━━\n\n"
            "<b>Додаткові кнопки:</b>\n\n"
            "❌ <b>Відмовитися</b> - скасувати замовлення\n"
            "📞 <b>Зв'язатися</b> - номер телефону клієнта\n"
            "💬 <b>Підтримка</b> - зв'язок з адміністрацією"
        )
    
    @router.message(F.text == "💬 Підтримка")
    async def trip_support_button(message: Message) -> None:
        """Зв'язок з адміністрацією"""
        admin_ids = config.bot.admin_ids
        
        if admin_ids and len(admin_ids) > 0:
            admin_id = admin_ids[0]  # Перший адмін зі списку
            admin_link = f"tg://user?id={admin_id}"
            
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📨 Написати адміну", url=admin_link)]
                ]
            )
            
            await message.answer(
                "💬 <b>Зв'язок з підтримкою</b>\n\n"
                "Натисніть кнопку нижче щоб написати адміністратору:\n\n"
                "💡 Опишіть вашу проблему детально",
                reply_markup=kb
            )
        else:
            await message.answer(
                "💬 <b>Зв'язок з підтримкою</b>\n\n"
                "❌ Контакт адміністратора не налаштовано"
            )
    
    @router.message(F.text == "📖 Правила користування")
    async def show_driver_rules(message: Message) -> None:
        """Показати правила користування для водіїв"""
        if not message.from_user:
            return
        
        # Видалити повідомлення користувача
        try:
            await message.delete()
        except:
            pass
        
        rules_text = (
            "📖 <b>ПРАВИЛА ДЛЯ ВОДІЇВ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "🚀 <b>1. ПОЧАТОК РОБОТИ</b>\n"
            "   • Натисніть 🚗 Панель водія\n"
            "   • Переконайтесь що статус: 🟢 Онлайн\n"
            "   • Якщо 🔴 Офлайн - натисніть 📋 Почати роботу\n"
            "   • Замовлення надходять в групу вашого міста\n\n"
            
            "📱 <b>2. ПРИЙНЯТТЯ ЗАМОВЛЕННЯ</b>\n"
            "   • В групі з'явиться нове замовлення:\n"
            "      - Інформація про клієнта (ім'я, телефон)\n"
            "      - Звідки та куди їхати\n"
            "      - Вартість поїздки\n"
            "   • Натисніть ✅ Прийняти замовлення\n"
            "   • Перший хто натисне - отримає замовлення\n\n"
            
            "🎯 <b>3. ВИКОНАННЯ ЗАМОВЛЕННЯ (4 ЕТАПИ)</b>\n\n"
            "   <b>Етап 1: 🚗 В дорозі</b>\n"
            "   • Натисніть коли починаєте рух до клієнта\n"
            "   • Використовуйте посилання \"📍 Відкрити на карті\"\n"
            "   • Їдьте до адреси подачі\n\n"
            
            "   <b>Етап 2: 📍 На місці</b>\n"
            "   • Натисніть коли приїхали на адресу подачі\n"
            "   • Клієнт отримає повідомлення \"Водій на місці\"\n"
            "   • Зустрічайте клієнта\n\n"
            
            "   <b>Етап 3: 🚀 Виконую замовлення</b>\n"
            "   • Натисніть коли клієнт сів в авто\n"
            "   • Використовуйте навігацію до призначення\n"
            "   • Їдьте безпечно!\n\n"
            
            "   <b>Етап 4: 🏁 Завершити</b>\n"
            "   • Натисніть коли доїхали до призначення\n"
            "   • Клієнт отримає запит на оцінку\n"
            "   • Ви повернетесь до панелі водія\n"
            "   • Заробіток та комісія будуть нараховані\n\n"
            
            "🔧 <b>4. ДОДАТКОВІ КНОПКИ</b>\n\n"
            "   ❌ <b>Відмовитися</b>\n"
            "   • Якщо не можете виконати замовлення\n"
            "   • Замовлення повернеться іншим водіям\n"
            "   • Клієнт буде повідомлений\n\n"
            
            "   📞 <b>Зв'язатися з клієнтом</b>\n"
            "   • Показує ім'я та телефон клієнта\n"
            "   • Можна передзвонити для уточнення\n\n"
            
            "   ℹ️ <b>Допомога</b>\n"
            "   • Покрокові інструкції\n"
            "   • Пояснення всіх кнопок\n\n"
            
            "   💬 <b>Підтримка</b>\n"
            "   • Прямий зв'язок з адміністратором\n"
            "   • Швидке вирішення проблем\n\n"
            
            "💰 <b>5. ОПЛАТА ТА КОМІСІЯ</b>\n\n"
            "   • <b>Готівка:</b> Отримуєте від клієнта\n"
            "   • <b>Картка:</b> Клієнт переводить на вашу картку\n"
            "   • <b>Комісія:</b> Нараховується автоматично\n"
            "      - Перегляд: 💳 Комісія\n"
            "      - Сплата: На вказану картку в боті\n"
            "      - Після сплати: натисніть \"✅ Комісію сплачено\"\n"
            "      - Адмін підтвердить → комісія анулюється\n\n"
            
            "📊 <b>6. СТАТИСТИКА</b>\n\n"
            "   • 📊 Мій заробіток - сьогоднішні доходи\n"
            "   • 📜 Історія поїздок - всі ваші поїздки\n"
            "   • 📊 Розширена аналітика - детальна статистика\n"
            "   • 💼 Гаманець - управління карткою для переказів\n\n"
            
            "⭐ <b>7. РЕЙТИНГ</b>\n\n"
            "   • Клієнти оцінюють вас після кожної поїздки\n"
            "   • Високий рейтинг = більше замовлень\n"
            "   • Середній рейтинг показується в профілі\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "💡 <b>ВАЖЛИВІ ПОРАДИ:</b>\n\n"
            "✅ Будьте ввічливими з клієнтами\n"
            "✅ Приїжджайте вчасно\n"
            "✅ Підтримуйте чистоту в авто\n"
            "✅ Дотримуйтесь ПДР\n"
            "✅ Оновлюйте геолокацію для live tracking\n"
            "✅ Сплачуйте комісію вчасно\n\n"
            
            "⚠️ <b>ЗАБОРОНЕНО:</b>\n\n"
            "❌ Відмовлятися без причини\n"
            "❌ Просити додаткову оплату\n"
            "❌ Неввічлива поведінка\n"
            "❌ Порушення ПДР\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "🎉 <b>Успішної роботи!</b> 🚗"
        )
        
        # Inline кнопка "Зрозуміло"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Зрозуміло", callback_data="driver_rules:close")]
            ]
        )
        
        await message.answer(rules_text, reply_markup=kb)
        logger.info(f"📖 Водій {message.from_user.id} переглядає правила користування")
    
    @router.callback_query(F.data == "driver_rules:close")
    async def close_driver_rules(call: CallbackQuery) -> None:
        """Закрити правила водія"""
        await call.answer("✅")
        
        try:
            await call.message.delete()
        except:
            pass
    
    return router
