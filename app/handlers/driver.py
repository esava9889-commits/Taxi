from __future__ import annotations

from datetime import datetime, timezone

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

from app.config.config import AppConfig
from app.storage.db import (
    Driver,
    create_driver_application,
    fetch_pending_drivers,
    get_driver_by_tg_user_id,
    get_driver_by_id,
    update_driver_status,
)
from app.handlers.start import DRIVER_TEXT


CANCEL_TEXT = "Скасувати"


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


class DriverRegStates(StatesGroup):
    name = State()
    phone = State()
    car_make = State()
    car_model = State()
    car_plate = State()
    license_photo = State()
    confirm = State()


def create_router(config: AppConfig) -> Router:
    router = Router(name="driver")

    # Public: entrypoint for driver registration
    @router.message(F.text == DRIVER_TEXT)
    @router.message(Command("register_driver"))
    async def start_driver_registration(message: Message, state: FSMContext) -> None:
        await state.set_state(DriverRegStates.name)
        await message.answer(
            "Введіть ПІБ водія:", reply_markup=cancel_keyboard()
        )

    @router.message(F.text == CANCEL_TEXT)
    async def cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Скасовано.", reply_markup=ReplyKeyboardRemove())

    @router.message(DriverRegStates.name)
    async def take_name(message: Message, state: FSMContext) -> None:
        full_name = message.text.strip()
        if len(full_name) < 3:
            await message.answer("Введіть коректне ім'я.")
            return
        await state.update_data(full_name=full_name)
        await state.set_state(DriverRegStates.phone)
        await message.answer("Вкажіть номер телефону:", reply_markup=cancel_keyboard())

    @router.message(DriverRegStates.phone)
    async def take_phone(message: Message, state: FSMContext) -> None:
        phone = message.text.strip()
        if len(phone) < 7:
            await message.answer("Введіть коректний номер телефону.")
            return
        await state.update_data(phone=phone)
        await state.set_state(DriverRegStates.car_make)
        await message.answer("Марка авто:", reply_markup=cancel_keyboard())

    @router.message(DriverRegStates.car_make)
    async def take_car_make(message: Message, state: FSMContext) -> None:
        car_make = message.text.strip()
        await state.update_data(car_make=car_make)
        await state.set_state(DriverRegStates.car_model)
        await message.answer("Модель авто:", reply_markup=cancel_keyboard())

    @router.message(DriverRegStates.car_model)
    async def take_car_model(message: Message, state: FSMContext) -> None:
        car_model = message.text.strip()
        await state.update_data(car_model=car_model)
        await state.set_state(DriverRegStates.car_plate)
        await message.answer("Номерний знак авто:", reply_markup=cancel_keyboard())

    @router.message(DriverRegStates.car_plate)
    async def take_car_plate(message: Message, state: FSMContext) -> None:
        car_plate = message.text.strip().upper()
        await state.update_data(car_plate=car_plate)
        await state.set_state(DriverRegStates.license_photo)
        await message.answer(
            "Надішліть фото посвідчення водія (можна пропустити командою /skip)",
            reply_markup=cancel_keyboard(),
        )

    @router.message(Command("skip"), DriverRegStates.license_photo)
    async def skip_license(message: Message, state: FSMContext) -> None:
        await state.update_data(license_photo_file_id=None)
        await finalize_application(message, state)

    @router.message(DriverRegStates.license_photo, F.photo)
    async def take_license_photo(message: Message, state: FSMContext) -> None:
        file_id = message.photo[-1].file_id  # biggest size
        await state.update_data(license_photo_file_id=file_id)
        await finalize_application(message, state)

    async def finalize_application(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        driver = Driver(
            id=None,
            tg_user_id=message.from_user.id if message.from_user else 0,
            full_name=str(data.get("full_name")),
            phone=str(data.get("phone")),
            car_make=str(data.get("car_make")),
            car_model=str(data.get("car_model")),
            car_plate=str(data.get("car_plate")),
            license_photo_file_id=(data.get("license_photo_file_id") or None),
            status="pending",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        driver_id = await create_driver_application(config.database_path, driver)
        await state.clear()
        # Notify admin(s)
        for admin_id in set(config.bot.admin_ids):
            try:
                await message.bot.send_message(
                    admin_id,
                    (
                        "Нова заявка водія:\n"
                        f"ID заявки: {driver_id}\n"
                        f"ПІБ: {driver.full_name}\n"
                        f"Телефон: {driver.phone}\n"
                        f"Авто: {driver.car_make} {driver.car_model} ({driver.car_plate})\n"
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Підтвердити",
                                    callback_data=f"drv:approve:{driver_id}",
                                ),
                                InlineKeyboardButton(
                                    text="Відхилити",
                                    callback_data=f"drv:reject:{driver_id}",
                                ),
                            ]
                        ]
                    ),
                )
                if driver.license_photo_file_id:
                    await message.bot.send_photo(
                        admin_id,
                        driver.license_photo_file_id,
                        caption=f"Посвідчення водія (заявка #{driver_id})",
                    )
            except Exception:
                # Ignore delivery errors to some admins
                pass

        await message.answer(
            "Заявку відправлено на модерацію. Очікуйте підтвердження.",
            reply_markup=ReplyKeyboardRemove(),
        )

    # Admin moderation callbacks
    @router.callback_query(F.data.startswith("drv:"))
    async def on_driver_callback(call: CallbackQuery) -> None:
        data = (call.data or "").split(":")
        if len(data) != 3:
            await call.answer("Невірні дані", show_alert=True)
            return
        _, action, sid = data
        try:
            driver_id = int(sid)
        except ValueError:
            await call.answer("Помилка ID", show_alert=True)
            return
        # Only admins can moderate
        if not call.from_user or call.from_user.id not in set(config.bot.admin_ids):
            await call.answer("Недостатньо прав", show_alert=True)
            return

        if action == "approve":
            await update_driver_status(config.database_path, driver_id, "approved")
            await call.answer("Водія підтверджено")
            drv = await get_driver_by_id(config.database_path, driver_id)
            if drv:
                try:
                    await call.message.bot.send_message(
                        drv.tg_user_id,
                        "Вашу заявку водія підтверджено. Ви активні!",
                    )
                except Exception:
                    pass
        elif action == "reject":
            await update_driver_status(config.database_path, driver_id, "rejected")
            await call.answer("Заявку відхилено")
            drv = await get_driver_by_id(config.database_path, driver_id)
            if drv:
                try:
                    await call.message.bot.send_message(
                        drv.tg_user_id,
                        "Вашу заявку водія відхилено. Зв'яжіться з підтримкою.",
                    )
                except Exception:
                    pass
        else:
            await call.answer("Невірна дія", show_alert=True)
            return

    # Helper: driver status check
    @router.message(Command("my_driver_status"))
    async def my_driver_status(message: Message) -> None:
        if not message.from_user:
            return
        drv = await get_driver_by_tg_user_id(
            config.database_path, message.from_user.id
        )
        if not drv:
            await message.answer("Заявок не знайдено.")
            return
        await message.answer(
            f"Статус заявки: {drv.status}\nАвто: {drv.car_make} {drv.car_model} ({drv.car_plate})"
        )

    # Admin commands
    @router.message(Command("pending_drivers"))
    async def list_pending_drivers(message: Message) -> None:
        if not message.from_user or message.from_user.id not in set(config.bot.admin_ids):
            return
        drivers = await fetch_pending_drivers(config.database_path, limit=20)
        if not drivers:
            await message.answer("Немає заявок, що очікують.")
            return
        for d in drivers:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Підтвердити", callback_data=f"drv:approve:{d.id}"),
                        InlineKeyboardButton(text="Відхилити", callback_data=f"drv:reject:{d.id}"),
                    ]
                ]
            )
            await message.answer(
                (
                    f"#{d.id} {d.full_name} ({d.phone})\n"
                    f"Авто: {d.car_make} {d.car_model} ({d.car_plate})\n"
                    f"Статус: {d.status}"
                ),
                reply_markup=kb,
            )

    @router.message(Command("approve_driver"))
    async def approve_driver_cmd(message: Message) -> None:
        if not message.from_user or message.from_user.id not in set(config.bot.admin_ids):
            return
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer("Використання: /approve_driver <id>")
            return
        driver_id = int(parts[1])
        await update_driver_status(config.database_path, driver_id, "approved")
        await message.answer(f"Водія #{driver_id} підтверджено.")
        drv = await get_driver_by_id(config.database_path, driver_id)
        if drv:
            try:
                await message.bot.send_message(drv.tg_user_id, "Вашу заявку водія підтверджено. Ви активні!")
            except Exception:
                pass

    @router.message(Command("reject_driver"))
    async def reject_driver_cmd(message: Message) -> None:
        if not message.from_user or message.from_user.id not in set(config.bot.admin_ids):
            return
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer("Використання: /reject_driver <id>")
            return
        driver_id = int(parts[1])
        await update_driver_status(config.database_path, driver_id, "rejected")
        await message.answer(f"Заявку #{driver_id} відхилено.")
        drv = await get_driver_by_id(config.database_path, driver_id)
        if drv:
            try:
                await message.bot.send_message(drv.tg_user_id, "Вашу заявку водія відхилено. Зв'яжіться з підтримкою.")
            except Exception:
                pass

    return router
