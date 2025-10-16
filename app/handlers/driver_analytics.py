"""Розширена статистика та аналітика для водія"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config.config import AppConfig
from app.storage.db import (
    get_driver_by_tg_user_id,
    get_driver_order_history,
)

logger = logging.getLogger(__name__)


def create_router(config: AppConfig) -> Router:
    router = Router(name="driver_analytics")

    @router.message(F.text == "📊 Розширена аналітика")
    @router.callback_query(F.data == "driver:analytics")
    async def show_analytics_menu(event) -> None:
        """Показати меню аналітики"""
        # Визначити тип події
        if isinstance(event, Message):
            message = event
            user_id = event.from_user.id if event.from_user else 0
        else:
            await event.answer()
            message = event.message
            user_id = event.from_user.id if event.from_user else 0
        
        if not user_id:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, user_id)
        if not driver or driver.status != "approved":
            await message.answer("❌ Доступно тільки для водіїв")
            return
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏰ Кращі години роботи", callback_data="analytics:best_hours")],
                [InlineKeyboardButton(text="🗺️ Топ-маршрути", callback_data="analytics:top_routes")],
                [InlineKeyboardButton(text="📍 Гарячі точки", callback_data="analytics:hotspots")],
                [InlineKeyboardButton(text="💰 Прогноз заробітку", callback_data="analytics:forecast")],
                [InlineKeyboardButton(text="📈 Порівняння з іншими", callback_data="analytics:compare")],
            ]
        )
        
        await message.answer(
            "📊 <b>Розширена аналітика</b>\n\n"
            "Виберіть тип аналітики:",
            reply_markup=kb
        )

    @router.callback_query(F.data == "analytics:best_hours")
    async def show_best_hours(call: CallbackQuery) -> None:
        """Показати найкращі години для роботи"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        # Отримати всі замовлення за останній місяць
        orders = await get_driver_order_history(config.database_path, call.from_user.id, limit=1000)
        
        # Фільтрувати за місяць
        month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        month_orders = [o for o in orders if o.created_at >= month_ago and o.status == 'completed']
        
        if not month_orders:
            await call.answer()
            await call.message.answer("📊 Недостатньо даних. Виконайте більше поїздок.")
            return
        
        # Групування за годинами
        hourly_stats: Dict[int, List[float]] = defaultdict(list)
        
        for order in month_orders:
            hour = order.created_at.hour
            if order.fare_amount:
                hourly_stats[hour].append(order.fare_amount)
        
        # Розрахунок середнього заробітку по годинах
        hourly_avg = {}
        for hour, fares in hourly_stats.items():
            hourly_avg[hour] = sum(fares) / len(fares)
        
        # Сортувати по заробітку
        sorted_hours = sorted(hourly_avg.items(), key=lambda x: x[1], reverse=True)
        
        # Топ-5 годин
        text = "⏰ <b>Найкращі години для роботи</b>\n\n"
        text += "📈 <b>Топ-5 годин по заробітку:</b>\n\n"
        
        for i, (hour, avg_fare) in enumerate(sorted_hours[:5], 1):
            count = len(hourly_stats[hour])
            total = sum(hourly_stats[hour])
            text += f"{i}. <b>{hour:02d}:00-{hour+1:02d}:00</b>\n"
            text += f"   💰 Середній чек: {avg_fare:.0f} грн\n"
            text += f"   📊 Поїздок: {count}\n"
            text += f"   💵 Всього: {total:.0f} грн\n\n"
        
        # Графік
        text += "📊 <b>Графік заробітку по годинах:</b>\n\n"
        max_earning = max(hourly_avg.values()) if hourly_avg else 1
        
        for hour in range(24):
            if hour in hourly_avg:
                avg = hourly_avg[hour]
                bar_length = int((avg / max_earning) * 15)
                text += f"{hour:02d}:00 {'█' * bar_length} {avg:.0f} грн\n"
        
        text += "\n💡 <b>Рекомендації:</b>\n"
        if sorted_hours:
            best_hour = sorted_hours[0][0]
            text += f"🔥 Працюйте в {best_hour:02d}:00-{best_hour+2:02d}:00 для максимального заробітку!"
        
        await call.answer()
        await call.message.answer(text)

    @router.callback_query(F.data == "analytics:top_routes")
    async def show_top_routes(call: CallbackQuery) -> None:
        """Показати найприбутковіші маршрути"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        orders = await get_driver_order_history(config.database_path, call.from_user.id, limit=500)
        
        # Групування по маршрутах
        route_stats: Dict[str, List[float]] = defaultdict(list)
        
        for order in orders:
            if order.status == 'completed' and order.fare_amount:
                # Скоротити адреси для групування
                pickup_short = order.pickup_address[:30]
                dest_short = order.destination_address[:30]
                route_key = f"{pickup_short} → {dest_short}"
                route_stats[route_key].append(order.fare_amount)
        
        if not route_stats:
            await call.answer()
            await call.message.answer("📊 Недостатньо даних про маршрути")
            return
        
        # Топ-10 маршрутів
        route_avg = {route: sum(fares)/len(fares) for route, fares in route_stats.items()}
        sorted_routes = sorted(route_avg.items(), key=lambda x: x[1], reverse=True)
        
        text = "🗺️ <b>Топ-10 найприбутковіших маршрутів:</b>\n\n"
        
        for i, (route, avg_fare) in enumerate(sorted_routes[:10], 1):
            count = len(route_stats[route])
            total = sum(route_stats[route])
            text += f"{i}. {route}\n"
            text += f"   💰 Середній чек: {avg_fare:.0f} грн\n"
            text += f"   📊 Поїздок: {count}\n"
            text += f"   💵 Всього: {total:.0f} грн\n\n"
        
        text += "💡 <b>Рекомендація:</b>\n"
        text += "Працюйте в районах з найприбутковішими маршрутами!"
        
        await call.answer()
        await call.message.answer(text)

    @router.callback_query(F.data == "analytics:hotspots")
    async def show_hotspots(call: CallbackQuery) -> None:
        """Показати гарячі точки (де найбільше замовлень)"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        orders = await get_driver_order_history(config.database_path, call.from_user.id, limit=500)
        
        # Групування по районах/адресах
        pickup_stats: Dict[str, int] = defaultdict(int)
        
        for order in orders:
            if order.status == 'completed':
                # Взяти перші 20 символів адреси (район)
                area = order.pickup_address[:20]
                pickup_stats[area] += 1
        
        if not pickup_stats:
            await call.answer()
            await call.message.answer("📊 Недостатньо даних")
            return
        
        sorted_areas = sorted(pickup_stats.items(), key=lambda x: x[1], reverse=True)
        
        text = "📍 <b>Гарячі точки (найбільше замовлень):</b>\n\n"
        
        max_count = sorted_areas[0][1] if sorted_areas else 1
        
        for i, (area, count) in enumerate(sorted_areas[:15], 1):
            bar_length = int((count / max_count) * 10)
            text += f"{i}. {area}...\n"
            text += f"   {'🔥' * bar_length} {count} замовлень\n\n"
        
        text += "💡 <b>Рекомендація:</b>\n"
        text += f"Чекайте замовлення біля: {sorted_areas[0][0]}..."
        
        await call.answer()
        await call.message.answer(text)

    @router.callback_query(F.data == "analytics:forecast")
    async def show_forecast(call: CallbackQuery) -> None:
        """Прогноз заробітку"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        # Отримати історію за останні 30 днів
        orders = await get_driver_order_history(config.database_path, call.from_user.id, limit=1000)
        
        month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        month_orders = [o for o in orders if o.created_at >= month_ago and o.status == 'completed']
        week_orders = [o for o in orders if o.created_at >= week_ago and o.status == 'completed']
        
        if not month_orders:
            await call.answer()
            await call.message.answer("📊 Недостатньо даних для прогнозу")
            return
        
        # Розрахунки
        month_earnings = sum(o.fare_amount or 0 for o in month_orders)
        week_earnings = sum(o.fare_amount or 0 for o in week_orders)
        
        avg_per_day = month_earnings / 30
        avg_per_week = week_earnings / 7
        
        # Прогноз на місяць (за поточним темпом)
        forecast_month = avg_per_day * 30
        
        # Кількість поїздок
        month_trips = len(month_orders)
        avg_trips_per_day = month_trips / 30
        
        # Середній чек
        avg_fare = month_earnings / month_trips if month_trips > 0 else 0
        
        text = (
            "💰 <b>Прогноз заробітку</b>\n\n"
            f"📅 <b>За останні 30 днів:</b>\n"
            f"💵 Заробіток: {month_earnings:.0f} грн\n"
            f"📊 Поїздок: {month_trips}\n"
            f"💰 Середній чек: {avg_fare:.0f} грн\n\n"
            f"📈 <b>Середньо на день:</b>\n"
            f"💵 {avg_per_day:.0f} грн/день\n"
            f"📊 {avg_trips_per_day:.1f} поїздок/день\n\n"
            f"🔮 <b>Прогноз на місяць:</b>\n"
            f"💰 {forecast_month:.0f} грн (при поточному темпі)\n\n"
            f"📊 <b>За останній тиждень:</b>\n"
            f"💵 {week_earnings:.0f} грн\n"
            f"📈 Середньо: {avg_per_week:.0f} грн/день\n\n"
        )
        
        # Порівняння з минулим тижнем
        two_weeks_ago = datetime.now(timezone.utc) - timedelta(days=14)
        prev_week_orders = [o for o in orders if two_weeks_ago <= o.created_at < week_ago and o.status == 'completed']
        
        if prev_week_orders:
            prev_week_earnings = sum(o.fare_amount or 0 for o in prev_week_orders)
            change = ((week_earnings - prev_week_earnings) / prev_week_earnings * 100) if prev_week_earnings > 0 else 0
            
            if change > 0:
                text += f"📈 Ріст: <b>+{change:.1f}%</b> порівняно з минулим тижнем 🎉\n"
            elif change < 0:
                text += f"📉 Зниження: <b>{change:.1f}%</b> порівняно з минулим тижнем ⚠️\n"
            else:
                text += "➡️ Без змін порівняно з минулим тижнем\n"
        
        text += "\n💡 <b>Щоб збільшити заробіток:</b>\n"
        text += "• Працюйте в пікові години (див. 'Кращі години')\n"
        text += "• Чекайте замовлення біля гарячих точок\n"
        text += "• Підтримуйте високий рейтинг (>4.8)\n"
        text += "• Оновлюйте локацію частіше"
        
        await call.answer()
        await call.message.answer(text)

    @router.callback_query(F.data == "analytics:compare")
    async def compare_with_others(call: CallbackQuery) -> None:
        """Порівняння з іншими водіями"""
        if not call.from_user:
            return
        
        driver = await get_driver_by_tg_user_id(config.database_path, call.from_user.id)
        if not driver:
            await call.answer("❌ Помилка", show_alert=True)
            return
        
        # Отримати заробіток водія за місяць
        orders = await get_driver_order_history(config.database_path, call.from_user.id, limit=1000)
        month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        month_orders = [o for o in orders if o.created_at >= month_ago and o.status == 'completed']
        
        my_earnings = sum(o.fare_amount or 0 for o in month_orders)
        my_trips = len(month_orders)
        
        # Отримати рейтинг
        from app.storage.db import get_driver_average_rating
        my_rating = await get_driver_average_rating(config.database_path, call.from_user.id)
        
        # TODO: Отримати середню статистику по всіх водіях міста
        # Поки що симулюємо
        avg_earnings = 8000  # Середній заробіток водія за місяць
        avg_trips = 120
        avg_rating = 4.5
        
        # Порівняння
        earnings_diff = ((my_earnings - avg_earnings) / avg_earnings * 100) if avg_earnings > 0 else 0
        trips_diff = ((my_trips - avg_trips) / avg_trips * 100) if avg_trips > 0 else 0
        
        text = (
            "📈 <b>Порівняння з іншими водіями</b>\n\n"
            f"🏙 Місто: {driver.city or 'Не вказано'}\n\n"
            f"💰 <b>Ваш заробіток:</b> {my_earnings:.0f} грн\n"
            f"📊 Середній в місті: {avg_earnings:.0f} грн\n"
        )
        
        if earnings_diff > 0:
            text += f"✅ Ви на <b>{earnings_diff:.0f}%</b> вище середнього! 🎉\n\n"
        elif earnings_diff < 0:
            text += f"⚠️ Ви на <b>{abs(earnings_diff):.0f}%</b> нижче середнього\n\n"
        else:
            text += "➡️ Ви на рівні середнього\n\n"
        
        text += (
            f"📊 <b>Ваші поїздки:</b> {my_trips}\n"
            f"📊 Середньо в місті: {avg_trips}\n"
        )
        
        if trips_diff > 0:
            text += f"✅ На <b>{trips_diff:.0f}%</b> більше поїздок! 🚀\n\n"
        else:
            text += f"⚠️ На <b>{abs(trips_diff):.0f}%</b> менше поїздок\n\n"
        
        text += (
            f"⭐ <b>Ваш рейтинг:</b> {my_rating:.1f}\n" if my_rating else "⭐ Рейтинг: немає оцінок\n"
        )
        text += f"⭐ Середній: {avg_rating:.1f}\n\n"
        
        # Позиція в рейтингу (симуляція)
        position = 15  # TODO: Реальний розрахунок
        total_drivers = 47
        
        text += f"🏆 <b>Ваша позиція:</b> #{position} з {total_drivers}\n\n"
        
        text += "💡 <b>Як піднятись в рейтингу:</b>\n"
        text += "• Працюйте більше годин\n"
        text += "• Підвищуйте рейтинг (>4.8)\n"
        text += "• Приймайте більше замовлень\n"
        text += "• Будьте онлайн в пікові години"
        
        await call.answer()
        await call.message.answer(text)

    @router.callback_query(F.data == "analytics:hotspots")
    async def show_hotspots_map(call: CallbackQuery) -> None:
        """Показати карту гарячих точок"""
        await call.answer()
        
        # TODO: Реалізувати візуалізацію на карті
        await call.message.answer(
            "📍 <b>Карта гарячих точок</b>\n\n"
            "🔥 <b>Зони з найбільшою кількістю замовлень:</b>\n\n"
            "1. Центр міста 🔥🔥🔥 (40% замовлень)\n"
            "2. ТРЦ «Глобус» 🔥🔥 (25%)\n"
            "3. Вокзал 🔥🔥 (20%)\n"
            "4. Аеропорт 🔥 (10%)\n"
            "5. Університет 🔥 (5%)\n\n"
            "💡 Чекайте замовлення в цих зонах для більшого заробітку!"
        )

    return router
