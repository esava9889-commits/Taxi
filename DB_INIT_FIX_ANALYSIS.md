# 🔍 ГЛИБОКИЙ АНАЛІЗ: Помилка ініціалізації БД

**Дата:** 2025-10-18  
**Помилка:** `sqlite3.OperationalError: no such table: drivers`  
**Пріоритет:** 🔴 КРИТИЧНИЙ

---

## ❌ ПРОБЛЕМА

### Помилка:
```python
sqlite3.OperationalError: no such table: drivers
```

### Місце виникнення:
```python
# Будь-де де викликається:
await get_driver_by_tg_user_id(db_path, user_id)
# або інші функції що працюють з drivers
```

---

## 🔍 АНАЛІЗ ПРИЧИНИ

### Було (НЕПРАВИЛЬНО):

```python
# db.py

async def ensure_driver_columns(db_path: str) -> None:
    """Міграція: додати колонки до drivers"""
    async with aiosqlite.connect(db_path) as db:
        # ❌ ПОМИЛКА: Робота з таблицею drivers БЕЗ перевірки існування!
        async with db.execute("PRAGMA table_info(drivers)") as cur:
            columns = await cur.fetchall()  # ← ПАДАЄ якщо таблиці немає!


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        # ❌ ПОМИЛКА: Міграція ПЕРЕД створенням таблиці!
        await ensure_driver_columns(db_path)  # ← Таблиці ще немає!
        
        # Створення таблиць...
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS drivers (
                ...
            )
            """
        )
```

### Послідовність помилки:

```
1. Запускається init_db()
   ↓
2. Викликається ensure_driver_columns()
   ↓
3. Спроба: PRAGMA table_info(drivers)
   ↓
4. ❌ ПОМИЛКА: no such table: drivers
   (Таблиця ще не створена!)
   ↓
5. БД НЕ ініціалізується
   ↓
6. При спробі get_driver_by_tg_user_id()
   ↓
7. ❌ ПОМИЛКА: no such table: drivers
```

---

## ✅ ВИПРАВЛЕННЯ

### 1️⃣ Додано перевірку існування таблиці

```python
async def ensure_driver_columns(db_path: str) -> None:
    """Міграція: додати відсутні колонки до drivers"""
    import logging
    logger = logging.getLogger(__name__)
    
    async with aiosqlite.connect(db_path) as db:
        # ✅ ВИПРАВЛЕННЯ #1: Перевірити чи таблиця існує
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='drivers'"
        ) as cur:
            table_exists = await cur.fetchone()
        
        if not table_exists:
            logger.info("ℹ️  Таблиця drivers ще не створена, пропускаю міграцію")
            return  # ← Вийти без помилки!
        
        # Тепер безпечно працювати з таблицею
        async with db.execute("PRAGMA table_info(drivers)") as cur:
            columns = await cur.fetchall()
            col_names = [c[1] for c in columns]
        
        # Додати колонки якщо потрібно...
```

### 2️⃣ Перенесено виклик міграції в КІНЕЦЬ

```python
async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        # ❌ ВИДАЛЕНО: await ensure_driver_columns(db_path)
        
        # Створення ВСІХ таблиць...
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_addresses (...)
            """
        )
        
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (...)
            """
        )
        
        # ... інші таблиці ...
        
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS drivers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_user_id INTEGER NOT NULL,
                # ... всі поля ...
                car_class TEXT NOT NULL DEFAULT 'economy',
                card_number TEXT
            )
            """
        )
        
        # ... індекси ...
        
        await db.commit()
    
    # ✅ ВИПРАВЛЕННЯ #2: Міграція ПІСЛЯ створення таблиць!
    await ensure_driver_columns(db_path)
```

---

## 📊 РЕЗУЛЬТАТ

### До виправлення:

```
Запуск бота:
1. init_db() викликається
2. ensure_driver_columns() намагається працювати з drivers
3. ❌ ПОМИЛКА: no such table: drivers
4. БД НЕ ініціалізується
5. Бот НЕ працює
```

### Після виправлення:

```
Запуск бота:
1. init_db() викликається
2. Створюються ВСІ таблиці (включно з drivers)
3. await db.commit()
4. ensure_driver_columns() перевіряє існування таблиці
5. Таблиця існує → додає колонки якщо потрібно
6. ✅ БД ініціалізована
7. ✅ Бот працює
```

---

## 🧪 ТЕСТУВАННЯ

### Тест 1: Нова БД (таблиць немає)

```python
# Запуск на пустій БД
await init_db("new_db.db")

# Очікуємо:
✅ CREATE TABLE drivers створює таблицю
✅ ensure_driver_columns() перевіряє існування
✅ Таблиця є, але колонки вже створені
✅ Міграція не потрібна
✅ Успіх!
```

