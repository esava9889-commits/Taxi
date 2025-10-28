# Звіт про виправлення помилок PostgreSQL

**Дата:** 2025-10-19  
**Гілка:** fix-taxi-bot

## Проблеми які були виправлені

### 1. TypeError: 'coroutine' object does not support the asynchronous context manager protocol

**Причина:**
- У файлі `app/storage/db.py` використовувався неправильний підхід до виконання INSERT/UPDATE/DELETE операцій
- Для SQLite `db.execute()` повертає coroutine, який потрібно await
- Для PostgreSQL `db.execute()` повертав `PostgresCursor`, який не підтримував await

**Виправлення:**
1. **`app/storage/db_connection.py`** - Додано підтримку `__await__` до класу `PostgresCursor`:
   - Додано метод `__await__()` для підтримки `await cursor`
   - Додано метод `_execute()` для виконання запитів INSERT/UPDATE/DELETE
   - Додано властивості `lastrowid` та `rowcount` для сумісності з SQLite cursor
   - Для INSERT запитів автоматично додається `RETURNING id` для отримання lastrowid
   - Для UPDATE/DELETE запитів парситься результат для отримання rowcount

2. **`app/storage/db.py`** - Повернуто `await` для всіх INSERT/UPDATE/DELETE операцій:
   - `insert_order()` - ✅
   - `update_order_group_message()` - ✅
   - `cancel_order_by_client()` - ✅
   - `save_address()` - ✅
   - `delete_saved_address()` - ✅
   - `update_saved_address()` - ✅
   - `set_driver_online_status()` - ✅
   - `delete_user()` - ✅
   - `create_driver_application()` - ✅
   - `offer_order_to_driver()` - ✅
   - `accept_order()` - ✅
   - `reject_order()` - ✅
   - `start_order()` - ✅
   - `complete_order()` - ✅
   - `insert_rating()` - ✅
   - `insert_client_rating()` - ✅
   - `insert_payment()` - ✅
   - `insert_tariff()` - ✅

### 2. TelegramConflictError: Conflict: terminated by other getUpdates request

**Причина:**
- На Render після деплою старий процес не встигав завершитись перед запуском нового
- Обидва процеси намагались одночасно отримувати оновлення від Telegram
- Затримка 30 секунд була недостатньою для PostgreSQL ініціалізації

**Виправлення:**
1. **`app/main.py`** - Збільшено затримку запуску:
   - Змінено з 30 секунд на 45 секунд
   - Змінено інтервал повідомлень з 5 секунд на 10 секунд
   - Додано коментар про PostgreSQL

```python
# Було:
startup_delay = 30  # Збільшено до 30 секунд!

# Стало:
startup_delay = 45  # Збільшено до 45 секунд для PostgreSQL!
```

## Технічні деталі

### PostgresCursor з підтримкою await

```python
class PostgresCursor:
    def __await__(self):
        """Зробити cursor awaitable для INSERT/UPDATE/DELETE операцій"""
        return self._execute_and_return_self().__await__()
    
    async def _execute_and_return_self(self):
        """Виконати запит і повернути self"""
        if not self._executed:
            await self._execute()
        return self
    
    async def _execute(self):
        """Виконати запит для INSERT/UPDATE/DELETE"""
        # Для INSERT автоматично додаємо RETURNING id
        # Для UPDATE/DELETE парсимо результат для rowcount
```

### Сумісність SQLite та PostgreSQL

Тепер код працює однаково для обох БД:

```python
# Для SQLite:
cursor = await db.execute(...)  # await coroutine
await db.commit()               # commit required
return cursor.lastrowid         # доступний напряму

# Для PostgreSQL:
cursor = await db.execute(...)  # await PostgresCursor
await db.commit()               # no-op (автоматично)
return cursor.lastrowid         # доступний через властивість
```

## Тестування

Рекомендовано протестувати:

1. **Локально з SQLite:**
   ```bash
   python app/main.py
   ```

2. **На Render з PostgreSQL:**
   - Виконати Manual Deploy
   - Зачекати 45 секунд після запуску
   - Перевірити логи на наявність помилок
   - Перевірити що бот відповідає на команди

3. **Функціональність для тестування:**
   - ✅ Створення замовлення (INSERT)
   - ✅ Оновлення статусу замовлення (UPDATE)
   - ✅ Збережені адреси (INSERT, SELECT, UPDATE, DELETE)
   - ✅ Реєстрація водія (INSERT)
   - ✅ Рейтинги (INSERT, SELECT)

## Очікуваний результат

- ✅ Відсутність помилки `TypeError: 'coroutine' object does not support the asynchronous context manager protocol`
- ✅ Відсутність помилки `TelegramConflictError`
- ✅ Коректна робота з PostgreSQL на Render
- ✅ Коректна робота з SQLite локально
- ✅ Правильне отримання `lastrowid` для INSERT операцій
- ✅ Правильне отримання `rowcount` для UPDATE/DELETE операцій

## Додаткові рекомендації

1. **Моніторинг:** Відстежувати логи на Render перші 2-3 деплої
2. **Backup:** Регулярно робити backup PostgreSQL бази
3. **Testing:** Протестувати всі критичні функції після деплою
4. **Rollback:** При проблемах можна швидко повернутись до попередньої версії через git

## Додаткове виправлення (коміт 8ada8c8)

### 3. Помилка "column id does not exist"

**Причина:**
- PostgresCursor намагався додати `RETURNING id` до всіх INSERT запитів
- Деякі таблиці (наприклад, `users`) мають інший primary key (`user_id`)
- Відсутні таблиці `tips`, `referrals`, `rejected_offers` в init_postgres.py
- Розбіжності в схемі між SQLite та PostgreSQL (ratings, client_ratings, payments)

**Виправлення:**

1. **`app/storage/db_connection.py`:**
   - Додано try-catch для обробки INSERT без колонки `id`
   - Якщо `RETURNING id` викликає помилку, виконується звичайний INSERT
   - Graceful fallback для таблиць без колонки `id`

2. **`app/storage/init_postgres.py`:**
   - Додано відсутні таблиці:
     - `tips` - чайові
     - `referrals` - реферальна програма  
     - `rejected_offers` - відхилені пропозиції
   - Виправлено схему `ratings`:
     - Додано `from_user_id` та `to_user_id` (замість `driver_user_id`)
   - Виправлено схему `client_ratings`:
     - Додано `driver_id`
     - Видалено `comment`
   - Виправлено схему `payments`:
     - Змінено на `order_id`, `driver_id`, `commission`, `commission_paid`, тощо
   - Додано індекси для всіх нових таблиць

## Файли які було змінено

1. `app/storage/db_connection.py` - додано підтримку await до PostgresCursor + обробка відсутнього id
2. `app/storage/db.py` - виправлено 18 функцій з INSERT/UPDATE/DELETE
3. `app/main.py` - збільшено затримку запуску до 45 секунд
4. `app/storage/init_postgres.py` - синхронізовано схему з SQLite, додано відсутні таблиці
