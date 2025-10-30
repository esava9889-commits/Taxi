# 🔍 ДЕТАЛЬНИЙ АУДИТ КОДУ TAXI BOT

**Дата:** 2025-10-30  
**Гілка:** `fix-taxi-bot`  
**Статус:** ⚠️ Знайдено критичні проблеми

---

## 📊 РЕЗЮМЕ

**Всього знайдено проблем:** 11  
**Критичних:** 4 🔴  
**Важливих:** 5 🟡  
**Рекомендацій:** 2 🔵

---

## 🔴 КРИТИЧНІ ПРОБЛЕМИ (потрібно виправити НЕГАЙНО)

### 1. **МАСИВНЕ ДУБЛЮВАННЯ КОДУ в webapp_api.py**

**Локація:** `app/handlers/webapp_api.py`

**Проблема:**
- Функція `webapp_location_handler` (рядки 217-354) містить майже ІДЕНТИЧНИЙ код до `webapp_order_handler` (рядки 455-558)
- Дублюється логіка розрахунку цін, створення клавіатур, відправки повідомлень
- ~140 рядків коду дублюється

**Наслідки:**
- Будь-яка зміна логіки потребує правки в 2 місцях
- Висока ймовірність помилок через розбіжності
- Складність підтримки коду

**Рекомендація:**
Виділити спільну логіку в окрему функцію:
```python
async def _calculate_and_show_prices(
    bot: Bot,
    state: FSMContext,
    config: AppConfig,
    user_id: int,
    pickup_address: str,
    dest_address: str,
    distance_km: float,
    duration_minutes: float
) -> None:
    # Спільна логіка розрахунку цін і відображення
    ...
```

---

### 2. **ДУБЛЮВАННЯ base_fare РОЗРАХУНКУ**

**Локація:** 5 різних файлів

**Файли та рядки:**
- `app/handlers/order.py` (155-157, 979-981)
- `app/handlers/webapp_api.py` (255-258, 467-470)
- `app/handlers/webapp.py` (224-226)

**Проблема:**
Однаковий код розрахунку базової ціни повторюється 5 разів:
```python
base_fare = tariff.base_fare + (distance_km * tariff.per_km) + (duration_minutes * tariff.per_minute)
if base_fare < tariff.minimum:
    base_fare = tariff.minimum
```

**Наслідки:**
- Зміна формули потребує правки в 5 місцях
- Ризик неузгодженості розрахунків

**Рекомендація:**
Створити helper функцію:
```python
def calculate_base_fare(tariff: Tariff, distance_km: float, duration_minutes: float) -> float:
    """Розрахувати базову ціну з урахуванням мінімуму"""
    fare = tariff.base_fare + (distance_km * tariff.per_km) + (duration_minutes * tariff.per_minute)
    return max(fare, tariff.minimum)
```

---

### 3. **МОВЧАЗНИЙ FALLBACK без повідомлення користувачу**

**Локація:** 
- `app/handlers/webapp_api.py` (243-246, 450-453)
- `app/handlers/order.py` (142-143)
- `app/handlers/webapp.py` (211-213)

**Проблема:**
Коли OSRM не може розрахувати відстань, код МОВЧКИ встановлює:
```python
if not distance_km:
    distance_km = 5.0
    duration_minutes = 15
    await state.update_data(distance_km=distance_km, duration_minutes=duration_minutes)
```

**Наслідки:**
- Користувач бачить ціну за 5 км, але реальна відстань може бути 50 км!
- Водій може отримати замовлення з неадекватною ціною
- Фінансові втрати для сервісу або незадоволення клієнтів

**Рекомендація:**
```python
if not distance_km:
    logger.error(f"❌ OSRM не зміг розрахувати відстань для {user_id}")
    await bot.send_message(
        user_id,
        "⚠️ Не вдалося розрахувати відстань.\n"
        "Спробуйте обрати інші точки або зверніться до підтримки.",
        parse_mode="HTML"
    )
    return web.json_response(
        {"success": False, "error": "Could not calculate distance"},
        status=400
    )
```

---

### 4. **КОНФЛІКТ ДВОХ API ENDPOINTS**

**Локація:** `app/handlers/webapp_api.py` (586-587)

**Проблема:**
```python
app.router.add_post('/api/webapp/location', webapp_location_handler)  # Старий
app.router.add_post('/api/webapp/order', webapp_order_handler)  # Новий
```

Обидва endpoints роблять майже те саме (показують ціни класів авто), але:
- `webapp_location_handler` - приймає координати поетапно (pickup, потім destination)
- `webapp_order_handler` - приймає обидві координати одразу

**Наслідки:**
- Плутанина: який endpoint використовувати?
- Webapp використовує `/api/webapp/order`, але старий код залишився
- Подвійна підтримка коду

**Рекомендація:**
- Видалити `webapp_location_handler` якщо він не використовується
- АБО чітко розділити функціональність:
  - `/location` - тільки зберігає координати (БЕЗ розрахунку цін)
  - `/order` - розраховує ціни і показує класи

---

## 🟡 ВАЖЛИВІ ПРОБЛЕМИ (варто виправити)

### 5. **Неточне відображення множників у dynamic_pricing**

**Локація:** `app/handlers/dynamic_pricing.py` (184)

**Проблема:**
```python
reasons.append(f"• {time_reason}: +{int((time_mult-1)*100)}%")
```

Коли `time_mult` є результатом ДЕКІЛЬКОХ множників (наприклад піковий час 1.3 × нічний тариф 1.5 = 1.95), відображається "+95%", але насправді це 30% + 50%.

