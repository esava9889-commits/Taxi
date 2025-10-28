from __future__ import annotations

import math
from typing import Optional, Tuple
from datetime import datetime

from app.storage.db import Driver, fetch_online_drivers


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in meters using Haversine formula"""
    R = 6371000  # Earth radius in meters
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) *
         math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


async def find_nearest_driver(
    db_path: str,
    pickup_lat: float,
    pickup_lon: float
) -> Optional[Driver]:
    """Find the nearest online driver to the pickup location"""
    drivers = await fetch_online_drivers(db_path, limit=50)
    
    if not drivers:
        return None
    
    nearest = None
    min_distance = float('inf')
    
    for driver in drivers:
        if driver.last_lat is None or driver.last_lon is None:
            continue
        
        distance = calculate_distance(
            pickup_lat, pickup_lon,
            driver.last_lat, driver.last_lon
        )
        
        if distance < min_distance:
            min_distance = distance
            nearest = driver
    
    return nearest


def parse_geo_coordinates(address: str) -> Optional[Tuple[float, float]]:
    """Parse geo:lat,lon format to (lat, lon) tuple"""
    if not address or not address.startswith("geo:"):
        return None
    
    try:
        coords = address[4:].split(",")
        if len(coords) != 2:
            return None
        lat = float(coords[0])
        lon = float(coords[1])
        return (lat, lon)
    except (ValueError, IndexError):
        return None
