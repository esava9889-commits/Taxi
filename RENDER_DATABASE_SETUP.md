# 🗄️ ІНСТРУКЦІЯ: ПІДКЛЮЧЕННЯ PostgreSQL НА RENDER

## 📋 КРОК 1: СТВОРЕННЯ БАЗИ ДАНИХ

1. Відкрий https://dashboard.render.com
2. Натисни **"New +"** → **"PostgreSQL"**
3. Заповни форму:

   ```
   Name: taxi-bot-db
   Database: taxi_bot
   User: taxi_bot_user
   Region: Frankfurt (EU Central)
   PostgreSQL Version: 16
   Instance Type: FREE ← ВАЖЛИВО!
   ```

4. Натисни **"Create Database"**
5. Почекай 2-3 хвилини...

---

## 🔑 КРОК 2: СКОПІЮВАТИ DATABASE URL

Після створення БД:

1. Відкрий створену базу даних
2. Прокрути вниз до секції **"Connections"**
3. Знайди **"Internal Database URL"**
4. Натисни на іконку **"Copy"** 📋

Приклад URL:
```
postgres://taxi_bot_user:пароль@dpg-xxxxx/taxi_bot
```

⚠️ **КОПІЮЙ САМЕ "Internal Database URL"** - не "External"!

---

## 🔧 КРОК 3: ДОДАТИ DATABASE_URL ДО СЕРВІСУ

1. Відкрий твій сервіс бота (telegram-taxi-bot)
2. Перейди в **"Environment"** (ліве меню)
3. Знайди змінну **"DATABASE_URL"**
4. Вставити скопійований URL
5. Натисни **"Save Changes"**

---

## 🚀 КРОК 4: РЕДЕПЛОЙ БОТА

Render автоматично перезапустить бота з новою БД!

Перевір логи:
```
🐘 Ініціалізація PostgreSQL...
🐘 PostgreSQL виявлено: postgresql://...
✅ Всі таблиці PostgreSQL створено!
✅ PostgreSQL готова!
```

---

## ✅ ВСЕ ГОТОВО!

Тепер дані зберігаються в PostgreSQL:
✅ Дані НЕ зникають при перезапуску
✅ Автоматичні бекапи кожні 24 години
✅ Можна підключитися через pgAdmin
✅ Масштабується для великої кількості замовлень

---

## 🔍 ЯК ПЕРЕВІРИТИ ЩО ПРАЦЮЄ?

1. Перегляд логів бота:
   - Має бути: "🐘 Ініціалізація PostgreSQL..."
   - Має бути: "✅ PostgreSQL готова!"

2. Зареєструй клієнта
3. Перезапусти бот (Manual Deploy)
4. Клієнт має залишитись в БД ✅

---

## 💾 ЛОКАЛЬНА РОЗРОБКА

Для локальної розробки бот автоматично використовує SQLite:
```bash
# Без DATABASE_URL → SQLite
python -m app.main
```

Для тестування з PostgreSQL локально:
```bash
# З DATABASE_URL → PostgreSQL
export DATABASE_URL="postgresql://..."
python -m app.main
```

---

## 🆘 ПРОБЛЕМИ?

### Помилка: "asyncpg not found"
```bash
pip install asyncpg
```

### Помилка: "connection refused"
Перевір що DATABASE_URL правильний (Internal URL, не External)

### Дані не зберігаються
Перевір логи - має бути "✅ PostgreSQL готова!"

---

## 📊 БЕЗКОШТОВНИЙ ПЛАН RENDER PostgreSQL:

✅ 256 MB SSD  
✅ Спільний CPU  
✅ SSL підключення  
✅ Автоматичні бекапи (24 год)  
⚠️ Видаляється через 90 днів БЕЗ активності  
⚠️ Обмежена швидкість  

**Для таксі бота цього ДОСТАТНЬО!** 🎉

Просто використовуй бота хоча б раз на тиждень, і БД не видалиться.
