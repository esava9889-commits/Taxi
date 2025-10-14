# ⚡ Швидкий деплой за 5 хвилин

## 🎯 Render.com (Рекомендовано)

### Крок 1: Отримайте токен (2 хв)
1. Telegram → [@BotFather](https://t.me/BotFather)
2. `/newbot` → Введіть назву та username
3. Скопіюйте токен: `123456789:ABC...`

### Крок 2: Push на GitHub (1 хв)
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/telegram-taxi-bot.git
git push -u origin main
```

### Крок 3: Deploy на Render (2 хв)
1. Відкрийте [Render.com](https://render.com)
2. **New +** → **Blueprint**
3. Підключіть GitHub репозиторій
4. Додайте змінні:
   - `BOT_TOKEN`: вставте ваш токен
   - `GOOGLE_MAPS_API_KEY`: (пропустіть, додасте пізніше)
5. **Apply**

### ✅ Готово! Перевірка:
1. Render → **Logs** → Шукайте `🚀 Bot started successfully!`
2. Telegram → Відкрийте бота → `/start`
3. `/admin` → Налаштуйте тарифи (50, 8, 2, 60)

---

## 🐳 Docker (Локально)

### Крок 1: Створіть .env (1 хв)
```bash
cp .env.example .env
nano .env  # Додайте BOT_TOKEN
```

### Крок 2: Запустіть (1 хв)
```bash
docker-compose up -d
```

### ✅ Готово! Перевірка:
```bash
docker-compose logs -f  # Шукайте "Bot started successfully"
```

---

## 🖥️ VPS (Ubuntu/Debian)

### Крок 1: Автоматично (2 хв)
```bash
./deploy.sh vps
```

### Крок 2: Запуск (1 хв)
```bash
source venv/bin/activate
python -m app.main
```

### ✅ Готово! Для production:
```bash
sudo cp telegram-taxi-bot.service /etc/systemd/system/
sudo systemctl enable telegram-taxi-bot
sudo systemctl start telegram-taxi-bot
```

---

## ❓ Проблеми?

### Бот не запускається
```
ERROR: BOT_TOKEN is not set
```
**Рішення:** Додайте `BOT_TOKEN` в змінні середовища

### Render показує помилку
```
ERROR: No module named 'aiogram'
```
**Рішення:** Переконайтесь, що `requirements.txt` є в репозиторії

### Бот не відповідає
**Рішення:** Перевірте логи: `Render → Logs` або `docker-compose logs -f`

---

## 📖 Детальна інструкція

Якщо щось не вийшло, читайте:
- **DEPLOY.md** - Детальна інструкція (800+ рядків)
- **DEPLOYMENT_COMPARISON.md** - Порівняння варіантів
- **TESTING.md** - Тестування всіх функцій

---

**Успіхів! 🚀**
