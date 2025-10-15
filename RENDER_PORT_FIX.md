# ⚠️ ВИПРАВЛЕННЯ: Port scan timeout на Render

## 🔴 Проблема:

```
Timed out: Port scan timeout reached, no open ports detected
Received SIGTERM signal
```

## 🎯 Причина:

Render створив ваш бот як **Web Service** (очікує HTTP порт), але Telegram бот використовує **polling** (не відкриває порти) → Render чекає 60 секунд → не бачить порту → вбиває процес.

---

## ✅ РІШЕННЯ (виберіть одне):

### ВАРІАНТ 1: Background Worker (НАЙКРАЩЕ!) ⭐️

**Переваги:**
- ✅ Правильний тип для Telegram ботів
- ✅ Безкоштовний план
- ✅ Не очікує портів
- ✅ Автоматичний перезапуск

**Як зробити:**

#### Крок 1: Видалити старий сервіс

1. Render Dashboard → ваш сервіс
2. **Settings** → прокрутіть до **Delete Service**
3. Введіть назву сервісу для підтвердження
4. Натисніть **Delete**

⚠️ Не хвилюйтесь! Код на GitHub збережений.

#### Крок 2: Створити Background Worker

1. Render Dashboard → **New +**
2. Оберіть **Background Worker**
3. **Connect** ваш GitHub репозиторій
4. **Configure:**

```
Name: taxi-bot
Environment: Python 3
Branch: fix-taxi-bot
Region: Frankfurt (або ближчий до вас)

Build Command:
pip install -r requirements.txt

Start Command:
python -m app.main
```

#### Крок 3: Додати Environment Variables

Натисніть **Advanced** → **Add Environment Variable**:

```
BOT_TOKEN=ваш_токен_від_BotFather
ADMIN_IDS=ваш_telegram_id
DRIVER_GROUP_CHAT_ID=-1001234567890
PAYMENT_CARD_NUMBER=4149 4999 0123 4567
RENDER=true
```

#### Крок 4: Deploy

1. Натисніть **Create Background Worker**
2. Чекайте 2-3 хвилини
3. **Logs** → має з'явитись `🚀 Bot started successfully!`

**✅ Готово!** Бот працює без помилок про порти.

---

### ВАРІАНТ 2: Залишити Web Service + додати HTTP сервер

**Якщо не хочете перестворювати сервіс:**

Я вже додав HTTP сервер в код! Тепер бот:
- Відкриває порт для Render (health check)
- Працює як Telegram бот (polling)

**Що треба зробити:**

1. На Render перевірте що є змінна:
   ```
   RENDER=true
   ```

2. **Manual Deploy** → **Clear build cache & deploy**

3. Бот запуститься і відкриє порт

**Health check endpoints:**
- `https://ваш-сервіс.onrender.com/` → OK
- `https://ваш-сервіс.onrender.com/health` → OK

---

## 🔍 ЯК ПЕРЕВІРИТИ ЩО ПРАЦЮЄ:

### На Render:

1. **Logs** має показувати:
```
🌐 Health check server started on port 10000
🚀 Bot started successfully!
Start polling for bot @YourBot...
```

2. **Статус** має бути: 🟢 **Live**

### В Telegram:

1. Напишіть боту `/start`
2. Має прийти привітання з кнопками
3. Якщо працює - все ОК! ✅

---

## ⚠️ ВАЖЛИВО: База даних

**На Render БД зберігається в `/tmp/`** - це ephemeral storage!

**Що це означає:**
- ❌ БД **очищується** при кожному деплої
- ❌ БД **видаляється** при рестарті сервісу
- ❌ Всі дані (користувачі, замовлення) **втрачаються**

**Рішення для production:**

### Варіант А: PostgreSQL на Render (рекомендовано)

1. Render → **New +** → **PostgreSQL**
2. Назва: taxi-bot-db
3. Plan: Free
4. **Create Database**
5. Скопіюйте **Internal Database URL**
6. Додайте в Environment Variables вашого бота:
   ```
   DATABASE_URL=postgresql://...
   ```
7. Оновіть код для використання PostgreSQL (можу допомогти)

### Варіант Б: Render Disk (платно)

1. Render → Settings вашого сервісу
2. **Disks** → **Add Disk**
3. Name: taxi-data
4. Mount Path: /data
5. Size: 1GB (мінімум)
6. В .env:
   ```
   DB_PATH=/data/taxi.sqlite3
   ```

### Варіант В: Зовнішня БД

- MongoDB Atlas (безкоштовно)
- Supabase (безкоштовно)
- PlanetScale (безкоштовно)

---

## 📋 ЧЕКЛИСТ:

**Виберіть один варіант:**

### Варіант 1: Background Worker
- [ ] Видалити Web Service
- [ ] Створити Background Worker
- [ ] Додати Environment Variables
- [ ] Deploy
- [ ] Перевірити логи

### Варіант 2: Web Service з HTTP
- [ ] Додати RENDER=true в Environment
- [ ] Clear build cache & deploy
- [ ] Перевірити що порт відкрився
- [ ] Перевірити бота в Telegram

**В обох випадках:**
- [ ] Налаштувати постійну БД (PostgreSQL/Disk)
- [ ] Створити групу водіїв
- [ ] Додати DRIVER_GROUP_CHAT_ID

---

## 🚀 Код вже на GitHub!

Останній коміт: `cbbb28b` - Виправлено Port timeout

**Гілка:** `fix-taxi-bot`

Тепер просто задеплойте на Render одним з варіантів вище!

---

**Рекомендація:** Використовуйте **Background Worker** - це правильно для Telegram ботів! 🎯
