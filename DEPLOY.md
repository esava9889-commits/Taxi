# 🚀 Інструкція з деплою на Render.com

## 📋 Зміст

1. [Швидкий деплой через Blueprint](#швидкий-деплой-через-blueprint)
2. [Ручний деплой](#ручний-деплой)
3. [Налаштування змінних середовища](#налаштування-змінних-середовища)
4. [Перевірка роботи](#перевірка-роботи)
5. [Troubleshooting](#troubleshooting)

---

## 🎯 Швидкий деплой через Blueprint

### Крок 1: Підготовка

1. **Створіть репозиторій на GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Initial commit: Telegram Taxi Bot"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/telegram-taxi-bot.git
   git push -u origin main
   ```

2. **Отримайте необхідні ключі:**
   - **BOT_TOKEN**: Створіть бота через [@BotFather](https://t.me/BotFather)
   - **GOOGLE_MAPS_API_KEY** (опціонально): [Google Cloud Console](https://console.cloud.google.com/)

### Крок 2: Деплой на Render

1. **Зайдіть на [Render.com](https://render.com)** і авторизуйтесь

2. **Натисніть "New +" → "Blueprint"**

3. **Підключіть GitHub репозиторій:**
   - Оберіть ваш репозиторій `telegram-taxi-bot`
   - Render автоматично знайде `render.yaml`

4. **Назва Blueprint:**
   - Введіть: `Telegram Taxi Bot`

5. **Натисніть "Apply"**

### Крок 3: Налаштування змінних

Render попросить ввести змінні, які позначені `sync: false`:

1. **BOT_TOKEN** (обов'язково):
   ```
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

2. **GOOGLE_MAPS_API_KEY** (опціонально):
   ```
   AIzaSyABCDEF1234567890
   ```

3. Натисніть **"Create Resources"**

### Крок 4: Очікування деплою

- Render почне білд (~2-3 хвилини)
- Після успішного білду бот автоматично запуститься
- Перевірте логи: **Logs** → Побачите `🚀 Bot started successfully!`

---

## 🔧 Ручний деплой

Якщо не хочете використовувати Blueprint:

### Крок 1: Створення сервісу

1. На Render.com натисніть **"New +" → "Worker"**

2. **Підключіть репозиторій:**
   - Connect GitHub → Оберіть ваш репозиторій

3. **Налаштування:**
   ```
   Name: telegram-taxi-bot
   Environment: Python
   Region: Frankfurt (ближче до України)
   Branch: main
   Runtime: Python 3.11
   Build Command: pip install -r requirements.txt
   Start Command: python3 -m app.main
   Plan: Starter ($7/mo)
   ```

### Крок 2: Додавання змінних середовища

В розділі **Environment**, додайте:

| Key | Value |
|-----|-------|
| `BOT_TOKEN` | `ваш_токен_від_botfather` |
| `ADMIN_IDS` | `6828579427` |
| `DB_PATH` | `data/taxi.sqlite3` |
| `GOOGLE_MAPS_API_KEY` | `ваш_api_ключ` (опціонально) |
| `PYTHONUNBUFFERED` | `1` |
| `TZ` | `Europe/Kiev` |

### Крок 3: Додавання Disk

1. Scroll down до **Disks**
2. Натисніть **"Add Disk"**
3. **Налаштування:**
   ```
   Name: taxi-bot-data
   Mount Path: /opt/render/project/src/data
   Size: 1 GB
   ```

### Крок 4: Деплой

Натисніть **"Create Worker"** → Деплой почнеться автоматично

---

## ⚙️ Налаштування змінних середовища

### Обов'язкові:

#### `BOT_TOKEN`
**Як отримати:**
1. Відкрийте [@BotFather](https://t.me/BotFather) в Telegram
2. Надішліть `/newbot`
3. Вкажіть назву: `My Taxi Bot`
4. Вкажіть username: `my_taxi_bot` (має бути унікальний)
5. Скопіюйте токен: `123456789:ABCdefGHI...`

**Формат:**
```
123456789:ABCdefGHIjklMNOpqrsTUVwxyz
```

### Опціональні:

#### `GOOGLE_MAPS_API_KEY`
**Як отримати:**
1. Перейдіть на [Google Cloud Console](https://console.cloud.google.com/)
2. Створіть новий проєкт
3. Увімкніть APIs:
   - **Distance Matrix API**
   - **Geocoding API**
   - **Static Maps API**
4. Створіть API Key
5. Обмежте ключ (рекомендовано):
   - API restrictions → Restrict key
   - Оберіть три API вище

**Формат:**
```
AIzaSyABCDEF1234567890_example
```

**Що дає Google Maps API:**
- ✅ Точний розрахунок відстані та часу
- ✅ Автоматичне визначення найближчого водія
- ✅ Генерація статичних карт

**Без Google Maps API:**
- ⚠️ Оціночний розрахунок (5 км, 10 хв)
- ⚠️ Менш точний підбір водія

#### `ADMIN_IDS`
**За замовчуванням:** `6828579427`

**Як додати більше адмінів:**
```
6828579427,123456789,987654321
```
або через пробіл:
```
6828579427 123456789 987654321
```

#### `TZ` (Timezone)
**За замовчуванням:** `Europe/Kiev`

Для нагадувань о 20:00 за вашим часом:
- Київ: `Europe/Kiev`
- Москва: `Europe/Moscow`
- Варшава: `Europe/Warsaw`
- UTC: `UTC`

---

## ✅ Перевірка роботи

### 1. Перевірка логів

В Render Dashboard → **Logs**, ви повинні побачити:

```
INFO - 🚀 Bot started successfully!
INFO - Started polling
INFO - Received message from user: /start
```

### 2. Тестування бота

1. **Відкрийте вашого бота в Telegram**
2. Надішліть `/start`
3. **Очікуваний результат:**
   ```
   Вітаємо у таксі-боті! Ось головне меню.
   
   [Замовити таксі] [Зареєструватися]
   [Стати водієм]   [Допомога]
   ```

### 3. Перевірка адмін-панелі

1. Надішліть `/admin`
2. **Очікуваний результат (якщо ваш ID = 6828579427):**
   ```
   🔐 Адмін-панель
   
   Оберіть дію:
   
   [📊 Статистика]      [👥 Модерація водіїв]
   [💰 Тарифи]          [📋 Замовлення]
   ```

### 4. Налаштування тарифів

**Обов'язково після першого запуску:**

```
/admin → 💰 Тарифи → ✏️ Змінити тарифи
```

Введіть:
- Базова ціна: `50`
- Ціна за км: `8`
- Ціна за хвилину: `2`
- Мінімальна сума: `60`

---

## 🔄 Оновлення бота

### Автоматичне оновлення (якщо `autoDeploy: true`):

```bash
git add .
git commit -m "Update: новий функціонал"
git push origin main
```

Render автоматично задеплоїть нову версію (~2-3 хв)

### Ручне оновлення:

В Render Dashboard → **Manual Deploy** → "Deploy latest commit"

---

## 📊 Моніторинг

### Перегляд логів:

**В реальному часі:**
```
Render Dashboard → Logs
```

**Фільтрація:**
- `ERROR` - тільки помилки
- `INFO` - загальна інформація
- `WARNING` - попередження

### Метрики:

**Render Dashboard → Metrics:**
- CPU Usage
- Memory Usage
- Restart count

**Рекомендовані показники:**
- CPU: < 50%
- Memory: < 256 MB
- Restarts: 0 (крім оновлень)

---

## 🐛 Troubleshooting

### Проблема 1: Бот не запускається

**Симптоми:**
```
ERROR - BOT_TOKEN is not set
```

**Рішення:**
1. Перейдіть в **Environment**
2. Додайте `BOT_TOKEN` з вашим токеном
3. Натисніть **Save Changes**
4. Manual Deploy → Deploy

### Проблема 2: База даних не зберігається

**Симптоми:**
- Після рестарту всі дані зникають

**Рішення:**
1. Перевірте, чи додано **Disk**
2. Mount Path має бути: `/opt/render/project/src/data`
3. `DB_PATH` = `data/taxi.sqlite3`
4. Redeploy

### Проблема 3: Бот не відповідає

**Симптоми:**
- Бот онлайн, але не відповідає на команди

**Перевірки:**
1. **Логи:** Чи є помилки?
   ```
   Render Dashboard → Logs → Search "ERROR"
   ```

2. **Polling активний?**
   ```
   Logs → Шукайте "Started polling"
   ```

3. **Webhook видалено?**
   - Бот автоматично видаляє webhook при старті
   - Якщо раніше використовували webhook, перезапустіть

**Рішення:**
```
Manual Deploy → Deploy
```

### Проблема 4: Google Maps API не працює

**Симптоми:**
- Відстань не розраховується
- "Оцінка маршруту" не показується

**Перевірки:**
1. Чи додано `GOOGLE_MAPS_API_KEY`?
2. Чи увімкнені API в Google Cloud?
   - Distance Matrix API ✅
   - Geocoding API ✅
   - Static Maps API ✅
3. Чи є квота на API?

**Рішення:**
- Без API: бот працює з оціночними значеннями
- З API: перевірте налаштування в Google Cloud Console

### Проблема 5: Нагадування не приходять о 20:00

**Симптоми:**
- Водії не отримують SMS о 20:00

**Перевірки:**
1. Чи встановлено `TZ=Europe/Kiev`?
2. Чи є у водіїв несплачена комісія?

**Рішення:**
1. Додайте змінну `TZ`:
   ```
   Environment → Add → TZ = Europe/Kiev
   ```
2. Redeploy

### Проблема 6: Out of Memory

**Симптоми:**
```
ERROR - Process killed (out of memory)
```

**Рішення:**
1. Upgrade план до Standard ($25/mo)
2. Або оптимізуйте код (зменшіть ліміти в fetch_online_drivers)

---

## 💰 Вартість

### Free Plan:
- ❌ Worker не підтримується на Free

### Starter Plan ($7/mo):
- ✅ 512 MB RAM
- ✅ 0.5 CPU
- ✅ Достатньо для ~100 активних користувачів
- ✅ 1 GB Disk (безкоштовно)

### Standard Plan ($25/mo):
- ✅ 2 GB RAM
- ✅ 1 CPU
- ✅ Для ~1000+ користувачів

**Рекомендація:** Starter Plan для початку

---

## 🔐 Безпека

### Рекомендації:

1. **Не коммітьте .env файл:**
   ```bash
   # .gitignore вже налаштований
   echo ".env" >> .gitignore
   ```

2. **Обмежте Google Maps API Key:**
   - Google Cloud Console → Credentials
   - Restrict key → API restrictions

3. **Регулярно перевіряйте логи:**
   ```
   Render → Logs → Filter "ERROR"
   ```

4. **Бекап бази даних:**
   - Download disk snapshot (щомісяця)
   - Або export через SQLite команди

---

## 📞 Підтримка

### Офіційна документація:
- [Render Docs](https://render.com/docs)
- [Render Blueprint Spec](https://render.com/docs/blueprint-spec)

### Render Support:
- Dashboard → Help → Chat Support

---

## ✅ Чеклист перед запуском

- [ ] GitHub репозиторій створено
- [ ] `render.yaml` в корені проєкту
- [ ] Отримано `BOT_TOKEN` від @BotFather
- [ ] (Опціонально) Отримано `GOOGLE_MAPS_API_KEY`
- [ ] Blueprint створено на Render
- [ ] Змінні середовища налаштовані
- [ ] Disk додано (1 GB)
- [ ] Деплой успішний (логи: "Bot started successfully")
- [ ] Бот відповідає на `/start`
- [ ] Адмін-панель працює (`/admin`)
- [ ] Тарифи налаштовані
- [ ] Тестове замовлення створено

---

**Готово! Ваш бот працює на Render! 🚀**

Для тестування всіх функцій дивіться `TESTING.md`
