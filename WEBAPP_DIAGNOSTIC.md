# 🔍 ДІАГНОСТИКА WEBAPP - Інструкція

## Проблема
Карта відкривається через Telegram, користувач натискає "Підтвердити місце", карта закривається, але бот не продовжує замовлення.

## 📋 Що було додано для діагностики

### 1. **JavaScript логування** (`webapp/index.html`)
У браузерній консолі (розробницькі інструменти) будуть логуватися:
```
🚀 WEBAPP START: [timestamp]
✅ Telegram WebApp initialized
🗺 MAP CLICKED: [coordinates]
🔘 MAINBUTTON CLICK EVENT
📡 Calling tg.sendData()...
✅ tg.sendData() called successfully!
🚪 CALLING tg.close() - THIS IS CRITICAL!
```

### 2. **Python логування** (`app/handlers/webapp.py` + `app/main.py`)
У логах Render повинно з'явитися:
```
📦 REGISTERING ROUTERS...
🔧 webapp.create_router() called
✅ webapp_router created
✅ webapp_router registered in dispatcher
...
🗺 WEBAPP F.web_app_data HANDLER TRIGGERED!
🗺 WEBAPP DATA RECEIVED from user 123456
📦 Raw WebApp data string: '{"type":"location","latitude":50.45,"longitude":30.52}'
```

---

## 🔬 ЯК ДІАГНОСТУВАТИ

### **Крок 1: Відкрити консоль браузера**
1. Відкрийте бота в **Telegram Desktop** або **Telegram Web**
2. Натисніть "🗺 Обрати на інтерактивній карті"
3. Відразу відкрийте **розробницькі інструменти**:
   - **Chrome/Edge**: `F12` або `Ctrl+Shift+I`
   - **Firefox**: `F12` або `Ctrl+Shift+K`
   - **Safari**: `Cmd+Option+I`
4. Перейдіть на вкладку **Console**

### **Крок 2: Натисніть точку на карті**
Повинні з'явитися логи:
```
🗺 MAP CLICKED: 2025-10-30T...
📍 Click position: 50.450001 30.523333
📌 Adding new marker...
✅ Marker added to map
🔘 Showing MainButton...
```

✅ **Якщо логи є** → WebApp працює правильно
❌ **Якщо логів немає** → Проблема в JavaScript або WebApp не завантажується

### **Крок 3: Натисніть "✅ Підтвердити місце"**
Повинні з'явитися логи:
```
🔘 MAINBUTTON CLICK EVENT: 2025-10-30T...
📍 Selected coords: {lat: 50.45, lng: 30.52}
📦 JSON string: {"type":"location","latitude":50.45,"longitude":30.52}
📡 Calling tg.sendData()...
✅ tg.sendData() called successfully!
🚪 CALLING tg.close() - THIS IS CRITICAL!
```

✅ **Якщо всі логи є** → JavaScript працює правильно, дані відправлено
❌ **Якщо помилка** → Буде показано червону помилку в консолі

### **Крок 4: Перевірити логи на Render**
1. Зайдіть на [Render Dashboard](https://dashboard.render.com)
2. Відкрийте ваш сервіс
3. Перейдіть на вкладку **Logs**
4. **ВАЖЛИВО**: Після натискання "Підтвердити" зачекайте 2-3 секунди і оновіть логи

Шукайте рядки:
```
🗺 WEBAPP F.web_app_data HANDLER TRIGGERED!
🗺 WEBAPP DATA RECEIVED from user 123456
```

**Результати:**

| Що бачите в логах | Діагноз | Рішення |
|-------------------|---------|---------|
| ✅ `WEBAPP F.web_app_data HANDLER TRIGGERED!` | Все працює! | Немає проблеми |
| ❌ Нічого не з'являється | Telegram не передає дані в бота | Проблема з webhook або initData |
| ❌ `ERROR` в логах | Помилка обробки | Дивіться деталі помилки |

---

## 🐛 ТИПОВІ ПРОБЛЕМИ ТА РІШЕННЯ

### Проблема 1: "Немає логів у Console браузера"
**Причина:** WebApp відкривається в мобільному Telegram, де немає консолі.

**Рішення:**
- Тестуйте в **Telegram Desktop** або **Telegram Web**
- АБО дивіться тільки логи на Render (вони показують чи дані дійшли)

---

### Проблема 2: "JavaScript логи є, але логів на Render немає"
**Причина:** `tg.sendData()` працює, але Telegram не передає дані в webhook.

**Можливі причини:**
1. **Неправильний `initData`** - WebApp відкрито не через кнопку бота
2. **Webhook не налаштовано** - Telegram не знає куди відправляти дані
3. **WEBAPP_URL неправильний** - бот не розпізнає WebApp

**Рішення:**
```bash
# Перевірте на Render в Environment Variables:
WEBAPP_URL=https://taxi-bot-hciq.onrender.com/webapp/index.html
WEBHOOK_URL=https://taxi-bot-hciq.onrender.com
```

---

### Проблема 3: "Логи на Render є, але замовлення не продовжується"
**Причина:** Помилка в обробці даних у Python.

**Рішення:** Дивіться логи далі після `WEBAPP DATA RECEIVED`. Шукайте `ERROR` або `exception`.

Типові помилки:
```python
❌ Missing coordinates! lat=None, lon=None
❌ ERROR: message.web_app_data is None!
❌ JSON decode error
```

---

### Проблема 4: "Cannot read property 'lat' of null"
**Причина:** `selectedCoords` не встановлено перед натисканням кнопки.

**Рішення:** Спочатку натисніть на карту, ПОТІМ "Підтвердити".

---

## 📊 Контрольний список діагностики

Перед зверненням за допомогою, перевірте:

- [ ] WEBAPP_URL встановлено в Environment Variables
- [ ] WEBAPP_URL має формат: `https://your-app.onrender.com/webapp/index.html`
- [ ] WebApp відкривається через кнопку в боті (НЕ прямим посиланням)
- [ ] Сервіс на Render в статусі "Live" (зелений)
- [ ] Webhook налаштовано (`WEBHOOK_URL` або `RENDER=true`)
- [ ] Натискали на карту ПЕРЕД "Підтвердити місце"
- [ ] Дивилися логи JavaScript в Console
- [ ] Дивилися логи Python на Render

---

## 📤 Що надіслати для допомоги

Якщо проблема залишається, надішліть:

1. **Скріншот Console** (з логами після натискання "Підтвердити")
2. **Скріншот логів Render** (з часу натискання кнопки + 10 секунд)
3. **Environment Variables** (тільки WEBAPP_URL, без токенів!)
4. **Статус сервісу** (Live / Building / Failed)

---

## ✅ Очікувана поведінка (все працює)

1. Відкрили бота → Замовити таксі
2. Натиснули "🗺 Обрати на інтерактивній карті"
3. Карта відкрилася, клікнули на точку → маркер з'явився
4. Натиснули "✅ Підтвердити місце"
5. **Console:** `✅ tg.sendData() called successfully!`
6. Карта закрилася
7. **Render logs:** `🗺 WEBAPP DATA RECEIVED`
8. **Бот:** "✅ Місце подачі: вул. Хрещатик 1"
9. **Бот:** "📍 Куди їдемо?" ← **ВСЕ ПРАЦЮЄ!**

---

Створено: 2025-10-30
