from __future__ import annotations

from typing import Optional, Tuple
import aiohttp
import asyncio
import logging

logger = logging.getLogger(__name__)

# Затримка між запитами до Nominatim (обов'язкова згідно з правилами)
_last_nominatim_request = 0
NOMINATIM_DELAY = 1.0  # 1 секунда між запитами


async def _wait_for_nominatim():
    """Затримка між запитами до Nominatim (1 запит/сек)"""
    global _last_nominatim_request
    import time
    
    now = time.time()
    time_since_last = now - _last_nominatim_request
    
    if time_since_last < NOMINATIM_DELAY:
        await asyncio.sleep(NOMINATIM_DELAY - time_since_last)
    
    _last_nominatim_request = time.time()


async def get_distance_and_duration(
    api_key: str,  # Не використовується, залишено для сумісності
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float
) -> Optional[Tuple[int, int]]:
    """
    Розрахувати відстань та час через OSRM (Open Source Routing Machine)
    БЕЗКОШТОВНО, без API ключа!
    
    Returns (distance_meters, duration_seconds) or None
    """
    try:
        # OSRM API - безкоштовний, публічний
        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
            f"?overview=false&steps=false"
        )
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    logger.error(f"OSRM API HTTP error: {resp.status}")
                    return None
                data = await resp.json()
        
        if data.get("code") != "Ok":
            logger.warning(f"⚠️ OSRM API код: {data.get('code')}")
            return None
        
        routes = data.get("routes", [])
        if not routes:
            logger.warning("⚠️ OSRM API: порожні маршрути")
            return None
        
        route = routes[0]
        distance = route.get("distance")  # в метрах
        duration = route.get("duration")  # в секундах
        
        if distance is None or duration is None:
            logger.warning("⚠️ OSRM API: немає distance/duration")
            return None
        
        logger.info(f"✅ OSRM: {distance:.0f}м, {duration:.0f}сек")
        return (int(distance), int(duration))
        
    except Exception as e:
        logger.error(f"❌ OSRM API exception: {type(e).__name__}: {str(e)}")
        return None


