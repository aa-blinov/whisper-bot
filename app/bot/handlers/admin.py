"""Админ-панель: список людей, выдача и закрытие доступа, статистика.

Добавить человека можно тремя способами, и все три ведут к одной карточке
с кнопкой подтверждения: номер, `@username` или пересланное сообщение, из
которого берутся номер и имя.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from telegram import Message, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.bot import deps, keyboards, texts
from app.bot.formatting import escape
from app.bot.handlers.guards import answer, deny, is_admin, say_not_admin
from app.domain import User

logger = logging.getLogger(__name__)

WAITING_USER = 1

USERNAME_RE = re.compile(r"^(?:@|https?://t\.me/)([A-Za-z0-9_]{4,32})/?$")


def menu_for(context: ContextTypes.DEFAULT_TYPE, user_id: int | None):
    return keyboards.main_menu(deps.access(context).is_admin(user_id))


# --- панель и список ------------------------------------------------------


async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if deny(update, context):
        await say_not_admin(update)
        return

    access = deps.access(context)
    user = update.effective_user
    total = access.count()

    if update.callback_query:
        await answer(update.callback_query)
        await update.callback_query.edit_message_text(
            texts.panel(total),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.admin_home(total),
        )
        return

    message = update.effective_message
    if message is None:
        return
    # Ответную клавиатуру показываем один раз за сессию, дальше всё
    # делается inline-кнопками, чтобы не дублировать меню.
    if not context.user_data.get("admin_menu_sent"):
        await message.reply_text(
            texts.MENU_READY, reply_markup=menu_for(context, user.id if user else None)
        )
        context.user_data["admin_menu_sent"] = True
    await message.reply_text(
        texts.panel(total),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.admin_home(total),
    )


async def show_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if deny(update, context):
        await say_not_admin(update)
        return

    users = deps.access(context).all()
    text = texts.users_list(users) if users else texts.USERS_EMPTY
    markup = keyboards.users_list(users) if users else keyboards.back_home()

    if update.callback_query:
        await answer(update.callback_query)
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )


async def user_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if deny(update, context):
        await answer(query, texts.CALLBACK_NOT_ADMIN, alert=True)
        return

    user_id = int(query.data.split(":")[1])
    user = deps.access(context).get(user_id)
    if user is None:
        await answer(query, texts.ALERT_NO_USER_LIST, alert=True)
        await show_users(update, context)
        return

    await answer(query)
    await query.edit_message_text(
        texts.user_card(
            user, keyboards.LANGUAGE_NAMES.get(user.language, "русский")
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.user_card(user),
    )


async def user_confirm_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if deny(update, context):
        await answer(query, texts.CALLBACK_NOT_ADMIN, alert=True)
        return

    user_id = int(query.data.split(":")[1])
    access = deps.access(context)
    user = access.get(user_id)
    if user is None:
        await answer(query, texts.ALERT_NO_USER, alert=True)
        return
    if user_id in deps.settings(context).admin_ids:
        await answer(query, texts.ALERT_ENV_ADMIN, alert=True)
        return

    await answer(query)
    await query.edit_message_text(
        texts.confirm_remove(user.display_name),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.confirm_remove(user),
    )


async def user_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if deny(update, context):
        await answer(query, texts.CALLBACK_NOT_ADMIN, alert=True)
        return

    user_id = int(query.data.split(":")[1])
    access = deps.access(context)
    user = access.get(user_id) or User(user_id=user_id)
    removed = access.revoke(user_id)
    await answer(query, texts.ALERT_REVOKED if removed else texts.ALERT_NOTHING_TO_REVOKE)

    try:
        await context.bot.send_message(chat_id=user_id, text=texts.ACCESS_REVOKED)
    except Exception as exc:
        logger.info("Не удалось уведомить %s о закрытии доступа: %s", user_id, exc)

    users = access.all()
    await query.edit_message_text(
        texts.users_list(users) if users else texts.USERS_EMPTY,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.users_list(users) if users else keyboards.back_home(),
    )
    logger.info("Админ закрыл доступ %s (%s)", user_id, user.display_name)


# --- добавление -----------------------------------------------------------


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало добавления: просим номер, @username или пересланное сообщение."""
    if deny(update, context):
        await say_not_admin(update)
        return ConversationHandler.END

    context.user_data["admin_action"] = "add"
    if update.callback_query:
        await answer(update.callback_query)
        await update.callback_query.edit_message_text(
            texts.ADD_PROMPT, parse_mode=ParseMode.HTML
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            texts.ADD_PROMPT,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.cancel_menu(),
        )
    return WAITING_USER


