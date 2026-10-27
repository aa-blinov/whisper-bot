"""Выбор языка распознавания."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot import deps, keyboards, texts
from app.bot.handlers.guards import is_admin


async def language_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return
    current = deps.access(context).language(user.id)
    await message.reply_text(
        texts.LANGUAGE_MENU, reply_markup=keyboards.language_menu(current)
    )


def detect_language(text: str) -> str | None:
    """Понять выбранный язык по подписи кнопки."""
    stripped = text.strip()
    if keyboards.BTN_RU in stripped or stripped.lower().startswith("рус"):
        return "ru"
    if keyboards.BTN_EN in stripped or stripped.lower().startswith("англ"):
        return "en"
    return None


async def language_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return

    language = detect_language(message.text)
    if language is None:
        await language_menu(update, context)
        return

    deps.access(context).set_language(user.id, language)
    note = texts.LANGUAGE_EN_NOTE if language == "en" else ""
    await message.reply_text(
        texts.language_set(keyboards.LANGUAGE_NAMES[language], note),
        reply_markup=keyboards.main_menu(is_admin(update, context)),
    )
