# house-style: emoji-ok
# The emoji here are the product: they are what the user
# sees in a message or a button. See docs/house-style.md.
"""Telegram-бот: голосовые сообщения и видео-кружки превращаются в текст.

Бот принимает медиа, складывает файл в `data/`, отправляет задачу в Huey и
ждёт результат от воркера. Распознавание делает GigaAM v3 (ONNX), текст
приходит с готовой пунктуацией.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import time
import uuid

from telegram import BotCommand, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    Defaults,
    MessageHandler,
    filters,
)
from huey.contrib.asyncio import aget_result

import admin
import database
import keyboards
from config import settings
from huey_tasks import transcribe_task

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 3_800
# Сколько ждать воркер: запись длиннее, значит и распознавание дольше, но не вечно.
RESULT_TIMEOUT_MIN = 60
RESULT_TIMEOUT_MAX = 900

START_TEXT = (
    "Привет, {name}!\n\n"
    "Пришли голосовое сообщение или видео-кружок, я верну текст. "
    "Речь распознаётся вместе с пунктуацией, модель работает на этом же сервере."
)
ADMIN_HINT = "\n\nТы администратор. Команда /admin открывает доступы, список людей и статистику."


def db_path() -> str:
    return settings.db_path


def _is_admin(user_id: int | None) -> bool:
    return admin.is_admin(user_id)


async def _ensure_profile(update: Update) -> None:
    user = update.effective_user
    if user is None:
        return
    database.touch_profile(
        db_path(),
        user.id,
        user.first_name or "",
        user.last_name or "",
        user.username or "",
    )


async def _deny_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отказ и заявка администратору, одним сообщением пользователю."""
    sent = await admin.access_request(update, context)
    if update.effective_user and database.is_user_allowed(db_path(), update.effective_user.id):
        await start(update, context)
        return
    if update.effective_message:
        await update.effective_message.reply_text(
            "Пока нет доступа. Я отправил заявку администратору, и как только он её "
            "подтвердит, можно присылать голосовые."
            if sent
            else "Пока нет доступа. Напиши администратору."
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start: приветствие, меню и создание профиля."""
    user = update.effective_user
    if user is None or update.effective_message is None:
        return

    if not database.is_user_allowed(db_path(), user.id):
        await _deny_access(update, context)
        return

    await _ensure_profile(update)
    text = START_TEXT.format(name=html.escape(user.first_name or "друг"))
    if _is_admin(user.id):
        text += ADMIN_HINT
    await update.effective_message.reply_text(
        text,
        reply_markup=keyboards.main_menu(_is_admin(user.id)),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    lines = [
        "<b>Что умеет бот</b>",
        "• голосовое сообщение становится текстом",
        "• видео-кружок тоже",
        "• в тексте есть пунктуация и заглавные буквы",
        "",
        "<b>Команды</b>",
        "/language: русский или английский",
        "/help: эта справка",
    ]
    if _is_admin(update.effective_user.id if update.effective_user else None):
        lines += [
            "",
            "<b>Администратору</b>",
            "/admin: доступы, список людей и статистика",
            "/add_user: добавить человека",
            "/users: список допущенных",
            "/invite: ссылка для приглашения",
            "/stats: статистика",
        ]
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def language_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.effective_message is None:
        return
    current = database.get_language(db_path(), user.id)
    await update.effective_message.reply_text(
        "Выбери язык распознавания:",
        reply_markup=keyboards.language_menu(current),
    )


async def language_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return

    text = message.text.strip()
    if keyboards.BTN_RU in text or text.lower().startswith("рус"):
        language = "ru"
    elif keyboards.BTN_EN in text or text.lower().startswith("англ"):
        language = "en"
    else:
        await language_menu(update, context)
        return

    database.set_language(db_path(), user.id, language)
    name = keyboards.LANGUAGE_NAMES[language]
    note = (
        "\n\nАнглийскую речь распознаёт вторая модель, поэтому первый такой "
        "запрос идёт дольше."
        if language == "en"
        else ""
    )
    await message.reply_text(
        f"Язык распознавания: {name}.{note}",
        reply_markup=keyboards.main_menu(_is_admin(user.id)),
    )


def _split_text(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Разбить длинный текст по строкам, чтобы влезть в лимит Telegram."""
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks or [text]


async def _send_transcript(message, text: str, is_admin: bool) -> None:
    """Отправить расшифровку, при длинном тексте несколькими сообщениями."""
    chunks = _split_text(text)
    for index, chunk in enumerate(chunks):
        last = index == len(chunks) - 1
        await message.reply_text(
            f"<blockquote>{html.escape(chunk)}</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.main_menu(is_admin) if last else None,
            disable_web_page_preview=True,
        )


def _result_timeout(duration: int) -> int:
    return min(RESULT_TIMEOUT_MAX, max(RESULT_TIMEOUT_MIN, int(duration or 0) * 2))


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Голосовое сообщение или видео-кружок превращаются в текст."""
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    if not database.is_user_allowed(db_path(), user.id):
        await _deny_access(update, context)
        return

    if message.voice is not None:
        media, file_type = message.voice, "voice"
    elif message.video_note is not None:
        media, file_type = message.video_note, "video_note"
    else:
        return

    duration = int(getattr(media, "duration", 0) or 0)
    if duration > settings.max_media_seconds:
        await message.reply_text(
            f"Запись длится {duration} с, а максимум {settings.max_media_seconds}. "
            "Пришли покороче."
        )
        return

    await _ensure_profile(update)
    language = database.get_language(db_path(), user.id)
    status = await message.reply_text("🎧 Скачиваю запись…")

    os.makedirs(settings.data_dir, exist_ok=True)
    file_path = os.path.join(settings.data_dir, f"{uuid.uuid4().hex}_{file_type}.bin")
    started = time.time()
    try:
        telegram_file = await media.get_file()
        await telegram_file.download_to_drive(file_path)
        await status.edit_text("🧠 Распознаю…")
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)

        task = transcribe_task(file_path, file_type, language)
        try:
            result = await asyncio.wait_for(
                aget_result(task, backoff=1.2, max_delay=1.0, preserve=False),
                timeout=_result_timeout(duration),
            )
        except asyncio.TimeoutError:
            logger.error("Воркер не ответил за отведённое время (%s с)", duration)
            await status.edit_text("Распознавание затянулось. Попробуй ещё раз чуть позже.")
            return

        if not isinstance(result, (list, tuple)) or not result or not result[0]:
            await status.edit_text(
                "Не расслышал текст. Запись слишком короткая или тихая?"
            )
            return

        text = result[0]
        if len(result) > 1 and result[1]:
            language = result[1]

        elapsed = time.time() - started
        try:
            await status.delete()
        except Exception as exc:  # сообщение могли удалить вручную
            logger.debug("Не удалось убрать статус: %s", exc)
        await _send_transcript(message, text, _is_admin(user.id))
        database.record_task_metadata(
            db_path(), user.id, elapsed, file_type, text, language
        )
        logger.info(
            "Запрос пользователя %s: %.1f с, %s символов", user.id, elapsed, len(text)
        )
    except Exception:
        logger.exception("Ошибка обработки медиа пользователя %s", user.id)
        try:
            await status.edit_text("Что-то сломалось при обработке. Попробуй ещё раз.")
        except Exception:
            pass
    finally:
        # Воркер удаляет файл сам; здесь страховка, если задача не дошла.
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as exc:
                logger.warning("Не удалось удалить %s: %s", file_path, exc)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    user = update.effective_user
    await update.effective_message.reply_text(
        "Хорошо, вернулся в меню.",
        reply_markup=keyboards.main_menu(_is_admin(user.id if user else None)),
    )


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Любой другой текст: не молчим, объясняем, что делать."""
    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        "Пришли голосовое сообщение или видео-кружок, я превращу его в текст.\n"
        "Все команды: /help",
        reply_markup=keyboards.main_menu(
            _is_admin(update.effective_user.id if update.effective_user else None)
        ),
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Ошибка при обработке обновления", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Что-то пошло не так. Попробуй ещё раз или напиши позже."
            )
        except Exception:
            pass