async def resolve_username(
    context: ContextTypes.DEFAULT_TYPE, username: str
) -> dict | None:
    try:
        chat = await context.bot.get_chat(f"@{username}")
    except Exception as exc:
        logger.info("Не удалось найти @%s: %s", username, exc)
        return None
    return {
        "user_id": chat.id,
        "first_name": chat.first_name or "",
        "last_name": chat.last_name or "",
        "username": chat.username or username,
    }


def from_forward(message: Message) -> dict | None:
    """Профиль человека из пересланного сообщения."""
    origin = getattr(message, "forward_origin", None)
    sender = getattr(origin, "sender_user", None) if origin else None
    if sender is None:
        return None
    return {
        "user_id": sender.id,
        "first_name": sender.first_name or "",
        "last_name": sender.last_name or "",
        "username": sender.username or "",
    }


async def _candidate_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> dict | None:
    candidate = from_forward(update.effective_message)
    if candidate is None and text.isdigit():
        user_id = int(text)
        try:
            chat = await context.bot.get_chat(user_id)
            candidate = {
                "user_id": chat.id,
                "first_name": chat.first_name or "",
                "last_name": chat.last_name or "",
                "username": chat.username or "",
            }
        except Exception:
            candidate = {"user_id": user_id, "first_name": "", "last_name": "", "username": ""}
    if candidate is None:
        match = USERNAME_RE.match(text)
        if match:
            candidate = await resolve_username(context, match.group(1))
    return candidate


async def add_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Разобрать ответ админа и показать карточку подтверждения."""
    message = update.effective_message
    if not message:
        return WAITING_USER
    if deny(update, context):
        await say_not_admin(update)
        return ConversationHandler.END

    text = (message.text or "").strip()
    if text in (keyboards.BTN_CANCEL, "/cancel"):
        await message.reply_text(
            texts.ADD_CANCELLED,
            reply_markup=menu_for(context, update.effective_user.id),
        )
        return ConversationHandler.END

    candidate = await _candidate_from_message(update, context, text)
    if candidate is None:
        await message.reply_text(texts.ADD_UNCLEAR, reply_markup=keyboards.cancel_menu())
        return WAITING_USER

    user_id = candidate["user_id"]
    existing = deps.access(context).get(user_id)
    if existing is not None:
        await message.reply_text(
            texts.add_already(existing.display_name),
            parse_mode=ParseMode.HTML,
            reply_markup=menu_for(context, update.effective_user.id),
        )
        return ConversationHandler.END

    profile = User(
        user_id=user_id,
        first_name=candidate.get("first_name", ""),
        last_name=candidate.get("last_name", ""),
        username=candidate.get("username", ""),
    )
    await message.reply_text(
        texts.add_confirm(profile.display_name, user_id),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.confirm_add(user_id, escape(profile.display_name)),
    )
    context.user_data["pending_user"] = candidate
    return ConversationHandler.END


async def add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение добавления по inline-кнопке."""
    query = update.callback_query
    if not query:
        return
    if deny(update, context):
        await answer(query, texts.CALLBACK_NOT_ADMIN, alert=True)
        return

    user_id = int(query.data.split(":")[1])
    access = deps.access(context)
    pending = context.user_data.pop("pending_user", None) or {}
    if pending.get("user_id") != user_id:
        current = access.get(user_id)
        pending = (
            {
                "first_name": current.first_name,
                "last_name": current.last_name,
                "username": current.username,
            }
            if current
            else {}
        )

    access.grant(
        user_id,
        first_name=pending.get("first_name", ""),
        last_name=pending.get("last_name", ""),
        username=pending.get("username", ""),
    )
    user = access.get(user_id) or User(user_id=user_id)
    name = user.display_name

    await answer(query, texts.ALERT_GRANTED)
    await query.edit_message_text(
        texts.added(name, user_id),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.back_home(),
    )
    try:
        await context.bot.send_message(
            chat_id=user_id, text=texts.WELCOME_NEW, reply_markup=keyboards.user_menu()
        )
    except Exception as exc:
        logger.info("Пользователь %s не получил приветствие: %s", user_id, exc)
        await context.bot.send_message(
            chat_id=query.from_user.id, text=texts.WELCOME_FAILED
        )
    logger.info("Админ выдал доступ %s (%s)", user_id, name)


