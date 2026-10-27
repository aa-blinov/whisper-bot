"""Проверки «это админ?» и аккуратные ответы на нажатия."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.bot import deps, texts

logger = logging.getLogger(__name__)


def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    return deps.access(context).is_admin(user.id if user else None)


def deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True, если это не админ и обработчик должен остановиться."""
    return not is_admin(update, context)


async def answer(query, text: str | None = None, alert: bool = False) -> None:
    """Ответить на нажатие, не падая на повторном или устаревшем запросе."""
    try:
        await query.answer(text or None, show_alert=alert)
    except Exception as exc:
        logger.debug("callback уже отвечен: %s", exc)


async def say_not_admin(update: Update) -> None:
    if update.callback_query:
        await answer(update.callback_query, texts.CALLBACK_NOT_ADMIN, alert=True)
        return
    if update.effective_message:
        await update.effective_message.reply_text(texts.NOT_ADMIN)
