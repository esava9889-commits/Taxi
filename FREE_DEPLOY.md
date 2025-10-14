# 💰 Безкоштовний деплой Telegram Taxi Bot

## 🎯 Безкоштовні платформи

| Платформа | Безкоштовно | RAM | Storage | Складність |
|-----------|-------------|-----|---------|------------|
| **Railway.app** ⭐ | $5 кредитів/міс | 512MB | 1GB | ⭐ Легко |
| **Fly.io** | 3 VM по 256MB | 256MB | 3GB | ⭐⭐ Середньо |
| **Oracle Cloud** | Завжди безкоштовно | 1GB | 50GB | ⭐⭐⭐ Складно |
| **Google Cloud** | $300 на 90 днів | 614MB | 10GB | ⭐⭐ Середньо |

---

## 🚀 Варіант 1: Railway.app (РЕКОМЕНДУЮ)

### ✅ Переваги:
- Найпростіше налаштування (2 хвилини)
- $5 безкоштовних кредитів/міс
- Автодеплой з GitHub
- Вбудований моніторинг

### 📦 Підготовка

**1. Отримайте BOT_TOKEN:**
```
Telegram → @BotFather → /newbot
```

**2. Push на GitHub:**
```bash
git add .
git commit -m "Deploy to Railway"
git push origin main
```

### 🚂 Деплой на Railway

