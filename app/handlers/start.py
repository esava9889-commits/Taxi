from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import CommandStart, Command
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

from app.config.config import AppConfig
from app.storage.db import get_user_by_id, User, upsert_user
from app.handlers.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)


class ProfileEditStates(StatesGroup):
    """Стани для редагування профілю"""
    edit_city = State()
    edit_phone = State()


def create_router(config: AppConfig) -> Router:
    router = Router(name="start")

    @router.message(CommandStart())
    async def on_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        
        if not message.from_user:
            return
        
        # Перевірка чи це АДМІН (найвищий пріоритет)
        is_admin = message.from_user.id in config.bot.admin_ids
        
        # Перевірити чи це ВОДІЙ або є заявка водія
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        is_driver = driver is not None and driver.status == "approved"
        has_driver_application = driver is not None  # pending/rejected/approved → заявка існує
        
        # Перевірити чи це КЛІЄНТ (тільки якщо НЕ водій і НЕ має заявки, окрім адміна)
        user = None
        if (not is_driver and not has_driver_application) or is_admin:
            user = await get_user_by_id(config.database_path, message.from_user.id)
        
        # АДМІН - найвищий пріоритет
        if is_admin:
            text = (
                f"👋 <b>Вітаю, Адмін {message.from_user.first_name}!</b>\n\n"
                "🔧 Ви маєте доступ до адміністративних функцій.\n"
                "Оберіть дію з меню нижче."
            )
            
            await message.answer(
                text,
                reply_markup=main_menu_keyboard(
                    is_registered=True, 
                    is_driver=is_driver, 
                    is_admin=True,
                    has_driver_application=has_driver_application
                )
            )
            return
        
        # ВОДІЙ - показуємо меню водія
        if is_driver:
            text = (
                f"👋 <b>Вітаю, {driver.full_name}!</b>\n\n"
                f"🚗 Ви зареєстровані як <b>водій</b>\n"
                f"📍 Місто: {driver.city or 'Не вказано'}\n"
                f"🚙 Авто: {driver.car_make} {driver.car_model} ({driver.car_plate})\n\n"
                "Оберіть дію з меню нижче:"
            )
            
            await message.answer(
                text,
                reply_markup=main_menu_keyboard(
                    is_registered=False, 
                    is_driver=True, 
                    is_admin=False,
                    has_driver_application=False  # Водій вже approved
                )
            )
            return
        
        # КЛІЄНТ - звичайний flow
        if user and user.phone and user.city:
            # Повна реєстрація
            greeting = "З поверненням, "
            if is_admin:
                greeting = "З поверненням, Адміністратор "
            
            await message.answer(
                f"{greeting}{user.full_name}! 👋\n\n"
                f"📍 Місто: {user.city}\n"
                f"📱 Телефон: {user.phone}\n\n"
                "Оберіть дію з меню нижче:",
                reply_markup=main_menu_keyboard(
                    is_registered=True, 
                    is_driver=is_driver, 
                    is_admin=is_admin,
                    has_driver_application=has_driver_application
                )
            )
        elif user:
            # Неповна реєстрація - пропонуємо завершити
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📱 Завершити реєстрацію", callback_data="register:start")],
                    [InlineKeyboardButton(text="ℹ️ Допомога", callback_data="help:show")],
                ]
            )
            await message.answer(
                f"Вітаємо, {user.full_name}! 👋\n\n"
                "Для замовлення таксі завершіть реєстрацію:\n"
                "• Вкажіть ваше місто\n"
                "• Додайте номер телефону\n\n"
                "Це займе менше хвилини! ⏱",
                reply_markup=kb
            )
        else:
            # Новий користувач
            new_user = User(
                user_id=message.from_user.id,
                full_name=message.from_user.full_name or "Користувач",
                phone="",
                role="client",
                created_at=datetime.now(timezone.utc),
                city=None,
            )
            await upsert_user(config.database_path, new_user)
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📱 Почати реєстрацію", callback_data="register:start")],
                    [InlineKeyboardButton(text="ℹ️ Як це працює?", callback_data="help:show")],
                ]
            )
            
            await message.answer(
                f"Вітаємо в таксі-боті! 🚖\n\n"
                f"Привіт, {message.from_user.full_name}!\n\n"
                "🚕 Швидке замовлення таксі\n"
                "💰 Прозорі ціни\n"
                "⭐️ Перевірені водії\n\n"
                "Почніть з реєстрації - це займе 1 хвилину!",
                reply_markup=kb
            )

    # Реєстрація тепер в окремому модулі registration.py
    # Тут залишаємо тільки базову навігацію

    @router.callback_query(F.data == "help:show")
    @router.message(F.text == "ℹ️ Допомога")
    async def show_help(event) -> None:
        # Видалити повідомлення користувача для чистого чату
        try:
            await event.delete()
        except:
            pass
        
        # Отримати актуальну комісію з БД
        from app.storage.db import get_latest_tariff
        tariff = await get_latest_tariff(config.database_path)
        commission_percent = tariff.commission_percent * 100 if tariff else 2.0
        
        help_text = (
            "ℹ️ <b>Як користуватися ботом?</b>\n\n"
            "<b>Для клієнтів:</b>\n"
            "1️⃣ Зареєструйтесь (вкажіть місто та телефон)\n"
            "2️⃣ Натисніть 🚖 Замовити таксі\n"
            "3️⃣ Вкажіть адресу подачі та призначення\n"
            "4️⃣ Підтвердіть замовлення\n"
            "5️⃣ Очікуйте водія!\n\n"
            "<b>Для водіїв:</b>\n"
            "• Подайте заявку через кнопку 🚗 Стати водієм\n"
            "• Після підтвердження адміністратором отримаєте доступ\n"
            "• Замовлення надходять у групу водіїв\n"
            "• Перший хто прийме - отримує замовлення\n\n"
            "💰 <b>Тарифи:</b>\n"
            "• Базова ціна + відстань + час\n"
            f"• Комісія сервісу: {commission_percent:.1f}%\n\n"
        )
        
        # Додати посилання на адміна, якщо є
        if config.admin_username:
            help_text += f"📞 <b>Підтримка:</b> @{config.admin_username}"
        else:
            help_text += "📞 <b>Підтримка:</b> Напишіть адміністратору"
        
        if isinstance(event, CallbackQuery):
            await event.answer()
            await event.message.answer(help_text)
        else:
            await event.answer(help_text)

    @router.message(F.text == "👤 Мій профіль")
    async def show_profile(message: Message) -> None:
        if not message.from_user:
            return
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        if not user:
            await message.answer("❌ Профіль не знайдено. Зареєструйтесь спочатку.")
            return
        
        # Перевірка активного замовлення
        from app.storage.db import get_user_active_order
        active_order = await get_user_active_order(config.database_path, message.from_user.id)
        
        # Формування кнопок
        buttons = []
        
        if active_order:
            # Якщо є активне замовлення
            if active_order.status == "pending":
                # Замовлення ще не прийняте - можна скасувати
                buttons.append([
                    InlineKeyboardButton(text="🔍 Статус замовлення", callback_data=f"order:status:{active_order.id}"),
                    InlineKeyboardButton(text="❌ Скасувати замовлення", callback_data=f"order:cancel_confirm:{active_order.id}")
                ])
            elif active_order.status in ("accepted", "in_progress"):
                # Замовлення прийняте або виконується - можна відстежити водія
                buttons.append([
                    InlineKeyboardButton(text="🚗 Відстежити водія", callback_data=f"order:track:{active_order.id}"),
                    InlineKeyboardButton(text="📞 Зв'язатись з водієм", callback_data=f"order:contact:{active_order.id}")
                ])
                buttons.append([InlineKeyboardButton(text="🔍 Статус замовлення", callback_data=f"order:status:{active_order.id}")])
        
        # Загальні кнопки
        buttons.append([
            InlineKeyboardButton(text="📍 Збережені адреси", callback_data="profile:saved_addresses"),
            InlineKeyboardButton(text="📜 Історія замовлень", callback_data="profile:history")
        ])
        buttons.append([
            InlineKeyboardButton(text="✏️ Змінити місто", callback_data="profile:edit:city"),
            InlineKeyboardButton(text="📱 Змінити телефон", callback_data="profile:edit:phone")
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        # Текст профілю
        profile_text = (
            f"👤 <b>Ваш профіль</b>\n\n"
            f"Ім'я: {user.full_name}\n"
            f"📍 Місто: {user.city or 'Не вказано'}\n"
            f"📱 Телефон: {user.phone or 'Не вказано'}\n"
            f"📅 Дата реєстрації: {user.created_at.strftime('%d.%m.%Y')}"
        )
        
        if active_order:
            status_emoji = {
                "pending": "⏳",
                "accepted": "✅",
                "in_progress": "🚗"
            }.get(active_order.status, "❓")
            
            status_text = {
                "pending": "Очікує водія",
                "accepted": "Водія призначено",
                "in_progress": "В дорозі"
            }.get(active_order.status, "Невідомо")
            
            profile_text += f"\n\n{status_emoji} <b>Активне замовлення #{active_order.id}</b>\n"
            profile_text += f"Статус: {status_text}\n"
            profile_text += f"📍 Звідки: {active_order.pickup_address}\n"
            profile_text += f"📍 Куди: {active_order.destination_address}"
        
        await message.answer(profile_text, reply_markup=kb)

    # Обробники кнопок профілю
    @router.callback_query(F.data.startswith("order:status:"))
    async def show_order_status(call: CallbackQuery) -> None:
        """Показати статус замовлення"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[-1])
        
        from app.storage.db import get_order_by_id, get_driver_by_id
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        status_emoji = {
            "pending": "⏳",
            "accepted": "✅",
            "in_progress": "🚗",
            "completed": "✅",
            "cancelled": "❌"
        }.get(order.status, "❓")
        
        status_text = {
            "pending": "Очікує водія",
            "accepted": "Водія призначено",
            "in_progress": "В дорозі",
            "completed": "Завершено",
            "cancelled": "Скасовано"
        }.get(order.status, "Невідомо")
        
        text = (
            f"{status_emoji} <b>Замовлення #{order.id}</b>\n\n"
            f"Статус: <b>{status_text}</b>\n"
            f"📍 Звідки: {order.pickup_address}\n"
            f"📍 Куди: {order.destination_address}\n"
            f"📅 Створено: {order.created_at.strftime('%d.%m.%Y %H:%M')}"
        )
        
        if order.distance_m:
            text += f"\n📏 Відстань: {order.distance_m / 1000:.1f} км"
        
        if order.fare_amount:
            text += f"\n💰 Вартість: {order.fare_amount:.2f} грн"
        
        if order.driver_id:
            driver = await get_driver_by_id(config.database_path, order.driver_id)
            if driver:
                text += f"\n\n🚗 <b>Водій:</b>\n"
                text += f"👤 {driver.full_name}\n"
                text += f"🚙 {driver.car_make} {driver.car_model}\n"
                text += f"🔢 {driver.car_plate}\n"
                text += f"📱 {driver.phone}"
        
        if order.comment:
            text += f"\n\n💬 Коментар: {order.comment}"
        
        await call.answer()
        await call.message.answer(text)
    
    @router.callback_query(F.data.startswith("order:cancel_confirm:"))
    async def confirm_order_cancellation(call: CallbackQuery) -> None:
        """Підтвердження скасування замовлення"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[-1])
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Так, скасувати", callback_data=f"order:cancel_yes:{order_id}"),
                    InlineKeyboardButton(text="❌ Ні, залишити", callback_data="order:cancel_no")
                ]
            ]
        )
        
        await call.answer()
        await call.message.answer(
            "❓ <b>Скасувати замовлення?</b>\n\n"
            "Ви впевнені, що хочете скасувати це замовлення?",
            reply_markup=kb
        )
    
    @router.callback_query(F.data.startswith("order:cancel_yes:"))
    async def cancel_order_confirmed(call: CallbackQuery) -> None:
        """Скасування замовлення підтверджено"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[-1])
        
        from app.storage.db import cancel_order_by_client, get_order_by_id
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if order.status != "pending":
            await call.answer("❌ Замовлення вже не можна скасувати", show_alert=True)
            return
        
        success = await cancel_order_by_client(config.database_path, order_id, call.from_user.id)
        
        if success:
            await call.answer("✅ Замовлення скасовано", show_alert=True)
            await call.message.answer("✅ <b>Замовлення скасовано</b>\n\nВи можете створити нове замовлення будь-коли.")
            
            # Повідомити в групу водіїв
            if order.group_message_id and config.driver_group_chat_id:
                try:
                    await call.bot.edit_message_text(
                        chat_id=config.driver_group_chat_id,
                        message_id=order.group_message_id,
                        text=f"❌ <b>ЗАМОВЛЕННЯ #{order.id} СКАСОВАНО КЛІЄНТОМ</b>\n\n"
                             f"📍 Маршрут: {order.pickup_address} → {order.destination_address}"
                    )
                except Exception as e:
                    logger.error(f"Failed to update group message: {e}")
        else:
            await call.answer("❌ Не вдалося скасувати замовлення", show_alert=True)
    
    @router.callback_query(F.data == "order:cancel_no")
    async def cancel_order_declined(call: CallbackQuery) -> None:
        """Скасування відхилено"""
        await call.answer("✅ Замовлення залишається активним")
        await call.message.delete()
    
    @router.callback_query(F.data.startswith("order:track:"))
    async def track_driver(call: CallbackQuery) -> None:
        """Відстежити водія"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[-1])
        
        from app.storage.db import get_order_by_id, get_driver_by_id
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if not order.driver_id:
            await call.answer("❌ Водія ще не призначено", show_alert=True)
            return
        
        driver = await get_driver_by_id(config.database_path, order.driver_id)
        
        if not driver:
            await call.answer("❌ Інформація про водія недоступна", show_alert=True)
            return
        
        text = (
            f"🚗 <b>Ваш водій:</b>\n\n"
            f"👤 {driver.full_name}\n"
            f"🚙 {driver.car_make} {driver.car_model}\n"
            f"🔢 Номер: {driver.car_plate}\n"
            f"📱 Телефон: {driver.phone}\n\n"
            f"📍 <b>Маршрут:</b>\n"
            f"Звідки: {order.pickup_address}\n"
            f"Куди: {order.destination_address}"
        )
        
        if order.distance_m:
            text += f"\n\n📏 Відстань: {order.distance_m / 1000:.1f} км"
        
        if order.status == "in_progress":
            text += "\n\n🚗 <b>Статус: В дорозі</b>"
        elif order.status == "accepted":
            text += "\n\n✅ <b>Статус: Водій їде до вас</b>"
        
        await call.answer()
        await call.message.answer(text)
    
    @router.callback_query(F.data.startswith("order:contact:"))
    async def contact_driver(call: CallbackQuery) -> None:
        """Зв'язатись з водієм"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[-1])
        
        from app.storage.db import get_order_by_id, get_driver_by_id
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if not order.driver_id:
            await call.answer("❌ Водія ще не призначено", show_alert=True)
            return
        
        driver = await get_driver_by_id(config.database_path, order.driver_id)
        
        if not driver:
            await call.answer("❌ Інформація про водія недоступна", show_alert=True)
            return
        
        await call.answer()
        await call.message.answer(
            f"📞 <b>Контакт водія:</b>\n\n"
            f"👤 {driver.full_name}\n"
            f"📱 {driver.phone}\n\n"
            f"Ви можете зателефонувати водієві за цим номером."
        )
    
    @router.callback_query(F.data == "profile:history")
    async def show_order_history(call: CallbackQuery) -> None:
        """Показати історію замовлень"""
        if not call.from_user:
            return
        
        from app.storage.db import get_user_order_history
        orders = await get_user_order_history(config.database_path, call.from_user.id, limit=10)
        
        if not orders:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Повернутися", callback_data="profile:back")]
            ])
            await call.answer()
            await call.message.edit_text("📜 У вас поки немає замовлень.", reply_markup=kb)
            return
        
        text = "📜 <b>Ваші останні замовлення:</b>\n\n"
        
        for o in orders:
            status_emoji = {
                "pending": "⏳ Очікує",
                "offered": "📤 Запропоновано",
                "accepted": "✅ Прийнято",
                "in_progress": "🚗 В дорозі",
                "completed": "✔️ Завершено",
                "cancelled": "❌ Скасовано",
            }.get(o.status, "❓")
            
            text += (
                f"<b>#{o.id}</b> - {status_emoji}\n"
                f"📍 {o.pickup_address[:30]}...\n"
                f"   → {o.destination_address[:30]}...\n"
            )
            if o.fare_amount:
                text += f"💰 {o.fare_amount:.0f} грн\n"
            text += "\n"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Повернутися", callback_data="profile:back")]
        ])
        
        await call.answer()
        await call.message.edit_text(text, reply_markup=kb)
    
    @router.callback_query(F.data == "profile:back")
    async def back_to_profile(call: CallbackQuery) -> None:
        """Повернутися до профілю"""
        if not call.from_user:
            return
        
        # Перезавантажити профіль
        user = await get_user_by_id(config.database_path, call.from_user.id)
        if not user:
            await call.answer("❌ Профіль не знайдено", show_alert=True)
            return
        
        from app.storage.db import get_user_active_order
        active_order = await get_user_active_order(config.database_path, call.from_user.id)
        
        buttons = []
        
        if active_order and active_order.status in ("accepted", "in_progress"):
            buttons.append([
                InlineKeyboardButton(text="🚗 Відстежити водія", callback_data=f"order:track:{active_order.id}"),
                InlineKeyboardButton(text="📞 Зв'язатись з водієм", callback_data=f"order:contact:{active_order.id}")
            ])
        
        buttons.extend([
            [
                InlineKeyboardButton(text="📍 Збережені адреси", callback_data="profile:saved_addresses"),
                InlineKeyboardButton(text="📜 Історія замовлень", callback_data="profile:history")
            ],
            [
                InlineKeyboardButton(text="✏️ Змінити місто", callback_data="profile:edit:city"),
                InlineKeyboardButton(text="📱 Змінити телефон", callback_data="profile:edit:phone")
            ]
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        profile_text = (
            f"👤 <b>Ваш профіль</b>\n\n"
            f"Ім'я: {user.full_name}\n"
            f"📍 Місто: {user.city or 'Не вказано'}\n"
            f"📱 Телефон: {user.phone or 'Не вказано'}\n"
            f"📅 Дата реєстрації: {user.created_at.strftime('%d.%m.%Y')}"
        )
        
        await call.answer()
        try:
            await call.message.edit_text(profile_text, reply_markup=kb)
        except:
            await call.message.answer(profile_text, reply_markup=kb)
    
    @router.callback_query(F.data == "profile:saved_addresses")
    async def show_saved_addresses(call: CallbackQuery) -> None:
        """Показати збережені адреси"""
        if not call.from_user:
            return
        
        from app.storage.db import get_user_saved_addresses
        addresses = await get_user_saved_addresses(config.database_path, call.from_user.id)
        
        if not addresses:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")],
                    [InlineKeyboardButton(text="⬅️ Повернутися", callback_data="profile:back")]
                ]
            )
            await call.answer()
            try:
                await call.message.edit_text(
                    "📍 <b>Збережені адреси</b>\n\n"
                    "У вас поки немає збережених адрес.\n"
                    "Додайте часто використовувані місця для швидкого замовлення!",
                    reply_markup=kb
                )
            except:
                await call.message.answer(
                    "📍 <b>Збережені адреси</b>\n\n"
                    "У вас поки немає збережених адрес.\n"
                    "Додайте часто використовувані місця для швидкого замовлення!",
                    reply_markup=kb
                )
            return
        
        buttons = []
        for addr in addresses:
            buttons.append([InlineKeyboardButton(
                text=f"{addr.emoji} {addr.name}",
                callback_data=f"address:view:{addr.id}"
            )])
        
        buttons.append([InlineKeyboardButton(text="➕ Додати адресу", callback_data="address:add")])
        buttons.append([InlineKeyboardButton(text="⬅️ Повернутися", callback_data="profile:back")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await call.answer()
        try:
            await call.message.edit_text(
                f"📍 <b>Збережені адреси ({len(addresses)}/10)</b>\n\n"
                "Оберіть адресу для перегляду або додайте нову:",
                reply_markup=kb
            )
        except:
            await call.message.answer(
                f"📍 <b>Збережені адреси ({len(addresses)}/10)</b>\n\n"
                "Оберіть адресу для перегляду або додайте нову:",
                reply_markup=kb
            )
    
    @router.callback_query(F.data.startswith("address:view:"))
    async def view_saved_address(call: CallbackQuery) -> None:
        """Переглянути збережену адресу"""
        if not call.from_user:
            return
        
        address_id = int(call.data.split(":")[-1])
        
        from app.storage.db import get_saved_address_by_id
        address = await get_saved_address_by_id(config.database_path, address_id, call.from_user.id)
        
        if not address:
            await call.answer("❌ Адресу не знайдено", show_alert=True)
            return
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📍 Використати звідки", callback_data=f"address:use:pickup:{address_id}"),
                    InlineKeyboardButton(text="📍 Використати куди", callback_data=f"address:use:dest:{address_id}")
                ],
                [InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"address:edit:{address_id}")],
                [InlineKeyboardButton(text="🗑️ Видалити", callback_data=f"address:delete_confirm:{address_id}")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile:saved_addresses")]
            ]
        )
        
        await call.answer()
        await call.message.answer(
            f"{address.emoji} <b>{address.name}</b>\n\n"
            f"📍 Адреса: {address.address}\n"
            f"📅 Додано: {address.created_at.strftime('%d.%m.%Y')}",
            reply_markup=kb
        )
    
    @router.callback_query(F.data.startswith("address:delete_confirm:"))
    async def confirm_delete_address(call: CallbackQuery) -> None:
        """Підтвердження видалення адреси"""
        if not call.from_user:
            return
        
        address_id = int(call.data.split(":")[-1])
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"address:delete_yes:{address_id}"),
                    InlineKeyboardButton(text="❌ Скасувати", callback_data=f"address:view:{address_id}")
                ]
            ]
        )
        
        await call.answer()
        await call.message.answer(
            "❓ <b>Видалити адресу?</b>\n\n"
            "Ви впевнені, що хочете видалити цю адресу?",
            reply_markup=kb
        )
    
    @router.callback_query(F.data.startswith("address:delete_yes:"))
    async def delete_address_confirmed(call: CallbackQuery) -> None:
        """Видалення адреси підтверджено"""
        if not call.from_user:
            return
        
        address_id = int(call.data.split(":")[-1])
        
        from app.storage.db import delete_saved_address
        success = await delete_saved_address(config.database_path, address_id, call.from_user.id)
        
        if success:
            await call.answer("✅ Адресу видалено", show_alert=True)
            # Показати список адрес знову
            await show_saved_addresses(call)
        else:
            await call.answer("❌ Помилка видалення", show_alert=True)
    
    async def show_profile_history(call: CallbackQuery) -> None:
        """Показати історію замовлень"""
        if not call.from_user:
            return
        
        from app.storage.db import get_user_order_history
        orders = await get_user_order_history(config.database_path, call.from_user.id, limit=10)
        
        if not orders:
            await call.answer("📜 У вас поки немає замовлень", show_alert=True)
            return
        
        text = "📜 <b>Історія замовлень</b>\n\n"
        
        for order in orders:
            status_emoji = {
                "pending": "⏳",
                "accepted": "✅",
                "in_progress": "🚗",
                "completed": "✅",
                "cancelled": "❌"
            }.get(order.status, "❓")
            
            text += f"{status_emoji} <b>Замовлення #{order.id}</b>\n"
            text += f"📍 {order.pickup_address} → {order.destination_address}\n"
            text += f"📅 {order.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            
            if order.fare_amount:
                text += f"💰 {order.fare_amount:.2f} грн\n"
            
            text += "\n"
        
        await call.answer()
        await call.message.answer(text)
    
    @router.callback_query(F.data == "open_driver_panel")
    async def open_driver_panel(call: CallbackQuery) -> None:
        """Обробник для відкриття панелі водія після підтвердження"""
        if not call.from_user:
            return
        
        await call.answer("🚗 Відкриваю панель водія...")
        
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        
        if not driver or driver.status != "approved":
            await call.answer("❌ Ви не є підтвердженим водієм.", show_alert=True)
            return
        
        from app.storage.db import get_driver_earnings_today, get_driver_unpaid_commission
        
        earnings, commission_owed = await get_driver_earnings_today(config.database_path, call.from_user.id)
        net_earnings = earnings - commission_owed
        
        online_status = "🟢 Онлайн" if driver.online else "🔴 Офлайн"
        
        text = (
            f"🚗 <b>Панель водія</b>\n\n"
            f"👤 {driver.full_name}\n"
            f"🏙 Місто: {driver.city or 'Не вказано'}\n"
            f"🚙 Авто: {driver.car_make} {driver.car_model}\n"
            f"🔢 Номер: {driver.car_plate}\n\n"
            f"📊 <b>Статистика сьогодні:</b>\n"
            f"💰 Заробіток: {earnings:.2f} грн\n"
            f"💸 Комісія: {commission_owed:.2f} грн\n"
            f"💵 Чистий: {net_earnings:.2f} грн\n\n"
            f"Статус: {online_status}\n\n"
            "ℹ️ Замовлення надходять у групу водіїв.\n"
            "Прийміть замовлення першим, щоб його отримати!"
        )
        
        # Перевірка чи це адмін
        is_admin = call.from_user.id in config.bot.admin_ids
        
        # Видалити попереднє повідомлення "Вашу заявку схвалено" або "Панель водія активована"
        try:
            await call.message.delete()
        except:
            pass
        
        # Відправити панель водія з клавіатурою
        await call.message.answer(
            text,
            reply_markup=main_menu_keyboard(is_registered=True, is_driver=True, is_admin=is_admin),
            parse_mode="HTML"
        )

    # ВИДАЛЕНО ОБРОБНИК "🚗 Панель водія" - він тепер тільки в driver_panel.py!
    # Це виправляє конфлікт обробників
    
    # Команда /driver залишена для сумісності
    @router.message(Command("driver"))
    async def quick_driver_command(message: Message) -> None:
        """Команда /driver - показати підказку"""
        if not message.from_user:
            return
        
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        
        if not driver:
            await message.answer("❌ Ви не зареєстровані як водій.\n\nНатисніть 🚗 Стати водієм для реєстрації.")
            return
        
        if driver.status != "approved":
            await message.answer("⏳ Ваша заявка на розгляді.")
            return
        
        # Показати підказку
        is_admin = message.from_user.id in config.bot.admin_ids
        await message.answer(
            "🚗 Використовуйте кнопку <b>'🚗 Панель водія'</b> внизу екрану",
            reply_markup=main_menu_keyboard(is_registered=True, is_driver=True, is_admin=is_admin)
        )
    
    @router.callback_query(F.data == "driver_to_client:confirm")
    async def confirm_driver_to_client(call: CallbackQuery, state: FSMContext) -> None:
        """Підтвердити видалення акаунта водія та перехід до клієнта"""
        if not call.from_user:
            return
        
        await call.answer()
        
        # Видалити акаунт водія з БД
        from app.storage.db import delete_driver_account
        success = await delete_driver_account(config.database_path, call.from_user.id)
        
        if not success:
            await call.message.edit_text(
                "❌ Помилка видалення акаунта водія.\n\n"
                "Зверніться до адміністратора."
            )
            return
        
        # Видалити повідомлення з попередженням
        try:
            await call.message.delete()
        except:
            pass
        
        # Очистити FSM state
        await state.clear()
        
        # Очистити чат (видалити останні 50 повідомлень)
        try:
            for i in range(50):
                try:
                    await call.bot.delete_message(
                        chat_id=call.from_user.id,
                        message_id=call.message.message_id - i
                    )
                except:
                    pass
        except:
            pass
        
        # Показати початкове меню (як для нового користувача)
        from app.handlers.keyboards import main_menu_keyboard
        
        # Перевірити чи є базова реєстрація
        user = await get_user_by_id(config.database_path, call.from_user.id)
        
        if not user or not user.phone or not user.city:
            # Немає базової реєстрації - показати меню реєстрації
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📱 Зареєструватись", callback_data="register:start")]
                ]
            )
            
            await call.bot.send_message(
                chat_id=call.from_user.id,
                text=(
                    "👋 <b>Вітаємо в боті таксі!</b>\n\n"
                    "✅ Ваш акаунт водія успішно видалено.\n\n"
                    "Тепер ви можете користуватися ботом як клієнт.\n\n"
                    "Для замовлення таксі необхідно завершити реєстрацію:"
                ),
                reply_markup=kb
            )
        else:
            # Є базова реєстрація - показати головне меню клієнта
            await call.bot.send_message(
                chat_id=call.from_user.id,
                text=(
                    "✅ <b>Акаунт водія успішно видалено!</b>\n\n"
                    f"👤 Ім'я: {user.full_name}\n"
                    f"📱 Телефон: {user.phone}\n"
                    f"🏙 Місто: {user.city}\n\n"
                    "Тепер ви можете користуватися ботом як клієнт.\n\n"
                    "🚖 Натисніть кнопку нижче для замовлення таксі!"
                ),
                reply_markup=main_menu_keyboard(is_registered=True, is_driver=False, is_admin=False)
            )
    
    @router.callback_query(F.data == "driver_to_client:cancel")
    async def cancel_driver_to_client(call: CallbackQuery) -> None:
        """Скасувати перехід до клієнта"""
        if not call.from_user:
            return
        
        await call.answer("Скасовано", show_alert=False)
        
        # Видалити повідомлення з попередженням
        try:
            await call.message.delete()
        except:
            await call.message.edit_text("Операцію скасовано.")
    
    @router.message(Command("client"))
    @router.message(F.text == "👤 Кабінет клієнта")
    async def quick_client_panel(message: Message) -> None:
        """Швидкий перехід до кабінету клієнта"""
        if not message.from_user:
            return
        
        # Видалити повідомлення користувача для чистого чату
        try:
            await message.delete()
        except:
            pass
        
        # Перевірка чи водій
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        
        # ЯКЩО ЦЕ ВОДІЙ - ПОКАЗАТИ ПОПЕРЕДЖЕННЯ
        if driver and driver.status == "approved":
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Підтвердити", callback_data="driver_to_client:confirm")],
                    [InlineKeyboardButton(text="❌ Скасувати", callback_data="driver_to_client:cancel")]
                ]
            )
            
            await message.answer(
                "⚠️ <b>УВАГА!</b>\n\n"
                "Ви зареєстровані як водій.\n\n"
                "Якщо ви бажаєте перейти до <b>кабінету клієнта</b>,\n"
                "ваш <b>акаунт водія буде ВИДАЛЕНО</b> з бази даних.\n\n"
                "Це означає:\n"
                "• Видалення всіх даних водія\n"
                "• Видалення історії поїздок\n"
                "• Видалення заробітку\n"
                "• Неможливо буде відновити\n\n"
                "⚠️ <b>Ця дія НЕЗВОРОТНА!</b>\n\n"
                "Бажаєте продовжити?\n\n"
                "<i>З повагою, Адміністрація бота</i> 🤝",
                reply_markup=kb
            )
            return
        
        # ЯКЩО НЕ ВОДІЙ - ПОКАЗАТИ КАБІНЕТ КЛІЄНТА ЯК ЗАРАЗ
        user = await get_user_by_id(config.database_path, message.from_user.id)
        if not user or not user.phone or not user.city:
            await message.answer("❌ Завершіть реєстрацію для доступу до кабінету клієнта.\n\nНатисніть 📱 Зареєструватись")
            return
        
        # Перевірка чи адмін
        is_admin = message.from_user.id in config.bot.admin_ids
        is_driver = False
        
        await message.answer(
            f"👤 <b>Кабінет клієнта</b>\n\n"
            f"Вітаємо, {user.full_name}!\n\n"
            f"📍 Місто: {user.city}\n"
            f"📱 Телефон: {user.phone}\n\n"
            "Оберіть дію з меню нижче:",
            reply_markup=main_menu_keyboard(is_registered=True, is_driver=is_driver, is_admin=is_admin)
        )
    
    @router.message(F.text == "❌ Скасувати")
    async def cancel(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        is_registered = user is not None and user.phone and user.city
        
        from app.storage.db import get_driver_by_tg_user_id
        driver = await get_driver_by_tg_user_id(config.database_path, message.from_user.id)
        is_driver = driver is not None and driver.status == "approved"
        
        await state.clear()
        # Перевірка чи це адмін
        is_admin = message.from_user.id in config.bot.admin_ids if message.from_user else False
        
        await message.answer(
            "❌ Скасовано.",
            reply_markup=main_menu_keyboard(is_registered=is_registered, is_driver=is_driver, is_admin=is_admin)
        )

    # Обробники редагування профілю
    @router.callback_query(F.data == "profile:edit:city")
    async def edit_city_start(call: CallbackQuery, state: FSMContext) -> None:
        """Почати редагування міста"""
        if not call.from_user:
            return
        
        from app.config.config import AVAILABLE_CITIES
        
        buttons = []
        for city in AVAILABLE_CITIES:
            buttons.append([InlineKeyboardButton(text=city, callback_data=f"city:select:{city}")])
        
        buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="profile:back")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await state.set_state(ProfileEditStates.edit_city)
        await call.answer()
        try:
            await call.message.edit_text(
                "🏙 <b>Оберіть ваше місто:</b>\n\n"
                "Місто необхідне для пошуку водіїв у вашому регіоні.",
                reply_markup=kb
            )
        except:
            await call.message.answer(
                "🏙 <b>Оберіть ваше місто:</b>\n\n"
                "Місто необхідне для пошуку водіїв у вашому регіоні.",
                reply_markup=kb
            )
    
    @router.callback_query(F.data.startswith("city:select:"), ProfileEditStates.edit_city)
    async def save_new_city(call: CallbackQuery, state: FSMContext) -> None:
        """Зберегти нове місто"""
        if not call.from_user:
            return
        
        city = call.data.split("city:select:")[-1]
        
        user = await get_user_by_id(config.database_path, call.from_user.id)
        if not user:
            await call.answer("❌ Помилка", show_alert=True)
            await state.clear()
            return
        
        # Оновити місто
        updated_user = User(
            user_id=user.user_id,
            full_name=user.full_name,
            phone=user.phone,
            role=user.role,
            city=city,
            language=user.language,
            created_at=user.created_at
        )
        
        await upsert_user(config.database_path, updated_user)
        await state.clear()
        
        await call.answer(f"✅ Місто змінено на {city}")
        
        # Повернутися до профілю
        await back_to_profile(call)
    
    @router.callback_query(F.data == "profile:edit:phone")
    async def edit_phone_start(call: CallbackQuery, state: FSMContext) -> None:
        """Почати редагування телефону"""
        if not call.from_user:
            return
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="profile:back")]
        ])
        
        await state.set_state(ProfileEditStates.edit_phone)
        await call.answer()
        try:
            await call.message.edit_text(
                "📱 <b>Введіть новий номер телефону:</b>\n\n"
                "Формат: +380XXXXXXXXX\n"
                "Наприклад: +380501234567",
                reply_markup=kb
            )
        except:
            await call.message.answer(
                "📱 <b>Введіть новий номер телефону:</b>\n\n"
                "Формат: +380XXXXXXXXX\n"
                "Наприклад: +380501234567",
                reply_markup=kb
            )
    
    @router.message(ProfileEditStates.edit_phone)
    async def save_new_phone(message: Message, state: FSMContext) -> None:
        """Зберегти новий телефон"""
        if not message.from_user or not message.text:
            return
        
        phone = message.text.strip()
        
        # Валідація телефону
        if not re.match(r'^\+380\d{9}$', phone):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Скасувати", callback_data="profile:back")]
            ])
            await message.answer(
                "❌ <b>Невірний формат!</b>\n\n"
                "Введіть номер у форматі: +380XXXXXXXXX\n"
                "Спробуйте ще раз:",
                reply_markup=kb
            )
            return
        
        user = await get_user_by_id(config.database_path, message.from_user.id)
        if not user:
            await message.answer("❌ Помилка оновлення профілю")
            await state.clear()
            return
        
        # Оновити телефон
        updated_user = User(
            user_id=user.user_id,
            full_name=user.full_name,
            phone=phone,
            role=user.role,
            city=user.city,
            language=user.language,
            created_at=user.created_at
        )
        
        await upsert_user(config.database_path, updated_user)
        await state.clear()
        
        await message.answer(f"✅ Телефон змінено на {phone}")
        
        # Показати оновлений профіль
        from app.storage.db import get_user_active_order
        active_order = await get_user_active_order(config.database_path, message.from_user.id)
        
        buttons = []
        if active_order and active_order.status in ("accepted", "in_progress"):
            buttons.append([
                InlineKeyboardButton(text="🚗 Відстежити водія", callback_data=f"order:track:{active_order.id}"),
                InlineKeyboardButton(text="📞 Зв'язатись з водієм", callback_data=f"order:contact:{active_order.id}")
            ])
        
        buttons.extend([
            [
                InlineKeyboardButton(text="📍 Збережені адреси", callback_data="profile:saved_addresses"),
                InlineKeyboardButton(text="📜 Історія замовлень", callback_data="profile:history")
            ],
            [
                InlineKeyboardButton(text="✏️ Змінити місто", callback_data="profile:edit:city"),
                InlineKeyboardButton(text="📱 Змінити телефон", callback_data="profile:edit:phone")
            ]
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        profile_text = (
            f"👤 <b>Ваш профіль</b>\n\n"
            f"Ім'я: {updated_user.full_name}\n"
            f"📍 Місто: {updated_user.city or 'Не вказано'}\n"
            f"📱 Телефон: {updated_user.phone}\n"
            f"📅 Дата реєстрації: {updated_user.created_at.strftime('%d.%m.%Y')}"
        )
        
        await message.answer(profile_text, reply_markup=kb)
    
    # Обробник оплати поїздки
    @router.callback_query(F.data.startswith("pay:"))
    async def show_payment_info(call: CallbackQuery) -> None:
        """Показати інформацію для оплати поїздки"""
        if not call.from_user:
            return
        
        order_id = int(call.data.split(":")[-1])
        
        from app.storage.db import get_order_by_id, get_driver_by_id
        order = await get_order_by_id(config.database_path, order_id)
        
        if not order or order.user_id != call.from_user.id:
            await call.answer("❌ Замовлення не знайдено", show_alert=True)
            return
        
        if not order.driver_id:
            await call.answer("❌ Водія ще не призначено", show_alert=True)
            return
        
        driver = await get_driver_by_id(config.database_path, order.driver_id)
        
        if not driver:
            await call.answer("❌ Інформація про водія недоступна", show_alert=True)
            return
        
        payment_text = (
            f"💳 <b>Оплата поїздки #{order.id}</b>\n\n"
            f"💰 Вартість: {order.fare_amount:.0f} грн\n\n"
        )
        
        if order.payment_method == "card":
            if driver.card_number:
                payment_text += (
                    f"💳 <b>Картка водія:</b>\n"
                    f"<code>{driver.card_number}</code>\n\n"
                    f"👤 {driver.full_name}\n\n"
                    f"ℹ️ Натисніть на номер картки щоб скопіювати"
                )
            else:
                payment_text += (
                    f"⚠️ <b>Водій не вказав картку</b>\n\n"
                    f"Зв'яжіться з водієм для уточнення реквізитів:\n"
                    f"📱 {driver.phone}"
                )
        else:
            payment_text += (
                f"💵 <b>Оплата готівкою</b>\n\n"
                f"Розрахуйтесь з водієм після завершення поїздки."
            )
        
        await call.answer()
        await call.message.answer(payment_text)
    
    return router
