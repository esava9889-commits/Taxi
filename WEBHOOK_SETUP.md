# 🎯 WEBHOOK НАЛАШТУВАННЯ

## 📖 Що таке Webhook?

**Webhook** - це спосіб отримання оновлень від Telegram **миттєво**, замість постійних запитів (Polling).

### Різниця:

| Режим | Затримка | Навантаження | Використання |
|-------|----------|--------------|--------------|
| **🔄 Polling** | 1-2 сек | Високе (постійні запити) | Розробка |
| **🎯 Webhook** | 0 сек | Низьке (тільки події) | Production |

---

## 🚀 АВТОМАТИЧНЕ ПЕРЕМИКАННЯ

Бот **автоматично** вибирає режим:

### 🎯 Webhook активується якщо:
- ✅ Встановлено `WEBHOOK_URL`
- ✅ Або встановлено `RENDER=1`
- ✅ Або встановлено `PRODUCTION=1`

### 🔄 Polling використовується якщо:
- ❌ Жодна з цих змінних не встановлена
- ❌ Локальна розробка

---

## 🔧 НАЛАШТУВАННЯ ДЛЯ РІЗНИХ ПЛАТФОРМ

### 1️⃣ RENDER.COM (Рекомендовано)

**Webhook активується АВТОМАТИЧНО!** 🎉

Render встановлює `RENDER=1`, тому webhook запуститься сам.

#### Опціонально: Встановити власний URL

```bash
# У Render Dashboard → Environment
WEBHOOK_URL=https://your-app.onrender.com
```

#### Перевірка:

Після deploy перевірте логи:
```
🎯 РЕЖИМ: WEBHOOK (Production)
✅ Webhook налаштовано успішно!
📍 URL: https://your-app.onrender.com/webhook/...
⚡ Бот отримуватиме оновлення МИТТЄВО
```

---

### 2️⃣ HEROKU

```bash
# У Heroku Dashboard → Settings → Config Vars
PRODUCTION=1
WEBHOOK_URL=https://your-app.herokuapp.com
```

---

### 3️⃣ VPS (з доменом та SSL)

```bash
# У .env файлі
PRODUCTION=1
WEBHOOK_URL=https://your-domain.com
```

**Вимоги:**
- ✅ HTTPS (обов'язково!)
- ✅ Валідний SSL сертифікат
- ✅ Порт 8080 (або інший з PORT)

---

### 4️⃣ ЛОКАЛЬНА РОЗРОБКА

**НЕ треба нічого налаштовувати!**

Якщо немає жодної ENV змінної → автоматично **Polling**

```bash
# Просто запустіть:
python -m app.main

# Побачите:
🔄 РЕЖИМ: POLLING (Development)
⚠️ Для production рекомендовано використовувати WEBHOOK
```

#### Якщо хочете тестувати Webhook локально:

Використовуйте **ngrok**:

```bash
# 1. Встановіть ngrok
brew install ngrok  # macOS
# або завантажте з https://ngrok.com

# 2. Запустіть тунель
ngrok http 8080

# 3. Встановіть URL
export WEBHOOK_URL=https://abc123.ngrok.io
export PRODUCTION=1

# 4. Запустіть бота
python -m app.main
```

---

## 📊 ПЕРЕВІРКА РЕЖИМУ

### Як дізнатись який режим активний?

Подивіться логи при запуску:

#### Webhook активний:
```
🎯 РЕЖИМ: WEBHOOK (Production)
✅ Webhook налаштовано успішно!
📍 URL: https://...
⚡ Бот отримуватиме оновлення МИТТЄВО
💰 Економія ресурсів: ~90%
```

#### Polling активний:
```
🔄 РЕЖИМ: POLLING (Development)
⚠️ Для production рекомендовано використовувати WEBHOOK
💡 Встановіть WEBHOOK_URL або PRODUCTION=1
```

---

## 🛠️ ENV ЗМІННІ

### Обов'язкові (для всіх режимів):
```bash
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=123456789
```

### Для Webhook (опціонально):
```bash
# Автоматично визначається на Render
WEBHOOK_URL=https://your-app.onrender.com

# Або просто увімкнути production режим
PRODUCTION=1

# Або на Render (встановлюється автоматично)
RENDER=1
```

### Для Render (автоматично):
```bash
RENDER=1                    # Встановлює Render
PORT=8080                   # Встановлює Render
RENDER_SERVICE_NAME=...     # Встановлює Render
```

---

## 🔍 ДІАГНОСТИКА

### Проблема: Webhook не працює

1. **Перевірте логи:**
   ```
   ❌ Помилка налаштування webhook: ...
   ```

2. **Перевірте URL:**
   - Має починатись з `https://` (не http!)
   - Має бути публічний (не localhost)
   - SSL сертифікат має бути валідний

3. **Перевірте в Telegram:**
   ```bash
   curl https://api.telegram.org/bot<YOUR_TOKEN>/getWebhookInfo
   ```

### Проблема: "Conflict" помилка

Означає що є інший процес бота.

**Рішення:**
```bash
# 1. Видалити webhook вручну
curl https://api.telegram.org/bot<YOUR_TOKEN>/deleteWebhook?drop_pending_updates=true

# 2. Перезапустити бота
```

---

## 📈 ПЕРЕВАГИ WEBHOOK

### Що отримуєте:

✅ **Швидкість:** Миттєві відповіді (0 сек затримки)  
✅ **Економія:** 90% менше CPU/RAM  
✅ **Масштабування:** Необмежена кількість користувачів  
✅ **Стабільність:** Менше запитів = менше помилок  
✅ **Професійність:** Стандарт для production  

### Цифри:

```
Polling:   43,200 запитів/день
Webhook:   100-1,000 запитів/день
Економія:  99.8% запитів!
```

---

## 🎯 РЕКОМЕНДАЦІЇ

### Для розробки:
- 🔄 **Polling** - просто і зручно
- Не треба SSL та публічного URL

### Для production:
- 🎯 **Webhook** - обов'язково!
- Набагато ефективніше
- Миттєві відповіді

---

## 📞 ПІДТРИМКА

Якщо виникли проблеми:

1. Перевірте логи при запуску
2. Переконайтесь що HTTPS працює
3. Перевірте getWebhookInfo в Telegram
4. Спробуйте видалити webhook і перезапустити

---

**Готово! Webhook налаштовано! 🎉**
