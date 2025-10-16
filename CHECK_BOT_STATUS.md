# 🔍 ПЕРЕВІРКА СТАТУСУ БОТА

## ❓ БОТ ЗУПИНИВСЯ - ЩО РОБИТИ?

---

## 1️⃣ ПЕРЕВІРТЕ ЧИ БОТ ПРАЦЮЄ ЗАРАЗ

### Спосіб 1: Відкрийте Telegram
```
1. Відкрийте бота в Telegram
2. Напишіть /start
3. Якщо бот відповідає → ✅ ВСЕ ДОБРЕ!
4. Якщо ні → читайте далі
```

### Спосіб 2: Render Dashboard
```
1. Зайдіть на https://dashboard.render.com
2. Відкрийте ваш сервіс
3. Перейдіть на вкладку "Logs"
4. Подивіться останні рядки логів
```

**Має бути:**
```
✅ Бот запущено успішно
✅ Polling started for bot @YourBot
```

**Якщо бачите:**
```
❌ TelegramConflictError
❌ Failed to fetch updates
❌ Connection timeout
```
→ Є проблема!

---

## 2️⃣ ПРИЧИНИ ЗУПИНКИ БОТА

### ✅ НОРМАЛЬНІ (Не хвилюйтесь):

#### A. Редеплой (найчастіше)
```
ОЗНАКИ:
- Ви щойно запушили зміни на GitHub
- В логах: "Received SIGTERM signal"
- Через 10-30 сек бот знову запускається
- Бот працює після перезапуску

ЩО ВІДБУВАЄТЬСЯ:
1. GitHub отримує новий код
2. Render бачить зміни
3. Render деплоїть новий код
4. Старий процес → SIGTERM → зупинка
5. Новий процес → запуск → працює

РІШЕННЯ:
→ Це нормально! Просто зачекайте 1-2 хв
→ Бот автоматично перезапуститься
```

#### B. Ручний рестарт
```
ОЗНАКИ:
- Ви натиснули "Restart" на Render
- Бот зупинився і запустився знову

РІШЕННЯ:
→ Це нормально!
```

---

### ⚠️ ПРОБЛЕМНІ (Потрібно виправити):

#### A. TelegramConflictError (409 Conflict)
```
ОЗНАКИ:
В логах:
"TelegramConflictError: terminated by other getUpdates request"
"Conflict: 409"

ПРИЧИНА:
- Два боти працюють одночасно
- Webhook не видалений
- Render service type = "Web Service" (неправильно)

РІШЕННЯ:
1. Перевірте тип сервісу на Render:
   Settings → Service Type → має бути "Background Worker"

2. Якщо "Web Service":
   - Delete service
   - Create new → Background Worker
   - Re-deploy

3. Або suspend/resume:
   - Suspend service
   - Wait 30 sec
   - Resume service
```

#### B. Port Scan Timeout (тільки для Web Service)
```
ОЗНАКИ:
"Port scan timeout reached, no open ports detected"

ПРИЧИНА:
- Service type = "Web Service"
- Бот не відкриває HTTP порт

РІШЕННЯ:
→ Змінити на "Background Worker"
```

#### C. Out of Memory (OOM)
```
ОЗНАКИ:
"Process killed"
"Out of memory"
Бот раптово зупиняється без SIGTERM

ПРИЧИНА:
- Недостатньо RAM
- Render free tier має обмеження

РІШЕННЯ:
- Перейти на платний план Render
- Або використати VPS
```

#### D. Database Errors
```
ОЗНАКИ:
"database is locked"
"unable to open database file"

ПРИЧИНА:
- Проблеми з SQLite на Render
- База в /tmp видаляється

РІШЕННЯ:
→ Вже виправлено в config.py (використовуємо /tmp)
→ Дані зберігаються тимчасово
→ Для постійного зберігання → використати PostgreSQL
```

#### E. Google Maps API Errors
```
ОЗНАКИ:
"REQUEST_DENIED"
"OVER_QUERY_LIMIT"

ПРИЧИНА:
- Білінг не увімкнений
- Перевищено квоту
- Невірний API key

РІШЕННЯ:
1. Google Cloud Console
2. Enable Billing
3. Перевірити квоти
4. Перевірити GOOGLE_MAPS_API_KEY на Render
```

