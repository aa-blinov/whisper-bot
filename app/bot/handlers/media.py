"""Голосовые, кружки, аудио- и видеофайлы превращаются в текст.

Бот не скачивает файл к себе: он спрашивает у Telegram ссылку на файл и
отдаёт её воркеру. Воркер читает поток ffmpeg-ом прямо по этой ссылке,
поэтому копии на диске нет, а общий каталог нужен только под кэш моделей.
"""

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
from app.services.transcription import TranscriptionTimeout, TranscriptTooLong

logger = logging.getLogger(__name__)

# Bot API отдаёт ботам файлы не больше 20 МБ, дальше get_file отвечает
# ошибкой. Проверяем до запроса, чтобы человек получил понятный ответ.
TELEGRAM_FILE_LIMIT = 20 * 1024 * 1024

AUDIO_EXTENSIONS = (
    ".mp3",
    ".ogg",
    ".oga",
    ".opus",
    ".wav",
    ".flac",
    ".m4a",
    ".aac",
    ".wma",
    ".amr",
)
VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".3gp")


def _document_is_media(document) -> str | None:
    """Тип файла, если документ похож на аудио или видео."""
    mime = (document.mime_type or "").lower()
    name = (document.file_name or "").lower()
    if mime.startswith("audio/") or mime in ("application/ogg", "application/x-ogg"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if name.endswith(AUDIO_EXTENSIONS):
        return "audio"
    if name.endswith(VIDEO_EXTENSIONS):
        return "video"
    return None


def pick_media(message: Message) -> tuple[object, str] | str | None:
    """Вернуть вложение и тип, строку для «не поддерживается» или None.

    Тип нужен только для истории и текстов, распознавание всё равно идёт
    через ffmpeg по содержимому.
    """
    if message.voice is not None:
        return message.voice, "voice"
    if message.video_note is not None:
        return message.video_note, "video_note"
    if message.audio is not None:
        return message.audio, "audio"
    if message.document is not None:
        kind = _document_is_media(message.document)
        if kind is None:
            return "unsupported"
        return message.document, kind
    if message.video is not None:
        return message.video, "video"
    return None


def file_url(context: ContextTypes.DEFAULT_TYPE, telegram_file) -> str:
    """Ссылка на файл: PTB отдаёт её целиком, старые версии только путь."""
    path = telegram_file.file_path or ""
    if path.startswith(("http://", "https://")):
        return path
    return f"{context.bot.base_url}/file/{path}"


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
    if picked == "unsupported":
        await message.reply_text(texts.UNSUPPORTED)
        return
    attachment, file_type = picked

    settings = deps.settings(context)
    duration = int(getattr(attachment, "duration", 0) or 0)
    if duration > settings.max_media_seconds:
        await message.reply_text(
            texts.media_too_long(duration, settings.max_media_seconds)
        )
        return

    size = int(getattr(attachment, "file_size", 0) or 0)
    if size > TELEGRAM_FILE_LIMIT:
        await message.reply_text(texts.FILE_TOO_BIG)
        return

    await ensure_profile(update, context)
    language = deps.access(context).language(user.id)
    status = await message.reply_text(texts.DOWNLOADS)

    started = time.time()
    try:
        telegram_file = await attachment.get_file()
        source = file_url(context, telegram_file)
        await status.edit_text(texts.RECOGNIZING)
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)

        try:
            transcript = await deps.transcription(context).transcribe(
                source, file_type, language, duration
            )
        except TranscriptionTimeout:
            await status.edit_text(texts.TIMEOUT)
            return
        except TranscriptTooLong as exc:
            # У документа нет поля duration, поэтому лимит ловится уже
            # после декодирования в воркере.
            await status.edit_text(
                texts.media_too_long(exc.seconds, settings.max_media_seconds)
            )
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
            "Запрос пользователя %s: %.1f с, %s, %s символов",
            user.id,
            elapsed,
            file_type,
            len(transcript.text),
        )
    except Exception:
        logger.exception("Ошибка обработки медиа пользователя %s", user.id)
        try:
            await status.edit_text(texts.INTERNAL_ERROR)
        except Exception:
            pass
