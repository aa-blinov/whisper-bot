"""Сборка Telegram-приложения: обработчики, сервисы, меню команд."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    Defaults,
    MessageHandler,
    filters,
)

from app.bot import keyboards
from app.bot.handlers import admin
from app.bot.handlers import common, language, media
from app.bot.handlers.requests import access_decision
from app.config import Settings
from app.container import Services

logger = logging.getLogger(__name__)

AVATAR_PATH = Path(__file__).resolve().parent.parent / "assets" / "bot_avatar.png"
READY_FILE = os.getenv("BOT_READY_FILE", "/tmp/bot-ready")

BOT_NAME = "Lazy to Text"
DESCRIPTION = (
    "Пришли голосовое сообщение или видео-кружок, и я верну текст с пунктуацией. "
    "Речь распознаётся на своём сервере: ни облака, ни подписок, ни отправки записей на сторону."
)
SHORT_DESCRIPTION = "Голосовые и видео-кружки в текст, с пунктуацией. Всё на своём сервере."
WELCOME_COMMANDS = [
    BotCommand("start", "Начать"),
    BotCommand("language", "Язык распознавания"),
    BotCommand("admin", "Панель администратора"),
    BotCommand("help", "Справка"),
]


async def _upload_avatar(bot, path: Path) -> None:
    """Залить картинку в профиль бота.

    `Bot.set_my_profile_photo` в PTB 22.8 принимает только `file_id` или
    ссылку: файл в этом методе он не умеет отправлять. Поэтому тот же
    запрос, что делает Bot API для загрузки, отправляем сами.
    """
    url = f"{bot.base_url}/setMyProfilePhoto"
    async with httpx.AsyncClient(timeout=60) as client:
        with open(path, "rb") as handle:
            response = await client.post(
                url,
                data={"photo": '{"type":"static","photo":"attach://avatar"}'},
                files={"avatar": (path.name, handle, "image/png")},
            )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", "setMyProfilePhoto failed"))


async def _sync_text(bot, getter, setter, value: str, label: str, attr: str) -> None:
    """Записать поле профиля, только если оно отличается.

    Telegram ограничивает частоту смены имени и описания: жёсткий вызов
    set_my_name на каждом старте упирается в Flood control на сутки. Поэтому
    сначала читаем, потом, если нужно, пишем. Геттеры Bot API возвращают
    объекты (`BotName`, `BotDescription`), значение лежит в поле.
    """
    try:
        result = await getter()
        current = getattr(result, attr, result)
    except Exception as exc:
        logger.debug("Не удалось прочитать %s: %s", label, exc)
        current = None
    if isinstance(current, str) and current == value:
        return
    try:
        await setter(value)
    except Exception as exc:
        logger.warning("Не удалось обновить %s: %s", label, exc)


async def _update_profile(bot) -> None:
    """Имя, описание и аватар бота. Аватар грузим, только если его ещё нет."""
    try:
        await bot.set_my_commands(WELCOME_COMMANDS)
    except Exception as exc:
        logger.warning("Не удалось обновить меню команд: %s", exc)

    await _sync_text(
        bot,
        bot.get_my_name,
        lambda value: bot.set_my_name(name=value),
        BOT_NAME,
        "имя",
        "name",
    )
    await _sync_text(
        bot,
        bot.get_my_description,
        lambda value: bot.set_my_description(description=value),
        DESCRIPTION,
        "описание",
        "description",
    )
    await _sync_text(
        bot,
        bot.get_my_short_description,
        lambda value: bot.set_my_short_description(short_description=value),
        SHORT_DESCRIPTION,
        "короткое описание",
        "short_description",
    )

    if not AVATAR_PATH.exists():
        return
    force = os.getenv("BOT_PROFILE_FORCE", "").strip() in ("1", "true", "yes")
    try:
        if not force:
            photos = await bot.get_user_profile_photos(bot.id, limit=1)
            if photos.total_count:
                return
        await _upload_avatar(bot, AVATAR_PATH)
        logger.info("Аватар бота обновлён из %s", AVATAR_PATH)
    except Exception as exc:
        logger.warning("Не удалось обновить аватар бота: %s", exc)


async def post_init(application) -> None:
    """Профиль бота в Telegram: команды, имя, описание, аватар."""
    await _update_profile(application.bot)
    # Файл готовности читает healthcheck в compose: он появляется, когда
    # приложение собрано и профиль обновлён, до старта long polling.
    try:
        Path(READY_FILE).write_text("ready\n", encoding="utf-8")
    except OSError as exc:
        logger.debug("Не удалось записать %s: %s", READY_FILE, exc)
    logger.info("Бот запущен: @%s", application.bot.username)


def build_application(settings: Settings, services: Services):
    """Собрать приложение и положить сервисы в `bot_data`."""
    application = (
        ApplicationBuilder()
        .token(settings.token)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .concurrent_updates(4)
        .post_init(post_init)
        .build()
    )

    application.bot_data["settings"] = settings
    application.bot_data["access"] = services.access
    application.bot_data["stats"] = services.stats
    application.bot_data["transcription"] = services.transcription
    application.bot_data["media"] = services.media

    private = filters.ChatType.PRIVATE

    for handler in admin.build_handlers():
        application.add_handler(handler)

    application.add_handler(
        CommandHandler("start", common.start, filters=private)
    )
    application.add_handler(
        CommandHandler("help", common.help_command, filters=private)
    )
    application.add_handler(
        CommandHandler("language", language.language_menu, filters=private)
    )
    application.add_handler(CommandHandler("cancel", common.cancel, filters=private))

    application.add_handler(
        MessageHandler(
            private & filters.Regex(rf"^{keyboards.BTN_LANGUAGE}$"), language.language_menu
        )
    )
    application.add_handler(
        MessageHandler(
            private & filters.Regex(rf"^({keyboards.BTN_RU}|{keyboards.BTN_EN})"),
            language.language_choice,
        )
    )
    application.add_handler(
        MessageHandler(private & filters.Regex(rf"^{keyboards.BTN_CANCEL}$"), common.cancel)
    )
    application.add_handler(
        MessageHandler(private & (filters.VOICE | filters.VIDEO_NOTE), media.handle_media)
    )
    application.add_handler(
        MessageHandler(private & filters.TEXT & ~filters.COMMAND, common.fallback)
    )
    application.add_handler(
        CallbackQueryHandler(access_decision, pattern=r"^req:\d+:(allow|deny)$")
    )
    application.add_error_handler(common.on_error)
    return application