# --- приглашение и статистика --------------------------------------------


async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ссылка на бота, которую админ пересылает сам."""
    if deny(update, context):
        await say_not_admin(update)
        return
    username = context.bot.username
    link = f"https://t.me/{username}" if username else "ссылку получить не вышло"
    text = texts.invite(link)

    if update.callback_query:
        await answer(update.callback_query)
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboards.back_home()
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboards.back_home()
        )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if deny(update, context):
        await say_not_admin(update)
        return
    settings = deps.settings(context)
    text = texts.stats(
        deps.stats(context).overview(),
        datetime.now().strftime("%d.%m.%Y"),
        settings.asr_model,
        settings.asr_quantization or "fp32",
    )
    if update.callback_query:
        await answer(update.callback_query)
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboards.back_home()
        )
    elif update.effective_message:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message:
        await update.effective_message.reply_text(
            texts.ADD_CANCELLED,
            reply_markup=menu_for(
                context, update.effective_user.id if update.effective_user else None
            ),
        )
    return ConversationHandler.END


def _private_only(callback):
    """Админская часть работает только в личном чате.

    Иначе `/admin` в группе выкладывает туда список людей с их ID, а
    кнопки панели правят это сообщение на глазах у всей группы.
    """

    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if chat is None or chat.type != ChatType.PRIVATE:
            if update.callback_query:
                await update.callback_query.answer()
            return ConversationHandler.END
        return await callback(update, context)

    return wrapper


def _guard(handler):
    """Обернуть обработчик и все его состояния проверкой типа чата."""
    if isinstance(handler, ConversationHandler):
        for group in [handler.entry_points, *handler.states.values(), handler.fallbacks]:
            for inner in group:
                _guard(inner)
        return handler
    callback = getattr(handler, "callback", None)
    if callback is not None:
        handler.callback = _private_only(callback)
    return handler


def build_handlers() -> list:
    """Обработчики админской части, в порядке регистрации."""
    add_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_start, pattern=r"^admin:add$"),
            CommandHandler("add_user", add_start),
            MessageHandler(filters.Regex(rf"^{re.escape(keyboards.BTN_ADD)}$"), add_start),
        ],
        states={
            WAITING_USER: [
                MessageHandler(filters.ALL & ~filters.COMMAND, add_receive),
                CommandHandler("cancel", cmd_cancel),
            ]
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    return [
        _guard(handler)
        for handler in [
            add_conversation,
            CommandHandler(["admin", "admin_menu", "panel"], panel),
            CommandHandler("list_users", show_users),
            CommandHandler("users", show_users),
            CommandHandler("remove_user", show_users),
            CommandHandler("invite", invite),
            CommandHandler("stats", stats),
            CallbackQueryHandler(panel, pattern=r"^admin:home$"),
            CallbackQueryHandler(show_users, pattern=r"^admin:list$"),
            CallbackQueryHandler(stats, pattern=r"^admin:stats$"),
            CallbackQueryHandler(invite, pattern=r"^admin:invite$"),
            CallbackQueryHandler(add_confirm, pattern=r"^add:\d+$"),
            CallbackQueryHandler(user_remove, pattern=r"^user:\d+:del:yes$"),
            CallbackQueryHandler(user_confirm_remove, pattern=r"^user:\d+:del$"),
            CallbackQueryHandler(user_card, pattern=r"^user:\d+$"),
            MessageHandler(filters.Regex(rf"^{re.escape(keyboards.BTN_ADMIN)}$"), panel),
            MessageHandler(filters.Regex(rf"^{re.escape(keyboards.BTN_USERS)}$"), show_users),
            MessageHandler(filters.Regex(rf"^{re.escape(keyboards.BTN_STATS)}$"), stats),
            MessageHandler(filters.Regex(rf"^{re.escape(keyboards.BTN_INVITE)}$"), invite),
        ]
    ]
