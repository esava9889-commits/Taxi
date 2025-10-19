# ПРОГРЕС: Рефакторинг order.py

**Файл:** `app/handlers/order.py` (1125 рядків)

---

## 📊 СТРУКТУРА order.py

### Кроки замовлення:
1. **Старт** - рядок 199: `F.text == "🚖 Замовити таксі"`
2. **Pickup** (звідки) - рядки 429-497
   - location handler
   - voice handler  
   - text handler
3. **Destination** (куди) - рядки 505-560
   - location handler
   - text handler
4. **Car class** - показ цін та вибір
5. **Comment** - рядки 565-651 (є інлайн кнопка skip)
6. **Payment method** - рядок 779
7. **Confirm** - рядок 812 (є інлайн кнопка)

---

## ⚠️ ПРОБЛЕМИ

### 1. location_keyboard() - ReplyKeyboard
Рядки 187-197:
```python
def location_keyboard(text: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
            [KeyboardButton(text="🎤 Голосом")],
            [KeyboardButton(text=CANCEL_TEXT)],
        ],
        ...
    )
```

**Використовується в:**
- pickup_location (рядок 279)
- destination_location

### 2. Багато answer() без edit

### 3. Немає кнопок "Назад" на кожному кроці

---

## 🎯 ПЛАН ВИПРАВЛЕННЯ

### Етап 1: Початок та локації ⏱️ ~40хв

**Зміни:**
- [ ] Зробити `start_order` (рядок 199) інлайн з кнопками вибору
- [ ] Створити інлайн варіант вибору способу введення pickup
- [ ] Створити інлайн варіант вибору способу введення destination
- [ ] Додати кнопки "Назад" та "Скасувати"
- [ ] Видаляти повідомлення користувача

**Підхід:**
```python
# start_order → показати інлайн кнопки:
# - 📍 Надіслати мою локацію
# - ✏️ Ввести адресу текстом
# - 📍 Вибрати зі збережених
# - ❌ Скасувати

# Callback address:send_location → показати ReplyKeyboard тільки на цьому кроці
```

### Етап 2: Коментар, оплата, підтвердження ⏱️ ~30хв

**Зміни:**
- [ ] Перевірити comment - вже є інлайн skip
- [ ] Зробити payment_method повністю інлайн
- [ ] Зробити confirm повністю інлайн
- [ ] Додати кнопки "Назад"

---

## 🚀 ПРОГРЕС

### ✅ Етап 1.1: Інлайн кнопки для pickup/destination (ЗАВЕРШЕНО)

**Зроблено:**
- ✅ `start_order` (рядок 199) - тепер показує інлайн кнопки вибору
- ✅ Нові callback обробники:
  - `order:pickup:send_location` - показує ReplyKeyboard тільки коли потрібно
  - `order:pickup:text` - запит текстової адреси
  - `order:pickup:saved` - показ збережених адрес
  - `order:pickup:use_saved:{id}` - використати збережену адресу
  - `order:pickup:back` - повернутися до вибору способу
  - `order:dest:send_location` - геолокація для призначення
  - `order:dest:text` - текст для призначення
  - `order:dest:saved` - збережені адреси для призначення
  - `order:dest:use_saved:{id}` - використати адресу призначення
  - `order:dest:back` - повернутися до вибору
  - `order:back:pickup` - повернутися до pickup з destination
  - `order:back_to_destination` - оновлений з інлайн кнопками
- ✅ Кнопки "Назад" на кожному кроці
- ✅ Кнопка "Скасувати" всюди
- ✅ edit_text замість answer де можливо

**Результат:**
- Інтерфейс замовлення тепер повністю інлайн
- ReplyKeyboard показується ТІЛЬКИ для request_location
- Чистіший чат

**Закоммічено!**

---

### ⏳ Етап 1.2: Виправлення Message обробників (НАСТУПНЕ)

**Треба зробити:**
- [ ] Виправити `pickup_location` - видаляти повідомлення користувача
- [ ] Виправити `pickup_text` - оновлювати попереднє повідомлення
- [ ] Виправити `destination_location` - видаляти повідомлення
- [ ] Виправити `destination_text` - оновлювати повідомлення
- [ ] Додати edit_text замість answer в переходах