**Крок 1: Створення проєкту (1 хв)**
1. Зайдіть на [railway.app](https://railway.app)
2. **Login with GitHub**
3. **New Project** → **Deploy from GitHub repo**
4. Оберіть `telegram-taxi-bot`

**Крок 2: Налаштування (1 хв)**
1. Railway автоматично визначить Python
2. Перейдіть у **Variables**
3. Додайте змінні:

```env
BOT_TOKEN=ваш_токен_від_botfather
ADMIN_IDS=6828579427
DB_PATH=data/taxi.sqlite3
GOOGLE_MAPS_API_KEY=ваш_ключ
PYTHONUNBUFFERED=1
TZ=Europe/Kiev
```

**Крок 3: Deploy**
- Railway автоматично задеплоїть
- Перейдіть в **Deployments** → **Logs**
- Шукайте: `🚀 Bot started successfully!`

**Крок 4: Volume для SQLite**
1. **Settings** → **Volumes** → **New Volume**
2. Mount Path: `/app/data`
3. Redeploy

### ✅ Готово!

**Перевірка:**
```
Telegram → Ваш бот → /start
```

**Моніторинг:**
- Railway Dashboard → **Metrics**
- **Logs** в реальному часі

**Вартість:**
- $5/міс кредитів (безкоштовно)
- Вистачить на ~500 годин роботи
- Після використання - сплата $5/міс

---

## 🪰 Варіант 2: Fly.io

### ✅ Переваги:
- Завжди безкоштовно (3 VM)
- 256 MB RAM кожна
- 3 GB persistent storage

### 📦 Підготовка

**1. Встановіть flyctl:**
```bash
# macOS
brew install flyctl

# Linux
curl -L https://fly.io/install.sh | sh

# Windows
pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"
```

**2. Логін:**
```bash
flyctl auth login
```

### 🚀 Деплой

**Крок 1: Створіть .env**
```bash
cp .env.example .env
nano .env  # Додайте BOT_TOKEN
```

**Крок 2: Ініціалізуйте додаток**
```bash
flyctl launch --no-deploy
```

Відповіді на запитання:
- App name: `telegram-taxi-bot` (або ваше)
- Region: `ams` (Amsterdam)
- PostgreSQL: **No**
- Redis: **No**

**Крок 3: Створіть volume**
```bash
flyctl volumes create taxi_data --size 1 --region ams
```

**Крок 4: Налаштуйте секрети**
```bash
flyctl secrets set BOT_TOKEN="ваш_токен"
flyctl secrets set GOOGLE_MAPS_API_KEY="ваш_ключ"
```

**Крок 5: Deploy**
```bash
flyctl deploy
```

**Крок 6: Перевірка**
```bash
flyctl logs
# Шукайте: "Bot started successfully"
```

### ✅ Готово!

**Команди:**
```bash
flyctl logs            # Логи
flyctl status          # Статус
flyctl ssh console     # SSH в контейнер
flyctl deploy          # Redeploy
```

---

## ☁️ Варіант 3: Oracle Cloud (Безкоштовно назавжди)

### ✅ Переваги:
- **Завжди безкоштовно** (Always Free)
- 1 GB RAM, 1 CPU
- 50 GB storage
- Немає обмежень за часом

### ⚠️ Недоліки:
- Складне налаштування
- Потрібна кредитна картка (не списується)

### 🚀 Деплой

**Крок 1: Створіть акаунт**
1. [cloud.oracle.com](https://cloud.oracle.com)
2. Sign Up → Always Free
3. Підтвердіть картку (не списується)

**Крок 2: Створіть VM**
1. Compute → Instances → **Create Instance**
2. Image: **Ubuntu 22.04** (Always Free eligible)
3. Shape: **VM.Standard.E2.1.Micro** (Always Free)
4. Network: Default
5. SSH Keys: Згенеруйте або завантажте свій
6. **Create**

**Крок 3: SSH підключення**
```bash
ssh ubuntu@ваш_ip
```

**Крок 4: Встановіть залежності**
```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip git -y
```

**Крок 5: Клонуйте репо**
```bash
git clone https://github.com/YOUR_USERNAME/telegram-taxi-bot.git
cd telegram-taxi-bot
```

**Крок 6: Налаштуйте**
```bash
cp .env.example .env
nano .env  # Додайте BOT_TOKEN
```

**Крок 7: Запустіть**
```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

**Крок 8: Systemd service (автозапуск)**
```bash
sudo cp telegram-taxi-bot.service /etc/systemd/system/
sudo nano /etc/systemd/system/telegram-taxi-bot.service
# Змініть User на ubuntu та WorkingDirectory

sudo systemctl enable telegram-taxi-bot
sudo systemctl start telegram-taxi-bot
sudo systemctl status telegram-taxi-bot
```

### ✅ Готово!

**Логи:**
```bash
sudo journalctl -u telegram-taxi-bot -f
```

---

## 🌐 Варіант 4: Google Cloud (90 днів безкоштовно)

### ✅ Переваги:
- $300 кредитів на 90 днів
- 614 MB RAM (e2-micro)
- Просте налаштування

### 🚀 Швидкий деплой

**Крок 1: Google Cloud Console**
1. [console.cloud.google.com](https://console.cloud.google.com)
2. Активуйте Free Trial ($300)
3. Compute Engine → VM Instances → **Create**

**Крок 2: Налаштування VM**
- Machine type: **e2-micro** (Free tier eligible)
- Boot disk: **Ubuntu 22.04 LTS**
- Firewall: Дозвольте SSH
- **Create**

**Крок 3: SSH та налаштування**
```bash
# У Google Cloud Console натисніть SSH
# Далі як Oracle Cloud (кроки 4-8)
```

---

## 📊 Порівняння безкоштовних варіантів

### За складністю:
1. **Railway.app** ⭐ - 2 хвилини
2. **Fly.io** ⭐⭐ - 10 хвилин
3. **Google Cloud** ⭐⭐ - 15 хвилин
4. **Oracle Cloud** ⭐⭐⭐ - 30 хвилин

### За надійністю:
1. **Oracle Cloud** - безкоштовно назавжди
2. **Fly.io** - безкоштовно назавжди
3. **Railway.app** - $5 кредитів/міс
4. **Google Cloud** - тільки 90 днів

### За простотою:
1. **Railway.app** - найпростіше
2. **Fly.io** - потрібен flyctl
3. **Google Cloud** - середньо
4. **Oracle Cloud** - найскладніше

---

## 🎯 Моя рекомендація

### Для початківців:
**Railway.app** - найпростіше, працює з коробки

### Для довгострокового використання:
**Fly.io** або **Oracle Cloud** - безкоштовно назавжди

### Якщо є $7/міс:
**Render.com** - найнадійніше (з першої інструкції)

---

## ⚠️ Важливі примітки

### Railway.app:
- $5/міс безкоштовно
- Після використання кредитів - автосплата
- Вистачить на ~24/7 роботу протягом місяця

### Fly.io:
- Безкоштовно назавжди
- Але 256MB RAM може бути мало при багатьох користувачах
- Рекомендую для тестування

### Oracle Cloud:
- Найкращий безкоштовний варіант
- Але складний для новачків
- Потрібна кредитна картка

---

## 🚀 Швидкий вибір

**Хочу швидко запустити:**
```bash
# Railway.app (2 хвилини)
git push origin main
# → railway.app → Deploy from GitHub
```

**Хочу безкоштовно назавжди:**
```bash
# Fly.io (10 хвилин)
flyctl launch
flyctl deploy
```

**Маю час налаштовувати:**
```bash
# Oracle Cloud (30 хвилин)
# Найнадійніше + безкоштовно назавжди
```

---

## 📞 Допомога

### Railway.app не працює:
- Перевірте логи в Dashboard
- Переконайтесь, що `railway.json` та `Procfile` є

### Fly.io помилки:
```bash
flyctl logs  # Подивіться помилки
flyctl ssh console  # SSH в контейнер
```

### Oracle/Google Cloud:
```bash
sudo journalctl -u telegram-taxi-bot -f
```

---

**Обирайте варіант та деплойте! 🚀**

Питання? Пишіть в issues на GitHub!