async def geocode_address(api_key: str, address: str) -> Optional[Tuple[float, float]]:
    """
    Конвертувати адресу в координати через Nominatim (OpenStreetMap)
    БЕЗКОШТОВНО, без API ключа!
    
    Returns (lat, lon) or None
    """
    import urllib.parse
    
    # Додаємо країну якщо не вказана
    if "україна" not in address.lower() and "ukraine" not in address.lower():
        address = f"{address}, Україна"
    
    # Затримка для Nominatim
    await _wait_for_nominatim()
    
    encoded_address = urllib.parse.quote(address)
    url = (
        f"https://nominatim.openstreetmap.org/search?"
        f"q={encoded_address}&format=json&limit=1&addressdetails=1"
    )
    
    headers = {
        'User-Agent': 'TaxiBot/1.0 (Ukrainian Taxi Service)'  # Обов'язково!
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    logger.error(f"Nominatim Geocoding HTTP error: {resp.status}")
                    return None
                data = await resp.json()
        
        if not data or len(data) == 0:
            logger.warning(f"⚠️ Nominatim не знайшов адресу: {address}")
            return None
        
        result = data[0]
        lat = result.get("lat")
        lon = result.get("lon")
        
        if lat is None or lon is None:
            logger.warning(f"⚠️ Nominatim: немає координат в результаті")
            return None
        
        logger.info(f"✅ Nominatim geocoded: {address} → {lat},{lon}")
        return (float(lat), float(lon))
        
    except Exception as e:
        logger.error(f"❌ Nominatim Geocoding exception: {type(e).__name__}: {str(e)}")
        return None


async def reverse_geocode(api_key: str, lat: float, lon: float) -> Optional[str]:
    """
    Конвертувати координати в адресу через Nominatim (OpenStreetMap)
    БЕЗКОШТОВНО, без API ключа!
    
    Returns address string or None
    """
    # Затримка для Nominatim
    await _wait_for_nominatim()
    
    # Використовуємо HTTP замість HTTPS для обходу SSL проблем на Render
    url = (
        f"http://nominatim.openstreetmap.org/reverse?"
        f"lat={lat}&lon={lon}&format=json&addressdetails=1&accept-language=uk"
    )
    
    headers = {
        'User-Agent': 'TaxiBot/1.0 (Ukrainian Taxi Service)'  # Обов'язково!
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    logger.error(f"Nominatim Reverse Geocoding HTTP error: {resp.status}")
                    return None
                data = await resp.json()
        
        # Отримати адресу
        display_name = data.get("display_name")
        
        if not display_name:
            logger.warning("⚠️ Nominatim: порожня адреса")
            return None
        
        # Спробувати отримати структуровану адресу для кращого форматування
        address = data.get("address", {})
        
        # Сформувати адресу в українському форматі
        parts = []
        
        # Вулиця та номер будинку
        road = address.get("road")
        house_number = address.get("house_number")
        if road:
            if house_number:
                parts.append(f"{road}, {house_number}")
            else:
                parts.append(road)
        
        # Район/квартал
        suburb = address.get("suburb") or address.get("neighbourhood")
        if suburb and suburb not in parts:
            parts.append(suburb)
        
        # Місто
        city = (
            address.get("city") or 
            address.get("town") or 
            address.get("village") or
            address.get("municipality")
        )
        if city and city not in parts:
            parts.append(city)
        
        # Якщо є структурована адреса - використати її
        if parts:
            formatted = ", ".join(parts)
            logger.info(f"✅ Nominatim reverse: {lat},{lon} → {formatted}")
            return formatted
        
        # Fallback на display_name (якщо структура недоступна)
        logger.info(f"✅ Nominatim reverse (fallback): {lat},{lon} → {display_name}")
        return display_name
        
    except Exception as e:
        logger.error(f"❌ Nominatim Reverse Geocoding exception: {type(e).__name__}: {str(e)}")
        return None


async def reverse_geocode_with_places(api_key: str, lat: float, lon: float) -> Optional[str]:
    """
    Отримати адресу (з Nominatim, Places не використовується)
    
    Для сумісності з існуючим кодом. Просто викликає reverse_geocode.
    """
    return await reverse_geocode(api_key, lat, lon)


def generate_static_map_url(
    api_key: str,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    width: int = 600,
    height: int = 400
) -> str:
    """
    Генерувати URL для статичної карти через OpenStreetMap
    БЕЗКОШТОВНО!
    """
    # Використовуємо StaticMap від OpenStreetMap
    # Центр між двома точками
    center_lat = (origin_lat + dest_lat) / 2
    center_lon = (origin_lon + dest_lon) / 2
    
    # Приблизний zoom (можна налаштувати)
    zoom = 13
    
    # URL для StaticMap
    return (
        f"https://staticmap.openstreetmap.de/staticmap.php?"
        f"center={center_lat},{center_lon}&"
        f"zoom={zoom}&"
        f"size={width}x{height}&"
        f"markers={origin_lat},{origin_lon},greena&"
        f"markers={dest_lat},{dest_lon},redb"
    )


async def search_places_nearby(lat: float, lon: float, radius: int = 100) -> list:
    """
    Пошук об'єктів поруч через Overpass API (OpenStreetMap)
    БЕЗКОШТОВНО!
    
    Args:
        lat: Широта
        lon: Довгота
        radius: Радіус пошуку в метрах
    
    Returns:
        Список назв об'єктів поруч
    """
    # Затримка
    await _wait_for_nominatim()
    
    # Overpass API для пошуку об'єктів
    overpass_url = "https://overpass-api.de/api/interpreter"
    
    # Пошук магазинів, ресторанів, визначних місць
    query = f"""
    [out:json][timeout:10];
    (
      node["amenity"](around:{radius},{lat},{lon});
      node["shop"](around:{radius},{lat},{lon});
      node["tourism"](around:{radius},{lat},{lon});
    );
    out body 5;
    """
    
    headers = {
        'User-Agent': 'TaxiBot/1.0'
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                overpass_url, 
                data={"data": query},
                headers=headers,
                timeout=15
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        
        elements = data.get("elements", [])
        places = []
        
        for elem in elements:
            name = elem.get("tags", {}).get("name")
            if name:
                places.append(name)
        
        return places[:3]  # Максимум 3 об'єкти
        
    except Exception as e:
        logger.debug(f"Overpass API помилка: {e}")
        return []
