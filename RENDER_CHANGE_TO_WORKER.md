# 🔧 ЯК ЗМІНИТИ ТИП СЕРВІСУ НА RENDER

## 📋 ПОКРОКОВА ІНСТРУКЦІЯ З СКРІНШОТАМИ

### Крок 1: Відкрийте Render Dashboard

1. Перейдіть на https://dashboard.render.com
2. Увійдіть в акаунт
3. Знайдіть ваш сервіс (telegram-taxi-bot або taxi bot)

---

### Крок 2: Відкрийте Settings

```
Dashboard → [Ваш сервіс] → Settings (верхнє меню)
```

На сторінці Settings прокрутіть вниз до секції **"Instance Type"** або **"Service Details"**

---

### Крок 3: Змініть тип сервісу

**ВАЖЛИВО:** Render не дозволяє змінити тип існуючого сервісу напряму.

Є **2 способи**:

#### СПОСІБ 1: Видалити і створити заново (РЕКОМЕНДОВАНО) ⭐️

1. **Збережіть Environment Variables:**
   - Settings → Environment
   - Скопіюйте всі змінні (`BOT_TOKEN`, `ADMIN_IDS`, тощо)

2. **Видаліть старий сервіс:**
   - Settings → Прокрутіть донизу
   - Кнопка **"Delete Service"**
   - Підтвердіть видалення

3. **Створіть новий як Background Worker:**
   - Dashboard → **"New +"** → **"Background Worker"**
   - **Repository:** Ваш GitHub репозиторій
   - **Branch:** `fix-taxi-bot`
   - **Name:** telegram-taxi-bot
   - **Runtime:** Python 3
   - **Build Command:**
     ```bash
     pip install --upgrade pip && pip install -r requirements.txt
     ```
   - **Start Command:**
     ```bash
     python -m app.main
     ```

4. **Додайте Environment Variables:**
   ```
   BOT_TOKEN=ваш_токен_від_BotFather
   ADMIN_IDS=ваш_telegram_id
   DRIVER_GROUP_CHAT_ID=-1001234567890
   PAYMENT_CARD_NUMBER=5555555555555555
   RENDER=true
   PYTHONUNBUFFERED=1
   TZ=Europe/Kiev
   ```

5. **Create Background Worker**

6. **Зачекайте деплой** (~2-3 хвилини)

---

#### СПОСІБ 2: Suspend + Resume (ШВИДШЕ, АЛЕ НЕ ВИРІШУЄ КОРІНЬ)

Якщо не хочете видаляти:

1. **Ваш сервіс** → Кнопка **"Suspend"** (правий верхній кут)
2. **Зачекайте 30 секунд**
3. Кнопка **"Resume"**
4. Слідкуйте за логами

**Мінус:** Залишається Web Service, конфлікт може повторитись при наступному деплої.

---

## ✅ ПЕРЕВІРКА ПІСЛЯ СТВОРЕННЯ WORKER:

### У логах має бути:

```
==> Starting service with 'python -m app.main'
⏳ Затримка запуску 3s для graceful shutdown...
🚀 Bot started successfully!
✅ Webhook видалено, pending updates очищено
🔄 Запуск polling...
```

### НЕ має бути:

❌ `Port scan timeout`  
❌ `TelegramConflictError`  
❌ `Terminated by other getUpdates`

---

## 🎯 РІЗНИЦЯ МІЖ WEB SERVICE ТА BACKGROUND WORKER:

| Параметр | Web Service | Background Worker |
|----------|-------------|-------------------|
| **HTTP порт** | Обов'язковий | Не потрібен |
| **Health checks** | Так | Ні |
| **Port scanning** | Так (timeout після 10 хв) | Ні |
| **Ціна (free tier)** | Засипає через 15 хв | 750 год/місяць |
| **Для Telegram ботів** | ❌ Не підходить | ✅ Ідеально |

---

## 💰 ВАРТІСТЬ:

### Background Worker (що потрібно):
- **Free tier:** 750 годин/місяць
- Цього вистачить на **25 днів** безперервної роботи
- Після цього: $7/місяць за Starter план

### Альтернатива для безкоштовного:
Якщо потрібно безкоштовно 24/7:
- **Railway.app** - $5 credit щомісяця (безкоштовно)
- **Oracle Cloud** - завжди безкоштовно
- **Fly.io** - $5 credit одноразово

---

## 🆘 ЯКЩО ЩОСЬ НЕ ВИЙШЛО:

### Конфлікт досі є?

1. **Видаліть webhook через API:**
   ```
   https://api.telegram.org/bot<ВАШ_ТОКЕН>/deleteWebhook?drop_pending_updates=true
   ```

2. **Перевірте чи немає інших запущених інстансів:**
   - Інший деплой на Render
   - Локальний запуск на вашому комп'ютері
   - Railway/Heroku/VPS

3. **Зачекайте 1 хвилину** після Suspend перед Resume

4. **Перевірте логи Render** - має бути тільки ОДИН запуск бота

---

## 📞 ПІДТРИМКА:

Якщо виникли проблеми:
1. Перевірте `FIX_RENDER_CONFLICT.md`
2. Прочитайте логи на Render Dashboard
3. Переконайтесь що BOT_TOKEN правильний
4. Перевірте що тільки один інстанс запущений

**Після зміни на Background Worker конфлікти мають зникнути!** ✅
