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
                    return None
                data = await resp.json()
        
        rows = data.get("rows", [])
        if not rows:
            return None
        
        elements = rows[0].get("elements", [])
        if not elements:
            return None
        
        element = elements[0]
        if element.get("status") != "OK":
            return None
        
        distance = element.get("distance", {}).get("value")
        duration = element.get("duration", {}).get("value")
        
        if distance is None or duration is None:
            return None
        
        return (int(distance), int(duration))
    except Exception:
        return None


async def geocode_address(api_key: str, address: str) -> Optional[Tuple[float, float]]:
    """
    Convert address to coordinates using Google Geocoding API
    Returns (lat, lon) or None
    """
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={api_key}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        
        results = data.get("results", [])
        if not results:
            return None
        
        location = results[0].get("geometry", {}).get("location", {})
        lat = location.get("lat")
        lng = location.get("lng")
        
        if lat is None or lng is None:
            return None
        
        return (float(lat), float(lng))
    except Exception:
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
