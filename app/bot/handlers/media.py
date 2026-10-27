"""Голосовое сообщение или видео-кружок превращаются в текст."""

from __future__ import annotations

import logging
import time

from telegram import Message, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from app.bot import deps, keyboards, texts
from app.bot.formatting import transcript_blocks
from app.bot.handlers.common import deny_access, ensure_profile
from app.bot.handlers.guards import is_admin
from app.services.transcription import TranscriptionTimeout

logger = logging.getLogger(__name__)


def pick_media(message: Message) -> tuple[object, str] | None:
    """Вернуть медиа и его тип, если это голосовое или кружок."""
    if message.voice is not None:
        return message.voice, "voice"
    if message.video_note is not None:
        return message.video_note, "video_note"
    return None


async def send_transcript(
    message: Message, text: str, is_admin_flag: bool
) -> None:
    """Отправить расшифровку, при длинном тексте несколькими сообщениями."""
    blocks = transcript_blocks(text)
    for index, block in enumerate(blocks):
        last = index == len(blocks) - 1
        await message.reply_text(
            block,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.main_menu(is_admin_flag) if last else None,
            disable_web_page_preview=True,
        )


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    if not deps.access(context).is_allowed(user.id):
        await deny_access(update, context)
        return

    picked = pick_media(message)
    if picked is None:
        return
    media, file_type = picked

    duration = int(getattr(media, "duration", 0) or 0)
    settings = deps.settings(context)
    if duration > settings.max_media_seconds:
        await message.reply_text(
            texts.media_too_long(duration, settings.max_media_seconds)
        )
        return

    await ensure_profile(update, context)
    access = deps.access(context)
    language = access.language(user.id)
    status = await message.reply_text(texts.DOWNLOADS)

    storage = deps.media(context)
    file_path = storage.new_path(file_type)
    started = time.time()
    try:
        telegram_file = await media.get_file()
        await telegram_file.download_to_drive(file_path)
        await status.edit_text(texts.RECOGNIZING)
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)

        try:
            transcript = await deps.transcription(context).transcribe(
                file_path, file_type, language, duration
            )
        except TranscriptionTimeout:
            await status.edit_text(texts.TIMEOUT)
            return

        if transcript is None or not transcript.text:
            await status.edit_text(texts.NOT_RECOGNIZED)
            return

        elapsed = time.time() - started
        try:
            await status.delete()
        except Exception as exc:  # сообщение могли удалить вручную
            logger.debug("Не удалось убрать статус: %s", exc)

        await send_transcript(message, transcript.text, is_admin(update, context))
        deps.stats(context).record(
            user.id, elapsed, file_type, transcript.text, transcript.language
        )
        logger.info(
            "Запрос пользователя %s: %.1f с, %s символов",
            user.id,
            elapsed,
            len(transcript.text),
        )
    except Exception:
        logger.exception("Ошибка обработки медиа пользователя %s", user.id)
        try:
            await status.edit_text(texts.INTERNAL_ERROR)
        except Exception:
            pass
    finally:
        # Воркер удаляет файл сам; здесь страховка, если задача не дошла.
        storage.remove(file_path)
