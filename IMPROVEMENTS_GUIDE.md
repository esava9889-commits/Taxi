# 🚀 Покращення проекту - Інструкція

## 📋 ЩО БУЛО ДОДАНО

### 1. 🛡️ Централізована обробка помилок

**Файл:** `app/utils/error_handler.py`

**Можливості:**
- ✅ Автоматична класифікація помилок (LOW, MEDIUM, HIGH, CRITICAL)
- ✅ Детальне логування з контекстом (user_id, handler, state)
- ✅ Автоматичне сповіщення адміна про критичні помилки
- ✅ Збір статистики помилок

**Як працює:**
```python
# Middleware автоматично перехоплює всі помилки
dp.update.middleware(error_middleware)

# При помилці:
# 1. Визначається важливість (🟢 🟡 🟠 🔴)
# 2. Логується з контекстом
# 3. Якщо критична - сповіщається адмін
# 4. Додається до статистики
```

### 2. 📊 Система метрик

**Файл:** `app/utils/metrics.py`

**Можливості:**
- ✅ Збір метрик в реальному часі
- ✅ 3 формати виводу (JSON, HTML, Prometheus)
- ✅ Автоматичне оновлення з БД кожні 30 секунд
- ✅ Вимірювання часу відповіді

**Endpoints:**
- `/metrics` - JSON format
- `/metrics?format=html` - Красивий UI (оновлюється кожні 10 сек)
- `/metrics?format=prometheus` - Для Prometheus
- `/errors` - Статистика помилок

### 3. 🧪 Автоматичні тести

**Папка:** `tests/`

**Що покрито:**
- ✅ `test_validation.py` - Валідація телефонів, адрес, карток (50+ тестів)
- ✅ `test_rate_limiter.py` - Rate limiting (20+ тестів)
- ✅ `test_matching.py` - Розрахунок відстаней (15+ тестів)

**Налаштування:**
- `pytest.ini` - Конфігурація pytest
- `.coveragerc` - Налаштування покриття коду
- `tests/conftest.py` - Fixtures (готові дані для тестів)

### 4. 📝 Helper функції для метрик

**Файл:** `app/storage/db.py`

Додано функції:
- `count_users()` - Підрахунок користувачів
- `count_drivers()` - Підрахунок водіїв
- `count_online_drivers()` - Онлайн водії
- `count_orders()` - Всього замовлень
- `count_orders_by_status()` - Замовлення по статусу

---

## 🚀 ЯК ЗАПУСТИТИ

### 1. Оновити залежності

```bash
pip install -r requirements.txt
```

**Нові залежності:**
- `pytest` - Фреймворк для тестів
- `pytest-asyncio` - Async тести
- `pytest-cov` - Покриття коду
- `pytest-mock` - Moking

### 2. Запустити тести

```bash
# Всі тести
pytest

# З покриттям коду
pytest --cov=app --cov-report=html

# Тільки валідація
pytest tests/test_validation.py

# Verbose режим
pytest -v
```

**Переглянути звіт покриття:**
```bash
# Відкрити в браузері
open htmlcov/index.html
```

### 3. Запустити бота з новою системою

```bash
python -m app.main
```

**Що запуститься:**
- ✅ Error handling middleware
- ✅ Metrics middleware
- ✅ Фонове оновлення метрик (кожні 30 сек)
- ✅ HTTP endpoints: `/metrics`, `/errors`, `/health`

### 4. Переглянути метрики

**В браузері:**
```
http://localhost:8080/metrics?format=html
```

**В терміналі (JSON):**
```bash
curl http://localhost:8080/metrics | jq
```

**Статистика помилок:**
```bash
curl http://localhost:8080/errors | jq
```

---

## 📖 ЯК ВИКОРИСТОВУВАТИ

### Обробка помилок

#### Автоматично (рекомендовано)

Middleware **автоматично** обробляє всі помилки в хендлерах:

```python
@router.message(Command("test"))
async def test_handler(message: Message):
    # Не потрібно try/except!
    result = await risky_function()
    await message.answer(f"Result: {result}")
```

#### Вручну (якщо потрібен контроль)

```python
from app.utils.error_handler import handle_error, ErrorContext

try:
    await risky_operation()
except Exception as e:
    context = ErrorContext(
        user_id=message.from_user.id,
        handler="my_handler",
        state="SomeState"
    )
    await handle_error(e, context, bot)
```

### Перегляд метрик в боті

Додайте команду для адмінів:

```python
from app.utils.metrics import get_metrics_collector

@router.message(Command("stats"))
async def stats_command(message: Message, config: AppConfig):
    """Статистика бота (тільки для адміна)"""
    if message.from_user.id not in config.bot.admin_ids:
        return
    
    collector = get_metrics_collector()
    if not collector:
        await message.answer("❌ Метрики не ініціалізовані")
        return
    
    metrics = collector.get_metrics()
    await message.answer(
        metrics.to_human_readable(),
        parse_mode="HTML"
    )
```

### Написання нових тестів

1. **Створити файл:** `tests/test_mymodule.py`

