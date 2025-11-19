# 🛡️ Обробка помилок та моніторинг

Цей документ описує систему обробки помилок та моніторингу в Telegram Taxi Bot.

## 📊 Огляд

Бот використовує централізовану систему для:
- 🔍 **Автоматичного виявлення** та класифікації помилок
- 📝 **Детального логування** з контекстом
- 🚨 **Сповіщення адміна** про критичні помилки
- 📈 **Збору метрик** продуктивності
- 📊 **Моніторингу** в реальному часі

---

## 🛡️ СИСТЕМА ОБРОБКИ ПОМИЛОК

### Рівні важливості помилок

Помилки автоматично класифікуються за важливістю:

| Рівень | Emoji | Опис | Дії |
|--------|-------|------|------|
| `LOW` | 🟢 | Не критично | Тільки логування (DEBUG) |
| `MEDIUM` | 🟡 | Потрібна увага | Логування (WARNING) |
| `HIGH` | 🟠 | Серйозна помилка | Логування + traceback |
| `CRITICAL` | 🔴 | Критична помилка | Логування + сповіщення адміна |

### Автоматична класифікація

Система автоматично визначає важливість помилки:

```python
# КРИТИЧНІ помилки (бот може не працювати)
- Database errors
- Connection errors
- Authentication errors

# ВИСОКІ помилки (щось пішло не так)
- API timeouts
- Network errors
- Permission errors

# СЕРЕДНІ помилки (очікувані помилки)
- Validation errors
- Invalid input
- Not found errors

# НИЗЬКІ помилки (не критичні)
- "message is not modified"
- "message can't be deleted"
- User blocked bot
```

### Використання

#### В коді хендлерів

Middleware **автоматично** обробляє всі помилки:

```python
@router.message(Command("test"))
async def test_handler(message: Message):
    # Не потрібно try/except - middleware все зробить
    result = await some_risky_function()
    await message.answer(f"Result: {result}")
```

#### Ручна обробка (якщо потрібен контроль)

```python
from app.utils.error_handler import handle_error, ErrorContext

try:
    await risky_operation()
except Exception as e:
    # Передати контекст помилки
    context = ErrorContext(
        user_id=message.from_user.id,
        handler="test_handler",
        message_text=message.text
    )
    await handle_error(e, context, bot)
```

### Що логується?

При помилці зберігається:
- ✅ Тип помилки (`TypeError`, `ValueError`, тощо)
- ✅ Повідомлення помилки
- ✅ ID користувача
- ✅ ID чату
- ✅ Назва хендлера
- ✅ Текст повідомлення
- ✅ Callback data
- ✅ FSM state
- ✅ Traceback (для HIGH/CRITICAL)

### Сповіщення адміна

При **критичній** помилці адмін отримує Telegram повідомлення:

```
🔴 КРИТИЧНА ПОМИЛКА В БОТІ

Тип: DatabaseError
Повідомлення: connection refused

Час: 2024-11-10 15:30:45
Користувач: 123456789
Хендлер: order_handler
Стан: OrderStates:confirm

<traceback>
```

### API для статистики помилок

**Endpoint:** `/errors`

```bash
curl http://localhost:8080/errors
```

**Відповідь:**
```json
{
  "total_errors": 15,
  "critical_errors": 2,
  "errors_by_type": {
    "ValueError": 8,
    "KeyError": 5,
    "DatabaseError": 2
  },
  "last_10_errors": [
    {
      "type": "ValueError",
      "severity": "MEDIUM",
      "timestamp": "2024-11-10T15:30:45"
    }
  ]
}
```

---

## 📊 СИСТЕМА МЕТРИК

### Що відстежується?

#### 👥 Користувачі
- Всього користувачів
- Всього водіїв
- Онлайн водіїв

#### 🚖 Замовлення
- Всього замовлень
- Активних замовлень
- Завершених замовлень
- Скасованих замовлень

#### ⚡ Продуктивність
- Середній час відповіді
- Запитів за хвилину
- Всього запитів

#### ❌ Помилки
- Всього помилок
- Критичних помилок
- Помилок за годину

### Endpoints для моніторингу

#### 1. JSON format (за замовчуванням)

```bash
curl http://localhost:8080/metrics
```

**Відповідь:**
```json
{
  "uptime": "2г 15хв",
  "uptime_seconds": 8100,
  "users": {
    "total": 150,
    "total_drivers": 25,
    "active_drivers": 8
  },
  "orders": {
    "total": 342,
    "active": 5,
    "completed": 320,
    "cancelled": 17
  },
  "performance": {
    "avg_response_time": 0.234,
    "total_requests": 1250,
    "requests_per_minute": 12.5
  },
  "errors": {
    "total": 15,
    "critical": 2,
    "per_hour": 1.85
  }
}
```

#### 2. HTML format (для браузера)

```bash
curl http://localhost:8080/metrics?format=html
```

Відкрийте в браузері: `http://your-bot.com/metrics?format=html`

- 🔄 Авто-оновлення кожні 10 секунд
- 🎨 Красивий UI з кольорами
- 📊 Всі метрики в зручному вигляді

#### 3. Prometheus format

```bash
curl http://localhost:8080/metrics?format=prometheus
```