async def _post_init(application: Application) -> None:
    """Команды в меню Telegram и подсказка при первом открытии чата."""
    commands = [
        BotCommand("start", "Начать"),
        BotCommand("language", "Язык распознавания"),
        BotCommand("admin", "Панель администратора"),
        BotCommand("help", "Справка"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        await application.bot.set_my_short_description(
            "Голосовые сообщения и видео-кружки в текст, с пунктуацией."
        )
    except Exception as exc:
        logger.warning("Не удалось обновить меню команд: %s", exc)
    logger.info("Бот запущен: @%s", application.bot.username)


def build_application() -> Application:
    application = (
        ApplicationBuilder()
        .token(settings.token)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .concurrent_updates(4)
        .post_init(_post_init)
        .build()
    )
    application.bot_data["settings"] = settings

    for handler in admin.build_handlers():
        application.add_handler(handler)

    private = filters.ChatType.PRIVATE
    application.add_handler(CommandHandler("start", start, filters=private))
    application.add_handler(CommandHandler("help", help_command, filters=private))
    application.add_handler(CommandHandler("language", language_menu, filters=private))
    application.add_handler(CommandHandler("cancel", cancel, filters=private))
    application.add_handler(
        MessageHandler(private & filters.Regex(rf"^{keyboards.BTN_LANGUAGE}$"), language_menu)
    )
    application.add_handler(
        MessageHandler(
            private & filters.Regex(rf"^({keyboards.BTN_RU}|{keyboards.BTN_EN})"),
            language_choice,
        )
    )
    application.add_handler(
        MessageHandler(private & filters.Regex(rf"^{keyboards.BTN_CANCEL}$"), cancel)
    )
    application.add_handler(
        MessageHandler(private & (filters.VOICE | filters.VIDEO_NOTE), handle_media)
    )
    application.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, fallback))
    application.add_error_handler(on_error)
    return application


def main() -> int:
    if not settings.token:
        logger.error("TELEGRAM_BOT_TOKEN не задан, бот не может стартовать.")
        return 1

    os.makedirs(settings.data_dir, exist_ok=True)
    database.init_db(db_path(), settings.admin_ids)
    if not settings.admin_ids and not database.has_admins(db_path()):
        logger.warning(
            "ADMIN_ID не задан: администратором станет первый, кто напишет /start. "
            "Укажи ADMIN_ID в .env, чтобы закрепить админа."
        )

    application = build_application()
    logger.info("Запуск long polling")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
