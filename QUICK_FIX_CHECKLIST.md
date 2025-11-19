# ⚡ ШВИДКИЙ ЧЕКЛИСТ: Виправлення карти

## 🚨 ГОЛОВНА ПРОБЛЕМА

**Render не може автоматично змінити `worker` → `web`**

Потрібно створити **новий Web Service** вручну!

---

## ✅ ЩО РОБИТИ (15 хвилин)

### 1️⃣ Відкрити Render Dashboard
👉 https://dashboard.render.com/

### 2️⃣ Створити новий Web Service
```
New + → Web Service
```

### 3️⃣ Підключити репозиторій
```
Repo: esava9889-commits/Taxi
Branch: fix-taxi-bot
```

### 4️⃣ Налаштувати
```
Name: telegram-taxi-bot-web
Build: pip install --upgrade pip && pip install -r requirements.txt
Start: python3 -m app.main
```

### 5️⃣ Додати Environment Variables
```
BOT_TOKEN=<твій токен>
DATABASE_URL=<твій postgresql>
PORT=10000
ADMIN_IDS=6828579427
```

### 6️⃣ Створити і дочекатися деплою
```
Create Web Service → Дочекайся ~5-10 хв
```

### 7️⃣ Скопіювати новий URL
```
https://telegram-taxi-bot-web-XXXX.onrender.com
```

### 8️⃣ Додати WEBAPP_URL
```
Environment → Add:
WEBAPP_URL=https://твій-url.onrender.com/webapp/index.html
```

### 9️⃣ Перезапустити
```
Manual Deploy → Deploy latest commit
```

### 🔟 Перевірити
```
https://твій-url.onrender.com/webapp/index.html
→ Має показатися карта! ✅
```

---

## 📱 ОНОВИТИ БОТА

Якщо змінився URL - оновити в Telegram:

```python
# Команда для оновлення webhook (якщо використовується)
# Або просто перезапустити бота - він використає новий WEBAPP_URL
```

---

## 🆘 ЯКЩО ЩОСЬ НЕ ТАК

### Карта 404
→ Перевір що це Web Service (не Worker!)

### Карта білий екран  
→ F12 → Console → Покажи помилку

### Бот не працює
→ Перевір BOT_TOKEN та DATABASE_URL

---

## 📄 ДЕТАЛЬНА ІНСТРУКЦІЯ

Дивись: `RENDER_MANUAL_SETUP.md`

---

**⏱ Час:** 15-20 хвилин  
**💰 Вартість:** $7/місяць (Starter plan)  
**✅ Результат:** Робоча карта!
