# 🔍 ДІАГНОСТИКА WebApp - Інструкція з перегляду логів

**Коміт:** `06b348d` на гілці `fix-taxi-bot`  
**Дата:** 2025-10-28  
**Статус:** ✅ ДЕТАЛЬНЕ ЛОГУВАННЯ ДОДАНО

---

## 🎯 МЕТА

З'ясувати чому кнопка "Підтвердити місце" не обробляється правильно:
- ❓ Чи відкривається карта?
- ❓ Чи працює клік по карті?
- ❓ Чи показується кнопка "Підтвердити"?
- ❓ Чи спрацьовує клік по кнопці?
- ❓ Чи надсилаються дані в бота?
- ❓ Чи отримує бот ці дані?
- ❓ Чи обробляються дані правильно?

---

## 📱 ЯК ПЕРЕГЛЯНУТИ ЛОГИ В БРАУЗЕРІ (Frontend)

### Крок 1: Відкрити DevTools

**На комп'ютері (Telegram Desktop або Web):**
1. Відкрийте бота в Telegram
2. Натисніть `/order` → "Замовити таксі"
3. Натисніть "📍 Надіслати мою геолокацію"
4. Натисніть "🗺 Обрати на інтерактивній карті"
5. **ОДРАЗУ після відкриття карти:**
   - **Windows/Linux:** `F12` або `Ctrl+Shift+I`
   - **Mac:** `Cmd+Option+I`
6. Перейдіть на вкладку **Console**

**На телефоні (Android з Chrome):**
1. На **комп'ютері** відкрийте Chrome
2. Підключіть телефон по USB
3. Увімкніть "USB Debugging" на телефоні
4. В Chrome на ПК: `chrome://inspect`
5. Знайдіть ваш телефон → WebView
6. Клікніть **Inspect**
7. Відкриється DevTools з логами WebApp

**На телефоні (iPhone - складніше):**
- Потрібен Mac з Safari
- Settings → Safari → Advanced → Web Inspector
- На Mac: Safari → Develop → [Ваш iPhone]

### Крок 2: Що шукати в логах браузера

#### При СТАРТІ WebApp ви маєте побачити:

```
============================================================
🚀 WEBAPP START: 2025-10-28T14:27:00.000Z
============================================================
✅ Telegram WebApp initialized: Object {...}
📱 Version: 7.10
📱 Platform: ios / android / web
🎨 Color scheme: light / dark
👤 User: {id: 123456789, first_name: "...", ...}
🔍 initData present: true
🔍 API methods available:
  - MainButton: object
  - sendData: function
  - close: function
  - expand: function
✅ WebApp expanded
🔘 MainButton configured
  - Text: ✅ Підтвердити місце
  - isVisible: false
============================================================
```

**Якщо цього НЕМАЄ** → проблема з Telegram WebApp SDK або index.html не завантажився!

#### При КЛІКУ на карту ви маєте побачити:

```
============================================================
🗺 MAP CLICKED: 2025-10-28T14:27:05.000Z
============================================================
📍 Click position: 50.4501 30.5234
📍 e.latlng object: LatLng {...}
🗑 Removing previous marker (якщо не перший клік)
📌 Adding new marker...
✅ Marker added to map
💾 Coordinates saved to selectedCoords: {lat: 50.4501, lng: 30.5234}
🔍 Type of selectedCoords: object
🔍 selectedCoords.lat: 50.4501
🔍 selectedCoords.lng: 30.5234
✅ Coordinates displayed: 50.450100, 30.523400
🔘 Showing MainButton...
  - BEFORE show(): isVisible = false
  - AFTER show(): isVisible = true
✅ MainButton.show() executed
============================================================
```

**Якщо цього НЕМАЄ** → проблема з Leaflet картою або обробником кліків!

#### При НАТИСКАННІ "Підтвердити місце" ви маєте побачити:

