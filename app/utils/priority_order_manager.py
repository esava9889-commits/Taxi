"""Менеджер пріоритетних замовлень"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

# Словник для зберігання активних таймерів пріоритетних замовлень
# order_id -> task
_priority_timers: dict[int, asyncio.Task] = {}


class PriorityOrderManager:
    """Менеджер для роботи з пріоритетними замовленнями"""
    
    @staticmethod
    async def send_to_priority_drivers(
        bot: Bot,
        order_id: int,
        drivers: List,  # List[Driver]
        order_details: dict,
        db_path: str,
        city_group_id: int
    ) -> bool:
        """
        Відправити замовлення пріоритетним водіям
        
        Returns:
            True якщо замовлення відправлено пріоритетним водіям
            False якщо немає пріоритетних водіїв
        """
        from app.storage.db import Driver
        
        # Відфільтрувати водіїв з priority > 0
        priority_drivers = [d for d in drivers if hasattr(d, 'priority') and d.priority > 0]
        
        if not priority_drivers:
            logger.info(f"📢 Замовлення #{order_id}: немає пріоритетних водіїв, відправка в групу")
            return False
        
        logger.info(f"⭐ Замовлення #{order_id}: знайдено {len(priority_drivers)} пріоритетних водіїв")
        
        # Сортувати за priority (DESC)
        priority_drivers.sort(key=lambda d: d.priority, reverse=True)
        
        # Взяти топ-5 пріоритетних водіїв
        top_drivers = priority_drivers[:5]
        
        # Створити клавіатуру для водіїв
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="✅ Прийняти замовлення",
                    callback_data=f"accept_order:{order_id}"
                )]
            ]
        )
        
        # Сформувати повідомлення
        message_text = _build_priority_message(order_id, order_details)
        
        # Відправити кожному пріоритетному водію
        sent_count = 0
        for driver in top_drivers:
            try:
                await bot.send_message(
                    chat_id=driver.tg_user_id,
                    text=message_text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
                sent_count += 1
                logger.info(f"📨 Замовлення #{order_id} відправлено пріоритетному водію {driver.full_name} (ID: {driver.id})")
            except Exception as e:
                logger.error(f"❌ Помилка відправки водію {driver.id}: {e}")
        
        if sent_count > 0:
            # Запустити таймер на 1 хвилину
            await PriorityOrderManager.start_priority_timer(
                bot, order_id, db_path, city_group_id, order_details
            )
            logger.info(f"⏰ Таймер запущено для замовлення #{order_id} на 60 секунд")
            return True
        else:
            logger.warning(f"⚠️ Не вдалося відправити замовлення #{order_id} жодному водію")
            return False
    
    @staticmethod
    async def start_priority_timer(
        bot: Bot,
        order_id: int,
        db_path: str,
        city_group_id: int,
        order_details: dict
    ):
        """Запустити таймер на 1 хвилину для пріоритетного замовлення"""
        
        # Скасувати попередній таймер якщо є
        if order_id in _priority_timers:
            _priority_timers[order_id].cancel()
        
        # Створити нову задачу
        task = asyncio.create_task(
            _priority_timeout_handler(bot, order_id, db_path, city_group_id, order_details)
        )
        _priority_timers[order_id] = task
    
    @staticmethod
    def cancel_priority_timer(order_id: int):
        """Скасувати таймер для замовлення (коли водій прийняв або відхилив)"""
        if order_id in _priority_timers:
            _priority_timers[order_id].cancel()
            _priority_timers.pop(order_id, None)  # Безпечне видалення
            logger.info(f"⏰ Таймер скасовано для замовлення #{order_id}")


async def _priority_timeout_handler(
    bot: Bot,
    order_id: int,
    db_path: str,
    city_group_id: int,
    order_details: dict
):
    """Обробник таймауту пріоритетного замовлення"""
    try:
        # Чекати 60 секунд
        await asyncio.sleep(60)
        
        # Перевірити статус замовлення
        from app.storage.db import get_order_by_id
        order = await get_order_by_id(db_path, order_id)
        
        if not order:
            logger.warning(f"⚠️ Замовлення #{order_id} не знайдено після таймауту")
            return
        
        # Якщо замовлення все ще pending - відправити в групу
        if order.status == "pending":
            logger.info(f"⏰ ТАЙМАУТ! Замовлення #{order_id} не прийнято пріоритетними водіями, відправка в групу")
            
            # Відправити в групу
            await _send_to_group(bot, order_id, city_group_id, order_details)
            
            # Повідомити пріоритетних водіїв що замовлення більше недоступне
            await _notify_priority_drivers_timeout(bot, order_id, order_details.get('priority_driver_ids', []))
        else:
            logger.info(f"✅ Замовлення #{order_id} вже має статус {order.status}, таймер завершено")
        
        # Видалити таймер зі словника (безпечно)
        _priority_timers.pop(order_id, None)
            
    except asyncio.CancelledError:
        logger.info(f"⏰ Таймер для замовлення #{order_id} скасовано (водій прийняв/відхилив)")
    except Exception as e:
        logger.error(f"❌ Помилка в таймері замовлення #{order_id}: {e}")


async def _send_to_group(bot: Bot, order_id: int, city_group_id: int, order_details: dict):
    """Відправити замовлення в групу водіїв"""
    try:
        from app.handlers.driver_panel import clean_address
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="✅ Прийняти замовлення",
                    callback_data=f"accept_order:{order_id}"
                )]
            ]
        )
        
        # ⭐ ПЕРЕТВОРИТИ КООРДИНАТИ В АДРЕСИ (для пріоритетних водіїв)
        from app.utils.maps import reverse_geocode
        
        pickup_display = order_details.get('pickup', '')
        destination_display = order_details.get('destination', '')
        
        pickup_lat = order_details.get('pickup_lat')
        pickup_lon = order_details.get('pickup_lon')
        dest_lat = order_details.get('dest_lat')
        dest_lon = order_details.get('dest_lon')
        
        # Якщо є координати - спробувати геокодувати в адресу
        if pickup_lat and pickup_lon:
            # Перевірити чи це координати
            if '.' in str(pickup_display) and any(char.isdigit() for char in str(pickup_display)):
                logger.info(f"🔄 [PRIORITY] Координати в pickup, геокодую: {pickup_display}")
                try:
                    readable_address = await reverse_geocode("", float(pickup_lat), float(pickup_lon))
                    if readable_address:
                        pickup_display = readable_address
                        logger.info(f"✅ [PRIORITY] Pickup геокодовано: {pickup_display}")
                except Exception as e:
                    logger.error(f"❌ [PRIORITY] Помилка геокодування pickup: {e}")
        
        if dest_lat and dest_lon:
            # Перевірити чи це координати
            if '.' in str(destination_display) and any(char.isdigit() for char in str(destination_display)):
                logger.info(f"🔄 [PRIORITY] Координати в destination, геокодую: {destination_display}")
                try:
                    readable_address = await reverse_geocode("", float(dest_lat), float(dest_lon))
                    if readable_address:
                        destination_display = readable_address
                        logger.info(f"✅ [PRIORITY] Destination геокодовано: {destination_display}")
                except Exception as e:
                    logger.error(f"❌ [PRIORITY] Помилка геокодування destination: {e}")
        
        # Очистити адреси від Plus Codes
        clean_pickup = clean_address(pickup_display)
        clean_destination = clean_address(destination_display)
        
        # Створити посилання на маршрут
        route_link = ""
        
        if pickup_lat and pickup_lon and dest_lat and dest_lon:
            route_link = (
                f"\n🗺️ <a href='https://www.google.com/maps/dir/?api=1"
                f"&origin={pickup_lat},{pickup_lon}"
                f"&destination={dest_lat},{dest_lon}"
                f"&travelmode=driving'>Відкрити маршрут на Google Maps</a>"
            )
        
        # Форматувати дистанцію
        distance_info = ""
        if order_details.get('distance_m'):
            km = order_details.get('distance_m') / 1000.0
            minutes = (order_details.get('duration_s') or 0) / 60.0
            distance_info = f"📏 Відстань: {km:.1f} км (~{int(minutes)} хв)\n"
        
        # Вартість
        fare_text = ""
        if order_details.get('estimated_fare'):
            fare_text = f"💰 <b>ВАРТІСТЬ: {int(order_details['estimated_fare'])} грн</b> 💰\n"
        
        # Клас авто
        car_class = order_details.get('car_class', 'economy')
        from app.handlers.car_classes import get_car_class_name
        car_class_name = get_car_class_name(car_class)
        
        # Маскування телефону
        from app.handlers.order import mask_phone_number
        masked_phone = mask_phone_number(order_details.get('phone', ''), show_last_digits=2)
        
        group_message = (
            f"🚖 <b>ЗАМОВЛЕННЯ #{order_id}</b>\n\n"
            f"👤 Клієнт: {order_details.get('name', 'Не вказано')}\n"
            f"📱 Телефон: {masked_phone}\n\n"
            f"📍 Звідки: {clean_pickup}\n"
            f"📍 Куди: {clean_destination}\n\n"
            f"{distance_info}"
            f"🚗 Клас авто: {car_class_name}\n"
            f"{fare_text}\n"
            f"💬 Коментар: {order_details.get('comment', 'Немає')}\n"
            f"{route_link}"
        )
        
        sent_msg = await bot.send_message(
            chat_id=city_group_id,
            text=group_message,
            reply_markup=kb,
            parse_mode="HTML"
        )
        
        # Оновити group_message_id в БД
        from app.storage.db_connection import db_manager
        async with db_manager.connect(order_details.get('db_path')) as db:
            await db.execute(
                "UPDATE orders SET group_message_id = ? WHERE id = ?",
                (sent_msg.message_id, order_id)
            )
            await db.commit()
        
        logger.info(f"📢 Замовлення #{order_id} відправлено в групу {city_group_id}")
        
    except Exception as e:
        logger.error(f"❌ Помилка відправки замовлення #{order_id} в групу: {e}")


async def _notify_priority_drivers_timeout(bot: Bot, order_id: int, driver_ids: List[int]):
    """Повідомити пріоритетних водіїв що замовлення більше недоступне"""
    for driver_id in driver_ids:
        try:
            await bot.send_message(
                chat_id=driver_id,
                text=f"⏰ Замовлення #{order_id} більше недоступне (час очікування минув)",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.debug(f"Не вдалося повідомити водія {driver_id}: {e}")


def _build_priority_message(order_id: int, order_details: dict) -> str:
    """Створити повідомлення для пріоритетних водіїв"""
    from app.handlers.driver_panel import clean_address
    from app.handlers.car_classes import get_car_class_name
    
    # ⚠️ УВАГА: ця функція НЕ може використовувати async reverse_geocode
    # Тому адреси мають бути вже геокодовані до цього моменту
    # Якщо тут координати - вони будуть показані як є
    
    clean_pickup = clean_address(order_details.get('pickup', ''))
    clean_destination = clean_address(order_details.get('destination', ''))
    
    # Дистанція
    distance_info = ""
    if order_details.get('distance_m'):
        km = order_details.get('distance_m') / 1000.0
        minutes = (order_details.get('duration_s') or 0) / 60.0
        distance_info = f"📏 Відстань: {km:.1f} км (~{int(minutes)} хв)\n"
    
    # Вартість
    fare_text = ""
    if order_details.get('estimated_fare'):
        fare_text = f"💰 <b>ВАРТІСТЬ: {int(order_details['estimated_fare'])} грн</b> 💰\n"
    
    # Клас авто
    car_class = order_details.get('car_class', 'economy')
    car_class_name = get_car_class_name(car_class)
    
    # Посилання на маршрут
    route_link = ""
    pickup_lat = order_details.get('pickup_lat')
    pickup_lon = order_details.get('pickup_lon')
    dest_lat = order_details.get('dest_lat')
    dest_lon = order_details.get('dest_lon')
    
    if pickup_lat and pickup_lon and dest_lat and dest_lon:
        route_link = (
            f"\n🗺️ <a href='https://www.google.com/maps/dir/?api=1"
            f"&origin={pickup_lat},{pickup_lon}"
            f"&destination={dest_lat},{dest_lon}"
            f"&travelmode=driving'>Відкрити маршрут на Google Maps</a>"
        )
    
    return (
        f"⭐ <b>ПРІОРИТЕТНЕ ЗАМОВЛЕННЯ #{order_id}</b> ⭐\n\n"
        f"<i>У вас є 60 секунд для прийняття рішення!</i>\n\n"
        f"👤 Клієнт: {order_details.get('name', 'Не вказано')}\n"
        f"📱 Телефон: {order_details.get('phone', 'Не вказано')}\n\n"
        f"📍 Звідки: {clean_pickup}\n"
        f"📍 Куди: {clean_destination}\n\n"
        f"{distance_info}"
        f"🚗 Клас авто: {car_class_name}\n"
        f"{fare_text}\n"
        f"💬 Коментар: {order_details.get('comment', 'Немає')}\n"
        f"{route_link}\n\n"
        f"⏰ Якщо ви не прийміте або не відхилите замовлення протягом 1 хвилини,\n"
        f"воно автоматично з'явиться в загальній групі."
    )
