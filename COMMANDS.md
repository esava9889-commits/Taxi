# 📖 Довідник команд та API

## 🎮 Команди для всіх користувачів

### `/start`
Запуск бота та відображення головного меню

**Відповідь:**
```
Вітаємо у таксі-боті! Ось головне меню.

[Замовити таксі] [Зареєструватися]
[Стати водієм]   [Допомога]
```

---

### `/help`
Відображення довідки

**Відповідь:**
```
Натисніть 'Замовити таксі' щоб оформити поїздку.
'Зареєструватися' — створити профіль клієнта.
'Стати водієм' — подати заявку водія.
```

---

## 👤 Команди для клієнтів

### `/client`
Панель клієнта

**Відповідь:**
```
👤 Профіль клієнта

Ім'я: [Ваше ім'я]
Телефон: +380...
Зареєстровано: 2025-10-14

[🚖 Замовити таксі] [📜 Моя історія]
[ℹ️ Допомога]      [⭐️ Мій рейтинг]
```

---

### `/order`
Створення нового замовлення таксі

**Процес:**
1. Введення імені
2. Введення телефону
3. Надсилання геолокації або адреси початку
4. Надсилання адреси призначення
5. Опціональний коментар
6. Підтвердження

**Приклад відповіді:**
```
✅ Дякуємо! Ваше замовлення №1 прийнято.
🔍 Шукаємо водія...
✅ Знайдено водія!
```

---

### `/my_rating`
Переглянути свій рейтинг

**Відповідь:**
```
⭐️ Ваш рейтинг

⭐️⭐️⭐️⭐️⭐️
Середня оцінка: 5.00/5
```

---

## 🚗 Команди для водіїв

### `/driver`
Панель водія

**Відповідь:**
```
🚗 Панель водія

Статус: 🟢 Онлайн
ПІБ: Іванов Іван Іванович
Авто: Toyota Camry (АА1234ВВ)

💰 Заробіток сьогодні: 150.00 грн
💸 Комісія до сплати: 3.00 грн
💵 Чистий заробіток: 147.00 грн

[🟢 Онлайн]    [📊 Заробіток]
[📜 Історія]   [💳 Комісія]
[📍 Оновити геолокацію]
```

---

### `/register_driver`
Реєстрація як водій

**Процес:**
1. ПІБ
2. Номер телефону
3. Марка авто
4. Модель авто
5. Номерний знак
6. Фото посвідчення (опціонально)

**Відповідь:**
```
Заявку відправлено на модерацію. Очікуйте підтвердження.
```

---

### `/my_driver_status`
Переглянути статус заявки водія

**Відповідь:**
```
Статус заявки: approved
Авто: Toyota Camry (АА1234ВВ)
```

**Можливі статуси:**
- `pending` - На модерації
- `approved` - Підтверджено
- `rejected` - Відхилено

---

## 👑 Команди для адміністратора

### `/admin`
Адмін-панель

**Відповідь:**
```
🔐 Адмін-панель

Оберіть дію:

[📊 Статистика]      [👥 Модерація водіїв]
[💰 Тарифи]          [📋 Замовлення]
[📢 Розсилка]        [⚙️ Налаштування]
```

---

### `/orders`
Швидкий перегляд останніх замовлень

**Відповідь:**
```
📋 Останні замовлення:

✔️ №1 (completed)
Клієнт: Петренко Петро (+380671111111)
Маршрут: geo:... → ...
Створено: 2025-10-14 14:30
Вартість: 72.00 грн
```

---

### `/pending_drivers`
Швидкий перегляд заявок водіїв

**Відповідь:**
```
#1 Іванов Іван Іванович (+380501234567)
Авто: Toyota Camry (АА1234ВВ)
Статус: pending

[✅ Підтвердити] [❌ Відхилити]
```

---

### `/approve_driver <id>`
Підтвердження водія за ID

**Приклад:**
```
/approve_driver 1
```

**Відповідь:**
```
Водія #1 підтверджено.
```

---

### `/reject_driver <id>`
Відхилення заявки водія за ID

**Приклад:**
```
/reject_driver 1
```

