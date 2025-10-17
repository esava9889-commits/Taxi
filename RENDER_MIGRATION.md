# 🔧 МІГРАЦІЯ БД НА RENDER

## ❗️ ВАЖЛИВО

Після деплою нової версії коду, потрібно **ОДИН РАЗ** виконати міграцію БД!

---

## 📊 ЩО ДОДАЄТЬСЯ

```sql
ALTER TABLE drivers ADD COLUMN card_number TEXT;
```

**Для чого:** Зберігати номер картки водія для оплати.

---

## 🚀 ЯК ВИКОНАТИ НА RENDER

### Варіант 1: Через Shell на Render

1. Відкрити **Render Dashboard**
2. Перейти в **Shell** вашого сервісу
3. Виконати:
   ```bash
   python migration_add_card_number.py data/taxi.db
   ```

### Варіант 2: Автоматична міграція при старті

Додати в `main.py` ПЕРЕД `start_polling`:

```python
# main.py
async def main():
    config = load_config()
    
    # Міграція БД
    await ensure_card_number_column(config.database_path)
    
    await init_database(config.database_path)
    # ... решта коду
```

І додати функцію:

```python
# db.py
async def ensure_card_number_column(db_path: str):
    """Міграція: додати card_number якщо немає"""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("PRAGMA table_info(drivers)") as cur:
            columns = await cur.fetchall()
            col_names = [c[1] for c in columns]
        
        if 'card_number' not in col_names:
            logger.info("⚙️ Додаю колонку card_number...")
            await db.execute("ALTER TABLE drivers ADD COLUMN card_number TEXT")
            await db.commit()
            logger.info("✅ Колонка card_number додана")
```

---

## ✅ ПЕРЕВІРКА

Після міграції перевірити:

1. **Водій відкриває гаманець** → Не повинно бути помилки
2. **Водій додає картку** → Збережеться в БД
3. **Клієнт обирає оплату карткою** → Бачить номер картки водія

---

## 🐛 ЩО БУЛО ВИПРАВЛЕНО

```
❌ БУЛО:
AttributeError: 'Driver' object has no attribute 'card_number'

✅ СТАЛО:
💼 Ваш гаманець
💳 Картка для оплати: [номер]
```

---

**Автор:** Background Agent  
**Дата:** 2025-10-17  
**Commit:** 172951e
