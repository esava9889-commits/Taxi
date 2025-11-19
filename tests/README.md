# 🧪 Тести для Telegram Taxi Bot

Цей каталог містить автоматичні тести для перевірки функціональності бота.

## 📁 Структура

```
tests/
├── __init__.py              # Пакет тестів
├── conftest.py              # Fixtures для pytest
├── test_validation.py       # Тести валідації даних
├── test_rate_limiter.py     # Тести rate limiting
└── test_matching.py         # Тести пошуку водіїв
```

## 🚀 Запуск тестів

### Встановлення залежностей

```bash
pip install -r requirements.txt
```

### Запуск всіх тестів

```bash
pytest
```

### Запуск з покриттям коду

```bash
pytest --cov=app --cov-report=html
```

Після цього відкрийте `htmlcov/index.html` в браузері для перегляду звіту.

### Запуск конкретного файлу

```bash
pytest tests/test_validation.py
```

### Запуск конкретного тесту

```bash
pytest tests/test_validation.py::TestPhoneValidation::test_valid_phone_numbers
```

### Запуск тільки швидких тестів

```bash
pytest -m "not slow"
```

### Запуск в verbose режимі

```bash
pytest -v
```

## 📊 Покриття коду

Наша мета: **80%+ покриття**

Поточне покриття можна переглянути після запуску:

```bash
pytest --cov=app --cov-report=term-missing
```

## 🎯 Типи тестів

### Unit тести
Швидкі, ізольовані тести окремих функцій:
- `test_validation.py` - валідація даних
- `test_rate_limiter.py` - обмеження частоти запитів
- `test_matching.py` - розрахунок відстаней

### Integration тести
Тести що потребують БД або зовнішніх сервісів:
- Позначені маркером `@pytest.mark.integration`
- Пропускаються в CI/CD без налаштованої БД

## 🛠️ Написання тестів

### Приклад простого тесту

```python
def test_example():
    """Опис що перевіряє тест"""
    result = my_function(input_data)
    assert result == expected_output
```

### Приклад async тесту

```python
@pytest.mark.asyncio
async def test_async_example():
    """Тест async функції"""
    result = await my_async_function()
    assert result is not None
```

### Використання fixtures

```python
def test_with_fixture(sample_phone_numbers):
    """Використання готових даних з conftest.py"""
    for phone in sample_phone_numbers["valid"]:
        valid, cleaned = validate_phone_number(phone)
        assert valid
```

## 📝 Правила написання тестів

1. **Назва тесту** має описувати що перевіряється:
   ```python
   # ✅ Добре
   def test_phone_validation_accepts_ukrainian_numbers()
   
   # ❌ Погано
   def test_phone()
   ```

2. **Один тест = одна перевірка**
   ```python
   # ✅ Добре - кожен тест перевіряє одну річ
   def test_phone_accepts_plus_380_format()
   def test_phone_accepts_380_format()
   
   # ❌ Погано - тест перевіряє багато речей
   def test_phone_validation()
   ```

3. **Arrange-Act-Assert** структура:
   ```python
   def test_example():
       # Arrange - підготовка даних
       phone = "+380671234567"
       
       # Act - виконання функції
       valid, cleaned = validate_phone_number(phone)
       
       # Assert - перевірка результату
       assert valid
       assert cleaned == "+380671234567"
   ```

4. **Тестуйте граничні випадки**:
   - Порожні дані
   - Мінімальні/максимальні значення
   - Некоректні дані
   - Спеціальні символи

## 🐛 Debugging тестів

### Запустити з pdb (debugger)

```bash
pytest --pdb
```

### Показати print statements

```bash
pytest -s
```

### Показати локальні змінні при помилці

```bash
pytest --showlocals
```

### Зупинитись на першій помилці

```bash
pytest -x
```

## 📈 CI/CD

Тести запускаються автоматично в GitHub Actions при кожному push.

Конфігурація: `.github/workflows/ci.yml`

## 🎓 Додаткові ресурси

- [Pytest документація](https://docs.pytest.org/)
- [Pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [Coverage.py](https://coverage.readthedocs.io/)

## ❓ Питання?

Якщо маєте питання по тестах, створіть issue в GitHub.