**Приклад:**
- Піковий час: +30%
- Нічний тариф: +50%
- `time_mult = 1.3 × 1.5 = 1.95`
- Відображення: "+95%" ❌
- Очікується: "+30%, +50%" або "+95% (комбінація)" ✅

**Рекомендація:**
Повертати окремі причини з `get_surge_multiplier()` замість комбінованого `time_reason`.

---

### 6. **Відсутність валідації координат**

**Локація:** `app/handlers/webapp_api.py` (37-40, 388-392)

**Проблема:**
Координати приймаються без валідації:
```python
latitude = data.get('latitude')
longitude = data.get('longitude')
```

**Наслідки:**
- Можуть прийти некоректні значення (наприклад "abc", 999, null)
- Координати поза діапазоном (latitude > 90, longitude > 180)

**Рекомендація:**
```python
def validate_coordinates(lat: float, lon: float) -> bool:
    """Валідувати координати"""
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180

# У handler:
if not validate_coordinates(latitude, longitude):
    return web.json_response(
        {"success": False, "error": "Invalid coordinates"},
        status=400
    )
```

---

### 7. **121 "голих" except блоків**

**Локація:** По всьому проекту

**Проблема:**
```python
except:  # ❌ Ловить ВСІ винятки, навіть системні (KeyboardInterrupt, SystemExit)
    await call.message.answer(...)
```

**Наслідки:**
- Складно дебагити
- Може ховати критичні помилки
- Неможливо graceful shutdown

**Рекомендація:**
```python
except Exception as e:  # ✅ Ловить тільки application exceptions
    logger.error(f"Error: {e}", exc_info=True)
    await call.message.answer(...)
```

---

### 8. **Відсутність timeout для HTTP запитів**

**Локація:** `app/utils/maps.py`

**Проблема:**
OSRM та Nominatim запити мають timeout=15, але що якщо сервіс повільний?

**Текущий код:**
```python
async with session.get(url, headers=headers, timeout=15) as resp:
```

**Рекомендація:**
Додати retry логіку або exponential backoff:
```python
from aiohttp import ClientTimeout

timeout = ClientTimeout(total=15, connect=5)
async with session.get(url, headers=headers, timeout=timeout) as resp:
```

---

### 9. **Потенційна race condition з _last_nominatim_request**

**Локація:** `app/utils/maps.py` (11, 26)

**Проблема:**
```python
_last_nominatim_request = 0  # Глобальна змінна

async def _wait_for_nominatim():
    global _last_nominatim_request
    now = time.time()
    time_since_last = now - _last_nominatim_request
    # ...
    _last_nominatim_request = time.time()
```

**Наслідки:**
При одночасних запитах від різних користувачів може порушуватися rate limit (1 req/sec для Nominatim).

**Рекомендація:**
Використати asyncio.Lock:
```python
_nominatim_lock = asyncio.Lock()

async def _wait_for_nominatim():
    async with _nominatim_lock:
        global _last_nominatim_request
        # ... решта логіки
```

---

## 🔵 РЕКОМЕНДАЦІЇ (покращення коду)

### 10. **Відсутність типізації в багатьох функціях**

**Проблема:**
Багато функцій не мають type hints, що ускладнює розуміння коду.

**Рекомендація:**
Додати типи для всіх параметрів та return values:
```python
async def get_user_by_id(db_path: str, user_id: int) -> Optional[User]:
    ...
```

---

### 11. **Відсутність unit tests**

**Проблема:**
Немає тестів для критичної логіки (ціноутворення, розрахунок відстані, тощо).

**Рекомендація:**
Додати pytest тести:
```python
def test_calculate_dynamic_price():
    base_fare = 100.0
    result = calculate_dynamic_price(
        base_fare,
        online_drivers=5,
        pending_orders=0,
        # ...
    )
    assert result[0] == 100.0  # Без націнок
```

---

## 📋 CHECKLIST ДЛЯ ВИПРАВЛЕННЯ

### Пріоритет 1 (КРИТИЧНО):
- [ ] Виділити спільну логіку розрахунку цін у webapp_api.py
- [ ] Створити helper функцію для calculate_base_fare
- [ ] Додати повідомлення користувачу при OSRM fallback
- [ ] Видалити або розділити конфліктуючі API endpoints

### Пріоритет 2 (ВАЖЛИВО):
- [ ] Виправити відображення множників у dynamic_pricing
- [ ] Додати валідацію координат
- [ ] Замінити голі `except:` на `except Exception as e:`
- [ ] Додати retry логіку для HTTP запитів
- [ ] Виправити race condition в Nominatim rate limiter

### Пріоритет 3 (ПОКРАЩЕННЯ):
- [ ] Додати type hints по всьому проекту
- [ ] Написати unit tests для критичної логіки
- [ ] Додати integration tests для API endpoints

---

## 📈 МЕТРИКИ КОДУ

**Дублювання коду:**
- webapp_api.py: ~140 рядків дублюється (23% файлу)
- base_fare розрахунок: 5 копій

**Складність:**
- webapp_api.py: 589 рядків (занадто великий, треба розділити)
- order.py: 2569 рядків (дуже великий!)

**Технічний борг:**
- 121 голих except блоків
- Відсутність тестів
- Мінімальна типізація

---

## ✅ ЩО ПРАЦЮЄ ДОБРЕ

1. ✅ **SQL ін'єкції відсутні** - використовуються параметризовані запити
2. ✅ **Rate limiting для Nominatim** - реалізовано
3. ✅ **HTTPS для геокодування** - виправлено
4. ✅ **Логування** - детальне і інформативне
5. ✅ **Структура проекту** - логічна організація модулів

---

**Аудит виконав:** AI Agent  
**Інструменти:** grep, manual code review, static analysis
