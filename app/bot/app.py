"""Сборка Telegram-приложения: обработчики, сервисы, меню команд."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from telegram import BotCommand, InputProfilePhotoStatic, Update
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


async def _update_profile(bot) -> None:
    """Имя, описание и аватар бота. Аватар грузим, только если его ещё нет."""
    try:
        await bot.set_my_commands(WELCOME_COMMANDS)
        await bot.set_my_name(BOT_NAME)
        await bot.set_my_description(DESCRIPTION)
        await bot.set_my_short_description(SHORT_DESCRIPTION)
    except Exception as exc:
        logger.warning("Не удалось обновить профиль бота: %s", exc)

    if not AVATAR_PATH.exists():
        return
    force = os.getenv("BOT_PROFILE_FORCE", "").strip() in ("1", "true", "yes")
    try:
        if not force:
            photos = await bot.get_user_profile_photos(bot.id, limit=1)
            if photos.total_count:
                return
        await bot.set_my_profile_photo(
            InputProfilePhotoStatic(photo=str(AVATAR_PATH))
        )
        logger.info("Аватар бота обновлён из %s", AVATAR_PATH)
    except Exception as exc:
        logger.warning("Не удалось обновить аватар бота: %s", exc)


async def post_init(application) -> None:
    """Профиль бота в Telegram: команды, имя, описание, аватар."""
    await _update_profile(application.bot)
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
