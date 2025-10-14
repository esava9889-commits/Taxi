# Taxi Bot

Телеграм-бот для оформлення замовлень таксі.

## Налаштування

1. Скопіюйте `.env.example` у `.env` і заповніть значення:
   - `BOT_TOKEN` — токен вашого бота
   - `ADMIN_IDS` — (необов'язково) ID адмінів для команди `/orders`
   - `DB_PATH` — (необов'язково) шлях до SQLite бази

## Залежності

- Python 3.10+ (перевірено на 3.13)
- Встановіть залежності:

```bash
pip install --user -r requirements.txt
```

## Запуск локально

```bash
python3 -m app.main
```

Бот прибере вебхук і запустить polling. Використовуйте `/order` для оформлення замовлення. Адміни можуть переглянути останні замовлення командою `/orders`.

## Деплой на Render

1. Створіть репозиторій з цим кодом на GitHub.
2. Увійдіть до Render і натисніть "New +" → "Blueprint".
3. Вкажіть посилання на ваш репозиторій. Render знайде `render.yaml` автоматично.
4. Під час створення сервісу:
   - Тип: Worker
   - План: Starter (або інший)
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python -m app.main`
   - Environment Variables: додайте `BOT_TOKEN` (обов'язково), `ADMIN_IDS` (за потреби)
5. Диск:
   - Render створить диск з `render.yaml` і змонтує його у `/opt/render/project/src/data`.
   - `DB_PATH` вже вказаний як `data/taxi.sqlite3`, що відповідатиме змонтованому диску.
6. Розгорніть. Після деплою Worker запустить бота і почне polling.

Оновлення: кожен push у main (якщо `autoDeploy: true`) перезапустить Worker.