```
============================================================
🔘 MAINBUTTON CLICK EVENT: 2025-10-28T14:27:10.000Z
============================================================
📍 Selected coords: {lat: 50.4501, lng: 30.5234}
🔍 Type of selectedCoords: object
🔍 selectedCoords value: {"lat":50.4501,"lng":30.5234}
✅ Coordinates are valid, preparing data...
📤 Data to send: {type: 'location', latitude: 50.4501, longitude: 30.5234}
  - type: location
  - latitude: 50.4501
  - longitude: 30.5234
📦 JSON string: {"type":"location","latitude":50.4501,"longitude":30.5234}
📦 JSON length: 62
📡 Calling tg.sendData()...
✅ tg.sendData() called successfully!
📳 Triggering success haptic
🚪 Calling tg.close()...
✅ tg.close() called!
============================================================
```

**Якщо цього НЕМАЄ** → кнопка MainButton не налаштована або onClick не зареєстрований!

**Якщо бачите помилку:**
```
============================================================
❌ ERROR in try block: 2025-10-28T14:27:10.000Z
============================================================
Error type: TypeError
Error message: Cannot read property 'lat' of undefined
Error stack: ...
============================================================
```
→ selectedCoords не збереглися після кліку на карту!

---

## 🖥 ЯК ПЕРЕГЛЯНУТИ ЛОГИ RENDER (Backend)

### Крок 1: Відкрити Render Dashboard

1. Перейдіть на https://render.com
2. Увійдіть в акаунт
3. Знайдіть ваш сервіс (Taxi bot)
4. Клікніть на назву сервісу
5. Перейдіть на вкладку **Logs**

### Крок 2: Що шукати в логах Render

#### При ОТРИМАННІ даних з WebApp ви маєте побачити:

```
2025-10-28 14:27:10 - app.handlers.webapp - INFO - ============================================================
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 🗺 WEBAPP DATA RECEIVED from user 123456789
2025-10-28 14:27:10 - app.handlers.webapp - INFO - ============================================================
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 📦 Message object: Message(...)
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 📦 Message type: web_app_data
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 📦 Has web_app_data: True
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 📦 web_app_data is None: False
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 📦 Raw WebApp data string: '{"type":"location","latitude":50.4501,"longitude":30.5234}'
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 📦 Data type: <class 'str'>
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 📦 Data length: 62
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 🔧 Parsing JSON...
2025-10-28 14:27:10 - app.handlers.webapp - INFO - ✅ Parsed JSON successfully: {'type': 'location', 'latitude': 50.4501, 'longitude': 30.5234}
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 🔍 Data keys: ['type', 'latitude', 'longitude']
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 🔍 Data type field: 'location'
2025-10-28 14:27:10 - app.handlers.webapp - INFO - ✅ Data type is 'location'
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 📍 Extracted coordinates:
2025-10-28 14:27:10 - app.handlers.webapp - INFO -   - latitude: 50.4501 (type: <class 'float'>)
2025-10-28 14:27:10 - app.handlers.webapp - INFO -   - longitude: 30.5234 (type: <class 'float'>)
2025-10-28 14:27:10 - app.handlers.webapp - INFO - ✅ Coordinates are valid
2025-10-28 14:27:10 - app.handlers.webapp - INFO - 🌍 Calling reverse_geocode(50.4501, 30.5234)...
2025-10-28 14:27:11 - app.handlers.webapp - INFO - ✅ Reverse geocoding result: 'Хрещатик 1, Київ, Україна'
2025-10-28 14:27:11 - app.handlers.webapp - INFO - 📍 WebApp location received:
2025-10-28 14:27:11 - app.handlers.webapp - INFO -   - Latitude: 50.4501
2025-10-28 14:27:11 - app.handlers.webapp - INFO -   - Longitude: 30.5234
2025-10-28 14:27:11 - app.handlers.webapp - INFO -   - Address: Хрещатик 1, Київ, Україна
2025-10-28 14:27:11 - app.handlers.webapp - INFO -   - Current state: OrderStates:pickup
2025-10-28 14:27:11 - app.handlers.webapp - INFO -   - Waiting for: pickup
2025-10-28 14:27:11 - app.handlers.webapp - INFO -   - All state data keys: ['waiting_for', 'last_message_id', 'city']
2025-10-28 14:27:11 - app.handlers.webapp - INFO - ✅ WebApp pickup збережено: Хрещатик 1, Київ, Україна (50.4501, 30.5234)
2025-10-28 14:27:11 - app.handlers.webapp - INFO - 📦 State після збереження pickup: {'pickup': 'Хрещатик 1, Київ, Україна', 'pickup_lat': 50.4501, 'pickup_lon': 30.5234, 'waiting_for': None, ...}
2025-10-28 14:27:11 - app.handlers.webapp - INFO - 📍 WebApp location processed: 50.4501, 30.5234 -> Хрещатик 1, Київ, Україна
```