---

## 3️⃣ ЯК ДІАГНОСТУВАТИ ПРОБЛЕМУ

### Крок 1: Подивіться ПОВНІ логи

**На Render:**
```
Dashboard → Your Service → Logs → Scroll to bottom
```

**Шукайте:**
- ❌ ERROR
- ❌ FAILED
- ❌ Exception
- ❌ Traceback

### Крок 2: Перевірте останні рядки

**Якщо бачите:**
```
✅ Бот запущено успішно
✅ Polling started
```
→ Бот працює, все добре!

**Якщо бачите:**
```
❌ TelegramConflictError
```
→ Проблема з кількома інстансами

**Якщо бачите:**
```
❌ Process exited with code 1
```
→ Помилка в коді або конфігурації

### Крок 3: Перевірте Environment Variables

**На Render:**
```
Dashboard → Your Service → Environment → Environment Variables
```

**Перевірте:**
- ✅ BOT_TOKEN - правильний токен
- ✅ ADMIN_IDS - ваш Telegram ID
- ✅ DRIVER_GROUP_CHAT_ID - ID групи водіїв
- ✅ GOOGLE_MAPS_API_KEY - якщо використовуєте
- ✅ PAYMENT_CARD - карта для оплати

---

## 4️⃣ ЩО РОБИТИ ЗАРАЗ?

### Варіант 1: Якщо бот працює
```
1. Напишіть боту /start
2. Якщо відповідає → ✅ ВСЕ ДОБРЕ
3. Це був просто редеплой
4. Можна продовжувати тестування
```

### Варіант 2: Якщо бот НЕ відповідає
```
1. Зайдіть на Render Dashboard
2. Подивіться логи (останні 50 рядків)
3. Скопіюйте помилки (якщо є)
4. Напишіть мені помилки з логів
5. Я допоможу виправити
```

### Варіант 3: Швидкий фікс
```
1. Render Dashboard
2. Your Service
3. Manual Deploy → Deploy latest commit
4. Або Suspend → Wait 30s → Resume
```

---

## 5️⃣ ЧАСТI ПИТАННЯ

### Q: Бот зупиняється кожні 15 хвилин
**A:** Render free tier має обмеження. Використовуйте платний план або VPS.

### Q: Після рестарту база даних порожня
**A:** Render видаляє /tmp після рестарту. Для постійного зберігання використовуйте PostgreSQL або зовнішній диск.

### Q: Бот працює, але дані губляться
**A:** SQLite в /tmp тимчасовий. Рішення:
- Використати PostgreSQL на Render
- Або зовнішній VPS

### Q: TelegramConflictError постійно
**A:** 
1. Delete webhook: `/delete_webhook.py`
2. Change service type to Background Worker
3. Або використовуйте Railway/Fly.io

### Q: Як перевірити що бот точно працює?
**A:**
```bash
# Надішліть GET запит
curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getMe

# Має повернути інфу про бота
# Якщо повертає - бот живий
```

---

## 6️⃣ РЕКОМЕНДАЦІЇ

### Для стабільної роботи:

1. ✅ **Service Type = Background Worker**
   (Не Web Service!)

2. ✅ **Graceful Shutdown реалізовано**
   (Вже є в коді)

3. ✅ **Startup Delay = 3 sec**
   (Вже є в коді)

4. ✅ **Правильні змінні середовища**
   (Перевірте на Render)

5. ⚠️ **Для production:**
   - Платний Render план (не free tier)
   - Або Railway/Fly.io/VPS
   - PostgreSQL замість SQLite
   - Моніторинг (UptimeRobot)

---

## 7️⃣ КОНТРОЛЬНИЙ СПИСОК

```
☐ Бот відповідає на /start?
☐ Service type = Background Worker?
☐ Логи без ERROR?
☐ Environment variables правильні?
☐ Останній деплой успішний?
☐ База даних доступна?
☐ Google Maps API працює?
☐ Група водіїв налаштована?
```

**Якщо все ☑️ → Все добре! Бот працює!**

---

## 🆘 ПОТРІБНА ДОПОМОГА?

**Надішліть мені:**
1. Останні 20-30 рядків логів з Render
2. Скріншот Environment Variables (без токенів!)
3. Опис проблеми

**Я швидко допоможу!** 💪