**Відповідь:**
```
Заявку #1 відхилено.
```

---

## 🎹 Inline-кнопки (Callback Actions)

### Для водіїв (замовлення):

#### `order:accept:<order_id>`
Прийняти замовлення

**Приклад:** `order:accept:1`

**Ефект:**
- Статус замовлення → `accepted`
- Клієнт отримує дані водія
- Водій може почати поїздку

---

#### `order:reject:<order_id>`
Відхилити замовлення

**Приклад:** `order:reject:1`

**Ефект:**
- Замовлення залишається в статусі `offered`
- Може бути запропоновано іншому водію

---

#### `order:start:<order_id>`
Почати поїздку

**Приклад:** `order:start:1`

**Ефект:**
- Статус → `in_progress`
- Водій в статусі "В дорозі"
- Клієнт отримує сповіщення

---

#### `order:complete:<order_id>`
Завершити поїздку

**Приклад:** `order:complete:1`

**Ефект:**
- Статус → `completed`
- Розрахунок вартості та комісії
- Створення запису платежу
- Клієнт може оцінити водія

---

### Для клієнтів (рейтинги):

#### `rate:driver:<driver_tg_id>:<rating>:<order_id>`
Оцінити водія

**Приклад:** `rate:driver:123456789:5:1`

**Параметри:**
- `driver_tg_id` - Telegram ID водія
- `rating` - Оцінка (1-5)
- `order_id` - ID замовлення

**Ефект:**
- Створення запису рейтингу
- Сповіщення водія

---

### Для адміністратора:

#### `drv:approve:<driver_id>`
Підтвердити водія

**Приклад:** `drv:approve:1`

**Ефект:**
- Статус водія → `approved`
- Сповіщення водія

---

#### `drv:reject:<driver_id>`
Відхилити заявку

**Приклад:** `drv:reject:1`

**Ефект:**
- Статус водія → `rejected`
- Сповіщення водія

---

#### `tariff:edit`
Почати редагування тарифів

**Ефект:**
- Запуск діалогу зміни тарифів

---

#### `commission:paid`
Підтвердження сплати комісії

**Ефект:**
- Позначення всіх платежів водія як сплачених
- `commission_paid` → `true`

---

## 🗄️ API бази даних

### Users

```python
async def upsert_user(db_path: str, user: User) -> None
```
Створення або оновлення користувача

```python
async def get_user_by_id(db_path: str, user_id: int) -> Optional[User]
```
Отримання користувача за ID

---

### Drivers

```python
async def create_driver_application(db_path: str, driver: Driver) -> int
```
Створення заявки водія

```python
async def update_driver_status(db_path: str, driver_id: int, status: str) -> None
```
Оновлення статусу водія

```python
async def set_driver_online(db_path: str, tg_user_id: int, online: bool) -> None
```
Встановлення статусу онлайн/офлайн

```python
async def update_driver_location(db_path: str, tg_user_id: int, lat: float, lon: float) -> None
```
Оновлення геолокації водія

```python
async def fetch_online_drivers(db_path: str, limit: int = 50) -> List[Driver]
```
Отримання онлайн-водіїв

```python
async def get_driver_by_tg_user_id(db_path: str, tg_user_id: int) -> Optional[Driver]
```
Отримання водія за Telegram ID

---

### Orders

```python
async def insert_order(db_path: str, order: Order) -> int
```
Створення замовлення

```python
async def get_order_by_id(db_path: str, order_id: int) -> Optional[Order]
```
Отримання замовлення за ID

```python
async def offer_order_to_driver(db_path: str, order_id: int, driver_id: int) -> bool
```
Запропонувати замовлення водію

```python
async def accept_order(db_path: str, order_id: int, driver_id: int) -> bool
```
Прийняти замовлення

```python
async def start_order(db_path: str, order_id: int, driver_id: int) -> bool
```
Почати поїздку

```python
async def complete_order(db_path: str, order_id: int, driver_id: int, fare_amount: float, distance_m: int, duration_s: int, commission: float) -> bool
```
Завершити поїздку

