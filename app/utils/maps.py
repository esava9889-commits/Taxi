from __future__ import annotations

from typing import Optional, Tuple
import aiohttp


async def get_distance_and_duration(
    api_key: str,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float
) -> Optional[Tuple[int, int]]:
    """
    Get distance (meters) and duration (seconds) from Google Distance Matrix API
    Returns (distance_meters, duration_seconds) or None
    """
    import logging
    logger = logging.getLogger(__name__)
    
    origins = f"{origin_lat},{origin_lon}"
    destinations = f"{dest_lat},{dest_lon}"
    
    url = (
        "https://maps.googleapis.com/maps/api/distancematrix/json"
        f"?origins={origins}&destinations={destinations}&key={api_key}&mode=driving"
    )
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    logger.error(f"Distance Matrix API HTTP error: {resp.status}")
                    return None
                data = await resp.json()
        
        status = data.get("status")
        
        if status == "REQUEST_DENIED":
            error_message = data.get("error_message", "Unknown error")
            logger.error(f"❌ Distance Matrix API REQUEST_DENIED: {error_message}")
            logger.error(f"Перевірте що Distance Matrix API увімкнений в Google Cloud Console")
            return None
        
        if status != "OK":
            logger.warning(f"⚠️ Distance Matrix API status: {status}")
            return None
        
        rows = data.get("rows", [])
        if not rows:
            logger.warning(f"⚠️ Distance Matrix API: порожні rows")
            return None
        
        elements = rows[0].get("elements", [])
        if not elements:
            logger.warning(f"⚠️ Distance Matrix API: порожні elements")
            return None
        
        element = elements[0]
        element_status = element.get("status")
        
        if element_status != "OK":
            logger.warning(f"⚠️ Distance Matrix API element status: {element_status}")
            return None
        
        distance = element.get("distance", {}).get("value")
        duration = element.get("duration", {}).get("value")
        
        if distance is None or duration is None:
            logger.warning(f"⚠️ Distance Matrix API: немає distance/duration")
            return None
        
        return (int(distance), int(duration))
    except Exception as e:
        logger.error(f"❌ Distance Matrix API exception: {type(e).__name__}: {str(e)}")
        return None


async def geocode_address(api_key: str, address: str) -> Optional[Tuple[float, float]]:
    """
    Convert address to coordinates using Google Geocoding API
    Returns (lat, lon) or None
    """
    import logging
    import urllib.parse
    logger = logging.getLogger(__name__)
    
    # Додаємо країну якщо не вказана
    if "україна" not in address.lower() and "ukraine" not in address.lower():
        address = f"{address}, Україна"
    
    encoded_address = urllib.parse.quote(address)
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    logger.error(f"Geocoding API HTTP error: {resp.status}")
                    return None
                data = await resp.json()
        
        status = data.get("status")
        
        if status == "REQUEST_DENIED":
            error_message = data.get("error_message", "Unknown error")
            logger.error(f"❌ Geocoding API REQUEST_DENIED: {error_message}")
            logger.error(f"Перевірте що Geocoding API увімкнений в Google Cloud Console")
            return None
        
        if status == "ZERO_RESULTS":
            logger.warning(f"⚠️ Geocoding API не знайшов адресу: {address}")
            return None
        
        if status == "OVER_QUERY_LIMIT":
            logger.error(f"❌ Geocoding API: перевищено ліміт запитів")
            return None
        
        if status != "OK":
            logger.warning(f"⚠️ Geocoding API status: {status}")
            return None
        
        results = data.get("results", [])
        if not results:
            logger.warning(f"⚠️ Geocoding API: порожні результати")
            return None
        
        location = results[0].get("geometry", {}).get("location", {})
        lat = location.get("lat")
        lng = location.get("lng")
        
        if lat is None or lng is None:
            logger.warning(f"⚠️ Geocoding API: немає координат в результаті")
            return None
        
        return (float(lat), float(lng))
    except Exception as e:
        logger.error(f"❌ Geocoding API exception: {type(e).__name__}: {str(e)}")
        return None


async def reverse_geocode(api_key: str, lat: float, lon: float) -> Optional[str]:
    """
    Convert coordinates to address using Google Reverse Geocoding API
    Returns address string or None
    """
    import logging
    logger = logging.getLogger(__name__)
    
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={api_key}&language=uk"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    logger.error(f"Reverse Geocoding API HTTP error: {resp.status}")
                    return None
                data = await resp.json()
        
        status = data.get("status")
        
        if status == "REQUEST_DENIED":
            error_message = data.get("error_message", "Unknown error")
            logger.error(f"❌ Reverse Geocoding API REQUEST_DENIED: {error_message}")
            logger.error(f"Перевірте що Geocoding API увімкнений в Google Cloud Console")
            return None
        
        if status != "OK":
            logger.warning(f"⚠️ Reverse Geocoding API status: {status}")
            return None
        
        results = data.get("results", [])
        if not results:
            logger.warning(f"⚠️ Reverse Geocoding: порожні результати")
            return None
        
        # Взяти першу (найточнішу) адресу
        formatted_address = results[0].get("formatted_address")
        
        if formatted_address:
            return formatted_address
        
        return None
    except Exception as e:
        logger.error(f"❌ Reverse Geocoding API exception: {type(e).__name__}: {str(e)}")
        return None


def generate_static_map_url(
    api_key: str,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    width: int = 600,
    height: int = 400
) -> str:
    """Generate URL for static map image with route"""
    markers = (
        f"markers=color:green|label:A|{origin_lat},{origin_lon}&"
        f"markers=color:red|label:B|{dest_lat},{dest_lon}"
    )
    
    return (
        f"https://maps.googleapis.com/maps/api/staticmap?"
        f"{markers}&"
        f"size={width}x{height}&"
        f"key={api_key}"
    )