**Це означає що ВСЕ ПРАЦЮЄ ІДЕАЛЬНО!** ✅

### Якщо бачите ТІЛЬКИ це:

```
2025-10-28 14:27:25 - aiogram.event - INFO - Update id=538985182 is handled. Duration 203 ms by bot id=8390434370
2025-10-28 14:27:32 - aiogram.event - INFO - Update id=538985183 is handled. Duration 549 ms by bot id=8390434370
```

**БЕЗ жодних рядків з `🗺 WEBAPP DATA RECEIVED`** →

❌ **ПРОБЛЕМА:** Дані з WebApp НЕ надсилаються або НЕ доходять до бота!

**Можливі причини:**
1. `tg.sendData()` не викликається (перевірте логи браузера!)
2. `tg.close()` не викликається після `sendData()` (дані не відправляються!)
3. WebApp відкривається не з того бота
4. `WEBAPP_URL` не встановлено або неправильний

---

## 🔍 СЦЕНАРІЇ ПОМИЛОК

### Сценарій 1: Карта не відкривається

**Симптоми:**
- Натискаєте "🗺 Обрати на карті"
- Нічого не відбувається

**Діагностика:**
1. Перевірте `WEBAPP_URL` в Render Environment Variables
2. Має бути: `https://ваш-логін.github.io/taxi-map/`
3. Відкрийте цей URL в браузері - карта має завантажитися

**Виправлення:**
- Перевірте що `index.html` на GitHub Pages актуальний
- Очистіть кеш браузера: `Ctrl+Shift+R`

---

### Сценарій 2: Карта відкривається, але логів НЕМАЄ

**Симптоми:**
- Карта відкривається
- В Console (F12) ПУСТО

**Діагностика:**
1. Перевірте що DevTools відкрито ПІСЛЯ відкриття карти
2. Оновіть карту (закрийте і відкрийте знову)
3. DevTools має бути відкрито на вкладці Console

**Виправлення:**
- Оновіть index.html на GitHub Pages (коміт `06b348d`)
- Очистіть кеш: `Ctrl+Shift+R`

---

### Сценарій 3: Клік по карті не працює

**Симптоми:**
- Карта відкривається
- Клікаєте по карті
- Маркер не з'являється
- Кнопка "Підтвердити" не показується

**Діагностика в Console:**
```javascript
// Перевірте чи є обробник
map._events.click // має бути масив з функцією
```

**Логи які МАЮТЬ з'явитися:**
```
🗺 MAP CLICKED: ...
```

**Якщо логів НЕМАЄ** → проблема з Leaflet або обробником `map.on('click')`

---

### Сценарій 4: Кнопка не показується після кліку

**Симптоми:**
- Клік працює (є маркер)
- Кнопка "Підтвердити" НЕ з'являється внизу

**Логи в Console:**
```
🔘 Showing MainButton...
  - BEFORE show(): isVisible = false
  - AFTER show(): isVisible = false  ← ❌ ПРОБЛЕМА!
```

**Можлива причина:**
- Telegram WebApp API не працює
- Версія SDK застаріла

**Виправлення:**
- Перевірте `tg.version` в логах (має бути >= 6.0)
- Оновіть Telegram на телефоні

---

### Сценарій 5: Кнопка є, але клік не працює

**Симптоми:**
- Кнопка "Підтвердити місце" внизу
- Натискаєте - нічого не відбувається

**Логи які МАЮТЬ з'явитися:**
```
🔘 MAINBUTTON CLICK EVENT: ...
```

**Якщо логів НЕМАЄ:**
- onClick handler не зареєстрований
- Оновіть index.html (коміт `06b348d`)

