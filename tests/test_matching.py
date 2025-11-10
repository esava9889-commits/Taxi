"""
Тести для модуля matching.py

Перевіряють пошук найближчого водія та розрахунок відстаней
"""
import pytest
import math
from app.utils.matching import (
    calculate_distance,
    parse_geo_coordinates,
)


class TestCalculateDistance:
    """Тести розрахунку відстані"""
    
    def test_same_location(self):
        """Відстань між однаковими точками = 0"""
        lat, lon = 50.4501, 30.5234  # Київ
        
        distance = calculate_distance(lat, lon, lat, lon)
        assert distance == 0.0
    
    def test_known_distance(self):
        """Перевірити відомі відстані"""
        # Київ -> Львів приблизно 470 км
        kyiv_lat, kyiv_lon = 50.4501, 30.5234
        lviv_lat, lviv_lon = 49.8397, 24.0297
        
        distance = calculate_distance(kyiv_lat, kyiv_lon, lviv_lat, lviv_lon)
        
        # Перевірити що в межах розумного (460-480 км)
        assert 460_000 < distance < 480_000
    
    def test_short_distance(self):
        """Перевірити короткі відстані"""
        # 2 точки в одному районі (~1 км)
        lat1, lon1 = 50.4501, 30.5234
        lat2, lon2 = 50.4600, 30.5334
        
        distance = calculate_distance(lat1, lon1, lat2, lon2)
        
        # Має бути близько 1-2 км
        assert 500 < distance < 2000
    
    def test_symmetry(self):
        """Відстань A→B = відстань B→A"""
        lat1, lon1 = 50.4501, 30.5234
        lat2, lon2 = 49.8397, 24.0297
        
        distance_ab = calculate_distance(lat1, lon1, lat2, lon2)
        distance_ba = calculate_distance(lat2, lon2, lat1, lon1)
        
        assert distance_ab == distance_ba
    
    def test_positive_distance(self):
        """Відстань завжди позитивна"""
        lat1, lon1 = 50.4501, 30.5234
        lat2, lon2 = 40.7128, -74.0060  # Нью-Йорк
        
        distance = calculate_distance(lat1, lon1, lat2, lon2)
        assert distance > 0
    
    def test_earth_radius(self):
        """Перевірити що використовується правильний радіус Землі"""
        # Відстань на екваторі між 0°E та 1°E має бути ~111 км
        lat = 0.0
        lon1, lon2 = 0.0, 1.0
        
        distance = calculate_distance(lat, lon1, lat, lon2)
        
        # Має бути близько 111 км
        assert 110_000 < distance < 112_000
    
    def test_north_south_distance(self):
        """Перевірити відстань північ-південь"""
        # 1 градус широти ≈ 111 км
        lat1, lat2 = 50.0, 51.0
        lon = 30.0
        
        distance = calculate_distance(lat1, lon, lat2, lon)
        
        # Має бути близько 111 км
        assert 110_000 < distance < 112_000


class TestParseGeoCoordinates:
    """Тести парсингу координат"""
    
    def test_valid_coordinates(self):
        """Перевірити валідні координати"""
        # Формат: geo:lat,lon
        result = parse_geo_coordinates("geo:50.4501,30.5234")
        
        assert result is not None
        lat, lon = result
        assert lat == 50.4501
        assert lon == 30.5234
    
    def test_negative_coordinates(self):
        """Перевірити від'ємні координати"""
        result = parse_geo_coordinates("geo:-33.8688,151.2093")  # Сідней
        
        assert result is not None
        lat, lon = result
        assert lat == -33.8688
        assert lon == 151.2093
    
    def test_invalid_format(self):
        """Перевірити невалідні формати"""
        invalid_formats = [
            "50.4501,30.5234",  # без geo:
            "geo:50.4501",  # тільки широта
            "geo:50.4501,30.5234,100",  # 3 числа
            "geo:abc,def",  # не числа
            "latitude:50.4501,longitude:30.5234",  # інший формат
            "",
            None,
        ]
        
        for invalid in invalid_formats:
            result = parse_geo_coordinates(invalid)
            assert result is None, f"Формат {invalid} має бути невалідним"
    
    def test_whitespace_handling(self):
        """Перевірити обробку пробілів"""
        # Пробіли не підтримуються
        result = parse_geo_coordinates("geo: 50.4501 , 30.5234")
        assert result is None
    
    def test_zero_coordinates(self):
        """Перевірити нульові координати"""
        result = parse_geo_coordinates("geo:0.0,0.0")
        
        assert result is not None
        lat, lon = result
        assert lat == 0.0
        assert lon == 0.0


class TestFindNearestDriver:
    """
    Тести для find_nearest_driver
    
    ПРИМІТКА: Ці тести потребують доступу до БД, тому пропускаються
    в CI/CD без налаштованої БД. Для повноцінного тестування потрібно
    використовувати mock або тестову БД.
    """
    
    @pytest.mark.skip(reason="Потребує БД для інтеграційного тестування")
    async def test_find_nearest_driver_no_drivers(self):
        """Коли немає водіїв - повернути None"""
        # TODO: Реалізувати з mock БД
        pass
    
    @pytest.mark.skip(reason="Потребує БД для інтеграційного тестування")
    async def test_find_nearest_driver_one_driver(self):
        """Коли один водій - повернути його"""
        # TODO: Реалізувати з mock БД
        pass
    
    @pytest.mark.skip(reason="Потребує БД для інтеграційного тестування")
    async def test_find_nearest_driver_multiple_drivers(self):
        """Коли кілька водіїв - повернути найближчого"""
        # TODO: Реалізувати з mock БД
        pass
