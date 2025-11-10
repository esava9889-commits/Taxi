# 🚨 КРИТИЧНО: Ручне налаштування Render Web Service

## ⚠️ ПРОБЛЕМА

Render **НЕ МОЖЕ** автоматично змінити тип сервісу з `worker` на `web`.  
Потрібно створити НОВИЙ web service вручну.

---

## 📋 ПОКРОКОВА ІНСТРУКЦІЯ

### Крок 1: Зайти на Render Dashboard
```
https://dashboard.render.com/
```

### Крок 2: Видалити старий Worker Service (або залишити якщо потрібен)

**Опція A: Видалити** (рекомендовано якщо не використовується)
1. Знайти сервіс: `telegram-taxi-bot`
2. Settings → внизу "Delete Service"
3. Підтвердити

**Опція B: Залишити** (якщо використовується для чогось іншого)
- Просто створимо новий web service з іншою назвою

---

### Крок 3: Створити новий Web Service

#### 3.1 Натисніть "New +" → "Web Service"

#### 3.2 Підключіть GitHub репозиторій
```
Repository: esava9889-commits/Taxi
Branch: fix-taxi-bot
```

#### 3.3 Базові налаштування
```
Name: telegram-taxi-bot-web
Region: Frankfurt
Branch: fix-taxi-bot
Runtime: Python 3
```

#### 3.4 Build & Deploy
```
Build Command:
pip install --upgrade pip && pip install -r requirements.txt

Start Command:
python3 -m app.main
```

#### 3.5 Plan
```
Plan: Starter ($7/month) або Free (якщо доступний)
```

---

### Крок 4: Додати Environment Variables

**ОБОВ'ЯЗКОВІ:**

```bash
BOT_TOKEN=<твій_токен_від_BotFather>
DATABASE_URL=<твій_postgresql_url>
```

**РЕКОМЕНДОВАНІ:**

```bash
PORT=10000
ADMIN_IDS=6828579427
PYTHONUNBUFFERED=1
TZ=Europe/Kiev
DB_PATH=data/taxi.sqlite3
```

**ДЛЯ WEBAPP (додати ПІСЛЯ деплою!):**

```bash
WEBAPP_URL=https://твій-новий-url.onrender.com/webapp/index.html
```

⚠️ **WEBAPP_URL можна додати тільки після того як отримаєш URL!**

---

### Крок 5: Розпочати Deploy

1. Натисни "Create Web Service"
2. Дочекайся завершення білду (5-10 хвилин)
3. Перевір логи на помилки

---

### Крок 6: Отримати URL

Після успішного деплою Render покаже URL:
```
https://telegram-taxi-bot-web-XXXX.onrender.com
```

**Скопіюй цей URL!**

---

### Крок 7: Додати WEBAPP_URL

1. Перейди в **Environment** вкладку
2. Додай нову змінну:
   ```
   Key: WEBAPP_URL
   Value: https://твій-url.onrender.com/webapp/index.html
   ```
3. **Save Changes**

---

### Крок 8: Перезапустити сервіс

1. Manual Deploy → "Clear build cache & deploy"
2. АБО просто "Deploy latest commit"

---

### Крок 9: Перевірити

#### A) Перевірка в браузері:
```bash
# Health check
https://твій-url.onrender.com/health

# WebApp
https://твій-url.onrender.com/webapp/index.html
```

**Очікуваний результат:**
- ✅ `/health` → `{"status":"ok",...}`
- ✅ `/webapp/index.html` → Карта завантажується

#### B) Перевірка в Telegram:
1. Відкрий бота
2. `/order` → "🗺 Обрати на карті"
3. Карта відкривається

---

## 🐛 TROUBLESHOOTING

### Проблема: Build Failed

**Причина:** Відсутні залежності або помилки в коді

**Рішення:**
1. Перевір логи білду
2. Переконайся що `requirements.txt` на місці
3. Перевір що гілка `fix-taxi-bot` активна

---

### Проблема: Service Exits (код 1)

**Причина:** Відсутній BOT_TOKEN або DATABASE_URL

**Рішення:**
1. Environment → Додай BOT_TOKEN
2. Додай DATABASE_URL (PostgreSQL)
3. Перезапусти сервіс

---

### Проблема: 404 на /webapp/

**Причина:** webapp папка не знайдена

**Рішення:**
1. Перевір що файли в `webapp/` в репозиторії
2. Перевір логи: "🗺️ Static files enabled"
3. Якщо немає - перевір шлях в main.py

---

### Проблема: Карта білий екран

**Причина:** JavaScript помилки або CORS

**Рішення:**
1. F12 → Console → Шукай помилки
2. Перевір WEBAPP_URL (має бути правильний)
3. Перевір що всі JS виправлення застосовані

---

## ✅ ФІНАЛЬНИЙ ЧЕКЛИСТ

- [ ] Створено новий Web Service
- [ ] Додано BOT_TOKEN
- [ ] Додано DATABASE_URL
- [ ] Деплой успішний
- [ ] Отримано URL
- [ ] Додано WEBAPP_URL
- [ ] Перезапущено сервіс
- [ ] /health працює
- [ ] /webapp/index.html показує карту
- [ ] Карта працює в Telegram боті

---

## 📞 ЯКЩО НЕ ПРАЦЮЄ

Надішли:
1. URL нового web service
2. Скріншот Environment Variables
3. Логи з Render (останні 50 рядків)
4. Скріншот помилки в браузері (F12 → Console)

---

**Створено:** 2025-11-10  
**Важливість:** 🚨 КРИТИЧНО  
**Час виконання:** 15-20 хвилин
