from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.config.config import AppConfig
from app.handlers.start import ORDER_TEXT  # reuse label for hot button
from app.storage.db import (
    Order,
    insert_order,
    fetch_recent_orders,
    get_latest_tariff,
)
import math
import aiohttp


def create_router(config: AppConfig) -> Router:
    router = Router(name="order")

    CANCEL_TEXT = "Скасувати"
    SKIP_TEXT = "Пропустити"
    CONFIRM_TEXT = "Підтвердити"

    class OrderStates(StatesGroup):
        name = State()
        phone = State()
        pickup = State()
        destination = State()
        comment = State()
        confirm = State()

    def cancel_keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=CANCEL_TEXT)]],
            resize_keyboard=True,
            one_time_keyboard=True,
            input_field_placeholder="Ви можете скасувати замовлення",
        )

    def skip_or_cancel_keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=SKIP_TEXT)], [KeyboardButton(text=CANCEL_TEXT)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    def confirm_keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=CONFIRM_TEXT)], [KeyboardButton(text=CANCEL_TEXT)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    def location_or_cancel_keyboard(prompt: str) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Надіслати геолокацію", request_location=True)],
                [KeyboardButton(text=CANCEL_TEXT)],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
            input_field_placeholder=prompt,
        )

    def is_valid_phone(text: str) -> bool:
        return bool(re.fullmatch(r"[+]?[\d\s\-()]{7,18}", text.strip()))

    # Start order via command or hot button
    @router.message(F.text == ORDER_TEXT)
    @router.message(Command("order"))
    async def start_order(message: Message, state: FSMContext) -> None:
        await state.set_state(OrderStates.name)
        await message.answer(
            "Як до вас звертатися?", reply_markup=cancel_keyboard()
        )

    @router.message(F.text == CANCEL_TEXT)
    async def cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Замовлення скасовано.", reply_markup=ReplyKeyboardRemove())

    @router.message(OrderStates.name)
    async def ask_phone(message: Message, state: FSMContext) -> None:
        full_name = message.text.strip()
        if not full_name:
            await message.answer("Будь ласка, введіть ім'я.")
            return
        await state.update_data(name=full_name)
        await state.set_state(OrderStates.phone)
        await message.answer(
            "Ваш номер телефону?", reply_markup=cancel_keyboard()
        )

    @router.message(OrderStates.phone)
    async def ask_pickup(message: Message, state: FSMContext) -> None:
        phone = message.text.strip()
        if not is_valid_phone(phone):
            await message.answer("Введіть коректний номер, напр.: +380 67 123 45 67")
            return
        await state.update_data(phone=phone)
        await state.set_state(OrderStates.pickup)
        await message.answer(
            "Адреса подачі авто? Ви можете надіслати геолокацію.",
            reply_markup=location_or_cancel_keyboard("Надішліть адресу або геолокацію"),
        )

    @router.message(OrderStates.pickup)
    async def ask_destination(message: Message, state: FSMContext) -> None:
        pickup = message.text.strip()
        if len(pickup) < 3:
            await message.answer("Будь ласка, уточніть адресу подачі.")
            return
        await state.update_data(pickup=pickup)
        await state.set_state(OrderStates.destination)
        await message.answer(
            "Куди їдемо? Вкажіть адресу призначення або надішліть геолокацію.",
            reply_markup=location_or_cancel_keyboard("Вкажіть адресу призначення або гео"),
        )

    @router.message(OrderStates.pickup, F.location)
    async def ask_destination_from_location(message: Message, state: FSMContext) -> None:
        loc = message.location
        pickup = f"geo:{loc.latitude:.6f},{loc.longitude:.6f}"
        await state.update_data(pickup=pickup)
        await state.set_state(OrderStates.destination)
        await message.answer(
            "Куди їдемо? Вкажіть адресу призначення або надішліть геолокацію.",
            reply_markup=location_or_cancel_keyboard("Вкажіть адресу призначення або гео"),
        )

    @router.message(OrderStates.destination)
    async def ask_comment(message: Message, state: FSMContext) -> None:
        destination = message.text.strip()
        if len(destination) < 3:
            await message.answer("Будь ласка, уточніть адресу призначення.")
            return
        await state.update_data(destination=destination)
        await state.set_state(OrderStates.comment)
        await message.answer(
            "Коментар до замовлення? (наприклад, під'їзд/поверх)\n"
            "Можете натиснути 'Пропустити'.",
            reply_markup=skip_or_cancel_keyboard(),
        )

    @router.message(OrderStates.destination, F.location)
    async def ask_comment_from_location(message: Message, state: FSMContext) -> None:
        loc = message.location
        destination = f"geo:{loc.latitude:.6f},{loc.longitude:.6f}"
        await state.update_data(destination=destination)
        await state.set_state(OrderStates.comment)
        await message.answer(
            "Коментар до замовлення? (наприклад, під'їзд/поверх)\n"
            "Можете натиснути 'Пропустити'.",
            reply_markup=skip_or_cancel_keyboard(),
        )

    @router.message(OrderStates.comment, F.text == SKIP_TEXT)
    async def skip_comment(message: Message, state: FSMContext) -> None:
        await state.update_data(comment=None)
        await show_confirmation(message, state)

    @router.message(OrderStates.comment)
    async def take_comment(message: Message, state: FSMContext) -> None:
        comment = message.text.strip()
        await state.update_data(comment=comment)
        await show_confirmation(message, state)

    async def show_confirmation(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        text = (
            "Будь ласка, підтвердіть замовлення:\n\n"
            f"Ім'я: {data.get('name')}\n"
            f"Телефон: {data.get('phone')}\n"
            f"Звідки: {data.get('pickup')}\n"
            f"Куди: {data.get('destination')}\n"
            f"Коментар: {data.get('comment') or '—'}\n"
        )

        # Attempt to estimate distance/time/cost via Google Distance Matrix if possible
        async def parse_geo(s: str) -> Optional[str]:
            if not s:
                return None
            s = s.strip()
            if s.startswith("geo:"):
                return s[4:]
            return None

        origin_geo = await parse_geo(str(data.get("pickup")))
        dest_geo = await parse_geo(str(data.get("destination")))
        api_key = config.google_maps_api_key
        if api_key and origin_geo and dest_geo:
            try:
                origins = origin_geo
                destinations = dest_geo
                url = (
                    "https://maps.googleapis.com/maps/api/distancematrix/json"
                    f"?origins={origins}&destinations={destinations}&key={api_key}&mode=driving"
                )
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=8) as resp:
                        dm = await resp.json()
                rows = dm.get("rows", [])
                if rows and rows[0].get("elements"):
                    el = rows[0]["elements"][0]
                    if el.get("status") == "OK":
                        meters = el["distance"]["value"]
                        seconds = el["duration"]["value"]
                        km = meters / 1000.0
                        minutes = math.ceil(seconds / 60)
                        tariff = await get_latest_tariff(config.database_path)
                        if tariff:
                            amount = max(
                                tariff.minimum,
                                tariff.base_fare + km * tariff.per_km + minutes * tariff.per_minute,
                            )
                            text += (
                                "\nОцінка маршруту:\n"
                                f"Відстань: {km:.1f} км\n"
                                f"Час: ~{minutes} хв\n"
                                f"Вартість: ~{amount:.2f} грн\n"
                            )
            except Exception:
                pass
        await state.set_state(OrderStates.confirm)
        await message.answer(text, reply_markup=confirm_keyboard())

    @router.message(OrderStates.confirm, F.text == CONFIRM_TEXT)
    async def confirm_order(message: Message, state: FSMContext) -> None:
        from app.utils.matching import find_nearest_driver, parse_geo_coordinates
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        data = await state.get_data()
        order = Order(
            id=None,
            user_id=message.from_user.id if message.from_user else 0,
            name=str(data.get("name")),
            phone=str(data.get("phone")),
            pickup_address=str(data.get("pickup")),
            destination_address=str(data.get("destination")),
            comment=(None if data.get("comment") in (None, "") else str(data.get("comment"))),
            created_at=datetime.now(timezone.utc),
        )
        order_id = await insert_order(config.database_path, order)
        await state.clear()
        await message.answer(
            f"✅ Дякуємо! Ваше замовлення №{order_id} прийнято.\n\n"
            f"🔍 Шукаємо водія...",
            reply_markup=ReplyKeyboardRemove(),
        )
        
        # Try to find nearest driver
        pickup_coords = parse_geo_coordinates(str(data.get("pickup")))
        if pickup_coords:
            pickup_lat, pickup_lon = pickup_coords
            driver = await find_nearest_driver(config.database_path, pickup_lat, pickup_lon)
            
            if driver:
                from app.storage.db import offer_order_to_driver
                
                # Offer order to driver
                success = await offer_order_to_driver(config.database_path, order_id, driver.id)
                
                if success:
                    # Notify driver
                    try:
                        dest_coords = parse_geo_coordinates(str(data.get("destination")))
                        distance_info = ""
                        
                        if dest_coords and config.google_maps_api_key:
                            from app.utils.maps import get_distance_and_duration
                            result = await get_distance_and_duration(
                                config.google_maps_api_key,
                                pickup_lat, pickup_lon,
                                dest_coords[0], dest_coords[1]
                            )
                            if result:
                                distance_m, duration_s = result
                                distance_info = f"\n📍 Відстань: {distance_m/1000:.1f} км\n⏱ Час: ~{duration_s//60} хв"
                        
                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(text="✅ Прийняти", callback_data=f"order:accept:{order_id}"),
                                    InlineKeyboardButton(text="❌ Відхилити", callback_data=f"order:reject:{order_id}"),
                                ]
                            ]
                        )
                        
                        await message.bot.send_message(
                            driver.tg_user_id,
                            f"🔔 <b>Нове замовлення #{order_id}</b>\n\n"
                            f"👤 Клієнт: {order.name}\n"
                            f"📱 Телефон: {order.phone}\n"
                            f"📍 Звідки: {order.pickup_address}\n"
                            f"📍 Куди: {order.destination_address}\n"
                            f"{distance_info}\n"
                            f"💬 Коментар: {order.comment or '—'}",
                            reply_markup=kb
                        )
                        
                        await message.answer(
                            f"✅ Знайдено водія!\n"
                            f"Очікуйте підтвердження..."
                        )
                    except Exception as e:
                        await message.answer(
                            f"⚠️ Не вдалося надіслати повідомлення водію.\n"
                            f"Очікуйте, ми знайдемо іншого водія."
                        )
                else:
                    await message.answer("⚠️ Всі водії зайняті. Очікуйте, будь ласка...")
            else:
                await message.answer(
                    "⚠️ На жаль, зараз немає вільних водіїв.\n"
                    "Спробуйте пізніше або зв'яжіться з підтримкою."
                )
        else:
            await message.answer(
                "⚠️ Для автоматичного пошуку водія надайте геолокацію.\n"
                "Адміністратор обробить ваше замовлення вручну."
            )

    @router.message(OrderStates.confirm)
    async def confirm_unknown(message: Message, state: FSMContext) -> None:
        await message.answer("Будь ласка, натисніть 'Підтвердити' або 'Скасувати'.")

    @router.message(Command("orders"))
    async def list_recent_orders(message: Message) -> None:
        if not message.from_user or message.from_user.id not in set(config.bot.admin_ids):
            return
        orders = await fetch_recent_orders(config.database_path, limit=5)
        if not orders:
            await message.answer("Замовлень поки немає.")
            return
        lines = []
        for o in orders:
            lines.append(
                "\n".join([
                    f"№{o.id} від {o.created_at.strftime('%Y-%m-%d %H:%M')}",
                    f"Клієнт: {o.name} ({o.phone})",
                    f"Маршрут: {o.pickup_address} → {o.destination_address}",
                    f"Коментар: {o.comment or '—'}",
                ])
            )
        await message.answer("\n\n".join(lines))

    return router
