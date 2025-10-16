# 🔧 Виправлення проблеми з геокодуванням адрес

## ❌ Проблема:
При додаванні збережених адрес виникає помилка:
```
ERROR - ❌ Geocoding API REQUEST_DENIED: The provided API key is invalid.
```

Але при замовленні таксі все працює нормально.

---

## ✅ Що було виправлено:

### 1. **Додано Reverse Geocoding** (координати → адреса)
- Коли користувач надсилає **геолокацію**, тепер автоматично визначається адреса
- Функція `reverse_geocode()` в `app/utils/maps.py`
- Замість координат зберігається читабельна адреса

### 2. **Додано детальне логування**
Тепер в логах буде видно:
```
🔑 API ключ присутній, геокодую: вулиця Хрещатик 15
✅ Геокодування успішне: 50.4501, 30.5234
```

Або якщо проблема:
```
⚠️ Google Maps API ключ відсутній
⚠️ Геокодування не вдалось для: вулиця...
```

---

## 🔍 Діагностика:

Після деплою перевірте логи:

### **Якщо бачите:**
```
⚠️ Google Maps API ключ відсутній
```

**Рішення:**
1. Перевірте `.env` файл
2. Переконайтесь що `GOOGLE_MAPS_API_KEY=ваш_ключ`
3. На Render: Settings → Environment → додати `GOOGLE_MAPS_API_KEY`

### **Якщо бачите:**
```
❌ Geocoding API REQUEST_DENIED: The provided API key is invalid.
```

**Рішення:**
1. Перевірте що ключ правильний
2. Google Cloud Console → APIs & Services → Enable APIs
3. Увімкніть **Geocoding API** (не тільки Distance Matrix)
4. Перевірте billing (платіжний метод підключений)

### **Якщо бачите:**
```
🔑 API ключ присутній, геокодую: адреса
❌ Geocoding API REQUEST_DENIED...
```

**Це означає:**
- Ключ передається правильно
- Але Google відхиляє запит
- Перевірте Google Cloud Console:
  - Geocoding API увімкнено?
  - Обмеження API (restrictions)?
  - Квоти не вичерпані?

---

## 🚀 Код змін:

### `app/utils/maps.py` - додано функцію:
```python
async def reverse_geocode(api_key: str, lat: float, lon: float) -> Optional[str]:
    """Координати → адреса"""
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={api_key}&language=uk"
    # ... обробка відповіді
```

### `app/handlers/saved_addresses.py`:
```python
# При отриманні геолокації:
if config.google_maps_api_key:
    logger.info(f"🔑 API ключ присутній, reverse geocoding...")
    readable_address = await reverse_geocode(...)
    if readable_address:
        address = readable_address  # Зберегти читабельну адресу
```

---

## 📊 Перевірка:

### **Тест 1: Збережена адреса (текст)**
1. Клієнт → 📍 Мої адреси → ➕ Додати
2. Ввести назву: "Додому"
3. Вибрати емодзі: 🏠
4. Ввести текстом: "вулиця Хрещатик 15, Київ"
5. **Очікується:** адреса геокодується і зберігається з координатами

**Лог має бути:**
```
🔑 API ключ присутній, геокодую: вулиця Хрещатик 15, Київ
✅ Геокодування успішне: 50.4501, 30.5234
```

### **Тест 2: Збережена адреса (геолокація)**
1. Клієнт → 📍 Мої адреси → ➕ Додати
2. Ввести назву: "Робота"
3. Вибрати емодзі: 💼
4. Натиснути "📍 Надіслати геолокацію"
5. **Очікується:** координати перетворюються в адресу

**Лог має бути:**
```
🔑 API ключ присутній, reverse geocoding: 50.4501, 30.5234
✅ Reverse geocoded: вулиця Хрещатик, 15, Київ, Україна
```

---

## 🔑 Google Cloud Console - Checklist:

1. ✅ **APIs & Services → Library**
   - Geocoding API (ENABLED)
   - Distance Matrix API (ENABLED)

2. ✅ **APIs & Services → Credentials**
   - API key існує
   - Без IP обмежень (або додати IP Render)
   - Без application restrictions

3. ✅ **Billing**
   - Платіжний метод підключений
   - $200 безкоштовно на місяць
   - Geocoding: $5 на 1000 запитів (після free tier)

4. ✅ **Quotas**
   - Geocoding API: не досягнуто ліміту
   - Distance Matrix API: не досягнуто ліміту

---

## 🎯 Висновок:

**Проблема НЕ в коді** - код правильно передає API ключ.

**Проблема швидше за все:**
1. Geocoding API не увімкнено в Google Cloud
2. Або billing не налаштовано
3. Або обмеження на API key

**Наступні кроки:**
1. Подивитись логи після деплою (з новим логуванням)
2. Якщо "⚠️ API ключ відсутній" → додати в Render env
3. Якщо "REQUEST_DENIED" → перевірити Google Cloud Console
4. Звернути увагу чи працює Distance Matrix (при замовленні) - якщо так, то ключ правильний і треба тільки увімкнути Geocoding API

---

## 📝 Коміти:

```
2b7859d - fix: Додати детальне логування для діагностики geocoding
deaa9e6 - fix: Додати logger в saved_addresses
54af4ff - fix: Додано reverse geocoding для збережених адрес
```

Всі зміни запушені на `fix-taxi-bot` ✅