2. **Написати тести:**

```python
import pytest
from app.mymodule import my_function

class TestMyFunction:
    """Тести для my_function"""
    
    def test_basic_case(self):
        """Базовий випадок"""
        result = my_function(input_data)
        assert result == expected_output
    
    def test_edge_case(self):
        """Граничний випадок"""
        result = my_function(None)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_async_function(self):
        """Async функція"""
        result = await my_async_function()
        assert result is not None
```

3. **Запустити:**

```bash
pytest tests/test_mymodule.py -v
```

---

## 🔧 НАЛАШТУВАННЯ

### Змінити частоту оновлення метрик

**Файл:** `app/utils/metrics.py:118`

```python
async def _update_loop(self):
    while True:
        await asyncio.sleep(30)  # ⬅️ Змінити тут (секунди)
        await self.update_from_db()
```

### Налаштувати класифікацію помилок

**Файл:** `app/utils/error_handler.py:88`

```python
# Додати патерни для критичних помилок
critical_patterns = [
    "database",
    "connection",
    # Додайте свої
    "payment",
    "billing",
]
```

### Додати нову метрику

**1. В `app/utils/metrics.py`:**

```python
@dataclass
class BotMetrics:
    # ... існуючі поля
    
    # Нова метрика
    total_revenue: float = 0.0
```

**2. Оновити в `update_from_db()`:**

```python
async def update_from_db(self):
    # ... існуючий код
    
    self.metrics.total_revenue = await get_total_revenue(self.db_path)
```

**3. Додати helper в `app/storage/db.py`:**

```python
async def get_total_revenue(db_path: str) -> float:
    """Підрахувати загальний дохід"""
    async with db_manager.connect(db_path) as db:
        async with db.execute(
            "SELECT SUM(fare_amount) FROM orders WHERE status = ?",
            ("completed",)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] else 0.0
```

---

## 📊 PRODUCTION SETUP

### 1. Render.com

**Environment Variables:**
```
WEBHOOK_URL=https://your-bot.onrender.com
```

**Endpoints:**
- Health: `https://your-bot.onrender.com/health`
- Metrics: `https://your-bot.onrender.com/metrics?format=html`
- Errors: `https://your-bot.onrender.com/errors`

### 2. UptimeRobot

Налаштуйте моніторинг:
- URL: `https://your-bot.onrender.com/health`
- Interval: 5 хвилин
- Alert: Email/Telegram при downtime

### 3. Prometheus (опціонально)

**prometheus.yml:**
```yaml
scrape_configs:
  - job_name: 'taxi-bot'
    static_configs:
      - targets: ['your-bot.onrender.com:443']
    scheme: https
    metrics_path: '/metrics'
    params:
      format: ['prometheus']
```

### 4. Grafana (опціонально)

Створіть dashboard з панелями:
- **Uptime** - gauge
- **Active Orders** - time series
- **Requests/min** - graph
- **Error Rate** - graph
- **Response Time** - histogram

---

## 🐛 TROUBLESHOOTING

### Тести падають з ImportError

**Проблема:**
```
ImportError: No module named 'app'
```

**Рішення:**
```bash
# Переконайтесь що запускаєте з root папки проекту
cd /workspace
pytest
```

### Metrics не оновлюються

**Проблема:** Metrics показують старі дані

**Рішення:**
```python
# Перезапустити background updates
collector = get_metrics_collector()
await collector.stop_background_updates()
await collector.start_background_updates()
```

### Coverage показує 0%

**Проблема:** Coverage не показує покриття

**Рішення:**
```bash
# Переконайтесь що coverage встановлено
pip install pytest-cov

# Запустити з правильними параметрами
pytest --cov=app --cov-report=term-missing
```

---

## 📚 ДОДАТКОВА ДОКУМЕНТАЦІЯ

- [ERROR_HANDLING_AND_MONITORING.md](ERROR_HANDLING_AND_MONITORING.md) - Повна документація
- [tests/README.md](tests/README.md) - Документація по тестах

---

## ✅ CHECKLIST

Перед deploy:

- [ ] Запустити всі тести: `pytest`
- [ ] Перевірити покриття: `pytest --cov=app`
- [ ] Перевірити що `/metrics` працює
- [ ] Перевірити що `/errors` працює
- [ ] Перевірити що адмін отримує сповіщення про критичні помилки
- [ ] Налаштувати UptimeRobot
- [ ] Перевірити логи на CRITICAL помилки

---

## 🎉 РЕЗУЛЬТАТ

### До покращень:
- ❌ Помилки губляться в логах
- ❌ Важко знайти причину багу
- ❌ Немає статистики
- ❌ Немає тестів

### Після покращень:
- ✅ Всі помилки класифіковані та залоговані
- ✅ Адмін отримує сповіщення про критичні баги
- ✅ Метрики в реальному часі (3 формати!)
- ✅ 85+ автоматичних тестів
- ✅ Покриття коду тестами
- ✅ Легко знайти і виправити баги

---

**Створено:** 2024-11-10  
**Автор:** AI Assistant  
**Версія:** 1.0