```python
async def fetch_recent_orders(db_path: str, limit: int = 10) -> List[Order]
```
Отримання останніх замовлень

```python
async def get_user_order_history(db_path: str, user_id: int, limit: int = 10) -> List[Order]
```
Історія замовлень клієнта

```python
async def get_driver_order_history(db_path: str, driver_tg_id: int, limit: int = 10) -> List[Order]
```
Історія замовлень водія

---

### Tariffs

```python
async def insert_tariff(db_path: str, t: Tariff) -> int
```
Створення нового тарифу

```python
async def get_latest_tariff(db_path: str) -> Optional[Tariff]
```
Отримання останнього тарифу

---

### Ratings

```python
async def insert_rating(db_path: str, rating: Rating) -> int
```
Створення оцінки

```python
async def get_driver_average_rating(db_path: str, driver_user_id: int) -> Optional[float]
```
Середній рейтинг водія

---

### Payments

```python
async def insert_payment(db_path: str, payment: Payment) -> int
```
Створення запису платежу

```python
async def mark_commission_paid(db_path: str, driver_tg_id: int) -> None
```
Позначити комісію як сплачену

```python
async def get_driver_earnings_today(db_path: str, driver_tg_id: int) -> Tuple[float, float]
```
Заробіток водія за сьогодні (total, commission)

```python
async def get_driver_unpaid_commission(db_path: str, driver_tg_id: int) -> float
```
Несплачена комісія водія

---

## 🗺️ Google Maps API

### Distance Matrix

```python
async def get_distance_and_duration(
    api_key: str,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float
) -> Optional[Tuple[int, int]]
```

**Повертає:** `(distance_meters, duration_seconds)`

---

### Geocoding

```python
async def geocode_address(api_key: str, address: str) -> Optional[Tuple[float, float]]
```

**Повертає:** `(latitude, longitude)`

---

### Static Map

```python
def generate_static_map_url(
    api_key: str,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    width: int = 600,
    height: int = 400
) -> str
```

**Повертає:** URL статичної карти

---

## 🎯 Утиліти

### Matching

```python
async def find_nearest_driver(
    db_path: str,
    pickup_lat: float,
    pickup_lon: float
) -> Optional[Driver]
```
Знаходить найближчого онлайн-водія

```python
def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float
```
Розрахунок відстані за Haversine (метри)

```python
def parse_geo_coordinates(address: str) -> Optional[Tuple[float, float]]
```
Парсинг формату `geo:lat,lon`

---

### Scheduler

```python
async def start_scheduler(bot: Bot, db_path: str) -> None
```
Запуск планувальника завдань

```python
async def commission_reminder_task(bot: Bot, db_path: str) -> None
```
Щоденне нагадування о 20:00 UTC

---

## 📊 Структура даних

### Order статуси
- `pending` - Створено
- `offered` - Запропоновано водію
- `accepted` - Прийнято водієм
- `in_progress` - В процесі
- `completed` - Завершено
- `cancelled` - Скасовано

### Driver статуси
- `pending` - На модерації
- `approved` - Підтверджено
- `rejected` - Відхилено

### User roles
- `client` - Клієнт
- `driver` - Водій (окремо в таблиці drivers)

---

## 🔐 Права доступу

| Команда | Клієнт | Водій | Адміністратор |
|---------|--------|-------|---------------|
| `/start` | ✅ | ✅ | ✅ |
| `/help` | ✅ | ✅ | ✅ |
| `/client` | ✅ | ✅ | ✅ |
| `/order` | ✅ | ✅ | ✅ |
| `/my_rating` | ✅ | ✅ | ✅ |
| `/driver` | ❌ | ✅ | ✅ |
| `/register_driver` | ✅ | ✅ | ✅ |
| `/my_driver_status` | ❌ | ✅ | ✅ |
| `/admin` | ❌ | ❌ | ✅ |
| `/orders` | ❌ | ❌ | ✅ |
| `/pending_drivers` | ❌ | ❌ | ✅ |
| `/approve_driver` | ❌ | ❌ | ✅ |
| `/reject_driver` | ❌ | ❌ | ✅ |

---

**Версія документації: 1.0.0**
