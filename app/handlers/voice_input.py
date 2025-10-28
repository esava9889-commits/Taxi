"""Голосовий ввід адреси"""
from __future__ import annotations

import logging
import os
from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

from app.config.config import AppConfig

logger = logging.getLogger(__name__)


async def transcribe_voice(file_path: str) -> Optional[str]:
    """
    Розпізнати текст з голосового повідомлення
    
    ПРИМІТКА: Для production інтеграція потребує:
    - Google Speech-to-Text API (платно, але якісно)
    - або OpenAI Whisper (безкоштовно, self-hosted)
    - або Azure Speech Services
    
    Args:
        file_path: Шлях до голосового файлу
    
    Returns:
        Розпізнаний текст або None
    """
    # Заглушка - повертає None поки немає інтеграції
    # Приклад з Google Speech-to-Text:
    """
    from google.cloud import speech
    
    client = speech.SpeechClient()
    
    with open(file_path, 'rb') as audio_file:
        content = audio_file.read()
    
    audio = speech.RecognitionAudio(content=content)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
        sample_rate_hertz=48000,
        language_code='uk-UA',
    )
    
    response = client.recognize(config=config, audio=audio)
    
    for result in response.results:
        return result.alternatives[0].transcript
    """
    
    # Поки що повертаємо None (потрібна інтеграція з API)
    logger.warning("Voice transcription not configured. Need Google Speech-to-Text or OpenAI Whisper API")
    return None


def create_router(config: AppConfig) -> Router:
    router = Router(name="voice_input")

    @router.message(F.voice)
    async def handle_voice_address(message: Message, state: FSMContext) -> None:
        """Обробити голосовий ввід адреси"""
        if not message.from_user or not message.voice:
            return
        
        # Перевірити чи зараз в процесі замовлення
        current_state = await state.get_state()
        
        # Якщо не в процесі замовлення - ігноруємо
        if not current_state or "order" not in current_state.lower():
            return
        
        await message.answer(
            "🎤 <b>Розпізнавання голосу...</b>\n\n"
            "⏳ Обробляю ваше голосове повідомлення..."
        )
        
        try:
            # Завантажити голосовий файл
            file = await message.bot.get_file(message.voice.file_id)
            file_path = f"/tmp/voice_{message.from_user.id}_{message.voice.file_id}.ogg"
            
            await message.bot.download_file(file.file_path, file_path)
            
            # Розпізнати текст
            text = await transcribe_voice(file_path)
            
            # Видалити тимчасовий файл
            if os.path.exists(file_path):
                os.remove(file_path)
            
            if text:
                logger.info(f"Voice transcribed: {text}")
                
                # Запитати підтвердження
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="✅ Так, вірно", callback_data=f"voice:confirm:{text}"),
                            InlineKeyboardButton(text="❌ Ні, ввести вручну", callback_data="voice:cancel")
                        ]
                    ]
                )
                
                await message.answer(
                    f"🎤 <b>Розпізнано адресу:</b>\n\n"
                    f"📍 {text}\n\n"
                    "Це правильно?",
                    reply_markup=kb
                )
            else:
                # Якщо не вдалося розпізнати
                await message.answer(
                    "❌ <b>Не вдалося розпізнати голосове повідомлення</b>\n\n"
                    "💡 Спробуйте:\n"
                    "• Говорити чіткіше\n"
                    "• Без фонового шуму\n"
                    "• Або введіть адресу текстом\n\n"
                    "⚠️ <i>Функція розпізнавання голосу в розробці.\n"
                    "Наразі використовуйте текстовий ввід або геолокацію.</i>"
                )
        
        except Exception as e:
            logger.error(f"Voice processing error: {e}")
            await message.answer(
                "❌ Помилка обробки голосового повідомлення.\n"
                "Будь ласка, введіть адресу текстом або надішліть геолокацію."
            )

    @router.callback_query(F.data.startswith("voice:confirm:"))
    async def confirm_voice_address(call: CallbackQuery, state: FSMContext) -> None:
        """Підтвердити розпізнану адресу"""
        if not call.from_user:
            return
        
        address = call.data.split(":", 2)[2]
        
        # Зберегти адресу в стейт (залежно від поточного стану)
        current_state = await state.get_state()
        
        await call.answer("✅ Адресу прийнято!")
        
        # Спробувати геокодувати
        if config.google_maps_api_key:
            from app.utils.maps import geocode_address
            coords = await geocode_address(config.google_maps_api_key, address)
            
            if coords:
                lat, lon = coords
                
                # Визначити чи це pickup чи destination
                if "pickup" in current_state:
                    await state.update_data(pickup=address, pickup_lat=lat, pickup_lon=lon)
                    await call.message.edit_text(f"✅ Адресу подачі збережено:\n📍 {address}")
                else:
                    await state.update_data(destination=address, dest_lat=lat, dest_lon=lon)
                    await call.message.edit_text(f"✅ Пункт призначення збережено:\n📍 {address}")
            else:
                await call.message.edit_text(
                    f"⚠️ Адресу збережено, але не вдалося знайти координати:\n📍 {address}"
                )
        else:
            await call.message.edit_text(f"✅ Адресу збережено:\n📍 {address}")

    @router.callback_query(F.data == "voice:cancel")
    async def cancel_voice(call: CallbackQuery) -> None:
        """Скасувати голосовий ввід"""
        await call.answer()
        await call.message.edit_text("❌ Введіть адресу текстом або надішліть геолокацію")

    return router
