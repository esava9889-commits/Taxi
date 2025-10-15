# 🚀 Інструкції для деплою на Render

## ❌ Проблема: ImportError на Render

```
ImportError: cannot import name 'DRIVER_TEXT' from 'app.handlers.start'
```

## 🔍 Причина:

На Render залишився **старий скомпільований Python кеш** (`.pyc` файли) з попередньої версії коду.

## ✅ Рішення:

### Варіант 1: Очистити Build Cache на Render (РЕКОМЕНДОВАНО)

1. Зайдіть в **Render Dashboard**
2. Оберіть ваш сервіс (Taxi Bot)
3. Перейдіть в **Settings**
4. Знайдіть секцію **Build & Deploy**
5. Натисніть **"Clear build cache"**
6. Натисніть **"Manual Deploy"** → **"Deploy latest commit"**

### Варіант 2: Force Redeploy

1. Зайдіть в Render Dashboard
2. Оберіть сервіс
3. Натисніть **"Manual Deploy"**
4. Оберіть **"Clear build cache & deploy"**

### Варіант 3: Додати команду очищення кешу

У файл `render.yaml` або в **Build Command** додайте:

```bash
# Очистити Python кеш перед запуском
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

# Встановити залежності
pip install -r requirements.txt
```

## 📋 Перевірка що код правильний:

### Локально перевірте:

```bash
# Очистити локальний кеш
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -name "*.pyc" -delete

# Перевірити синтаксис
python3 -m py_compile app/handlers/driver.py
python3 -m py_compile app/handlers/start.py
python3 -m py_compile app/handlers/order.py

# Запустити бота локально
python -m app.main
```

### Перевірити що немає DRIVER_TEXT:

```bash
# Не повинно нічого знайти:
grep -r "DRIVER_TEXT" app/ --include="*.py"
```

## 🔧 Налаштування Render:

### Build Command:
```bash
pip install -r requirements.txt
```

### Start Command:
```bash
python -m app.main
```

### Environment Variables (.env):
```env
BOT_TOKEN=your_bot_token
ADMIN_IDS=your_telegram_id
DRIVER_GROUP_CHAT_ID=-1001234567890
PAYMENT_CARD_NUMBER=4149 4999 0123 4567
```

## 📤 Запушити зміни:

```bash
# Переконайтеся що на правильній гілці
git branch
# Має бути: * fix-taxi-bot

# Додати .gitignore
git add .gitignore

# Закомітити
git commit -m "chore: Додано .gitignore для ігнорування Python кешу"

# Запушити на GitHub
git push origin fix-taxi-bot
```

## 🔄 Автоматичний деплой на Render:

Якщо налаштований auto-deploy з GitHub:

1. **Push на GitHub** (команди вище)
2. **Render автоматично** почне новий деплой
3. **Очистить кеш** автоматично (якщо .gitignore налаштований)
4. **Встановить залежності**
5. **Запустить бота**

## ⚠️ Важливо:

### Файли які НЕ повинні бути в репозиторії:

- ❌ `__pycache__/` (Python кеш)
- ❌ `*.pyc` (скомпільовані файли)
- ❌ `.env` (секретні дані)
- ❌ `data/*.sqlite3` (база даних)
- ✅ `.env.example` (приклад конфігурації) - OK

### Перевірка .gitignore:

```bash
git status

# Не повинно бути:
# - app/__pycache__/
# - app/**/*.pyc
# - .env (якщо є)
```

## 🎯 Після деплою:

1. Перейдіть в **Logs** на Render
2. Перевірте що немає помилок
3. Має з'явитись: `🚀 Bot started successfully!`
4. Напишіть боту `/start` для перевірки

## 📊 Checklist перед деплоєм:

- [ ] Код закомічений в гілку `fix-taxi-bot`
- [ ] Додано `.gitignore`
- [ ] Видалені всі `__pycache__` та `.pyc` файли
- [ ] Перевірено що немає `DRIVER_TEXT` в коді
- [ ] Запушено на GitHub
- [ ] Очищено Build Cache на Render
- [ ] Запущено Manual Deploy
- [ ] Перевірено логи

---

## 🆘 Якщо все одно помилка:

### SSH в Render (якщо доступно):

```bash
# Підключитись до сервера
render ssh your-service-name

# Очистити кеш вручну
cd /opt/render/project/src
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -name "*.pyc" -delete

# Перезапустити
exit
```

### Або створити новий сервіс:

1. Видалити старий сервіс на Render
2. Створити новий
3. Підключити до гілки `fix-taxi-bot`
4. Налаштувати Environment Variables
5. Deploy

---

**Готово!** Бот має запрацювати після очищення кешу 🎉
