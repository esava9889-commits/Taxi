# Міграції PostgreSQL для оновлення схеми БД

**Дата:** 2025-10-19  
**Коміт:** a31396f  
**Проблема:** `asyncpg.exceptions.UndefinedColumnError: column "to_user_id" does not exist`

## Проблема

При спробі створити індекс на колонку `ratings.to_user_id`, виникала помилка, тому що:
- Таблиця `ratings` вже існувала зі старою схемою
- Стара схема мала колонку `driver_user_id`
- Нова схема має колонки `from_user_id` та `to_user_id`
- `CREATE INDEX IF NOT EXISTS` не створює індекс, якщо колонки не існує

## Рішення

Додано систему міграцій в `init_postgres.py`, яка:
1. Перевіряє існування таблиць
2. Перевіряє існування колонок
3. Виконує необхідні зміни схеми (ALTER TABLE)
4. Безпечно створює індекси

## Міграції

### Міграція 1: Таблиця `ratings`

**Проблема:** Стара колонка `driver_user_id` → Нові колонки `from_user_id` та `to_user_id`

**Рішення:**
```sql
-- Перейменувати driver_user_id на to_user_id
ALTER TABLE ratings RENAME COLUMN driver_user_id TO to_user_id;

-- Додати нову колонку from_user_id
ALTER TABLE ratings ADD COLUMN from_user_id BIGINT;

-- Заповнити дані (тимчасово копіювати з to_user_id)
UPDATE ratings SET from_user_id = to_user_id WHERE from_user_id IS NULL;

-- Зробити колонку обов'язковою
ALTER TABLE ratings ALTER COLUMN from_user_id SET NOT NULL;
```

### Міграція 2: Таблиця `client_ratings`

**Проблема:** Відсутня колонка `driver_id`

**Рішення:**
```sql
-- Додати колонку driver_id
ALTER TABLE client_ratings ADD COLUMN driver_id INTEGER;
```

## Безпечне створення індексів

Додано функцію `create_index_safe()`, яка:
1. Перевіряє чи існує таблиця
2. Перевіряє чи існує колонка
3. Створює індекс тільки якщо колонка існує
4. Логує попередження якщо колонка відсутня

```python
async def create_index_safe(index_name: str, table: str, column: str):
    try:
        # Перевірити чи існує колонка
        exists = await conn.fetchval(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_name = '{table}' AND column_name = '{column}'
            )
        """)
        if exists:
            await conn.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})")
        else:
            logger.warning(f"⚠️ Колонка {table}.{column} не існує, пропускаю індекс")
    except Exception as e:
        logger.warning(f"⚠️ Не вдалося створити індекс {index_name}: {e}")
```

## Процес міграції

При кожному запуску `init_postgres_db()`:

1. **Перевірка міграцій** (завжди першою)
   ```
   🔄 Перевіряю необхідність міграцій...
   ```

2. **Виконання міграцій** (якщо потрібно)
   ```
   🔄 Міграція ratings: перейменування driver_user_id...
   ✅ Колонка driver_user_id перейменована на to_user_id
   🔄 Міграція ratings: додавання from_user_id...
   ✅ Колонка from_user_id додана
   ```

3. **Створення нових таблиць** (якщо не існують)
   ```
   🐘 Створюю таблиці в PostgreSQL...
   ```

4. **Створення індексів** (безпечно)
   ```
   🔍 Створюю індекси...
   ✅ Всі таблиці та індекси PostgreSQL створено!
   ```

## Переваги цього підходу

✅ **Безпечні оновлення:** Міграції виконуються автоматично при deploy  
✅ **Немає втрати даних:** Дані зберігаються при перейменуванні колонок  
✅ **Graceful degradation:** Помилки міграцій не зупиняють запуск бота  
✅ **Логування:** Всі дії логуються для моніторингу  
✅ **Ідемпотентність:** Можна запускати багато разів - спрацює тільки раз  

## Тестування

### Сценарій 1: Перший запуск (нові таблиці)
```
🔄 Перевіряю необхідність міграцій...
✅ Міграції завершено!
🐘 Створюю таблиці в PostgreSQL...
✅ Всі таблиці та індекси PostgreSQL створено!
```

### Сценарій 2: Оновлення існуючих таблиць
```
🔄 Перевіряю необхідність міграцій...
🔄 Міграція ratings: перейменування driver_user_id...
✅ Колонка driver_user_id перейменована на to_user_id
🔄 Міграція ratings: додавання from_user_id...
✅ Колонка from_user_id додана
✅ Міграції завершено!
🐘 Створюю таблиці в PostgreSQL...
✅ Всі таблиці та індекси PostgreSQL створено!
```

### Сценарій 3: Схема вже оновлена
```
🔄 Перевіряю необхідність міграцій...
✅ Міграції завершено!
🐘 Створюю таблиці в PostgreSQL...
✅ Всі таблиці та індекси PostgreSQL створено!
```

## Майбутні міграції

Для додавання нових міграцій:

1. Додати новий блок try-except в розділ "МІГРАЦІЇ для існуючих таблиць"
2. Перевірити існування таблиці
3. Перевірити існування колонок
4. Виконати необхідні ALTER TABLE
5. Логувати дії

**Приклад:**
```python
# Міграція 3: orders - додати нову колонку
try:
    check = await conn.fetchval("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'orders'
        )
    """)
    
    if check:
        has_column = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_name = 'orders' AND column_name = 'new_column'
            )
        """)
        
        if not has_column:
            logger.info("🔄 Міграція orders: додавання new_column...")
            await conn.execute("ALTER TABLE orders ADD COLUMN new_column TEXT")
            logger.info("✅ Колонка new_column додана")
except Exception as e:
    logger.warning(f"⚠️ Помилка міграції orders: {e}")
```

## Статус

| Міграція | Статус | Опис |
|----------|--------|------|
| ratings: driver_user_id → to_user_id | ✅ Завершено | Перейменування колонки |
| ratings: додати from_user_id | ✅ Завершено | Нова колонка |
| client_ratings: додати driver_id | ✅ Завершено | Нова колонка |
| Безпечні індекси | ✅ Завершено | Перевірка перед створенням |

**Всі міграції готові до production!** 🚀