**Якщо є логи але є помилка:**
```
❌ ERROR in try block: ...
Error message: selectedCoords is undefined
```
→ Координати не збереглися після кліку!

---

### Сценарій 6: sendData викликається, але бот не отримує

**Симптоми:**
- В Console бачите:
```
✅ tg.sendData() called successfully!
✅ tg.close() called!
```
- Але в логах Render НЕМАЄ `🗺 WEBAPP DATA RECEIVED`

**Можливі причини:**
1. ❌ `tg.close()` НЕ викликається → дані не відправляються!
2. ❌ WebApp відкрито не з того бота
3. ❌ Проблема з Telegram API

**Діагностика:**
1. Перевірте що в Console є `tg.close()` ПІСЛЯ `sendData()`
2. Перевірте User ID в логах браузера і Render (мають співпадати!)
3. Зачекайте 10 секунд - іноді є затримка

---

### Сценарій 7: Бот отримує дані, але не зберігає

**Симптоми:**
- В Render логах бачите `🗺 WEBAPP DATA RECEIVED`
- Але адреса не зберігається і не переходить до destination

**Логи які шукати:**
```
  - Waiting for: pickup  ← має бути 'pickup' або 'destination'!
```

**Якщо `Waiting for: None` або інше значення:**
→ Проблема з встановленням `waiting_for` в `order.py`

**Виправлення:**
- Перевірте що натискали "📍 Надіслати мою геолокацію" ПЕРЕД відкриттям карти
- Не натискали "Назад" або інші кнопки

---

## 📊 ПОВНИЙ ЧЕК-ЛИСТ ДІАГНОСТИКИ

### 1. Підготовка

- [ ] Render задеплоїв коміт `06b348d` (перевірте в Logs)
- [ ] GitHub Pages має актуальний `index.html` (коміт `06b348d`)
- [ ] `WEBAPP_URL` встановлено в Render Environment Variables
- [ ] Очищено кеш браузера (`Ctrl+Shift+R`)

### 2. Тест Frontend (Console)

- [ ] Відкрити WebApp → побачити `🚀 WEBAPP START`
- [ ] Клік по карті → побачити `🗺 MAP CLICKED`
- [ ] Клік по кнопці → побачити `🔘 MAINBUTTON CLICK EVENT`
- [ ] Побачити `✅ tg.sendData() called`
- [ ] Побачити `✅ tg.close() called`

### 3. Тест Backend (Render Logs)

- [ ] Побачити `🗺 WEBAPP DATA RECEIVED`
- [ ] Побачити `✅ Parsed JSON successfully`
- [ ] Побачити `Waiting for: pickup` (або `destination`)
- [ ] Побачити `✅ WebApp pickup збережено`
- [ ] Побачити повідомлення в боті "📍 Куди їдемо?"

### 4. Якщо щось не працює

1. Скопіюйте ВСІ логи з Console (F12)
2. Скопіюйте ВСІ логи з Render (останні 100 рядків)
3. Зробіть скріншот екрану
4. Надішліть мені ВСЕ це разом

---

## 🚀 ПІСЛЯ ДЕПЛОЮ

**Зачекайте 2-3 хвилини** щоб Render задеплоїв новий код.

**Потім:**
1. ✅ Відкрийте бота в Telegram
2. ✅ Відкрийте DevTools (F12 → Console)
3. ✅ Натисніть `/order` → "Замовити таксі"
4. ✅ Натисніть "📍 Надіслати мою геолокацію"
5. ✅ Натисніть "🗺 Обрати на карті"
6. ✅ **ОДРАЗУ** дивіться логи в Console
7. ✅ Клікніть по карті
8. ✅ Дивіться логи в Console
9. ✅ Натисніть "Підтвердити місце"
10. ✅ Дивіться логи в Console
11. ✅ Перейдіть в Render → Logs
12. ✅ Знайдіть `🗺 WEBAPP DATA RECEIVED`

**Надішліть мені:**
- ✅ Скріншот Console з усіма логами
- ✅ Скріншот Render Logs з `🗺 WEBAPP DATA RECEIVED`
- ✅ Опис що саме не працює

**З цим я зможу ТОЧНО знайти проблему!** 🎯
