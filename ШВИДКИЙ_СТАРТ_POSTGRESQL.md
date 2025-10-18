# 🚀 ШВИДКИЙ СТАРТ: POSTGRESQL НА RENDER

## ⏱️ 5 ХВИЛИН ДО ЗБЕРЕЖЕННЯ ДАНИХ!

---

### 📍 КРОК 1: СТВОРИ БД (2 хв)

1. Відкрий https://dashboard.render.com
2. Натисни **"New +"** → **"PostgreSQL"**
3. Введи:
   - **Name:** `taxi-bot-db`
   - **Database:** `taxi_bot`  
   - **Region:** `Frankfurt (EU Central)`
   - **Instance Type:** **FREE** ← ВАЖЛИВО!
4. Натисни **"Create Database"**

⏳ Почекай 2 хв...

---

### 📍 КРОК 2: СКОПІЮЙ URL (1 хв)

Після створення БД:

1. **Connections** → **Internal Database URL**
2. Натисни **📋 Copy**

Виглядає так:
```
postgres://taxi_bot_user:password123@dpg-abc123/taxi_bot
```

⚠️ **ОБОВ'ЯЗКОВО "Internal"** (не External)!

---

### 📍 КРОК 3: ДОДАЙ ДО БОТА (1 хв)

1. Відкрий твій бот-сервіс
2. **Environment** (ліве меню)
3. Знайди **DATABASE_URL**
4. **Вставити** скопійований URL
5. **Save Changes**

Render автоматично перезапустить! ⚡

---

### 📍 КРОК 4: ПЕРЕВІР ЛОГИ (1 хв)

1. **Logs** (ліве меню)
2. Шукай:

```
🐘 Ініціалізація PostgreSQL...
✅ Всі таблиці PostgreSQL створено!
✅ PostgreSQL готова!
```

✅ Якщо бачиш це - **ВСЕ ПРАЦЮЄ!**

---

## 🎉 ГОТОВО!

Тепер:
- ✅ Дані **НЕ зникають** при перезапуску
- ✅ Автоматичні **бекапи** (24 год)
- ✅ **Безкоштовно** (256 MB)

---

## ❓ ЯКЩО ЩОСЬ НЕ ТАК:

### Бачу помилку: "asyncpg not found"
→ Render має автоматично встановити з requirements.txt
→ Почекай 3-5 хв після Save Changes

### Бачу: "connection refused"
→ Перевір що скопіював **Internal** URL (не External)
→ Перевір що URL починається з `postgres://`

### Все ще SQLite в логах
→ DATABASE_URL не встановлено
→ Перевір Environment Variables

---

## 💡 ПІДКАЗКА:

Якщо хочеш переключитись назад на SQLite:
1. Environment → DATABASE_URL
2. Видали значення
3. Save Changes

Бот автоматично використає SQLite! 📁

