#!/bin/bash
# Швидка перевірка webhook через Telegram API

if [ -z "$BOT_TOKEN" ]; then
    echo "❌ Встановіть BOT_TOKEN!"
    echo "Використання: BOT_TOKEN=ваш_токен ./check_webhook.sh"
    exit 1
fi

echo "🔍 Перевірка webhook..."
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" | jq '.'

echo ""
echo "🗑️ Видалення webhook..."
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/deleteWebhook?drop_pending_updates=true" | jq '.'

echo ""
echo "✅ Готово! Зачекайте 10 секунд і перезапустіть бота на Render"