### Тест 2: Стара БД (без car_class, card_number)

```python
# БД існує, але немає нових колонок
await init_db("old_db.db")

# Очікуємо:
✅ CREATE TABLE IF NOT EXISTS drivers (таблиця вже є, skip)
✅ ensure_driver_columns() перевіряє існування
✅ Таблиця є
✅ Перевіряє колонки
❌ car_class - немає
❌ card_number - немає
✅ ALTER TABLE додає колонки
✅ Міграція успішна!
```

### Тест 3: Актуальна БД (всі колонки є)

```python
# БД з усіма колонками
await init_db("current_db.db")

# Очікуємо:
✅ CREATE TABLE IF NOT EXISTS drivers (таблиця вже є, skip)
✅ ensure_driver_columns() перевіряє існування
✅ Таблиця є
✅ Перевіряє колонки
✅ car_class - є
✅ card_number - є
✅ Міграція не потрібна
✅ Успіх!
```

---

## 🔍 ПОВНИЙ СПИСОК ТАБЛИЦЬ

Після ініціалізації БД має містити:

1. **saved_addresses** - збережені адреси
2. **orders** - замовлення
3. **tariffs** - тарифи
4. **users** - користувачі (клієнти)
5. **drivers** - водії ✅
6. **ratings** - оцінки
7. **client_ratings** - оцінки клієнтів
8. **tips** - чайові
9. **referrals** - реферали
10. **payments** - платежі

### Колонки drivers:

```sql
CREATE TABLE drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    car_make TEXT NOT NULL,
    car_model TEXT NOT NULL,
    car_plate TEXT NOT NULL,
    license_photo_file_id TEXT,
    city TEXT,
    status TEXT NOT NULL,  -- pending | approved | rejected
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    online INTEGER NOT NULL DEFAULT 0,
    last_lat REAL,
    last_lon REAL,
    last_seen_at TEXT,
    car_class TEXT NOT NULL DEFAULT 'economy',  -- ← Нова!
    card_number TEXT  -- ← Нова!
)
```

---

## 🛡️ ЗАХИСТ ВІД МАЙБУТНІХ ПОМИЛОК

### 1. Порядок ініціалізації:

```python
async def init_db(db_path: str) -> None:
    # 1. Створити з'єднання
    async with aiosqlite.connect(db_path) as db:
        # 2. Створити ВСІ таблиці
        await db.execute("CREATE TABLE IF NOT EXISTS ...")
        # ... всі таблиці ...
        
        # 3. Створити індекси
        await db.execute("CREATE INDEX IF NOT EXISTS ...")
        
        # 4. Закомітити
        await db.commit()
    
    # 5. ТІЛЬКИ ТЕПЕР міграції
    await ensure_driver_columns(db_path)
```

### 2. Безпечні міграції:

```python
async def ensure_XXX_columns(db_path: str):
    """Міграція для таблиці XXX"""
    async with aiosqlite.connect(db_path) as db:
        # ЗАВЖДИ перевіряти існування таблиці!
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='XXX'"
        ) as cur:
            if not await cur.fetchone():
                logger.info("Таблиця XXX не існує, пропускаю")
                return  # ← Безпечний вихід
        
        # Працювати з таблицею...
```

### 3. Логування:

```python
logger.info("ℹ️  Таблиця drivers ще не створена")  # INFO, не ERROR
logger.info("⚙️  Міграція: додаю колонку card_number...")
logger.info("✅ Колонка card_number додана")
```

---

## 📝 CHECKLIST ВИПРАВЛЕНЬ

- [x] Додано перевірку існування таблиці в `ensure_driver_columns()`
- [x] Видалено виклик міграції з початку `init_db()`
- [x] Додано виклик міграції в КІНЕЦЬ `init_db()`
- [x] Створено тестовий скрипт `test_db_init.py`
- [x] Створено документацію `DB_INIT_FIX_ANALYSIS.md`
- [x] Перевірено порядок створення таблиць
- [x] Перевірено що drivers створюється з car_class та card_number

---

## 🎯 ВИСНОВОК

**Проблема:** Міграція викликалася ПЕРЕД створенням таблиці

**Рішення:** 
1. Додана перевірка існування таблиці
2. Міграція перенесена в КІНЕЦЬ init_db()

**Результат:**
- ✅ БД ініціалізується правильно
- ✅ Міграції працюють безпечно
- ✅ Немає помилки "no such table"

**Статус:** ✅ ГОТОВО ДО ДЕПЛОЮ

---

**Файли змінені:**
- `app/storage/db.py` - виправлено init_db() та ensure_driver_columns()
- `test_db_init.py` - створено тестовий скрипт

**Дата:** 2025-10-18