**Відповідь:**
```
# HELP bot_uptime_seconds Bot uptime in seconds
# TYPE bot_uptime_seconds gauge
bot_uptime_seconds 8100

# HELP bot_users_total Total number of users
# TYPE bot_users_total counter
bot_users_total 150

# HELP bot_orders_active Active orders
# TYPE bot_orders_active gauge
bot_orders_active 5
```

**Використання з Prometheus:**

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'taxi-bot'
    static_configs:
      - targets: ['your-bot.com:8080']
    metrics_path: '/metrics'
    params:
      format: ['prometheus']
```

### Інтеграція з Grafana

1. Додайте Prometheus як Data Source в Grafana
2. Створіть dashboard з панелями:
   - **Uptime** - gauge
   - **Active Orders** - graph
   - **Requests/minute** - graph
   - **Error Rate** - graph

---

## 🚀 ЯК ВИКОРИСТОВУВАТИ

### Локальна розробка

1. **Запустити бота**
   ```bash
   python -m app.main
   ```

2. **Відкрити metrics в браузері**
   ```
   http://localhost:8080/metrics?format=html
   ```

3. **Переглянути логи**
   ```bash
   tail -f logs/bot.log
   ```

### Production (Render)

1. **Metrics endpoint**
   ```
   https://your-bot.onrender.com/metrics?format=html
   ```

2. **Налаштувати моніторинг**
   - UptimeRobot - перевірка доступності
   - Sentry - збір помилок
   - Prometheus + Grafana - метрики

### Telegram команда (для адмінів)

Можна додати команду для перегляду метрик в боті:

```python
@router.message(Command("stats"))
async def stats_command(message: Message):
    """Показати статистику (тільки для адміна)"""
    if message.from_user.id not in config.bot.admin_ids:
        return
    
    collector = get_metrics_collector()
    if collector:
        metrics = collector.get_metrics()
        await message.answer(
            metrics.to_human_readable(),
            parse_mode="HTML"
        )
```

---

## 🔧 НАЛАШТУВАННЯ

### Змінити частоту оновлення метрик

В `app/utils/metrics.py`:

```python
async def _update_loop(self):
    while True:
        await asyncio.sleep(30)  # ⬅️ Змінити тут (секунди)
        await self.update_from_db()
```

### Додати нову метрику

1. **Додати поле в `BotMetrics`:**
   ```python
   @dataclass
   class BotMetrics:
       # ... існуючі поля
       
       # Нова метрика
       total_revenue: float = 0.0
   ```

2. **Оновити в `update_from_db()`:**
   ```python
   async def update_from_db(self):
       # ... існуючий код
       
       # Оновити нову метрику
       self.metrics.total_revenue = await get_total_revenue(self.db_path)
   ```

3. **Додати в `to_dict()` та `to_prometheus_format()`**

### Налаштувати сповіщення

В `app/utils/error_handler.py`:

```python
# Змінити список критичних патернів
critical_patterns = [
    "database",
    "connection",
    # Додати свої патерни
    "payment",
    "billing",
]
```

---

## 📈 BEST PRACTICES

### 1. Регулярно переглядайте метрики

- **Кожен день:** Перевіряйте помилки
- **Кожен тиждень:** Аналізуйте trends
- **Кожен місяць:** Оптимізуйте вузькі місця

### 2. Налаштуйте alerts

Використовуйте UptimeRobot або Pingdom для:
- ✅ Перевірки `/health` кожні 5 хвилин
- ✅ Сповіщення при downtime
- ✅ SSL certificate expiry alerts

### 3. Збирайте feedback користувачів

Додайте команду `/report` для звітів про баги:

```python
@router.message(Command("report"))
async def report_bug(message: Message, state: FSMContext):
    """Дозволити користувачам звітувати про баги"""
    await state.set_state(BugReportStates.description)
    await message.answer("Опишіть проблему:")
```

### 4. Використовуйте structured logging

```python
logger.info(
    "Order created",
    extra={
        "order_id": order.id,
        "user_id": user.id,
        "fare": order.fare_amount
    }
)
```

---

## 🐛 TROUBLESHOOTING

### Metrics не оновлюються

**Проблема:** Метрики показують старі дані

**Рішення:**
```python
# Перевірити чи запущено background updates
collector = get_metrics_collector()
await collector.start_background_updates()
```

### Занадто багато помилок

**Проблема:** `/errors` показує багато помилок

**Рішення:**
1. Перевірити логи: `tail -f logs/bot.log`
2. Знайти найчастіші помилки
3. Виправити код
4. Скинути статистику (restart бота)

### Адмін не отримує сповіщення

**Проблема:** Критичні помилки не приходять в Telegram

**Рішення:**
1. Перевірити `ADMIN_IDS` в `.env`
2. Перевірити що бот не заблокований адміном
3. Перевірити логи на помилки відправки

---

## 📚 ДОДАТКОВІ РЕСУРСИ

- [Документація logging (Python)](https://docs.python.org/3/library/logging.html)
- [Prometheus документація](https://prometheus.io/docs/)
- [Grafana tutorials](https://grafana.com/tutorials/)

---

**Останнє оновлення:** 2024-11-10
