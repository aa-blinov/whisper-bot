"""Заявки на доступ: карточка админу и решение одной кнопкой."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.bot import deps, keyboards, texts
from app.bot.handlers.guards import answer, is_admin

logger = logging.getLogger(__name__)


async def notify_admins(
    context: ContextTypes.DEFAULT_TYPE, text: str, markup=None
) -> None:
    for admin_id in deps.access(context).admins():
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logger.warning("Не удалось написать админу %s: %s", admin_id, exc)


async def notify_access_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать админам карточку с кнопками «Разрешить» и «Отклонить»."""
    user = update.effective_user
    if user is None:
        return
    await notify_admins(
        context,
        texts.access_request(user.id, user.full_name or str(user.id), user.username),
        keyboards.access_request(user.id),
    )


async def access_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Разрешить или отклонить заявку одной кнопкой."""
    query = update.callback_query
    if not query:
        return
    if not is_admin(update, context):
        await answer(query, texts.CALLBACK_NOT_ADMIN, alert=True)
        return

    _, raw_id, action = query.data.split(":")
    user_id = int(raw_id)
    service = deps.access(context)

    if action == "allow":
        await _allow(context, user_id)
        await answer(query, texts.ALERT_GRANTED)
        await query.edit_message_text(
            texts.access_granted(user_id), parse_mode=ParseMode.HTML
        )
        try:
            await context.bot.send_message(
                chat_id=user_id, text=texts.WELCOME_NEW, reply_markup=keyboards.user_menu()
            )
        except Exception as exc:
            logger.info("Не удалось написать %s: %s", user_id, exc)
        return

    await answer(query, texts.ALERT_DENIED)
    await query.edit_message_text(texts.access_denied(user_id), parse_mode=ParseMode.HTML)
    try:
        await context.bot.send_message(chat_id=user_id, text=texts.ACCESS_REFUSED)
    except Exception:
        pass


async def _allow(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Выдать доступ, подтянув профиль из Telegram, если он доступен."""
    first_name = last_name = username = ""
    try:
        chat = await context.bot.get_chat(user_id)
        first_name = chat.first_name or ""
        last_name = chat.last_name or ""
        username = chat.username or ""
    except Exception:
        pass
    deps.access(context).grant(
        user_id, first_name=first_name, last_name=last_name, username=username
    )
